"""
Render the widget with fabricated accounts and capture docs/screenshot.png.

Documentation must never carry a real address, and a screenshot taken from a
live install would. This also lets the picture show every state at once —
running, queued for next start, and the three bar colours — which a real
install rarely does.

    python scripts/make_screenshot.py             docs/screenshot.png
    python scripts/make_screenshot.py --compact   docs/screenshot-compact.png
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
import time
import zlib
from ctypes import wintypes
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

OUTPUT = os.path.join(REPO, "docs", "screenshot.png")
COMPACT_OUTPUT = os.path.join(REPO, "docs", "screenshot-compact.png")
WINDOW_X, WINDOW_Y = 120, 120

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
_user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
PW_RENDERFULLCONTENT = 2


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _png(width: int, height: int, rows: list[bytes], path: str) -> None:
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw, 9))
                 + chunk(b"IEND", b""))


def capture(hwnd: int, path: str) -> tuple[int, int]:
    """
    PrintWindow into a DIB, written out as a PNG by hand.

    Not a screen grab: the window asks itself to paint, so the picture is right
    whatever is on top of it — and, unlike CopyFromScreen, the coordinates come
    from the same process as the window, which is what keeps the frame correct
    on a display scaled above 100 %.
    """
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 100 or height < 60:
        raise RuntimeError(f"window not ready: {width}x{height}")

    info = _BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height  # top-down
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32

    screen = _user32.GetDC(hwnd)
    memory = _gdi32.CreateCompatibleDC(screen)
    bits = ctypes.c_void_p()
    bitmap = _gdi32.CreateDIBSection(screen, ctypes.byref(info), 0,
                                     ctypes.byref(bits), None, 0)
    _gdi32.SelectObject(memory, bitmap)
    if not _user32.PrintWindow(hwnd, memory, PW_RENDERFULLCONTENT):
        raise RuntimeError("PrintWindow failed")

    buffer = (ctypes.c_char * (width * height * 4)).from_address(bits.value)
    rows = []
    for y in range(height):
        line = buffer[y * width * 4:(y + 1) * width * 4]
        rows.append(bytes(b for x in range(width)
                          for b in (line[x * 4 + 2], line[x * 4 + 1], line[x * 4])))
    _png(width, height, rows, path)

    _gdi32.DeleteObject(bitmap)
    _gdi32.DeleteDC(memory)
    _user32.ReleaseDC(hwnd, screen)
    return width, height


def _bucket(window: str, label: str, remaining: float, reset: datetime | None):
    return {"id": "", "window": window, "window_label": label,
            "remaining": remaining, "reset": reset, "description": ""}


def _groups(gemini_5h, gemini_week, third_5h, third_week):
    now = datetime.now(timezone.utc)
    return [
        {"name": "Gemini", "full_name": "Gemini Models",
         "models": "Gemini Flash, Gemini Pro", "buckets": [
             _bucket("5h", "5-hour", gemini_5h, now + timedelta(hours=2, minutes=41)),
             _bucket("weekly", "weekly", gemini_week, now + timedelta(days=4, hours=6))]},
        {"name": "Claude / GPT", "full_name": "Claude and GPT models",
         "models": "Claude Opus, Claude Sonnet, GPT-OSS", "buckets": [
             _bucket("5h", "5-hour", third_5h, now + timedelta(hours=4, minutes=52)),
             _bucket("weekly", "weekly", third_week, now + timedelta(days=6, hours=1))]},
    ]


def _account(email, running=False, pending=False, groups=None):
    return {"email": email, "name": "", "running": running, "pending": pending,
            "loaded": running or pending, "active": running or pending,
            "error": None, "groups": groups or []}


# One of each state, and all three bar colours, so the picture documents the
# whole interface rather than whatever the author's quota happened to be.
STATE = {
    "accounts": [
        _account("account-1@example.com", running=True,
                 groups=_groups(0.62, 0.88, 1.0, 0.97)),
        _account("account-2@example.com", pending=True,
                 groups=_groups(1.0, 1.0, 1.0, 1.0)),
        _account("account-3@example.com", groups=_groups(0.34, 0.71, 1.0, 1.0)),
        _account("account-4@example.com", groups=_groups(0.08, 0.44, 0.9, 0.9)),
    ],
    "active": "account-2@example.com",
    "running": ["account-1@example.com"],
    "tracking": True,
    "logged_in": True,
    "fetched_at": datetime.now(timezone.utc),
}


def main(argv: list[str] | None = None) -> int:
    from lagrange import accounts, ui

    compact = "--compact" in (argv if argv is not None else sys.argv[1:])
    output = COMPACT_OUTPUT if compact else OUTPUT

    # Isolated from a real install: no network, no shared singleton port, and
    # no chance of writing the fabricated layout into the user's ui.json.
    ui.SINGLETON_PORT = 52799
    accounts.collect_state = lambda: STATE
    accounts.load_ui_state = lambda: {"geometry": f"+{WINDOW_X}+{WINDOW_Y}",
                                      "pinned": True, "expanded": [],
                                      "compact": compact}
    accounts.save_ui_state = lambda state: None

    widget = ui.Widget()
    widget.state = STATE
    widget.busy_text = None
    widget.seconds_left = 47
    widget._render()
    widget.status.configure(text="next refresh in 47s")
    for _ in range(5):
        widget.root.update()
        time.sleep(0.15)

    os.makedirs(os.path.dirname(output), exist_ok=True)
    try:
        size = capture(int(widget.root.winfo_id()), output)
    except (RuntimeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        widget._close()  # takes the temporary tray icon down with it

    print(f"saved {output} ({size[0]}x{size[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
