from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageCms

from .models import OptimizationPolicy, Preset, policy_for_preset


def resize_image_to_box(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return copy


def flatten_transparency_to_white(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        base = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        base.paste(rgba, mask=rgba.getchannel("A"))
        return base
    return image.convert("RGB")


def has_visible_transparency(data: bytes) -> bool:
    """A picture with a pixel not fully opaque: laid on white, it would change on any background but white
    (a logo on a coloured slide). A mode with a channel of alpha that is opaque everywhere is not transparent."""
    with Image.open(BytesIO(data)) as image:
        if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
            return image.convert("RGBA").getchannel("A").getextrema()[0] < 255
    return False


def shrink_png_bytes(data: bytes, policy: OptimizationPolicy) -> bytes:
    """A transparent picture brought inside the limit and kept a PNG, its transparency whole."""
    with Image.open(BytesIO(data)) as image:
        working = resize_image_to_box(image.convert("RGBA"), policy.max_width, policy.max_height)
        buffer = BytesIO()
        working.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def save_progressive_jpeg_bytes(image: Image.Image, quality: int = 75) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, progressive=True, optimize=False)
    return buffer.getvalue()


def _extract_embedded_profile(data: bytes) -> ImageCms.ImageCmsProfile | None:
    if not data:
        return None
    try:
        return ImageCms.ImageCmsProfile(BytesIO(data))
    except Exception:
        return None


def _apply_rgb_profile(image: Image.Image, profile_bytes: bytes | None, target_profile_path: str) -> Image.Image:
    source_profile = _extract_embedded_profile(profile_bytes) or ImageCms.createProfile("sRGB")
    target_profile = ImageCms.ImageCmsProfile(target_profile_path)
    return ImageCms.profileToProfile(image, source_profile, target_profile, outputMode="RGB")


def _apply_cmyk_profile(
    image: Image.Image,
    profile_bytes: bytes | None,
    srgb_profile_path: str,
    cmyk_profile_path: str,
) -> Image.Image:
    source_profile = _extract_embedded_profile(profile_bytes) or ImageCms.ImageCmsProfile(srgb_profile_path)
    target_profile = ImageCms.ImageCmsProfile(cmyk_profile_path)
    return ImageCms.profileToProfile(image, source_profile, target_profile, outputMode="CMYK")


def save_jpeg_with_profile_bytes(
    image: Image.Image,
    icc_profile_bytes: bytes | None,
    quality: int = 75,
) -> bytes:
    buffer = BytesIO()
    save_kwargs = {
        "format": "JPEG",
        "quality": quality,
        "progressive": True,
        "optimize": False,
    }
    if icc_profile_bytes:
        save_kwargs["icc_profile"] = icc_profile_bytes
    image.save(buffer, **save_kwargs)
    return buffer.getvalue()


def save_png_with_profile_bytes(image: Image.Image, icc_profile_bytes: bytes) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False, icc_profile=icc_profile_bytes)
    return buffer.getvalue()


def normalize_image_to_srgb_bytes(
    data: bytes,
    *,
    srgb_profile_path: str,
    embed_profile: bool = True,
    quality: int = 90,
) -> tuple[bytes, str]:
    srgb_profile_bytes = BytesIO(Path(srgb_profile_path).read_bytes()).getvalue()
    with Image.open(BytesIO(data)) as image:
        embedded = image.info.get("icc_profile")
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            converted = _apply_rgb_profile(rgba.convert("RGB"), embedded, srgb_profile_path)
            output = converted.convert("RGBA")
            output.putalpha(alpha)
            profile_bytes = srgb_profile_bytes if embed_profile else b""
            return save_png_with_profile_bytes(output, profile_bytes), "png"

        converted = _apply_rgb_profile(image.convert("RGB"), embedded, srgb_profile_path)
        profile_bytes = srgb_profile_bytes if embed_profile else None
        return save_jpeg_with_profile_bytes(converted, profile_bytes, quality=quality), "jpg"


def normalize_image_to_cmyk_bytes(
    data: bytes,
    *,
    srgb_profile_path: str,
    cmyk_profile_path: str,
    embed_profile: bool = False,
    quality: int = 90,
) -> tuple[bytes, str]:
    cmyk_profile_bytes = BytesIO(Path(cmyk_profile_path).read_bytes()).getvalue()
    with Image.open(BytesIO(data)) as image:
        embedded = image.info.get("icc_profile")
        working = flatten_transparency_to_white(image)
        converted = _apply_cmyk_profile(
            working,
            embedded,
            srgb_profile_path=srgb_profile_path,
            cmyk_profile_path=cmyk_profile_path,
        )
        # Photoshop CMYK profiles can be very large; use them for transform by default
        # and only embed them when the caller explicitly asks for it.
        profile_bytes = cmyk_profile_bytes if embed_profile else None
        return save_jpeg_with_profile_bytes(converted, profile_bytes, quality=quality), "jpg"


def process_safe_jpeg_bytes(
    data: bytes,
    action: str,
    preset: Preset,
    quality: int | None = None,
    policy: OptimizationPolicy | None = None,
) -> bytes:
    if action == "keep":
        return data
    if action not in {"recompress", "resize", "resize+recompress"}:
        raise ValueError(f"Unsupported SAFE action: {action}")

    resolved_policy = policy or policy_for_preset(preset)
    resolved_quality = resolved_policy.jpeg_quality if quality is None else quality
    with Image.open(BytesIO(data)) as image:
        working = image.convert("RGB")
        if action in {"resize", "resize+recompress"}:
            working = resize_image_to_box(working, resolved_policy.max_width, resolved_policy.max_height)
        return save_progressive_jpeg_bytes(working, quality=resolved_quality)


def process_hard_raster_bytes(
    data: bytes,
    action: str,
    preset: Preset,
    quality: int | None = None,
    policy: OptimizationPolicy | None = None,
) -> bytes:
    if action not in {"convert", "resize+convert"}:
        raise ValueError(f"Unsupported HARD raster action: {action}")

    resolved_policy = policy or policy_for_preset(preset)
    resolved_quality = resolved_policy.jpeg_quality if quality is None else quality
    with Image.open(BytesIO(data)) as image:
        working = image.copy()
        if action == "resize+convert":
            working = resize_image_to_box(working, resolved_policy.max_width, resolved_policy.max_height)
        working = flatten_transparency_to_white(working)
        return save_progressive_jpeg_bytes(working, quality=resolved_quality)
