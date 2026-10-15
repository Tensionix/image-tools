"""What the window sends the console command, held to the rules of the command.

The self-test of the built window (`--self-test --to FILE`) writes beside its report what the window
would send for every operation: the untouched form, and every choice of every switch set as its
button sets it (`FILE.sent.json`). A window that draws every field and sends the wrong thing passes
a check of what is drawn; this one does not. Skipped when no build of the window is there.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from system_core.core import operation_model as model
from system_core.core.manifest import load_manifest

PROJECT = Path(__file__).resolve().parent.parent
BUILDS = [PROJECT / "App" / "AudionImageTools.exe", PROJECT / "Source" / "bin" / "Debug" / "net10.0" / "AudionImageTools.exe"]
SOURCE, TARGET = PROJECT / "input", PROJECT / "output"


@pytest.fixture(scope="module")
def sent(tmp_path_factory: pytest.TempPathFactory) -> dict:
    window = next((build for build in BUILDS if build.is_file()), None)
    if window is None:
        pytest.skip("no build of the window: install\\Build-App.cmd, or dotnet build -c Debug in Source")
    report = tmp_path_factory.mktemp("window") / "report.txt"
    done = subprocess.run([str(window), "--self-test", "--to", str(report)], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    return json.loads((report.parent / (report.name + ".sent.json")).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(PROJECT / "config" / "tool_manifest.yaml")


def _run(node, values: dict) -> dict:
    return model.build_parameters(node, model.form_values(node, values), SOURCE, TARGET)


def test_an_untouched_form_sends_what_the_command_would_run_by_default(sent: dict, manifest) -> None:
    assert len(sent["untouched"]) >= 24
    for operation, values in sent["untouched"].items():
        node = model.find_node(manifest, operation)
        assert node is not None, operation
        assert model.unknown_values(node, values) == [], operation
        assert model.wrong_choices(node, model.form_values(node, values)) == [], operation
        assert model.refusal(node, model.form_values(node, values)) == model.refusal(node, model.form_values(node, {})), operation
        assert _run(node, values) == _run(node, {}), operation


def test_every_choice_set_by_its_button_reaches_the_command_as_that_choice(sent: dict, manifest) -> None:
    assert len(sent["choices"]) >= 150
    wrong = []
    for item in sent["choices"]:
        node = model.find_node(manifest, item["operation"])
        if _run(node, item["sent"]) != _run(node, {item["field"]: item["option"]}):
            wrong.append(f"{item['operation']}/{item['field']}={item['option']}")
    assert not wrong, wrong[:10]
