"""
Shared X11 connection for the Linux backends of `chrome.py` and `screens.py`.

Both need a live `Display *` — one to shape a window, the other to enumerate
monitors — and there is no reason to open the socket twice. A second
connection would work too (X does not mind), this just avoids it.

Opening a display can fail for reasons that have nothing to do with either
caller (no `DISPLAY`, a Wayland-only session with no XWayland), so failure is
reported once and remembered rather than retried on every call.
"""

from __future__ import annotations

import ctypes

_libx11: ctypes.CDLL | None = None
_display: int | None = None
_attempted = False


def _open() -> None:
    global _libx11, _display, _attempted
    _attempted = True
    try:
        lib = ctypes.CDLL("libX11.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        handle = lib.XOpenDisplay(None)
    except OSError:
        return
    if not handle:
        return
    _libx11 = lib
    _display = handle


def display() -> int | None:
    """The shared `Display *`, or None when there is no X11 to talk to."""
    if not _attempted:
        _open()
    return _display


def libx11() -> ctypes.CDLL | None:
    if not _attempted:
        _open()
    return _libx11


def root_window() -> int | None:
    lib, dpy = libx11(), display()
    if not lib or not dpy:
        return None
    return lib.XDefaultRootWindow(dpy)


def flush() -> None:
    lib, dpy = libx11(), display()
    if lib and dpy:
        lib.XFlush(dpy)


def load(name: str) -> ctypes.CDLL | None:
    """An extension library (Xext, Xrandr, ...), or None if it is not there."""
    if not display():
        return None
    try:
        return ctypes.CDLL(name)
    except OSError:
        return None
