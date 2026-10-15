from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

Mode = Literal["safe", "hard", "normalize-srgb", "normalize-cmyk"]
Preset = Literal["fhd", "qhd", "uhd", "office", "presentation", "quality", "custom"]
Action = Literal[
    "keep",
    "recompress",
    "resize",
    "resize+recompress",
    "convert",
    "resize+convert",
    "normalize-srgb",
    "normalize-cmyk",
    "unsupported",
    "skip",
]

SUPPORTED_SAFE = {"jpg", "jpeg"}
SUPPORTED_HARD = {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff"}
ALL_RECOGNIZED = SUPPORTED_HARD
UNSUPPORTED_IMAGE_EXTENSIONS = {"emf", "wmf", "svg"}
KNOWN_IMAGE_EXTENSIONS = ALL_RECOGNIZED | UNSUPPORTED_IMAGE_EXTENSIONS


@dataclass(frozen=True, slots=True)
class OptimizationPolicy:
    max_width: int
    max_height: int
    max_megapixels: float
    jpeg_quality: int
    min_skip_width: int
    min_skip_height: int
    min_skip_megapixels: float
    # A picture stored without loss and lighter than this stays as it is - an emblem, an icon, a line drawing:
    # as a JPEG it gains nothing and loses its edges. 0 - no such barrier.
    keep_png_under_bytes: int = 0

    @property
    def limit_label(self) -> str:
        return f"{self.max_width}x{self.max_height}, JPEG {self.jpeg_quality}"


PRESET_POLICIES: dict[str, OptimizationPolicy] = {
    "fhd": OptimizationPolicy(1920, 1080, 2.1, 82, 400, 400, 0.16),
    "qhd": OptimizationPolicy(2560, 1440, 3.7, 85, 400, 400, 0.16),
    "uhd": OptimizationPolicy(3840, 2160, 8.3, 90, 400, 400, 0.16),
    "office": OptimizationPolicy(1920, 1080, 2.1, 82, 400, 400, 0.16),
    "presentation": OptimizationPolicy(2560, 1440, 3.7, 85, 400, 400, 0.16),
    "quality": OptimizationPolicy(3840, 2160, 8.3, 90, 400, 400, 0.16),
    "custom": OptimizationPolicy(2560, 1440, 3.7, 85, 400, 400, 0.16),
}


def policy_for_preset(preset: str) -> OptimizationPolicy:
    return PRESET_POLICIES.get(str(preset or "").strip().lower(), PRESET_POLICIES["presentation"])


def policy_for_dimensions(policy: OptimizationPolicy, width: int | None, height: int | None) -> OptimizationPolicy:
    if not width or not height:
        return policy
    if height <= width or policy.max_height >= policy.max_width:
        return policy
    return replace(policy, max_width=policy.max_height, max_height=policy.max_width)


def _positive_int(value: int | None, fallback: int, minimum: int = 1) -> int:
    if value is None:
        return fallback
    return max(minimum, int(value))


def _positive_float(value: float | None, fallback: float, minimum: float = 0.01) -> float:
    if value is None:
        return fallback
    return max(minimum, float(value))


def _jpeg_quality(value: int | None, fallback: int) -> int:
    if value is None:
        return fallback
    return max(40, min(95, int(value)))


def build_optimization_policy(
    preset: str,
    *,
    max_width: int | None = None,
    max_height: int | None = None,
    max_megapixels: float | None = None,
    jpeg_quality: int | None = None,
    min_skip_width: int | None = None,
    min_skip_height: int | None = None,
    min_skip_megapixels: float | None = None,
    keep_png_under_kb: int | None = None,
) -> OptimizationPolicy:
    base = policy_for_preset(preset)
    return OptimizationPolicy(
        max_width=_positive_int(max_width, base.max_width),
        max_height=_positive_int(max_height, base.max_height),
        max_megapixels=_positive_float(max_megapixels, base.max_megapixels),
        jpeg_quality=_jpeg_quality(jpeg_quality, base.jpeg_quality),
        min_skip_width=_positive_int(min_skip_width, base.min_skip_width, minimum=0),
        min_skip_height=_positive_int(min_skip_height, base.min_skip_height, minimum=0),
        min_skip_megapixels=_positive_float(min_skip_megapixels, base.min_skip_megapixels),
        keep_png_under_bytes=max(0, int(keep_png_under_kb or 0)) * 1024,
    )


@dataclass(slots=True)
class ScanItem:
    document_path: Path
    package_path: str
    file_name: str
    extension: str
    detected_format: str
    width: int | None
    height: int | None
    encoded_size_bytes: int = 0
    zip_size_bytes: int = 0
    has_transparency: bool = False
    supported: bool = False
    note: str = ""

    @property
    def megapixels(self) -> float:
        if not self.width or not self.height:
            return 0.0
        return (self.width * self.height) / 1_000_000


@dataclass(slots=True)
class Decision:
    mode: Mode
    preset: Preset
    recommended_action: Action
    reason: str


@dataclass(slots=True)
class ScanResult:
    document_path: Path
    package_type: str
    items: list[ScanItem] = field(default_factory=list)
    unsupported_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_images(self) -> int:
        return len(self.items)


@dataclass(slots=True)
class AppliedItem:
    document_path: Path
    package_path: str
    output_package_path: str
    detected_format: str
    width: int | None
    height: int | None
    has_transparency: bool
    supported: bool
    recommended_action: Action
    executed_action: Action
    changed: bool
    bytes_before: int
    bytes_after: int
    note: str = ""


@dataclass(slots=True)
class ProcessResult:
    document_path: Path
    output_path: Path
    package_type: str
    mode: Mode
    preset: Preset
    batch: bool
    items: list[AppliedItem] = field(default_factory=list)
    unsupported_count: int = 0
    input_size_bytes: int = 0
    output_size_bytes: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_images(self) -> int:
        return len(self.items)
