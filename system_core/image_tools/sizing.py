"""The size of a picture in pixels: by a percent, up as well as down, and to an exact width and height.

    scale       --percent P (0.1-1000) --algorithm lanczos | bicubic | box | nearest
    exact-size  --width W --height H --mode fit | pad | crop | stretch --background white | black | transparent | R,G,B

A picture keeps its format unless another is asked ("--to keep"), and keeps the density it states: a
picture made larger by 141.4 % prints larger by as much - an A4 becomes an A3. Every picture is first
turned the way it is seen (commands._process_batch_file). A result over HUGE megapixels is refused
unless --allow-huge-images: three times a large scan does not fit the memory of an ordinary machine.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from .pipeline import resample_method
from .transform import _batch, _with_fill, parse_fill

HUGE = 250_000_000


def _guarded(args, width: int, height: int) -> None:
    if width * height > HUGE and not getattr(args, "allow_huge_images", False):
        raise ValueError(f"the result would be {width} x {height} px, over {HUGE // 1_000_000} megapixels; "
                         "make it smaller or allow huge images")


def cmd_scale(args) -> int:
    percent = float(args.percent)
    method = resample_method(args.algorithm)

    def scale(image: Image.Image, _src: Path) -> Image.Image:
        size = (max(1, round(image.width * percent / 100.0)), max(1, round(image.height * percent / 100.0)))
        _guarded(args, *size)
        out = image.resize(size, method)
        # The mild sharpening of a Lanczos downscale (pipeline.resize_by_percent); a picture made larger is left as drawn.
        if percent < 100 and args.algorithm == "lanczos":
            out = out.filter(ImageFilter.UnsharpMask(radius=0.8, percent=80, threshold=2))
        out.info = dict(image.info)
        return out

    return _batch(args, f"scale {percent:g}%", scale)


def cmd_exact_size(args) -> int:
    size = (int(args.width), int(args.height))
    if min(size) < 1:
        print(f"A width and a height of at least 1 px: {size[0]} x {size[1]}")
        return 2
    method = resample_method(args.algorithm)
    fill = parse_fill(args.background)

    def exact(image: Image.Image, _src: Path) -> Image.Image:
        _guarded(args, *size)
        if args.mode == "fit":
            out = ImageOps.contain(image, size, method=method)
        elif args.mode == "crop":
            out = ImageOps.fit(image, size, method=method, centering=(0.5, 0.5))
        elif args.mode == "stretch":
            out = image.resize(size, method)
        else:
            fitted = ImageOps.contain(image, size, method=method)
            fitted.info = dict(image.info)
            canvas, colour = _with_fill(fitted, fill)
            out = Image.new(canvas.mode, size, colour)
            out.paste(canvas, ((size[0] - canvas.width) // 2, (size[1] - canvas.height) // 2))
        out.info = dict(image.info)
        return out

    return _batch(args, f"exact-size {size[0]}x{size[1]} {args.mode}", exact)


def add_parsers(sub, add_common_io) -> None:
    choices = ("keep", "jpg", "png", "tiff", "webp", "avif", "heif", "heic")
    algorithms = ["lanczos", "bicubic", "box", "nearest"]

    def io(parser) -> None:
        add_common_io(parser, default_to="keep", output_choices=choices)
        parser.set_defaults(jpeg_quality=92)

    def percent(value: str) -> float:
        number = float(str(value).replace(",", "."))
        if not 0.1 <= number <= 1000:
            raise ValueError("a percent from 0.1 to 1000")
        return number

    scale = sub.add_parser("scale", help="Make pictures smaller or larger by a percent; the density stays, so the print size follows")
    io(scale)
    scale.add_argument("--percent", type=percent, required=True, help="0.1-1000; 141.42 makes an A4 an A3, 200 doubles")
    scale.add_argument("--algorithm", choices=algorithms, default="lanczos")
    scale.set_defaults(func=cmd_scale)

    exact = sub.add_parser("exact-size", help="Bring pictures to an exact width and height in pixels")
    io(exact)
    exact.add_argument("--width", type=int, required=True)
    exact.add_argument("--height", type=int, required=True)
    exact.add_argument("--mode", choices=["fit", "pad", "crop", "stretch"], default="pad",
                       help="fit - inside the box, proportions kept, the box not filled; pad - the box filled with the "
                            "background; crop - the box covered, the overflow cut; stretch - the proportions given up")
    exact.add_argument("--background", default="white", help="For pad: white, black, transparent, R,G,B or #RRGGBB")
    exact.add_argument("--algorithm", choices=algorithms, default="lanczos")
    exact.set_defaults(func=cmd_exact_size)
