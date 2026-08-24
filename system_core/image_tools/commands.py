from __future__ import annotations

import json
import io
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageOps
try:
    from PIL import ImageCms
except Exception:
    ImageCms = None
from tqdm import tqdm

from .io_utils import adapter_report, discover_inputs, open_image, write_json_report
from .pdf_utils import (
    discover_pdfs,
    extract_embedded_images,
    export_largest_embedded_images,
    images_to_pdf,
    images_to_pdf_from_paths,
    normalize_pdf_to_pdf,
    rasterize_pdf_to_images,
)
from .photo_sheet import build_photo_sheet_by_width, load_photo_sheet_config, mode_config
from .tile_sheet import build_tile_sheets
from .pipeline import (
    KEEP_ICC,
    add_text_watermark,
    build_contact_sheet,
    dpi_for_print_side,
    fit_resize_to_target_bytes,
    grayscale_image,
    normalize_profile,
    ratio_size,
    resize_by_percent,
    resize_to_box,
    resize_to_screen,
    save_image,
    split_image_grid,
    split_image_strips,
    split_tiff_to_png,
    trim_border,
    trim_white_border,
)


def _frame_count(image: Image.Image) -> int:
    try:
        return max(1, int(getattr(image, 'n_frames', 1) or 1))
    except Exception:
        return 1


def _multi_frame_warning(src: Path, frame_count: int) -> str:
    if frame_count <= 1:
        return ''
    suffix = src.suffix.lower()
    if suffix in {'.tif', '.tiff'}:
        return f'WARNING: multi-frame image detected ({frame_count} frames); only the first frame was converted. Use split-tiff for all frames.'
    if suffix in {'.gif', '.webp'}:
        return f'WARNING: animated/multi-frame image detected ({frame_count} frames); only the first frame was converted.'
    return f'WARNING: multi-frame image detected ({frame_count} frames); only the first frame was converted.'


def _batch_summary(results: list[dict]) -> dict:
    warnings = sum(1 for item in results if item.get('warning'))
    errors = sum(1 for item in results if item.get('error'))
    payload = {'processed': len(results) - errors}
    if warnings:
        payload['warnings'] = warnings
    if errors:
        payload['errors'] = errors
    return payload


def _error_result(src: Path, exc: Exception) -> dict:
    return {
        'input': str(src),
        'error': f'{exc.__class__.__name__}: {exc}',
    }


def _has_errors(results: list[dict]) -> bool:
    return any(item.get('error') for item in results)


def _effective_workers(args, item_count: int) -> int:
    if item_count <= 1:
        return 1
    try:
        requested = int(getattr(args, 'workers', 0) or 0)
    except (TypeError, ValueError):
        requested = 0
    if requested <= 0:
        requested = min(8, os.cpu_count() or 1)
    return max(1, min(requested, item_count))


def _result_sort_key(item: dict) -> str:
    return str(item.get('input') or '')


def _emit_result_notice(item: dict) -> None:
    src = item.get('input', '')
    if item.get('warning'):
        tqdm.write(f'{src}: {item["warning"]}')
    if item.get('error'):
        tqdm.write(f'{src}: ERROR: {item["error"]}')


def _relative_output_path(input_path: Path, src: Path) -> Path:
    if input_path.is_dir():
        return src.relative_to(input_path)
    return Path(src.name)


def _parse_integer_size_component(value: str, label: str) -> int:
    try:
        numeric = float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be an integer pixel value')
    if not numeric.is_integer():
        raise ValueError(f'{label} must be an integer pixel value')
    parsed = int(numeric)
    if parsed <= 0:
        raise ValueError(f'{label} must be greater than zero')
    return parsed


def _parse_size_pair(value: str, label: str = 'size') -> tuple[int, int]:
    try:
        width, height = str(value).lower().split('x', 1)
    except ValueError:
        raise ValueError(f'{label} must use WIDTHxHEIGHT')
    return (
        _parse_integer_size_component(width, f'{label} width'),
        _parse_integer_size_component(height, f'{label} height'),
    )


def _icc_profile_name(icc_bytes: bytes | None) -> str:
    if not icc_bytes:
        return ''
    if ImageCms is None:
        return 'embedded ICC'
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes))
        return str(ImageCms.getProfileName(profile)).strip() or 'embedded ICC'
    except Exception:
        return 'embedded ICC'


def _image_output_detail(path: Path) -> dict:
    detail = {'output': str(path), 'format': '', 'mode': '', 'icc_profile': ''}
    try:
        with Image.open(path) as image:
            detail['format'] = str(image.format or '')
            detail['mode'] = str(image.mode or '')
            detail['icc_profile'] = _icc_profile_name(image.info.get('icc_profile'))
    except Exception as exc:
        detail['error'] = f'{exc.__class__.__name__}: {exc}'
    return detail


def _format_dpi_pair(value) -> str:
    if value is None:
        return ''
    try:
        dpi = float(value)
    except (TypeError, ValueError):
        return str(value)
    if dpi.is_integer():
        return f'{int(dpi)}dpi'
    return f'{dpi:.1f}'.rstrip('0').rstrip('.') + 'dpi'


def _normalize_output_dpi(value: float) -> float:
    dpi = max(1.0, float(value))
    nearest_int = round(dpi)
    if abs(dpi - nearest_int) < 0.05:
        return float(nearest_int)
    return round(dpi, 1)


def emit_formats() -> int:
    rows = [
        {
            'extension': row.extension,
            'mode': row.mode,
            'detail': row.detail,
        }
        for row in adapter_report()
    ]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def _process_batch_file(args, input_path: Path, output_dir: Path, src: Path, transform_fn, embedded_icc_fn=None, dpi_fn=None) -> dict:
    try:
        source_image = open_image(src)
        warning = _multi_frame_warning(src, _frame_count(source_image))
        image = ImageOps.exif_transpose(source_image)
        transformed = transform_fn(image, src)
        rel = _relative_output_path(input_path, src)
        out_stem = output_dir / rel
        embedded_icc = embedded_icc_fn(transformed, image, src) if embedded_icc_fn is not None else KEEP_ICC
        output_dpi = dpi_fn(image, transformed, src) if dpi_fn is not None else getattr(args, 'set_dpi', None)
        written = save_image(
            transformed,
            out_stem.with_suffix(''),
            out_format=args.to,
            jpeg_quality=getattr(args, 'jpeg_quality', 75),
            png_preset=getattr(args, 'png_preset', 'balanced'),
            metadata=getattr(args, 'metadata', 'preserve_dpi_color'),
            dpi=output_dpi,
            alpha_bg=getattr(args, 'alpha_bg', 'white'),
            embedded_icc=embedded_icc,
            metadata_source=image,
        )
        result = {'input': str(src), 'output': str(written)}
        if output_dpi is not None:
            result['dpi_written'] = _format_dpi_pair(output_dpi)
        if warning:
            result['warning'] = warning
        return result
    except Exception as exc:
        return _error_result(src, exc)


def _run_parallel(files: list[Path], args, worker_fn, desc: str = 'Processing') -> list[dict]:
    workers = _effective_workers(args, len(files))
    results: list[dict] = []
    if workers <= 1:
        for src in tqdm(files, desc=desc, unit='file'):
            result = worker_fn(src)
            _emit_result_notice(result)
            results.append(result)
        return results

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker_fn, src) for src in files]
        for future in tqdm(as_completed(futures), total=len(futures), desc=f'{desc} x{workers}', unit='file'):
            result = future.result()
            _emit_result_notice(result)
            results.append(result)
    return sorted(results, key=_result_sort_key)


def process_batch(args, transform_fn, embedded_icc_fn=None, dpi_fn=None):
    input_path = Path(args.input)
    output_dir = Path(args.output)
    files = discover_inputs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    return _run_parallel(
        files,
        args,
        lambda src: _process_batch_file(args, input_path, output_dir, src, transform_fn, embedded_icc_fn, dpi_fn),
    )


def cmd_convert(args) -> int:
    results = process_batch(args, lambda image, src: image)
    write_json_report(Path(args.log_dir), {'command': 'convert', 'results': results})
    print(json.dumps(_batch_summary(results), ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_normalize(args) -> int:
    cmyk_profile = getattr(args, 'cmyk_profile', None)
    srgb_profile = getattr(args, 'srgb_profile', None)
    srgb_profile_mode = getattr(args, 'srgb_profile_mode', 'colororg')
    embed_srgb_profile = bool(getattr(args, 'embed_srgb_profile', True))
    embed_cmyk_profile = bool(getattr(args, 'embed_cmyk_profile', False))
    embed_pdf_image_profile = bool(getattr(args, 'embed_pdf_image_profile', True))
    def embedded_icc_for_normalize(transformed: Image.Image, _source: Image.Image, _src: Path):
        target_profile = (args.target_profile or 'keep').lower()
        if target_profile == 'keep':
            return KEEP_ICC
        if target_profile == 'srgb':
            return transformed.info.get('icc_profile') if embed_srgb_profile else None
        if target_profile == 'cmyk':
            return transformed.info.get('icc_profile') if embed_cmyk_profile else None
        return KEEP_ICC

    results = process_batch(
        args,
        lambda image, src: normalize_profile(
            image,
            args.target_profile,
            cmyk_profile,
            args.alpha_bg,
            srgb_profile_mode=srgb_profile_mode,
            srgb_profile_path=srgb_profile,
            embed_srgb_profile=embed_srgb_profile,
            embed_cmyk_profile=embed_cmyk_profile,
        ),
        embedded_icc_fn=embedded_icc_for_normalize,
    )
    input_path = Path(args.input)
    output_path = Path(args.output)
    pdfs = discover_pdfs(input_path)
    for src in tqdm(pdfs, desc='Normalizing PDF', unit='pdf'):
        rel_parent = src.parent.relative_to(input_path) if input_path.is_dir() and src.parent != input_path else Path()
        written = normalize_pdf_to_pdf(
            src,
            output_path / rel_parent / f'{src.stem}.pdf',
            target_profile=args.target_profile,
            cmyk_profile_path=cmyk_profile,
            srgb_profile_mode=srgb_profile_mode,
            srgb_profile_path=srgb_profile,
            embed_srgb_profile=embed_srgb_profile,
            embed_cmyk_profile=embed_cmyk_profile,
            embed_pdf_image_profile=embed_pdf_image_profile,
            dpi=getattr(args, 'pdf_dpi', 300),
            alpha_bg=getattr(args, 'alpha_bg', 'white'),
        )
        results.append({'input': str(src), 'output': str(written)})
    write_json_report(Path(args.log_dir), {'command': 'normalize', 'results': results})
    print(json.dumps(_batch_summary(results), ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_grayscale(args) -> int:
    results = process_batch(args, lambda image, src: grayscale_image(image))
    write_json_report(Path(args.log_dir), {'command': 'grayscale', 'results': results})
    print(json.dumps(_batch_summary(results), ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_resize_screen(args) -> int:
    results = process_batch(args, lambda image, src: resize_to_screen(image, args.target, args.mode, args.background))
    write_json_report(Path(args.log_dir), {'command': 'resize-screen', 'target': args.target, 'results': results})
    print(json.dumps({**_batch_summary(results), 'target': args.target}, ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_aspect(args) -> int:
    explicit = None
    if args.size:
        explicit = _parse_size_pair(args.size, '--size')
    target_size = ratio_size(args.ratio, args.long_edge, explicit)
    results = process_batch(args, lambda image, src: resize_to_box(image, target_size, args.mode, args.background))
    write_json_report(Path(args.log_dir), {'command': 'aspect', 'ratio': args.ratio, 'size': list(target_size), 'results': results})
    print(json.dumps({**_batch_summary(results), 'size': list(target_size)}, ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_trim_border(args) -> int:
    results = process_batch(args, lambda image, src: trim_border(image, args.tolerance, args.safety_margin_mm))
    write_json_report(Path(args.log_dir), {'command': 'trim-border', 'results': results})
    print(json.dumps(_batch_summary(results), ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_smart_crop_white(args) -> int:
    results = process_batch(args, lambda image, src: trim_white_border(image, args.tolerance, args.safety_margin_mm))
    write_json_report(Path(args.log_dir), {'command': 'smart-crop-white', 'results': results})
    print(json.dumps(_batch_summary(results), ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_watermark(args) -> int:
    results = process_batch(
        args,
        lambda image, src: add_text_watermark(
            image,
            args.text,
            args.position,
            args.margin,
            args.opacity,
            args.font_size,
            args.color,
            getattr(args, 'watermark_mode', 'corner'),
            getattr(args, 'diagonal_coverage', 0.7),
        ),
    )
    write_json_report(Path(args.log_dir), {'command': 'watermark', 'results': results})
    print(json.dumps(_batch_summary(results), ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def _image_dpi_pair(dpi_raw) -> tuple[float, float, bool]:
    if isinstance(dpi_raw, (tuple, list)) and len(dpi_raw) >= 2:
        try:
            dpi_x = float(dpi_raw[0])
            dpi_y = float(dpi_raw[1])
            if dpi_x > 0 and dpi_y > 0:
                return dpi_x, dpi_y, False
        except (TypeError, ValueError):
            pass
    try:
        dpi = float(dpi_raw)
        if dpi > 0:
            return dpi, dpi, False
    except (TypeError, ValueError):
        pass
    return 300.0, 300.0, True


def _format_dpi(dpi_x: float, dpi_y: float) -> str:
    rounded_x = round(dpi_x)
    rounded_y = round(dpi_y)
    if rounded_x == rounded_y:
        return f'{rounded_x}dpi'
    return f'{rounded_x}x{rounded_y}dpi'


def cmd_contact_sheet(args) -> int:
    input_path = Path(args.input)
    files = discover_inputs(input_path)
    images = []
    labels = []
    label_mode = str(getattr(args, 'label_mode', 'inspection') or 'inspection')
    for src in tqdm(files, desc='Loading', unit='file'):
        image = open_image(src)
        dpi_raw = image.info.get('dpi')
        image = ImageOps.exif_transpose(image)
        images.append(image)
        if label_mode == 'filename':
            labels.append(src.name)
        elif label_mode == 'filename-size':
            labels.append(f'{src.name}\n{image.width}x{image.height}px')
        elif label_mode == 'inspection':
            dpi_x, dpi_y, dpi_estimated = _image_dpi_pair(dpi_raw)
            width_cm = image.width / dpi_x * 2.54
            height_cm = image.height / dpi_y * 2.54
            size_kb = max(1, round(src.stat().st_size / 1024))
            dpi_text = '300dpi fallback' if dpi_estimated else _format_dpi(dpi_x, dpi_y)
            labels.append(
                f'{src.name}\n'
                f'{image.width}x{image.height}px | {width_cm:.1f}x{height_cm:.1f}cm | {dpi_text}\n'
                f'{size_kb} KB'
            )
    thumb_w, thumb_h = _parse_size_pair(args.thumb_size, '--thumb-size')
    sheet = build_contact_sheet(
        images,
        args.columns,
        (thumb_w, thumb_h),
        args.background,
        args.spacing,
        labels=labels if label_mode != 'none' else None,
        label_height=args.label_height,
        border_size=args.border_size,
        border_color=args.border_color,
        text_color=args.text_color,
        font_size=args.label_font_size,
    )
    output_path = Path(args.output)
    out_format = str(getattr(args, 'to', '') or '').lower()
    if not out_format:
        suffix = output_path.suffix.lower().lstrip('.')
        out_format = {'jpeg': 'jpg', 'tif': 'tiff'}.get(suffix, suffix or 'png')
    output_path = save_image(
        sheet,
        output_path,
        out_format,
        jpeg_quality=getattr(args, 'jpeg_quality', 92),
        metadata='strip_all',
    )
    write_json_report(
        Path(args.log_dir),
        {
            'command': 'contact-sheet',
            'count': len(images),
            'output': str(output_path),
            'to': out_format,
            'jpeg_quality': getattr(args, 'jpeg_quality', 92),
            'columns': args.columns,
            'thumb_size': args.thumb_size,
            'label_mode': label_mode,
        },
    )
    print(json.dumps({'processed': len(images), 'output': str(output_path)}, ensure_ascii=False, indent=2))
    return 0


def cmd_photo_sheet_width(args) -> int:
    config_mode = getattr(args, 'config_mode', None)
    if config_mode:
        config = load_photo_sheet_config(Path(getattr(args, 'config', 'config/photo_sheet.yaml')))
        settings = mode_config(config, config_mode)
        input_path = Path(settings['input'])
        output_dir = Path(settings['output'])
        page_width_mm = float(settings['page_width_mm'])
        dpi = int(settings['dpi'])
        gap_mm = float(settings['gap_mm'])
        size_source = str(settings['size_source'])
        layout = str(settings['layout'])
        height_tolerance_mm = float(settings['height_tolerance_mm'])
        recursive = bool(settings['recursive'])
        background = str(settings['background'])
        preview_width_px = int(settings['preview_width_px'])
        out_format = str(settings.get('to', 'png'))
        jpeg_quality = int(settings.get('jpeg_quality', 90))
    else:
        if args.page_width_mm is None:
            raise ValueError('--page-width-mm is required when --config-mode is not used')
        if args.dpi is None:
            raise ValueError('--dpi is required when --config-mode is not used')
        input_path = Path(args.input)
        output_dir = Path(args.output)
        page_width_mm = float(args.page_width_mm)
        dpi = int(args.dpi)
        gap_mm = float(getattr(args, 'gap_mm', 0.0))
        size_source = getattr(args, 'size_source', 'pixels')
        layout = getattr(args, 'layout', 'shelf')
        height_tolerance_mm = float(getattr(args, 'height_tolerance_mm', 0.2))
        recursive = bool(getattr(args, 'recursive', False))
        background = getattr(args, 'background', 'white')
        preview_width_px = int(getattr(args, 'preview_width_px', 1800))
        out_format = getattr(args, 'to', 'png')
        jpeg_quality = int(getattr(args, 'jpeg_quality', 90))

    payload = build_photo_sheet_by_width(
        input_path=input_path,
        output_dir=output_dir,
        page_width_mm=page_width_mm,
        dpi=dpi,
        gap_mm=gap_mm,
        size_source=size_source,
        layout=layout,
        height_tolerance_mm=height_tolerance_mm,
        recursive=recursive,
        background=background,
        preview_width_px=preview_width_px,
        out_format=out_format,
        jpeg_quality=jpeg_quality,
        workers=getattr(args, 'workers', 1),
    )
    write_json_report(Path(args.log_dir), {'command': 'photo-sheet-width', **payload})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload.get('error') else 0


def cmd_tile_sheet(args) -> int:
    payload = build_tile_sheets(
        input_path=Path(args.input),
        output_dir=Path(args.output),
        paper=args.paper,
        orientation=args.orientation,
        margin_mm=args.margin_mm,
        gap_mm=args.gap_mm,
        dpi=args.dpi,
        size_mode=args.size_mode,
        item_width_mm=getattr(args, 'item_width_mm', None),
        item_height_mm=getattr(args, 'item_height_mm', None),
        box_fit=args.box_fit,
        frame_mm=args.frame_mm,
        frame_color=args.frame_color,
        background=args.background,
        preview_width_px=args.preview_width_px,
        roll_width_mm=getattr(args, 'roll_width_mm', None),
        count_mode=args.count_mode,
        requested_rows=getattr(args, 'rows', None),
        copies=getattr(args, 'copies', None),
        out_format=getattr(args, 'to', 'tiff'),
        workers=getattr(args, 'workers', 1),
    )
    write_json_report(Path(args.log_dir), payload)
    print(json.dumps({
        'processed': payload['processed'],
        'copies': sum(int(sheet.get('copies', 0)) for sheet in payload['sheets']),
        'sheets': [
            {
                'source': sheet['source'],
                'paper': sheet['paper'],
                'columns': sheet['columns'],
                'rows': sheet['rows'],
                'copies': sheet['copies'],
                'output': sheet['outputs']['sheet'],
            }
            for sheet in payload['sheets']
        ],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_split_tiff(args) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output)
    written = []
    if input_path.is_dir():
        for src in sorted(input_path.rglob('*')):
            if src.is_file() and src.suffix.lower() in {'.tif', '.tiff'}:
                rel = src.parent.relative_to(input_path) if src.parent != input_path else Path()
                subdir = output_dir / rel / src.stem
                written.extend(split_tiff_to_png(src, subdir))
    else:
        written.extend(split_tiff_to_png(input_path, output_dir))
    write_json_report(Path(args.log_dir), {'command': 'split-tiff', 'count': len(written), 'outputs': [str(p) for p in written]})
    print(json.dumps({'written': len(written)}, ensure_ascii=False, indent=2))
    return 0


def cmd_plotter_size(args) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output)
    files = discover_inputs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    def process_one(src: Path) -> dict:
        try:
            image = open_image(src)
            image = ImageOps.exif_transpose(image)
            dpi = dpi_for_print_side(image, args.side, args.target_mm)
            rel = _relative_output_path(input_path, src)
            out_stem = output_dir / rel
            written = save_image(
                image,
                out_stem.with_suffix(''),
                out_format=args.to,
                jpeg_quality=getattr(args, 'jpeg_quality', 90),
                png_preset=getattr(args, 'png_preset', 'balanced'),
                metadata=getattr(args, 'metadata', 'preserve_dpi_color'),
                dpi=dpi,
                alpha_bg=getattr(args, 'alpha_bg', 'white'),
                metadata_source=image,
            )
            return {
                'input': str(src),
                'output': str(written),
                'side': args.side,
                'target_mm': args.target_mm,
                'dpi_written': dpi,
                'source_pixels': [image.width, image.height],
            }
        except Exception as exc:
            return _error_result(src, exc)

    results = _run_parallel(files, args, process_one)
    write_json_report(Path(args.log_dir), {'command': 'plotter-size', 'side': args.side, 'target_mm': args.target_mm, 'results': results})
    print(json.dumps({**_batch_summary(results), 'side': args.side, 'target_mm': args.target_mm}, ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_plotter_dpi_only(args) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output)
    files = discover_inputs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    def process_one(src: Path) -> dict:
        try:
            image = open_image(src)
            image = ImageOps.exif_transpose(image)
            rel = _relative_output_path(input_path, src)
            out_stem = output_dir / rel
            written = save_image(
                image,
                out_stem.with_suffix(''),
                out_format=args.to,
                jpeg_quality=getattr(args, 'jpeg_quality', 90),
                png_preset=getattr(args, 'png_preset', 'balanced'),
                metadata=getattr(args, 'metadata', 'preserve_dpi_color'),
                dpi=args.dpi,
                alpha_bg=getattr(args, 'alpha_bg', 'white'),
                metadata_source=image,
            )
            return {
                'input': str(src),
                'output': str(written),
                'dpi_written': args.dpi,
                'source_pixels': [image.width, image.height],
            }
        except Exception as exc:
            return _error_result(src, exc)

    results = _run_parallel(files, args, process_one)
    write_json_report(Path(args.log_dir), {'command': 'plotter-dpi-only', 'dpi': args.dpi, 'results': results})
    print(json.dumps({**_batch_summary(results), 'dpi': args.dpi}, ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_split_half(args) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output)
    files = discover_inputs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    mode = getattr(args, 'mode', 'strips')
    metadata = getattr(args, 'metadata', 'preserve_dpi_color')
    out_format = getattr(args, 'to', 'png')
    jpeg_quality = getattr(args, 'jpeg_quality', 75)

    def process_one(src: Path) -> dict:
        try:
            image = open_image(src)
            image = ImageOps.exif_transpose(image)
            base = output_dir / src.stem
            written: list[Path] = []
            if mode == 'grid':
                rows = int(getattr(args, 'rows', 2))
                columns = int(getattr(args, 'columns', 2))
                for index, (_row, _column, part) in enumerate(split_image_grid(image, rows, columns), start=1):
                    out_path = save_image(part, base.with_name(f'{base.name}_{index:02d}'), out_format, jpeg_quality=jpeg_quality, metadata=metadata, metadata_source=image)
                    written.append(out_path)
                result = {'input': str(src), 'mode': mode, 'rows': rows, 'columns': columns, 'outputs': [str(path) for path in written]}
            else:
                orientation = getattr(args, 'orientation', 'vertical')
                parts = int(getattr(args, 'parts', 2))
                for index, part in enumerate(split_image_strips(image, orientation, parts), start=1):
                    out_path = save_image(part, base.with_name(f'{base.name}_{index:02d}'), out_format, jpeg_quality=jpeg_quality, metadata=metadata, metadata_source=image)
                    written.append(out_path)
                result = {'input': str(src), 'mode': mode, 'orientation': orientation, 'parts': parts, 'outputs': [str(path) for path in written]}
            return result
        except Exception as exc:
            return _error_result(src, exc)

    results = _run_parallel(files, args, process_one)
    write_json_report(Path(args.log_dir), {'command': 'split-half', 'mode': mode, 'to': out_format, 'results': results})
    print(json.dumps({**_batch_summary(results), 'mode': mode, 'to': out_format}, ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0


def cmd_downscale_percent(args) -> int:
    unsharp = bool(getattr(args, 'unsharp', True))
    print_size_mode = str(getattr(args, 'print_size_mode', 'scale') or 'scale').lower()
    scale_mode = str(getattr(args, 'scale_mode', '') or '').lower()
    legacy_percent = getattr(args, 'percent', None)
    if legacy_percent is not None and scale_mode in {'', 'percent', 'percent-25', 'percent-50'}:
        percent = float(legacy_percent)
        scale_mode = 'percent'
    elif scale_mode in {'25', 'percent-25'}:
        percent = 25.0
    elif scale_mode in {'50', 'percent-50', ''}:
        percent = 50.0
    elif scale_mode in {'custom', 'percent-custom'}:
        percent = float(getattr(args, 'custom_percent', 50.0) or 50.0)
    elif scale_mode in {'target', 'target-mb', 'fit-mb'}:
        percent = None
    else:
        raise ValueError(f'Unsupported downscale mode: {scale_mode}')

    def source_average_dpi(source: Image.Image) -> float:
        src_dpi_x, src_dpi_y, _estimated = _image_dpi_pair(source.info.get('dpi'))
        return (float(src_dpi_x) + float(src_dpi_y)) / 2.0

    def dpi_for_percent(source: Image.Image, percent_value: float):
        if print_size_mode != 'dpi':
            return getattr(args, 'set_dpi', None)
        return _normalize_output_dpi(source_average_dpi(source) * (float(percent_value) / 100.0))

    def dpi_for_resized_print_size(source: Image.Image, resized: Image.Image, _src: Path):
        if print_size_mode != 'dpi':
            return getattr(args, 'set_dpi', None)
        scale_x = resized.width / max(1, source.width)
        scale_y = resized.height / max(1, source.height)
        scale = (scale_x + scale_y) / 2.0
        return _normalize_output_dpi(source_average_dpi(source) * scale)

    if percent is not None:
        results = process_batch(
            args,
            lambda image, src: resize_by_percent(image, percent, args.algorithm, unsharp=unsharp),
            dpi_fn=dpi_for_resized_print_size,
        )
        report = {'command': 'downscale-percent', 'mode': scale_mode, 'percent': percent, 'algorithm': args.algorithm, 'unsharp': unsharp, 'print_size_mode': print_size_mode, 'results': results}
        write_json_report(Path(args.log_dir), report)
        print(json.dumps({**_batch_summary(results), 'mode': scale_mode, 'percent': percent, 'algorithm': args.algorithm, 'unsharp': unsharp, 'print_size_mode': print_size_mode}, ensure_ascii=False, indent=2))
        return 1 if _has_errors(results) else 0

    input_path = Path(args.input)
    output_dir = Path(args.output)
    files = discover_inputs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_mb = float(getattr(args, 'target_mb', 1.0) or 1.0)
    target_bytes = max(1, round(target_mb * 1024 * 1024))
    floor_ratio = max(0.0, min(1.0, float(getattr(args, 'target_floor_ratio', 0.8) or 0.8)))
    probe_workers = _effective_workers(args, 8)

    def process_one(src: Path) -> dict:
        try:
            source_image = open_image(src)
            warning = _multi_frame_warning(src, _frame_count(source_image))
            image = ImageOps.exif_transpose(source_image)
            resized, chosen_percent, estimated_bytes = fit_resize_to_target_bytes(
                image,
                target_bytes,
                args.to,
                algorithm=args.algorithm,
                unsharp=unsharp,
                jpeg_quality=getattr(args, 'jpeg_quality', 75),
                png_preset=getattr(args, 'png_preset', 'balanced'),
                metadata=getattr(args, 'metadata', 'preserve_dpi_color'),
                dpi=(getattr(args, 'set_dpi', None) if print_size_mode != 'dpi' else None),
                dpi_for_percent=(lambda percent_value, source=image: dpi_for_percent(source, percent_value)) if print_size_mode == 'dpi' else None,
                alpha_bg=getattr(args, 'alpha_bg', 'white'),
                metadata_source=image,
                probe_workers=probe_workers,
            )
            output_dpi = dpi_for_resized_print_size(image, resized, src)
            rel = _relative_output_path(input_path, src)
            written = save_image(
                resized,
                (output_dir / rel).with_suffix(''),
                out_format=args.to,
                jpeg_quality=getattr(args, 'jpeg_quality', 75),
                png_preset=getattr(args, 'png_preset', 'balanced'),
                metadata=getattr(args, 'metadata', 'preserve_dpi_color'),
                dpi=output_dpi,
                alpha_bg=getattr(args, 'alpha_bg', 'white'),
                metadata_source=image,
            )
            actual_bytes = written.stat().st_size
            result = {
                'input': str(src),
                'output': str(written),
                'target_mb': target_mb,
                'target_bytes': target_bytes,
                'percent': chosen_percent,
                'estimated_bytes': estimated_bytes,
                'actual_bytes': actual_bytes,
                'probe_workers': probe_workers,
                'print_size_mode': print_size_mode,
            }
            if output_dpi is not None:
                result['dpi_written'] = _format_dpi_pair(output_dpi)
            if warning:
                result['warning'] = warning
            if actual_bytes > target_bytes:
                result['warning'] = (result.get('warning', '') + ' ' if result.get('warning') else '') + f'Target size was not reached: {actual_bytes} > {target_bytes} bytes.'
            elif actual_bytes < target_bytes * floor_ratio and chosen_percent < 99.95:
                result['warning'] = (result.get('warning', '') + ' ' if result.get('warning') else '') + f'Result is below {floor_ratio:.0%} of target; source/compression granularity limited the fit.'
            return result
        except Exception as exc:
            return _error_result(src, exc)

    results: list[dict] = []
    for src in tqdm(files, desc=f'Fitting target MB x{probe_workers}', unit='file'):
        result = process_one(src)
        _emit_result_notice(result)
        results.append(result)
    report = {
        'command': 'downscale-percent',
        'mode': 'target-mb',
        'target_mb': target_mb,
        'target_bytes': target_bytes,
        'target_floor_ratio': floor_ratio,
        'algorithm': args.algorithm,
        'unsharp': unsharp,
        'print_size_mode': print_size_mode,
        'probe_workers': probe_workers,
        'results': results,
    }
    write_json_report(Path(args.log_dir), report)
    print(json.dumps({**_batch_summary(results), 'mode': 'target-mb', 'target_mb': target_mb, 'algorithm': args.algorithm, 'unsharp': unsharp, 'print_size_mode': print_size_mode, 'probe_workers': probe_workers}, ensure_ascii=False, indent=2))
    return 1 if _has_errors(results) else 0



def cmd_pdf_rasterize(args) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output)
    pdfs = discover_pdfs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for src in tqdm(pdfs, desc='Rasterizing PDF', unit='pdf'):
        rel_parent = src.parent.relative_to(input_path) if input_path.is_dir() and src.parent != input_path else Path()
        subdir = output_dir / rel_parent / src.stem
        written = rasterize_pdf_to_images(
            src,
            subdir,
            out_format=args.to,
            dpi=args.dpi,
            jpeg_quality=getattr(args, 'jpeg_quality', 90),
            png_preset=getattr(args, 'png_preset', 'balanced'),
            metadata=getattr(args, 'metadata', 'preserve_dpi_color'),
        )
        results.append({'input': str(src), 'outputs': [str(p) for p in written]})
    write_json_report(Path(args.log_dir), {'command': 'pdf-rasterize', 'dpi': args.dpi, 'results': results})
    print(json.dumps({'processed_pdfs': len(results), 'dpi': args.dpi}, ensure_ascii=False, indent=2))
    return 0



def cmd_pdf_extract_embedded(args) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output)
    pdfs = discover_pdfs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    layout = str(getattr(args, 'layout', 'folders') or 'folders').lower()
    out_format = str(getattr(args, 'to', 'original') or 'original').lower()
    for src in tqdm(pdfs, desc='Extracting embedded images', unit='pdf'):
        rel_parent = src.parent.relative_to(input_path) if input_path.is_dir() and src.parent != input_path else Path()
        if layout in {'flat', 'one-folder', 'one_folder', 'all'}:
            subdir = output_dir
        else:
            subdir = output_dir / rel_parent / src.stem
        written = extract_embedded_images(
            src,
            subdir,
            out_format=out_format,
            jpeg_quality=getattr(args, 'jpeg_quality', 90),
            png_preset=getattr(args, 'png_preset', 'balanced'),
            metadata=getattr(args, 'metadata', 'preserve_dpi_color'),
            png_side_tiff=bool(getattr(args, 'png_side_tiff', False)),
        )
        results.append({'input': str(src), 'outputs': [str(p) for p in written], 'output_details': [_image_output_detail(p) for p in written]})
    png_side_tiff = bool(getattr(args, 'png_side_tiff', False))
    write_json_report(Path(args.log_dir), {'command': 'pdf-extract-embedded', 'to': out_format, 'layout': layout, 'png_side_tiff': png_side_tiff, 'results': results})
    print(json.dumps({'processed_pdfs': len(results), 'to': out_format, 'layout': layout, 'png_side_tiff': png_side_tiff}, ensure_ascii=False, indent=2))
    return 0



def cmd_pdf_export(args) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output)
    pdfs = discover_pdfs(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    mode = getattr(args, 'mode', 'render')
    for src in tqdm(pdfs, desc=f'Exporting PDF ({mode})', unit='pdf'):
        rel_parent = src.parent.relative_to(input_path) if input_path.is_dir() and src.parent != input_path else Path()
        subdir = output_dir / rel_parent / src.stem
        if mode == 'embedded':
            written = export_largest_embedded_images(
                src,
                subdir,
                out_format=args.to,
                jpeg_quality=getattr(args, 'jpeg_quality', 90),
                png_preset=getattr(args, 'png_preset', 'balanced'),
                metadata=getattr(args, 'metadata', 'preserve_dpi_color'),
            )
        else:
            written = rasterize_pdf_to_images(
                src,
                subdir,
                out_format=args.to,
                dpi=getattr(args, 'dpi', 300),
                jpeg_quality=getattr(args, 'jpeg_quality', 90),
                png_preset=getattr(args, 'png_preset', 'balanced'),
                metadata=getattr(args, 'metadata', 'preserve_dpi_color'),
            )
        results.append({'input': str(src), 'outputs': [str(p) for p in written]})
    payload = {
        'command': 'pdf-export',
        'mode': mode,
        'to': args.to,
        'results': results,
    }
    if mode == 'render':
        payload['dpi'] = getattr(args, 'dpi', 300)
    write_json_report(Path(args.log_dir), payload)
    print(json.dumps({k: v for k, v in payload.items() if k != 'results'} | {'processed_pdfs': len(results)}, ensure_ascii=False, indent=2))
    return 0


def cmd_images_to_pdf(args) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output)
    bundle = str(getattr(args, 'bundle', 'all') or 'all').lower()
    preserve_icc = bool(getattr(args, 'preserve_icc', True))
    dpi = getattr(args, 'dpi', None)

    if bundle in {'folders', 'folder', 'many', 'multiple'}:
        files = [p for p in discover_inputs(input_path) if p.suffix.lower() != '.pdf']
        if not files:
            raise RuntimeError('No supported images found for PDF export')
        output_dir = output_path.with_suffix('') if output_path.suffix.lower() == '.pdf' else output_path
        groups: dict[Path, list[Path]] = {}
        for src in files:
            groups.setdefault(src.parent, []).append(src)

        results = []
        for parent, image_paths in groups.items():
            if input_path.is_dir():
                rel_parent = parent.relative_to(input_path)
            else:
                rel_parent = Path()
            pdf_name = 'images.pdf' if str(rel_parent) in {'', '.'} else f'{parent.name}.pdf'
            target_pdf = output_dir / rel_parent / pdf_name
            results.append(
                images_to_pdf_from_paths(
                    image_paths,
                    target_pdf,
                    mode=args.mode,
                    preserve_icc=preserve_icc,
                    dpi=dpi,
                )
            )
        payload = {
            'backend': results[0].get('backend', ''),
            'mode': args.mode,
            'bundle': 'folders',
            'pdf_count': len(results),
            'count': sum(int(item.get('count', 0)) for item in results),
            'outputs': [item.get('output', '') for item in results],
        }
    else:
        payload = images_to_pdf(
            input_path,
            output_path,
            mode=args.mode,
            preserve_icc=preserve_icc,
            dpi=dpi,
        )
        payload['bundle'] = 'all'
    if dpi is not None:
        payload['dpi'] = dpi
    write_json_report(Path(args.log_dir), {'command': 'images-to-pdf', **payload})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
