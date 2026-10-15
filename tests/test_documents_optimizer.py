"""The engine of Audion Office Image Optimizer inside Audion Image Tools: its own tests, and the commands over it.

The first three tests are those of the Optimizer (tests\\test_office_image_optimizer.py there), as
they were; the changes: a copy keeps the name of its document, and the PNG of the sample is noise, not
one colour - a PNG of one colour is lighter than any JPEG of it and now stays a PNG - and opaque: a
transparent PNG is no longer laid on white. The rest run the commands of main.py the way the window runs them.
"""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from system_core.documents.optimizer.ooxml_package import write_hard_batch_document, write_profile_normalized_document
from system_core.documents.optimizer.scanner import scan_document

PROJECT = Path(__file__).resolve().parent.parent
MAIN = PROJECT / "system_core" / "main.py"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def _image_bytes(fmt: str, size: tuple[int, int], color: tuple[int, ...]) -> bytes:
    mode = "RGBA" if len(color) == 4 else "RGB"
    image = Image.new(mode, size, color)
    output = BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def _noise_png(size: tuple[int, int] = (720, 520), alpha: int = 255) -> bytes:
    """A photograph stored as PNG: heavy without loss, much lighter as a JPEG. A channel of alpha opaque everywhere
    is no transparency; below 255 it is."""
    image = Image.merge("RGBA", [Image.effect_noise(size, 60).convert("L") for _ in range(3)] + [Image.new("L", size, alpha)])
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _sample_package(path: Path, package_type: str, png: bytes | None = None) -> None:
    if package_type == "docx":
        prefix, document_part, rels_part = "word", "word/document.xml", "word/_rels/document.xml.rels"
        main_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    else:
        prefix, document_part, rels_part = "ppt", "ppt/presentation.xml", "ppt/_rels/presentation.xml.rels"
        main_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
    root_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    content_types = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="{CONTENT_TYPES_NS}">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="svg" ContentType="image/svg+xml"/>
  <Override PartName="/{document_part}" ContentType="{main_type}"/>
</Types>"""
    root_rels = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{REL_NS}">
  <Relationship Id="rId1" Type="{root_type}" Target="{document_part}"/>
</Relationships>"""
    document_rels = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{REL_NS}">
  <Relationship Id="rIdImage1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/photo.jpg"/>
  <Relationship Id="rIdImage2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/alpha.png"/>
  <Relationship Id="rIdImage3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/vector.svg"/>
</Relationships>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr(document_part, "<?xml version='1.0' encoding='UTF-8'?><root/>")
        archive.writestr(rels_part, document_rels)
        archive.writestr(f"{prefix}/media/photo.jpg", _image_bytes("JPEG", (2400, 1600), (80, 120, 180)))
        archive.writestr(f"{prefix}/media/alpha.png", png if png is not None else _noise_png())
        archive.writestr(f"{prefix}/media/vector.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>")


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_scanner_recognizes_docx_and_pptx_without_modifying_sources(tmp_path: Path) -> None:
    for package_type in ("docx", "pptx"):
        source = tmp_path / f"sample.{package_type}"
        _sample_package(source, package_type)
        before = _digest(source)
        result = scan_document(source)
        assert result.errors == []
        assert result.package_type == package_type
        assert result.total_images == 3
        assert {item.detected_format for item in result.items} == {"jpeg", "png", "svg"}
        assert result.unsupported_count == 1
        assert _digest(source) == before


def test_hard_batch_rewrites_raster_relationships_and_preserves_vector(tmp_path: Path) -> None:
    source = tmp_path / "sample.docx"
    _sample_package(source, "docx")
    before = _digest(source)
    result = write_hard_batch_document(source, "fhd", output_dir=tmp_path / "output")
    assert result.errors == []
    assert result.output_path == tmp_path / "output" / "sample.docx"
    assert _digest(source) == before
    with ZipFile(result.output_path) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert "word/media/alpha.jpg" in names and "word/media/alpha.png" not in names and "word/media/vector.svg" in names
        rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        targets = {node.get("Target") for node in rels.findall(f"{{{REL_NS}}}Relationship")}
        assert "media/alpha.jpg" in targets and "media/alpha.png" not in targets
        types = ET.fromstring(archive.read("[Content_Types].xml"))
        defaults = {node.get("Extension"): node.get("ContentType") for node in types.findall(f"{{{CONTENT_TYPES_NS}}}Default")}
        assert defaults.get("jpg") == "image/jpeg"


def test_srgb_and_cmyk_normalization_produce_readable_packages(tmp_path: Path) -> None:
    source = tmp_path / "sample.pptx"
    _sample_package(source, "pptx")
    before = _digest(source)
    for mode in ("normalize-srgb", "normalize-cmyk"):
        result = write_profile_normalized_document(source, profile_mode=mode, output_dir=tmp_path / mode)
        assert result.errors == []
        assert result.output_path.exists()
        with ZipFile(result.output_path) as archive:
            assert archive.testzip() is None
            assert "ppt/media/vector.svg" in archive.namelist()
    assert _digest(source) == before


def test_a_light_png_stays_a_png_under_the_barrier_in_kb(tmp_path: Path) -> None:
    from system_core.documents.optimizer.models import build_optimization_policy

    source = tmp_path / "sample.docx"
    _sample_package(source, "docx")
    with ZipFile(source) as archive:
        weight = archive.getinfo("word/media/alpha.png").file_size
    # The barrier above the weight of the PNG: it stays; below it: it becomes a JPEG.
    kept = write_hard_batch_document(source, "custom", output_dir=tmp_path / "kept",
                                     policy=build_optimization_policy("fhd", keep_png_under_kb=weight // 1024 + 1))
    gone = write_hard_batch_document(source, "custom", output_dir=tmp_path / "gone",
                                     policy=build_optimization_policy("fhd", keep_png_under_kb=weight // 1024 - 1))
    with ZipFile(kept.output_path) as archive:
        assert "word/media/alpha.png" in archive.namelist()
    with ZipFile(gone.output_path) as archive:
        assert "word/media/alpha.jpg" in archive.namelist()
    item = next(item for item in kept.items if item.package_path.endswith("alpha.png"))
    assert item.executed_action == "keep" and not item.changed


def test_a_png_that_as_a_jpeg_would_weigh_more_stays_a_png(tmp_path: Path) -> None:
    source = tmp_path / "sample.docx"
    flat = _image_bytes("PNG", (720, 520), (180, 60, 40))
    _sample_package(source, "docx", png=flat)
    result = write_hard_batch_document(source, "fhd", output_dir=tmp_path / "out")
    with ZipFile(result.output_path) as archive:
        assert archive.read("word/media/alpha.png") == flat and "word/media/alpha.jpg" not in archive.namelist()
    item = next(item for item in result.items if item.package_path.endswith("alpha.png"))
    assert item.executed_action == "keep" and "JPEG would weigh" in item.note


def test_a_transparent_png_is_not_laid_on_white(tmp_path: Path) -> None:
    for size, action in (((720, 520), "keep"), ((2400, 1600), "resize")):
        source = tmp_path / f"{size[0]}.pptx"
        png = _noise_png(size, alpha=170)
        _sample_package(source, "pptx", png=png)
        result = write_hard_batch_document(source, "fhd", output_dir=tmp_path / "out")
        item = next(item for item in result.items if item.package_path.endswith("alpha.png"))
        assert item.executed_action == action and "transparent" in item.note, (size, item.executed_action, item.note)
        with ZipFile(result.output_path) as archive:
            assert "ppt/media/alpha.jpg" not in archive.namelist()
            with Image.open(BytesIO(archive.read("ppt/media/alpha.png"))) as kept:
                assert kept.mode == "RGBA" and kept.getchannel("A").getextrema() == (170, 170)
                assert max(kept.size) <= 1920


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-X", "utf8", str(MAIN), *args], capture_output=True, text=True, encoding="utf-8")


def test_the_commands_of_the_optimizer_run_over_a_folder(tmp_path: Path) -> None:
    source = tmp_path / "in"
    _sample_package(source / "a.docx", "docx")
    _sample_package(source / "deep" / "b.pptx", "pptx")
    (source / "c.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    logs = str(tmp_path / "logs")

    done = _run("docs-shrink", "--input", str(source), "--output", str(tmp_path / "shrunk"), "--kinds", "docx,pptx,pdf", "--log-dir", logs)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "c.pdf: a PDF - this operation is over DOCX and PPTX, passed by" in done.stdout
    assert "2 of 2 documents shrunk to 1920 x 1080, JPEG 82" in done.stdout
    with ZipFile(tmp_path / "shrunk" / "a.docx") as archive, Image.open(BytesIO(archive.read("word/media/photo.jpg"))) as photo:
        assert max(photo.size) <= 1920
    assert (tmp_path / "shrunk" / "deep" / "b.pptx").exists()

    done = _run("docs-shrink", "--input", str(source), "--output", str(tmp_path / "own"), "--limit", "custom", "--max-width", "300",
                "--max-height", "300", "--log-dir", logs)
    assert done.returncode == 2 and "at least 400 x 400" in done.stdout

    done = _run("docs-fit-size", "--input", str(source), "--output", str(tmp_path / "fit"), "--target-mb", "1", "--log-dir", logs)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "2 of 2 documents fit under 1 MB" in done.stdout

    done = _run("docs-color", "--input", str(source), "--output", str(tmp_path / "cmyk"), "--profile", "cmyk", "--embed-icc", "--log-dir", logs)
    assert done.returncode == 0, done.stdout + done.stderr
    with ZipFile(tmp_path / "cmyk" / "a.docx") as archive, Image.open(BytesIO(archive.read("word/media/photo.jpg"))) as photo:
        assert photo.mode == "CMYK" and photo.info.get("icc_profile")

    done = _run("docs-extract-media", "--input", str(source), "--output", str(tmp_path / "media"), "--log-dir", logs)
    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(path.name for path in (tmp_path / "media" / "a").iterdir()) == ["alpha.png", "photo.jpg", "vector.svg"]
    assert (tmp_path / "media" / "deep" / "b" / "photo.jpg").exists()

    # The Target may not be the folder of the documents themselves: a copy keeps the name of its document.
    done = _run("docs-color", "--input", str(source), "--output", str(source), "--log-dir", logs)
    assert done.returncode == 2
    report = json.loads(sorted((tmp_path / "logs").glob("run_*.json"))[-1].read_text(encoding="utf-8"))
    assert report["command"] in ("docs-extract-media", "docs-color")
