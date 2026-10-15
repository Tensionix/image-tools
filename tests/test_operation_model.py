"""The model of the parameters against what the former window did.

tests\\former_window_parameters.json holds 915 states of the forms of 27 operations as the window on
NiceGUI of 2.4.3 turned them into command lines of the engine, taken from that window before it went.
Here the same states go through system_core\\core\\operation_model.py and the
services, the engine not started: the refusal, the parameters and every command line must be the
same. The record is not written anew; a place where the former window was wrong is changed here,
one line each, with its reason.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from system_core.core import jobs
from system_core.core import operation_model as model
from system_core.core.manifest import load_manifest
from system_core.core.paths import get_project_paths
from system_core.services import image_tools_gui as service

PROJECT = Path(__file__).resolve().parent.parent
RECORD: list[dict[str, Any]] = json.loads((Path(__file__).resolve().parent / "former_window_parameters.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def stand(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A project folder with the configuration alone: what the record was taken on."""
    root = tmp_path_factory.mktemp("model")
    shutil.copytree(PROJECT / "config", root / "config")
    for name in ("input", "output", "logs", "report", "workspace"):
        (root / name).mkdir()
    (root / "input" / "one.jpg").write_bytes(b"")
    return root


@pytest.fixture(scope="module")
def manifest(stand: Path):
    return load_manifest(stand / "config" / "tool_manifest.yaml")


def _swap(value: Any, pairs: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for old, new in pairs:
            value = value.replace(old, new)
        return value
    if isinstance(value, (list, tuple)):
        return [_swap(item, pairs) for item in value]
    if isinstance(value, dict):
        return {key: _swap(item, pairs) for key, item in value.items()}
    return value


@pytest.mark.parametrize("entry", RECORD, ids=[f"{entry['operation']}:{entry['state']}" for entry in RECORD])
def test_a_form_becomes_what_the_former_window_made_of_it(entry: dict, stand: Path, manifest, monkeypatch: pytest.MonkeyPatch) -> None:
    there = [("<ROOT>", str(stand)), ("<PYTHON>", sys.executable)]
    back = [(str(stand), "<ROOT>"), (sys.executable, "<PYTHON>")]
    threads = entry["state"] == "threads=8"
    (stand / "config" / "parallel_settings.json").write_text(json.dumps({"parallel_enabled": threads, "worker_count": 8}), encoding="utf-8")
    source = stand / "input" / "one.jpg" if entry["state"] == "source=one file" else stand / "input"

    node = model.find_node(manifest, entry["operation"])
    assert node is not None
    values = model.form_values(node, _swap(entry["set"], there))

    if entry["operation"] == "plotter_dpi_only" and values.get("dpi_preset") == "custom" and values.get("dpi_custom") in (None, ""):
        # Changed on purpose: an own DPI left empty became 300 without a word (the inventory, 12.8); it is refused now.
        assert model.refusal(node, values, "en") == "Fill in: Custom DPI"
        return
    if "refused" in entry:
        assert model.refusal(node, values, "en") == entry["refused"][0]
        return
    assert model.refusal(node, values, "en") == ""

    parameters = model.build_parameters(node, values, source, stand / "output")
    expected = dict(entry["parameters"])
    if entry["operation"] == "watermark" and entry["state"].startswith("color_mode=custom"):
        # Changed on purpose: the former window never told a colour of one's own (the inventory, 12.1).
        # The colour now goes as its channels; the colour of this state is the default one, so the
        # command line below is the same as the record's.
        expected.update({"color_r": 204, "color_g": 0, "color_b": 0})
        expected.pop("custom_rgb", None)
    if entry["operation"] == "split_tiff":
        # Changed on purpose (the owner, 14.10.2026): every picture of many frames is taken apart, not a TIFF alone.
        expected["fixed_args"] = ["split-frames"]
        expected["defaults"] = {**expected["defaults"], "output_path": "output/frames"}
    added = ADDED_FIELDS.get(entry["operation"], {})
    if added:
        parameters = _without_added_fields(parameters, added)
    assert _swap(parameters, back) == expected

    ran: list[list[str]] = []
    monkeypatch.setattr(service, "_run_cli", lambda _context, args: ran.append([str(part) for part in service.unbuffer_python_command(args)]) or 0)
    result = jobs.execute_operation(get_project_paths(stand), node.to_operation(parameters))
    assert bool(result.ok) == entry["ok"], result.message
    commands = entry["commands"]
    if entry["operation"] == "tile_sheet":
        # Changed on purpose: a margin, a gap, copies and rows of 0 went as their defaults (the inventory, 12.7).
        commands = [_noughts_kept(command, parameters) for command in commands]
    if added:
        ran = [_without_added_args(command, added) for command in ran]
    if entry["operation"] == "split_tiff":
        commands = [[part.replace("split-tiff", "split-frames").replace("tiff_frames", "frames") for part in command] for command in commands]
    assert _swap(ran, back) == commands


# Fields this window added to a form of the former one (14.10.2026): their defaults are the engine's own, so the
# command means what it meant. They are taken out of what is held to the record - and must stand at the defaults.
ADDED_FIELDS = {"convert_images": {"--png-preset": ("png_preset", "balanced"), "--metadata": ("metadata", "preserve_dpi_color"),
                                   "--alpha-bg": ("alpha_bg", "white")},
                # What only the console menus could do (the plan, 5.7): the profiles, the colour of the margins.
                "normalize_profile": {"--srgb-profile-mode": ("srgb_profile_mode", "colororg"),
                                      "--cmyk-profile": ("cmyk_profile", "config/icc/Photoshop5DefaultCMYK.icc")},
                "resize_screen": {"--background": ("background", "black")},
                "aspect_fit": {"--background": ("background", "black")}}


def _without_added_fields(parameters: dict, added: dict) -> dict:
    kept = dict(parameters)
    for flag, (field, default) in added.items():
        assert kept.pop(field, default) == default, field
        for key in ("value_args", "composite_args"):
            if isinstance(kept.get(key), dict) and flag in kept[key]:
                kept[key] = {name: spec for name, spec in kept[key].items() if name != flag}
                if not kept[key]:
                    kept.pop(key)
    return kept


def _without_added_args(command: list[str], added: dict) -> list[str]:
    kept: list[str] = []
    skip = False
    for index, part in enumerate(command):
        if skip:
            skip = False
            continue
        if part in added:
            assert command[index + 1] == added[part][1], (part, command[index + 1])
            skip = True
            continue
        kept.append(part)
    return kept


def _noughts_kept(command: list[str], parameters: dict) -> list[str]:
    """A command line of the record with the noughts the former window lost put back: only of a field that was told."""
    fixed = list(command)
    for flag, key in (("--margin-mm", "margin_mm"), ("--gap-mm", "gap_mm"), ("--copies", "copies"), ("--rows", "rows")):
        if flag in fixed and key in parameters and parameters[key] in (0, 0.0):
            fixed[fixed.index(flag) + 1] = str(parameters[key])
    return fixed


# Operations the window on NiceGUI never had: they have no state of its forms to be held to.
NEW_SINCE_THE_FORMER_WINDOW = {"docs_dpi_check", "docs_dpi_raise", "docs_shrink", "docs_fit_size", "docs_color", "docs_extract_media",
                               "quick_rotate_cw", "quick_rotate_ccw", "quick_rotate_180", "quick_flip_h", "quick_flip_v",
                               "rotate_angle", "add_margins",
                               "pdf_dpi_check", "pdf_dpi_raise", "pdf_shrink_images", "pdf_watermark",
                               "pdf_rotate_pages", "pdf_merge", "pdf_split", "quick_pdf_clean_meta",
                               "exact_size", "quick_scale_a3", "quick_scale_x2", "quick_scale_x3", "quick_strip_meta",
                               "frames_to_animation", "color_adjust", "png_palette", "quick_auto_levels", "quick_png_256"}


def test_every_operation_of_the_manifest_is_in_the_record(manifest) -> None:
    recorded = {entry["operation"] for entry in RECORD}
    runs = {node.id for node in model.all_nodes(manifest) if node.service} - NEW_SINCE_THE_FORMER_WINDOW
    assert runs == recorded, f"not in the record: {sorted(runs - recorded)}; not in the manifest: {sorted(recorded - runs)}"


def test_a_refusal_speaks_the_language_asked_for(manifest) -> None:
    node = model.find_node(manifest, "watermark")
    values = model.form_values(node, {})
    assert model.refusal(node, values, "en") == "Fill in: Watermark text"
    assert model.refusal(node, values, "ru").startswith("Заполните поле: ")
    # The former window said these in English whatever its language was.
    node = model.find_node(manifest, "trim_border")
    assert model.refusal(node, model.form_values(node, {"tolerance": -1}), "ru").endswith(": не меньше 0.")


def test_a_colour_of_ones_own_reaches_the_engine(stand: Path, manifest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The former window sent 204,0,0 whatever colour was set (the inventory, 12.1)."""
    node = model.find_node(manifest, "watermark")
    ran: list[list[str]] = []
    monkeypatch.setattr(service, "_run_cli", lambda _context, args: ran.append([str(part) for part in args]) or 0)
    for typed, sent in (("10,20,30", "10,20,30"), ("#0a141e", "10,20,30"), ("300,0,0", "255,0,0")):
        ran.clear()
        values = model.form_values(node, {"text": "SAMPLE", "color_mode": "custom", "custom_rgb": typed})
        jobs.execute_operation(get_project_paths(stand), node.to_operation(model.build_parameters(node, values, stand / "input", stand / "output")))
        assert ran and ran[0][ran[0].index("--color") + 1] == sent, (typed, ran)
    # A colour of the row of ready ones goes as it is; the channels are not told.
    values = model.form_values(node, {"text": "SAMPLE", "color_mode": "#0066cc"})
    parameters = model.build_parameters(node, values, stand / "input", stand / "output")
    assert "custom_rgb" not in parameters and parameters["color_mode"] == "#0066cc"


def test_a_nought_of_tile_sheet_stays_a_nought(stand: Path, manifest, monkeypatch: pytest.MonkeyPatch) -> None:
    node = model.find_node(manifest, "tile_sheet")
    ran: list[list[str]] = []
    monkeypatch.setattr(service, "_run_cli", lambda _context, args: ran.append([str(part) for part in args]) or 0)
    values = model.form_values(node, {"margin_mm": 0, "rows": 0, "count_mode": "rows"})
    jobs.execute_operation(get_project_paths(stand), node.to_operation(model.build_parameters(node, values, stand / "input", stand / "output")))
    line = ran[0]
    assert line[line.index("--margin-mm") + 1] == "0" and line[line.index("--rows") + 1] == "0"


def test_an_empty_dpi_of_ones_own_is_refused(manifest) -> None:
    node = model.find_node(manifest, "plotter_dpi_only")
    assert model.refusal(node, model.form_values(node, {"dpi_preset": "custom"})) == "Fill in: Custom DPI"
    assert model.refusal(node, model.form_values(node, {"dpi_preset": "custom", "dpi_custom": 450})) == ""
    # Not asked for while a ready DPI is chosen.
    assert model.refusal(node, model.form_values(node, {"dpi_preset": "300"})) == ""


def test_a_value_that_is_no_option_is_named(manifest) -> None:
    node = model.find_node(manifest, "downscale_percent")
    assert model.wrong_choices(node, model.form_values(node, {"algorithm": "cubic"}))
    assert not model.wrong_choices(node, model.form_values(node, {"algorithm": "bicubic"}))
    assert model.unknown_values(node, {"algoritm": "x"}) == ["algoritm"]


def test_the_text_of_a_console_becomes_the_value_of_its_field(manifest) -> None:
    node = model.find_node(manifest, "downscale_percent")
    fields = {model.field_id(field): field for field in node.fields}
    assert model.coerce(fields["unsharp"], "false") is False
    assert model.coerce(fields["custom_percent"], "75") == 75
    assert model.coerce(fields["target_mb"], "0,5") == 0.5
    node = model.find_node(manifest, "convert_images")
    fields = {model.field_id(field): field for field in node.fields}
    assert model.coerce(fields["to"], "jpg, png") == ["jpg", "png"]
