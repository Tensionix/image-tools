"""Frames: a picture of many frames taken apart, and frames put together into an animation.

    split-frames         every TIFF, GIF, WebP, PNG (APNG) and MPO of the Source of more than one frame: its
                         frames as PNG, without loss, in a folder of its name - 001_name.png, 002_name.png.
                         An animation leaves frames.json beside them: the pause of every frame and the loops.
    frames-to-animation  the pictures of a folder, in the order of their names (2 before 10), into one GIF,
                         WebP or APNG named after the folder; a folder of folders gives one a folder. The
                         pauses come from frames.json when it lies there (split-frames wrote it), else from
                         --fps. A frame of another size is fitted into the size of the first, centred.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

from .io_utils import write_json_report, written_whole

try:  # imported as system_core.image_tools
    from ..core.lines import item, tally
except ImportError:  # run by main.py, where the packages of system_core are top-level
    from core.lines import item, tally

# A JPEG of a phone may hold a depth map as its second frame (MPO): only a file named .mpo is taken apart.
TAKEN_APART = {".tif", ".tiff", ".gif", ".webp", ".png", ".mpo"}
FRAME_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
TIMING = "frames.json"


def _natural(path: Path) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def _frame_count(path: Path) -> int:
    try:
        with Image.open(path) as image:
            return int(getattr(image, "n_frames", 1) or 1)
    except Exception:
        return 0


def split_one(src: Path, folder: Path) -> tuple[int, bool]:
    """The frames of one picture as PNG into `folder`; the count, and whether it was an animation (timing written)."""
    folder.mkdir(parents=True, exist_ok=True)
    durations: list[int] = []
    count = 0
    with Image.open(src) as image:
        animated = bool(getattr(image, "is_animated", False)) and image.format in ("GIF", "WEBP", "PNG")
        loop = image.info.get("loop")
        for index, frame in enumerate(ImageSequence.Iterator(image), start=1):
            # A WebP tells the pause of a frame once the frame is loaded.
            frame.load()
            durations.append(int(frame.info.get("duration", image.info.get("duration", 100)) or 100))
            picture = frame.convert("RGBA") if frame.mode in ("P", "PA", "LA") or "transparency" in frame.info else frame.copy()
            if picture.mode == "CMYK":
                picture = picture.convert("RGB")
            target = folder / f"{index:03d}_{src.stem}.png"
            with written_whole(target) as temp:
                picture.save(temp, "PNG", compress_level=6)
            count = index
    if animated:
        (folder / TIMING).write_text(json.dumps({"source": src.name, "loop": loop, "durations": durations}, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    return count, animated


def cmd_split_frames(args) -> int:
    input_path, output_dir = Path(args.input), Path(args.output)
    files = [input_path] if input_path.is_file() else sorted(p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in TAKEN_APART)
    many = [src for src in files if _frame_count(src) > 1]
    if not many:
        print(f"No picture of more than one frame in {input_path} (TIFF, GIF, WebP, APNG, MPO)")
        return 1
    results, failed = [], 0
    for at, src in enumerate(many, start=1):
        rel = src.parent.relative_to(input_path) if input_path.is_dir() else Path()
        folder = output_dir / rel / src.stem
        try:
            count, animated = split_one(src, folder)
            print(item("OK", src.name, f"{count} frames" + (", the pauses in frames.json" if animated else "") + f" -> {folder}", at, len(many)))
            results.append({"input": str(src), "frames": count, "folder": str(folder), "animated": animated})
        except Exception as error:
            failed += 1
            print(item("ERR", src.name, f"{type(error).__name__}: {error}", at, len(many)))
            results.append({"input": str(src), "error": f"{type(error).__name__}: {error}"})
    print(tally(len(many) - failed, len(many), f"pictures taken apart into frames; copies in {output_dir}"))
    write_json_report(Path(args.log_dir), {"command": "split-frames", "results": results})
    return 1 if failed else 0


def _groups(input_path: Path) -> dict[Path, list[Path]]:
    """The frames of every folder that holds pictures, in the order of their names."""
    groups: dict[Path, list[Path]] = {}
    for path in sorted(input_path.rglob("*")):
        if path.is_file() and path.suffix.lower() in FRAME_SUFFIXES:
            groups.setdefault(path.parent, []).append(path)
    return {folder: sorted(paths, key=_natural) for folder, paths in groups.items() if len(paths) > 1}


def _fitted(frame: Image.Image, size: tuple[int, int]) -> Image.Image:
    frame = ImageOps.exif_transpose(frame).convert("RGBA")
    if frame.size == size:
        return frame
    inner = ImageOps.contain(frame, size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.paste(inner, ((size[0] - inner.width) // 2, (size[1] - inner.height) // 2))
    return canvas


def build_animation(frames: list[Path], target: Path, kind: str, fps: float, loop: int, quality: int, timing: dict | None) -> int:
    pictures = []
    with Image.open(frames[0]) as first:
        size = ImageOps.exif_transpose(first).size
    for path in frames:
        with Image.open(path) as frame:
            pictures.append(_fitted(frame, size))
    durations = [max(10, round(1000 / fps))] * len(pictures)
    if timing and len(timing.get("durations", [])) == len(pictures):
        durations = [max(10, int(value)) for value in timing["durations"]]
    target.parent.mkdir(parents=True, exist_ok=True)
    first, rest = pictures[0], pictures[1:]
    with written_whole(target) as temp:
        if kind == "gif":
            # A GIF plays once when it has no loop block at all; loop=1 would play it twice in most viewers.
            looped = {"loop": 0} if loop == 0 else {}
            first.save(temp, "GIF", save_all=True, append_images=rest, duration=durations, disposal=2, optimize=False, **looped)
        elif kind == "webp":
            first.save(temp, "WEBP", save_all=True, append_images=rest, duration=durations, loop=loop, quality=quality,
                       lossless=quality >= 100, method=4)
        else:
            first.save(temp, "PNG", save_all=True, append_images=rest, duration=durations, loop=loop, disposal=1)
    return len(pictures)


def cmd_frames_to_animation(args) -> int:
    input_path, output_dir = Path(args.input), Path(args.output)
    if not input_path.is_dir():
        print(f"The Source must be a folder of frames: {input_path}")
        return 2
    groups = _groups(input_path)
    if not groups:
        print(f"No folder with two frames or more in {input_path}")
        return 1
    kind = args.to
    suffix = {"gif": ".gif", "webp": ".webp", "apng": ".png"}[kind]
    results, failed = [], 0
    for at, (folder, frames) in enumerate(groups.items(), start=1):
        rel = folder.relative_to(input_path)
        name = (folder.name if rel != Path() else input_path.name) or "animation"
        target = output_dir / rel.parent / f"{name}{suffix}" if rel != Path() else output_dir / f"{name}{suffix}"
        timing = None
        timing_file = folder / TIMING
        if args.timing == "file" and timing_file.is_file():
            timing = json.loads(timing_file.read_text(encoding="utf-8"))
        loop = int(args.loop)
        try:
            count = build_animation(frames, target, kind, float(args.fps), loop, int(args.quality), timing)
            with Image.open(target) as check:
                ok = int(getattr(check, "n_frames", 1)) == count
            if not ok:
                raise ValueError(f"the animation reads back with another number of frames than {count}")
            told = "the pauses of frames.json" if timing else f"{float(args.fps):g} frames a second"
            print(item("OK", name, f"{count} frames, {told} -> {target}", at, len(groups)))
            results.append({"folder": str(folder), "frames": count, "output": str(target)})
        except Exception as error:
            failed += 1
            print(item("ERR", name, f"{type(error).__name__}: {error}", at, len(groups)))
            results.append({"folder": str(folder), "error": f"{type(error).__name__}: {error}"})
    print(tally(len(groups) - failed, len(groups), f"animations put together and read back; in {output_dir}"))
    write_json_report(Path(args.log_dir), {"command": "frames-to-animation", "results": results})
    return 1 if failed else 0


def add_parsers(sub) -> None:
    split = sub.add_parser("split-frames", help="Take TIFF, GIF, WebP, APNG and MPO of many frames apart into PNG frames")
    split.add_argument("--input", required=True)
    split.add_argument("--output", required=True)
    split.add_argument("--log-dir", default="logs")
    split.set_defaults(func=cmd_split_frames)

    build = sub.add_parser("frames-to-animation", help="Put the frames of a folder together into a GIF, WebP or APNG")
    build.add_argument("--input", required=True, help="A folder of frames, or a folder of such folders")
    build.add_argument("--output", required=True, help="The folder for the animations")
    build.add_argument("--to", choices=["gif", "webp", "apng"], default="gif")
    build.add_argument("--fps", type=float, default=10.0, help="Frames a second where no pauses are written")
    build.add_argument("--timing", choices=["file", "fps"], default="file", help="file - the pauses of frames.json when it is there")
    build.add_argument("--loop", type=int, default=0, help="0 - endless; 1 - once")
    build.add_argument("--quality", type=int, default=90, help="WebP: 100 - without loss")
    build.add_argument("--log-dir", default="logs")
    build.set_defaults(func=cmd_frames_to_animation)
