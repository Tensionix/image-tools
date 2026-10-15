from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile

from PIL import Image

from .models import ALL_RECOGNIZED, KNOWN_IMAGE_EXTENSIONS, ScanItem, ScanResult


_PIL_FORMAT_TO_EXTENSION = {
    "JPEG": "jpeg",
    "JPG": "jpg",
    "PNG": "png",
    "GIF": "gif",
    "BMP": "bmp",
    "TIF": "tif",
    "TIFF": "tiff",
}


def _detect_package_type(names: list[str]) -> str:
    if any(name.startswith("word/") for name in names):
        return "docx"
    if any(name.startswith("ppt/") for name in names):
        return "pptx"
    return "unknown"


def _iter_media_paths(names: list[str]) -> list[str]:
    return [
        name for name in names
        if name.lower().startswith(("word/media/", "ppt/media/"))
           and not name.endswith("/")
           and Path(name).suffix.lower().lstrip(".") in KNOWN_IMAGE_EXTENSIONS
    ]


def _has_transparency(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA"):
        return True
    if image.mode == "P":
        return "transparency" in image.info
    return False


def _normalize_format(image: Image.Image, extension: str) -> str:
    pil_format = (image.format or "").upper()
    normalized = _PIL_FORMAT_TO_EXTENSION.get(pil_format)
    if normalized:
        return normalized
    return extension or "unknown"


def scan_document(path: str | Path) -> ScanResult:
    doc_path = Path(path).resolve()
    result = ScanResult(document_path=doc_path, package_type="unknown")
    try:
        with ZipFile(doc_path, "r") as zf:
            names = zf.namelist()
            result.package_type = _detect_package_type(names)
            for package_path in _iter_media_paths(names):
                file_name = Path(package_path).name
                extension = Path(package_path).suffix.lower().lstrip(".")
                info = zf.getinfo(package_path)
                item = ScanItem(
                    document_path=doc_path,
                    package_path=package_path,
                    file_name=file_name,
                    extension=extension,
                    detected_format=extension or "unknown",
                    width=None,
                    height=None,
                    encoded_size_bytes=info.file_size,
                    zip_size_bytes=info.compress_size,
                    supported=extension in ALL_RECOGNIZED,
                )
                try:
                    with zf.open(package_path) as fh:
                        data = fh.read()
                    with Image.open(BytesIO(data)) as img:
                        item.detected_format = _normalize_format(img, extension)
                        item.width, item.height = img.size
                        item.has_transparency = _has_transparency(img)
                        item.supported = item.detected_format in ALL_RECOGNIZED
                        item.note = f"Pillow format: {img.format or 'unknown'}"
                except Exception as exc:
                    item.note = f"Could not decode image: {exc}"
                    if not item.supported:
                        result.unsupported_count += 1
                    result.items.append(item)
                    continue

                if not item.supported:
                    result.unsupported_count += 1
                result.items.append(item)
            if result.package_type == "unknown":
                result.errors.append("Input ZIP package is not recognized as DOCX or PPTX.")
    except BadZipFile:
        result.errors.append("Input file is not a valid ZIP/OOXML package.")
    except FileNotFoundError:
        result.errors.append("Input file not found.")
    except Exception as exc:
        result.errors.append(str(exc))
    return result
