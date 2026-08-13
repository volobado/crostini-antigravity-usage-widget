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
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)

MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTONEAREST = 2


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


_user32.MonitorFromRect.restype = wintypes.HMONITOR
_user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]


def work_area(x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
    """The usable area of the monitor nearest that rectangle, taskbar excluded."""
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
    try:
        rect = wintypes.RECT(x, y, x + width, y + height)
        if _user32.MonitorFromRect(ctypes.byref(rect), MONITOR_DEFAULTTONULL):
            return x, y  # something shows at least part of it

        left, top, right, bottom = work_area(x, y, width, height)
    except OSError:
        return x, y  # never move the window on the strength of a failed call

    return (max(left + margin, min(x, right - width - margin)),
            max(top + margin, min(y, bottom - height - margin)))
