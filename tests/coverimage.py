"""A small real PNG, for testing a cover being written into a book.

A real one rather than a stand-in because the media type is read off the bytes:
a fake signature would test the signature table against itself.
"""

import base64
import struct
import zlib
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
COVER = FIXTURES / "covers" / "one-pixel.png"


def _chunk(kind, body):
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    )


def a_one_pixel_png():
    """A 1x1 PNG, built by hand, so the suite carries no opaque binary."""
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    raw = b"\x00\xff\x00\x00\xff"
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    COVER.parent.mkdir(parents=True, exist_ok=True)
    body = a_one_pixel_png()
    COVER.write_bytes(body)
    print(f"wrote {COVER}: {len(body)} bytes, {base64.b64encode(body[:8]).decode()}")
