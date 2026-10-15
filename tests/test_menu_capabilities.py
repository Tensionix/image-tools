"""What only the console menus could do, now in the window (the plan, 5.7): the profile of Normalize, fit by height
or width and the colour of the margins - from the form to the command line and into the picture written."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image

from system_core.core import operation_model as model
from system_core.core.manifest import load_manifest
from system_core.services import image_tools_gui as service

PROJECT = Path(__file__).resolve().parent.parent
MANIFEST = load_manifest(PROJECT / "config" / "tool_manifest.yaml")


def _run(tmp_path: Path, operation: str, values: dict) -> list[str]:
    """The command line the window would send for these values, run in the project; the first of its runs is returned."""
    source = tmp_path / "in"
    if not source.exists():
        source.mkdir()
        Image.new("RGB", (400, 200), (40, 90, 160)).save(source / "wide.png")
    target = tmp_path / operation
    node = model.find_node(MANIFEST, operation)
    parameters = model.build_parameters(node, model.form_values(node, values), source, target)
    runs = service._manifest_cli_runs(PROJECT, node.to_operation(parameters))
    for words, _values in runs:
        done = subprocess.run([*words, "--log-dir", str(tmp_path / "logs")], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8")
        assert done.returncode == 0, done.stdout + done.stderr
    return [str(word) for word in runs[0][0]]


def _option(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def _written(tmp_path: Path, operation: str) -> Path:
    return next(path for path in (tmp_path / operation).rglob("wide.*") if path.is_file())


def test_cmyk_by_fogra39(tmp_path: Path) -> None:
    command = _run(tmp_path, "normalize_profile", {"target_profile": "cmyk", "cmyk_profile": "config/icc/CoatedFOGRA39.icc", "to": ["tiff"]})
    assert _option(command, "--cmyk-profile") == "config/icc/CoatedFOGRA39.icc"
    with Image.open(_written(tmp_path, "normalize_profile")) as image:
        assert image.mode == "CMYK"


def test_srgb_built_into_pillow(tmp_path: Path) -> None:
    command = _run(tmp_path, "normalize_profile", {"target_profile": "srgb", "srgb_profile_mode": "pillow", "to": ["png"]})
    assert _option(command, "--srgb-profile-mode") == "pillow" and "--cmyk-profile" not in command


def test_fit_by_height(tmp_path: Path) -> None:
    command = _run(tmp_path, "resize_screen", {"target": "1080p", "mode": "by-height", "to": ["png"]})
    assert _option(command, "--mode") == "by-height"
    with Image.open(_written(tmp_path, "resize_screen")) as image:
        assert image.size == (2160, 1080)


def test_white_margins(tmp_path: Path) -> None:
    command = _run(tmp_path, "aspect_fit", {"ratio": "a4-portrait", "mode": "pad", "background": "white", "to": ["png"]})
    assert _option(command, "--background") == "white"
    with Image.open(_written(tmp_path, "aspect_fit")) as image:
        assert image.convert("RGB").getpixel((image.width // 2, 2)) == (255, 255, 255)
