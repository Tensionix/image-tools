"""The preview of the console command: the same command line of the engine on a copy made smaller - nothing of
the project written, the copy and what was made of it handed back, the size at full scale told right."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
CLI = PROJECT / "system_core" / "cli.py"


def _preview(tmp_path: Path, operation: str, picture: Path, *sets: str) -> dict:
    words = [sys.executable, "-X", "utf8", str(CLI), "--language", "en", "preview", "--operation", operation, "--file", str(picture),
             "--out", str(tmp_path / "out")]
    for one in sets:
        words += ["--set", one]
    done = subprocess.run(words, capture_output=True, text=True, encoding="utf-8")
    line = next(line for line in done.stdout.splitlines() if line.startswith('::image::{"preview"'))
    return json.loads(line[len("::image::"):])["preview"]


def _picture(tmp_path: Path) -> Path:
    path = tmp_path / "wide.png"
    Image.new("RGB", (2400, 1600), (40, 90, 160)).save(path, dpi=(300, 300))
    return path


def _project_files() -> set[str]:
    return {str(path) for folder in ("logs", "report") for path in (PROJECT / folder).rglob("*") if path.is_file()}


def test_a_turn_seen_on_a_copy_and_nothing_of_the_project_written(tmp_path: Path) -> None:
    before = _project_files()
    told = _preview(tmp_path, "rotate_angle", _picture(tmp_path), "angle=90")
    assert "error" not in told, told
    assert told["pixels"] == [2400, 1600] and told["factor"] == 0.5 and told["dpi"] == [300.0, 300.0]
    with Image.open(told["before"]) as copy:
        assert copy.size == (1200, 800) and round(copy.info["dpi"][0]) == 150
    assert told["after"][0]["pixels"] == [800, 1200] and told["after"][0]["full_pixels"] == [1600, 2400]
    assert _project_files() == before


def test_a_size_set_by_the_form_is_told_as_it_is(tmp_path: Path) -> None:
    told = _preview(tmp_path, "exact_size", _picture(tmp_path), "width=640", "height=480")
    assert told["after"][0]["full_pixels"] == [640, 480]


def test_what_the_preview_cannot_show_is_said(tmp_path: Path) -> None:
    picture = _picture(tmp_path)
    assert "error" in _preview(tmp_path, "docs_shrink", picture)
    # A watermark without its text is refused by the form, not run.
    refused = _preview(tmp_path, "watermark", picture)
    assert "error" in refused and "text" in refused["error"].lower()


def test_the_pages_with_a_preview_are_named_by_the_layout() -> None:
    sys.path.insert(0, str(PROJECT))
    from system_core.core import window_layout

    told = window_layout.describe(window_layout.load(PROJECT / "config"))
    shown = {place["op"] for section in told["sections"] for row in window_layout.ROWS for place in section[row] if place["preview"]}
    assert {"rotate_angle", "trim_border", "smart_crop_white", "add_margins", "split_half", "exact_size"} <= shown
    assert not shown & {"docs_shrink", "pdf_merge", "images_to_pdf"}
