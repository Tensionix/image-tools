"""Pictures without EXIF and GPS - the picture itself not written again.

    strip-meta --input SOURCE --output TARGET

JPEG, PNG and WebP are taken apart into their blocks, and the blocks of what a picture tells about
itself go: EXIF (GPS, the camera and its serial number, the date, the thumbnail - which may show what
was cut away), XMP, IPTC, comments, texts. The blocks of the picture stay byte for byte: the copy
decodes into the same pixels, which is checked. The colour profile stays; the density stays.

Two things EXIF may hold that a person sees: the turn of a photograph and its density. When the
picture is turned by its EXIF, or states its density nowhere else, a small EXIF of those alone is
written in place of the old one - nothing else goes back.

Another format (HEIC, AVIF, TIFF, GIF, BMP) is named and passed by: its metadata is not taken out
without writing the picture again. Convert does that - "DPI + colour" leaves no EXIF.
"""
from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

from PIL import Image

from .io_utils import discover_inputs, write_json_report, write_whole

try:  # imported as system_core.image_tools
    from ..core.lines import item, tally
    from ..core.paths import routes_cross
except ImportError:  # run by main.py, where the packages of system_core are top-level
    from core.lines import item, tally
    from core.paths import routes_cross

# EXIF tags that go back when they matter: the turn, the density and its unit.
ORIENTATION, X_RESOLUTION, Y_RESOLUTION, RESOLUTION_UNIT = 0x0112, 0x011A, 0x011B, 0x0128
KEPT_TAGS = {ORIENTATION, X_RESOLUTION, Y_RESOLUTION, RESOLUTION_UNIT}
# PNG chunks that tell about the picture rather than draw it.
PNG_TOLD = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}


def _small_exif(exif: Image.Exif, density_elsewhere: bool) -> bytes:
    """An EXIF of the turn and of the density alone, when either matters; b"" - nothing to write back."""
    small = Image.Exif()
    turn = exif.get(ORIENTATION, 1)
    if turn not in (None, 1):
        small[ORIENTATION] = turn
    if not density_elsewhere and exif.get(X_RESOLUTION):
        for tag in (X_RESOLUTION, Y_RESOLUTION, RESOLUTION_UNIT):
            if exif.get(tag) is not None:
                small[tag] = exif[tag]
    return small.tobytes() if len(small) else b""


def _exif_of(blob: bytes) -> Image.Exif:
    exif = Image.Exif()
    try:
        exif.load(blob)
    except Exception:
        pass
    return exif


def _picture_end(data: bytes, at: int) -> int:
    """The byte after the end marker of the picture that begins its scans at `at`: segments by their lengths, the
    data of a scan up to the next marker (FF 00 is a byte of data, FF D0-D7 a restart, FF FF a fill)."""
    while at + 1 < len(data):
        marker = data[at + 1]
        if marker == 0xD9:
            return at + 2
        if marker == 0xFF:
            at += 1
            continue
        length = struct.unpack(">H", data[at + 2:at + 4])[0]
        at += 2 + length
        if marker != 0xDA:
            continue
        while True:
            at = data.find(b"\xff", at)
            if at < 0 or at + 1 >= len(data):
                # Cut short: what is there is the picture, as a viewer shows it.
                return len(data)
            following = data[at + 1]
            if following == 0x00 or 0xD0 <= following <= 0xD7 or following == 0xFF:
                at += 1
                continue
            break
    return len(data)


def strip_jpeg(data: bytes) -> tuple[bytes, list[str]]:
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    out, gone = [data[:2]], []
    at, exif_blob, jfif = 2, b"", False
    has_app0 = data[2:4] == b"\xff\xe0"
    while at < len(data):
        if data[at] != 0xFF:
            raise ValueError(f"a broken marker at byte {at}")
        marker = data[at + 1]
        if marker == 0xFF:
            at += 1
            continue
        if marker == 0xDA or marker == 0xD9:
            # The picture runs to its end marker; what a phone writes after it - the pictures of MPF (a depth map,
            # a preview) with EXIF of their own, a trailer of its maker - goes.
            end = _picture_end(data, at)
            body = data[at:end]
            if data[end:].strip(b"\0"):
                gone.append("data after the picture")
            break
        length = struct.unpack(">H", data[at + 2:at + 4])[0]
        segment = data[at:at + 2 + length]
        payload = segment[4:]
        at += 2 + length
        if marker == 0xE0 and payload.startswith(b"JFIF\0"):
            # JFIF states a density only in dots per inch or per centimetre; unit 0 is a bare aspect ratio.
            jfif = len(payload) > 7 and payload[7] in (1, 2)
        if marker == 0xE1 and payload.startswith(b"Exif\0\0"):
            exif_blob = payload
            gone.append("EXIF")
            continue
        if marker == 0xE1:
            gone.append("XMP")
            continue
        if marker == 0xED:
            gone.append("IPTC")
            continue
        if marker == 0xE2 and payload.startswith(b"MPF\0"):
            # The index of the pictures after this one: they go, and so does their index.
            gone.append("MPF")
            continue
        if marker == 0xFE:
            gone.append("comment")
            continue
        # APP3-APP13, APP15: what programs tell about themselves. APP0 (density), APP2 (ICC) and APP14 (Adobe colour) stay.
        if 0xE3 <= marker <= 0xEF and marker != 0xEE:
            gone.append(f"APP{marker - 0xE0}")
            continue
        out.append(segment)
    else:
        raise ValueError("no picture data in the JPEG")
    small = _small_exif(_exif_of(exif_blob), jfif) if exif_blob else b""
    if small:
        app1 = b"\xff\xe1" + struct.pack(">H", len(small) + 2) + small
        # After the JFIF block when there is one: it must stand first.
        out.insert(2 if has_app0 else 1, app1)
    return b"".join(out) + body, gone


def strip_png(data: bytes) -> tuple[bytes, list[str]]:
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise ValueError("not a PNG")
    out, gone, at, exif_blob = [signature], [], len(signature), b""
    while at < len(data):
        length = struct.unpack(">I", data[at:at + 4])[0]
        kind = data[at + 4:at + 8]
        chunk = data[at:at + 12 + length]
        at += 12 + length
        if kind == b"eXIf":
            exif_blob = chunk[8:8 + length]
        if kind in PNG_TOLD:
            gone.append(kind.decode("ascii"))
            continue
        if kind == b"IEND" and exif_blob:
            small = _small_exif(_exif_of(b"Exif\0\0" + exif_blob), density_elsewhere=True)
            if small:
                raw = small[6:]
                out.append(struct.pack(">I", len(raw)) + b"eXIf" + raw + struct.pack(">I", zlib.crc32(b"eXIf" + raw) & 0xFFFFFFFF))
        out.append(chunk)
    return b"".join(out), sorted(set(gone), key=gone.index)


def strip_webp(data: bytes) -> tuple[bytes, list[str]]:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP")
    chunks, gone, at = [], [], 12
    while at < len(data):
        kind = data[at:at + 4]
        length = struct.unpack("<I", data[at + 4:at + 8])[0]
        chunk = data[at:at + 8 + length + (length & 1)]
        at += 8 + length + (length & 1)
        if kind in (b"EXIF", b"XMP "):
            gone.append(kind.decode("ascii").strip())
            continue
        if kind == b"VP8X":
            # The flags of the container: EXIF (0x08) and XMP (0x04) are no longer there.
            chunk = chunk[:8] + bytes([chunk[8] & ~0x0C]) + chunk[9:]
        chunks.append(chunk)
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body, gone


STRIPPERS = {".jpg": strip_jpeg, ".jpeg": strip_jpeg, ".png": strip_png, ".webp": strip_webp}


def _pixels(data: bytes) -> tuple:
    with Image.open(io.BytesIO(data)) as image:
        frames = getattr(image, "n_frames", 1)
        image.seek(0)
        return image.size, image.mode, frames, image.tobytes()


def check_stripped(before: bytes, after: bytes) -> list[str]:
    """What does not hold in the copy: the pixels, a block of metadata left, a tag that did not go."""
    wrong = []
    if _pixels(before) != _pixels(after):
        wrong.append("the pixels are not the same")
    with Image.open(io.BytesIO(after)) as image:
        exif = image.getexif()
        left = set(exif.keys()) - KEPT_TAGS
        if left:
            wrong.append(f"EXIF tags left: {sorted(left)}")
        if exif.get_ifd(0x8825):
            wrong.append("GPS is left")
        told = [key for key in ("xmp", "XML:com.adobe.xmp", "comment", "photoshop") if image.info.get(key)]
        if image.format == "PNG":
            # Every text of a PNG comes as a string in its info.
            told += [key for key, value in image.info.items() if isinstance(value, str) and key not in told]
        if told:
            wrong.append(f"texts left: {told}")
    return wrong


def cmd_strip_meta(args) -> int:
    input_path, output_dir = Path(args.input), Path(args.output)
    files = discover_inputs(input_path)
    if not files:
        print(f"No pictures in {input_path}")
        return 1
    if crossing := routes_cross(input_path, output_dir):
        print(crossing[0].upper() + crossing[1:])
        return 2
    results, failed = [], 0
    for at, src in enumerate(files, start=1):
        strip = STRIPPERS.get(src.suffix.lower())
        if strip is None:
            print(item("WARN", src.name, f"{src.suffix.lstrip('.').upper()} - its metadata is not taken out without writing the picture "
                       "again; Convert with \"DPI + colour\" leaves no EXIF", at, len(files)))
            results.append({"input": str(src), "skipped": "format"})
            continue
        target = output_dir / (src.relative_to(input_path) if input_path.is_dir() else Path(src.name))
        try:
            before = src.read_bytes()
            after, gone = strip(before)
            wrong = check_stripped(before, after)
            if wrong:
                raise ValueError("; ".join(wrong))
            target.parent.mkdir(parents=True, exist_ok=True)
            write_whole(target, after)
            said = ", ".join(dict.fromkeys(gone)) or "nothing was told"
            lighter = len(before) - len(after)
            weight = f"{lighter} bytes lighter" if lighter >= 0 else f"{-lighter} bytes heavier"
            print(item("OK", src.name, f"taken away - {said}; {weight}", at, len(files)))
            results.append({"input": str(src), "output": str(target), "gone": gone, "bytes_before": len(before), "bytes_after": len(after)})
        except Exception as error:
            failed += 1
            print(item("ERR", src.name, f"{type(error).__name__}: {error}", at, len(files)))
            results.append({"input": str(src), "error": f"{type(error).__name__}: {error}"})
    done = sum(1 for item in results if "output" in item)
    skipped = sum(1 for item in results if "skipped" in item)
    print(tally(done, len(files), f"pictures without EXIF and GPS, checked; passed by: {skipped}; copies in {output_dir}"))
    write_json_report(Path(args.log_dir), {"command": "strip-meta", "results": results})
    return 1 if failed else 0


def add_parsers(sub) -> None:
    strip = sub.add_parser("strip-meta", help="Copy JPEG, PNG and WebP without EXIF, GPS, XMP, IPTC and comments, not writing the picture again")
    strip.add_argument("--input", required=True, help="Input file or folder")
    strip.add_argument("--output", required=True, help="Output folder")
    strip.add_argument("--log-dir", default="logs")
    strip.set_defaults(func=cmd_strip_meta)
