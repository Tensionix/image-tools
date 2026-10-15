"""The fields of Convert the engine had and the window now shows: the background under transparency, the
compression of PNG, the metadata - from the form to the command line and into the file written.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from system_core.core import jobs
from system_core.core import operation_model as model
from system_core.core.manifest import load_manifest
from system_core.core.paths import get_project_paths
from system_core.image_tools.pipeline import parse_color
from system_core.services import image_tools_gui as service

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "system_core" / "main.py"


def test_a_colour_of_ones_own_is_read_as_r_g_b() -> None:
    assert parse_color("10,20,30") == (10, 20, 30)
    assert parse_color("300, 0, 7") == (255, 0, 7)
    assert parse_color("#0a141e") == (10, 20, 30)
    assert parse_color("black") == (0, 0, 0)


def test_the_form_sends_its_own_background(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copytree(PROJECT / "config", tmp_path / "config")
    for name in ("input", "output", "logs", "report", "workspace"):
        (tmp_path / name).mkdir()
    node = model.find_node(load_manifest(tmp_path / "config" / "tool_manifest.yaml"), "convert_images")
    values = model.form_values(node, {"to": ["jpg", "png"], "alpha_bg": "custom", "alpha_rgb": "10,20,30", "png_preset": "small",
                                      "metadata": "strip_all"})
    parameters = model.build_parameters(node, values, tmp_path / "input", tmp_path / "output")
    ran: list[list[str]] = []
    monkeypatch.setattr(service, "_run_cli", lambda _context, args: ran.append([str(part) for part in args]) or 0)
    jobs.execute_operation(get_project_paths(tmp_path), node.to_operation(parameters))
    assert len(ran) == 2
    for command in ran:
        assert command[command.index("--alpha-bg") + 1] == "10,20,30"
        assert command[command.index("--png-preset") + 1] == "small"
        assert command[command.index("--metadata") + 1] == "strip_all"
    # Only JPG asked for: the compression of PNG is not live and is not sent.
    ran.clear()
    values = model.form_values(node, {"to": ["jpg"], "png_preset": "small"})
    jobs.execute_operation(get_project_paths(tmp_path), node.to_operation(model.build_parameters(node, values, tmp_path / "input",
                                                                                                  tmp_path / "output")))
    assert "--png-preset" not in ran[0]


def test_the_transparent_parts_lie_on_the_background_asked_for(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    picture = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    picture.paste((200, 30, 30, 255), (16, 16, 48, 48))
    picture.save(source / "mark.png")
    done = subprocess.run([sys.executable, "-X", "utf8", str(MAIN), "convert", "--input", str(source), "--output", str(tmp_path / "out"),
                           "--to", "jpg", "--jpeg-quality", "95", "--alpha-bg", "10,120,200", "--log-dir", str(tmp_path / "logs")],
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr
    written = next((tmp_path / "out").rglob("mark.jpg"))
    with Image.open(written) as result:
        corner = result.convert("RGB").getpixel((2, 2))
    assert all(abs(got - want) <= 6 for got, want in zip(corner, (10, 120, 200))), corner


def test_an_icon_holds_every_size_up_to_its_side(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    Image.new("RGBA", (300, 180), (30, 120, 220, 255)).save(source / "logo.png")
    Image.new("RGB", (40, 20), (200, 0, 0)).save(source / "small.png")
    done = subprocess.run([sys.executable, "-X", "utf8", str(MAIN), "convert", "--input", str(source), "--output", str(tmp_path / "out"),
                           "--to", "ico", "--log-dir", str(tmp_path / "logs")], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr
    with Image.open(tmp_path / "out" / "logo.ico") as icon:
        assert sorted(icon.info["sizes"]) == [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        # The picture is wider than tall: the square has transparent margins above and below.
        assert icon.convert("RGBA").getpixel((128, 2))[3] == 0 and icon.convert("RGBA").getpixel((128, 128))[3] == 255
    with Image.open(tmp_path / "out" / "small.ico") as icon:
        assert sorted(icon.info["sizes"]) == [(16, 16), (24, 24), (32, 32)]
