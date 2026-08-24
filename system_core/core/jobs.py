from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import importlib
import json
import locale
import os
import subprocess
import traceback

from .logging_utils import append_log, timestamp
from .manifest import Operation
from .output_decode import decode_process_bytes
from .paths import ProjectPaths


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]
CancelCallback = Callable[[], bool]


@dataclass
class JobContext:
    paths: ProjectPaths
    operation: Operation
    log_file: Path
    report_dir: Path
    log_callback: LogCallback | None = None
    progress_callback: ProgressCallback | None = None
    cancel_callback: CancelCallback | None = None

    def log(self, message: str) -> None:
        append_log(self.log_file, message)
        if self.log_callback:
            try:
                self.log_callback(message)
            except UnicodeEncodeError:
                self.log_callback(message.encode("ascii", errors="replace").decode("ascii"))

    def progress(self, value: float) -> None:
        if self.progress_callback:
            self.progress_callback(max(0.0, min(1.0, float(value))))

    def cancelled(self) -> bool:
        return bool(self.cancel_callback and self.cancel_callback())


@dataclass
class JobResult:
    ok: bool
    message: str
    data: dict[str, Any]


class UserFacingError(RuntimeError):
    """Expected validation problem that should be shown to the user without a traceback."""

    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.data = data or {}


def utf8_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if extra:
        env.update(extra)
    env.setdefault("PYTHONUTF8", "1")
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.pop("NO_COLOR", None)
    if env.get("CLICOLOR") == "0":
        env.pop("CLICOLOR", None)
    env.setdefault("CLICOLOR", "1")
    env.setdefault("CLICOLOR_FORCE", "1")
    env.setdefault("FORCE_COLOR", "1")
    env.setdefault("AUDION_GUI_TERMINAL", "1")
    return env


PYTHON_EXECUTABLE_NAMES = {"python", "python.exe", "python3", "python3.exe", "pythonw.exe", "py", "py.exe"}


def is_python_command(command: list[str]) -> bool:
    if not command:
        return False
    return Path(command[0]).name.lower() in PYTHON_EXECUTABLE_NAMES


def unbuffer_python_command(command: list[str]) -> list[str]:
    if len(command) < 2:
        return list(command)
    if not is_python_command(command):
        return list(command)
    if command[1] == "-u":
        return list(command)
    return [command[0], "-u", *command[1:]]


def windows_oem_encoding() -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        code_page = int(ctypes.windll.kernel32.GetOEMCP())
    except Exception:
        return None
    return f"cp{code_page}" if code_page else None


def output_decodings() -> list[str]:
    candidates = [
        windows_oem_encoding(),
        "cp866" if os.name == "nt" else None,
        locale.getencoding() if hasattr(locale, "getencoding") else locale.getpreferredencoding(False),
        "mbcs" if os.name == "nt" else None,
        "cp1251" if os.name == "nt" else None,
    ]
    seen: set[str] = set()
    result: list[str] = []
    for item in candidates:
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _decode_utf16ish(raw_line: bytes, encoding: str) -> str | None:
    data = raw_line
    if encoding == "utf-16-le" and data.startswith(b"\x00") and len(data) > 1:
        data = data[1:]
    elif encoding == "utf-16-be" and data.endswith(b"\x00") and len(data) > 1:
        data = data[:-1]
    if len(data) % 2:
        data = data + b"\x00" if encoding == "utf-16-le" else b"\x00" + data
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        try:
            return data.decode(encoding, errors="replace")
        except Exception:
            return None


def decode_process_line(raw_line: bytes) -> str:
    return decode_process_bytes(raw_line)


SPINNER_FRAME_CHARS = set("-\\|/ \t")


def _is_spinner_only_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and all(char in SPINNER_FRAME_CHARS for char in line)


def decoded_process_lines(raw_line: bytes | str) -> list[str]:
    text = str(raw_line) if isinstance(raw_line, str) else decode_process_bytes(raw_line)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for part in text.split("\n"):
        line = part.rstrip()
        if not line or _is_spinner_only_line(line):
            continue
        lines.append(line)
    return lines


def hidden_subprocess_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def hidden_subprocess_creationflags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def hidden_subprocess_kwargs() -> dict[str, Any]:
    return {
        "startupinfo": hidden_subprocess_startupinfo(),
        "creationflags": hidden_subprocess_creationflags(),
    }


def _load_callable(service: str) -> Callable[[JobContext], Any]:
    module_name, function_name = service.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def execute_operation(
    paths: ProjectPaths,
    operation: Operation,
    log_callback: LogCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> JobResult:
    run_stamp = timestamp().replace(":", "-")
    log_file = paths.logs / f"{run_stamp}_{operation.id}.log"
    report_dir = paths.report / f"{run_stamp}_{operation.id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    context = JobContext(paths, operation, log_file, report_dir, log_callback, progress_callback, cancel_callback)

    try:
        context.log(f"Starting operation: {operation.id}")
        if operation.parameters:
            context.log(f"Parameters: {json.dumps(operation.parameters, ensure_ascii=False, sort_keys=True)}")
        context.progress(0.0)
        result = _load_callable(operation.service)(context)
        context.progress(1.0)
        context.log(f"Finished operation: {operation.id}")

        if isinstance(result, dict):
            return JobResult(True, "Operation finished.", result)
        return JobResult(True, str(result or "Operation finished."), {})

    except UserFacingError as exc:
        context.progress(1.0)
        context.log(f"Operation stopped: {exc}")
        return JobResult(False, str(exc), dict(exc.data))

    except Exception as exc:
        context.log(traceback.format_exc())
        return JobResult(False, f"{exc.__class__.__name__}: {exc}", {})
