"""COLOUR: the correction of colour and a palette of a few colours."""
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


def _one(tmp_path: Path, name: str, image: Image.Image, **save) -> Path:
    folder = tmp_path / "in"
    folder.mkdir(exist_ok=True)
    image.save(folder / name, **save)
    return folder / name


def _pixel(path: Path, at=(5, 5)):
    with Image.open(path) as image:
        return image.convert("RGBA").getpixel(at)


def test_levels_take_a_cast_away_and_keep_the_format(tmp_path: Path) -> None:
    picture = Image.new("RGB", (60, 40), (90, 100, 140))
    picture.paste((40, 50, 90), (0, 0, 30, 40))
    source = _one(tmp_path, "dull.jpg", picture, quality=95)
    done = _run(tmp_path, "adjust", "--input", str(source), "--output", str(tmp_path / "out"), "--levels", "channels", "--cutoff", "0")
    assert done.returncode == 0, done.stdout + done.stderr
    dark, light = _pixel(tmp_path / "out" / "dull.jpg", (5, 5)), _pixel(tmp_path / "out" / "dull.jpg", (50, 5))
    assert max(dark[:3]) < 12 and min(light[:3]) > 243, (dark, light)


def test_brightness_contrast_gamma_and_saturation_move_as_asked(tmp_path: Path) -> None:
    source = _one(tmp_path, "mid.png", Image.new("RGB", (20, 20), (100, 120, 140)))

    def after(*args: str) -> tuple:
        out = tmp_path / ("out_" + "_".join(arg.strip("-") for arg in args))
        assert _run(tmp_path, "adjust", "--input", str(source), "--output", str(out), *args).returncode == 0
        return _pixel(out / "mid.png")[:3]

    assert after("--brightness", "50") == (150, 180, 210)
    assert after("--gamma", "2.0")[0] > 150
    assert after("--saturation", "-100") == after("--tone", "gray")


def test_grey_sepia_tint_and_inversion(tmp_path: Path) -> None:
    source = _one(tmp_path, "c.png", Image.new("RGB", (20, 20), (200, 60, 60)))
    for tone, check in (("gray", lambda p: p[0] == p[1] == p[2]), ("sepia", lambda p: p[0] > p[1] > p[2]), ("0,0,255", lambda p: p[2] > p[0])):
        out = tmp_path / f"out_{tone.replace(',', '_')}"
        assert _run(tmp_path, "adjust", "--input", str(source), "--output", str(out), "--tone", tone).returncode == 0
        assert check(_pixel(out / "c.png")), (tone, _pixel(out / "c.png"))
    assert _run(tmp_path, "adjust", "--input", str(source), "--output", str(tmp_path / "inv"), "--invert").returncode == 0
    assert _pixel(tmp_path / "inv" / "c.png")[:3] == (55, 195, 195)


def test_white_goes_transparent_and_a_jpeg_becomes_a_png(tmp_path: Path) -> None:
    picture = Image.new("RGB", (40, 40), (252, 252, 252))
    picture.paste((20, 60, 160), (10, 10, 30, 30))
    source = _one(tmp_path, "scan.jpg", picture, quality=100)
    done = _run(tmp_path, "adjust", "--input", str(source), "--output", str(tmp_path / "out"), "--white-transparent", "--tolerance", "8")
    assert done.returncode == 0, done.stdout + done.stderr
    written = tmp_path / "out" / "scan.png"
    assert written.exists() and not (tmp_path / "out" / "scan.jpg").exists()
    assert _pixel(written, (2, 2))[3] == 0 and _pixel(written, (20, 20))[3] == 255
    refused = _run(tmp_path, "adjust", "--input", str(source), "--output", str(tmp_path / "jpg"), "--white-transparent", "--to", "jpg")
    assert refused.returncode == 2


def test_the_transparency_of_a_picture_is_kept(tmp_path: Path) -> None:
    logo = Image.new("RGBA", (30, 30), (0, 0, 0, 0))
    logo.paste((200, 50, 50, 255), (5, 5, 25, 25))
    source = _one(tmp_path, "logo.png", logo)
    assert _run(tmp_path, "adjust", "--input", str(source), "--output", str(tmp_path / "out"), "--tone", "gray", "--brightness", "20").returncode == 0
    assert _pixel(tmp_path / "out" / "logo.png", (1, 1))[3] == 0 and _pixel(tmp_path / "out" / "logo.png", (15, 15))[3] == 255


def test_a_palette_of_few_colours_is_lighter_and_keeps_transparency(tmp_path: Path) -> None:
    plan = Image.effect_noise((300, 200), 30).convert("RGB")
    source = _one(tmp_path, "plan.png", plan)
    logo = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    logo.paste((30, 120, 220, 255), (8, 8, 56, 56))
    _one(tmp_path, "logo.png", logo)
    done = _run(tmp_path, "palette", "--input", str(source.parent), "--output", str(tmp_path / "out"), "--colors", "16")
    assert done.returncode == 0, done.stdout + done.stderr
    with Image.open(tmp_path / "out" / "plan.png") as result:
        assert result.mode == "P" and len(result.getcolors()) <= 16
    assert (tmp_path / "out" / "plan.png").stat().st_size < source.stat().st_size
    assert _pixel(tmp_path / "out" / "logo.png", (1, 1))[3] == 0 and _pixel(tmp_path / "out" / "logo.png", (30, 30))[3] == 255
