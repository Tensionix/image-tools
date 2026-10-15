"""Turns, mirrors, a turn by an angle and margins: the commands of the section TRANSFORM.

Every picture is turned upright by its EXIF first, as every command of the engine does
(commands._process_batch_file): a turn counts from the picture a person sees. A picture keeps its
format unless another is asked ("--to keep"): a JPEG stays a JPEG, a PNG a PNG.

A JPEG turned by 90 or 180 degrees or mirrored, kept a JPEG, is turned without loss by jpegtran of
libjpeg-turbo (system_core\\jpegtran, install\\get_jpegtran.py): its blocks are moved, not encoded again.
The turn its EXIF asks for and the turn asked are made one. A JPEG whose sides are not whole numbers of
its blocks cannot be turned so (-perfect refuses), nor one whose EXIF is to be kept with a turn in it:
those, and every other picture, Pillow turns by its pixels, a JPEG then written again at quality 95.
Every copy of jpegtran is checked: its size, and its pixels against the picture turned by Pillow.

  rotate        --turn cw90 | ccw90 | 180 | flip-h | flip-v
  rotate-angle  --angle DEGREES (clockwise, fractions too) --fit expand | keep | inner --fill white | black | transparent | R,G,B
  add-margins   --top --right --bottom --left MM --fill white | black | R,G,B --dpi DPI (used where a picture states none)
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import uuid
from pathlib import Path

from PIL import Image, ImageChops, ImageOps, ImageStat

from .commands import _batch_summary, _has_errors, _process_batch_file, _run_parallel
from .io_utils import discover_inputs, write_json_report, write_whole

try:  # imported as system_core.image_tools
    from ..core.lines import item
    from ..core.output_decode import decode_process_bytes
except ImportError:  # run by main.py, where the packages of system_core are top-level
    from core.lines import item
    from core.output_decode import decode_process_bytes

# The format a picture keeps when no other is asked: by the suffix of its file.
KEEP = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png", ".tif": "tiff", ".tiff": "tiff", ".webp": "webp",
        ".avif": "avif", ".heic": "heic", ".heif": "heif"}
TURNS = {
    "cw90": Image.Transpose.ROTATE_270,
    "ccw90": Image.Transpose.ROTATE_90,
    "180": Image.Transpose.ROTATE_180,
    "flip-h": Image.Transpose.FLIP_LEFT_RIGHT,
    "flip-v": Image.Transpose.FLIP_TOP_BOTTOM,
}
NAMED = {"white": (255, 255, 255), "black": (0, 0, 0)}


def _format_for(args, src: Path) -> str:
    return KEEP.get(src.suffix.lower(), "png") if args.to == "keep" else args.to


def _batch(args, name: str, transform, dpi_fn=None) -> int:
    """Every picture of the Source through `transform`, written in its own format or the one asked."""
    input_path, output_dir = Path(args.input), Path(args.output)
    files = discover_inputs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    def one(src: Path) -> dict:
        own = argparse.Namespace(**{**vars(args), "to": _format_for(args, src)})
        return _process_batch_file(own, input_path, output_dir, src, transform, None, dpi_fn)

    results = _run_parallel(files, args, one)
    write_json_report(Path(args.log_dir), {"command": name, "results": results})
    print(json.dumps(_batch_summary(results), ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def _swapped_dpi(image: Image.Image, _transformed: Image.Image, _src: Path):
    """A picture turned by 90 degrees: its two densities change places (the same for most pictures, they state one)."""
    dpi = image.info.get("dpi")
    if not dpi or len(dpi) < 2 or dpi[0] == dpi[1]:
        return None
    return (dpi[1], dpi[0])


JPEGTRAN = Path(__file__).resolve().parents[1] / "jpegtran" / "jpegtran.exe"
# What the EXIF Orientation of a picture asks to make the one a person sees of the one stored (ImageOps.exif_transpose).
ORIENTED = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
            5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
# The same turns in the words of jpegtran (it turns clockwise, Pillow counter-clockwise).
LOSSLESS = {None: [], Image.Transpose.ROTATE_270: ["-rotate", "90"], Image.Transpose.ROTATE_180: ["-rotate", "180"],
            Image.Transpose.ROTATE_90: ["-rotate", "270"], Image.Transpose.FLIP_LEFT_RIGHT: ["-flip", "horizontal"],
            Image.Transpose.FLIP_TOP_BOTTOM: ["-flip", "vertical"], Image.Transpose.TRANSPOSE: ["-transpose"],
            Image.Transpose.TRANSVERSE: ["-transverse"]}


def one_turn(first, then):
    """The single turn that is `first` and then `then`: tried on a tiny picture of six different pixels."""
    probe = Image.frombytes("L", (2, 3), bytes(range(6)))
    target = (probe if first is None else probe.transpose(first)).transpose(then)
    for turn in LOSSLESS:
        candidate = probe if turn is None else probe.transpose(turn)
        if candidate.size == target.size and candidate.tobytes() == target.tobytes():
            return turn
    raise ValueError("no single turn")


def _set_density(path: Path, dpi: tuple) -> None:
    """The density in the JFIF block jpegtran writes first: a few bytes, nothing of the picture."""
    data = bytearray(path.read_bytes())
    if data[2:4] == b"\xff\xe0" and data[6:11] == b"JFIF\x00":
        data[13] = 1
        data[14:18] = struct.pack(">HH", max(1, min(65535, round(dpi[0]))), max(1, min(65535, round(dpi[1]))))
        path.write_bytes(bytes(data))


def _fits(path: Path) -> bool:
    """jpegtran takes its paths in the ANSI code page of Windows: a path outside it ("Фото ü.jpg", "写真.jpg") does not open."""
    if os.name != "nt":
        return True
    try:
        str(path).encode("mbcs")  # strict: no best fit, "ü" is not taken for "u"
    except UnicodeEncodeError:
        return False
    return True


def turn_without_loss(src: Path, target: Path, turn, metadata: str) -> str:
    """"" when jpegtran turned the JPEG without loss and the copy holds; else why not - the caller turns it by its pixels."""
    if not JPEGTRAN.is_file():
        return "jpegtran is not in place"
    with Image.open(src) as image:
        if image.format != "JPEG":
            return f"not a plain JPEG ({image.format})"
        orientation = image.getexif().get(0x0112, 1)
        if metadata == "preserve_all" and orientation not in (None, 1):
            return "its EXIF is to be kept, and a turn in it would turn the copy again"
        dpi = image.info.get("dpi")
        expected = ImageOps.exif_transpose(image).transpose(turn)
    whole = one_turn(ORIENTED.get(orientation), turn)
    copy = {"preserve_all": "all", "strip_all": "none"}.get(metadata, "icc")
    target.parent.mkdir(parents=True, exist_ok=True)
    given, draft = src, target.with_name(target.name + ".writing")
    # A path outside the code page goes to jpegtran as a stand-in of plain letters: in the Target when its folder fits,
    # else among the temporary files. "*.writing.*" is what the service clears after a stop.
    stand_ins: list[Path] = []
    if not (_fits(src) and _fits(draft)):
        spare = target.parent if _fits(target.parent) else Path(tempfile.gettempdir())
        if not _fits(spare):
            return "its path is outside the code page jpegtran reads"
        token = uuid.uuid4().hex[:12]
        if not _fits(src):
            given = spare / f"jpegtran-{token}.writing.jpg"
            stand_ins.append(given)
            shutil.copyfile(src, given)
        if not _fits(draft):
            draft = spare / f"jpegtran-{token}-turned.writing.jpg"
    try:
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
        done = subprocess.run([str(JPEGTRAN), "-copy", copy, "-perfect", "-optimize", *LOSSLESS[whole], "-outfile", str(draft), str(given)],
                              capture_output=True, timeout=300, **flags)
        if done.returncode != 0 or not draft.is_file():
            # jpegtran speaks in the code page of the console, not in UTF-8: its words are decoded by the guess of the engine.
            said = decode_process_bytes(done.stderr or done.stdout).strip()
            return "its sides are not whole numbers of its JPEG blocks" if "perfect" in said.lower() or "transform" in said.lower() else f"jpegtran: {said[:200]}"
        if dpi and metadata != "strip_all":
            quarter = whole in (Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_270, Image.Transpose.TRANSPOSE, Image.Transpose.TRANSVERSE)
            _set_density(draft, (dpi[1], dpi[0]) if quarter else dpi)
        with Image.open(draft) as made:
            made.load()
            size_ok = made.size == expected.size
            off = sum(ImageStat.Stat(ImageChops.difference(made.convert("RGB"), expected.convert("RGB"))).mean) / 3 if size_ok else 255
        if not size_ok or off > 2.0:
            return f"the copy of jpegtran did not hold (size {'right' if size_ok else 'wrong'}, pixels off by {off:.1f})"
        if draft.parent == target.parent:
            draft.replace(target)
        else:  # made among the temporary files, perhaps on another disk: put in place whole all the same
            write_whole(target, draft.read_bytes())
        return ""
    finally:
        for path in (*stand_ins, draft):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)


def cmd_rotate(args) -> int:
    turn = TURNS[args.turn]
    quarter = args.turn in ("cw90", "ccw90")
    dpi_fn = _swapped_dpi if quarter else None
    input_path, output_dir = Path(args.input), Path(args.output)
    files = discover_inputs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    # The files go in parallel: the place of each in the batch is counted before.
    place = {src: at for at, src in enumerate(files, start=1)}

    def one(src: Path) -> dict:
        to = _format_for(args, src)
        if to == "jpg" and src.suffix.lower() in (".jpg", ".jpeg"):
            target = (output_dir / (src.relative_to(input_path) if input_path.is_dir() else Path(src.name))).with_suffix(".jpg")
            why = turn_without_loss(src, target, turn, getattr(args, "metadata", "preserve_dpi_color"))
            if not why:
                return {"input": str(src), "output": str(target), "lossless": True}
            print(item("INFO", src.name, f"not turned without loss - {why}; turned by its pixels, JPEG {args.jpeg_quality}", place[src], len(files)))
        own = argparse.Namespace(**{**vars(args), "to": to})
        return _process_batch_file(own, input_path, output_dir, src, lambda image, _src: image.transpose(turn), None, dpi_fn)

    results = _run_parallel(files, args, one)
    write_json_report(Path(args.log_dir), {"command": f"rotate {args.turn}", "results": results})
    print(json.dumps({**_batch_summary(results), "without_loss": sum(1 for item in results if item.get("lossless"))}, ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def parse_fill(text: str) -> tuple[int, ...] | None:
    """white, black, transparent (None) or "R,G,B" - a colour as a tuple."""
    text = (text or "white").strip().lower()
    if text == "transparent":
        return None
    if text in NAMED:
        return NAMED[text]
    parts = [part.strip() for part in text.lstrip("#").split(",")]
    if len(parts) == 1 and len(parts[0]) == 6:
        return tuple(int(parts[0][at:at + 2], 16) for at in (0, 2, 4))
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return tuple(min(255, int(part)) for part in parts)
    raise argparse.ArgumentTypeError(f"not a colour: {text} (white, black, transparent, R,G,B or #RRGGBB)")


def _with_fill(image: Image.Image, fill: tuple[int, ...] | None) -> tuple[Image.Image, tuple[int, ...]]:
    """The picture in a mode that can take the fill, and the fill in that mode. Transparent needs a mask."""
    if fill is None:
        image = image.convert("RGBA") if image.mode not in ("RGBA", "LA") else image
        return image, (0, 0, 0, 0) if image.mode == "RGBA" else (0, 0)
    if image.mode in ("P", "1", "I", "I;16", "F"):
        image = image.convert("RGB")
    if image.mode == "L":
        return image, (round(sum(fill) / 3),)
    if image.mode == "LA":
        return image, (round(sum(fill) / 3), 255)
    if image.mode == "RGBA":
        return image, (*fill, 255)
    if image.mode == "CMYK":
        image = image.convert("RGB")
    return image, fill


def inner_box(width: int, height: int, degrees: float) -> tuple[int, int]:
    """The largest upright rectangle inside a picture turned by `degrees`: what is left with no corner of the fill."""
    if width <= 0 or height <= 0:
        return 0, 0
    angle = math.radians(degrees % 180)
    if angle > math.pi / 2:
        angle = math.pi - angle
    sin, cos = abs(math.sin(angle)), abs(math.cos(angle))
    long_side, short_side = max(width, height), min(width, height)
    if short_side <= 2 * sin * cos * long_side or abs(sin - cos) < 1e-10:
        half = 0.5 * short_side
        x, y = (half / sin, half / cos) if width >= height else (half / cos, half / sin)
    else:
        cos2 = cos * cos - sin * sin
        x, y = (width * cos - height * sin) / cos2, (height * cos - width * sin) / cos2
    return max(1, int(math.floor(abs(x)))), max(1, int(math.floor(abs(y))))


def cmd_rotate_angle(args) -> int:
    fill = parse_fill(args.fill)

    def turn(image: Image.Image, _src: Path) -> Image.Image:
        if abs(args.angle) % 360 < 1e-9:
            return image
        canvas, colour = _with_fill(image, fill)
        # Pillow turns counter-clockwise for a positive angle; the form counts clockwise, as a person says it.
        turned = canvas.rotate(-args.angle, resample=Image.Resampling.BICUBIC, expand=args.fit == "expand", fillcolor=colour)
        turned.info = dict(image.info)
        if args.fit != "inner":
            return turned
        width, height = inner_box(image.width, image.height, args.angle)
        left, top = (turned.width - width) // 2, (turned.height - height) // 2
        return turned.crop((left, top, left + width, top + height))

    return _batch(args, f"rotate-angle {args.angle:g}", turn)


def cmd_add_margins(args) -> int:
    fill = parse_fill(args.fill) or NAMED["white"]

    def margins(image: Image.Image, _src: Path) -> Image.Image:
        dpi = image.info.get("dpi")
        per_mm_x = (float(dpi[0]) if dpi and float(dpi[0]) > 0 else args.dpi) / 25.4
        per_mm_y = (float(dpi[1]) if dpi and len(dpi) > 1 and float(dpi[1]) > 0 else args.dpi) / 25.4
        left, right = round(args.left * per_mm_x), round(args.right * per_mm_x)
        top, bottom = round(args.top * per_mm_y), round(args.bottom * per_mm_y)
        canvas, colour = _with_fill(image, fill)
        out = Image.new(canvas.mode, (canvas.width + left + right, canvas.height + top + bottom), colour)
        out.paste(canvas, (left, top))
        out.info = dict(image.info)
        return out

    return _batch(args, "add-margins", margins)


def add_parsers(sub, add_common_io) -> None:
    choices = ("keep", "jpg", "png", "tiff", "webp", "avif", "heif", "heic")

    def io(parser) -> None:
        add_common_io(parser, default_to="keep", output_choices=choices)
        # A turned JPEG is written again: at 95 the difference does not show.
        parser.set_defaults(jpeg_quality=95)

    rotate = sub.add_parser("rotate", help="Turn by 90 or 180 degrees, or mirror")
    io(rotate)
    rotate.add_argument("--turn", required=True, choices=list(TURNS))
    rotate.set_defaults(func=cmd_rotate)

    angle = sub.add_parser("rotate-angle", help="Turn by any angle, clockwise, fractions too")
    io(angle)
    angle.add_argument("--angle", type=float, required=True, help="Degrees, clockwise; negative - counter-clockwise")
    angle.add_argument("--fit", choices=["expand", "keep", "inner"], default="expand",
                       help="expand - the canvas grows to hold the whole picture; keep - the size stays, the corners are cut; "
                            "inner - the largest rectangle with no fill in its corners")
    angle.add_argument("--fill", default="white", help="white, black, transparent, R,G,B or #RRGGBB")
    angle.set_defaults(func=cmd_rotate_angle)

    margins = sub.add_parser("add-margins", help="Add margins in millimetres")
    io(margins)
    for side in ("top", "right", "bottom", "left"):
        margins.add_argument(f"--{side}", type=float, default=0.0, help=f"The margin at the {side}, mm")
    margins.add_argument("--fill", default="white", help="white, black, R,G,B or #RRGGBB")
    margins.add_argument("--dpi", type=float, default=300.0, help="The density used where a picture states none")
    margins.set_defaults(func=cmd_add_margins)
