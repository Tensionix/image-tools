from __future__ import annotations

import csv
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageOps

from .io_utils import discover_inputs, open_image
from .pipeline import flatten_alpha


RESAMPLE = getattr(Image, 'Resampling', Image).LANCZOS

PAPER_SIZES_MM = {
    'a5': (148.0, 210.0),
    'a4': (210.0, 297.0),
    'a3': (297.0, 420.0),
}

DOCUMENT_PRESETS_MM = {
    'doc-40x30': (40.0, 30.0),
    'doc-60x40': (60.0, 40.0),
}


@dataclass(frozen=True)
class TilePlacement:
    index: int
    row: int
    column: int
    x_px: int
    y_px: int
    w_px: int
    h_px: int


def _mm_to_px(value_mm: float, dpi: int) -> int:
    return max(1, int(round(float(value_mm) / 25.4 * dpi)))


def _px_to_mm(value_px: int, dpi: int) -> float:
    return float(value_px) / float(dpi) * 25.4


def _positive_float(value: float | int | str | None, name: str) -> float:
    try:
        parsed = float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a positive number')
    if parsed <= 0:
        raise ValueError(f'{name} must be a positive number')
    return parsed


def _non_negative_float(value: float | int | str | None, name: str) -> float:
    try:
        parsed = float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a number')
    if parsed < 0:
        raise ValueError(f'{name} must not be negative')
    return parsed


def _dpi_from_image(image: Image.Image, fallback: float) -> tuple[float, float]:
    dpi = image.info.get('dpi')
    if isinstance(dpi, (tuple, list)) and dpi:
        try:
            x_dpi = float(dpi[0])
            y_dpi = float(dpi[1] if len(dpi) > 1 else dpi[0])
            if x_dpi > 0 and y_dpi > 0:
                return x_dpi, y_dpi
        except (TypeError, ValueError):
            pass
    try:
        if dpi:
            parsed = float(dpi)
            if parsed > 0:
                return parsed, parsed
    except (TypeError, ValueError):
        pass
    return fallback, fallback


def _paper_size_mm(paper: str, orientation: str) -> tuple[float, float]:
    key = (paper or 'a4').lower()
    if key not in PAPER_SIZES_MM:
        raise ValueError(f'Unsupported paper: {paper}')
    width_mm, height_mm = PAPER_SIZES_MM[key]
    if (orientation or 'portrait').lower() == 'landscape':
        return height_mm, width_mm
    return width_mm, height_mm


def _target_item_size_mm(
    image: Image.Image,
    dpi: int,
    size_mode: str,
    item_width_mm: float | None,
    item_height_mm: float | None,
) -> tuple[float, float, str, bool]:
    mode = (size_mode or 'source').lower()
    aspect = image.width / image.height

    if mode == 'source':
        x_dpi, y_dpi = _dpi_from_image(image, float(dpi))
        return image.width / x_dpi * 25.4, image.height / y_dpi * 25.4, f'source-dpi:{x_dpi:g}x{y_dpi:g}', False

    if mode == 'width':
        width_mm = _positive_float(item_width_mm, 'item_width_mm')
        return width_mm, width_mm / aspect, f'width:{width_mm:g}mm keep-aspect', False

    if mode == 'height':
        height_mm = _positive_float(item_height_mm, 'item_height_mm')
        return height_mm * aspect, height_mm, f'height:{height_mm:g}mm keep-aspect', False

    if mode in DOCUMENT_PRESETS_MM:
        long_mm, short_mm = DOCUMENT_PRESETS_MM[mode]
        if image.width >= image.height:
            return long_mm, short_mm, f'{mode}:long-side {long_mm:g}mm short-side {short_mm:g}mm', True
        return short_mm, long_mm, f'{mode}:short-side {short_mm:g}mm long-side {long_mm:g}mm', True

    raise ValueError(f'Unsupported tile size mode: {size_mode}')


def _prepare_item_image(
    image: Image.Image,
    size_px: tuple[int, int],
    background: str,
    fit_mode: str,
    frame_mm: float,
    frame_color: str,
    dpi: int,
) -> Image.Image:
    item_w_px, item_h_px = size_px
    rgb = flatten_alpha(image, background)
    if (fit_mode or 'contain').lower() == 'crop':
        item = ImageOps.fit(rgb, size_px, method=RESAMPLE, centering=(0.5, 0.5))
    else:
        item = Image.new('RGB', size_px, ImageColor.getrgb(background))
        contained = ImageOps.contain(rgb, size_px, method=RESAMPLE)
        x = (item_w_px - contained.width) // 2
        y = (item_h_px - contained.height) // 2
        item.paste(contained, (x, y))

    if frame_mm > 0:
        line_px = max(1, _mm_to_px(frame_mm, dpi))
        draw = ImageDraw.Draw(item)
        draw.rectangle(
            (0, 0, item_w_px - 1, item_h_px - 1),
            outline=ImageColor.getrgb(frame_color),
            width=line_px,
        )
    return item


def _output_prefix(input_root: Path, source: Path) -> str:
    if input_root.is_dir():
        try:
            rel = source.relative_to(input_root).with_suffix('')
            return '__'.join(rel.parts)
        except ValueError:
            pass
    return source.stem


def _positive_int(value: int | str | None, name: str) -> int:
    try:
        parsed = int(float(str(value).replace(',', '.')))
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be an integer')
    if parsed <= 0:
        raise ValueError(f'{name} must be greater than zero')
    return parsed


def _optional_non_negative_int(value: int | str | None, name: str) -> int:
    if value in {None, ''}:
        return 0
    try:
        parsed = int(float(str(value).replace(',', '.')))
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be an integer')
    if parsed < 0:
        raise ValueError(f'{name} must not be negative')
    return parsed


def _render_preview(canvas: Image.Image, preview_width_px: int) -> Image.Image:
    if canvas.width <= preview_width_px:
        return canvas.copy()
    scale = preview_width_px / canvas.width
    return canvas.resize((preview_width_px, max(1, round(canvas.height * scale))), RESAMPLE)


def _write_reports(
    output_dir: Path,
    prefix: str,
    source: Path,
    placements: list[TilePlacement],
    payload: dict,
    dpi: int,
) -> dict[str, str]:
    csv_path = output_dir / f'{prefix}_layout_report.csv'
    with csv_path.open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file, delimiter=';')
        writer.writerow(['index', 'row', 'column', 'x_px', 'y_px', 'w_px', 'h_px', 'x_mm', 'y_mm', 'w_mm', 'h_mm'])
        for placement in placements:
            writer.writerow([
                placement.index,
                placement.row,
                placement.column,
                placement.x_px,
                placement.y_px,
                placement.w_px,
                placement.h_px,
                round(_px_to_mm(placement.x_px, dpi), 3),
                round(_px_to_mm(placement.y_px, dpi), 3),
                round(_px_to_mm(placement.w_px, dpi), 3),
                round(_px_to_mm(placement.h_px, dpi), 3),
            ])

    summary_path = output_dir / f'{prefix}_layout_summary.json'
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    text_path = output_dir / f'{prefix}_layout_summary.txt'
    lines = [
        'Audion Tile Sheet summary',
        '',
        f'Source: {source}',
        f'Paper: {payload["paper"]} {payload["orientation"]}',
        f'Paper size: {payload["paper_size_mm"][0]:g} x {payload["paper_size_mm"][1]:g} mm',
        f'Margins: {payload["margin_mm"]:g} mm',
        f'Gap: {payload["gap_mm"]:g} mm',
        f'DPI: {payload["dpi"]}',
        f'Item: {payload["item_size_mm"][0]:g} x {payload["item_size_mm"][1]:g} mm',
        f'Size rule: {payload["size_rule"]}',
        f'Grid: {payload["columns"]} x {payload["rows"]}',
        f'Copies: {payload["copies"]}',
        '',
        f'TIFF: {payload["outputs"].get("tiff", "")}',
        f'Preview: {payload["outputs"].get("preview", "")}',
        f'Report: {csv_path.name}',
    ]
    text_path.write_text('\n'.join(lines), encoding='utf-8')

    return {
        'layout_report': str(csv_path),
        'layout_summary_json': str(summary_path),
        'layout_summary_txt': str(text_path),
    }


def build_tile_sheet_for_image(
    source: Path,
    input_root: Path,
    output_dir: Path,
    paper: str = 'a4',
    orientation: str = 'portrait',
    margin_mm: float = 7.0,
    gap_mm: float = 0.0,
    dpi: int = 300,
    size_mode: str = 'source',
    item_width_mm: float | None = None,
    item_height_mm: float | None = None,
    box_fit: str = 'contain',
    frame_mm: float = 0.2,
    frame_color: str = '#999999',
    background: str = 'white',
    preview_width_px: int = 1800,
    roll_width_mm: float | None = None,
    count_mode: str = 'fill',
    requested_rows: int | None = 1,
    copies: int | None = 0,
    out_format: str = 'tiff',
) -> dict:
    if dpi <= 0:
        raise ValueError('dpi must be greater than zero')
    margin_mm = _non_negative_float(margin_mm, 'margin_mm')
    gap_mm = _non_negative_float(gap_mm, 'gap_mm')
    frame_mm = _non_negative_float(frame_mm, 'frame_mm')
    paper_key = (paper or 'a4').lower()
    if paper_key == 'roll':
        paper_w_mm = _positive_float(roll_width_mm, 'roll_width_mm')
        paper_h_mm = 0.0
        usable_w_mm = paper_w_mm - margin_mm * 2
        usable_h_mm = 0.0
    else:
        paper_w_mm, paper_h_mm = _paper_size_mm(paper_key, orientation)
        usable_w_mm = paper_w_mm - margin_mm * 2
        usable_h_mm = paper_h_mm - margin_mm * 2
    if usable_w_mm <= 0 or (paper_key != 'roll' and usable_h_mm <= 0):
        raise ValueError('Margins leave no printable area')

    image = ImageOps.exif_transpose(open_image(source))
    item_w_mm, item_h_mm, size_rule, exact_box = _target_item_size_mm(
        image,
        dpi,
        size_mode,
        item_width_mm,
        item_height_mm,
    )
    if item_w_mm > usable_w_mm or (paper_key != 'roll' and item_h_mm > usable_h_mm):
        raise ValueError(
            f'Item {item_w_mm:g} x {item_h_mm:g} mm does not fit printable area '
            f'{usable_w_mm:g} x {usable_h_mm:g} mm'
        )

    columns = max(0, math.floor((usable_w_mm + gap_mm) / (item_w_mm + gap_mm)))
    mode_count = (count_mode or 'fill').lower()
    if mode_count not in {'fill', 'copies', 'rows'}:
        raise ValueError(f'Unsupported count mode: {count_mode}')
    requested_copies = _optional_non_negative_int(copies, 'copies')
    requested_row_count = _optional_non_negative_int(requested_rows, 'rows')

    if paper_key == 'roll':
        if columns < 1:
            raise ValueError('No copies fit across the roll width')
        if mode_count == 'fill':
            raise ValueError('count-mode fill is not supported for roll; use copies or rows')
        if mode_count == 'copies':
            if requested_copies <= 0:
                raise ValueError('copies must be greater than zero when count-mode is copies')
            rows = max(1, math.ceil(requested_copies / columns))
            placement_limit = requested_copies
        elif mode_count == 'rows':
            if requested_row_count <= 0:
                raise ValueError('rows must be greater than zero when count-mode is rows')
            rows = requested_row_count
            placement_limit = rows * columns
        paper_h_mm = margin_mm * 2 + rows * item_h_mm + max(0, rows - 1) * gap_mm
        usable_h_mm = max(0.0, paper_h_mm - margin_mm * 2)
        orientation_key = 'roll'
    else:
        max_rows = max(0, math.floor((usable_h_mm + gap_mm) / (item_h_mm + gap_mm)))
        if columns < 1 or max_rows < 1:
            raise ValueError('No copies fit on the sheet')
        if mode_count == 'copies':
            if requested_copies <= 0:
                raise ValueError('copies must be greater than zero when count-mode is copies')
            rows = max(1, math.ceil(requested_copies / columns))
            if rows > max_rows:
                raise ValueError(f'{requested_copies} copies do not fit on this sheet; capacity is {columns * max_rows}')
            placement_limit = requested_copies
        elif mode_count == 'rows':
            if requested_row_count <= 0:
                raise ValueError('rows must be greater than zero when count-mode is rows')
            if requested_row_count > max_rows:
                raise ValueError(f'{requested_row_count} rows do not fit on this sheet; max rows is {max_rows}')
            rows = requested_row_count
            placement_limit = rows * columns
        else:
            rows = max_rows
            placement_limit = rows * columns
        orientation_key = (orientation or 'portrait').lower()

    page_w_px = _mm_to_px(paper_w_mm, dpi)
    page_h_px = _mm_to_px(paper_h_mm, dpi)
    item_w_px = _mm_to_px(item_w_mm, dpi)
    item_h_px = _mm_to_px(item_h_mm, dpi)
    margin_px = _mm_to_px(margin_mm, dpi) if margin_mm > 0 else 0
    gap_px = _mm_to_px(gap_mm, dpi) if gap_mm > 0 else 0

    canvas = Image.new('RGB', (page_w_px, page_h_px), ImageColor.getrgb(background))
    fit_mode = box_fit if exact_box else 'contain'
    item = _prepare_item_image(
        image,
        (item_w_px, item_h_px),
        background=background,
        fit_mode=fit_mode,
        frame_mm=frame_mm,
        frame_color=frame_color,
        dpi=dpi,
    )

    placements: list[TilePlacement] = []
    index = 1
    for row in range(rows):
        for column in range(columns):
            if index > placement_limit:
                break
            x = margin_px + column * (item_w_px + gap_px)
            y = margin_px + row * (item_h_px + gap_px)
            canvas.paste(item, (x, y))
            placements.append(TilePlacement(index, row + 1, column + 1, x, y, item_w_px, item_h_px))
            index += 1
        if index > placement_limit:
            break

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _output_prefix(input_root, source)
    paper_key = (paper or 'a4').lower()
    sheet_tag = f'roll_{paper_w_mm:g}mm' if paper_key == 'roll' else f'{paper_key}_{orientation_key}'
    output_format = (out_format or 'tiff').lower()
    if output_format in {'tif', 'tiff'}:
        output_format = 'tiff'
        sheet_path = output_dir / f'{prefix}_tile_sheet_{sheet_tag}_{dpi}dpi.tif'
        preview_path = output_dir / f'{prefix}_tile_sheet_preview.jpg'
        canvas.save(sheet_path, dpi=(dpi, dpi), compression='tiff_lzw')
        _render_preview(canvas, preview_width_px).save(preview_path, quality=90, optimize=True)
    elif output_format == 'png':
        sheet_path = output_dir / f'{prefix}_tile_sheet_{sheet_tag}_{dpi}dpi.png'
        preview_path = output_dir / f'{prefix}_tile_sheet_preview.png'
        canvas.save(sheet_path, format='PNG', dpi=(dpi, dpi), optimize=True)
        _render_preview(canvas, preview_width_px).save(preview_path, format='PNG', optimize=True)
    else:
        raise ValueError(f'Unsupported tile sheet output format: {out_format}')

    payload = {
        'source': str(source),
        'paper': paper_key,
        'orientation': orientation_key,
        'paper_size_mm': [paper_w_mm, paper_h_mm],
        'margin_mm': margin_mm,
        'gap_mm': gap_mm,
        'dpi': dpi,
        'size_mode': size_mode,
        'box_fit': fit_mode,
        'count_mode': mode_count,
        'roll_width_mm': roll_width_mm if paper_key == 'roll' else None,
        'requested_rows': requested_row_count if requested_row_count > 0 else None,
        'requested_copies': requested_copies if requested_copies > 0 else None,
        'item_size_mm': [round(item_w_mm, 3), round(item_h_mm, 3)],
        'item_size_px': [item_w_px, item_h_px],
        'size_rule': size_rule,
        'frame_mm': frame_mm,
        'frame_color': frame_color,
        'columns': columns,
        'rows': rows,
        'copies': len(placements),
        'outputs': {
            'sheet': str(sheet_path),
            output_format: str(sheet_path),
            'preview': str(preview_path),
        },
    }
    payload['outputs'].update(_write_reports(output_dir, prefix, source, placements, payload, dpi))
    return payload


def _effective_workers(workers: int | None, item_count: int) -> int:
    if item_count <= 1:
        return 1
    try:
        requested = int(workers or 1)
    except (TypeError, ValueError):
        requested = 1
    if requested <= 0:
        requested = min(8, os.cpu_count() or 1)
    return max(1, min(requested, item_count))


def build_tile_sheets(
    input_path: Path,
    output_dir: Path,
    paper: str = 'a4',
    orientation: str = 'portrait',
    margin_mm: float = 7.0,
    gap_mm: float = 0.0,
    dpi: int = 300,
    size_mode: str = 'source',
    item_width_mm: float | None = None,
    item_height_mm: float | None = None,
    box_fit: str = 'contain',
    frame_mm: float = 0.2,
    frame_color: str = '#999999',
    background: str = 'white',
    preview_width_px: int = 1800,
    roll_width_mm: float | None = None,
    count_mode: str = 'fill',
    requested_rows: int | None = 1,
    copies: int | None = 0,
    out_format: str = 'tiff',
    workers: int = 1,
) -> dict:
    sources = [path for path in discover_inputs(input_path) if path.suffix.lower() != '.pdf']
    if not sources:
        raise ValueError(f'No supported images found: {input_path}')

    effective_workers = _effective_workers(workers, len(sources))

    def build_one(source: Path) -> dict:
        return build_tile_sheet_for_image(
            source=source,
            input_root=input_path,
            output_dir=output_dir,
            paper=paper,
            orientation=orientation,
            margin_mm=margin_mm,
            gap_mm=gap_mm,
            dpi=dpi,
            size_mode=size_mode,
            item_width_mm=item_width_mm,
            item_height_mm=item_height_mm,
            box_fit=box_fit,
            frame_mm=frame_mm,
            frame_color=frame_color,
            background=background,
            preview_width_px=preview_width_px,
            roll_width_mm=roll_width_mm,
            count_mode=count_mode,
            requested_rows=requested_rows,
            copies=copies,
            out_format=out_format,
        )

    if effective_workers <= 1:
        sheets = [build_one(source) for source in sources]
    else:
        sheets_by_index: list[dict | None] = [None] * len(sources)
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            futures = {executor.submit(build_one, source): index for index, source in enumerate(sources)}
            for future in as_completed(futures):
                sheets_by_index[futures[future]] = future.result()
        sheets = [sheet for sheet in sheets_by_index if sheet is not None]

    return {
        'command': 'tile-sheet',
        'processed': len(sheets),
        'workers': effective_workers,
        'sheets': sheets,
    }
