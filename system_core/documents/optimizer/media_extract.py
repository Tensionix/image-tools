from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
import shutil

from .project_config import load_project_config


MEDIA_PREFIXES = ("word/media/", "ppt/media/")


@dataclass(slots=True)
class MediaExtractResult:
    source: Path
    target_dir: Path
    extracted: list[Path]
    warnings: list[str]
    errors: list[str]


def _default_output_root() -> Path:
    return load_project_config().root / "output"


def extract_media(target: str | Path, output_root: str | Path | None = None) -> MediaExtractResult:
    source = Path(target).resolve()
    root = Path(output_root).resolve() if output_root else _default_output_root()
    target_dir = root / source.stem
    extracted: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    if source.suffix.lower() not in {".docx", ".pptx"}:
        errors.append(f"Unsupported file extension: {source.suffix}")
        return MediaExtractResult(source, target_dir, extracted, warnings, errors)

    if not source.exists():
        errors.append(f"File not found: {source}")
        return MediaExtractResult(source, target_dir, extracted, warnings, errors)

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        with ZipFile(source, "r") as archive:
            media_names = [
                name
                for name in archive.namelist()
                if not name.endswith("/") and name.lower().startswith(MEDIA_PREFIXES)
            ]
            if not media_names:
                warnings.append("No word/media or ppt/media image parts found.")

            for media_name in media_names:
                target_path = target_dir / Path(media_name).name
                # Beside its place first, as every writer of the engine does: a stop leaves no cut picture in the folder.
                temp = target_path.with_name(f"{target_path.stem}.writing{target_path.suffix}")
                try:
                    with archive.open(media_name) as input_file, temp.open("wb") as output_file:
                        shutil.copyfileobj(input_file, output_file)
                    temp.replace(target_path)
                finally:
                    temp.unlink(missing_ok=True)
                extracted.append(target_path)
    except Exception as exc:
        errors.append(f"{exc.__class__.__name__}: {exc}")

    return MediaExtractResult(source, target_dir, extracted, warnings, errors)


def render_media_extract_report(result: MediaExtractResult) -> str:
    lines = [
        "=" * 72,
        "EXTRACT MEDIA",
        "=" * 72,
        f"Source: {result.source}",
        f"Output folder: {result.target_dir}",
        f"Extracted files: {len(result.extracted)}",
    ]
    if result.extracted:
        lines.append("")
        for path in result.extracted:
            lines.append(f"EXTRACTED: {path.name}")
    if result.warnings:
        lines.append("")
        for warning in result.warnings:
            lines.append(f"[WARN] {warning}")
    if result.errors:
        lines.append("")
        for error in result.errors:
            lines.append(f"[ERROR] {error}")
    return "\n".join(lines)
