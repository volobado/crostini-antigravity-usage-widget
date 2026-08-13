"""
Notification-area icon, via shell32 — standard library only.

The widget's window is borderless, so Windows gives it no taskbar button: once
it is hidden, the tray is the only way back. The icon is drawn at runtime as a
gauge of the tightest quota window on the active account, so the state stays
readable with the widget closed — which is the point of putting it there.

Windows delivers tray messages to a window, and a window belongs to the thread
that created it, so the window, the message loop and every Shell_NotifyIcon call
live on one dedicated thread. It talks to the widget by putting events on a
queue the Tk loop already drains; nothing here touches Tk.

A tray that fails must not take the widget with it, so every entry point here is
allowed to return False and be ignored.
"""

from __future__ import annotations

import contextlib
import ctypes
import math
import threading
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ─── win32 plumbing ─────────────────────────────────────────────────────────
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_MBUTTONUP = 0x0208
WM_APP = 0x8000
# Sent instead of the raw mouse messages when an icon asks for version 4.
NIN_SELECT = WM_APP + 0
NIN_KEYSELECT = WM_APP + 1
WM_TRAY = WM_APP + 17
WM_TRAY_REDRAW = WM_APP + 18
WM_TRAY_BALLOON = WM_APP + 19

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO = 0x01

MF_STRING, MF_SEPARATOR, MF_CHECKED = 0x0000, 0x0800, 0x0008
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080

CS_HREDRAW, CS_VREDRAW = 0x0002, 0x0001
WS_OVERLAPPED = 0x00000000
SM_CXSMICON = 49
BI_RGB = 0
DIB_RGB_COLORS = 0
ERROR_CLASS_ALREADY_EXISTS = 1410

ID_SHOW, ID_PIN, ID_REFRESH, ID_QUIT = 1, 2, 3, 4

# Live icons, held here so that dropping the last reference to a Tray cannot
# free the window procedure while Windows is still dispatching into it. That
# collection is what an access violation on exit looks like from Python.
_LIVE: set = set()


class _NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class _WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


# Every prototype is spelled out: ctypes assumes a C int return, and a handle
# truncated to 32 bits fails with "int too long to convert" — or worse, works
# until the process is unlucky with its addresses.
_user32.DefWindowProcW.restype = LRESULT
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                    wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
_user32.RegisterClassW.restype = wintypes.ATOM
_user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASS)]
_user32.CreatePopupMenu.restype = wintypes.HMENU
_user32.TrackPopupMenu.restype = wintypes.BOOL
_user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.LPVOID]
_shell32.Shell_NotifyIconW.restype = wintypes.BOOL
_shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATA)]
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(_BITMAPINFO),
                                    wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                    wintypes.HANDLE, wintypes.DWORD]
_user32.CreateIconIndirect.restype = wintypes.HICON
_user32.CreateIconIndirect.argtypes = [ctypes.POINTER(_ICONINFO)]
_gdi32.CreateBitmap.restype = wintypes.HBITMAP
_gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT,
                                wintypes.UINT, wintypes.LPVOID]
_gdi32.DeleteObject.restype = wintypes.BOOL
_gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
_user32.DestroyIcon.restype = wintypes.BOOL
_user32.DestroyIcon.argtypes = [wintypes.HICON]
_user32.CreateMenu.restype = wintypes.HMENU
_user32.AppendMenuW.restype = wintypes.BOOL
_user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                                wintypes.LPCWSTR]
_user32.DestroyMenu.restype = wintypes.BOOL
_user32.DestroyMenu.argtypes = [wintypes.HMENU]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM]
_user32.GetMessageW.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT]
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.restype = LRESULT
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.RegisterWindowMessageW.restype = wintypes.UINT
_user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


# ─── the mark ───────────────────────────────────────────────────────────────
TRACK_RGB = (0x3a, 0x3f, 0x52)
SUPERSAMPLE = 3


def _rgb(value: str | tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(value, tuple):
        return value
    text = value.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def gauge_pixels(size: int, fraction: float, color, track=TRACK_RGB) -> bytes:
    """
    A ring filled clockwise from twelve o'clock — BGRA, top-down.

    Supersampled rather than drawn with GDI: an anti-aliased circle is a few
    lines of arithmetic, and it keeps the mark identical everywhere it is used
    (tray icon, window icon, the .ico built into the executable).
    """
    fill_r, fill_g, fill_b = _rgb(color)
    track_r, track_g, track_b = _rgb(track)
    fraction = max(0.0, min(1.0, fraction))
    turn = fraction * 2 * math.pi

    center = size / 2.0
    outer = center - max(0.5, size * 0.04)
    inner = outer - max(1.6, size * 0.24)
    step = 1.0 / SUPERSAMPLE
    samples = SUPERSAMPLE * SUPERSAMPLE

    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            covered = filled = 0
            for sy in range(SUPERSAMPLE):
                dy = y + (sy + 0.5) * step - center
                for sx in range(SUPERSAMPLE):
                    dx = x + (sx + 0.5) * step - center
                    distance = math.hypot(dx, dy)
                    if not inner <= distance <= outer:
                        continue
                    covered += 1
                    # Zero at twelve o'clock, increasing clockwise.
                    angle = math.atan2(dx, -dy) % (2 * math.pi)
                    if angle <= turn:
                        filled += 1
            if not covered:
                continue
            share = filled / covered
            index = (y * size + x) * 4
            out[index + 0] = round(track_b + (fill_b - track_b) * share)
            out[index + 1] = round(track_g + (fill_g - track_g) * share)
            out[index + 2] = round(track_r + (fill_r - track_r) * share)
            out[index + 3] = round(255 * covered / samples)
    return bytes(out)


def _make_hicon(size: int, fraction: float, color) -> wintypes.HICON:
    """A 32-bit HICON with a real alpha channel, built from the pixels above."""
    info = _BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    info.bmiHeader.biWidth = size
    info.bmiHeader.biHeight = -size  # top-down, matching gauge_pixels
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = BI_RGB

    bits = ctypes.c_void_p()
    color_bitmap = _gdi32.CreateDIBSection(None, ctypes.byref(info), DIB_RGB_COLORS,
                                           ctypes.byref(bits), None, 0)
    if not color_bitmap:
        raise ctypes.WinError(ctypes.get_last_error())

    pixels = gauge_pixels(size, fraction, color)
    ctypes.memmove(bits, pixels, len(pixels))

    # The mask is unused for 32-bit icons, but CreateIconIndirect wants one, and
    # CreateBitmap with a NULL pointer leaves it uninitialised.
    stride = ((size + 31) // 32) * 4
    blank = (ctypes.c_byte * (stride * size))()
    mask_bitmap = _gdi32.CreateBitmap(size, size, 1, 1, ctypes.byref(blank))

    icon_info = _ICONINFO(True, 0, 0, mask_bitmap, color_bitmap)
    icon = _user32.CreateIconIndirect(ctypes.byref(icon_info))
    _gdi32.DeleteObject(color_bitmap)
    _gdi32.DeleteObject(mask_bitmap)
    if not icon:
        raise ctypes.WinError(ctypes.get_last_error())
    return icon


class Tray:
    """
    One tray icon, owned by its own thread.

    `on_event(name)` is called from that thread for "show", "pin", "refresh" and
    "quit"; it is expected to hand the name to the Tk loop rather than act.
    """

    def __init__(self, on_event, labels: dict[str, str]):
        self.on_event = on_event
        self.labels = labels
        self.hwnd: int | None = None
        self.icon: wintypes.HICON | None = None
        self._thread: threading.Thread | None = None
        self.pinned = True
        self.tip = "Lagrange"
        self.size = max(16, _user32.GetSystemMetrics(SM_CXSMICON))
        self._ready = threading.Event()
        self._alive = False
        self._wndproc = WNDPROC(self._handle)  # must outlive the window
        self._taskbar_created = _user32.RegisterWindowMessageW("TaskbarCreated")
        self._pending = (0.0, "#6d8cff", "Lagrange")
        self._balloon: tuple[str, str] | None = None

    # ── lifecycle ───────────────────────────────────────────────────────────
    def start(self) -> bool:
        _LIVE.add(self)
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="lagrange-tray")
        self._thread.start()
        self._ready.wait(timeout=5)
        if not self._alive:
            _LIVE.discard(self)
        return self._alive

    def stop(self, timeout: float = 3.0) -> None:
        """
        Take the icon down and wait for its thread to finish.

        Waiting is the point: returning early would let the interpreter tear
        down objects the window procedure is still being called through.
        """
        if self.hwnd:
            _user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)
        self.hwnd = None
        _LIVE.discard(self)

    def update(self, fraction: float | None, color: str, tip: str) -> None:
        """Redraw the gauge and retitle the icon. Safe from any thread."""
        self._pending = (0.0 if fraction is None else fraction, color, tip)
        if self.hwnd:
            _user32.PostMessageW(self.hwnd, WM_TRAY_REDRAW, 0, 0)

    def notify(self, title: str, text: str) -> None:
        """
        Balloon over the icon. Windows 11 files new icons under the overflow
        chevron, so the first time the widget hides itself it has to say where
        it went — otherwise it just looks closed.
        """
        self._balloon = (title[:63], text[:255])
        if self.hwnd:
            _user32.PostMessageW(self.hwnd, WM_TRAY_BALLOON, 0, 0)

    def set_pinned(self, pinned: bool) -> None:
        self.pinned = pinned

    # ── the tray thread ─────────────────────────────────────────────────────
    def _run(self):
        try:
            self._create_window()
            self._add_icon()
            self._alive = True
        except Exception:
            self._alive = False
            self._ready.set()
            return
        self._ready.set()

        message = wintypes.MSG()
        try:
            while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                _user32.TranslateMessage(ctypes.byref(message))
                _user32.DispatchMessageW(ctypes.byref(message))
        except OSError:
            pass  # the desktop went away underneath us; nothing left to serve
        finally:
            self._alive = False
            _LIVE.discard(self)

    def _create_window(self):
        instance = _kernel32.GetModuleHandleW(None)
        window_class = _WNDCLASS()
        window_class.style = CS_HREDRAW | CS_VREDRAW
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = instance
        window_class.lpszClassName = "LagrangeTrayWindow"
        if (not _user32.RegisterClassW(ctypes.byref(window_class))
                and ctypes.get_last_error() != ERROR_CLASS_ALREADY_EXISTS):
            raise ctypes.WinError(ctypes.get_last_error())

        # Deliberately not HWND_MESSAGE: message-only windows are skipped by the
        # TaskbarCreated broadcast, and the icon would never come back after an
        # Explorer restart. An ordinary window that is simply never shown does.
        self.hwnd = _user32.CreateWindowExW(0, "LagrangeTrayWindow", "Lagrange tray",
                                            WS_OVERLAPPED, 0, 0, 0, 0,
                                            None, None, instance, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

    def _data(self, flags: int) -> _NOTIFYICONDATA:
        data = _NOTIFYICONDATA()
        data.cbSize = ctypes.sizeof(_NOTIFYICONDATA)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self.icon or 0
        data.szTip = self.tip[:127]
        return data

    def _add_icon(self):
        fraction, color, tip = self._pending
        self.tip = tip
        self.icon = _make_hicon(self.size, fraction, color)
        if not _shell32.Shell_NotifyIconW(NIM_ADD,
                                          ctypes.byref(self._data(NIF_MESSAGE | NIF_ICON
                                                                  | NIF_TIP))):
            raise ctypes.WinError(ctypes.get_last_error())

    def _show_balloon(self):
        if not self._balloon:
            return
        title, text = self._balloon
        data = self._data(NIF_INFO)
        data.szInfoTitle = title
        data.szInfo = text
        data.dwInfoFlags = NIIF_INFO
        _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))
        self._balloon = None

    def _refresh_icon(self):
        fraction, color, tip = self._pending
        self.tip = tip
        previous = self.icon
        try:
            self.icon = _make_hicon(self.size, fraction, color)
        except OSError:
            return
        _shell32.Shell_NotifyIconW(NIM_MODIFY,
                                   ctypes.byref(self._data(NIF_ICON | NIF_TIP)))
        if previous:
            _user32.DestroyIcon(previous)

    def _menu(self):
        menu = _user32.CreatePopupMenu()
        _user32.AppendMenuW(menu, MF_STRING, ID_SHOW, self.labels["show"])
        _user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if self.pinned else 0),
                            ID_PIN, self.labels["pin"])
        _user32.AppendMenuW(menu, MF_STRING, ID_REFRESH, self.labels["refresh"])
        _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        _user32.AppendMenuW(menu, MF_STRING, ID_QUIT, self.labels["quit"])

        point = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(point))
        # Without the foreground dance the menu refuses to close on click-away.
        _user32.SetForegroundWindow(self.hwnd)
        choice = _user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            point.x, point.y, 0, self.hwnd, None)
        _user32.PostMessageW(self.hwnd, 0, 0, 0)
        _user32.DestroyMenu(menu)
        return choice

    def _handle(self, hwnd, message, wparam, lparam):
        if message == WM_TRAY:
            event = lparam & 0xFFFF
            # Every flavour of left click restores. Which of down/up/double the
            # shell forwards has changed between Windows versions, and firing
            # twice is harmless — the window is simply already back.
            if event in (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK,
                         WM_MBUTTONUP, NIN_SELECT, NIN_KEYSELECT):
                self.on_event("show")
            elif event == WM_RBUTTONUP:
                choice = self._menu()
                name = {ID_SHOW: "show", ID_PIN: "pin",
                        ID_REFRESH: "refresh", ID_QUIT: "quit"}.get(choice)
                if name:
                    self.on_event(name)
            return 0
        if message == WM_TRAY_REDRAW:
            self._refresh_icon()
            return 0
        if message == WM_TRAY_BALLOON:
            self._show_balloon()
            return 0
        if message == self._taskbar_created:
            # Explorer restarted and forgot every icon; put ours back.
            with contextlib.suppress(OSError):
                self._add_icon()
            return 0
        if message == WM_DESTROY:
            _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data(0)))
            if self.icon:
                _user32.DestroyIcon(self.icon)
                self.icon = None
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, message, wparam, lparam)
