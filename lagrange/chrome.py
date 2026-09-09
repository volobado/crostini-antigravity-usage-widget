"""
Window shaping: rounded corners for a borderless Tk window.

Tk draws rectangles and nothing else, so the roundness has to come from the
platform, and the two platforms this widget runs on offer it two different
ways.

Windows: two mechanisms exist and neither covers the whole job on its own.

  * DWM's corner preference (Windows 11 build 22000+) rounds and anti-aliases
    the frame, but it only applies to windows DWM frames — an `overrideredirect`
    window often is not one, and the call then succeeds while changing nothing.
  * A window region (`SetWindowRgn`) clips the window to any shape at all, on
    every Windows version, at the cost of hard pixel edges.

So both are asked for, in that order, and the region is what actually
guarantees the shape.

Linux/X11: there is no per-window "please round me" compositor protocol an
unmanaged (override-redirect) window can rely on across window managers, so
only the region-equivalent exists here — the X Shape extension
(`XShapeCombineRectangles`), which clips a window to an arbitrary set of
rectangles. Same hard-pixel-edge trade-off as the Windows region fallback, by
the same reasoning: nobody is anti-aliasing this for us.

Either way, the region is tied to the window's size, which changes every time
the widget re-renders, so `round_window` is called after each fit.
"""

from __future__ import annotations

import sys

DEFAULT_RADIUS = 16

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    try:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        _dwmapi = ctypes.WinDLL("dwmapi")
    except (OSError, AttributeError):  # not actually Windows — every call no-ops
        _user32 = _gdi32 = _dwmapi = None
    else:
        # Handles are 64-bit; without explicit prototypes ctypes truncates them to
        # an int and the region silently belongs to nobody.
        _gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
        _gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        _gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        _user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        _user32.SetWindowRgn.restype = ctypes.c_int
        _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        _user32.GetAncestor.restype = wintypes.HWND
        _dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                                  ctypes.c_void_p, wintypes.DWORD]

    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWCP_ROUND = 2

    GA_ROOT = 2

    def top_level(handle: int) -> int:
        """
        The real window behind a Tk widget id.

        `winfo_id()` hands back the child window Tk draws into, not the frame
        Windows manages — shaping that one changes nothing anybody can see, and
        the call still reports success. Everything here has to walk up to the
        root first.
        """
        if not _user32 or not handle:
            return handle
        root = _user32.GetAncestor(wintypes.HWND(handle), GA_ROOT)
        return int(root) if root else handle

    def prefer_round_corners(hwnd: int) -> bool:
        """Ask DWM for rounded corners. False when the OS has no such preference."""
        if not _dwmapi or not hwnd:
            return False
        value = ctypes.c_int(DWMWCP_ROUND)
        try:
            result = _dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(top_level(hwnd)), DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(value), ctypes.sizeof(value))
        except OSError:
            return False
        return result == 0

    def round_window(hwnd: int, width: int, height: int, radius: int = DEFAULT_RADIUS) -> bool:
        """
        Clip the window to a rounded rectangle.

        Safe to call on every resize: Windows takes ownership of the region handle
        passed in, so the previous one is released with the window, and a failed
        call leaves the window as it was rather than blanking it.
        """
        if not _user32 or not hwnd or width < 2 * radius or height < 2 * radius:
            return False
        # +1 on both extents: CreateRoundRectRgn treats the bottom-right corner as
        # exclusive, and without it the last row and column are clipped away.
        region = _gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius, radius)
        if not region:
            return False
        if not _user32.SetWindowRgn(wintypes.HWND(top_level(hwnd)), region, True):
            _gdi32.DeleteObject(region)
            return False
        return True

    def unround_window(hwnd: int) -> None:
        """Drop any region, restoring the plain rectangle."""
        if _user32 and hwnd:
            _user32.SetWindowRgn(wintypes.HWND(top_level(hwnd)), None, True)

elif sys.platform not in ("darwin",):
    # Linux and the BSDs: Tk only has an X11 backend, so this is safe whenever
    # it isn't Windows or macOS (whose Tk build this widget was never fit for
    # in the first place — the borderless-window mechanics differ there too).
    import ctypes

    from . import _x11

    _xext: ctypes.CDLL | None = None
    _xext_tried = False

    # <X11/extensions/shape.h>
    _SHAPE_BOUNDING = 0
    _SHAPE_SET = 0

    class _XRectangle(ctypes.Structure):
        _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short),
                    ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]

    def _ext() -> ctypes.CDLL | None:
        global _xext, _xext_tried
        if _xext_tried:
            return _xext
        _xext_tried = True
        lib = _x11.load("libXext.so.6")
        if not lib:
            return None
        dpy_t = ctypes.c_void_p
        lib.XShapeCombineRectangles.argtypes = [
            dpy_t, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(_XRectangle), ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.XShapeCombineMask.argtypes = [
            dpy_t, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_ulong, ctypes.c_int]
        _xext = lib
        return _xext

    def top_level(handle: int) -> int:
        """
        Walk up to the outermost window below the root window.
        Tk wraps its toplevel inside an outer X11 window even for override-redirect.
        """
        lib, dpy = _x11.libx11(), _x11.display()
        if not lib or not dpy or not handle:
            return handle
        current = handle
        root_ret = ctypes.c_ulong()
        parent_ret = ctypes.c_ulong()
        children_ret = ctypes.POINTER(ctypes.c_ulong)()
        nchildren_ret = ctypes.c_uint()
        while True:
            res = lib.XQueryTree(dpy, current, ctypes.byref(root_ret),
                                 ctypes.byref(parent_ret),
                                 ctypes.byref(children_ret),
                                 ctypes.byref(nchildren_ret))
            if not res or not parent_ret.value or parent_ret.value == root_ret.value:
                break
            current = parent_ret.value
        return current

    def prefer_round_corners(hwnd: int) -> bool:
        """
        No equivalent of DWM's corner preference exists for an unmanaged X11
        window: anti-aliased rounding is a compositor's job, and there is no
        cross-desktop protocol asking one to do it for a window it does not
        manage. The hard-edged region from `round_window` is the whole story.
        """
        return False

    def round_window(hwnd: int, width: int, height: int, radius: int = DEFAULT_RADIUS) -> bool:
        """Clip the window to a rounded rectangle via the X Shape extension."""
        lib = _ext()
        dpy = _x11.display()
        if not lib or not dpy or not hwnd or width < 2 * radius or height < 2 * radius:
            return False
        radius = max(0, radius)
        rects: list[_XRectangle] = []
        for y in range(height):
            if y < radius:
                dy = radius - y
            elif y >= height - radius:
                dy = radius - (height - 1 - y)
            else:
                dy = 0
            dx = 0
            if 0 < dy <= radius:
                dx = radius - int((radius * radius - dy * dy) ** 0.5)
            rects.append(_XRectangle(dx, y, max(0, width - 2 * dx), 1))
        array = (_XRectangle * len(rects))(*rects)
        targets = {hwnd, top_level(hwnd)}
        for win in targets:
            lib.XShapeCombineRectangles(dpy, win, _SHAPE_BOUNDING, 0, 0,
                                        array, len(rects), _SHAPE_SET, 0)
        _x11.flush()
        return True

    def unround_window(hwnd: int) -> None:
        """Drop any region, restoring the plain rectangle."""
        lib = _ext()
        dpy = _x11.display()
        if lib and dpy and hwnd:
            targets = {hwnd, top_level(hwnd)}
            for win in targets:
                lib.XShapeCombineMask(dpy, win, _SHAPE_BOUNDING, 0, 0, 0, _SHAPE_SET)
            _x11.flush()

else:
    def top_level(handle: int) -> int:
        return handle

    def prefer_round_corners(hwnd: int) -> bool:
        return False

    def round_window(hwnd: int, width: int, height: int, radius: int = DEFAULT_RADIUS) -> bool:
        return False

    def unround_window(hwnd: int) -> None:
        return None
