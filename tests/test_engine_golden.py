"""The engine against a record of itself.

Until 3.0.0 the engine had no test: only the window was checked to draw. Every command of
system_core\\main.py is run here on pictures made on the spot, and what it left in the output is
compared with tests\\golden\\engine.json - the count of files, their format, pixels, mode, DPI and
frames; the pixels themselves for a lossless format, their mean for a lossy one or for a picture
with text on it (a font of the machine draws that).

The record was written from the engine as it was copied (2.4.3). To write it anew:
    set AUDION_GOLDEN_WRITE=1 && runtime\\python.exe -m pytest tests\\test_engine_golden.py
To run the same cases against another copy of the program (the reference beside this folder):
    set AUDION_ENGINE_ROOT=E:\\TOOLS\\Audion Image Tools NiceGUI
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageStat

PROJECT = Path(__file__).resolve().parent.parent
ENGINE = Path(os.environ.get("AUDION_ENGINE_ROOT") or PROJECT)
GOLDEN = Path(__file__).resolve().parent / "golden" / "engine.json"
WRITE = os.environ.get("AUDION_GOLDEN_WRITE") == "1"
LOSSLESS = {"PNG", "TIFF", "BMP"}
PICTURES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif", ".avif"}

# --- the pictures every case reads ---------------------------------------------------------


def _photo(size: tuple[int, int], seed: int) -> Image.Image:
    """A picture with gradients and grain: something a resampler and a JPEG coder have work with."""
    width, height = size
    noise = random.Random(seed)
    picture = Image.new("RGB", size)
    pixels = picture.load()
    for y in range(height):
        for x in range(width):
            grain = noise.randrange(-12, 13)
            pixels[x, y] = (
                max(0, min(255, int(255 * x / width) + grain)),
                max(0, min(255, int(255 * y / height) + grain)),
                max(0, min(255, int(127 + 120 * math.sin((x + y) / 37.0)) + grain)),
            )
    return picture


@pytest.fixture(scope="session")
def samples(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("samples")
    for folder in ("photos/sub", "frame", "scan", "tiff", "cmyk", "pdf", "single", "alpha"):
        (root / folder).mkdir(parents=True)

    photo = _photo((1200, 800), 7)
    photo.save(root / "photos" / "photo.jpg", quality=92, dpi=(72, 72))
    photo.save(root / "single" / "photo.jpg", quality=92, dpi=(72, 72))
    _photo((600, 400), 11).save(root / "photos" / "sub" / "nested.jpg", quality=92, dpi=(96, 96))

    logo = Image.new("RGBA", (640, 480), (0, 0, 0, 0))
    ImageDraw.Draw(logo).ellipse((80, 60, 560, 420), fill=(200, 40, 40, 255), outline=(20, 20, 20, 255), width=6)
    logo.save(root / "alpha" / "logo.png", dpi=(150, 150))

    frame = Image.new("RGB", (900, 700), (30, 120, 60))
    frame.paste(_photo((780, 580), 13), (60, 60))
    frame.save(root / "frame" / "frame.png", dpi=(300, 300))

    scan = Image.new("RGB", (1000, 1400), (255, 255, 255))
    draw = ImageDraw.Draw(scan)
    draw.rectangle((180, 240, 820, 1100), fill=(40, 40, 40))
    draw.rectangle((260, 320, 740, 700), fill=(180, 60, 20))
    scan.save(root / "scan" / "scan.png", dpi=(300, 300))

    frames = [_photo((500, 360), seed) for seed in (21, 22, 23)]
    frames[0].save(root / "tiff" / "pages.tif", save_all=True, append_images=frames[1:], compression="tiff_deflate", dpi=(200, 200))

    photo.convert("CMYK").save(root / "cmyk" / "cmyk.jpg", quality=90, dpi=(300, 300))

    import img2pdf

    first, second = root / "pdf" / "_one.jpg", root / "pdf" / "_two.png"
    photo.save(first, quality=90, dpi=(150, 150))
    scan.save(second, dpi=(300, 300))
    (root / "pdf" / "print.pdf").write_bytes(img2pdf.convert([str(first), str(second)]))
    first.unlink()
    second.unlink()
    return root


# --- the cases -----------------------------------------------------------------------------

# id, the command, its arguments. {S} - the samples, {O} - the output of the case.
# soft: text is drawn with a font of the machine, so the pixels are told by their mean.
CASES: list[dict] = [
    {"id": "convert_jpg", "run": ["convert", "--input", "{S}/photos", "--output", "{O}", "--to", "jpg"]},
    {"id": "convert_png", "run": ["convert", "--input", "{S}/photos", "--output", "{O}", "--to", "png"]},
    {"id": "convert_tiff_dpi", "run": ["convert", "--input", "{S}/photos", "--output", "{O}", "--to", "tiff", "--set-dpi", "300"]},
    {"id": "convert_webp", "run": ["convert", "--input", "{S}/photos", "--output", "{O}", "--to", "webp", "--jpeg-quality", "75"]},
    {"id": "convert_alpha_to_jpg", "run": ["convert", "--input", "{S}/alpha", "--output", "{O}", "--to", "jpg", "--jpeg-quality", "90"]},
    {"id": "convert_one_file", "run": ["convert", "--input", "{S}/single/photo.jpg", "--output", "{O}", "--to", "png"]},
    {"id": "convert_strip_all", "run": ["convert", "--input", "{S}/photos", "--output", "{O}", "--to", "jpg", "--metadata", "strip_all"]},
    {"id": "normalize_srgb", "run": ["normalize", "--input", "{S}/cmyk", "--output", "{O}", "--to", "jpg", "--target-profile", "srgb"]},
    {"id": "normalize_keep", "run": ["normalize", "--input", "{S}/cmyk", "--output", "{O}", "--to", "tiff", "--target-profile", "keep"]},
    {"id": "normalize_cmyk", "run": ["normalize", "--input", "{S}/photos", "--output", "{O}", "--to", "tiff", "--target-profile", "cmyk"]},
    {"id": "grayscale_png", "run": ["grayscale", "--input", "{S}/photos", "--output", "{O}", "--to", "png"]},
    {"id": "screen_1080_crop", "run": ["resize-screen", "--input", "{S}/photos", "--output", "{O}", "--to", "png", "--target", "1080p", "--mode", "crop"]},
    {"id": "screen_1440_contain", "run": ["resize-screen", "--input", "{S}/photos", "--output", "{O}", "--to", "png", "--target", "1440p", "--mode", "contain"]},
    {"id": "screen_2160_pad", "run": ["resize-screen", "--input", "{S}/single", "--output", "{O}", "--to", "jpg", "--target", "2160p", "--mode", "pad", "--jpeg-quality", "90"]},
    {"id": "aspect_169_crop", "run": ["aspect", "--input", "{S}/photos", "--output", "{O}", "--to", "png", "--ratio", "16:9", "--mode", "crop"]},
    {"id": "aspect_a4_pad", "run": ["aspect", "--input", "{S}/single", "--output", "{O}", "--to", "png", "--ratio", "a4-portrait", "--mode", "pad"]},
    {"id": "trim_border", "run": ["trim-border", "--input", "{S}/frame", "--output", "{O}", "--to", "png", "--tolerance", "10"]},
    {"id": "trim_border_margin", "run": ["trim-border", "--input", "{S}/frame", "--output", "{O}", "--to", "png", "--tolerance", "10", "--safety-margin-mm", "2"]},
    {"id": "smart_crop_white", "run": ["smart-crop-white", "--input", "{S}/scan", "--output", "{O}", "--to", "png", "--tolerance", "10"]},
    {"id": "smart_crop_white_margin", "run": ["smart-crop-white", "--input", "{S}/scan", "--output", "{O}", "--to", "png", "--safety-margin-mm", "3"]},
    {"id": "watermark_corner", "soft": True, "run": ["watermark", "--input", "{S}/single", "--output", "{O}", "--to", "png", "--text", "SAMPLE", "--color", "204,0,0"]},
    {"id": "watermark_diagonal", "soft": True, "run": ["watermark", "--input", "{S}/single", "--output", "{O}", "--to", "png", "--text", "SAMPLE", "--watermark-mode", "diagonal", "--color", "#0066cc"]},
    {"id": "contact_sheet", "soft": True, "run": ["contact-sheet", "--input", "{S}/photos", "--output", "{O}/contact_sheet.png", "--columns", "2", "--thumb-size", "320x240"]},
    {"id": "photo_sheet_shelf", "soft": True, "run": ["photo-sheet-width", "--input", "{S}/photos", "--output", "{O}", "--page-width-mm", "600", "--dpi", "300", "--layout", "shelf", "--recursive"]},
    {"id": "photo_sheet_cut_lines", "soft": True, "run": ["photo-sheet-width", "--input", "{S}/photos", "--output", "{O}", "--page-width-mm", "600", "--dpi", "300", "--layout", "cut-lines", "--recursive"]},
    {"id": "tile_sheet_a4", "soft": True, "run": ["tile-sheet", "--input", "{S}/alpha/logo.png", "--output", "{O}", "--paper", "a4", "--to", "png", "--size-mode", "width", "--item-width-mm", "40"]},
    {"id": "split_tiff", "run": ["split-tiff", "--input", "{S}/tiff", "--output", "{O}"]},
    {"id": "plotter_size_short", "run": ["plotter-size", "--input", "{S}/photos", "--output", "{O}", "--to", "png", "--side", "short", "--target-mm", "900"]},
    {"id": "plotter_dpi_only", "run": ["plotter-dpi-only", "--input", "{S}/photos", "--output", "{O}", "--to", "tiff", "--dpi", "300"]},
    {"id": "split_strips", "run": ["split-half", "--input", "{S}/single", "--output", "{O}", "--to", "png", "--mode", "strips", "--orientation", "vertical", "--parts", "3"]},
    {"id": "split_grid", "run": ["split-half", "--input", "{S}/single", "--output", "{O}", "--to", "png", "--mode", "grid", "--rows", "2", "--columns", "3"]},
    {"id": "pdf_rasterize_150", "run": ["pdf-rasterize", "--input", "{S}/pdf", "--output", "{O}", "--to", "png", "--dpi", "150"]},
    {"id": "pdf_export_embedded", "run": ["pdf-export", "--input", "{S}/pdf", "--output", "{O}", "--to", "png", "--mode", "embedded"]},
    {"id": "pdf_export_render", "run": ["pdf-export", "--input", "{S}/pdf", "--output", "{O}", "--to", "jpg", "--mode", "render", "--dpi", "100"]},
    {"id": "pdf_extract_original", "run": ["pdf-extract-embedded", "--input", "{S}/pdf", "--output", "{O}", "--to", "original", "--layout", "flat"]},
    {"id": "pdf_extract_png_folders", "run": ["pdf-extract-embedded", "--input", "{S}/pdf", "--output", "{O}", "--to", "png", "--layout", "folders"]},
    # With --bundle all the output is the PDF itself, with --bundle folders it is a folder.
    {"id": "images_to_pdf_lossless", "run": ["images-to-pdf", "--input", "{S}/photos", "--output", "{O}/all.pdf", "--mode", "lossless", "--bundle", "all"]},
    {"id": "images_to_pdf_jpg75_folders", "run": ["images-to-pdf", "--input", "{S}/photos", "--output", "{O}", "--mode", "jpg75", "--bundle", "folders"]},
    {"id": "downscale_50", "run": ["downscale-percent", "--input", "{S}/photos", "--output", "{O}", "--to", "png", "--scale-mode", "percent-50"]},
    {"id": "downscale_custom_dpi", "run": ["downscale-percent", "--input", "{S}/photos", "--output", "{O}", "--to", "png", "--scale-mode", "custom", "--custom-percent", "75", "--print-size-mode", "dpi", "--algorithm", "bicubic", "--unsharp", "False"]},
    {"id": "downscale_target_mb", "run": ["downscale-percent", "--input", "{S}/single", "--output", "{O}", "--to", "jpg", "--scale-mode", "target-mb", "--target-mb", "0.05", "--jpeg-quality", "75"]},
    {"id": "formats", "run": ["formats"]},
    {"id": "info", "run": ["info"]},
]


# --- what a case left ----------------------------------------------------------------------


def _picture(path: Path, soft: bool) -> dict:
    if path.suffix.lower() in {".heic", ".heif"}:
        import pillow_heif

        pillow_heif.register_heif_opener()
    with Image.open(path) as picture:
        told: dict = {"format": picture.format, "size": list(picture.size), "mode": picture.mode, "frames": getattr(picture, "n_frames", 1)}
        dpi = picture.info.get("dpi")
        told["dpi"] = [round(float(dpi[0])), round(float(dpi[1]))] if dpi else None
        told["icc"] = bool(picture.info.get("icc_profile"))
        flat = picture.convert("RGBA" if picture.mode in {"RGBA", "LA", "P"} else "RGB")
        if picture.format in LOSSLESS and not soft:
            told["pixels"] = hashlib.sha1(flat.tobytes()).hexdigest()[:16]
        else:
            told["mean"] = [round(value) for value in ImageStat.Stat(flat.convert("RGB")).mean]
    return told


def _document(path: Path) -> dict:
    import pikepdf

    with pikepdf.open(path) as pdf:
        pages = [[round(float(value)) for value in page.MediaBox] for page in pdf.pages]
        pictures = sum(1 for obj in pdf.objects if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == "/Image")
    return {"format": "PDF", "pages": pages, "pictures": pictures}


def _left(folder: Path, soft: bool) -> dict:
    found: dict = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(folder).as_posix()
        suffix = path.suffix.lower()
        if suffix in PICTURES:
            found[name] = _picture(path, soft)
        elif suffix == ".pdf":
            found[name] = _document(path)
        else:
            found[name] = {"format": suffix.lstrip(".") or "file"}
    return found


def _run(case: dict, samples: Path, out: Path, logs: Path) -> tuple[int, str]:
    out.mkdir(parents=True, exist_ok=True)
    args = [part.replace("{S}", str(samples)).replace("{O}", str(out)).replace("/", os.sep) if "{" in part else part for part in case["run"]]
    if case["run"][0] not in {"formats", "info"}:
        args += ["--log-dir", str(logs)]
    python = ENGINE / "runtime" / "python.exe"
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    done = subprocess.run([str(python), "-u", str(ENGINE / "system_core" / "main.py"), *args], cwd=str(ENGINE), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _close(recorded: dict, now: dict) -> list[str]:
    """What differs. A mean may move by two: a coder of another build rounds its own way."""
    differs: list[str] = []
    for name in sorted(set(recorded) | set(now)):
        if name not in recorded or name not in now:
            differs.append(f"{name}: {'new' if name not in recorded else 'gone'}")
            continue
        was, became = dict(recorded[name]), dict(now[name])
        mean_was, mean_now = was.pop("mean", None), became.pop("mean", None)
        if was != became:
            differs.append(f"{name}: {was} -> {became}")
        elif (mean_was is None) != (mean_now is None) or (mean_was and any(abs(a - b) > 2 for a, b in zip(mean_was, mean_now))):
            differs.append(f"{name}: mean {mean_was} -> {mean_now}")
    return differs


@pytest.fixture(scope="session")
def golden() -> dict:
    if GOLDEN.is_file():
        return json.loads(GOLDEN.read_text(encoding="utf-8"))
    return {}


_written: dict = {}


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_the_engine_does_what_it_did(case: dict, samples: Path, tmp_path: Path, golden: dict) -> None:
    code, said = _run(case, samples, tmp_path / "out", tmp_path / "logs")
    now = {"exit": code, "left": _left(tmp_path / "out", bool(case.get("soft")))}
    if WRITE:
        assert code == 0, f"a case that fails is not a record: {said[-1500:]}"
        _written[case["id"]] = now
        return
    assert case["id"] in golden, "no record of this case: write it with AUDION_GOLDEN_WRITE=1"
    recorded = golden[case["id"]]
    assert now["exit"] == recorded["exit"], said[-1500:]
    differs = _close(recorded["left"], now["left"])
    assert not differs, "\n".join(differs[:20])


def test_the_record_is_written_whole() -> None:
    """Last in the file: with AUDION_GOLDEN_WRITE=1 the cases above are put on disk here."""
    if not WRITE:
        assert GOLDEN.is_file(), "tests\\golden\\engine.json is not there"
        return
    assert set(_written) == {case["id"] for case in CASES}, "some case did not run: the record would be short"
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(_written, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
