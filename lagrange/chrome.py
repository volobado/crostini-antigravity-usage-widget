"""
Window shaping: rounded corners for a borderless Tk window.

Tk draws rectangles and nothing else, so the roundness has to come from
Windows. Two mechanisms exist and neither covers the whole job on its own:

  * DWM's corner preference (Windows 11 build 22000+) rounds and anti-aliases
    the frame, but it only applies to windows DWM frames — an `overrideredirect`
    window often is not one, and the call then succeeds while changing nothing.
  * A window region (`SetWindowRgn`) clips the window to any shape at all, on
    every Windows version, at the cost of hard pixel edges.

So both are asked for, in that order, and the region is what actually
guarantees the shape. The region is tied to the window's size, which changes
every time the widget re-renders, so `round_window` is called after each fit.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi")
except (OSError, AttributeError):  # not Windows — every call below no-ops
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

DEFAULT_RADIUS = 16


def top_level(handle: int) -> int:
    """
    The real window behind a Tk widget id.

    `winfo_id()` hands back the child window Tk draws into, not the frame
    Windows manages — shaping that one changes nothing anybody can see, and the
    call still reports success. Everything here has to walk up to the root
    first.
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
