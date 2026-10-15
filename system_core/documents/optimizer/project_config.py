from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(slots=True)
class ICCConfig:
    srgb_profile: Path
    cmyk_profile: Path


@dataclass(slots=True)
class ProjectConfig:
    root: Path
    defaults_path: Path
    jpeg_quality_default: int
    icc: ICCConfig


def get_project_root() -> Path:
    # system_core\documents\optimizer\project_config.py: the root of Audion Image Tools is three folders up.
    return Path(__file__).resolve().parents[3]


def load_project_config() -> ProjectConfig:
    root = get_project_root()
    defaults_path = root / "config" / "defaults.json"
    payload = json.loads(defaults_path.read_text(encoding="utf-8"))
    icc = payload.get("icc", {})
    return ProjectConfig(
        root=root,
        defaults_path=defaults_path,
        jpeg_quality_default=int(payload.get("jpeg_quality_default", 75)),
        icc=ICCConfig(
            srgb_profile=(root / icc.get("srgb_profile", "config/icc/sRGB2014.icc")).resolve(),
            cmyk_profile=(root / icc.get("cmyk_profile", "config/icc/Photoshop5DefaultCMYK.icc")).resolve(),
        ),
    )
