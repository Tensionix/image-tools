"""SIZE: a picture made larger or smaller by a percent, and brought to an exact width and height."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "system_core" / "main.py"


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-X", "utf8", str(MAIN), *args, "--log-dir", str(tmp_path / "logs")],
                          capture_output=True, text=True, encoding="utf-8")


def _source(tmp_path: Path) -> Path:
    folder = tmp_path / "in"
    folder.mkdir()
    picture = Image.new("RGB", (400, 300), (40, 90, 160))
    picture.paste((250, 250, 250), (100, 100, 300, 200))
    picture.save(folder / "plan.png", dpi=(300, 300))
    Image.new("RGB", (200, 100), (200, 50, 50)).save(folder / "photo.jpg", quality=95, dpi=(150, 150))
    return folder


def test_a4_becomes_a3_the_density_kept_the_format_kept(tmp_path: Path) -> None:
    done = _run(tmp_path, "scale", "--input", str(_source(tmp_path)), "--output", str(tmp_path / "out"), "--percent", "141.42")
    assert done.returncode == 0, done.stdout + done.stderr
    with Image.open(tmp_path / "out" / "plan.png") as plan:
        assert plan.size == (566, 424) and round(plan.info["dpi"][0]) == 300
    with Image.open(tmp_path / "out" / "photo.jpg") as photo:
        assert photo.format == "JPEG" and photo.size == (283, 141)


def test_three_times_with_nearest_adds_no_colour(tmp_path: Path) -> None:
    done = _run(tmp_path, "scale", "--input", str(_source(tmp_path) / "plan.png"), "--output", str(tmp_path / "out"),
                "--percent", "300", "--algorithm", "nearest")
    assert done.returncode == 0, done.stdout + done.stderr
    with Image.open(tmp_path / "out" / "plan.png") as plan:
        assert plan.size == (1200, 900) and len(plan.getcolors()) == 2


def test_a_percent_out_of_range_is_refused(tmp_path: Path) -> None:
    done = _run(tmp_path, "scale", "--input", str(_source(tmp_path)), "--output", str(tmp_path / "out"), "--percent", "2000")
    assert done.returncode != 0 and not (tmp_path / "out").exists()


def test_the_four_ways_to_an_exact_size(tmp_path: Path) -> None:
    source = _source(tmp_path) / "plan.png"
    sizes = {}
    for mode in ("fit", "pad", "crop", "stretch"):
        done = _run(tmp_path, "exact-size", "--input", str(source), "--output", str(tmp_path / mode), "--width", "200", "--height", "200",
                    "--mode", mode, "--background", "10,20,30")
        assert done.returncode == 0, done.stdout + done.stderr
        with Image.open(tmp_path / mode / "plan.png") as result:
            sizes[mode] = result.size
            if mode == "pad":
                assert result.convert("RGB").getpixel((100, 5)) == (10, 20, 30)
    assert sizes == {"fit": (200, 150), "pad": (200, 200), "crop": (200, 200), "stretch": (200, 200)}


def test_transparent_margins_stay_transparent_in_a_png(tmp_path: Path) -> None:
    done = _run(tmp_path, "exact-size", "--input", str(_source(tmp_path) / "plan.png"), "--output", str(tmp_path / "out"),
                "--width", "300", "--height", "300", "--mode", "pad", "--background", "transparent")
    assert done.returncode == 0, done.stdout + done.stderr
    with Image.open(tmp_path / "out" / "plan.png") as result:
        assert result.mode == "RGBA" and result.getpixel((150, 2))[3] == 0 and result.getpixel((150, 150))[3] == 255
