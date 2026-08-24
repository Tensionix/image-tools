from __future__ import annotations

SUPPORTED_EXTENSIONS = {
    ".bmp", ".gif", ".jpg", ".jpeg", ".iff", ".png", ".psd", ".heic", ".tga",
    ".tif", ".tiff", ".xif", ".wmf", ".cr2", ".cr3", ".dng",
    ".heif", ".avif", ".webp",
}

CORE_EXTENSIONS = {".bmp", ".gif", ".jpg", ".jpeg", ".png", ".psd", ".tga", ".tif", ".tiff", ".avif", ".webp"}
HEIF_EXTENSIONS = {".heic", ".heif"}
RAW_EXTENSIONS = {".cr2", ".cr3", ".dng"}
PDF_EXTENSIONS = {".pdf"}

SCREEN_TARGETS = {
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2160p": (3840, 2160),
}

ASPECT_RATIOS = {
    "16:9": (16, 9),
    "a4-portrait": (210, 297),
    "a4-landscape": (297, 210),
    "a3-portrait": (297, 420),
    "a3-landscape": (420, 297),
}

PNG_PRESETS = {
    "fast": {"compress_level": 1, "optimize": False},
    "balanced": {"compress_level": 4, "optimize": False},
    "small": {"compress_level": 6, "optimize": True},
}

OUTPUT_FORMAT_CHOICES = ("jpg", "png", "tiff", "webp", "avif", "heif", "heic")
PIXEL_DPI_OUTPUT_FORMAT_CHOICES = ("jpg", "png", "tiff")
PDF_EXTRACT_OUTPUT_FORMAT_CHOICES = ("original", *OUTPUT_FORMAT_CHOICES)

PLOTTER_MM_CHOICES = (600, 900, 1050)
PLOTTER_DPI_CHOICES = (300, 600)
PERCENT_CHOICES = (25, 50)
RESAMPLE_ALGORITHM_CHOICES = ("lanczos", "bicubic", "box", "nearest")
PDF_RASTER_DPI_CHOICES = (150, 300, 600)
PDF_EXPORT_MODES = ("lossless", "jpg75", "jpg90")
