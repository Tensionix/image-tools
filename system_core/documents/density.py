"""The density a picture file states of itself, rewritten in place: not one pixel, not one byte of the picture changes.

JPEG  the JFIF header (added when the file has none) and, when there is one, the EXIF resolution
PNG   the pHYs chunk (added before the first IDAT when the file has none)

Anything else is told back as it was: `restate` returns None, and the caller decides.
"""
from __future__ import annotations

import struct
import zlib

INCH_PER_METRE = 39.37007874


def _jfif(density: int) -> bytes:
    return b"\xff\xe0" + struct.pack(">H5sBBBHHBB", 16, b"JFIF\x00", 1, 1, 1, density, density, 0, 0)


def restate_jpeg(raw: bytes, density: int) -> bytes:
    """The same JPEG stating another density of itself: JFIF and, where there is one, EXIF."""
    if raw[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG stream")
    head = bytearray(raw)
    at, has_jfif = 2, False
    while at + 4 <= len(head) and head[at] == 0xFF and head[at + 1] not in (0xDA, 0xD9):
        marker = head[at + 1]
        size = struct.unpack(">H", head[at + 2:at + 4])[0]
        if marker == 0xE0 and head[at + 4:at + 9] == b"JFIF\x00":
            head[at + 11:at + 16] = struct.pack(">BHH", 1, density, density)
            has_jfif = True
        elif marker == 0xE1 and head[at + 4:at + 10] == b"Exif\x00\x00":
            _restate_exif(head, at + 10, at + 2 + size, density)
        at += 2 + size
    return bytes(head) if has_jfif else bytes(head[:2]) + _jfif(density) + bytes(head[2:])


def _restate_exif(head: bytearray, tiff: int, end: int, density: int) -> None:
    order = "<" if head[tiff:tiff + 2] == b"II" else ">"
    try:
        ifd = tiff + struct.unpack(order + "I", head[tiff + 4:tiff + 8])[0]
        count = struct.unpack(order + "H", head[ifd:ifd + 2])[0]
    except struct.error:
        return
    for index in range(count):
        entry = ifd + 2 + 12 * index
        if entry + 12 > end:
            return
        tag, kind = struct.unpack(order + "HH", head[entry:entry + 4])
        if tag in (0x011A, 0x011B) and kind == 5:
            where = tiff + struct.unpack(order + "I", head[entry + 8:entry + 12])[0]
            if where + 8 <= end:
                head[where:where + 8] = struct.pack(order + "II", density, 1)
        elif tag == 0x0128 and kind == 3:
            head[entry + 8:entry + 10] = struct.pack(order + "H", 2)


def restate_png(raw: bytes, density: int) -> bytes:
    """The same PNG stating another density of itself in pHYs: the chunks of the picture are copied as they are."""
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG stream")
    per_metre = int(round(density * INCH_PER_METRE))
    body = struct.pack(">IIB", per_metre, per_metre, 1)
    phys = struct.pack(">I", len(body)) + b"pHYs" + body + struct.pack(">I", zlib.crc32(b"pHYs" + body) & 0xFFFFFFFF)
    out = bytearray(raw[:8])
    at, placed = 8, False
    while at + 8 <= len(raw):
        length = struct.unpack(">I", raw[at:at + 4])[0]
        kind = raw[at + 4:at + 8]
        chunk = raw[at:at + 12 + length]
        if kind == b"pHYs":
            if not placed:
                out += phys
                placed = True
        else:
            if kind == b"IDAT" and not placed:
                out += phys
                placed = True
            out += chunk
        at += 12 + length
    return bytes(out)


def restate(raw: bytes, density: int) -> bytes | None:
    """The picture stating `density` of itself, for a JPEG or a PNG; None for any other kind."""
    if raw[:2] == b"\xff\xd8":
        return restate_jpeg(raw, density)
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return restate_png(raw, density)
    return None
