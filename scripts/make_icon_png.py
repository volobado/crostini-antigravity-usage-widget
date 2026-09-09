"""
Build `assets/lagrange.png` from the same code that draws the tray gauge.

Windows gets an .ico (see `make_icon.py`); a `.desktop` launcher and the
hicolor icon theme both just want a PNG, which the standard library can also
write directly — `zlib` for the one compressed chunk a flat RGB image needs,
no different in kind from `make_icon.py` writing its own DIB headers by hand.

    python scripts/make_icon_png.py [output.png] [size]
"""

from __future__ import annotations

import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lagrange.tray import gauge_pixels  # noqa: E402

SIZE = 256
FRACTION = 0.72          # a gauge, not a full ring: reads as a meter at a glance
COLOR = "#6d8cff"        # the widget's accent
TRACK = (0x2c, 0x31, 0x45)

DEFAULT_OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "assets", "lagrange.png")


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def build(path: str = DEFAULT_OUTPUT, size: int = SIZE) -> str:
    """gauge_pixels is BGRA, top-down; PNG wants RGBA scanlines, each preceded
    by a filter-type byte — trivial for a size this small to leave as "None"."""
    pixels = gauge_pixels(size, FRACTION, COLOR, TRACK)
    scanlines = bytearray()
    for y in range(size):
        row = pixels[y * size * 4:(y + 1) * size * 4]
        rgba = bytearray(size * 4)
        rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = (
            row[2::4], row[1::4], row[0::4], row[3::4])
        scanlines += b"\x00" + bytes(rgba)

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(scanlines), 9))
    png += _chunk(b"IEND", b"")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(bytes(png))
    return path


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUT
    size = int(sys.argv[2]) if len(sys.argv) > 2 else SIZE
    written = build(output, size)
    print(f"{written}  ({os.path.getsize(written) / 1024:.0f} KB, {size}x{size})")
