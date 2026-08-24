from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps

from .io_utils import discover_inputs, ensure_dir, img2pdf, fitz, open_image
from .pipeline import flatten_alpha, normalize_profile, save_image


def discover_pdfs(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() == '.pdf' else []
    return sorted([p for p in path.rglob('*.pdf') if p.is_file()])


def require_pymupdf() -> None:
    if fitz is None:
        raise RuntimeError('PDF import requires PyMuPDF')


def _page_stem(stem: str, page_num: int, total_pages: int) -> str:
    if total_pages > 1:
        return f'{page_num:03d}_{stem}'
    return stem


def _embedded_output_name(stem: str, page_num: int, total_pages: int, image_num: int, total_images: int, ext: str) -> str:
    base = _page_stem(stem, page_num, total_pages)
    if total_images > 1:
        return f'{base}_embedded_{image_num:03d}.{ext}'
    return f'{base}.{ext}'


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f'{path.stem}_{index}{path.suffix}')
        if not candidate.exists():
            return candidate
    raise RuntimeError(f'Could not allocate a unique output path for {path.name}')


def rasterize_pdf_to_images(
    input_path: Path,
    output_dir: Path,
    out_format: str = 'png',
    dpi: int = 300,
    jpeg_quality: int = 90,
    png_preset: str = 'balanced',
    metadata: str = 'preserve_dpi_color',
) -> list[Path]:
    require_pymupdf()
    ensure_dir(output_dir)
    written: list[Path] = []
    with fitz.open(str(input_path)) as doc:
        stem = input_path.stem
        total_pages = len(doc)
        for idx, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes('png')))
            image.load()
            target = output_dir / _page_stem(stem, idx, total_pages)
            out = save_image(
                image,
                target,
                out_format,
                jpeg_quality=jpeg_quality,
                png_preset=png_preset,
                metadata=metadata,
                dpi=dpi,
                alpha_bg='white',
            )
            written.append(out)
    return written


def normalize_pdf_to_pdf(
    input_path: Path,
    output_pdf: Path,
    target_profile: str = 'srgb',
    cmyk_profile_path: str | None = None,
    srgb_profile_mode: str = 'colororg',
    srgb_profile_path: str | None = None,
    embed_srgb_profile: bool = True,
    embed_cmyk_profile: bool = False,
    embed_pdf_image_profile: bool = True,
    dpi: int = 300,
    alpha_bg: str = 'white',
) -> Path:
    require_pymupdf()
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='audion_norm_pdf_') as tmp_dir:
        temp_root = Path(tmp_dir)
        pages_dir = temp_root / 'pages'
        ensure_dir(pages_dir)
        page_paths: list[Path] = []
        with fitz.open(str(input_path)) as doc:
            stem = input_path.stem
            for idx, page in enumerate(doc, start=1):
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes('png')))
                image.load()
                normalized = normalize_profile(
                    image,
                    target_profile,
                    cmyk_profile_path,
                    alpha_bg,
                    srgb_profile_mode=srgb_profile_mode,
                    srgb_profile_path=srgb_profile_path,
                    embed_srgb_profile=embed_srgb_profile,
                    embed_cmyk_profile=embed_cmyk_profile,
                )
                target = pages_dir / f'_{idx:03d}_{stem}'
                embedded_icc = normalized.info.get('icc_profile') if embed_pdf_image_profile else None
                page_paths.append(
                    save_image(
                        normalized,
                        target,
                        'tiff',
                        metadata='preserve_dpi_color' if embed_pdf_image_profile else 'strip_all',
                        dpi=dpi,
                        alpha_bg=alpha_bg,
                        embedded_icc=embedded_icc,
                    )
                )
        if img2pdf is not None:
            pdf_bytes = img2pdf.convert([str(p) for p in page_paths])
            output_pdf.write_bytes(pdf_bytes)
        else:
            _pil_save_pdf(page_paths, output_pdf, jpeg_quality=90)
    return output_pdf


def extract_embedded_images(
    input_path: Path,
    output_dir: Path,
    out_format: str = 'original',
    jpeg_quality: int = 90,
    png_preset: str = 'balanced',
    metadata: str = 'preserve_dpi_color',
    png_side_tiff: bool = False,
) -> list[Path]:
    require_pymupdf()
    ensure_dir(output_dir)
    out_format = (out_format or 'original').lower()
    written: list[Path] = []
    stem = input_path.stem
    with fitz.open(str(input_path)) as doc:
        total_pages = len(doc)
        for page_num, page in enumerate(doc, start=1):
            page_images: list[tuple[str, bytes]] = []
            seen_page: set[int] = set()
            for image_info in page.get_images(full=True):
                xref = int(image_info[0])
                if xref in seen_page:
                    continue
                seen_page.add(xref)
                extracted = doc.extract_image(xref)
                ext = extracted.get('ext', 'png').lower()
                if ext == 'jpeg':
                    ext = 'jpg'
                page_images.append((ext, extracted['image']))
            total_images = len(page_images)
            for image_num, (ext, image_bytes) in enumerate(page_images, start=1):
                target_ext = ext if out_format == 'original' else out_format
                out_path = _unique_path(output_dir / _embedded_output_name(stem, page_num, total_pages, image_num, total_images, target_ext))
                if out_format == 'original':
                    out_path.write_bytes(image_bytes)
                    written.append(out_path)
                    continue

                with Image.open(io.BytesIO(image_bytes)) as embedded:
                    embedded.load()
                    source_image = ImageOps.exif_transpose(embedded.copy())
                    image = source_image
                    if out_format == 'png' and png_side_tiff and (source_image.mode == 'CMYK' or source_image.info.get('icc_profile')):
                        side_path = _unique_path(out_path.with_suffix('.tiff'))
                        written.append(
                            save_image(
                                source_image,
                                side_path.with_suffix(''),
                                'tiff',
                                jpeg_quality=jpeg_quality,
                                png_preset=png_preset,
                                metadata=metadata,
                                alpha_bg='white',
                            )
                        )
                    if out_format == 'png' and source_image.mode == 'CMYK':
                        image = source_image.convert('RGB')
                    written.append(
                        save_image(
                            image,
                            out_path.with_suffix(''),
                            out_format,
                            jpeg_quality=jpeg_quality,
                            png_preset=png_preset,
                            metadata=metadata,
                            alpha_bg='white',
                        )
                    )
    return written


def export_largest_embedded_images(
    input_path: Path,
    output_dir: Path,
    out_format: str = 'png',
    jpeg_quality: int = 90,
    png_preset: str = 'balanced',
    metadata: str = 'preserve_dpi_color',
) -> list[Path]:
    require_pymupdf()
    ensure_dir(output_dir)
    written: list[Path] = []
    stem = input_path.stem
    with fitz.open(str(input_path)) as doc:
        total_pages = len(doc)
        for page_num, page in enumerate(doc, start=1):
            page_candidates: list[tuple[int, int, Image.Image]] = []
            seen_page: set[int] = set()
            for image_info in page.get_images(full=True):
                xref = int(image_info[0])
                if xref in seen_page:
                    continue
                seen_page.add(xref)
                extracted = doc.extract_image(xref)
                with Image.open(io.BytesIO(extracted['image'])) as embedded:
                    embedded.load()
                    page_candidates.append(
                        (
                            embedded.width * embedded.height,
                            len(extracted['image']),
                            ImageOps.exif_transpose(embedded.copy()),
                        )
                    )
            if not page_candidates:
                continue
            _, _, image = max(page_candidates, key=lambda item: (item[0], item[1]))
            target = output_dir / _page_stem(stem, page_num, total_pages)
            written.append(
                save_image(
                    image,
                    target,
                    out_format,
                    jpeg_quality=jpeg_quality,
                    png_preset=png_preset,
                    metadata=metadata,
                    alpha_bg='white',
                )
            )
    return written


def _collect_image_inputs(path: Path) -> list[Path]:
    files = discover_inputs(path)
    return [p for p in files if p.suffix.lower() != '.pdf']


def _pil_save_pdf(image_paths: list[Path], output_pdf: Path, jpeg_quality: int = 90, dpi: int | None = None) -> str:
    pages: list[Image.Image] = []
    for src in image_paths:
        im = ImageOps.exif_transpose(open_image(src))
        im = flatten_alpha(im, 'white').convert('RGB')
        pages.append(im)
    if not pages:
        raise RuntimeError('No supported images found for PDF export')
    first, rest = pages[0], pages[1:]
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    save_kwargs = {'format': 'PDF', 'save_all': True, 'append_images': rest, 'quality': jpeg_quality}
    if dpi is not None:
        save_kwargs['resolution'] = dpi
    first.save(output_pdf, **save_kwargs)
    return 'pillow'


def images_to_pdf_from_paths(
    image_paths: list[Path],
    output_pdf: Path,
    mode: str = 'lossless',
    jpeg_quality: int = 90,
    preserve_icc: bool = True,
    dpi: int | None = None,
) -> dict:
    if not image_paths:
        raise RuntimeError('No supported images found for PDF export')
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    backend = 'img2pdf' if img2pdf is not None else 'pillow'
    mode = (mode or 'lossless').lower()

    if mode == 'lossless':
        if img2pdf is not None:
            kwargs = {}
            if dpi is not None:
                kwargs['layout_fun'] = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
            pdf_bytes = img2pdf.convert([str(p) for p in image_paths], **kwargs)
            output_pdf.write_bytes(pdf_bytes)
            payload = {'backend': 'img2pdf', 'mode': 'lossless', 'count': len(image_paths), 'output': str(output_pdf)}
            if dpi is not None:
                payload['dpi'] = dpi
            return payload
        used = _pil_save_pdf(image_paths, output_pdf, jpeg_quality=90, dpi=dpi)
        payload = {'backend': used, 'mode': 'lossless-fallback', 'count': len(image_paths), 'output': str(output_pdf)}
        if dpi is not None:
            payload['dpi'] = dpi
        return payload

    if mode not in {'jpg75', 'jpg90'}:
        raise ValueError(f'Unsupported PDF export mode: {mode}')

    temp_quality = 75 if mode == 'jpg75' else 90
    if img2pdf is not None:
        with tempfile.TemporaryDirectory(prefix='audion_img2pdf_') as tmp_dir:
            temp_paths: list[str] = []
            for idx, src in enumerate(image_paths, start=1):
                image = ImageOps.exif_transpose(open_image(src))
                image_dpi = (dpi, dpi) if dpi is not None else image.info.get('dpi', (72, 72))
                jpeg = flatten_alpha(image, 'white')
                temp_path = Path(tmp_dir) / f'{idx:04d}.jpg'
                save_kwargs = {'format': 'JPEG', 'quality': temp_quality, 'optimize': True, 'dpi': image_dpi}
                if preserve_icc:
                    icc = image.info.get('icc_profile')
                    if icc:
                        save_kwargs['icc_profile'] = icc
                jpeg.save(temp_path, **save_kwargs)
                temp_paths.append(str(temp_path))
            kwargs = {}
            if dpi is not None:
                kwargs['layout_fun'] = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
            pdf_bytes = img2pdf.convert(temp_paths, **kwargs)
            output_pdf.write_bytes(pdf_bytes)
            payload = {'backend': 'img2pdf', 'mode': mode, 'count': len(image_paths), 'output': str(output_pdf)}
            if dpi is not None:
                payload['dpi'] = dpi
            return payload

    used = _pil_save_pdf(image_paths, output_pdf, jpeg_quality=temp_quality, dpi=dpi)
    payload = {'backend': used, 'mode': mode + '-fallback', 'count': len(image_paths), 'output': str(output_pdf)}
    if dpi is not None:
        payload['dpi'] = dpi
    return payload


def images_to_pdf(
    input_path: Path,
    output_pdf: Path,
    mode: str = 'lossless',
    jpeg_quality: int = 90,
    preserve_icc: bool = True,
    dpi: int | None = None,
) -> dict:
    return images_to_pdf_from_paths(
        _collect_image_inputs(input_path),
        output_pdf,
        mode=mode,
        jpeg_quality=jpeg_quality,
        preserve_icc=preserve_icc,
        dpi=dpi,
    )
