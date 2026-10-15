"""The commands of the section TRANSFORM: turns, mirrors, a turn by an angle, margins - run as the window runs them."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from system_core.image_tools.transform import inner_box

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "system_core" / "main.py"


def run(*args: str) -> subprocess.CompletedProcess:
    done = subprocess.run([sys.executable, "-X", "utf8", str(MAIN), *args], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr
    return done


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    """A picture whose corners say where they went: red top-left, green top-right, blue bottom-left; 40 x 20 at 200 dpi."""
    folder = tmp_path / "in"
    folder.mkdir()
    image = Image.new("RGB", (40, 20), (128, 128, 128))
    for xy, colour in (((0, 0), (255, 0, 0)), ((39, 0), (0, 255, 0)), ((0, 19), (0, 0, 255))):
        image.putpixel(xy, colour)
    image.save(folder / "corners.png", dpi=(200, 200))
    Image.new("RGB", (64, 48), (10, 120, 200)).save(folder / "photo.jpg", quality=95)
    return folder


def corner(path: Path, xy: tuple[int, int]) -> tuple[int, ...]:
    with Image.open(path) as image:
        return image.convert("RGB").getpixel(xy)


def test_a_quarter_turn_clockwise_puts_the_top_left_at_the_top_right(source: Path, tmp_path: Path) -> None:
    out = tmp_path / "cw"
    run("rotate", "--input", str(source), "--output", str(out), "--turn", "cw90", "--log-dir", str(tmp_path / "logs"))
    with Image.open(out / "corners.png") as image:
        assert image.size == (20, 40) and image.format == "PNG"
        assert round(image.info["dpi"][0]) == 200
    assert corner(out / "corners.png", (19, 0)) == (255, 0, 0)
    # A JPEG stays a JPEG.
    with Image.open(out / "photo.jpg") as image:
        assert image.format == "JPEG" and image.size == (48, 64)


@pytest.mark.parametrize("turn, where", [("ccw90", (0, 39)), ("180", (39, 19)), ("flip-h", (39, 0)), ("flip-v", (0, 19))])
def test_the_other_turns_and_mirrors(source: Path, tmp_path: Path, turn: str, where: tuple[int, int]) -> None:
    out = tmp_path / turn
    run("rotate", "--input", str(source / "corners.png"), "--output", str(out), "--turn", turn, "--log-dir", str(tmp_path / "logs"))
    assert corner(out / "corners.png", where) == (255, 0, 0)


def test_a_turn_by_a_fraction_of_a_degree(source: Path, tmp_path: Path) -> None:
    for fit, check in (("expand", lambda size: size[0] > 40 and size[1] > 20), ("keep", lambda size: size == (40, 20)),
                       ("inner", lambda size: size[0] < 40 and size[1] < 20)):
        out = tmp_path / fit
        run("rotate-angle", "--input", str(source / "corners.png"), "--output", str(out), "--angle", "3.5", "--fit", fit,
            "--fill", "black", "--log-dir", str(tmp_path / "logs"))
        with Image.open(out / "corners.png") as image:
            assert check(image.size), (fit, image.size)
    # A transparent fill keeps the corners clear where the format can hold it.
    out = tmp_path / "clear"
    run("rotate-angle", "--input", str(source / "corners.png"), "--output", str(out), "--angle", "-10", "--fill", "transparent",
        "--log-dir", str(tmp_path / "logs"))
    with Image.open(out / "corners.png") as image:
        assert image.mode == "RGBA" and image.getpixel((0, 0))[3] == 0


def test_the_inner_box_of_a_turned_picture() -> None:
    assert inner_box(100, 50, 0) == (100, 50)
    width, height = inner_box(1000, 600, 2)
    assert 900 < width < 1000 and 500 < height < 600
    assert inner_box(100, 100, 45) == (70, 70)


def test_margins_in_millimetres_by_the_density_of_the_picture(source: Path, tmp_path: Path) -> None:
    out = tmp_path / "margins"
    # 200 dpi: 10 mm is 79 pixels; the JPEG states none - 300 dpi of the field: 10 mm is 118 pixels.
    run("add-margins", "--input", str(source), "--output", str(out), "--top", "10", "--left", "10", "--fill", "0,0,0",
        "--log-dir", str(tmp_path / "logs"))
    with Image.open(out / "corners.png") as image:
        assert image.size == (40 + 79, 20 + 79)
        assert image.convert("RGB").getpixel((0, 0)) == (0, 0, 0) and image.convert("RGB").getpixel((79, 79)) == (255, 0, 0)
    with Image.open(out / "photo.jpg") as image:
        assert image.size == (64 + 118, 48 + 118)


# --- turns of a JPEG without loss (jpegtran) ------------------------------------------------------------------------

from system_core.image_tools.transform import JPEGTRAN  # noqa: E402

needs_jpegtran = pytest.mark.skipif(not JPEGTRAN.is_file(), reason="jpegtran is not in place: install/get_jpegtran.py")


def _photo(path: Path, size=(640, 480), **save) -> Path:
    image = Image.effect_noise(size, 50).convert("RGB")
    image.paste((200, 40, 40), (0, 0, size[0] // 4, size[1] // 4))
    image.save(path, quality=90, **save)
    return path


def _pixels(path: Path) -> bytes:
    with Image.open(path) as image:
        return image.convert("RGB").tobytes()


@needs_jpegtran
def test_four_quarter_turns_give_the_same_pixels_back(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    current = _photo(tmp_path / "a" / "photo.jpg", dpi=(300, 300))
    original = _pixels(current)
    for step in range(4):
        out = tmp_path / f"turn{step}"
        done = run("rotate", "--input", str(current), "--output", str(out), "--turn", "cw90", "--log-dir", str(tmp_path / "logs"))
        assert '"without_loss": 1' in done.stdout, done.stdout
        current = out / "photo.jpg"
    assert _pixels(current) == original
    with Image.open(current) as image:
        assert round(image.info["dpi"][0]) == 300


@needs_jpegtran
def test_the_turn_of_the_exif_and_the_turn_asked_are_made_one(tmp_path: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    exif = Image.Exif()
    exif[0x0112] = 6
    stored = _photo(folder / "phone.jpg", exif=exif)
    # Seen upright, the photograph is turned a quarter clockwise; a quarter counter-clockwise back is the picture as stored.
    done = run("rotate", "--input", str(folder), "--output", str(tmp_path / "out"), "--turn", "ccw90",
               "--log-dir", str(tmp_path / "logs"))
    assert '"without_loss": 1' in done.stdout
    made = tmp_path / "out" / "phone.jpg"
    assert _pixels(made) == _pixels(stored)
    with Image.open(made) as image:
        assert image.getexif().get(0x0112, 1) == 1


@needs_jpegtran
def test_a_jpeg_of_odd_sides_is_turned_by_its_pixels_and_said_so(tmp_path: Path) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    _photo(folder / "odd.jpg", size=(643, 479))
    done = run("rotate", "--input", str(folder), "--output", str(tmp_path / "out"), "--turn", "180",
               "--log-dir", str(tmp_path / "logs"))
    assert "odd.jpg: not turned without loss" in done.stdout and '"without_loss": 0' in done.stdout
    with Image.open(tmp_path / "out" / "odd.jpg") as image:
        assert image.size == (643, 479)


# Outside the ANSI code page of Windows (cp1251 here): Latin with marks, ideographs, emoji. "Фото" fits.
OUTSIDE = ("Фото ü.jpg", "写真.jpg", "Фото 写真 🙂.jpg")


@needs_jpegtran
@pytest.mark.parametrize("target", ["out", "вывод ü"])
def test_names_outside_the_code_page_are_turned_without_loss_too(tmp_path: Path, target: str) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    pictures = {name: _photo(folder / name) for name in ("plain.jpg", "Фото.jpg", *OUTSIDE)}
    out = tmp_path / target
    done = run("rotate", "--input", str(folder), "--output", str(out), "--turn", "cw90", "--log-dir", str(tmp_path / "logs"))
    assert '"without_loss": 5' in done.stdout and "Traceback" not in done.stdout + done.stderr, done.stdout + done.stderr
    # Every copy is checked against Pillow by the command itself; here - each in its place, turned, and no stand-in left.
    for name in pictures:
        with Image.open(out / name) as image:
            assert image.size == (480, 640), name
    assert sorted(path.name for path in out.iterdir()) == sorted(pictures)


@needs_jpegtran
def test_what_jpegtran_says_in_the_code_page_of_the_console_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from system_core.image_tools import transform

    photo = _photo(tmp_path / "Фото.jpg")
    said = "jpegtran: can't open Фото.jpg.writing for writing".encode("cp1251")
    monkeypatch.setattr(transform.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", said))
    assert transform.turn_without_loss(photo, tmp_path / "out" / "Фото.jpg", Image.Transpose.ROTATE_180, "strip_all") == \
        "jpegtran: jpegtran: can't open Фото.jpg.writing for writing"
