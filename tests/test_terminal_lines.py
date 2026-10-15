"""The lines of the terminal: the colours of the engine, the line of one file of many, a batch folded.

The owner, 14.10.2026: "processes over many pictures must not make a ten-storey log of the
terminal - it can be laid into one line with colour accents"; and "the count, the ETA and the rest -
in different accents". The engine writes the line of every file in one form (system_core\\core\\lines.py);
the door folds a batch into its live line for the window (system_core\\cli.py, `--live`).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from system_core import cli
from system_core.core import lines
from system_core.core.ansi import strip_ansi


@pytest.fixture()
def plain():
    lines.wanted(False)
    yield
    lines.wanted(False)


def test_the_line_of_one_file_of_many(plain) -> None:
    assert lines.item("OK", "d02.docx", "done", 3, 10) == "[OK 3/10] d02.docx: done"
    assert lines.item("WARN", "scan.tiff", "passed by") == "[WARN] scan.tiff: passed by"
    assert lines.detail("checked: the copy reads") == "    checked: the copy reads"
    assert lines.tally(4, 4, "documents done") == "4 of 4 documents done"
    found = lines.ITEM.match("[OK 3/10] d02.docx: done")
    assert (found["status"], found["at"], found["of"], found["name"], found["note"]) == ("OK", "3", "10", "d02.docx", "done")


def test_the_colours_are_the_eight_of_a_console_and_a_log_file_takes_the_text() -> None:
    try:
        lines.wanted(True)
        line = lines.item("ERR", "a.jpg", "broken", 1, 2)
        assert line == "\x1b[31m[ERR 1/2]\x1b[0m a.jpg: broken"
        assert strip_ansi(line) == "[ERR 1/2] a.jpg: broken"
        assert lines.ITEM.match(strip_ansi(line))
        assert lines.tally(3, 4, "x").startswith("\x1b[33m3 of 4\x1b[0m")
    finally:
        lines.wanted(False)


class Live:
    """A Progress that only remembers what it was told."""

    def __init__(self) -> None:
        self.items: list[tuple[int, int, str]] = []

    def item(self, at: int, of: int, name: str) -> None:
        self.items.append((at, of, name))


def test_a_batch_is_folded_and_what_went_wrong_stays(plain) -> None:
    live, told = Live(), []
    journal = cli.Journal(live, told.append)
    for line in [
        "Parameters: {\"to\": \"jpg\"}",
        "Command:",
        "[OK 1/3] a.docx: done",
        "    checked: the copy reads",
        "[WARN 2/3] b.docx: partial - one picture stayed",
        "    [WARN] not held: the size",
        "[OK 3/3] c.docx: done",
        "    checked: the copy reads",
        "{",
        "  \"processed\": 3,",
        "  \"unsharp\": true,",
        "  \"outputs\": [",
        "    \"x.pdf\"",
        "  ],",
        "  \"sheets\": [{\"a\": 1}, {\"a\": 2}],",
        "  \"nested\": {\"a\": 1}",
        "}",
        "Image contains an alpha channel.",
        "Image contains an alpha channel.",
        "Image contains an alpha channel.",
        "2 of 3 documents done and checked",
    ]:
        journal.line(line)
    journal.close()
    assert live.items == [(1, 3, "a.docx"), (3, 3, "c.docx")]
    assert told == [
        "Command:",
        "[WARN 2/3] b.docx: partial - one picture stayed",
        "    [WARN] not held: the size",
        "processed 3 · unsharp yes · outputs x.pdf · sheets 2",
        "Image contains an alpha channel.",
        "    (the line above, 2 more times)",
        "2 of 3 documents done and checked",
    ]


def test_one_file_alone_is_said_in_full(plain) -> None:
    live, told = Live(), []
    journal = cli.Journal(live, told.append)
    for line in ["[OK 1/1] merged.pdf: done", "    checked: pages", "[OK] other.pdf: done", "    checked: text"]:
        journal.line(line)
    journal.close()
    assert live.items == [] and len(told) == 4


def test_a_summary_that_does_not_read_comes_as_it_was(plain) -> None:
    told = []
    journal = cli.Journal(Live(), told.append)
    for line in ["{", "  not json", "}"]:
        journal.line(line)
    journal.close()
    assert told == ["{", "  not json", "}"]


def test_the_live_line_tells_the_speed_and_the_time_left(monkeypatch: pytest.MonkeyPatch, plain) -> None:
    now = [100.0]
    said: list[dict] = []
    monkeypatch.setattr(cli, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(cli, "control", said.append)
    progress = cli.Progress(True)
    progress.item(1, 10, "a.jpg")
    now[0] = 104.0
    progress.item(5, 10, "e.jpg")
    now[0] = 109.0
    progress.item(10, 10, "j.jpg")
    pulses = [line["activity"] for line in said if "activity" in line]
    # Counted from the first file done, not from the start of the engine.
    assert pulses == ["Processing: 10% · 1 / 10 · a.jpg",
                      "Processing: 50% · 5 / 10 · 1.00 file/s · ETA 00:05 · e.jpg",
                      "Processing: 100% · 10 / 10 · 1.00 file/s · j.jpg"]
    assert cli.clock(65) == "01:05" and cli.clock(3725) == "1:02:05"


def test_the_bar_of_the_engine_gives_the_time_left_and_the_file(monkeypatch: pytest.MonkeyPatch, plain) -> None:
    now = [100.0]
    said: list[dict] = []
    monkeypatch.setattr(cli, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(cli, "control", said.append)
    progress = cli.Progress(True)
    assert progress.line("Processing:  42%|####2     | 5/12 [00:01<00:02,  9.28file/s]")
    now[0] = 100.5
    progress.item(5, 12, "e.jpg")
    pulses = [line["activity"] for line in said if "activity" in line]
    assert pulses[0] == "Processing: 42% · 5 / 12 · 9.28 file/s · ETA 00:02"
    assert pulses[-1] == "Processing: 42% · 5 / 12 · 9.28 file/s · ETA 00:02 · e.jpg"
