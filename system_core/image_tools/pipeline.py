from __future__ import annotations

import io
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageSequence

try:
    from PIL import ImageCms
except Exception:
    ImageCms = None

from .constants import PNG_PRESETS, SCREEN_TARGETS, ASPECT_RATIOS
from .io_utils import ensure_dir, open_image


RESAMPLING = getattr(Image, 'Resampling', Image)
RESAMPLE = RESAMPLING.LANCZOS
NEAREST = RESAMPLING.NEAREST
RESAMPLE_METHODS = {
    'lanczos': RESAMPLING.LANCZOS,
    'bicubic': RESAMPLING.BICUBIC,
    'box': RESAMPLING.BOX,
    'nearest': RESAMPLING.NEAREST,
}
KEEP_ICC = object()
OUTPUT_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.avif', '.heif', '.heic'}


def _with_output_suffix(path: Path, suffix: str) -> Path:
    if path.suffix.lower() in OUTPUT_IMAGE_SUFFIXES:
        return path.with_suffix(suffix)
    return Path(str(path) + suffix)


def _available_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    if path.is_file():
        return path

    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = parent / f'{stem}__file_{index:03d}{suffix}'
        if not candidate.exists():
            return candidate
    raise FileExistsError(f'Cannot find free output filename near directory: {path}')


def _permission_fallback_path(path: Path) -> Path:
    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = parent / f'{stem}__retry_{index:03d}{suffix}'
        if not candidate.exists():
            return candidate
    raise PermissionError(f'Cannot find writable output filename near: {path}')


def _quality_value(value: int | float | str | None, default: int = 75) -> int:
    try:
        quality = int(float(str(value).replace(',', '.')))
    except (TypeError, ValueError):
        quality = default
    return max(1, min(100, quality))


def resample_method(algorithm: str | None):
    key = (algorithm or 'lanczos').lower()
    try:
        return RESAMPLE_METHODS[key]
    except KeyError:
        supported = ', '.join(sorted(RESAMPLE_METHODS))
        raise ValueError(f'Unsupported resize algorithm: {algorithm}. Supported: {supported}')


def parse_color(value: str) -> tuple[int, int, int]:
    value = str(value)
    if value.lower() == 'white':
        return (255, 255, 255)
    if value.lower() == 'black':
        return (0, 0, 0)
    return ImageColor.getrgb(value)


def flatten_alpha(image: Image.Image, background: str = 'white') -> Image.Image:
    bg = parse_color(background)
    if image.mode in {'RGBA', 'LA'}:
        base = Image.new('RGBA', image.size, bg + (255,))
        merged = Image.alpha_composite(base, image.convert('RGBA'))
        return merged.convert('RGB')
    if image.mode == 'P' and 'transparency' in image.info:
        return flatten_alpha(image.convert('RGBA'), background)
    return image.convert('RGB')


def safe_rgb(image: Image.Image, background: str = 'white') -> Image.Image:
    if image.mode == 'RGB':
        return image
    if image.mode in {'RGBA', 'LA', 'P'}:
        return flatten_alpha(image, background)
    if image.mode == 'CMYK':
        return image.convert('RGB')
    return image.convert('RGB')


def resolve_profile_path(profile_path: str | None, fallbacks: tuple[str, ...] = ()) -> Path | None:
    candidates: list[Path] = []
    if profile_path:
        candidates.append(Path(profile_path))
    candidates.extend(Path(name) for name in fallbacks)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _icc_bytes_from_profile(profile) -> bytes | None:
    if ImageCms is None or profile is None:
        return None
    try:
        if hasattr(profile, 'tobytes'):
            return profile.tobytes()
        return ImageCms.ImageCmsProfile(profile).tobytes()
    except Exception:
        return None


def _set_output_icc(image: Image.Image, icc_bytes: bytes | None | object) -> Image.Image:
    if icc_bytes is KEEP_ICC:
        return image
    if icc_bytes:
        image.info['icc_profile'] = icc_bytes
    else:
        image.info.pop('icc_profile', None)
    return image


def normalize_profile(
    image: Image.Image,
    target_profile: str,
    cmyk_profile_path: str | None = None,
    background: str = 'white',
    srgb_profile_mode: str = 'colororg',
    srgb_profile_path: str | None = None,
    embed_srgb_profile: bool = True,
    embed_cmyk_profile: bool = False,
) -> Image.Image:
    target_profile = (target_profile or 'keep').lower()
    if target_profile == 'keep':
        return image

    if target_profile == 'srgb':
        dst_icc_bytes = None
        if ImageCms is not None:
            try:
                embedded = image.info.get('icc_profile')
                if embedded:
                    src = ImageCms.ImageCmsProfile(__import__('io').BytesIO(embedded))
                    if (srgb_profile_mode or 'colororg').lower() == 'pillow':
                        dst = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
                    else:
                        dst_path = resolve_profile_path(
                            srgb_profile_path or 'config/icc/sRGB2014.icc',
                            (
                                'config/icc/sRGB2014.icc',
                            ),
                        )
                        dst = ImageCms.getOpenProfile(str(dst_path)) if dst_path is not None else ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
                    dst_icc_bytes = _icc_bytes_from_profile(dst)
                    if image.mode in {'RGBA', 'LA', 'P'}:
                        image = flatten_alpha(image, background)
                    if image.mode not in {'RGB', 'CMYK', 'L'}:
                        image = image.convert('RGB')
                    converted = ImageCms.profileToProfile(image, src, dst, outputMode='RGB')
                    return _set_output_icc(converted, dst_icc_bytes if embed_srgb_profile else None)
            except Exception:
                pass
        converted = safe_rgb(image, background)
        if (srgb_profile_mode or 'colororg').lower() == 'colororg':
            dst_path = resolve_profile_path(
                srgb_profile_path or 'config/icc/sRGB2014.icc',
                ('config/icc/sRGB2014.icc',),
            )
            if dst_path is not None:
                try:
                    dst_icc_bytes = Path(dst_path).read_bytes()
                except Exception:
                    dst_icc_bytes = None
        return _set_output_icc(converted, dst_icc_bytes if embed_srgb_profile else None)

    if target_profile == 'cmyk':
        if ImageCms is not None and cmyk_profile_path:
            profile_path = resolve_profile_path(
                cmyk_profile_path,
                (
                    'config/icc/Photoshop5DefaultCMYK.icc',
                    'config/icc/CoatedFOGRA39.icc',
                ),
            )
            if profile_path is not None:
                try:
                    dst = ImageCms.getOpenProfile(str(profile_path))
                    dst_icc_bytes = _icc_bytes_from_profile(dst)
                    embedded = image.info.get('icc_profile')
                    if embedded:
                        src = ImageCms.ImageCmsProfile(__import__('io').BytesIO(embedded))
                    else:
                        src = ImageCms.createProfile('sRGB')
                        image = safe_rgb(image, background)
                    if image.mode in {'RGBA', 'LA', 'P'}:
                        image = flatten_alpha(image, background)
                    if image.mode not in {'RGB', 'CMYK', 'L'}:
                        image = image.convert('RGB')
                    converted = ImageCms.profileToProfile(image, src, dst, outputMode='CMYK')
                    return _set_output_icc(converted, dst_icc_bytes if embed_cmyk_profile else None)
                except Exception:
                    pass
        if image.mode in {'RGBA', 'LA', 'P'}:
            image = flatten_alpha(image, background)
        return _set_output_icc(image.convert('CMYK'), None)

    return image


def apply_metadata_policy(
    src: Image.Image,
    save_kwargs: dict,
    metadata: str,
    dpi: int | float | None,
    embedded_icc: bytes | None | object = KEEP_ICC,
    metadata_fallback: Image.Image | None = None,
) -> dict:
    metadata = (metadata or 'preserve_dpi_color').lower()
    fallback_info = metadata_fallback.info if metadata_fallback is not None else {}
    if dpi is not None:
        save_kwargs['dpi'] = (dpi, dpi)
    elif 'dpi' in src.info:
        src_dpi = src.info.get('dpi')
        if src_dpi:
            save_kwargs['dpi'] = src_dpi
    elif fallback_info.get('dpi'):
        save_kwargs['dpi'] = fallback_info.get('dpi')

    if metadata == 'strip_all':
        save_kwargs.pop('icc_profile', None)
        save_kwargs.pop('exif', None)
        if dpi is None:
            save_kwargs.pop('dpi', None)
        return save_kwargs

    if metadata in {'preserve_dpi_color', 'preserve_all'}:
        if embedded_icc is KEEP_ICC:
            icc = src.info.get('icc_profile') or fallback_info.get('icc_profile')
            if icc:
                save_kwargs['icc_profile'] = icc
        elif embedded_icc:
            save_kwargs['icc_profile'] = embedded_icc
        else:
            save_kwargs.pop('icc_profile', None)

    if metadata == 'preserve_all':
        exif = src.info.get('exif') or fallback_info.get('exif')
        if exif:
            save_kwargs['exif'] = exif

    return save_kwargs


def _prepare_image_for_save(
    src_image: Image.Image,
    out_format: str,
    jpeg_quality: int = 75,
    png_preset: str = 'balanced',
    alpha_bg: str = 'white',
) -> tuple[Image.Image, dict, str]:
    out_format = out_format.lower()
    save_kwargs: dict = {}

    if out_format == 'jpg':
        image = flatten_alpha(src_image, alpha_bg)
        save_kwargs.update({'format': 'JPEG', 'quality': _quality_value(jpeg_quality), 'optimize': True})
        suffix = '.jpg'
    elif out_format == 'png':
        image = src_image.convert('RGB') if src_image.mode == 'CMYK' else src_image
        preset = PNG_PRESETS.get(png_preset, PNG_PRESETS['balanced'])
        save_kwargs.update({'format': 'PNG', **preset})
        suffix = '.png'
    elif out_format == 'tiff':
        image = src_image
        save_kwargs.update({'format': 'TIFF'})
        suffix = '.tiff'
    elif out_format == 'webp':
        image = safe_rgb(src_image, alpha_bg)
        save_kwargs.update({'format': 'WEBP', 'quality': _quality_value(jpeg_quality), 'method': 4})
        suffix = '.webp'
    elif out_format == 'avif':
        image = safe_rgb(src_image, alpha_bg)
        save_kwargs.update({'format': 'AVIF', 'quality': _quality_value(jpeg_quality)})
        suffix = '.avif'
    elif out_format in {'heif', 'heic'}:
        image = safe_rgb(src_image, alpha_bg)
        save_kwargs.update({'format': 'HEIF', 'quality': _quality_value(jpeg_quality)})
        suffix = f'.{out_format}'
    else:
        raise ValueError(f'Unsupported output format: {out_format}')

    return image, save_kwargs, suffix


def encoded_image_size(
    src_image: Image.Image,
    out_format: str,
    jpeg_quality: int = 75,
    png_preset: str = 'balanced',
    metadata: str = 'preserve_dpi_color',
    dpi: int | float | None = None,
    alpha_bg: str = 'white',
    embedded_icc: bytes | None | object = KEEP_ICC,
    metadata_source: Image.Image | None = None,
) -> int:
    image, save_kwargs, _suffix = _prepare_image_for_save(src_image, out_format, jpeg_quality, png_preset, alpha_bg)
    save_kwargs = apply_metadata_policy(
        src_image,
        save_kwargs,
        metadata,
        dpi,
        embedded_icc=embedded_icc,
        metadata_fallback=metadata_source,
    )
    buffer = io.BytesIO()
    image.save(buffer, **save_kwargs)
    return buffer.tell()


def save_image(
    src_image: Image.Image,
    out_path: Path,
    out_format: str,
    jpeg_quality: int = 75,
    png_preset: str = 'balanced',
    metadata: str = 'preserve_dpi_color',
    dpi: int | float | None = None,
    alpha_bg: str = 'white',
    embedded_icc: bytes | None | object = KEEP_ICC,
    metadata_source: Image.Image | None = None,
) -> Path:
    image, save_kwargs, suffix = _prepare_image_for_save(src_image, out_format, jpeg_quality, png_preset, alpha_bg)
    out_path = _with_output_suffix(out_path, suffix)

    out_path = _available_output_path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_kwargs = apply_metadata_policy(
        src_image,
        save_kwargs,
        metadata,
        dpi,
        embedded_icc=embedded_icc,
        metadata_fallback=metadata_source,
    )
    try:
        image.save(out_path, **save_kwargs)
    except PermissionError:
        retry_path = _permission_fallback_path(out_path)
        image.save(retry_path, **save_kwargs)
        out_path = retry_path
    return out_path


def _resize_scale_for_box(image: Image.Image, size: tuple[int, int], mode: str) -> float:
    mode = mode.lower()
    if mode == 'crop':
        return max(size[0] / image.width, size[1] / image.height)
    if mode in {'contain', 'pad'}:
        return min(size[0] / image.width, size[1] / image.height)
    if mode == 'by-height':
        return size[1] / image.height
    if mode == 'by-width':
        return size[0] / image.width
    return 1.0


def resize_to_screen(image: Image.Image, target: str, mode: str = 'crop', background: str = 'black') -> Image.Image:
    size = SCREEN_TARGETS[target]
    scale = _resize_scale_for_box(image, size, mode)
    resized = resize_to_box(image, size, mode, background)
    if target == '2160p' and scale > 1.0:
        return resized.filter(ImageFilter.UnsharpMask(radius=0.8, percent=80, threshold=2))
    return resized


def resize_to_box(image: Image.Image, size: tuple[int, int], mode: str = 'crop', background: str = 'black') -> Image.Image:
    mode = mode.lower()
    if mode == 'crop':
        return ImageOps.fit(image, size, method=RESAMPLE, centering=(0.5, 0.5))
    if mode == 'contain':
        return ImageOps.contain(image, size, method=RESAMPLE)
    if mode == 'pad':
        return ImageOps.pad(image, size, method=RESAMPLE, color=parse_color(background), centering=(0.5, 0.5))
    if mode == 'by-height':
        ratio = size[1] / image.height
        new_size = (max(1, round(image.width * ratio)), size[1])
        return image.resize(new_size, RESAMPLE)
    if mode == 'by-width':
        ratio = size[0] / image.width
        new_size = (size[0], max(1, round(image.height * ratio)))
        return image.resize(new_size, RESAMPLE)
    raise ValueError(f'Unsupported resize mode: {mode}')


def ratio_size(ratio_name: str, long_edge: int | None = None, explicit_size: tuple[int, int] | None = None) -> tuple[int, int]:
    if explicit_size is not None:
        return explicit_size
    w, h = ASPECT_RATIOS[ratio_name]
    if long_edge is None:
        long_edge = 3840
    if w >= h:
        return (long_edge, max(1, round(long_edge * h / w)))
    return (max(1, round(long_edge * w / h)), long_edge)


def grayscale_image(image: Image.Image) -> Image.Image:
    return ImageOps.grayscale(image)


def _difference_bbox(diff: Image.Image, tolerance: int) -> tuple[int, int, int, int] | None:
    limit = max(0, min(255, int(tolerance)))
    mask = Image.new('L', diff.size, 0)
    for channel in diff.split():
        channel_mask = channel.point(lambda p, limit=limit: 255 if p > limit else 0)
        mask = ImageChops.lighter(mask, channel_mask)
    return mask.getbbox()


def _image_dpi_xy(image: Image.Image, fallback: float = 300.0) -> tuple[float, float]:
    raw_dpi = image.info.get('dpi')
    try:
        if isinstance(raw_dpi, (tuple, list)) and raw_dpi:
            x_dpi = float(raw_dpi[0])
            y_dpi = float(raw_dpi[1] if len(raw_dpi) > 1 else raw_dpi[0])
        elif raw_dpi:
            x_dpi = y_dpi = float(raw_dpi)
        else:
            x_dpi = y_dpi = fallback
    except (TypeError, ValueError):
        x_dpi = y_dpi = fallback
    if x_dpi <= 0:
        x_dpi = fallback
    if y_dpi <= 0:
        y_dpi = fallback
    return x_dpi, y_dpi


def _safety_margin_px(image: Image.Image, margin_mm: float) -> tuple[int, int]:
    try:
        margin = max(0.0, float(margin_mm or 0))
    except (TypeError, ValueError):
        margin = 0.0
    if margin <= 0:
        return 0, 0
    x_dpi, y_dpi = _image_dpi_xy(image)
    return math.ceil(margin / 25.4 * x_dpi), math.ceil(margin / 25.4 * y_dpi)


def _expand_bbox(
    bbox: tuple[int, int, int, int],
    size: tuple[int, int],
    margin_px: tuple[int, int],
) -> tuple[int, int, int, int]:
    x_margin, y_margin = margin_px
    if x_margin <= 0 and y_margin <= 0:
        return bbox
    left, top, right, bottom = bbox
    width, height = size
    return (
        max(0, left - x_margin),
        max(0, top - y_margin),
        min(width, right + x_margin),
        min(height, bottom + y_margin),
    )


def trim_border(image: Image.Image, tolerance: int = 10, safety_margin_mm: float = 0.0) -> Image.Image:
    rgb = safe_rgb(image)
    bg_color = rgb.getpixel((0, 0))
    bg = Image.new('RGB', rgb.size, bg_color)
    diff = ImageChops.difference(rgb, bg)
    bbox = _difference_bbox(diff, tolerance)
    if not bbox:
        return image
    bbox = _expand_bbox(bbox, image.size, _safety_margin_px(image, safety_margin_mm))
    return image.crop(bbox)


def trim_white_border(image: Image.Image, tolerance: int = 10, safety_margin_mm: float = 0.0) -> Image.Image:
    rgb = safe_rgb(image)
    bg = Image.new('RGB', rgb.size, 'white')
    diff = ImageChops.difference(rgb, bg)
    bbox = _difference_bbox(diff, tolerance)
    if not bbox:
        return image
    bbox = _expand_bbox(bbox, image.size, _safety_margin_px(image, safety_margin_mm))
    return image.crop(bbox)


def _watermark_font(font_size: int):
    size = max(1, int(font_size or 1))
    for font_name in (
        'arialbd.ttf',
        'Arial Bold.ttf',
        'arial.ttf',
        'Arial.ttf',
        str(Path(r'C:\Windows\Fonts\arialbd.ttf')),
        str(Path(r'C:\Windows\Fonts\arial.ttf')),
    ):
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_watermark_font(text: str, target_width: float, max_font_size: int):
    probe = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    low = 6
    high = max(low, int(max_font_size))
    best = _watermark_font(low)
    while low <= high:
        mid = (low + high) // 2
        font = _watermark_font(mid)
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        if width <= target_width:
            best = font
            low = mid + 1
        else:
            high = mid - 1
    return best


def _watermark_rgb(color: str) -> tuple[int, int, int]:
    raw = str(color or '#ffffff').strip()
    try:
        return ImageColor.getrgb(raw)
    except Exception:
        parts = [part.strip() for part in raw.replace(';', ',').split(',')]
        if len(parts) == 3:
            try:
                return tuple(max(0, min(255, int(float(part)))) for part in parts)  # type: ignore[return-value]
            except Exception:
                pass
        return ImageColor.getrgb('#ffffff')


def add_text_watermark(
    image: Image.Image,
    text: str,
    position: str = 'bottom-right',
    margin: int = 32,
    opacity: int = 64,
    font_size: int = 36,
    color: str = '#ffffff',
    watermark_mode: str = 'corner',
    diagonal_coverage: float = 0.6,
) -> Image.Image:
    base = image.convert('RGBA')
    overlay = Image.new('RGBA', base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fill = _watermark_rgb(color) + (max(0, min(255, opacity)),)
    mode = (watermark_mode or 'corner').lower()

    if mode in {'diagonal', 'diagonal-70', 'protective'}:
        diagonal = math.hypot(base.width, base.height)
        coverage = float(diagonal_coverage or 0.6)
        if coverage > 1.0:
            coverage = coverage / 100.0
        coverage = max(0.05, min(1.5, coverage))
        target_width = diagonal * coverage
        max_font_size = max(8, round(min(base.size) * 0.45))
        font = _fit_watermark_font(text, target_width, max_font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        padding = max(16, round(text_h * 0.45))
        text_layer = Image.new('RGBA', (text_w + padding * 2, text_h + padding * 2), (0, 0, 0, 0))
        text_draw = ImageDraw.Draw(text_layer)
        text_draw.text((padding - bbox[0], padding - bbox[1]), text, font=font, fill=fill)
        angle = math.degrees(math.atan2(base.height, base.width))
        rotated = text_layer.rotate(angle, resample=RESAMPLING.BICUBIC, expand=True)
        xy = ((base.width - rotated.width) // 2, (base.height - rotated.height) // 2)
        overlay.alpha_composite(rotated, xy)
        return Image.alpha_composite(base, overlay)

    font = _watermark_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    if position == 'bottom-right':
        xy = (base.width - text_w - margin, base.height - text_h - margin)
    elif position == 'bottom-left':
        xy = (margin, base.height - text_h - margin)
    elif position == 'top-left':
        xy = (margin, margin)
    else:
        xy = (base.width - text_w - margin, margin)
    draw.text(xy, text, font=font, fill=fill)
    return Image.alpha_composite(base, overlay)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    text = str(text)
    if _text_width(draw, text, font) <= max_width:
        return text
    suffix = '...'
    if _text_width(draw, suffix, font) > max_width:
        return ''
    for length in range(len(text) - 1, 0, -1):
        candidate = text[:length].rstrip() + suffix
        if _text_width(draw, candidate, font) <= max_width:
            return candidate
    return suffix


def _load_contact_sheet_font(size: int) -> ImageFont.ImageFont:
    for font_name in ('arial.ttf', 'segoeui.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    for font_path in (
        Path('C:/Windows/Fonts/arial.ttf'),
        Path('C:/Windows/Fonts/segoeui.ttf'),
        Path('C:/Windows/Fonts/DejaVuSans.ttf'),
    ):
        if not font_path.exists():
            continue
        try:
            return ImageFont.truetype(str(font_path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_contact_sheet(
    images: list[Image.Image],
    columns: int,
    thumb_size: tuple[int, int],
    background: str = 'white',
    spacing: int = 20,
    labels: list[str] | None = None,
    label_height: int = 64,
    border_size: int = 1,
    border_color: str = '#cccccc',
    text_color: str = '#222222',
    font_size: int = 14,
) -> Image.Image:
    if not images:
        raise ValueError('No images provided for contact sheet')
    columns = max(1, columns)
    rows = math.ceil(len(images) / columns)
    tw, th = thumb_size
    has_labels = bool(labels)
    label_area = max(0, label_height) if has_labels else 0
    sheet_w = columns * tw + (columns + 1) * spacing
    sheet_h = rows * (th + label_area) + (rows + 1) * spacing
    sheet = Image.new('RGB', (sheet_w, sheet_h), parse_color(background))
    draw = ImageDraw.Draw(sheet)
    font = _load_contact_sheet_font(font_size)
    line_bbox = draw.textbbox((0, 0), 'Ag', font=font)
    line_height = line_bbox[3] - line_bbox[1]
    label_padding = 6
    max_label_lines = max(1, (label_area - label_padding) // max(1, line_height + 2)) if label_area else 0
    border_rgb = parse_color(border_color)
    text_rgb = parse_color(text_color)
    for idx, image in enumerate(images):
        row = idx // columns
        col = idx % columns
        thumb = ImageOps.pad(safe_rgb(image), thumb_size, method=RESAMPLE, color=parse_color(background))
        x = spacing + col * (tw + spacing)
        y = spacing + row * (th + label_area + spacing)
        sheet.paste(thumb, (x, y))
        for offset in range(max(0, border_size)):
            draw.rectangle((x + offset, y + offset, x + tw - 1 - offset, y + th - 1 - offset), outline=border_rgb)
        if has_labels and idx < len(labels):
            text_y = y + th + label_padding
            max_text_width = max(1, tw)
            for line in str(labels[idx]).splitlines()[:max_label_lines]:
                fitted = _fit_text(draw, line, font, max_text_width)
                if fitted:
                    draw.text((x, text_y), fitted, font=font, fill=text_rgb)
                text_y += line_height + 2
    return sheet


def iter_frames(image: Image.Image):
    for frame in ImageSequence.Iterator(image):
        yield frame.copy()


def split_tiff_to_png(input_path: Path, output_dir: Path, prefix: str | None = None) -> list[Path]:
    ensure_dir(output_dir)
    image = open_image(input_path)
    stem = prefix or input_path.stem
    total_frames = max(1, int(getattr(image, 'n_frames', 1)))
    written: list[Path] = []
    for idx, frame in enumerate(iter_frames(image), start=1):
        if total_frames > 1:
            out_path = output_dir / f'{idx:03d}_{stem}.png'
        else:
            out_path = output_dir / f'{stem}.png'
        written.append(save_image(frame, out_path, 'png', metadata='strip_all', metadata_source=image))
    return written


def resize_by_percent(image: Image.Image, percent: int | float, algorithm: str = 'lanczos', unsharp: bool = True) -> Image.Image:
    algorithm = (algorithm or 'lanczos').lower()
    if percent <= 0:
        raise ValueError('Percent must be > 0')
    method = resample_method(algorithm)
    new_w = max(1, round(image.width * percent / 100.0))
    new_h = max(1, round(image.height * percent / 100.0))
    resized = image.resize((new_w, new_h), method)
    if algorithm == 'lanczos' and unsharp:
        return resized.filter(ImageFilter.UnsharpMask(radius=0.8, percent=80, threshold=2))
    return resized


def fit_resize_to_target_bytes(
    image: Image.Image,
    target_bytes: int,
    out_format: str,
    algorithm: str = 'lanczos',
    unsharp: bool = True,
    jpeg_quality: int = 75,
    png_preset: str = 'balanced',
    metadata: str = 'preserve_dpi_color',
    dpi: int | float | None = None,
    dpi_for_percent=None,
    alpha_bg: str = 'white',
    embedded_icc: bytes | None | object = KEEP_ICC,
    metadata_source: Image.Image | None = None,
    min_percent: float = 1.0,
    max_percent: float = 100.0,
    iterations: int = 18,
    probe_workers: int = 1,
) -> tuple[Image.Image, float, int]:
    if target_bytes <= 0:
        raise ValueError('target_bytes must be > 0')
    min_percent = max(0.1, min(float(min_percent), 100.0))
    max_percent = max(min_percent, min(float(max_percent), 100.0))

    size_cache: dict[float, int] = {}

    def candidate_size(percent_value: float) -> int:
        key = round(max(min_percent, min(max_percent, float(percent_value))), 4)
        if key in size_cache:
            return size_cache[key]
        resized = resize_by_percent(image, key, algorithm, unsharp=unsharp)
        candidate_dpi = dpi_for_percent(key) if dpi_for_percent is not None else dpi
        size = encoded_image_size(
            resized,
            out_format,
            jpeg_quality=jpeg_quality,
            png_preset=png_preset,
            metadata=metadata,
            dpi=candidate_dpi,
            alpha_bg=alpha_bg,
            embedded_icc=embedded_icc,
            metadata_source=metadata_source,
        )
        size_cache[key] = size
        return size

    def evaluate_many(points: list[float]) -> list[tuple[float, int]]:
        unique_points = sorted({round(max(min_percent, min(max_percent, float(point))), 4) for point in points})
        if not unique_points:
            return []
        workers = max(1, min(int(probe_workers or 1), len(unique_points)))
        if workers <= 1:
            return [(point, candidate_size(point)) for point in unique_points]
        results: list[tuple[float, int]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(candidate_size, point): point for point in unique_points}
            for future in as_completed(futures):
                point = futures[future]
                results.append((point, future.result()))
        return sorted(results, key=lambda item: item[0])

    original_size = encoded_image_size(
        image,
        out_format,
        jpeg_quality=jpeg_quality,
        png_preset=png_preset,
        metadata=metadata,
        dpi=(dpi_for_percent(100.0) if dpi_for_percent is not None else dpi),
        alpha_bg=alpha_bg,
        embedded_icc=embedded_icc,
        metadata_source=metadata_source,
    )
    if original_size <= target_bytes:
        return image.copy(), 100.0, original_size

    initial = dict(evaluate_many([50.0, 25.0]))
    size_50 = initial.get(50.0)
    size_25 = initial.get(25.0)

    if size_50 is not None and size_50 <= target_bytes:
        low = 50.0
        high = max_percent
        best_percent = low
        best_size = size_50
    elif size_25 is not None and size_25 <= target_bytes:
        low = 25.0
        high = 50.0
        best_percent = low
        best_size = size_25
    else:
        low = min_percent
        high = 25.0
        best_percent = low
        best_size = candidate_size(low)
        if best_size > target_bytes:
            best_image = resize_by_percent(image, best_percent, algorithm, unsharp=unsharp)
            return best_image, round(best_percent, 3), best_size

    width = high - low
    workers = max(1, int(probe_workers or 1))
    round_count = max(1, int(iterations))
    for _ in range(round_count):
        if width <= 0.05:
            break
        probes = max(1, min(workers, 8))
        step = width / (probes + 1)
        points = [low + step * index for index in range(1, probes + 1)]
        evaluated = evaluate_many(points)
        ok_points = [(point, size) for point, size in evaluated if size <= target_bytes]
        if ok_points:
            point, size = max(ok_points, key=lambda item: item[0])
            best_percent = point
            best_size = size
            low = point
            too_large = [candidate for candidate in evaluated if candidate[0] > low and candidate[1] > target_bytes]
            high = min((candidate[0] for candidate in too_large), default=high)
        else:
            high = min((point for point, _size in evaluated), default=high)
        width = high - low

    best_image = resize_by_percent(image, best_percent, algorithm, unsharp=unsharp)
    return best_image, round(best_percent, 3), best_size




def dpi_for_print_side(image: Image.Image, side: str, target_mm: int) -> float:
    side = (side or 'short').lower()
    if target_mm <= 0:
        raise ValueError('target_mm must be > 0')
    target_inches = target_mm / 25.4
    if side == 'short':
        basis_px = min(image.width, image.height)
    elif side == 'long':
        basis_px = max(image.width, image.height)
    else:
        raise ValueError(f'Unsupported side mode: {side}')
    return basis_px / target_inches
def fit_to_print_side(image: Image.Image, side: str, target_mm: int, dpi: int, algorithm: str = 'lanczos') -> Image.Image:
    side = (side or 'short').lower()
    method = RESAMPLE if (algorithm or 'lanczos').lower() == 'lanczos' else NEAREST
    target_px = max(1, round((target_mm / 25.4) * dpi))
    if side == 'short':
        basis = min(image.width, image.height)
    elif side == 'long':
        basis = max(image.width, image.height)
    else:
        raise ValueError(f'Unsupported side mode: {side}')
    ratio = target_px / basis
    new_size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(new_size, method)


def split_image_strips(image: Image.Image, orientation: str = 'vertical', parts: int = 2) -> list[Image.Image]:
    orientation = (orientation or 'vertical').lower()
    if not 2 <= parts <= 10:
        raise ValueError('parts must be between 2 and 10')
    if orientation == 'vertical':
        bounds = [round(index * image.width / parts) for index in range(parts + 1)]
        return [image.crop((bounds[index], 0, bounds[index + 1], image.height)) for index in range(parts)]
    if orientation == 'horizontal':
        bounds = [round(index * image.height / parts) for index in range(parts + 1)]
        return [image.crop((0, bounds[index], image.width, bounds[index + 1])) for index in range(parts)]
    raise ValueError(f'Unsupported orientation: {orientation}')


def split_image_grid(image: Image.Image, rows: int = 2, columns: int = 2) -> list[tuple[int, int, Image.Image]]:
    if not 2 <= rows <= 10:
        raise ValueError('rows must be between 2 and 10')
    if not 2 <= columns <= 10:
        raise ValueError('columns must be between 2 and 10')
    x_bounds = [round(index * image.width / columns) for index in range(columns + 1)]
    y_bounds = [round(index * image.height / rows) for index in range(rows + 1)]
    parts: list[tuple[int, int, Image.Image]] = []
    for row in range(rows):
        for column in range(columns):
            crop = image.crop((x_bounds[column], y_bounds[row], x_bounds[column + 1], y_bounds[row + 1]))
            parts.append((row + 1, column + 1, crop))
    return parts


def split_image_half(image: Image.Image, orientation: str = 'vertical') -> tuple[Image.Image, Image.Image]:
    first, second = split_image_strips(image, orientation, 2)
    return first, second
