"""The lines the engine writes: their colours, and the line of one file of many.

A console and the window show what the engine says in colours; a log file and a pipe take the
text alone (core\\logging_utils.py; system_core\\cli.py without --colours). The colours are the
eight of every console, named here by what they mean, so that any console - and every theme of
the window, which draws the eight in its own tones (Source\\Core\\Ansi.cs) - shows them readably.

The line of one file of many, and what became of it under it, indented:

    [OK 3/10] d02.docx: done
        checked: the copy is a whole ZIP package

The door folds the lines of a batch into the live line of the window (system_core\\cli.py,
`--live`): its journal keeps the files that went wrong, a console and a log file get every line.
Until 3.0.0 a batch of ten documents wrote some four hundred lines into the terminal of the window.
"""
from __future__ import annotations

import os
import re
import sys

TONES = {"ok": "32", "warn": "33", "bad": "31", "info": "36", "head": "1;36", "muted": "90", "accent": "34"}
# The word of the line of one file - what became of it - and the tone it is written in.
STATUS_TONES = {"OK": "ok", "INFO": "info", "SKIP": "warn", "WARN": "warn", "ERR": "bad", "ERROR": "bad", "FAIL": "bad"}
# The words of a file that went as asked: folded in a batch. The rest stay in the journal of the window.
QUIET = ("OK", "INFO")
# "[OK 3/10] d02.docx: done" - the word, where in the batch, the name, what became of it.
ITEM = re.compile(r"^\[(?P<status>OK|INFO|SKIP|WARN|ERR|ERROR|FAIL)(?: (?P<at>\d+)/(?P<of>\d+))?\] (?P<name>.+?)(?:: (?P<note>.*))?$")

_wanted: bool | None = None


def colours() -> bool:
    """True when somebody shows the colours: a console, or a caller that asked (FORCE_COLOR: core\\jobs.py sets it)."""
    global _wanted
    if _wanted is None:
        _wanted = _decide()
    return _wanted


def wanted(on: bool) -> None:
    """The caller says it shows the colours, or does not: the door, asked with `run --colours`."""
    global _wanted
    _wanted = bool(on)


def _decide() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"):
        return True
    try:
        if not sys.stdout.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    return _console_reads_colours()


def _console_reads_colours() -> bool:
    if os.name != "nt":
        return True
    # A console of Windows reads the codes once it is asked to (ENABLE_VIRTUAL_TERMINAL_PROCESSING);
    # one that cannot is given the text alone, not the codes as text.
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(mode.value & 4 or kernel.SetConsoleMode(handle, mode.value | 4))
    except Exception:  # noqa: BLE001 - no console to ask is a console without colours
        return False


def paint(text: str, tone: str) -> str:
    """The text in the colour of its meaning, where colours are shown; the text alone elsewhere."""
    text = str(text)
    if not text or not colours():
        return text
    return f"\x1b[{TONES[tone]}m{text}\x1b[0m"


def item(status: str, name: str, note: str = "", at: int | None = None, of: int | None = None) -> str:
    """The line of one file of many: "[OK 3/10] d02.docx: done"."""
    where = f" {at}/{of}" if of else ""
    line = paint(f"[{status}{where}]", STATUS_TONES[status]) + " " + str(name)
    return line + (": " + str(note) if note else "")


def detail(text: str, tone: str = "muted", indent: int = 4) -> str:
    """A line of what became of the file above it: indented, and quiet unless it says something went wrong."""
    return " " * indent + paint(str(text), tone)


def details(block: str, indent: int = 4) -> list[str]:
    """A report of several lines put under the line of its file, its empty lines left out."""
    return [detail(line, indent=indent) for line in str(block).splitlines() if line.strip()]


def tally(done: int, total: int, rest: str) -> str:
    """"4 of 4 documents done...": the count green when every one went, amber when not."""
    return paint(f"{done} of {total}", "ok" if done == total else "warn") + " " + str(rest)
