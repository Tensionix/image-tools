"""The console command, run as a caller runs it.

Every case starts system_core\\cli.py of a stand - a copy of the configuration and of the engine in
a temporary folder - so the journals and reports of a run never land in the project.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
CONTROL = "::image::"


@pytest.fixture(scope="module")
def stand(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("command")
    shutil.copytree(PROJECT / "config", root / "config")
    shutil.copytree(PROJECT / "system_core", root / "system_core",
                    ignore=shutil.ignore_patterns("__pycache__", "jpegtran", "license"))
    return root


@pytest.fixture()
def pictures(tmp_path: Path) -> tuple[Path, Path]:
    source, target = tmp_path / "in", tmp_path / "out"
    (source / "sub").mkdir(parents=True)
    colour = random.Random(5)
    for number in range(6):
        picture = Image.new("RGB", (300, 200), (colour.randrange(256), colour.randrange(256), colour.randrange(256)))
        picture.save((source / "sub" if number > 3 else source) / f"p{number}.jpg", quality=90, dpi=(96, 96))
    return source, target


def cli(stand: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-u", str(stand / "system_core" / "cli.py"), *args], cwd=str(cwd or stand),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)


def service_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line[len(CONTROL):]) for line in output.splitlines() if line.startswith(CONTROL)]


def files(folder: Path) -> list[str]:
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()) if folder.exists() else []


def test_describe_tells_the_whole_manifest(stand: Path) -> None:
    done = cli(stand, "describe")
    assert done.returncode == 0
    told = json.loads(done.stdout)
    # 27 of the window on NiceGUI the ten over documents and the seven of TRANSFORM (system_core\documents).
    assert told["operations"] == 58 and told["language"] == "en"
    assert told["version"] == json.loads((PROJECT / "config" / "version.json").read_text(encoding="utf-8"))["version"]
    size = next(node for node in told["nodes"] if node["id"] == "size")
    first = size["children"][0]
    routes = {field["id"]: field["route"] for field in first["fields"]}
    assert routes["input_path"] == "source" and routes["output_path"] == "target" and routes["scale_mode"] == ""
    assert cli(stand, "version").stdout.strip() == told["version"]
    # The layout of the window comes with it: nine sections, the service of the header.
    layout = told["layout"]
    assert len(layout["sections"]) == 9 and [node["id"] for node in layout["service"]] == ["formats", "info", "doctor"]
    # A page is an operation with its form; the Source and the Target are not fields of a form.
    page = next(section for section in layout["sections"] if section["id"] == "size")["pages"][0]
    form = page["operations"][0]
    assert (page["id"], page["row"], form["direct"]) == ("downscale_percent", "images", False)
    assert "input_path" not in {field["id"] for field in form["fields"]}
    tones = {option["value"]: option["tone"] for field in form["fields"] if field["id"] == "scale_mode" for option in field["options"]}
    assert tones == {"percent-25": "process", "percent-50": "process", "custom": "warn", "target-mb": "warn"}
    # The quick buttons of conversion stand on its page and run at once.
    quick = [node["id"] for node in layout["sections"][0]["pages"][0]["operations"] if node["direct"]]
    assert quick == ["quick_jpg_75", "quick_png", "quick_gray_png", "quick_2160_jpg", "quick_169_jpg"]


def test_an_operation_runs_and_tells_how_far_it_is(stand: Path, pictures: tuple[Path, Path], tmp_path: Path) -> None:
    source, target = pictures
    result = tmp_path / "result.json"
    done = cli(stand, "run", "--operation", "downscale_percent", "--source", str(source), "--target", str(target),
               "--live", "--result", str(result))
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-500:]
    told = service_lines(done.stdout)
    assert "started" in told[0] and told[-1]["finished"]["outcome"] == "done"
    shares = [line["progress"] for line in told if "progress" in line]
    assert shares == sorted(shares) and shares[-1] == 1.0, f"the share done never goes back: {shares}"
    pulses = [line["activity"] for line in told if "activity" in line]
    assert pulses and pulses[-1].startswith("Processing: 100% · 6 / 6")
    assert not any("%|" in line for line in done.stdout.splitlines()), "the bar of the engine is told as progress, not as lines"
    assert "deprecated" not in done.stdout
    assert files(target) == ["p0.png", "p1.png", "p2.png", "p3.png", "sub/p4.png", "sub/p5.png"]
    outcome = json.loads(result.read_text(encoding="utf-8"))
    assert (outcome["outcome"], outcome["ok"], outcome["operation"]) == ("done", True, "downscale_percent")


def test_a_batch_is_one_live_line_for_the_window_and_every_line_for_a_console(stand: Path, pictures: tuple[Path, Path], tmp_path: Path) -> None:
    source, target = pictures
    done = cli(stand, "run", "--operation", "quick_strip_meta", "--source", str(source), "--target", str(target), "--live")
    assert done.returncode == 0, done.stdout[-1500:]
    journal = [line for line in done.stdout.splitlines() if not line.startswith(CONTROL)]
    assert not any(line.startswith("[OK") for line in journal), journal
    assert not any(line.startswith("Parameters:") for line in journal), "the parameters stay in the log file"
    assert any(line.startswith("6 of 6 pictures without EXIF and GPS") for line in journal), journal
    pulses = [line["activity"] for line in service_lines(done.stdout) if "activity" in line]
    assert pulses and pulses[-1].startswith("Processing: 100% · 6 / 6") and pulses[-1].endswith(".jpg"), pulses
    # The log file of the operation keeps every line, without colour codes.
    log = max((stand / "logs").glob("*_quick_strip_meta.log"), key=lambda path: path.stat().st_mtime).read_text(encoding="utf-8")
    assert log.count("[OK ") == 6 and "\x1b" not in log
    console = cli(stand, "run", "--operation", "quick_strip_meta", "--source", str(source), "--target", str(tmp_path / "again"))
    assert sum(1 for line in console.stdout.splitlines() if line.startswith("[OK ")) == 6
    assert "\x1b" not in console.stdout, "a pipe that did not ask for colours gets the text alone"


def test_a_console_gets_the_bar_as_before(stand: Path, pictures: tuple[Path, Path]) -> None:
    source, target = pictures
    done = cli(stand, "run", "--operation", "downscale_percent", "--source", str(source), "--target", str(target))
    assert done.returncode == 0
    assert any("%|" in line for line in done.stdout.splitlines())
    assert not any("activity" in line for line in service_lines(done.stdout))


def test_every_format_ticked_is_a_run_of_its_own(stand: Path, pictures: tuple[Path, Path]) -> None:
    source, target = pictures
    done = cli(stand, "run", "--operation", "convert_images", "--source", str(source), "--target", str(target),
               "--set", "to=jpg,png", "--live")
    assert done.returncode == 0, done.stdout[-1500:]
    assert {name.split("/")[0] for name in files(target)} == {"jpg", "png"}
    shares = [line["progress"] for line in service_lines(done.stdout) if "progress" in line]
    assert shares == sorted(shares) and shares[-1] == 1.0
    assert any(0.4 <= share <= 0.6 for share in shares), f"the first of two runs is a half of the work: {shares}"


def test_one_file_may_be_the_source(stand: Path, pictures: tuple[Path, Path]) -> None:
    source, target = pictures
    done = cli(stand, "run", "--operation", "downscale_percent", "--source", str(source / "p0.jpg"), "--target", str(target))
    assert done.returncode == 0, done.stdout[-1500:]
    assert files(target) == ["p0.png"]


@pytest.mark.parametrize("args, said", [
    (["--operation", "watermark"], "Fill in: Watermark text"),
    (["--operation", "downscale_percent", "--set", "nothing=1"], "no field 'nothing'"),
    (["--operation", "downscale_percent", "--set", "algorithm=cubic"], "not one of its options"),
    (["--operation", "downscale_percent", "--set", "input_path=D:\\x"], "--source and --target"),
    (["--operation", "trim_border", "--set", "tolerance=-1"], "minimum is 0"),
    # "nan" passed every limit and 1.5 a whole field: the engine was started and failed (the audit of 15.10.2026, F11).
    (["--operation", "docs_shrink", "--set", "keep_png_kb=nan"], "enter a number"),
    (["--operation", "docs_shrink", "--set", "keep_png_kb=1.5"], "enter a whole number"),
    (["--operation", "no_such_operation"], "no operation"),
])
def test_a_wrong_call_runs_nothing(stand: Path, pictures: tuple[Path, Path], args: list[str], said: str) -> None:
    source, target = pictures
    done = cli(stand, "run", *args, "--source", str(source), "--target", str(target))
    assert done.returncode == 2 and said in done.stderr, done.stderr
    assert not service_lines(done.stdout) and files(target) == []
    assert len(files(source)) == 6


def test_a_target_inside_the_source_is_a_wrong_call(stand: Path, pictures: tuple[Path, Path]) -> None:
    # The copies of a run would be read as its originals and land on them (the audit of 15.10.2026, F01).
    source, _ = pictures
    done = cli(stand, "run", "--operation", "downscale_percent", "--source", str(source), "--target", str(source / "sub"))
    assert done.returncode == 2 and "inside the Source" in done.stderr, done.stderr
    assert not service_lines(done.stdout) and files(source / "sub") == ["p4.jpg", "p5.jpg"]


def test_a_stop_asked_before_the_start_begins_nothing(stand: Path, pictures: tuple[Path, Path], tmp_path: Path) -> None:
    source, target = pictures
    signal, result = tmp_path / "stop", tmp_path / "result.json"
    signal.write_text("", encoding="utf-8")
    done = cli(stand, "run", "--operation", "downscale_percent", "--source", str(source), "--target", str(target),
               "--cancel-file", str(signal), "--result", str(result))
    assert done.returncode == 130
    assert service_lines(done.stdout)[-1]["finished"]["outcome"] == "stopped"
    assert json.loads(result.read_text(encoding="utf-8"))["outcome"] == "stopped"
    assert files(target) == []


def test_a_stop_is_seen_while_the_engine_is_silent(stand: Path, tmp_path: Path) -> None:
    """Until 3.0.0 a stop was looked at only after a line of output: a silent engine ran to its end."""
    sys.path.insert(0, str(PROJECT))
    from system_core.core.jobs import JobContext
    from system_core.core.manifest import Operation
    from system_core.core.paths import get_project_paths
    from system_core.services import image_tools_gui as service

    asked = threading.Event()
    context = JobContext(get_project_paths(stand), Operation("probe", "probe", "", "x:y"), tmp_path / "probe.log", tmp_path,
                         None, None, asked.is_set)
    threading.Timer(0.6, asked.set).start()
    began = time.monotonic()
    code = service._run_cli(context, [sys.executable, "-c", "import time; time.sleep(60)"])
    assert code != 0 and time.monotonic() - began < 10
    assert "Stop requested: ending the engine" in (tmp_path / "probe.log").read_text(encoding="utf-8")


def test_a_run_leaves_no_empty_report_folder(stand: Path, pictures: tuple[Path, Path]) -> None:
    source, target = pictures
    before = set(files(stand / "report")) | {path.name for path in (stand / "report").glob("*")} if (stand / "report").exists() else set()
    done = cli(stand, "run", "--operation", "downscale_percent", "--source", str(source), "--target", str(target))
    assert done.returncode == 0
    left = {path.name for path in (stand / "report").glob("*")} - before
    assert not left, f"an operation that writes no report leaves no folder for it: {left}"
    assert any(path.name.endswith("_downscale_percent.log") for path in (stand / "logs").glob("*.log"))


def test_describe_tells_what_the_engine_can_do_here(stand: Path) -> None:
    """The badges of the header: HEIC, AVIF, RAW, Word, PowerPoint - each with a tooltip in both languages."""
    told = json.loads(cli(stand, "describe").stdout)
    rows = {row["id"]: row for row in told["abilities"]}
    assert list(rows) == ["heic", "avif", "raw", "word", "powerpoint"]
    for row in rows.values():
        assert isinstance(row["ok"], bool) and row["tip"] and row["tip_ru"] and row["text"]
    # The environment of the project carries the readers of HEIC and RAW.
    assert rows["heic"]["ok"] and rows["raw"]["ok"]
