"""Frames: an animation and a TIFF of many pages taken apart, and frames put back together, the pauses kept."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "system_core" / "main.py"


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-X", "utf8", str(MAIN), *args, "--log-dir", str(tmp_path / "logs")],
                          capture_output=True, text=True, encoding="utf-8")


def _frames(count: int = 3) -> list[Image.Image]:
    return [Image.new("RGB", (40, 30), (60 * index, 100, 255 - 60 * index)) for index in range(count)]


def test_an_animation_and_a_tiff_come_apart_into_frames_and_the_pauses_are_written(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    first, *rest = _frames()
    first.save(source / "wave.gif", save_all=True, append_images=rest, duration=[100, 250, 400], loop=0)
    first.save(source / "spin.webp", save_all=True, append_images=rest, duration=[50, 60, 70], loop=0, lossless=True)
    first.save(source / "pages.tiff", save_all=True, append_images=rest)
    first.save(source / "single.png")
    done = _run(tmp_path, "split-frames", "--input", str(source), "--output", str(tmp_path / "out"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "3 of 3 pictures taken apart into frames" in done.stdout
    assert json.loads((tmp_path / "out" / "spin" / "frames.json").read_text(encoding="utf-8"))["durations"] == [50, 60, 70]
    assert sorted(path.name for path in (tmp_path / "out" / "wave").iterdir()) == ["001_wave.png", "002_wave.png", "003_wave.png", "frames.json"]
    assert json.loads((tmp_path / "out" / "wave" / "frames.json").read_text(encoding="utf-8"))["durations"] == [100, 250, 400]
    assert len(list((tmp_path / "out" / "pages").glob("*.png"))) == 3 and not (tmp_path / "out" / "pages" / "frames.json").exists()
    assert not (tmp_path / "out" / "single").exists()
    with Image.open(tmp_path / "out" / "pages" / "002_pages.png") as page:
        assert page.convert("RGB").getpixel((5, 5)) == (60, 100, 195)


def test_frames_go_back_into_an_animation_with_their_pauses(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    first, *rest = _frames()
    first.save(source / "wave.gif", save_all=True, append_images=rest, duration=[100, 250, 400], loop=0)
    _run(tmp_path, "split-frames", "--input", str(source), "--output", str(tmp_path / "frames"))
    for kind, suffix in (("gif", ".gif"), ("webp", ".webp"), ("apng", ".png")):
        done = _run(tmp_path, "frames-to-animation", "--input", str(tmp_path / "frames"), "--output", str(tmp_path / kind), "--to", kind)
        assert done.returncode == 0, done.stdout + done.stderr
        with Image.open(tmp_path / kind / f"wave{suffix}") as animation:
            assert animation.n_frames == 3
            pauses = []
            for index in range(3):
                animation.seek(index)
                animation.load()
                pauses.append(animation.info.get("duration"))
            assert pauses == [100, 250, 400], (kind, pauses)


def test_frames_of_a_folder_by_fps_in_the_order_of_their_names(tmp_path: Path) -> None:
    folder = tmp_path / "shots"
    folder.mkdir()
    for number, frame in zip((10, 2, 1), _frames()):
        frame.save(folder / f"frame {number}.png")
    Image.new("RGB", (80, 30), (0, 0, 0)).save(folder / "frame 11.png")
    done = _run(tmp_path, "frames-to-animation", "--input", str(folder), "--output", str(tmp_path / "out"), "--to", "gif", "--fps", "5", "--loop", "1")
    assert done.returncode == 0, done.stdout + done.stderr
    with Image.open(tmp_path / "out" / "shots.gif") as animation:
        assert animation.n_frames == 4 and animation.size == (40, 30) and animation.info.get("duration") == 200
        assert "loop" not in animation.info
        colours = []
        for index in range(3):
            animation.seek(index)
            colours.append(animation.convert("RGB").getpixel((5, 5))[0])
    # frame 1, frame 2, frame 10: the colours of frames 2, 1, 0 of _frames().
    assert colours == [120, 60, 0]
