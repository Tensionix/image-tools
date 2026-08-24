from __future__ import annotations

import csv
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from .pipeline import flatten_alpha, save_image


SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.webp'}
RESAMPLE = getattr(Image, 'Resampling', Image).LANCZOS


DEFAULT_CONFIG = {
    'input': 'input',
    'size_source': 'pixels',
    'background': 'white',
    'preview_width_px': 1800,
    'recursive': False,
    'to': 'png',
    'jpeg_quality': 90,
    'modes': {
        'paper_saver': {
            'output': 'output/photo_sheet_width',
            'page_width_mm': 600,
            'dpi': 300,
            'gap_mm': 0,
            'layout': 'shelf',
            'height_tolerance_mm': 0.2,
        },
        'cut_lines': {
            'output': 'output/photo_sheet_cut_lines',
            'page_width_mm': 600,
            'dpi': 300,
            'gap_mm': 0,
            'layout': 'cut-lines',
            'height_tolerance_mm': 0.2,
        },
    },
}


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass
class SheetItem:
    path: Path
    source_w_px: int
    source_h_px: int
    print_w_mm: float
    print_h_mm: float
    target_w_px: int
    target_h_px: int
    size_rule: str
    warning: str = ''


@dataclass
class Placement:
    item: SheetItem
    x: int
    y: int
    w: int
    h: int


def _coerce_yaml_scalar(value: str):
    value = value.strip()
    if not value:
        return ''
    if value in {'true', 'True'}:
        return True
    if value in {'false', 'False'}:
        return False
    if value in {'null', 'None', '~'}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        if re.fullmatch(r'[-+]?\d+', value):
            return int(value)
        if re.fullmatch(r'[-+]?\d+(?:[.,]\d+)?', value):
            return float(value.replace(',', '.'))
    except Exception:
        pass
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_simple_yaml(path: Path) -> dict:
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding='utf-8'))
        return payload or {}
    except ImportError:
        pass

    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]

    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line_without_comment = raw_line.split('#', 1)[0].rstrip()
        if not line_without_comment.strip():
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(' '))
        line = line_without_comment.strip()
        if ':' not in line:
            raise ValueError(f'Unsupported YAML line: {raw_line}')
        key, value = line.split(':', 1)
        key = key.strip()
        value = value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if value == '':
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _coerce_yaml_scalar(value)

    return root


def load_photo_sheet_config(config_path: Path | None) -> dict:
    if config_path is None:
        return DEFAULT_CONFIG
    if not config_path.exists():
        return DEFAULT_CONFIG
    return _deep_merge(DEFAULT_CONFIG, load_simple_yaml(config_path))


def mode_config(config: dict, mode_name: str) -> dict:
    modes = config.get('modes') or {}
    if mode_name not in modes:
        available = ', '.join(sorted(modes)) or 'none'
        raise ValueError(f'Unknown photo sheet config mode: {mode_name}. Available: {available}')
    mode = modes[mode_name]
    return {
        'input': mode.get('input', config.get('input', 'input')),
        'output': mode.get('output', f'output/photo_sheet_{mode_name}'),
        'page_width_mm': mode.get('page_width_mm', 600),
        'dpi': mode.get('dpi', 300),
        'gap_mm': mode.get('gap_mm', 0),
        'size_source': mode.get('size_source', config.get('size_source', 'pixels')),
        'layout': mode.get('layout', 'shelf'),
        'height_tolerance_mm': mode.get('height_tolerance_mm', 0.2),
        'recursive': mode.get('recursive', config.get('recursive', False)),
        'background': mode.get('background', config.get('background', 'white')),
        'preview_width_px': mode.get('preview_width_px', config.get('preview_width_px', 1800)),
        'to': mode.get('to', config.get('to', 'png')),
        'jpeg_quality': mode.get('jpeg_quality', config.get('jpeg_quality', 90)),
    }


def _mm_to_px(value_mm: float, dpi: int) -> int:
    return max(1, int(round(value_mm / 25.4 * dpi)))


def _px_to_mm(value_px: int, dpi: int) -> float:
    return value_px / dpi * 25.4


def discover_sheet_images(input_path: Path, recursive: bool = False) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in SUPPORTED_EXTENSIONS else []
    pattern = '**/*' if recursive else '*'
    return sorted(
        p for p in input_path.glob(pattern)
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def _parse_decimal(value: str) -> float:
    return float(value.replace(',', '.'))


def _value_to_mm(value: str, unit: str) -> float:
    amount = _parse_decimal(value)
    if unit.lower() == 'cm':
        return amount * 10.0
    return amount


def _has_bare_size_token(stem: str) -> bool:
    return bool(
        re.search(
            r'(?:^|[^0-9a-z])\d+(?:[.,]\d+)?\s*(?:x|\u0445|\u043d\u0430)\s*\d+(?:[.,]\d+)?(?:$|[^0-9a-z])',
            stem,
            flags=re.IGNORECASE,
        )
    )


def parse_size_from_name(name: str, image_w: int, image_h: int) -> tuple[float, float, str] | None:
    stem = Path(name).stem.lower()
    aspect = image_w / image_h

    max_match = re.search(
        r'(?:^|[^0-9a-z])max\s*(\d+(?:[.,]\d+)?)\s*(cm|mm)(?:$|[^0-9a-z])',
        stem,
        flags=re.IGNORECASE,
    )
    if max_match:
        unit = max_match.group(2).lower()
        long_mm = _value_to_mm(max_match.group(1), unit)
        if image_w >= image_h:
            return long_mm, long_mm / aspect, f'name:max {max_match.group(1)}{unit}'
        return long_mm * aspect, long_mm, f'name:max {max_match.group(1)}{unit}'

    pair_match = re.search(
        r'(?:^|[^0-9a-z])(\d+(?:[.,]\d+)?)\s*(?:x|\u0445|\u043d\u0430)\s*(\d+(?:[.,]\d+)?)\s*(cm|mm)(?:$|[^0-9a-z])',
        stem,
        flags=re.IGNORECASE,
    )
    if pair_match:
        unit = pair_match.group(3).lower()
        a_mm = _value_to_mm(pair_match.group(1), unit)
        b_mm = _value_to_mm(pair_match.group(2), unit)
        long_mm = max(a_mm, b_mm)
        if image_w >= image_h:
            return long_mm, long_mm / aspect, f'name:{pair_match.group(1)}x{pair_match.group(2)}{unit} long-side'
        return long_mm * aspect, long_mm, f'name:{pair_match.group(1)}x{pair_match.group(2)}{unit} long-side'

    return None


def _dpi_from_image(image: Image.Image, fallback: float) -> tuple[float, float]:
    dpi = image.info.get('dpi')
    if isinstance(dpi, tuple) and len(dpi) >= 2:
        try:
            dx = float(dpi[0])
            dy = float(dpi[1])
            if dx > 0 and dy > 0:
                return dx, dy
        except Exception:
            pass
    return fallback, fallback


def measure_item(path: Path, output_dpi: int, size_source: str) -> SheetItem:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        source_w, source_h = image.size
        dpi_x, dpi_y = _dpi_from_image(image, float(output_dpi))

    warning = ''
    parsed = parse_size_from_name(path.name, source_w, source_h)

    if size_source == 'filename':
        if parsed is not None:
            print_w_mm, print_h_mm, rule = parsed
        else:
            print_w_mm = _px_to_mm(source_w, output_dpi)
            print_h_mm = _px_to_mm(source_h, output_dpi)
            rule = f'pixels@{output_dpi}dpi'
            if _has_bare_size_token(path.stem.lower()):
                warning = 'Ignored bare size-like token in file name; use 10x15cm, 100x150mm, max15cm, or max150mm.'
            else:
                warning = 'No explicit cm/mm size marker in file name; used pixels at output DPI.'
    elif size_source == 'dpi':
        print_w_mm = source_w / dpi_x * 25.4
        print_h_mm = source_h / dpi_y * 25.4
        rule = f'source-dpi:{dpi_x:g}x{dpi_y:g}'
    elif size_source == 'pixels':
        print_w_mm = _px_to_mm(source_w, output_dpi)
        print_h_mm = _px_to_mm(source_h, output_dpi)
        rule = f'pixels@{output_dpi}dpi'
    else:
        raise ValueError(f'Unsupported size source: {size_source}')

    target_w_px = _mm_to_px(print_w_mm, output_dpi)
    target_h_px = _mm_to_px(print_h_mm, output_dpi)

    return SheetItem(
        path=path,
        source_w_px=source_w,
        source_h_px=source_h,
        print_w_mm=print_w_mm,
        print_h_mm=print_h_mm,
        target_w_px=target_w_px,
        target_h_px=target_h_px,
        size_rule=rule,
        warning=warning,
    )


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


def measure_items(paths: list[Path], output_dpi: int, size_source: str, workers: int | None = 1) -> list[SheetItem]:
    worker_count = _effective_workers(workers, len(paths))
    if worker_count <= 1:
        return [measure_item(path, output_dpi, size_source=size_source) for path in paths]

    measured: list[SheetItem | None] = [None] * len(paths)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(measure_item, path, output_dpi, size_source): index
            for index, path in enumerate(paths)
        }
        for future in as_completed(futures):
            measured[futures[future]] = future.result()

    return [item for item in measured if item is not None]


def intersects(a: Rect, b: Rect) -> bool:
    return not (
        b.x >= a.x + a.w or
        b.x + b.w <= a.x or
        b.y >= a.y + a.h or
        b.y + b.h <= a.y
    )


def contains(a: Rect, b: Rect) -> bool:
    return b.x >= a.x and b.y >= a.y and b.x + b.w <= a.x + a.w and b.y + b.h <= a.y + a.h


class MaxRectsPacker:
    def __init__(self, width: int, height: int):
        self.free_rects = [Rect(0, 0, width, height)]

    def insert(self, w: int, h: int) -> Rect | None:
        best: Rect | None = None
        best_score = (10**18, 10**18, 10**18)
        for free in self.free_rects:
            if w <= free.w and h <= free.h:
                short = min(free.w - w, free.h - h)
                long = max(free.w - w, free.h - h)
                area = free.w * free.h - w * h
                score = (short, long, area)
                if best is None or score < best_score or (score == best_score and (free.y, free.x) < (best.y, best.x)):
                    best = Rect(free.x, free.y, w, h)
                    best_score = score
        if best is None:
            return None
        self._place(best)
        return best

    def _place(self, used: Rect) -> None:
        next_free: list[Rect] = []
        for free in self.free_rects:
            if not intersects(free, used):
                next_free.append(free)
                continue
            if used.y > free.y:
                next_free.append(Rect(free.x, free.y, free.w, used.y - free.y))
            if used.y + used.h < free.y + free.h:
                next_free.append(Rect(free.x, used.y + used.h, free.w, free.y + free.h - used.y - used.h))
            if used.x > free.x:
                next_free.append(Rect(free.x, free.y, used.x - free.x, free.h))
            if used.x + used.w < free.x + free.w:
                next_free.append(Rect(used.x + used.w, free.y, free.x + free.w - used.x - used.w, free.h))
        self.free_rects = self._prune(next_free)

    @staticmethod
    def _prune(rects: list[Rect]) -> list[Rect]:
        rects = [r for r in rects if r.w > 0 and r.h > 0]
        keep = [True] * len(rects)
        for i, rect in enumerate(rects):
            if not keep[i]:
                continue
            for j, other in enumerate(rects):
                if i != j and keep[j] and contains(other, rect):
                    keep[i] = False
                    break
        return [r for r, should_keep in zip(rects, keep) if should_keep]


def _sort_key(mode: str):
    if mode == 'area':
        return lambda item: (-(item.target_w_px * item.target_h_px), -max(item.target_w_px, item.target_h_px), item.path.name.lower())
    if mode == 'height':
        return lambda item: (-item.target_h_px, -item.target_w_px, item.path.name.lower())
    if mode == 'width':
        return lambda item: (-item.target_w_px, -item.target_h_px, item.path.name.lower())
    return lambda item: item.path.name.lower()


def pack_items_shelf(items: list[SheetItem], page_w_px: int, gap_px: int) -> tuple[list[Placement], list[SheetItem], str]:
    placements: list[Placement] = []
    unplaced: list[SheetItem] = []
    x = 0
    y = 0
    row_h = 0

    for item in sorted(items, key=lambda value: value.path.name.lower()):
        if item.target_w_px > page_w_px:
            unplaced.append(item)
            continue
        if x > 0 and x + item.target_w_px > page_w_px:
            x = 0
            y += row_h + gap_px
            row_h = 0
        placements.append(Placement(item=item, x=x, y=y, w=item.target_w_px, h=item.target_h_px))
        x += item.target_w_px + gap_px
        row_h = max(row_h, item.target_h_px)

    return placements, unplaced, 'shelf-name'


def _height_groups(items: list[SheetItem], tolerance_mm: float) -> list[list[SheetItem]]:
    groups: list[list[SheetItem]] = []
    group_heights: list[float] = []
    for item in sorted(items, key=lambda value: (-value.print_h_mm, value.path.name.lower())):
        target_index = None
        for index, height_mm in enumerate(group_heights):
            if abs(item.print_h_mm - height_mm) <= tolerance_mm:
                target_index = index
                break
        if target_index is None:
            groups.append([item])
            group_heights.append(item.print_h_mm)
        else:
            groups[target_index].append(item)
            group_heights[target_index] = max(group_heights[target_index], item.print_h_mm)
    return groups


def pack_items_cut_lines(
    items: list[SheetItem],
    page_w_px: int,
    gap_px: int,
    height_tolerance_mm: float,
) -> tuple[list[Placement], list[SheetItem], str]:
    placements: list[Placement] = []
    unplaced: list[SheetItem] = []
    y = 0

    for group in _height_groups(items, height_tolerance_mm):
        pending = sorted(group, key=lambda value: (-value.target_w_px, value.path.name.lower()))
        while pending:
            x = 0
            row: list[SheetItem] = []
            still_pending: list[SheetItem] = []
            for item in pending:
                if item.target_w_px > page_w_px:
                    unplaced.append(item)
                elif x + item.target_w_px <= page_w_px:
                    row.append(item)
                    x += item.target_w_px + gap_px
                else:
                    still_pending.append(item)

            if not row:
                break

            row_h = max(item.target_h_px for item in row)
            x = 0
            for item in row:
                placements.append(Placement(item=item, x=x, y=y, w=item.target_w_px, h=item.target_h_px))
                x += item.target_w_px + gap_px
            y += row_h + gap_px
            pending = still_pending

    return placements, unplaced, f'cut-lines height tolerance {height_tolerance_mm:g}mm'


def pack_items_maxrects(items: list[SheetItem], page_w_px: int, gap_px: int) -> tuple[list[Placement], list[SheetItem], str]:
    page_h_px = sum(item.target_h_px + gap_px for item in items) + 1
    best_placements: list[Placement] = []
    best_unplaced: list[SheetItem] = list(items)
    best_mode = ''

    for mode in ('area', 'height', 'width', 'name'):
        packer = MaxRectsPacker(page_w_px, page_h_px)
        placements: list[Placement] = []
        unplaced: list[SheetItem] = []
        for item in sorted(items, key=_sort_key(mode)):
            rect = packer.insert(item.target_w_px + gap_px, item.target_h_px + gap_px)
            if rect is None:
                unplaced.append(item)
            else:
                placements.append(Placement(item=item, x=rect.x, y=rect.y, w=item.target_w_px, h=item.target_h_px))

        used_h = max((p.y + p.h for p in placements), default=0)
        best_used_h = max((p.y + p.h for p in best_placements), default=10**18)
        if len(placements) > len(best_placements) or (len(placements) == len(best_placements) and used_h < best_used_h):
            best_placements = placements
            best_unplaced = unplaced
            best_mode = mode

    return best_placements, best_unplaced, best_mode


def pack_items(
    items: list[SheetItem],
    page_w_px: int,
    gap_px: int,
    layout: str,
    height_tolerance_mm: float,
) -> tuple[list[Placement], list[SheetItem], str]:
    if layout == 'maxrects':
        return pack_items_maxrects(items, page_w_px, gap_px)
    if layout == 'cut-lines':
        return pack_items_cut_lines(items, page_w_px, gap_px, height_tolerance_mm)
    return pack_items_shelf(items, page_w_px, gap_px)


def _render(
    placements: list[Placement],
    output_dir: Path,
    page_w_px: int,
    page_h_px: int,
    dpi: int,
    background: str,
    preview_width_px: int,
    out_format: str,
    jpeg_quality: int,
) -> tuple[Path, Path]:
    canvas = Image.new('RGB', (page_w_px, page_h_px), background)
    for placement in placements:
        with Image.open(placement.item.path) as image:
            image = ImageOps.exif_transpose(image)
            if image.size != (placement.w, placement.h):
                image = image.resize((placement.w, placement.h), RESAMPLE)
            if image.mode in {'RGBA', 'LA'} or 'transparency' in image.info:
                image = image.convert('RGBA')
                canvas.paste(image, (placement.x, placement.y), image)
            else:
                canvas.paste(flatten_alpha(image, background), (placement.x, placement.y))

    sheet_path = save_image(
        canvas,
        output_dir / f'photo_sheet_{round(_px_to_mm(page_w_px, dpi)):g}mm_{dpi}dpi',
        out_format,
        jpeg_quality=jpeg_quality,
        metadata='preserve_dpi_color',
        dpi=dpi,
    )

    preview = canvas
    if preview.width > preview_width_px:
        scale = preview_width_px / preview.width
        preview = preview.resize((preview_width_px, max(1, round(preview.height * scale))), RESAMPLE)
    if str(out_format).lower() == 'png':
        preview_path = output_dir / 'photo_sheet_preview.png'
        preview.save(preview_path, format='PNG', optimize=True)
    else:
        preview_path = output_dir / 'photo_sheet_preview.jpg'
        preview.save(preview_path, quality=90, optimize=True)
    return sheet_path, preview_path


def _write_reports(
    output_dir: Path,
    placements: list[Placement],
    unplaced: list[SheetItem],
    page_w_px: int,
    page_h_px: int,
    page_w_mm: float,
    dpi: int,
    gap_mm: float,
    size_source: str,
    layout: str,
    height_tolerance_mm: float,
    sort_mode: str,
    output_files: dict[str, str],
    requested_page_width_mm: float | None = None,
    required_page_width_mm: float | None = None,
    requested_dpi: int | None = None,
    required_dpi: int | None = None,
    warning_code: str = '',
    warning_message: str = '',
) -> None:
    required_width_mm = max((item.print_w_mm for item in unplaced), default=0.0)
    required_width_px = max((item.target_w_px for item in unplaced), default=0)
    too_wide = any(item.target_w_px > page_w_px for item in unplaced)

    report_path = output_dir / 'layout_report.csv'
    with report_path.open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file, delimiter=';')
        writer.writerow([
            'status', 'file', 'x_px', 'y_px', 'w_px', 'h_px', 'x_mm', 'y_mm',
            'w_mm', 'h_mm', 'source_w_px', 'source_h_px', 'size_rule', 'warning',
        ])
        for p in placements:
            writer.writerow([
                'placed', str(p.item.path), p.x, p.y, p.w, p.h,
                round(_px_to_mm(p.x, dpi), 3), round(_px_to_mm(p.y, dpi), 3),
                round(p.item.print_w_mm, 3), round(p.item.print_h_mm, 3),
                p.item.source_w_px, p.item.source_h_px, p.item.size_rule, p.item.warning,
            ])
        for item in unplaced:
            writer.writerow([
                'unplaced', str(item.path), '', '', item.target_w_px, item.target_h_px,
                '', '', round(item.print_w_mm, 3), round(item.print_h_mm, 3),
                item.source_w_px, item.source_h_px, item.size_rule, item.warning,
            ])

    summary = {
        'command': 'photo-sheet-width',
        'page_width_mm': page_w_mm,
        'auto_height_mm': round(_px_to_mm(page_h_px, dpi), 3),
        'dpi': dpi,
        'canvas_px': [page_w_px, page_h_px],
        'gap_mm': gap_mm,
        'size_source': size_source,
        'layout': layout,
        'height_tolerance_mm': height_tolerance_mm,
        'sort_mode': sort_mode,
        'input_images': len(placements) + len(unplaced),
        'placed': len(placements),
        'unplaced': len(unplaced),
        'outputs': output_files,
    }
    if requested_page_width_mm is not None and abs(float(requested_page_width_mm) - float(page_w_mm)) > 1e-6:
        summary['requested_page_width_mm'] = round(float(requested_page_width_mm), 3)
        summary['auto_page_width_mm'] = round(float(page_w_mm), 3)
        if required_page_width_mm is not None:
            summary['required_page_width_mm'] = round(float(required_page_width_mm), 3)
        summary['warning_code'] = 'page_width_auto_adjusted'
        summary['warning_message'] = warning_message
    if requested_dpi is not None and int(requested_dpi) != int(dpi):
        summary['requested_dpi'] = int(requested_dpi)
        summary['auto_dpi'] = int(dpi)
        if required_dpi is not None:
            summary['required_dpi'] = int(required_dpi)
        summary['warning_code'] = warning_code or 'dpi_auto_adjusted'
        summary['warning_message'] = warning_message
    if unplaced:
        summary['unplaced_reason'] = 'page_width_too_small' if too_wide else 'layout_constraints'
        summary['required_page_width_mm'] = round(required_width_mm, 3)
        summary['required_page_width_px'] = required_width_px
    (output_dir / 'layout_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    lines = [
        'Audion Photo Sheet Width summary',
        '',
        f'Width: {page_w_mm:g} mm',
        f'Auto height: {_px_to_mm(page_h_px, dpi):.2f} mm',
        f'DPI: {dpi}',
        f'Canvas: {page_w_px} x {page_h_px} px',
        f'Gap: {gap_mm:g} mm',
        f'Size source: {size_source}',
        f'Layout: {layout}',
        f'Height tolerance: {height_tolerance_mm:g} mm',
        f'Sort mode: {sort_mode}',
        f'Placed: {len(placements)}',
        f'Unplaced: {len(unplaced)}',
        '',
        f'Sheet ({output_files.get("format", "")}): {output_files.get("sheet", "")}',
        f'Preview: {output_files.get("preview", "")}',
        'Cut plan: cut_plan.txt',
        'Report: layout_report.csv',
    ]
    if warning_message:
        lines.append('')
        lines.append(f'Warning: {warning_message}')
    if unplaced:
        lines.append('')
        if required_width_mm:
            lines.append(f'Required sheet width for widest unplaced item: more than {required_width_mm:.3f} mm')
        lines.append('Unplaced files:')
        lines.extend(f'- {item.path.name}: {item.warning}' for item in unplaced)
    (output_dir / 'layout_summary.txt').write_text('\n'.join(lines), encoding='utf-8')

    _write_cut_plan(output_dir, placements, dpi)


def _write_cut_plan(output_dir: Path, placements: list[Placement], dpi: int) -> None:
    rows: list[list[Placement]] = []
    for y in sorted({p.y for p in placements}):
        rows.append(sorted([p for p in placements if p.y == y], key=lambda value: value.x))

    lines = [
        'Audion Photo Sheet cut plan',
        '',
        'Coordinates are measured from the top-left corner.',
        'Cut horizontal strips first, then cut each strip vertically.',
        '',
        'Horizontal cuts from top edge:',
    ]

    for index, row in enumerate(rows, start=1):
        row_y = row[0].y
        row_h = max(p.h for p in row)
        y2 = row_y + row_h
        lines.append(f'{index:02d}. y={_px_to_mm(y2, dpi):.3f} mm')

    lines.append('')
    lines.append('Strips:')

    for index, row in enumerate(rows, start=1):
        row_y = row[0].y
        row_h = max(p.h for p in row)
        y1_mm = _px_to_mm(row_y, dpi)
        y2_mm = _px_to_mm(row_y + row_h, dpi)
        lines.append('')
        lines.append(f'Strip {index:02d}: y={y1_mm:.3f}..{y2_mm:.3f} mm, height={_px_to_mm(row_h, dpi):.3f} mm')
        lines.append('Vertical cuts from left edge:')
        for cut_index, placement in enumerate(row, start=1):
            x2 = placement.x + placement.w
            lines.append(
                f'  {cut_index:02d}. x={_px_to_mm(x2, dpi):.3f} mm | '
                f'{placement.item.path.name} | '
                f'{placement.item.print_w_mm:.3f} x {placement.item.print_h_mm:.3f} mm'
            )

    (output_dir / 'cut_plan.txt').write_text('\n'.join(lines), encoding='utf-8')


def build_photo_sheet_by_width(
    input_path: Path,
    output_dir: Path,
    page_width_mm: float,
    dpi: int,
    gap_mm: float = 0.0,
    size_source: str = 'pixels',
    layout: str = 'shelf',
    height_tolerance_mm: float = 0.2,
    recursive: bool = False,
    background: str = 'white',
    preview_width_px: int = 1800,
    out_format: str = 'png',
    jpeg_quality: int = 90,
    workers: int = 1,
) -> dict:
    if page_width_mm <= 0:
        raise ValueError('page_width_mm must be greater than zero')
    if dpi <= 0:
        raise ValueError('dpi must be greater than zero')

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = discover_sheet_images(input_path, recursive=recursive)
    if not paths:
        raise ValueError(f'No supported images found: {input_path}')

    effective_workers = _effective_workers(workers, len(paths))
    requested_dpi = int(dpi)
    required_dpi: int | None = None
    warning_code = ''
    items = measure_items(paths, dpi, size_source=size_source, workers=effective_workers)
    requested_page_width_mm = float(page_width_mm)
    page_w_px = _mm_to_px(page_width_mm, dpi)
    required_item_width_px = max((item.target_w_px for item in items), default=page_w_px)
    required_item_width_mm = _px_to_mm(required_item_width_px, dpi)
    warning_message = ''
    if required_item_width_px > page_w_px:
        if size_source == 'pixels':
            required_dpi = max(requested_dpi, int(math.ceil(required_item_width_px * 25.4 / page_width_mm)))
            dpi = required_dpi
            items = measure_items(paths, dpi, size_source=size_source, workers=effective_workers)
            page_w_px = _mm_to_px(page_width_mm, dpi)
            required_item_width_px = max((item.target_w_px for item in items), default=page_w_px)
            required_item_width_mm = _px_to_mm(required_item_width_px, dpi)
            warning_code = 'dpi_auto_adjusted'
            warning_message = (
                f'Sheet width {requested_page_width_mm:g} mm at {requested_dpi} DPI was too narrow '
                f'for unchanged source pixels. Automatically increased sheet DPI to {dpi}; '
                f'required DPI is at least {required_dpi}.'
            )
        else:
            warning_code = 'page_width_too_small'
    gap_px = max(0, _mm_to_px(gap_mm, dpi) if gap_mm > 0 else 0)
    placements, unplaced, sort_mode = pack_items(
        items,
        page_w_px,
        gap_px,
        layout=layout,
        height_tolerance_mm=max(0.0, height_tolerance_mm),
    )
    for item in unplaced:
        if not item.warning and item.target_w_px > page_w_px:
            item.warning = (
                f'Item print width {item.print_w_mm:.3f} mm exceeds '
                f'page width {page_width_mm:g} mm.'
            )
    if not placements:
        required_width_mm = max((item.print_w_mm for item in unplaced), default=page_width_mm)
        too_wide = any(item.target_w_px > page_w_px for item in unplaced)
        output_files = {
            'sheet': '',
            'format': out_format,
            'preview': '',
            'cut_plan': str(output_dir / 'cut_plan.txt'),
        }
        _write_reports(
            output_dir=output_dir,
            placements=[],
            unplaced=unplaced,
            page_w_px=page_w_px,
            page_h_px=1,
            page_w_mm=page_width_mm,
            dpi=dpi,
            gap_mm=gap_mm,
            size_source=size_source,
            layout=layout,
            height_tolerance_mm=height_tolerance_mm,
            sort_mode=sort_mode,
            output_files=output_files,
            requested_page_width_mm=requested_page_width_mm,
            required_page_width_mm=required_item_width_mm,
            requested_dpi=requested_dpi,
            required_dpi=required_dpi,
            warning_code=warning_code,
            warning_message=warning_message,
        )
        return {
            'placed': 0,
            'unplaced': len(unplaced),
            'width_mm': page_width_mm,
            'height_mm': round(_px_to_mm(1, dpi), 3),
            'requested_dpi': requested_dpi,
            'dpi': dpi,
            **({'required_dpi': required_dpi} if required_dpi is not None else {}),
            'workers': effective_workers,
            'outputs': output_files,
            'error_code': 'page_width_too_small' if too_wide else 'no_images_placed',
            'required_page_width_mm': round(required_width_mm, 3),
            'error': (
                f'Page width {page_width_mm:g} mm is too small. '
                f'Required sheet width is more than {required_width_mm:.3f} mm.'
                if too_wide
                else 'No images could be placed on the sheet. See layout_report.csv for unplaced files.'
            ),
        }

    page_h_px = max(1, max(p.y + p.h for p in placements))
    sheet_path, preview_path = _render(
        placements,
        output_dir,
        page_w_px=page_w_px,
        page_h_px=page_h_px,
        dpi=dpi,
        background=background,
        preview_width_px=preview_width_px,
        out_format=out_format,
        jpeg_quality=jpeg_quality,
    )
    output_files = {
        'sheet': str(sheet_path),
        'format': out_format,
        'preview': str(preview_path),
        'cut_plan': str(output_dir / 'cut_plan.txt'),
    }
    output_files[out_format] = str(sheet_path)
    _write_reports(
        output_dir=output_dir,
        placements=placements,
        unplaced=unplaced,
        page_w_px=page_w_px,
        page_h_px=page_h_px,
        page_w_mm=page_width_mm,
        dpi=dpi,
        gap_mm=gap_mm,
        size_source=size_source,
        layout=layout,
        height_tolerance_mm=height_tolerance_mm,
        sort_mode=sort_mode,
        output_files=output_files,
        requested_page_width_mm=requested_page_width_mm,
        required_page_width_mm=required_item_width_mm,
        requested_dpi=requested_dpi,
        required_dpi=required_dpi,
        warning_code=warning_code,
        warning_message=warning_message,
    )
    return {
        'input_images': len(items),
        'placed': len(placements),
        'unplaced': len(unplaced),
        'requested_width_mm': requested_page_width_mm,
        'width_mm': page_width_mm,
        'required_page_width_mm': round(required_item_width_mm, 3),
        'height_mm': round(_px_to_mm(page_h_px, dpi), 3),
        'requested_dpi': requested_dpi,
        'dpi': dpi,
        **({'required_dpi': required_dpi} if required_dpi is not None else {}),
        'workers': effective_workers,
        'outputs': output_files,
        **({'warning_code': warning_code, 'warning_message': warning_message} if warning_message else {}),
    }
