"""
Keeping the window somewhere a person can actually see it.

A saved position outlives the screen it was saved on: a monitor is unplugged, a
remote session opens with a different desktop size, the display arrangement
changes. The window then opens exactly where it was told to — off the edge of
every monitor — and looks, from the desk, like an application that starts and
shows nothing.

So the position is checked against the monitors that exist right now, and moved
only when it belongs to none of them. Hanging half off an edge is a choice
somebody made by dragging, and is left alone.

Growing off an edge is not that choice. When the widget changes its own size —
leaving compact mode is the big one, a 224-pixel card becoming a metre of
accounts — nobody dragged anything, and the part that no longer fits was never
positioned by a person. `fit` covers that case by pulling the whole rectangle
back inside the work area; `on_screen` still covers the saved-position one.
"""

from __future__ import annotations

try:
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
except (OSError, AttributeError):
    _user32 = None

MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTONEAREST = 2

if _user32:
    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    _user32.MonitorFromRect.restype = wintypes.HMONITOR
    _user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]


def work_area(x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
    """The usable area of the monitor nearest that rectangle, taskbar excluded."""
    if not _user32:
        try:
            import tkinter as tk
            root = getattr(tk, "_default_root", None)
            if root:
                return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
        except Exception:
            pass
        return 0, 0, 1920, 1080
    rect = wintypes.RECT(x, y, x + width, y + height)
    monitor = _user32.MonitorFromRect(ctypes.byref(rect), MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not monitor or not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise OSError("no monitor information")
    area = info.rcWork
    return area.left, area.top, area.right, area.bottom


def on_screen(x: int, y: int, width: int, height: int,
              margin: int = 24) -> tuple[int, int]:
    """
    The same position, unless no monitor shows any part of the window.

    Coordinates come from the calling process, and so do the monitor rectangles,
    which keeps the two comparable whatever the display scaling does to them.
    """
    if not _user32:
        try:
            left, top, right, bottom = work_area(x, y, width, height)
            if x + width < left + margin or x > right - margin or y + height < top + margin or y > bottom - margin:
                return (max(left + margin, min(x, right - width - margin)),
                        max(top + margin, min(y, bottom - height - margin)))
        except Exception:
            pass
        return x, y
    try:
        rect = wintypes.RECT(x, y, x + width, y + height)
        if _user32.MonitorFromRect(ctypes.byref(rect), MONITOR_DEFAULTTONULL):
            return x, y  # something shows at least part of it

        left, top, right, bottom = work_area(x, y, width, height)
    except OSError:
        return x, y  # never move the window on the strength of a failed call

    return (max(left + margin, min(x, right - width - margin)),
            max(top + margin, min(y, bottom - height - margin)))


def anchored(x: int, y: int, old_width: int, old_height: int,
             width: int, height: int) -> tuple[int, int]:
    """
    Where a window of the new size belongs, given which edges it was parked against.

    A widget resized from its top-left corner grows down and to the right, which
    is exactly wrong for one parked at the bottom of the screen: it grows
    straight off the desk. So the corner that is kept is the one the window is
    already nearest — sitting bottom-right, it grows up and to the left, and the
    bottom-right corner does not move.

    That also makes the change reversible. Going back to the small size keeps
    the same corner, so a compact widget lands exactly where it was left rather
    than drifting a little further every time it is opened and closed.
    """
    try:
        left, top, right, bottom = work_area(x, y, old_width or width,
                                             old_height or height)
    except OSError:
        return x, y

    if right - (x + old_width) < x - left:   # nearer the right edge
        x += old_width - width
    if bottom - (y + old_height) < y - top:  # nearer the bottom edge
        y += old_height - height
    return x, y


def fit(x: int, y: int, width: int, height: int, margin: int = 4) -> tuple[int, int]:
    """
    The nearest position where the whole window is inside the work area.

    Used when the widget resizes itself: what used to fit at this corner may not
    any more, and the overhang is nobody's decision. The window is nudged along
    whichever axes overflow and left alone on the others, so a widget parked
    against the right edge stays against the right edge — it just stops
    disappearing past it.

    A window taller than the work area cannot be made to fit; it is aligned to
    the top instead, where its own title bar and first account are, rather than
    to the bottom, where the least useful part is.
    """
    try:
        left, top, right, bottom = work_area(x, y, width, height)
    except OSError:
        return x, y  # never move the window on the strength of a failed call

    fitted_x = min(x, right - width - margin)
    fitted_x = max(fitted_x, left + margin)
    if width > right - left - 2 * margin:
        fitted_x = left + margin

    fitted_y = min(y, bottom - height - margin)
    fitted_y = max(fitted_y, top + margin)
    if height > bottom - top - 2 * margin:
        fitted_y = top + margin

    return fitted_x, fitted_y
