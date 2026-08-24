
from __future__ import annotations

from pathlib import Path
import importlib
import os
import platform
import sys

REQUIRED_MODULES = [
    ("PIL", "Pillow"),
    ("tqdm", "tqdm"),
    ("pydantic", "pydantic"),
]

OPTIONAL_MODULES = [
    ("fitz", "PyMuPDF"),
    ("img2pdf", "img2pdf"),
    ("pillow_heif", "pillow-heif"),
    ("rawpy", "rawpy"),
    ("PIL.ImageCms", "Pillow ImageCms"),
]


def ansi_enabled() -> bool:
    return (
        'NO_COLOR' not in os.environ
        and (
            os.environ.get('AUDION_GUI_TERMINAL') == '1'
            or os.environ.get('FORCE_COLOR') == '1'
            or os.environ.get('CLICOLOR_FORCE') == '1'
            or sys.stdout.isatty()
        )
    )


def color(text: str, code: str) -> str:
    if not ansi_enabled():
        return text
    return f'\033[{code}m{text}\033[0m'


def info(label: str, value: object) -> None:
    print(f"{color('[INFO]', '36;1')} {label:<12}: {value}")


def check_module(import_name: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(import_name)
        version = getattr(mod, "__version__", "unknown")
        return True, str(version)
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


def detect_python_mode(root: Path) -> str:
    if (root / "runtime" / "python.exe").exists():
        return "portable-runtime"
    if (root / "runtime" / "python" / "python.exe").exists():
        return "portable-runtime"
    return "system-python"


def pillow_reader_registered(extension: str) -> tuple[bool, str]:
    try:
        from PIL import Image

        registered = Image.registered_extensions()
        readable_formats = set(Image.OPEN)
        image_format = registered.get(extension.lower())
        if image_format in readable_formats:
            return True, f"reader registered as {image_format}"
        if image_format:
            return False, f"extension registered as {image_format}, reader missing"
        return False, "reader not registered"
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


def heif_feature() -> tuple[bool, str]:
    ok, detail = check_module("pillow_heif")
    if not ok:
        return False, detail
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception as exc:
        return False, f"pillow-heif import OK, register failed: {exc.__class__.__name__}: {exc}"
    heic_ok, heic_detail = pillow_reader_registered(".heic")
    heif_ok, heif_detail = pillow_reader_registered(".heif")
    if heic_ok or heif_ok:
        return True, f"{detail}; .heic {heic_detail}; .heif {heif_detail}"
    return False, f"{detail}; .heic {heic_detail}; .heif {heif_detail}"


def feature_matrix() -> list[tuple[str, bool, str]]:
    fitz_ok, fitz_detail = check_module("fitz")
    img2pdf_ok, img2pdf_detail = check_module("img2pdf")
    raw_ok, raw_detail = check_module("rawpy")
    cms_ok, cms_detail = check_module("PIL.ImageCms")
    avif_ok, avif_detail = pillow_reader_registered(".avif")
    heif_ok, heif_detail = heif_feature()
    return [
        ("PDF rasterize", fitz_ok, fitz_detail),
        ("PDF embedded extract", fitz_ok, fitz_detail),
        ("Images-to-PDF lossless bridge", img2pdf_ok, img2pdf_detail),
        ("HEIC/HEIF", heif_ok, heif_detail),
        ("RAW", raw_ok, raw_detail),
        ("AVIF actual", avif_ok, avif_detail),
        ("ImageCms", cms_ok, cms_detail),
    ]


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    print(color("======================================================================", "36;1"))
    print(color("AUDION IMAGE TOOLS - DOCTOR", "36;1"))
    print(color("======================================================================", "36;1"))
    info("Project root", root)
    info("Executable", sys.executable)
    info("Python", sys.version.split()[0])
    info("Python mode", detect_python_mode(root))
    info("Platform", platform.platform())
    print()

    failed = False

    print(color("[Required modules]", "35;1"))
    for import_name, package_name in REQUIRED_MODULES:
        ok, detail = check_module(import_name)
        status = color("[OK]", "32;1") if ok else color("[FAIL]", "31;1")
        print(f"  - {package_name:<18} : {status} {detail}")
        if not ok:
            failed = True

    print()
    print(color("[Optional modules]", "35;1"))
    for import_name, package_name in OPTIONAL_MODULES:
        ok, detail = check_module(import_name)
        status = color("[OK]", "32;1") if ok else color("[MISS]", "33;1")
        print(f"  - {package_name:<18} : {status} {detail}")

    print()
    print(color("[Feature matrix]", "35;1"))
    for label, ok, detail in feature_matrix():
        status = color("[OK]", "32;1") if ok else color("[MISS]", "33;1")
        print(f"  - {label:<34} : {status} {detail}")

    print()
    if failed:
        print(color("[RESULT] One or more required modules are missing.", "31;1"))
        return 1

    print(color("[RESULT] Required environment looks good.", "32;1"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
