"""Every operation of the manifest stands in the window once, and the layout names nothing else."""
from __future__ import annotations

from pathlib import Path

from system_core.core import operation_model as model
from system_core.core import window_layout
from system_core.core.manifest import load_manifest

PROJECT = Path(__file__).resolve().parent.parent
ICONS = Path("E:/TOOLS/Lucide-Icons/package/icons")


def _both():
    manifest = load_manifest(PROJECT / "config" / "tool_manifest.yaml")
    operations = {node.id for node in model.all_nodes(manifest) if node.service}
    operations |= {operation.id for operation in manifest.maintenance_operations}
    return window_layout.load(PROJECT / "config"), operations


def test_every_operation_stands_in_the_window_once() -> None:
    layout, operations = _both()
    assert window_layout.problems(layout, operations) == []


def test_a_gap_in_the_layout_is_named() -> None:
    layout, operations = _both()
    assert window_layout.problems(layout, operations | {"a_new_operation"}) == ["stands nowhere in the window: a_new_operation"]
    assert window_layout.problems(layout, operations - {"watermark"}) == ["is not an operation of the manifest: watermark"]


def test_the_sections_are_the_nine_the_owner_named() -> None:
    layout, _operations = _both()
    told = window_layout.describe(layout)
    assert [section["id"] for section in told["sections"]] == ["convert", "pdf", "crop", "cut", "size", "dpi", "color", "photo_sheet", "sheets"]
    by_id = {section["id"]: section for section in told["sections"]}
    # Cropping and cutting apart; changing pixels and changing the print size apart. CROP became TRANSFORM
    # (the owner, 14.10.2026): turns, mirrors, a turn by an angle and margins stand with the crops.
    assert by_id["crop"]["title_ru"] == "ТРАНСФОРМАЦИЯ"
    assert [place["op"] for place in by_id["crop"]["images"]] == ["rotate_angle", "trim_border", "smart_crop_white", "add_margins"]
    assert [place["op"] for place in by_id["crop"]["quick"]] == ["quick_rotate_cw", "quick_rotate_ccw", "quick_rotate_180", "quick_flip_h", "quick_flip_v"]
    assert [place["op"] for place in by_id["cut"]["images"]] == ["split_half", "split_tiff"]
    # SIZE makes pictures larger too (the owner, 14.10.2026): an exact size, quick A4 -> A3, x2, x3.
    assert [place["op"] for place in by_id["size"]["images"]] == ["downscale_percent", "resize_screen", "aspect_fit", "exact_size"]
    assert [place["op"] for place in by_id["size"]["quick"]] == ["quick_scale_a3", "quick_scale_x2", "quick_scale_x3"]
    assert [place["op"] for place in by_id["dpi"]["images"]] == ["plotter_size", "plotter_dpi_only"]
    assert [place["op"] for place in told["service"]] == ["formats", "info", "doctor"]


def test_every_icon_named_is_in_the_set() -> None:
    if not ICONS.is_dir():
        import pytest

        pytest.skip("the icon set of the owner is not on this machine")
    layout, _operations = _both()
    told = window_layout.describe(layout)
    named = {section["icon"] for section in told["sections"]}
    named |= {place["icon"] for section in told["sections"] for row in window_layout.ROWS for place in section[row]}
    named |= {place["icon"] for place in told["service"]}
    missing = sorted(name for name in named if not (ICONS / f"{name}.svg").is_file())
    assert not missing, f"not in the icon set {ICONS}: {missing}"
