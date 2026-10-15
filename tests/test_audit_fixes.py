"""The findings of the targeted audit of 15.10.2026 (E:\\TOOLS\\AUDIT\\Audion Image Tools\\report\\2026-10-15_targeted_audit),
each held by a test on the inputs the audit used.

F01 a Target inside the Source wrote over the originals; F02 a STOP left a broken copy over a good one; F03 a signed PDF
without the optional /Type /Sig went through; F06 the cleanup swept the trees it keeps; F07 a copy with broken XML was
called done; F08 an existing flag w:val="0" was taken for "do not compress"; F09 a linked picture let a copy be done
(tests\\test_documents_dpi.py, LINKED); F10 one document that does not read ended the batch; F11 nan and 1.5 started the
engine; F12 the Optimizer changed a signed DOCX. F04, F05, F13 are of the window (Source\\MainWindow.Run.cs, Io.cs).
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

from system_core.core.paths import routes_cross
from system_core.documents.optimizer.ooxml_package import _whole_copy
from system_core.documents.optimizer.models import ProcessResult
from system_core.documents.placements import pdf_refusal
from system_core.documents.raise_dpi import keep_word_from_compressing, word_compression_off
from system_core.image_tools.io_utils import discover_inputs, written_whole
from test_documents_dpi import INCH, inline, make_docx

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "system_core" / "main.py"


def engine(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-X", "utf8", str(MAIN), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def png(size=(720, 520), colour=(30, 90, 160)) -> bytes:
    out = io.BytesIO()
    Image.effect_noise(size, 60).convert("RGB").save(out, "PNG")
    return out.getvalue()


def docx(path: Path, *, signed: bool = False, broken: bool = False, words: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    made = make_docx(path, {"image1.png": png()}, inline("rId5", INCH * 5, INCH * 4) + words, {"rId5": "media/image1.png"}, signed=signed)
    if broken:
        # The main part of the document cut short: it no longer parses.
        with zipfile.ZipFile(made) as old:
            parts = {name: old.read(name) for name in old.namelist()}
        parts["word/document.xml"] = b"<w:broken"
        with zipfile.ZipFile(made, "w") as new:
            for name, data in parts.items():
                new.writestr(name, data)
    return made


# --- F01 --------------------------------------------------------------------------------------------------------------


def test_a_target_that_crosses_the_source_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "nested_target").mkdir(parents=True)
    assert "inside the Source" in routes_cross(source, source / "nested_target")
    assert "the Source itself" in routes_cross(source, source)
    assert "Source lies inside the Target" in routes_cross(source, tmp_path)
    assert routes_cross(source, tmp_path / "beside") == ""
    single = source / "a.docx"
    single.write_bytes(b"x")
    assert routes_cross(single, source) != "" and routes_cross(single, source / "nested_target") == ""


def test_a_junction_does_not_hide_the_crossing(tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "source" / "result").mkdir(parents=True)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(tmp_path / "alias"), str(real)], capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip("no junction could be made here: " + made.stdout + made.stderr)
    assert "inside the Source" in routes_cross(real / "source", tmp_path / "alias" / "source" / "result")


def test_the_nested_target_of_the_audit_leaves_the_original_whole(tmp_path: Path) -> None:
    source = tmp_path / "source"
    docx(source / "same.docx")
    second = docx(source / "nested_target" / "same.docx", words="<w:p><w:r><w:t>NESTED ORIGINAL MUST SURVIVE</w:t></w:r></w:p>")
    before = second.read_bytes()
    done = engine("docs-shrink", "--input", str(source), "--output", str(source / "nested_target"), "--log-dir", str(tmp_path / "logs"))
    assert done.returncode == 2 and "inside the Source" in done.stdout, done.stdout
    assert second.read_bytes() == before


# --- F02, F07 ---------------------------------------------------------------------------------------------------------


def test_a_copy_is_written_beside_its_place_and_a_stop_leaves_the_old_one(tmp_path: Path) -> None:
    destination = tmp_path / "out" / "doc.docx"
    destination.parent.mkdir()
    destination.write_bytes(b"the good copy of yesterday")
    result = ProcessResult(document_path=tmp_path / "doc.docx", output_path=destination, package_type="docx", mode="hard", preset="custom", batch=True)
    with pytest.raises(KeyboardInterrupt):
        with _whole_copy(destination, result) as temp:
            with zipfile.ZipFile(temp, "w") as part:
                part.writestr("word/document.xml", "<w:document/>")
            # While the copy is written its place is untouched.
            assert destination.read_bytes() == b"the good copy of yesterday"
            raise KeyboardInterrupt
    assert destination.read_bytes() == b"the good copy of yesterday"
    assert not (tmp_path / "out" / "doc.docx.writing").exists()


def test_a_picture_is_written_whole_and_a_left_part_is_no_input(tmp_path: Path) -> None:
    target = tmp_path / "big.png"
    target.write_bytes(b"the good copy of yesterday")
    with pytest.raises(KeyboardInterrupt):
        with written_whole(target) as temp:
            temp.write_bytes(png())
            assert temp.name == "big.writing.png" and target.read_bytes() == b"the good copy of yesterday"
            raise KeyboardInterrupt
    assert target.read_bytes() == b"the good copy of yesterday" and not (tmp_path / "big.writing.png").exists()
    # A part an engine killed from outside left behind is not taken for a picture of the Source.
    (tmp_path / "cut.writing.png").write_bytes(png())
    assert discover_inputs(tmp_path) == [target]


def test_a_copy_with_broken_xml_is_not_called_done_nor_put_in_place(tmp_path: Path) -> None:
    source = tmp_path / "in"
    docx(source / "doc.docx", broken=True)
    target = tmp_path / "out"
    target.mkdir()
    (target / "doc.docx").write_bytes(b"the good copy of yesterday")
    done = engine("docs-shrink", "--input", str(source), "--output", str(target), "--keep-png-under-kb", "0", "--log-dir", str(tmp_path / "logs"))
    assert done.returncode == 1, done.stdout
    assert "[ERR 1/1] doc.docx" in done.stdout and "not put in place" in done.stdout, done.stdout
    assert (target / "doc.docx").read_bytes() == b"the good copy of yesterday"


# --- F03 --------------------------------------------------------------------------------------------------------------


def _pdf_with_field(path: Path, field_of) -> Path:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    signature = pdf.make_indirect(pikepdf.Dictionary(Filter=pikepdf.Name("/Adobe.PPKLite"), SubFilter=pikepdf.Name("/adbe.pkcs7.detached"),
                                                     ByteRange=pikepdf.Array([0, 10, 20, 30]), Contents=pikepdf.String(b"\x00" * 16)))
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([pdf.make_indirect(field_of(signature))]))
    pdf.save(path)
    return path


def test_a_signed_pdf_is_known_without_the_optional_type_and_flags(tmp_path: Path) -> None:
    # The audit's PDF: a field /FT /Sig with a filled /V, no /Type in the signature dictionary, no /SigFlags.
    plain = _pdf_with_field(tmp_path / "plain.pdf", lambda sig: pikepdf.Dictionary(FT=pikepdf.Name.Sig, T=pikepdf.String("s"), V=sig))
    assert "signed" in pdf_refusal(plain)
    # The kind inherited from a parent field.
    kid = _pdf_with_field(tmp_path / "kid.pdf", lambda sig: pikepdf.Dictionary(
        FT=pikepdf.Name.Sig, T=pikepdf.String("p"), Kids=pikepdf.Array([pikepdf.Dictionary(T=pikepdf.String("k"), V=sig)])))
    assert "signed" in pdf_refusal(kid)
    # An empty signature field signs nothing; a copy breaks nothing.
    empty = pikepdf.new()
    empty.add_blank_page(page_size=(200, 200))
    empty.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([empty.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name.Sig, T=pikepdf.String("e")))]))
    empty.save(tmp_path / "empty.pdf")
    assert pdf_refusal(tmp_path / "empty.pdf") == ""


# --- F06 --------------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "nt", reason="a script of CMD")
def test_the_cleanup_passes_the_trees_it_keeps(tmp_path: Path) -> None:
    root = tmp_path / "Audion Image Tools"
    for marker in ("system_core/main.py", "config/tool_manifest.yaml", "system_core/image_tools/commands.py"):
        (root / marker).parent.mkdir(parents=True, exist_ok=True)
        (root / marker).write_text("marker", encoding="utf-8")
    kept = ["App/keep.log", "App/cache/_runtime/keep.txt", "docs/original.bak", "config/precious.tmp", "licenses/audit.log",
            "licenses/cache/__pycache__/keep.txt"]
    taken = ["logs/run.log", "system_core/__pycache__/a.pyc", "system_core/old.bak", "x.tmp"]
    for rel in kept + taken:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x", encoding="utf-8")
    shutil.copy2(PROJECT / "cleanup_project.cmd", root / "cleanup_project.cmd")
    done = subprocess.run(["cmd", "/c", str(root / "cleanup_project.cmd"), "/Y"], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=dict(os.environ, AUDION_NO_PAUSE="1"), cwd=str(root))
    assert done.returncode == 0, done.stdout[-2000:]
    assert [rel for rel in kept if not (root / rel).exists()] == []
    assert [rel for rel in taken if (root / rel).exists()] == []


# --- F08 --------------------------------------------------------------------------------------------------------------


def test_the_flag_against_compression_is_set_on_even_when_it_said_no() -> None:
    settings = b'<w:settings xmlns:w="w"><w:doNotAutoCompressPictures w:val="0"/><w:decimalSymbol w:val=","/></w:settings>'
    assert not word_compression_off(settings)
    written = keep_word_from_compressing(settings)
    assert word_compression_off(written) and written.count(b"doNotAutoCompressPictures") == 1
    assert word_compression_off(keep_word_from_compressing(b'<w:settings xmlns:w="w"><w:decimalSymbol w:val=","/></w:settings>'))
    assert word_compression_off(b'<w:settings><w:doNotAutoCompressPictures w:val="true"/></w:settings>')


# --- F10 --------------------------------------------------------------------------------------------------------------


def test_one_document_that_does_not_read_does_not_end_the_batch(tmp_path: Path) -> None:
    source = tmp_path / "in"
    docx(source / "01-broken.docx", broken=True)
    docx(source / "02-good.docx")
    done = engine("docs-dpi-raise", "--input", str(source), "--output", str(tmp_path / "out"), "--log-dir", str(tmp_path / "logs"))
    assert done.returncode == 1, done.stdout + done.stderr
    assert "[ERR 1/2] 01-broken.docx" in done.stdout and "does not read" in done.stdout, done.stdout
    assert (tmp_path / "out" / "02-good.docx").exists()
    checked = engine("docs-dpi-check", "--input", str(source), "--log-dir", str(tmp_path / "logs"))
    assert "01-broken.docx" in checked.stdout and "Traceback" not in checked.stdout + checked.stderr


# --- F12 --------------------------------------------------------------------------------------------------------------


def test_the_optimizer_refuses_a_signed_document(tmp_path: Path) -> None:
    source = tmp_path / "in"
    docx(source / "signed.docx", signed=True)
    done = engine("docs-shrink", "--input", str(source), "--output", str(tmp_path / "out"), "--keep-png-under-kb", "0", "--log-dir", str(tmp_path / "logs"))
    assert done.returncode == 1 and "digital signature" in done.stdout, done.stdout
    assert not (tmp_path / "out" / "signed.docx").exists()
