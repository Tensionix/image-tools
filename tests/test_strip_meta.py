"""Pictures without EXIF and GPS: the blocks of what a picture tells go, the picture stays byte for byte."""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageCms

from system_core.image_tools.strip_meta import strip_jpeg, strip_png, strip_webp

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "system_core" / "main.py"
XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/></x:xmpmeta>'


def _told(turn: int = 6) -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "A camera"
    exif[0x0110] = "Model 7"
    exif[0x0132] = "2026:10:14 12:00:00"
    exif[0x0112] = turn
    exif[0x011A] = 300
    exif[0x011B] = 300
    exif[0x0128] = 2
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (55.0, 1.0, 2.0)
    return exif


def _photo() -> Image.Image:
    image = Image.effect_noise((96, 64), 40).convert("RGB")
    image.paste((200, 40, 40), (10, 10, 40, 30))
    return image


def _jpeg(jfif_density: bool) -> bytes:
    out = io.BytesIO()
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    kwargs = {"dpi": (300, 300)} if jfif_density else {}
    _photo().save(out, "JPEG", quality=90, exif=_told(), icc_profile=srgb, comment=b"a secret", xmp=XMP, **kwargs)
    return out.getvalue()


def _pixels(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        return image.tobytes()


def test_a_jpeg_loses_gps_camera_date_xmp_comment_and_keeps_its_turn_profile_and_pixels() -> None:
    before = _jpeg(jfif_density=True)
    after, gone = strip_jpeg(before)
    assert {"EXIF", "XMP", "comment"} <= set(gone)
    assert _pixels(after) == _pixels(before)
    with Image.open(io.BytesIO(after)) as image:
        exif = image.getexif()
        assert dict(exif) == {0x0112: 6}, dict(exif)
        assert not exif.get_ifd(0x8825)
        assert image.info.get("icc_profile") and not image.info.get("comment") and not image.info.get("xmp")
        assert round(image.info["dpi"][0]) == 300


def test_a_jpeg_that_states_its_density_in_exif_alone_keeps_it_there() -> None:
    before = _jpeg(jfif_density=False)
    after, _gone = strip_jpeg(before)
    with Image.open(io.BytesIO(after)) as image:
        assert set(image.getexif()) == {0x0112, 0x011A, 0x011B, 0x0128}
        assert round(image.info["dpi"][0]) == 300


def test_an_upright_picture_keeps_no_exif_at_all() -> None:
    out = io.BytesIO()
    _photo().save(out, "JPEG", quality=90, exif=_told(turn=1), dpi=(300, 300))
    after, _gone = strip_jpeg(out.getvalue())
    assert b"Exif\0\0" not in after


def test_the_pictures_a_phone_writes_after_the_photograph_go() -> None:
    out = io.BytesIO()
    first, second = _photo(), _photo().rotate(90, expand=True)
    first.save(out, "MPO", save_all=True, append_images=[second], exif=_told(turn=1), quality=90)
    before = out.getvalue()
    with Image.open(io.BytesIO(before)) as image:
        assert image.format == "MPO" and image.n_frames == 2
    after, gone = strip_jpeg(before + b"SEFT trailer with Exif and GPS")
    assert "MPF" in gone and "data after the picture" in gone
    assert b"GPS" not in after and b"SEFT" not in after and after.endswith(bytes([0xFF, 0xD9]))
    with Image.open(io.BytesIO(after)) as image:
        assert image.format == "JPEG" and getattr(image, "n_frames", 1) == 1
    with Image.open(io.BytesIO(before)) as image:
        image.seek(0)
        assert image.tobytes() == _pixels(after)


def test_a_png_loses_its_texts_and_exif() -> None:
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Author", "Someone")
    info.add_itxt("XML:com.adobe.xmp", XMP.decode())
    out = io.BytesIO()
    _photo().save(out, "PNG", pnginfo=info, exif=_told(turn=1), dpi=(300, 300))
    after, gone = strip_png(out.getvalue())
    assert {"tEXt", "iTXt", "eXIf"} <= set(gone)
    assert _pixels(after) == _pixels(out.getvalue())
    with Image.open(io.BytesIO(after)) as image:
        assert not [key for key, value in image.info.items() if isinstance(value, str)] and not image.getexif()
        assert round(image.info["dpi"][0]) == 300


def test_a_webp_loses_exif_and_xmp() -> None:
    out = io.BytesIO()
    _photo().save(out, "WEBP", lossless=True, exif=_told(turn=1).tobytes(), xmp=XMP)
    after, gone = strip_webp(out.getvalue())
    assert set(gone) == {"EXIF", "XMP"}
    assert _pixels(after) == _pixels(out.getvalue())
    with Image.open(io.BytesIO(after)) as image:
        assert not image.getexif() and not image.info.get("xmp")


def test_the_console_command_copies_cleans_checks_and_names_what_it_passes_by(tmp_path: Path) -> None:
    source = tmp_path / "in"
    (source / "trip").mkdir(parents=True)
    original = _jpeg(jfif_density=True)
    (source / "trip" / "photo.jpg").write_bytes(original)
    _photo().save(source / "scan.tiff")
    done = subprocess.run([sys.executable, "-X", "utf8", str(MAIN), "strip-meta", "--input", str(source), "--output", str(tmp_path / "out"),
                           "--log-dir", str(tmp_path / "logs")], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 of 2 pictures without EXIF and GPS, checked; passed by: 1" in done.stdout
    # The line of a file of many carries its place in the batch: "[WARN 2/2] scan.tiff: ..." (core\lines.py).
    assert any(line.startswith("[WARN ") and "] scan.tiff: " in line for line in done.stdout.splitlines()), done.stdout
    with Image.open(tmp_path / "out" / "trip" / "photo.jpg") as image:
        assert not image.getexif().get_ifd(0x8825)
    assert (source / "trip" / "photo.jpg").read_bytes() == original
    done = subprocess.run([sys.executable, "-X", "utf8", str(MAIN), "strip-meta", "--input", str(source), "--output", str(source),
                           "--log-dir", str(tmp_path / "logs")], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 2
