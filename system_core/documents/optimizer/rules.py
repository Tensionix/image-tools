from __future__ import annotations

from .models import (
    Decision,
    Mode,
    OptimizationPolicy,
    Preset,
    SUPPORTED_SAFE,
    SUPPORTED_HARD,
    ScanItem,
    policy_for_dimensions,
    policy_for_preset,
)


def _is_small_visual_asset(item: ScanItem, policy: OptimizationPolicy) -> bool:
    if not item.width or not item.height:
        return False
    return (
        item.width <= policy.min_skip_width
        and item.height <= policy.min_skip_height
        and item.megapixels <= policy.min_skip_megapixels
    )


def is_light_lossless(item: ScanItem, policy: OptimizationPolicy) -> bool:
    """A picture stored without loss under the barrier in kilobytes: it stays as it is."""
    return bool(policy.keep_png_under_bytes) and 0 < item.encoded_size_bytes < policy.keep_png_under_bytes


def light_reason(policy: OptimizationPolicy) -> str:
    return f"Light picture rule: a picture stored without loss under {policy.keep_png_under_bytes // 1024} KB stays as it is."


def _exceeds_limit(item: ScanItem, policy: OptimizationPolicy) -> bool:
    if not item.width or not item.height:
        return False
    return (
        item.width > policy.max_width
        or item.height > policy.max_height
        or item.megapixels > policy.max_megapixels
    )


def recommend(
    item: ScanItem,
    mode: Mode,
    preset: Preset,
    batch: bool = False,
    policy: OptimizationPolicy | None = None,
) -> Decision:
    resolved_policy = policy or policy_for_preset(preset)
    item_policy = policy_for_dimensions(resolved_policy, item.width, item.height)
    ext = item.detected_format
    if mode == "safe":
        if ext not in SUPPORTED_SAFE:
            return Decision(mode, preset, "unsupported", "SAFE mode only works with JPEG files.")
        if _exceeds_limit(item, item_policy):
            action = "resize+recompress" if batch else "resize+recompress"
            return Decision(mode, preset, action, f"JPEG exceeds {item_policy.limit_label}.")
        return Decision(mode, preset, "keep", "JPEG already fits inside the selected limit.")

    if ext not in SUPPORTED_HARD:
        return Decision(mode, preset, "unsupported", "Unsupported image format for HARD mode.")

    if ext in {"jpg", "jpeg"}:
        if _exceeds_limit(item, item_policy):
            return Decision(mode, preset, "resize+recompress", f"JPEG exceeds {item_policy.limit_label}.")
        return Decision(mode, preset, "keep", "JPEG already fits inside the selected limit.")

    if is_light_lossless(item, item_policy):
        return Decision(mode, preset, "keep", light_reason(item_policy))

    if _is_small_visual_asset(item, item_policy):
        return Decision(mode, preset, "keep", "Small visual asset rule: keep tiny images by pixels, not by file size.")

    if _exceeds_limit(item, item_policy):
        return Decision(mode, preset, "resize+convert", f"Raster image exceeds {item_policy.limit_label} and should be resized before JPEG conversion.")
    return Decision(mode, preset, "convert", "Supported non-JPEG raster image should be converted to JPEG in HARD mode.")
