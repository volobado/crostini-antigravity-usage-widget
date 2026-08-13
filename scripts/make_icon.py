"""
Build `assets/lagrange.ico` from the same code that draws the tray gauge.

An .ico is a container of DIBs, which the standard library can write directly —
so the mark stays a few lines of arithmetic in `lagrange/tray.py` instead of a
binary blob in the repository that nobody can edit.

    python scripts/make_icon.py [output.ico]
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lagrange.tray import gauge_pixels  # noqa: E402

SIZES = (16, 20, 24, 32, 48, 64, 128, 256)
FRACTION = 0.72          # a gauge, not a full ring: reads as a meter at a glance
COLOR = "#6d8cff"        # the widget's accent
TRACK = (0x2c, 0x31, 0x45)

DEFAULT_OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "assets", "lagrange.ico")


def _dib(size: int) -> bytes:
    """One icon image: BITMAPINFOHEADER, bottom-up BGRA, then an empty AND mask."""
    pixels = gauge_pixels(size, FRACTION, COLOR, TRACK)
    stride = size * 4
    rows = [pixels[y * stride:(y + 1) * stride] for y in range(size)]
    xor = b"".join(reversed(rows))

    mask_stride = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_stride * size)

    header = struct.pack("<IiiHHIIiiII",
                         40,            # biSize
                         size,          # biWidth
                         size * 2,      # biHeight — colour and mask stacked
                         1,             # biPlanes
                         32,            # biBitCount
                         0,             # BI_RGB
                         len(xor) + len(mask),
                         0, 0, 0, 0)
    return header + xor + mask


def build(path: str = DEFAULT_OUTPUT) -> str:
    images = [_dib(size) for size in SIZES]
    offset = 6 + 16 * len(images)

    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    for size, image in zip(SIZES, images, strict=True):
        dimension = 0 if size >= 256 else size  # 0 means 256 in an ICONDIRENTRY
        out += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32,
                           len(image), offset)
        offset += len(image)
    for image in images:
        out += image

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return path


if __name__ == "__main__":
    written = build(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUT)
    print(f"{written}  ({os.path.getsize(written) / 1024:.0f} KB, "
          f"{len(SIZES)} sizes)")
