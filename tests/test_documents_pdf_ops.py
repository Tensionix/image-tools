"""The operations of the section PDF over documents: pictures made lighter, a watermark across the pages.

Every copy is held by the checks the operation itself makes; here they have to pass, and the copy is
read again from outside: the pictures, the text of the pages, the watermark as text.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pikepdf
import pymupdf

from system_core.documents.pdf_ops import ShrinkOptions, colour_of, shrink_pdf, watermark_pdf
from system_core.documents.placements import lowest_ppi, scan

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_documents_dpi import make_pdf  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "system_core" / "main.py"


def _all_held(outcome) -> None:
    failed = [text for ok, text in outcome.checks if not ok]
    assert outcome.status == "done" and not failed, (outcome.status, outcome.reason, failed)


def test_pictures_above_the_target_are_made_lighter_down_to_it(tmp_path: Path) -> None:
    source = make_pdf(tmp_path / "sample.pdf")
    out = tmp_path / "out" / "sample.pdf"
    # The picture drawn twice counts by its larger drawing: 150 ppi - it stays; the one at 200 goes down to 150.
    outcome = shrink_pdf(scan(source), out, ShrinkOptions(target=150))
    _all_held(outcome)
    actions = sorted(change.action.split(":")[0] for change in outcome.changes)
    assert actions == ["kept", "made lighter"], [change.action for change in outcome.changes]
    lowest = sorted(round(value) for value in lowest_ppi(scan(out).placements).values())
    assert lowest == [150, 150]
    doc = pymupdf.open(out)
    assert "The text of the page stays." in doc[0].get_text()


def test_a_watermark_is_text_across_every_page(tmp_path: Path) -> None:
    source = make_pdf(tmp_path / "sample.pdf")
    out = tmp_path / "out" / "sample.pdf"
    outcome = watermark_pdf(source, out, "КОПИЯ", 0.25, 0.7, colour_of("#cc0000"))
    _all_held(outcome)
    text = pymupdf.open(out)[0].get_text()
    assert "КОПИЯ" in text and "The text of the page stays." in text


def test_an_encrypted_pdf_is_refused_by_both(tmp_path: Path) -> None:
    plain = make_pdf(tmp_path / "plain.pdf")
    locked = tmp_path / "locked.pdf"
    with pikepdf.open(plain) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(owner="o", user="", R=6))
    assert shrink_pdf(scan(locked), tmp_path / "out" / "a.pdf", ShrinkOptions()).status == "refused"
    assert watermark_pdf(locked, tmp_path / "out" / "b.pdf", "X", 0.3, 0.7, colour_of("red")).status == "refused"
    assert not (tmp_path / "out" / "a.pdf").exists() and not (tmp_path / "out" / "b.pdf").exists()


def test_the_console_commands_of_pdf(tmp_path: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    make_pdf(source / "sample.pdf")
    report = tmp_path / "report"

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-X", "utf8", str(MAIN), *args, "--report-dir", str(report), "--log-dir", str(tmp_path / "logs")],
                              capture_output=True, text=True, encoding="utf-8")

    done = run("docs-pdf-shrink", "--input", str(source), "--output", str(tmp_path / "light"), "--target-ppi", "150")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 of 1 documents done and checked" in done.stdout
    summary = json.loads((report / "summary.json").read_text(encoding="utf-8"))
    assert summary["kind"] == "pdf_shrink" and summary["done"] == 1 and "MB" in summary["rows"][0][2]

    done = run("docs-pdf-watermark", "--input", str(source), "--output", str(tmp_path / "marked"), "--text", "ОБРАЗЕЦ", "--color", "10,20,30")
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads((report / "summary.json").read_text(encoding="utf-8"))["kind"] == "pdf_watermark"
    assert "ОБРАЗЕЦ" in pymupdf.open(tmp_path / "marked" / "sample.pdf")[0].get_text()

    # The check of DPI of the section PDF reads PDF alone, whatever else lies in the Source.
    (source / "other.docx").write_bytes(b"not a document")
    done = run("docs-dpi-check", "--input", str(source), "--kinds", "pdf")
    assert done.returncode == 0 and "other.docx" not in done.stdout
