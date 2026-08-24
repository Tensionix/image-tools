from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from image_tools.commands import (
    cmd_aspect,
    cmd_contact_sheet,
    cmd_convert,
    cmd_downscale_percent,
    cmd_pdf_export,
    cmd_images_to_pdf,
    cmd_grayscale,
    cmd_pdf_extract_embedded,
    cmd_pdf_rasterize,
    cmd_photo_sheet_width,
    cmd_normalize,
    cmd_plotter_dpi_only,
    cmd_plotter_size,
    cmd_resize_screen,
    cmd_smart_crop_white,
    cmd_split_half,
    cmd_split_tiff,
    cmd_tile_sheet,
    cmd_trim_border,
    cmd_watermark,
    emit_formats,
)
from image_tools.constants import (
    OUTPUT_FORMAT_CHOICES,
    PDF_EXTRACT_OUTPUT_FORMAT_CHOICES,
    PIXEL_DPI_OUTPUT_FORMAT_CHOICES,
    PDF_EXPORT_MODES,
    PDF_RASTER_DPI_CHOICES,
    RESAMPLE_ALGORITHM_CHOICES,
)
from image_tools.io_utils import configure_image_pixel_guard


def detect_python_mode(root: Path) -> str:
    if (root / 'runtime' / 'python.exe').exists():
        return 'portable-runtime'
    if (root / 'runtime' / 'python' / 'python.exe').exists():
        return 'portable-runtime'
    return 'system-python'


def load_defaults() -> dict:
    root = Path(__file__).resolve().parents[1]
    defaults_path = root / 'config' / 'defaults.json'
    if not defaults_path.exists():
        return {}
    try:
        return json.loads(defaults_path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def parse_int_value(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        try:
            numeric = float(str(value).replace(',', '.'))
        except (TypeError, ValueError):
            raise argparse.ArgumentTypeError('must be an integer')
        if not numeric.is_integer():
            raise argparse.ArgumentTypeError('must be an integer')
        parsed = int(numeric)
    return parsed


def parse_positive_int(value):
    parsed = parse_int_value(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return parsed


def parse_positive_float(value):
    try:
        parsed = float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError('must be a positive number')
    if parsed <= 0:
        raise argparse.ArgumentTypeError('must be a positive number')
    return parsed


def parse_scale_percent(value):
    parsed = parse_positive_float(value)
    if parsed > 100:
        raise argparse.ArgumentTypeError('must be between 0.1 and 100')
    return parsed


def parse_pdf_dpi(value):
    parsed = parse_positive_int(value)
    if parsed > 1200:
        raise argparse.ArgumentTypeError('must be between 1 and 1200')
    return parsed


def parse_split_count(value):
    parsed = parse_positive_int(value)
    if parsed < 2 or parsed > 10:
        raise argparse.ArgumentTypeError('must be between 2 and 10')
    return parsed


def parse_jpeg_quality(value):
    parsed = parse_positive_int(value)
    if parsed > 100:
        raise argparse.ArgumentTypeError('must be between 1 and 100')
    return parsed


def add_safety_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--workers', type=parse_int_value, default=1, help='Parallel image workers. 1 = sequential, 0 = auto up to 8 workers.')
    parser.add_argument(
        '--allow-huge-images',
        action='store_true',
        help='Disable the Pillow decompression-bomb guard for intentionally huge scans/plots',
    )


def add_common_io(
    parser: argparse.ArgumentParser,
    default_to: str = 'png',
    include_set_dpi: bool = True,
    output_choices: tuple[str, ...] = OUTPUT_FORMAT_CHOICES,
) -> None:
    parser.add_argument('--input', required=True, help='Input file or folder')
    parser.add_argument('--output', required=True, help='Output file or folder')
    parser.add_argument('--to', default=default_to, choices=list(output_choices))
    parser.add_argument('--jpeg-quality', type=parse_jpeg_quality, default=83)
    parser.add_argument('--png-preset', default='balanced', choices=['fast', 'balanced', 'small'])
    parser.add_argument('--metadata', default='preserve_dpi_color', choices=['preserve_all', 'preserve_dpi_color', 'strip_all'])
    parser.add_argument('--alpha-bg', default='white', help='white, black, or #RRGGBB')
    if include_set_dpi:
        parser.add_argument('--set-dpi', type=parse_positive_int, default=None, help='Set output DPI without resampling')
    parser.add_argument('--log-dir', default='logs', help='Log folder for JSON run reports')
    add_safety_options(parser)


def build_parser() -> argparse.ArgumentParser:
    defaults = load_defaults()
    icc_defaults = defaults.get('icc', {})
    pdf_defaults = defaults.get('pdf', {})
    embed_defaults = icc_defaults.get('embed_profiles_on_save', {})
    pdf_embed_defaults = icc_defaults.get('embed_profiles_in_pdf', {})

    parser = argparse.ArgumentParser(prog='Audion Image Tools')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('info', help='Print project information')

    formats = sub.add_parser('formats', help='Show supported formats and adapter status')
    formats.set_defaults(func=lambda args: emit_formats())

    convert = sub.add_parser('convert', help='Convert images to JPG, PNG, TIFF, WebP, AVIF or HEIF/HEIC')
    add_common_io(convert)
    convert.set_defaults(func=cmd_convert)

    normalize = sub.add_parser('normalize', help='Normalize EXIF/color/alpha and optionally update DPI')
    add_common_io(normalize)
    normalize.add_argument('--target-profile', default='srgb', choices=['keep', 'srgb', 'cmyk'])
    normalize.add_argument('--srgb-profile-mode', default='colororg', choices=['pillow', 'colororg'])
    normalize.add_argument('--srgb-profile', default=icc_defaults.get('srgb_profile', 'config/icc/sRGB2014.icc'))
    normalize.add_argument('--cmyk-profile', default=icc_defaults.get('cmyk_profile', 'config/icc/Photoshop5DefaultCMYK.icc'))
    normalize.add_argument('--embed-srgb-profile', type=parse_bool, default=embed_defaults.get('srgb', True))
    normalize.add_argument('--embed-cmyk-profile', type=parse_bool, default=embed_defaults.get('cmyk', False))
    normalize.add_argument('--embed-pdf-image-profile', type=parse_bool, default=pdf_embed_defaults.get('normalized_images', True))
    normalize.add_argument('--pdf-dpi', type=parse_positive_int, default=pdf_defaults.get('raster_dpi_default', 300), choices=list(PDF_RASTER_DPI_CHOICES))
    normalize.set_defaults(func=cmd_normalize)

    grayscale = sub.add_parser('grayscale', help='Convert images to grayscale')
    add_common_io(grayscale)
    grayscale.set_defaults(func=cmd_grayscale)

    resize_screen = sub.add_parser('resize-screen', help='Resize images to 1080p/1440p/2160p')
    add_common_io(resize_screen)
    resize_screen.add_argument('--target', required=True, choices=['1080p', '1440p', '2160p'])
    resize_screen.add_argument('--mode', default='crop', choices=['crop', 'contain', 'pad', 'by-height', 'by-width'])
    resize_screen.add_argument('--background', default='black')
    resize_screen.set_defaults(func=cmd_resize_screen)

    aspect = sub.add_parser('aspect', help='Fit images to 16:9 or A4/A3 ratio')
    add_common_io(aspect)
    aspect.add_argument('--ratio', required=True, choices=['16:9', 'a4-portrait', 'a4-landscape', 'a3-portrait', 'a3-landscape'])
    aspect.add_argument('--mode', default='crop', choices=['crop', 'contain', 'pad', 'by-height', 'by-width'])
    aspect.add_argument('--background', default='black')
    aspect.add_argument('--long-edge', type=parse_positive_int, default=3840)
    aspect.add_argument('--size', default=None, help='Explicit size as WIDTHxHEIGHT')
    aspect.set_defaults(func=cmd_aspect)

    trim = sub.add_parser('trim-border', help='Trim solid border using corner color')
    add_common_io(trim)
    trim.add_argument('--tolerance', type=parse_int_value, default=10)
    trim.add_argument('--safety-margin-mm', type=float, default=0.0, help='Expand detected crop by millimeters using image DPI, fallback 300 DPI')
    trim.set_defaults(func=cmd_trim_border)

    smart_crop = sub.add_parser('smart-crop-white', help='Trim white background to first meaningful pixels')
    add_common_io(smart_crop, default_to='png')
    smart_crop.add_argument('--tolerance', type=parse_int_value, default=10)
    smart_crop.add_argument('--safety-margin-mm', type=float, default=0.0, help='Expand detected crop by millimeters using image DPI, fallback 300 DPI')
    smart_crop.set_defaults(func=cmd_smart_crop_white)

    watermark = sub.add_parser('watermark', help='Add text watermark overlay')
    add_common_io(watermark)
    watermark.add_argument('--text', required=True)
    watermark.add_argument('--position', default='bottom-right', choices=['bottom-right', 'bottom-left', 'top-right', 'top-left'])
    watermark.add_argument('--margin', type=parse_int_value, default=32)
    watermark.add_argument('--opacity', type=parse_int_value, default=64)
    watermark.add_argument('--font-size', type=parse_int_value, default=36)
    watermark.add_argument('--color', default='#ffffff')
    watermark.add_argument('--watermark-mode', default='corner', choices=['corner', 'diagonal'])
    watermark.add_argument('--diagonal-coverage', type=float, default=60.0)
    watermark.set_defaults(func=cmd_watermark)

    sheet = sub.add_parser('contact-sheet', help='Create a contact sheet from a folder')
    sheet.add_argument('--input', required=True)
    sheet.add_argument('--output', required=True)
    sheet.add_argument('--to', default=None, choices=list(OUTPUT_FORMAT_CHOICES), help='Output format. Defaults to the --output extension, or PNG if none.')
    sheet.add_argument('--columns', type=parse_positive_int, default=4)
    sheet.add_argument('--thumb-size', default='640x480')
    sheet.add_argument('--label-mode', default='inspection', choices=['none', 'filename', 'filename-size', 'inspection'])
    sheet.add_argument('--label-height', type=parse_positive_int, default=64)
    sheet.add_argument('--label-font-size', type=parse_positive_int, default=14)
    sheet.add_argument('--border-size', type=parse_int_value, default=1)
    sheet.add_argument('--border-color', default='#cccccc')
    sheet.add_argument('--text-color', default='#222222')
    sheet.add_argument('--jpeg-quality', type=parse_jpeg_quality, default=92)
    sheet.add_argument('--background', default='white')
    sheet.add_argument('--spacing', type=parse_int_value, default=20)
    sheet.add_argument('--log-dir', default='logs')
    add_safety_options(sheet)
    sheet.set_defaults(func=cmd_contact_sheet)

    photo_sheet = sub.add_parser('photo-sheet-width', help='Pack input photos into a no-gap line sheet by width in mm')
    photo_sheet.add_argument('--config', default='config/photo_sheet.yaml', help='YAML config file')
    photo_sheet.add_argument('--config-mode', default=None, help='Use a mode from YAML config')
    photo_sheet.add_argument('--input', default='input', help='Input folder with prepared photos')
    photo_sheet.add_argument('--output', default='output/photo_sheet_width', help='Output folder')
    photo_sheet.add_argument('--to', default='png', choices=list(OUTPUT_FORMAT_CHOICES), help='Main sheet output format')
    photo_sheet.add_argument('--jpeg-quality', type=parse_jpeg_quality, default=90)
    photo_sheet.add_argument('--page-width-mm', type=float, default=None)
    photo_sheet.add_argument('--dpi', type=parse_positive_int, default=None)
    photo_sheet.add_argument('--gap-mm', type=float, default=0.0)
    photo_sheet.add_argument('--size-source', default='pixels', choices=['pixels', 'dpi', 'filename'])
    photo_sheet.add_argument('--layout', default='shelf', choices=['shelf', 'cut-lines', 'maxrects'])
    photo_sheet.add_argument('--height-tolerance-mm', type=float, default=0.2)
    photo_sheet.add_argument('--recursive', action='store_true')
    photo_sheet.add_argument('--background', default='white')
    photo_sheet.add_argument('--preview-width-px', type=parse_positive_int, default=1800)
    photo_sheet.add_argument('--log-dir', default='logs')
    add_safety_options(photo_sheet)
    photo_sheet.set_defaults(func=cmd_photo_sheet_width)

    tile_sheet = sub.add_parser('tile-sheet', help='Tile one image across A5/A4/A3 sheets or a custom-width roll')
    tile_sheet.add_argument('--input', required=True)
    tile_sheet.add_argument('--output', required=True)
    tile_sheet.add_argument('--paper', default='a4', choices=['a5', 'a4', 'a3', 'roll'])
    tile_sheet.add_argument('--orientation', default='portrait', choices=['portrait', 'landscape'])
    tile_sheet.add_argument('--margin-mm', type=float, default=7.0)
    tile_sheet.add_argument('--gap-mm', type=float, default=0.0)
    tile_sheet.add_argument('--dpi', type=parse_positive_int, default=300)
    tile_sheet.add_argument('--to', default='tiff', choices=['png', 'tiff'])
    tile_sheet.add_argument('--size-mode', default='source', choices=['source', 'width', 'height', 'doc-40x30', 'doc-60x40'])
    tile_sheet.add_argument('--item-width-mm', type=float, default=None)
    tile_sheet.add_argument('--item-height-mm', type=float, default=None)
    tile_sheet.add_argument('--box-fit', default='contain', choices=['contain', 'crop'])
    tile_sheet.add_argument('--frame-mm', type=float, default=0.2)
    tile_sheet.add_argument('--frame-color', default='#999999')
    tile_sheet.add_argument('--background', default='white')
    tile_sheet.add_argument('--preview-width-px', type=parse_positive_int, default=1800)
    tile_sheet.add_argument('--roll-width-mm', type=float, default=None)
    tile_sheet.add_argument('--count-mode', default='fill', choices=['fill', 'copies', 'rows'])
    tile_sheet.add_argument('--copies', type=parse_int_value, default=0)
    tile_sheet.add_argument('--rows', type=parse_int_value, default=1)
    tile_sheet.add_argument('--log-dir', default='logs')
    add_safety_options(tile_sheet)
    tile_sheet.set_defaults(func=cmd_tile_sheet)

    split_tiff = sub.add_parser('split-tiff', help='Split multi-page TIFF to numbered PNG frames')
    split_tiff.add_argument('--input', required=True)
    split_tiff.add_argument('--output', required=True)
    split_tiff.add_argument('--log-dir', default='logs')
    add_safety_options(split_tiff)
    split_tiff.set_defaults(func=cmd_split_tiff)

    plotter = sub.add_parser('plotter-size', help='Fit print size for plotter roll by writing DPI metadata')
    add_common_io(plotter, default_to='png', include_set_dpi=False, output_choices=PIXEL_DPI_OUTPUT_FORMAT_CHOICES)
    plotter.add_argument('--side', required=True, choices=['short', 'long'])
    plotter.add_argument('--target-mm', type=parse_positive_int, required=True)
    plotter.set_defaults(func=cmd_plotter_size)

    plotter_dpi = sub.add_parser('plotter-dpi-only', help='Set DPI metadata without resampling')
    add_common_io(plotter_dpi, default_to='png', include_set_dpi=False, output_choices=PIXEL_DPI_OUTPUT_FORMAT_CHOICES)
    plotter_dpi.add_argument('--dpi', type=parse_positive_int, required=True)
    plotter_dpi.set_defaults(func=cmd_plotter_dpi_only)

    split_half = sub.add_parser('split-half', help='Split images into strips or grid cells')
    split_half.add_argument('--input', required=True)
    split_half.add_argument('--output', required=True)
    split_half.add_argument('--to', default='png', choices=list(OUTPUT_FORMAT_CHOICES))
    split_half.add_argument('--jpeg-quality', type=parse_jpeg_quality, default=75)
    split_half.add_argument('--mode', default='strips', choices=['strips', 'grid'])
    split_half.add_argument('--orientation', default='vertical', choices=['vertical', 'horizontal'])
    split_half.add_argument('--parts', type=parse_split_count, default=2)
    split_half.add_argument('--rows', type=parse_split_count, default=2)
    split_half.add_argument('--columns', type=parse_split_count, default=2)
    split_half.add_argument('--metadata', default='preserve_dpi_color', choices=['preserve_all', 'preserve_dpi_color', 'strip_all'])
    split_half.add_argument('--log-dir', default='logs')
    add_safety_options(split_half)
    split_half.set_defaults(func=cmd_split_half)



    pdf_rasterize = sub.add_parser('pdf-rasterize', help='Rasterize PDF pages to JPG or PNG at 150/300/600 DPI')
    pdf_rasterize.add_argument('--input', required=True)
    pdf_rasterize.add_argument('--output', required=True)
    pdf_rasterize.add_argument('--to', default='png', choices=list(OUTPUT_FORMAT_CHOICES))
    pdf_rasterize.add_argument('--dpi', type=parse_positive_int, required=True, choices=list(PDF_RASTER_DPI_CHOICES))
    pdf_rasterize.add_argument('--jpeg-quality', type=parse_jpeg_quality, default=90)
    pdf_rasterize.add_argument('--png-preset', default='balanced', choices=['fast', 'balanced', 'small'])
    pdf_rasterize.add_argument('--metadata', default='preserve_dpi_color', choices=['preserve_all', 'preserve_dpi_color', 'strip_all'])
    pdf_rasterize.add_argument('--log-dir', default='logs')
    add_safety_options(pdf_rasterize)
    pdf_rasterize.set_defaults(func=cmd_pdf_rasterize)

    pdf_export = sub.add_parser('pdf-export', help='Export PDF pages to JPG or PNG using embedded or render mode')
    pdf_export.add_argument('--input', required=True)
    pdf_export.add_argument('--output', required=True)
    pdf_export.add_argument('--to', default='png', choices=list(OUTPUT_FORMAT_CHOICES))
    pdf_export.add_argument('--mode', default='embedded', choices=['embedded', 'render'])
    pdf_export.add_argument('--dpi', type=parse_pdf_dpi, default=pdf_defaults.get('raster_dpi_default', 300), help='Render DPI for PDF page rasterization (1-1200)')
    pdf_export.add_argument('--jpeg-quality', type=parse_jpeg_quality, default=90)
    pdf_export.add_argument('--png-preset', default='balanced', choices=['fast', 'balanced', 'small'])
    pdf_export.add_argument('--metadata', default='preserve_dpi_color', choices=['preserve_all', 'preserve_dpi_color', 'strip_all'])
    pdf_export.add_argument('--log-dir', default='logs')
    add_safety_options(pdf_export)
    pdf_export.set_defaults(func=cmd_pdf_export)

    pdf_extract = sub.add_parser('pdf-extract-embedded', help='Extract embedded images from PDF without page rasterization')
    pdf_extract.add_argument('--input', required=True)
    pdf_extract.add_argument('--output', required=True)
    pdf_extract.add_argument('--to', default='original', choices=list(PDF_EXTRACT_OUTPUT_FORMAT_CHOICES), help='Keep original embedded format or convert extracted images')
    pdf_extract.add_argument('--layout', default='folders', choices=['flat', 'folders'], help='Write all outputs into one folder or into PDF-name folders')
    pdf_extract.add_argument('--jpeg-quality', type=parse_jpeg_quality, default=90)
    pdf_extract.add_argument('--png-preset', default='balanced', choices=['fast', 'balanced', 'small'])
    pdf_extract.add_argument('--metadata', default='preserve_dpi_color', choices=['preserve_all', 'preserve_dpi_color', 'strip_all'])
    pdf_extract.add_argument('--png-side-tiff', type=parse_bool, default=False, help='When converting to PNG, also write a TIFF sidecar for CMYK or ICC-tagged embedded images')
    pdf_extract.add_argument('--log-dir', default='logs')
    add_safety_options(pdf_extract)
    pdf_extract.set_defaults(func=cmd_pdf_extract_embedded)

    images_to_pdf = sub.add_parser('images-to-pdf', help='Build PDF from images using lossless-preferred or JPG-high modes')
    images_to_pdf.add_argument('--input', required=True)
    images_to_pdf.add_argument('--output', required=True)
    images_to_pdf.add_argument('--mode', default='lossless', choices=list(PDF_EXPORT_MODES))
    images_to_pdf.add_argument('--bundle', default='all', choices=['all', 'folders'])
    images_to_pdf.add_argument('--dpi', type=parse_pdf_dpi, default=None, help='Override image DPI for PDF page size (1-1200)')
    images_to_pdf.add_argument('--preserve-icc', type=parse_bool, default=pdf_embed_defaults.get('preserve_input_images', True))
    images_to_pdf.add_argument('--log-dir', default='logs')
    add_safety_options(images_to_pdf)
    images_to_pdf.set_defaults(func=cmd_images_to_pdf)

    downscale = sub.add_parser('downscale-percent', help='Downscale image by percent or fit output file size')
    add_common_io(downscale, default_to='png')
    downscale.add_argument('--scale-mode', default='percent-50', choices=['percent-25', 'percent-50', 'custom', 'target-mb'])
    downscale.add_argument('--percent', type=parse_scale_percent, default=None, help='Legacy/direct percent override, 0.1-100')
    downscale.add_argument('--custom-percent', type=parse_scale_percent, default=50.0)
    downscale.add_argument('--target-mb', type=parse_positive_float, default=1.0)
    downscale.add_argument('--target-floor-ratio', type=float, default=0.8, help='Warn when fit result is below this share of target bytes')
    downscale.add_argument('--algorithm', default='lanczos', choices=list(RESAMPLE_ALGORITHM_CHOICES))
    downscale.add_argument('--unsharp', type=parse_bool, default=True, help='Apply a mild Unsharp Mask after Lanczos downscaling')
    downscale.add_argument('--print-size-mode', default='scale', choices=['scale', 'dpi'], help='scale keeps source DPI metadata; dpi writes proportional DPI to preserve physical print size')
    downscale.set_defaults(func=cmd_downscale_percent)

    return parser


def print_info() -> int:
    root = Path(__file__).resolve().parents[1]
    payload = {
        'project_name': 'Audion Image Tools',
        'project_root': str(root),
        'python_executable': sys.executable,
        'python_version': sys.version.split()[0],
        'python_mode': detect_python_mode(root),
        'folders': {
            'input': str(root / 'input'),
            'output': str(root / 'output'),
            'logs': str(root / 'logs'),
            'report': str(root / 'report'),
            'workspace': str(root / 'workspace'),
            'config': str(root / 'config'),
            'data': str(root / 'data'),
            'runtime': str(root / 'runtime'),
            'wheelhouse': str(root / 'wheelhouse'),
            'release': str(root / 'release'),
        },
        'focus': 'Broad input conversion plus deep JPG/PNG processing',
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_image_pixel_guard(bool(getattr(args, 'allow_huge_images', False)))
    if args.command == 'info':
        return print_info()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
