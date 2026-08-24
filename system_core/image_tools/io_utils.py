
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import Image

from .constants import SUPPORTED_EXTENSIONS, HEIF_EXTENSIONS, RAW_EXTENSIONS

DEFAULT_MAX_IMAGE_PIXELS = 1_000_000_000
Image.MAX_IMAGE_PIXELS = DEFAULT_MAX_IMAGE_PIXELS

try:
    from pillow_heif import register_heif_opener
except Exception:
    register_heif_opener = None

try:
    import rawpy
except Exception:
    rawpy = None

try:
    import fitz
except Exception:
    fitz = None

try:
    import img2pdf
except Exception:
    img2pdf = None


if register_heif_opener is not None:
    try:
        register_heif_opener()
    except Exception:
        pass


@dataclass
class AdapterStatus:
    extension: str
    mode: str
    detail: str


def configure_image_pixel_guard(allow_huge_images: bool = False) -> None:
    if allow_huge_images:
        Image.MAX_IMAGE_PIXELS = None
        print(
            'WARNING: Pillow decompression-bomb guard disabled by --allow-huge-images.',
            file=sys.stderr,
            flush=True,
        )
    else:
        Image.MAX_IMAGE_PIXELS = DEFAULT_MAX_IMAGE_PIXELS


def discover_inputs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = []
    for p in path.rglob('*'):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(p)
    return sorted(files)


def adapter_report() -> list[AdapterStatus]:
    rows: list[AdapterStatus] = []
    registered = Image.registered_extensions()
    readable_formats = set(Image.OPEN)
    if fitz is None:
        rows.append(AdapterStatus('.pdf', 'optional', 'PyMuPDF missing for PDF raster/extract'))
    elif img2pdf is None:
        rows.append(AdapterStatus('.pdf', 'bridge', 'PyMuPDF available, img2pdf missing for preferred PDF export'))
    else:
        rows.append(AdapterStatus('.pdf', 'bridge', 'PyMuPDF + img2pdf available'))
    for ext in sorted(SUPPORTED_EXTENSIONS):
        if ext in HEIF_EXTENSIONS:
            if register_heif_opener is None:
                rows.append(AdapterStatus(ext, 'optional', 'pillow-heif missing'))
            elif registered.get(ext) in readable_formats:
                rows.append(AdapterStatus(ext, 'registered', f'Pillow reader registered as {registered.get(ext)} via pillow-heif'))
            else:
                rows.append(AdapterStatus(ext, 'maybe', 'pillow-heif available, but extension is not registered as readable'))
        elif ext in RAW_EXTENSIONS:
            if rawpy is None:
                rows.append(AdapterStatus(ext, 'optional', 'rawpy missing'))
            else:
                rows.append(AdapterStatus(ext, 'extended', 'rawpy available'))
        else:
            registered_format = registered.get(ext)
            if registered_format in readable_formats:
                rows.append(AdapterStatus(ext, 'registered', f'Pillow reader registered as {registered_format}'))
            elif registered_format:
                rows.append(AdapterStatus(ext, 'maybe', f'Pillow extension registered as {registered_format}, reader not available'))
            else:
                rows.append(AdapterStatus(ext, 'unsupported in this runtime', 'No Pillow reader registered for this extension'))
    return rows


def open_image(path: Path) -> Image.Image:
    suffix = path.suffix.lower()

    if suffix in RAW_EXTENSIONS:
        if rawpy is None:
            raise RuntimeError('RAW support requires rawpy')
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        return Image.fromarray(rgb)

    image = Image.open(path)
    image.load()
    return image


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def unique_target_path(base: Path, suffix: str) -> Path:
    candidate = base.with_suffix(suffix)
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = base.with_name(f"{base.name}_{index}").with_suffix(suffix)
        if not candidate.exists():
            return candidate
        index += 1


def write_json_report(log_dir: Path, payload: dict) -> Path:
    ensure_dir(log_dir)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = log_dir / f'run_{stamp}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path
