"""Colour correction and a palette of a few colours - Pillow alone, no model, no OpenCV.

    adjust   --levels none | channels | tone  --cutoff PERCENT
             --brightness -100..100  --contrast -100..100  --saturation -100..100  --gamma 0.2..5
             --tone keep | gray | sepia | R,G,B (a tint)  --invert  --white-transparent --tolerance 0..100
    palette  --colors 2..256 --dither on | off --method mediancut | maxcoverage | octree

adjust, in this order: the levels stretched (per channel - a cast of colour goes; or keeping the tone),
brightness, contrast, gamma, saturation, the tone (grey, sepia, a tint of one's own), the inversion,
and white made transparent - the near-white within the tolerance, with a soft edge of 16 steps. The
transparency of a picture is kept and not touched by any of it. A picture keeps its format unless
another is asked; one whose white became transparent and that was a JPEG is written as a PNG.

palette writes a PNG of at most --colors colours: drawings, plans, maps, screenshots - many times
lighter without a visible change. A transparent picture keeps its transparency (octree).
"""
from __future__ import annotations

import argparse

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from .transform import _batch, parse_fill

SEPIA = ((40, 26, 13), (255, 240, 205))


def _split_alpha(image: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    """The colour of a picture and its transparency apart: what is done to the colour leaves the transparency as it was."""
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        return rgba.convert("RGB"), rgba.getchannel("A")
    if image.mode in ("RGB", "L"):
        return image, None
    return image.convert("RGB"), None


def tone_of(text: str) -> tuple[str, tuple[int, int, int] | None]:
    text = (text or "keep").strip().lower()
    if text in ("keep", "gray", "grey", "sepia"):
        return ("gray" if text == "grey" else text), None
    colour = parse_fill(text)
    if colour is None:
        raise argparse.ArgumentTypeError("a tint cannot be transparent")
    return "tint", tuple(colour[:3])


def correct(image: Image.Image, args) -> Image.Image:
    colour, alpha = _split_alpha(image)
    if args.levels == "channels":
        colour = ImageOps.autocontrast(colour, cutoff=float(args.cutoff))
    elif args.levels == "tone":
        colour = ImageOps.autocontrast(colour, cutoff=float(args.cutoff), preserve_tone=True)
    if args.brightness:
        colour = ImageEnhance.Brightness(colour).enhance(1 + float(args.brightness) / 100)
    if args.contrast:
        colour = ImageEnhance.Contrast(colour).enhance(1 + float(args.contrast) / 100)
    if abs(float(args.gamma) - 1) > 1e-6:
        exponent = 1 / float(args.gamma)
        table = [round(255 * (value / 255) ** exponent) for value in range(256)]
        colour = colour.point(table * len(colour.getbands()))
    if args.saturation and colour.mode == "RGB":
        colour = ImageEnhance.Color(colour).enhance(1 + float(args.saturation) / 100)
    tone, tint = tone_of(args.tone)
    if tone == "gray":
        colour = ImageOps.grayscale(colour)
    elif tone == "sepia":
        colour = ImageOps.colorize(ImageOps.grayscale(colour), black=SEPIA[0], white=SEPIA[1])
    elif tone == "tint":
        colour = ImageOps.colorize(ImageOps.grayscale(colour), black=(0, 0, 0), white=(255, 255, 255), mid=tint)
    if args.invert:
        colour = ImageOps.invert(colour)
    if args.white_transparent:
        # Near-white within the tolerance goes transparent; 16 steps beyond it fade back - no ragged edge.
        limit = float(args.tolerance) * 2.55
        distance = (255 - np.asarray(colour.convert("RGB"), dtype=np.int16)).max(axis=2)
        fade = np.clip((distance - limit) * 255 / 16, 0, 255).astype(np.uint8)
        alpha = Image.fromarray(fade if alpha is None else np.minimum(np.asarray(alpha), fade))
    if alpha is not None:
        colour = colour.convert("RGB") if colour.mode not in ("RGB", "L") else colour
        colour = colour.convert("RGBA") if colour.mode == "RGB" else colour.convert("LA")
        colour.putalpha(alpha)
    colour.info = dict(image.info)
    return colour


def cmd_adjust(args) -> int:
    tone_of(args.tone)
    if args.white_transparent and args.to == "jpg":
        print("White made transparent cannot be written as a JPEG: choose PNG, WebP or TIFF, or the format of the source")
        return 2
    if args.white_transparent and args.to == "keep":
        return _batch_keep_transparent(args)
    return _batch(args, "adjust", lambda image, _src: correct(image, args))


def _batch_keep_transparent(args) -> int:
    """The format of the source, but a JPEG (HEIC, AVIF) keeps no transparency: its white made transparent goes into a PNG."""
    from . import transform

    saved = dict(transform.KEEP)
    try:
        for suffix in (".jpg", ".jpeg", ".heic", ".heif", ".avif"):
            transform.KEEP[suffix] = "png"
        return _batch(args, "adjust", lambda image, _src: correct(image, args))
    finally:
        transform.KEEP.clear()
        transform.KEEP.update(saved)


METHODS = {"mediancut": Image.Quantize.MEDIANCUT, "maxcoverage": Image.Quantize.MAXCOVERAGE, "octree": Image.Quantize.FASTOCTREE}


def to_palette(image: Image.Image, colors: int, dither: bool, method: str) -> Image.Image:
    dithering = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    colour, alpha = _split_alpha(image)
    if alpha is not None and alpha.getextrema()[0] < 255:
        # Transparency: only the octree of Pillow quantizes a picture with its alpha.
        out = image.convert("RGBA").quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=dithering)
    else:
        out = colour.convert("RGB").quantize(colors=colors, method=METHODS[method], dither=dithering)
    out.info = {key: value for key, value in image.info.items() if key in ("dpi", "icc_profile")}
    return out


def cmd_palette(args) -> int:
    colors = max(2, min(256, int(args.colors)))
    args.to = "png"
    return _batch(args, f"palette {colors}", lambda image, _src: to_palette(image, colors, args.dither == "on", args.method))


def add_parsers(sub, add_common_io) -> None:
    choices = ("keep", "jpg", "png", "tiff", "webp", "avif", "heif", "heic")

    def percent(value: str) -> float:
        number = float(str(value).replace(",", "."))
        if not -100 <= number <= 100:
            raise ValueError("from -100 to 100")
        return number

    adjust = sub.add_parser("adjust", help="Correct the colour: levels, brightness, contrast, gamma, saturation, a tone, inversion, white to transparent")
    add_common_io(adjust, default_to="keep", output_choices=choices)
    adjust.set_defaults(jpeg_quality=95)
    adjust.add_argument("--levels", choices=["none", "channels", "tone"], default="none",
                        help="channels - every channel stretched apart, a cast of colour goes; tone - stretched together, the tone kept")
    adjust.add_argument("--cutoff", type=float, default=0.5, help="Percent of the darkest and the lightest pixels left out of the stretch")
    adjust.add_argument("--brightness", type=percent, default=0)
    adjust.add_argument("--contrast", type=percent, default=0)
    adjust.add_argument("--saturation", type=percent, default=0, help="-100 - grey; 100 - twice as bright colours")
    adjust.add_argument("--gamma", type=float, default=1.0, help="Over 1 - the middle tones lighter; under 1 - darker")
    adjust.add_argument("--tone", default="keep", help="keep, gray, sepia, or R,G,B - a tint of that colour")
    adjust.add_argument("--invert", action="store_true")
    adjust.add_argument("--white-transparent", action="store_true", help="The near-white goes transparent")
    adjust.add_argument("--tolerance", type=float, default=8, help="0-100: how far from white still counts as white")
    adjust.set_defaults(func=cmd_adjust)

    palette = sub.add_parser("palette", help="A PNG of at most N colours: drawings, plans, maps many times lighter")
    add_common_io(palette, default_to="png", output_choices=("png",))
    palette.add_argument("--colors", type=int, default=256)
    palette.add_argument("--dither", choices=["on", "off"], default="off", help="on - photographs; off - drawings and plans, clean edges")
    palette.add_argument("--method", choices=list(METHODS), default="mediancut")
    palette.set_defaults(func=cmd_palette)
