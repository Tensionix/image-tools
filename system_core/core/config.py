from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def load_yaml_or_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")

    if path.suffix.lower() == ".json":
        return json.loads(text)

    try:
        import yaml  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"PyYAML is required to read {path.name}. Install package: pyyaml") from exc

    # The loader of C when PyYAML has it: the manifest of 3500 lines is read in a tenth of the time, and every call
    # of the console command - the preview among them - waits for it. The same safe loader, written in C.
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    data = yaml.load(text, Loader=loader) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return data
