"""The console command of Audion Image Tools.

A button of the window and the command line run the same thing: an operation of the manifest, by
the same runner (`execute_operation`), with the same rules of its form
(`core\\operation_model.py`). Until 3.0.0 an operation could be run "as the window runs it" only
from the window.

  python system_core/cli.py describe
  python system_core/cli.py run --operation downscale_percent --set scale_mode=custom --set custom_percent=75
  python system_core/cli.py run --operation convert_images --source D:\\Photos --target D:\\Out --set to=jpg,png
  python system_core/cli.py version

The output of `run`: a plain line is a line of the operation's journal; a line that starts with
`::image::` is a service line and carries JSON - `started`, `progress` (the share of the work
done, 0..1), `activity` (the one live line under the journal), `finished`. The outcome goes to the
file of `--result` as well.

The engine tells how far it is with a bar of tqdm, a line for every step. A caller that asked for
it (`--live`: the window does) gets `progress` and `activity` instead of those lines, and a batch
folded: the line of every file that went as asked moves the live line on, a file that went wrong
stays a line (`Journal`); a console gets every line as before. A caller that reads the output by a pipe gets the text without colour codes,
or with them when it asks (`--colours`).

Outcomes and exit codes: `done` 0; `failed` 1; `stopped` 130; a wrong call - 2, and nothing is
run. A form that may not be run as it stands (an empty required field, a number out of its
limits, a value that is none of the options) is a wrong call.

Paths: a relative `--source` or `--target` is counted from the project folder, as the window
shows them; a relative `--params`, `--result` or `--cancel-file` - from the folder of the caller.

Stopping: the caller creates the file of `--cancel-file`; the operation ends its engine and stops.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core import operation_model as model  # noqa: E402
from system_core.core.abilities import abilities  # noqa: E402
from system_core.core import lines  # noqa: E402
from system_core.core import window_layout  # noqa: E402
from system_core.core.ansi import strip_ansi  # noqa: E402
from system_core.core.jobs import execute_operation  # noqa: E402
from system_core.core.manifest import load_manifest  # noqa: E402
from system_core.core.paths import ensure_project_dirs, get_project_paths, routes_cross  # noqa: E402

CONTROL = "::image::"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_STOPPED = 0, 1, 2, 130

# Nobody reads the output any more - the caller closed its end of the pipe. The operation goes on
# without it: its own journal file is written all the same.
_nobody_listens = False
_colours = False


def say(line: str) -> None:
    global _nobody_listens
    if _nobody_listens:
        return
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        _nobody_listens = True


def control(payload: dict[str, Any]) -> None:
    say(CONTROL + json.dumps(payload, ensure_ascii=False, default=str))


def usage_error(message: str) -> int:
    try:
        print("[ERR] " + message, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass
    return EXIT_USAGE


# --- how far the engine is -------------------------------------------------------------------

# "Processing:  42%|####2     | 5/12 [00:00<00:00,  9.28file/s]" - a bar of tqdm, redrawn in place.
BAR = re.compile(r"^(?P<name>[^|%]*?):?\s*(?P<share>\d{1,3})%\|.*?\|\s*(?P<done>\d+)/(?P<all>\d+)\s*\[[^\]<]*<(?P<left>[^,\]]*),\s*(?P<rate>[^\]]*)\]")
# "Run 2/3": an operation that runs the engine once for every format ticked.
RUN = re.compile(r"^Run (?P<now>\d+)/(?P<all>\d+)$")


class Progress:
    """The share of an operation done: the steps its service names, until the engine counts its files."""

    def __init__(self, live: bool) -> None:
        self.live, self.run, self.runs, self.counted, self.told = live, 1, 1, False, -1.0
        # The file the engine finished last, and the measures of its bar: the live line names both.
        self.current, self.measures, self.said, self.when = "", "", "", 0.0
        # When the first file of a batch was done, and which it was: the speed is counted from it,
        # not from the start of the command - the engine takes its second to start.
        self.first: tuple[float, int] | None = None

    def activity(self, text: str, last: bool = False) -> None:
        """The live line, said at most ten times a second: a thousand small files are a thousand lines a second."""
        now = time.monotonic()
        if text == self.said or (not last and now - self.when < 0.1):
            return
        self.said, self.when = text, now
        control({"activity": text})

    def item(self, at: int, of: int, name: str) -> None:
        """A file of the batch went as asked (core\\lines.py): the live line moves on to it."""
        self.current = name
        if self.counted:
            # The bar of the engine counts the work; the file is named after its measures.
            self.activity(f"{self.measures} · {name}", at == of)
            return
        self.share(((self.run - 1) + at / of) / self.runs)
        # No bar to read the speed and the time left from: counted over the files done since the first.
        now = time.monotonic()
        if self.first is None or at <= self.first[1]:
            self.first = (now, at)
        measures = [f"{round(100 * at / of)}%", f"{at} / {of}"]
        since, first = now - self.first[0], self.first[1]
        if at > first and since > 0:
            speed = (at - first) / since
            measures.append(f"{speed:.2f} file/s")
            if at < of:
                measures.append("ETA " + clock((of - at) / speed))
        self.activity("Processing: " + " · ".join(measures) + f" · {name}", at == of)

    def share(self, value: float) -> None:
        """The share done, told once and never taken back: a bar of the engine starts from nought again."""
        value = round(max(0.0, min(1.0, float(value))), 4)
        if value > self.told:
            self.told = value
            control({"progress": value})

    def step(self, value: float) -> None:
        # The steps of a service are guesses (5 %, 10 %, 75 %): they are told until a real count comes.
        if not self.counted or float(value) >= 1.0:
            self.share(value)

    def line(self, text: str) -> bool:
        """A line of the journal read for what it says of the work done; True - it was a bar, and is told as progress."""
        plain = strip_ansi(text).strip()
        several = RUN.match(plain)
        if several:
            self.run, self.runs = int(several["now"]), max(1, int(several["all"]))
            return False
        bar = BAR.match(plain)
        if not bar or not self.live:
            return False
        self.counted = True
        share = min(100, int(bar["share"])) / 100
        self.share(((self.run - 1) + share) / self.runs)
        # "9.28file/s" - the speed and its unit apart; "?file/s" of the first frame is no speed yet.
        speed = re.match(r"^\s*(\d[\d.,]*)\s*(\S+)", bar["rate"])
        measures = [f"{bar['share']}%", f"{bar['done']} / {bar['all']}"] + ([f"{speed[1]} {speed[2]}"] if speed else [])
        # "00:03" left; "?" of the first frame is no time yet, and a bar at its end has none left.
        if re.match(r"^\d+(:\d\d)+$", bar["left"].strip()) and bar["done"] != bar["all"]:
            measures.append("ETA " + bar["left"].strip())
        self.measures = f"{bar['name'].strip() or 'Processing'}: " + " · ".join(measures)
        self.activity(self.measures + (f" · {self.current}" if self.current else ""), bar["done"] == bar["all"])
        return True


def clock(seconds: float) -> str:
    """The time left as tqdm writes it: 01:05, or 1:02:05 past an hour."""
    whole = max(0, int(round(seconds)))
    hours, rest = divmod(whole, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60:02d}:{rest % 60:02d}"


class Journal:
    """What of the engine's lines a live caller gets as lines (`--live`: the window).

    A batch is told in the live line, not in a line for every file. The line of a file that went as
    asked (core\\lines.py: "[OK 3/10] d02.docx: done") moves the live line on; what became of the
    file, indented under its line, stays in the log file of the operation. A file that went wrong is
    said in full. A summary the engine prints as JSON comes as one line; a line said again and again
    comes once, with how many times more; the parameters of the operation - its command line names
    them - stay in the log file. A console and a caller without --live get every line as before.
    """

    def __init__(self, progress: Progress, tell: Any) -> None:
        self.progress, self.tell = progress, tell
        self.folding = False
        self.json: list[str] | None = None
        self.last, self.again = "", 0

    def line(self, text: str) -> None:
        plain = strip_ansi(text).rstrip()
        if self.json is not None:
            self.json.append(text)
            if plain == "}":
                self._json_end()
            elif len(self.json) > 500:  # no summary is that long: it was no summary
                self._json_end(raw=True)
            return
        if plain == "{":
            self._again_end()
            self.folding, self.json = False, [text]
            return
        if plain.startswith("Parameters: {"):
            return
        found = lines.ITEM.match(plain)
        if found:
            of = int(found["of"] or 0)
            if found["status"] in lines.QUIET and of > 1:
                self._again_end()
                self.folding = True
                self.progress.item(int(found["at"]), of, found["name"])
                return
            self.folding = False
        elif self.folding and plain[:1] in (" ", "\t"):
            return
        else:
            self.folding = False
        if plain and plain == self.last:
            self.again += 1
            return
        self._again_end()
        self.last = plain
        self.tell(text)

    def close(self) -> None:
        if self.json is not None:
            self._json_end(raw=True)
        self._again_end()

    def _again_end(self) -> None:
        if self.again:
            self.tell(lines.detail(f"(the line above, {self.again} more {'time' if self.again == 1 else 'times'})"))
        self.last, self.again = "", 0

    def _json_end(self, raw: bool = False) -> None:
        block, self.json = self.json or [], None
        try:
            data = None if raw else json.loads("\n".join(strip_ansi(part) for part in block))
        except ValueError:
            data = None
        if not isinstance(data, dict):
            for part in block:
                self.tell(part)
            return
        self.tell(summary_line(data))


def summary_line(data: dict[str, Any]) -> str:
    """The summary of the engine in one line: "processed 40 · mode percent-50 · sheets 4"."""
    parts = []
    for key, value in data.items():
        if isinstance(value, dict):
            continue
        if isinstance(value, list):
            value = value[0] if len(value) == 1 and not isinstance(value[0], (dict, list)) else len(value)
        if isinstance(value, bool):
            value = "yes" if value else "no"
        parts.append(lines.paint(str(key).replace("_", " "), "muted") + " " + str(value))
    return lines.paint(" · ", "muted").join(parts)


# --- the project -----------------------------------------------------------------------------


def project(root: str | None):
    paths = get_project_paths(Path(root).resolve() if root else ROOT)
    manifest = paths.config / "tool_manifest.yaml"
    if not manifest.is_file():
        raise ValueError(f"not a project folder, no manifest: {manifest}")
    try:
        return paths, load_manifest(manifest)
    except Exception as error:  # noqa: BLE001 - whatever the manifest stumbles over, nothing was run
        raise ValueError(f"the manifest does not read: {manifest}: {error}") from error


def project_version(paths) -> str:
    try:
        return str(json.loads((paths.config / "version.json").read_text(encoding="utf-8")).get("version", ""))
    except (OSError, ValueError):
        return ""


def language_of(args: argparse.Namespace, paths) -> str:
    """The language named by the caller; without it - the one chosen in the window, English when none was."""
    if getattr(args, "language", ""):
        return model.safe_language(args.language)
    try:
        chosen = json.loads((paths.config / "window_settings.json").read_text(encoding="utf-8-sig")).get("Lang", "")
    except (OSError, ValueError, AttributeError):  # settings that do not read are no reason to refuse a run
        chosen = ""
    return model.safe_language(str(chosen))


def command_describe(args: argparse.Namespace) -> int:
    paths, manifest = project(args.root)
    payload = model.describe(manifest)
    payload["version"] = project_version(paths)
    payload["language"] = language_of(args, paths)
    # Where every operation stands in the window: its sections and the rows of each.
    payload["layout"] = window_layout.for_window(window_layout.load(paths.config), manifest)
    # What the engine can do on this machine: the badges of the header (system_core\core\abilities.py).
    payload["abilities"] = abilities()
    payload["paths"] = {"root": str(paths.root), "input": str(paths.input), "output": str(paths.output),
                        "logs": str(paths.logs), "report": str(paths.report), "config": str(paths.config),
                        "workspace": str(paths.workspace)}
    say(json.dumps(payload, ensure_ascii=False, default=str))
    return EXIT_OK


def command_version(args: argparse.Namespace) -> int:
    paths, _manifest = project(args.root)
    say(project_version(paths))
    return EXIT_OK


def read_values(args: argparse.Namespace, node) -> dict[str, Any]:
    """The values of the fields: the file of `--params`, over it every `--set name=value`."""
    values: dict[str, Any] = {}
    if args.params:
        loaded = json.loads(Path(args.params).read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, dict):
            raise ValueError("--params: a JSON object \"field name: value\" is expected")
        values.update(loaded)
    fields = {model.field_id(field): field for field in node.fields if model.field_id(field)}
    for item in args.set or []:
        name, separator, text = item.partition("=")
        name = name.strip()
        if not separator or not name:
            raise ValueError(f"--set: name=value is expected, got {item!r}")
        if name not in fields:
            raise ValueError(f"--set: the operation has no field {name!r}")
        if model.is_route_field(fields[name]):
            raise ValueError(f"--set {name}: the folders are named with --source and --target")
        try:
            values[name] = model.coerce(fields[name], text)
        except ValueError as error:
            raise ValueError(f"--set {name}: {error}") from error
    return values


def write_result(path: str, payload: dict[str, Any]) -> str:
    """The outcome into its file, whole or not at all; the reason when it could not be written."""
    if not path:
        return ""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        draft = target.with_name(target.name + ".tmp")
        draft.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        draft.replace(target)
        return ""
    except OSError as error:
        return str(error)


def expand_percent(text: str) -> str:
    """`%NAME%` of the environment and nothing else: a folder may be called `$TEMP`."""
    return re.sub(r"%([^%\\/:*?\"<>|]+)%", lambda found: os.environ.get(found.group(1), found.group(0)), text)


def workbench_path(text: str, fallback: Path, root: Path) -> Path:
    """Source or Target as named by the caller; a relative one is counted from the project folder."""
    if not text:
        return fallback
    cleaned = text.strip().strip('"').strip()
    if '"' in cleaned:
        # `"E:\My Files\" --target D:\Out` reaches a program as one argument with a quote
        # inside: the backslash before the closing quote glued the next key to the path.
        raise ValueError(f"a quotation mark inside a path - was the path quoted with a backslash at its end? {text!r}")
    path = Path(expand_percent(cleaned)).expanduser()
    return path if path.is_absolute() else root / path


def own_file(text: str) -> str:
    """A file of the caller - the values, the outcome, the stop signal - as a full path, counted from where it called."""
    return str(Path(text).expanduser().resolve()) if text else ""


def with_parameters(node, parameters: dict[str, Any]):
    return node.to_operation(parameters) if hasattr(node, "to_operation") else dataclasses.replace(node, parameters=parameters)


def command_run(args: argparse.Namespace) -> int:
    global _colours
    _colours = bool(args.colours)
    paths, manifest = project(args.root)
    node = model.find_node(manifest, args.operation)
    if node is None:
        return usage_error(f"the manifest has no operation {args.operation!r}")
    if node.kind == "dangerous":
        # It deletes for good. The window clears the working folders itself, through the Recycle Bin.
        return usage_error(f"{args.operation!r} deletes for good and is not run from here")
    language = language_of(args, paths)
    # Before the command moves to the project folder: these three are counted from the caller's.
    args.params, args.result, args.cancel_file = own_file(args.params), own_file(args.result), own_file(args.cancel_file)
    try:
        given = read_values(args, node)
        source = workbench_path(args.source, paths.input, paths.root)
        target = workbench_path(args.target, paths.output, paths.root)
    except (OSError, ValueError) as error:
        return usage_error(str(error))
    unknown = model.unknown_values(node, given)
    if unknown:
        return usage_error("the operation has no fields: " + ", ".join(unknown))
    values = model.form_values(node, given)
    wrong = model.wrong_choices(node, values, language)
    if wrong:
        return usage_error("; ".join(wrong))
    refused = model.refusal(node, values, language)
    if refused:
        return usage_error(refused)
    # An operation that reads the Source and writes the Target: the two must not hold each other.
    routes = {model.is_target_field(field) for field in node.fields if model.is_route_field(field)}
    if routes == {True, False} and (crossing := routes_cross(source, target)):
        return usage_error(crossing)

    ensure_project_dirs(paths)
    # Where the services have always been run from: the program folder.
    os.chdir(paths.root)
    cancel_file = Path(args.cancel_file) if args.cancel_file else None
    progress = Progress(bool(args.live))
    # The lines this process writes itself - around the engine - are coloured for a caller that shows colours.
    lines.wanted(_colours or lines.colours())

    def said(text: str) -> None:
        say(text if _colours or sys.stdout.isatty() else strip_ansi(text))

    journal = Journal(progress, said) if args.live else None

    def tell(line: str) -> None:
        """A line of the journal: a bar of the engine becomes progress; a live caller gets a batch folded (Journal)."""
        text = str(line)
        if progress.line(text):
            return
        if journal is not None:
            journal.line(text)
        else:
            said(text)

    operation = with_parameters(node, model.build_parameters(node, values, source, target))

    control({"started": {"operation": operation.id, "source": str(source), "target": str(target)}})
    began = time.monotonic()
    # The services read the two folders from the parameters; logs and reports stay the program's.
    result = execute_operation(paths, operation, tell, progress.step,
                               (lambda: cancel_file.exists()) if cancel_file is not None else None)
    if journal is not None:
        journal.close()
    # The services end their engine when asked to stop and report the run as failed: with the
    # signal there and no success, that is a stop. A success is a success whatever lies there.
    stopped = bool(not result.ok and cancel_file is not None and cancel_file.exists())
    outcome = "stopped" if stopped else "done" if result.ok else "failed"
    seconds = round(time.monotonic() - began, 1)
    trouble = write_result(args.result, {"operation": operation.id, "outcome": outcome, "ok": result.ok,
                                         "message": result.message, "data": result.data,
                                         "source": str(source), "target": str(target), "seconds": seconds})
    if trouble:
        say(f"[WARN] The outcome could not be written to {args.result}: {trouble}")
    control({"finished": {"outcome": outcome, "message": result.message, "seconds": seconds}})
    return EXIT_STOPPED if stopped else EXIT_OK if result.ok else EXIT_FAILED


def _engine_inside(paths):
    """system_core\\main.py in this process: a command line in, its exit code and everything it said out."""
    import contextlib
    import importlib
    import io

    folder = str(paths.system_core)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    engine = importlib.import_module("main")

    def run(words: list[str]) -> tuple[int, str]:
        said = io.StringIO()
        with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said):
            try:
                parsed = engine.build_parser().parse_args(words)
                code = int(parsed.func(parsed) or 0)
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else 2
            except Exception as error:
                print(f"[ERR] {type(error).__name__}: {error}")
                code = 1
        return code, said.getvalue()

    return run


PREVIEW_SIDE = 1200
# Operations whose result has the size the form sets, whatever the size of the picture: on the copy they make the
# same pixels as on the picture itself - their size at full scale is not the size on the copy over the factor.
PREVIEW_SIZE_SET_BY_FORM = {"exact_size", "resize_screen", "aspect_fit"}
PREVIEW_PICTURES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif", ".avif", ".heic", ".heif"}


def command_preview(args: argparse.Namespace) -> int:
    """
    What an operation makes of one picture, seen before it is run on all: the same command line of
    the engine, run on a copy of the picture made smaller (its long side PREVIEW_SIDE at most, its
    density made smaller as much - millimetres stay millimetres). Nothing of the project is
    written: the copy, the result and the logs of the engine stay in --out. The answer is one
    service line {"preview": {...}}: the copy, the pictures made of it, the sizes at full scale.
    """
    import shutil

    from PIL import ImageOps

    from system_core.image_tools.io_utils import open_image
    from system_core.services.image_tools_gui import _manifest_cli_runs

    def answer(payload: dict[str, Any]) -> int:
        control({"preview": payload})
        return EXIT_OK if "error" not in payload else EXIT_FAILED

    paths, manifest = project(args.root)
    node = model.find_node(manifest, args.operation)
    if node is None:
        return usage_error(f"the manifest has no operation {args.operation!r}")
    if not str(node.service).endswith(":run_manifest_cli"):
        return answer({"error": "no preview for this operation"})
    args.params, args.out = own_file(args.params), own_file(args.out)
    language = language_of(args, paths)
    try:
        values = model.form_values(node, read_values(args, node))
    except (OSError, ValueError) as error:
        return answer({"error": str(error)})
    refused = model.refusal(node, values, language)
    if refused:
        return answer({"error": refused})
    began = time.monotonic()
    picture, out = Path(args.file), Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    before_dir, after_dir = out / "before", out / "after"
    before_dir.mkdir(parents=True, exist_ok=True)
    after_dir.mkdir(parents=True, exist_ok=True)
    try:
        image = ImageOps.exif_transpose(open_image(picture))
    except Exception as error:
        return answer({"error": f"{picture.name}: {type(error).__name__}: {error}"})
    side = max(1, int(args.side))
    factor = min(1.0, side / max(image.size))
    copy = image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))), resample=3) if factor < 1 else image
    dpi = image.info.get("dpi")
    if copy.mode not in ("RGB", "RGBA", "L", "LA", "P", "I;16"):
        copy = copy.convert("RGBA" if "A" in copy.mode else "RGB")
    before = before_dir / f"{picture.stem}.png"
    copy.save(before, "PNG", compress_level=1, **({"dpi": (float(dpi[0]) * factor, float(dpi[1]) * factor)} if dpi else {}))

    operation = with_parameters(node, model.build_parameters(node, values, before, after_dir))
    said: list[str] = []
    # The engine in this process: the same command line, read by its own parser - a second Python would cost a second.
    os.chdir(paths.root)
    engine = _engine_inside(paths)
    for words, _values in _manifest_cli_runs(paths.root, operation):
        # [python, main.py, command, ...]: what follows the script is the command line of the engine.
        code, text = engine([*words[2:], "--log-dir", str(out / "logs")])
        said.extend(line for line in text.splitlines() if line.strip())
        if code != 0:
            return answer({"error": next((line for line in reversed(said) if "[ERR]" in line or "rror" in line), f"exit code {code}")})
    made = sorted(path for path in after_dir.rglob("*") if path.suffix.lower() in PREVIEW_PICTURES)
    if not made:
        return answer({"error": "the operation made no picture of the copy"})
    after = []
    for path in made[:16]:
        try:
            from PIL import Image

            with Image.open(path) as result:
                size = result.size
        except Exception:
            continue
        full = list(size) if node.id in PREVIEW_SIZE_SET_BY_FORM else [round(size[0] / factor), round(size[1] / factor)]
        after.append({"path": str(path), "pixels": list(size), "full_pixels": full})
    return answer({"before": str(before), "pixels": list(image.size), "dpi": [round(float(value), 1) for value in dpi] if dpi else None,
                   "factor": round(factor, 6), "after": after, "made": len(made), "seconds": round(time.monotonic() - began, 2)})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="image_cli", description="Audion Image Tools: the console command.")
    parser.add_argument("--root", default="", help="The project folder; this one when not named.")
    parser.add_argument("--language", default="", help="en or ru; the language of the window when not named")
    commands = parser.add_subparsers(dest="command", required=True)

    describe = commands.add_parser("describe", help="The sections, operations and fields as one line of JSON")
    describe.add_argument("--language", default=argparse.SUPPRESS)
    describe.set_defaults(func=command_describe)

    run = commands.add_parser("run", help="Run an operation of the manifest")
    run.add_argument("--operation", required=True)
    run.add_argument("--source", default="", help="A folder or one file; `input` of the program when not named")
    run.add_argument("--target", default="", help="A folder; `output` of the program when not named")
    run.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    run.add_argument("--params", default="", help="A JSON file \"field name: value\"")
    run.add_argument("--result", default="", help="A file the outcome is written to")
    run.add_argument("--cancel-file", default="", help="A file whose appearance stops the operation")
    run.add_argument("--language", default=argparse.SUPPRESS)
    run.add_argument("--live", action="store_true", help="Tell the progress of the engine as service lines, not as its bar")
    run.add_argument("--colours", action="store_true", help="Leave the colour codes in the lines")
    run.set_defaults(func=command_run)

    preview = commands.add_parser("preview", help="What an operation makes of one picture, on a copy made smaller")
    preview.add_argument("--operation", required=True)
    preview.add_argument("--file", required=True, help="The picture to see")
    preview.add_argument("--out", required=True, help="A folder of the caller: the copy, the result, the logs of the engine")
    preview.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    preview.add_argument("--params", default="", help="A JSON file \"field name: value\"")
    preview.add_argument("--side", type=int, default=PREVIEW_SIDE, help="The long side of the copy, px")
    preview.add_argument("--language", default=argparse.SUPPRESS)
    preview.set_defaults(func=command_preview)

    commands.add_parser("version", help="The version number").set_defaults(func=command_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as stop:
        return EXIT_OK if stop.code in (0, None) else EXIT_USAGE
    try:
        return args.func(args)
    except ValueError as error:
        return usage_error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
