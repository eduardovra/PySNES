"""Minimal PNG writer with no Pillow dependency.

Lifted from pysnes/ppu/test_ppu.py so the harness and existing screenshot
regression tests share one implementation.
"""

import struct
import zlib
from pathlib import Path


def write_png(path: Path, pixels, width: int, height: int) -> None:
    """Write pixels as an 8-bit RGB PNG.

    `pixels` may be a flat sequence of (r,g,b) tuples (length width*height) or
    a flat bytes-like of length width*height*3. The bytes path skips the
    Python-level per-pixel loop entirely and is much faster on PyPy.
    """
    if isinstance(pixels, (bytes, bytearray, memoryview)):
        flat = bytes(pixels)
        if len(flat) != width * height * 3:
            raise ValueError(
                f"bytes pixels length {len(flat)} does not match "
                f"{width}*{height}*3"
            )
        raw = bytearray(height * (1 + width * 3))
        stride = 1 + width * 3
        for row in range(height):
            raw[row * stride] = 0  # filter type None
            raw[row * stride + 1 : (row + 1) * stride] = flat[
                row * width * 3 : (row + 1) * width * 3
            ]
    else:
        raw = bytearray()
        for row in range(height):
            raw.append(0)  # filter type None
            for col in range(width):
                r, g, b = pixels[row * width + col]
                raw += bytes([r, g, b])

    def chunk(tag: bytes, body: bytes) -> bytes:
        c = struct.pack(">I", len(body)) + tag + body
        return c + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(png)
