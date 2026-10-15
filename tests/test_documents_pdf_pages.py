"""The pages of PDF: turned, put together, parted, the properties taken away - nothing drawn anew.

Every result is held by the checks the operation itself makes; here they have to pass, and the result
is read again from outside: the turn of each page, the order of the pages by their text, the properties.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pikepdf
import pymupdf
import pytest

from system_core.documents.pdf_pages import clean_meta, merge, parse_pages, rotate_pages, split

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "system_core" / "main.py"


def make_pages(path: Path, count: int, word: str = "page") -> Path:
    """A PDF of `count` pages, each saying its own number - the order of pages is read by it."""
    doc = pymupdf.open()
    for number in range(1, count + 1):
        doc.new_page(width=595, height=842).insert_text((72, 100), f"{word} {number}")
    doc.set_metadata({"author": "Someone", "title": "A title", "creator": "A program"})
    doc.save(path)
    doc.close()
    return path


def _texts(path: Path) -> list[str]:
    with pymupdf.open(path) as doc:
        return [page.get_text().strip() for page in doc]


def _all_held(outcome) -> None:
    failed = [text for ok, text in outcome.checks if not ok]
    assert outcome.status == "done" and not failed, (outcome.status, outcome.reason, failed)


def test_the_pages_asked_for(tmp_path: Path) -> None:
    assert parse_pages("", 4) == [1, 2, 3, 4]
    assert parse_pages("1-2, 4", 5) == [1, 2, 4]
    assert parse_pages("3-", 5) == [3, 4, 5]
    assert parse_pages("2 4", 5) == [2, 4]
    with pytest.raises(ValueError):
        parse_pages("6", 5)
    with pytest.raises(ValueError):
        parse_pages("a", 5)


def test_only_the_pages_asked_for_are_turned(tmp_path: Path) -> None:
    source = make_pages(tmp_path / "doc.pdf", 4)
    out = tmp_path / "out" / "doc.pdf"
    _all_held(rotate_pages(source, out, "ccw90", "2-3"))
    with pikepdf.open(out) as pdf:
        assert [int(page.obj.get("/Rotate", 0)) % 360 for page in pdf.pages] == [0, 270, 270, 0]
    assert _texts(out) == _texts(source)


def test_documents_are_put_together_in_their_order(tmp_path: Path) -> None:
    first = make_pages(tmp_path / "a.pdf", 2, "first")
    second = make_pages(tmp_path / "b.pdf", 3, "second")
    out = tmp_path / "out" / "both.pdf"
    _all_held(merge([first, second], out))
    assert _texts(out) == ["first 1", "first 2", "second 1", "second 2", "second 3"]


def test_a_document_is_parted_by_ranges_and_by_n(tmp_path: Path) -> None:
    source = make_pages(tmp_path / "doc.pdf", 5)
    _all_held(split(source, tmp_path / "ranges", "ranges", 1, "1-2, 4-"))
    assert [_texts(path) for path in sorted((tmp_path / "ranges").glob("*.pdf"))] == [["page 1", "page 2"], ["page 4", "page 5"]]
    _all_held(split(source, tmp_path / "every", "every", 2, ""))
    assert [len(_texts(path)) for path in sorted((tmp_path / "every").glob("*.pdf"))] == [2, 2, 1]
    assert sorted(path.name for path in (tmp_path / "every").glob("*.pdf")) == ["doc_001.pdf", "doc_002.pdf", "doc_003.pdf"]


def test_the_properties_are_taken_away_and_the_pages_stay(tmp_path: Path) -> None:
    source = make_pages(tmp_path / "doc.pdf", 2)
    out = tmp_path / "out" / "doc.pdf"
    outcome = clean_meta(source, out)
    _all_held(outcome)
    with pikepdf.open(out) as pdf:
        assert not dict(pdf.docinfo) and "/Metadata" not in pdf.Root
    assert _texts(out) == _texts(source)
    assert "Author" in outcome.notes[0]


def test_an_encrypted_pdf_is_refused(tmp_path: Path) -> None:
    plain = make_pages(tmp_path / "plain.pdf", 2)
    locked = tmp_path / "locked.pdf"
    with pikepdf.open(plain) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(owner="o", user="", R=6))
    assert rotate_pages(locked, tmp_path / "out" / "a.pdf", "180", "").status == "refused"
    assert merge([plain, locked], tmp_path / "out" / "b.pdf").status == "refused"
    assert not (tmp_path / "out" / "a.pdf").exists() and not (tmp_path / "out" / "b.pdf").exists()


def test_the_console_commands_of_pages(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    make_pages(source / "part 10.pdf", 1, "ten")
    make_pages(source / "part 2.pdf", 1, "two")
    report = tmp_path / "report"

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-X", "utf8", str(MAIN), *args, "--report-dir", str(report), "--log-dir", str(tmp_path / "logs")],
                              capture_output=True, text=True, encoding="utf-8")

    # The order of names as a person reads it: 2 before 10.
    done = run("docs-pdf-merge", "--input", str(source), "--output", str(tmp_path / "merged"), "--name", "Сборка")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _texts(tmp_path / "merged" / "Сборка.pdf") == ["two 1", "ten 1"]
    assert json.loads((report / "summary.json").read_text(encoding="utf-8"))["kind"] == "pdf_merge"

    done = run("docs-pdf-rotate", "--input", str(source), "--output", str(tmp_path / "turned"), "--turn", "180")
    assert done.returncode == 0 and "2 of 2 documents done and checked" in done.stdout, done.stdout + done.stderr

    done = run("docs-pdf-split", "--input", str(source), "--output", str(tmp_path / "parts"), "--mode", "ranges", "--ranges", "5")
    assert done.returncode == 1 and "pages 1-1" in done.stdout

    done = run("docs-pdf-clean-meta", "--input", str(source), "--output", str(tmp_path / "clean"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads((report / "summary.json").read_text(encoding="utf-8"))["kind"] == "pdf_clean_meta"

    done = run("docs-pdf-merge", "--input", str(source), "--output", str(source))
    assert done.returncode == 2
