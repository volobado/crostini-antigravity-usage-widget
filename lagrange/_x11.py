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


_ANY_PROPERTY_TYPE = 0
_property_prototypes_set = False


def _ensure_property_prototypes(lib: ctypes.CDLL) -> None:
    """
    Full prototypes, not left to ctypes' default guesses.

    `hasattr(lib, name)` is not a "have I configured this yet" check — ctypes
    resolves and caches *any* valid symbol name on first touch regardless of
    whether `.argtypes` was ever set on it, so that check would always be
    true and this would silently never run. A `Display *`/`Window`/`Atom`
    argument passed as a bare Python int without a declared `c_void_p` /
    `c_ulong` argtype is exactly the "handle truncated to 32 bits" failure
    tray.py's own prototypes exist to avoid — it happened to come back right
    while testing this, which is not the same as being correct.
    """
    global _property_prototypes_set
    if _property_prototypes_set:
        return
    _property_prototypes_set = True
    lib.XInternAtom.restype = ctypes.c_ulong
    lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.XGetWindowProperty.restype = ctypes.c_int
    lib.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
        ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
    lib.XFree.argtypes = [ctypes.c_void_p]


def _property(window: int, name: str, type_name: str | None) -> bytes | None:
    """Raw bytes of a window property, via the standard `XGetWindowProperty`
    dance — `type_name` narrows the request (e.g. "WINDOW", "UTF8_STRING"),
    or pass None to accept whatever type is there."""
    lib, dpy = libx11(), display()
    if not lib or not dpy:
        return None
    _ensure_property_prototypes(lib)

    property_atom = lib.XInternAtom(dpy, name.encode(), True)
    if not property_atom:
        return None
    type_atom = (lib.XInternAtom(dpy, type_name.encode(), True)
                if type_name else _ANY_PROPERTY_TYPE)
    actual_type = ctypes.c_ulong()
    actual_format = ctypes.c_int()
    nitems = ctypes.c_ulong()
    remaining = ctypes.c_ulong()
    data = ctypes.POINTER(ctypes.c_ubyte)()
    status = lib.XGetWindowProperty(
        dpy, window, property_atom, 0, 1024, False, type_atom,
        ctypes.byref(actual_type), ctypes.byref(actual_format),
        ctypes.byref(nitems), ctypes.byref(remaining), ctypes.byref(data))
    if status != 0 or not data or nitems.value == 0:
        return None
    width = max(1, actual_format.value // 8)
    result = bytes(data[:nitems.value * width])
    lib.XFree(data)
    return result


def is_sommelier() -> bool:
    """
    True specifically under ChromeOS's Crostini container, where the window
    manager identifies itself as "Sommelier" — the one desktop this widget
    knows cannot place a borderless (override-redirect) window where it says
    to, confirmed live rather than assumed (see `ui.BORDERLESS`). Detected
    through the standard EWMH `_NET_SUPPORTING_WM_CHECK` handshake, not
    anything ChromeOS-specific, so a real X11 desktop (GNOME, KDE, XFCE, ...)
    reads as False and keeps the fully borderless look. Fails closed — to
    False, "assume a normal, unaffected desktop" — if the check is
    inconclusive, since a false negative here just forgoes a visual nicety
    while a false positive would misattribute Sommelier's bug to someone
    else's window manager.
    """
    root = root_window()
    if root is None:
        return False
    raw = _property(root, "_NET_SUPPORTING_WM_CHECK", "WINDOW")
    if not raw or len(raw) < 4:
        return False
    wm_window = int.from_bytes(raw[:4], "little")
    if not wm_window:
        return False
    name = (_property(wm_window, "_NET_WM_NAME", "UTF8_STRING")
           or _property(wm_window, "WM_NAME", "STRING"))
    return bool(name) and name.rstrip(b"\x00").decode("utf-8", "replace").strip().lower() == "sommelier"
