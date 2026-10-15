"""The pictures inside documents: where they stand, their resolution, and the copy raised to a threshold.

The documents are made here, by hand, the way Word, PowerPoint and a PDF writer lay them out: a
picture of its own, one in a group, one cropped, one in VML, a linked one, a placeholder that takes
its size from its layout, a background, a picture drawn twice in a PDF. What a copy must be is held
by the copy itself: every check `raise_document` makes has to pass.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

import pikepdf
import pymupdf
import pytest
from PIL import Image

from system_core.documents.density import restate_jpeg, restate_png
from system_core.documents.placements import lowest_ppi, scan
from system_core.documents.raise_dpi import Options, raise_document

PROJECT = Path(__file__).resolve().parent.parent

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
WPG = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
INCH = 914400


def picture(size: tuple[int, int], kind: str = "PNG", mode: str = "RGB", dpi: int | None = 72) -> bytes:
    image = Image.effect_noise(size, 40).convert(mode) if mode != "RGBA" else Image.merge("RGBA", [Image.effect_noise(size, 40)] * 3 + [Image.new("L", size, 200)])
    out = io.BytesIO()
    extra = {"dpi": (dpi, dpi)} if dpi else {}
    image.save(out, kind, **extra)
    return out.getvalue()


def blip_pic(rid: str, cx: int, cy: int, crop: str = "") -> str:
    return (f'<pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="p"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/>{crop}'
            f'<a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>')


def make_docx(path: Path, media: dict[str, bytes], body: str, rels: dict[str, str], signed: bool = False) -> Path:
    rel_lines = "".join(
        f'<Relationship Id="{rid}" Type="{IMAGE}" Target="{target}"' + (' TargetMode="External"' if target.startswith("http") else "") + "/>"
        for rid, target in rels.items())
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}" xmlns:wp="{WP}" xmlns:a="{A}" '
                f'xmlns:pic="{PIC}" xmlns:r="{R}" xmlns:wpg="{WPG}" xmlns:v="urn:schemas-microsoft-com:vml" '
                f'xmlns:o="urn:schemas-microsoft-com:office:office"><w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                         '<Default Extension="jpeg" ContentType="image/jpeg"/>'
                         '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                         '</Types>')
        archive.writestr("_rels/.rels", f'<?xml version="1.0"?><Relationships xmlns="{REL}"><Relationship Id="rId1" '
                         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="{REL}">{rel_lines}</Relationships>')
        archive.writestr("word/settings.xml", f'<?xml version="1.0"?><w:settings xmlns:w="{W}"><w:defaultTabStop w:val="708"/>'
                         '<w:decimalSymbol w:val=","/><w:listSeparator w:val=";"/></w:settings>')
        for name, data in media.items():
            archive.writestr(f"word/media/{name}", data)
        if signed:
            archive.writestr("_xmlsignatures/sig1.xml", "<Signature/>")
    return path


def inline(rid: str, cx: int, cy: int, crop: str = "") -> str:
    return (f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="1" name="d"/><a:graphic>'
            f'<a:graphicData uri="{PIC}">{blip_pic(rid, cx, cy, crop)}</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


@pytest.fixture()
def docx(tmp_path: Path) -> Path:
    # image1: 1100 x 733 at 5 inches - 220 ppi; the same picture cropped to its middle half - 110 ppi.
    # image2: 1100 x 733 in a group drawn at half its size - 2.5 inches, 440 ppi.
    # image3: VML at 360 pt - 5 inches. A linked picture is named and not measured.
    group = (f'<w:p><w:r><w:drawing><wp:anchor><wp:extent cx="{INCH * 5 // 2}" cy="{INCH * 5 // 3}"/><wp:docPr id="2" name="g"/><a:graphic>'
             f'<a:graphicData uri="{WPG}"><wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{INCH * 5}" cy="{INCH * 10 // 3}"/>'
             f'<a:chOff x="0" y="0"/><a:chExt cx="{INCH * 5}" cy="{INCH * 10 // 3}"/></a:xfrm></wpg:grpSpPr>{blip_pic("rId6", INCH * 5, INCH * 10 // 3)}'
             '</wpg:wgp></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r></w:p>')
    vml = '<w:p><w:r><w:pict><v:shape style="width:360pt;height:240pt"><v:imagedata r:id="rId7" o:title=""/></v:shape></w:pict></w:r></w:p>'
    crop = '<a:srcRect l="25000" r="25000"/>'
    body = inline("rId5", INCH * 5, INCH * 10 // 3) + inline("rId5", INCH * 5 // 2, INCH * 10 // 3, crop) + group + vml + inline("rId8", INCH, INCH)
    return make_docx(tmp_path / "sample.docx",
                     {"image1.png": picture((1100, 733)), "image2.png": picture((1100, 733), "PNG", "RGBA"), "image3.jpeg": picture((1500, 1000), "JPEG")},
                     body, {"rId5": "media/image1.png", "rId6": "media/image2.png", "rId7": "media/image3.jpeg", "rId8": "http://example.org/a.png"})


def test_the_placements_of_a_docx(docx: Path) -> None:
    found = scan(docx)
    assert found.kind == "docx" and not found.refusal
    rows = [(p.place, p.picture.part, None if p.ppi is None else round(p.ppi)) for p in found.placements]
    assert rows == [
        ("document", "word/media/image1.png", 220),
        # Cropped to its middle half and drawn at half the width: still 220 across, 220 down.
        ("document", "word/media/image1.png", 220),
        ("document", "word/media/image2.png", 440),
        ("document", "http://example.org/a.png", None),
        ("document (VML)", "word/media/image3.jpeg", 300),
    ]
    linked = next(p for p in found.placements if p.picture.part.startswith("http"))
    assert "linked" in linked.note
    assert lowest_ppi(found.placements)["word/media/image1.png"] == pytest.approx(220, abs=0.5)


def test_a_crop_is_counted_by_the_visible_part(tmp_path: Path) -> None:
    path = make_docx(tmp_path / "crop.docx", {"image1.png": picture((1000, 1000))},
                     inline("rId5", INCH * 5, INCH * 5, '<a:srcRect l="25000" t="0" r="25000" b="0"/>'), {"rId5": "media/image1.png"})
    placement = scan(path).placements[0]
    # 500 visible pixels across 5 inches, 1000 down 5 inches.
    assert round(placement.ppi) == 100


def make_pptx(path: Path, media: dict[str, bytes]) -> Path:
    tree = (f'<p:cSld><p:bg><p:bgPr><a:blipFill><a:blip r:embed="rId4"/><a:stretch><a:fillRect/></a:stretch></a:blipFill></p:bgPr></p:bg><p:spTree>'
            f'<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
            f'<p:grpSp><p:nvGrpSpPr><p:cNvPr id="2" name="g"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="{INCH * 5 // 2}" cy="{INCH * 5 // 3}"/><a:chOff x="0" y="0"/><a:chExt cx="{INCH * 5}" cy="{INCH * 10 // 3}"/></a:xfrm></p:grpSpPr>'
            f'<p:pic><p:nvPicPr><p:cNvPr id="3" name="a"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{INCH * 5}" cy="{INCH * 10 // 3}"/></a:xfrm></p:spPr></p:pic></p:grpSp>'
            f'<p:pic><p:nvPicPr><p:cNvPr id="4" name="ph"/><p:cNvPicPr/><p:nvPr><p:ph type="pic" idx="1"/></p:nvPr></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="rId3"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr/></p:pic></p:spTree></p:cSld>')
    slide = f'<?xml version="1.0"?><p:sld xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}">{tree}</p:sld>'
    layout = (f'<?xml version="1.0"?><p:sldLayout xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
              f'<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="ph"/><p:cNvSpPr/><p:nvPr><p:ph type="pic" idx="1"/></p:nvPr></p:nvSpPr>'
              f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{INCH * 2}" cy="{INCH * 2}"/></a:xfrm></p:spPr></p:sp></p:spTree></p:cSld></p:sldLayout>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/></Types>')
        archive.writestr("ppt/presentation.xml", f'<?xml version="1.0"?><p:presentation xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}" saveSubsetFonts="1">'
                         f'<p:sldSz cx="{INCH * 10}" cy="{INCH * 15 // 2}"/></p:presentation>')
        archive.writestr("ppt/slides/slide1.xml", slide)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="{REL}">'
                         f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                         f'<Relationship Id="rId2" Type="{IMAGE}" Target="../media/image1.png"/><Relationship Id="rId3" Type="{IMAGE}" Target="../media/image2.png"/>'
                         f'<Relationship Id="rId4" Type="{IMAGE}" Target="../media/image3.png"/></Relationships>')
        archive.writestr("ppt/slideLayouts/slideLayout1.xml", layout)
        for name, data in media.items():
            archive.writestr(f"ppt/media/{name}", data)
    return path


def test_the_placements_of_a_pptx(tmp_path: Path) -> None:
    path = make_pptx(tmp_path / "sample.pptx", {"image1.png": picture((1100, 733)), "image2.png": picture((400, 400)), "image3.png": picture((1500, 1125))})
    rows = [(p.place, p.picture.part, None if p.ppi is None else round(p.ppi)) for p in scan(path).placements]
    assert rows == [
        # The background fills the slide: 1500 across 10 inches.
        ("slide 1", "ppt/media/image3.png", 150),
        # In a group drawn at half its size.
        ("slide 1", "ppt/media/image1.png", 440),
        # A placeholder without a size of its own: the 2 inches of its layout.
        ("slide 1", "ppt/media/image2.png", 200),
    ]


def make_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    # One picture drawn twice: at 2 inches (300 ppi) and at 4 inches (150 ppi).
    xref = page.insert_image(pymupdf.Rect(72, 72, 72 + 144, 72 + 96), stream=picture((600, 400)))
    page.insert_image(pymupdf.Rect(72, 300, 72 + 288, 300 + 192), xref=xref)
    # A picture with a mask of transparency, at 200 ppi.
    page.insert_image(pymupdf.Rect(300, 72, 300 + 144, 72 + 144), stream=picture((400, 400), "PNG", "RGBA"))
    page.insert_text((72, 700), "The text of the page stays.")
    doc.save(path)
    doc.close()
    return path


def test_the_placements_of_a_pdf(tmp_path: Path) -> None:
    found = scan(make_pdf(tmp_path / "sample.pdf"))
    ppis = sorted(round(p.ppi) for p in found.placements)
    assert ppis == [150, 200, 300]
    lowest = lowest_ppi(found.placements)
    assert sorted(round(value) for value in lowest.values()) == [150, 200]
    assert any(p.picture.alpha for p in found.placements)


# The sample DOCX carries a picture linked from outside (rId8): its pixels are not known, so the threshold is not
# checked on it and its copy is partial, not done (the audit of 15.10.2026, F09).
LINKED = "1 placements not measured - the threshold is not checked on them: document http://example.org/a.png"


def _all_held(outcome, linked: bool = False) -> None:
    failed = [text for ok, text in outcome.checks if not ok]
    if linked:
        assert outcome.status == "partial" and len(failed) == 1 and failed[0].startswith(LINKED), (outcome.status, outcome.reason, failed)
    else:
        assert outcome.status == "done" and not failed, (outcome.status, outcome.reason, failed)


def test_a_docx_raised_to_300(docx: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "sample.docx"
    outcome = raise_document(scan(docx), out, Options(threshold=300))
    _all_held(outcome, linked=True)
    actions = {change.part: change for change in outcome.changes}
    # 220 ppi: every pixel repeated two by two; a PNG without a mask becomes a JPEG under a new name.
    assert actions["word/media/image1.png"].pixels_after == (2200, 1466)
    assert actions["word/media/image1.png"].renamed_to == "word/media/image1.jpg"
    # A PNG with a mask stays a PNG; at 440 ppi its pixels stay, only the label is written.
    assert actions["word/media/image2.png"].action.startswith("label")
    assert actions["word/media/image3.jpeg"].action.startswith("label")
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        assert "word/media/image1.jpg" in names and "word/media/image1.png" not in names
        rels = archive.read("word/_rels/document.xml.rels").decode()
        assert 'Target="media/image1.jpg"' in rels and "http://example.org/a.png" in rels
        assert b'Extension="jpg"' in archive.read("[Content_Types].xml")
        settings = archive.read("word/settings.xml").decode()
        # On its place in the order of the schema: before w:decimalSymbol.
        assert settings.index("doNotAutoCompressPictures") < settings.index("decimalSymbol")
        with Image.open(io.BytesIO(archive.read("word/media/image2.png"))) as kept:
            assert kept.size == (1100, 733) and round(kept.info["dpi"][0]) == 300


def test_a_docx_keeps_its_lossless_pictures_when_asked(docx: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "sample.docx"
    outcome = raise_document(scan(docx), out, Options(threshold=300, keep_lossless=True, method="smooth"))
    _all_held(outcome, linked=True)
    change = next(c for c in outcome.changes if c.part == "word/media/image1.png")
    assert not change.renamed_to and change.stored_after == "png"
    assert change.ppi_after >= 300


def test_label_only_adds_no_pixel(docx: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "sample.docx"
    outcome = raise_document(scan(docx), out, Options(threshold=300, what="label", office_may_compress=True))
    _all_held(outcome)
    assert all(change.pixels_after == change.pixels_before for change in outcome.changes)
    with zipfile.ZipFile(out) as archive:
        assert b"doNotAutoCompressPictures" not in archive.read("word/settings.xml")


def test_a_pptx_raised_to_300(tmp_path: Path) -> None:
    path = make_pptx(tmp_path / "sample.pptx", {"image1.png": picture((1100, 733)), "image2.png": picture((400, 400)), "image3.png": picture((1500, 1125))})
    out = tmp_path / "out" / "sample.pptx"
    outcome = raise_document(scan(path), out, Options(threshold=300))
    _all_held(outcome)
    with zipfile.ZipFile(out) as archive:
        assert b'autoCompressPictures="0"' in archive.read("ppt/presentation.xml")
    lowest = lowest_ppi(scan(out).placements)
    assert min(lowest.values()) >= 300


def test_a_pdf_raised_to_300(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "sample.pdf")
    out = tmp_path / "out" / "sample.pdf"
    outcome = raise_document(scan(path), out, Options(threshold=300))
    _all_held(outcome)
    again = scan(out)
    assert min(p.ppi for p in again.placements) >= 300
    # The picture drawn twice is counted by its larger drawing: 150 -> x2.
    assert sorted(change.pixels_after for change in outcome.changes) == [(800, 800), (1200, 800)]


def make_special_pdf(path: Path) -> Path:
    """A palette picture, a one-bit scan and a CMYK JPEG, each at 100 ppi."""
    pdf = pikepdf.new()
    palette = pikepdf.Array([pikepdf.Name.Indexed, pikepdf.Name.DeviceRGB, 3, pikepdf.String(bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0]))])
    indices = bytes((x // 25 + y // 25) % 4 for y in range(100) for x in range(100))
    indexed = pikepdf.Stream(pdf, zlib.compress(indices), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
                             Width=100, Height=100, ColorSpace=palette, BitsPerComponent=8, Filter=pikepdf.Name.FlateDecode)
    bits = Image.new("1", (100, 100), 1)
    for x in range(0, 100, 4):
        for y in range(100):
            bits.putpixel((x, y), 0)
    onebit = pikepdf.Stream(pdf, zlib.compress(bits.tobytes("raw", "1")), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
                            Width=100, Height=100, ColorSpace=pikepdf.Name.DeviceGray, BitsPerComponent=1, Filter=pikepdf.Name.FlateDecode)
    cmyk = io.BytesIO()
    Image.merge("CMYK", [Image.linear_gradient("L").resize((100, 100))] + [Image.new("L", (100, 100), 30)] * 3).save(cmyk, "JPEG", quality=95)
    jpeg = pikepdf.Stream(pdf, cmyk.getvalue(), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=100, Height=100,
                          ColorSpace=pikepdf.Name.DeviceCMYK, BitsPerComponent=8, Filter=pikepdf.Name.DCTDecode)
    content = b"q 72 0 0 72 72 600 cm /A Do Q q 72 0 0 72 200 600 cm /B Do Q q 72 0 0 72 330 600 cm /C Do Q"
    page = pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, 612, 792],
                              Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(A=indexed, B=onebit, C=jpeg)),
                              Contents=pikepdf.Stream(pdf, content))
    pdf.pages.append(pikepdf.Page(page))
    pdf.save(path)
    return path


def test_a_palette_a_one_bit_scan_and_cmyk_are_raised_as_they_are(tmp_path: Path) -> None:
    path = make_special_pdf(tmp_path / "special.pdf")
    out = tmp_path / "out" / "special.pdf"
    outcome = raise_document(scan(path), out, Options(threshold=300))
    _all_held(outcome)
    assert all(change.action.startswith("raised") for change in outcome.changes), [c.action for c in outcome.changes]
    with pikepdf.open(out) as pdf:
        images = [obj for obj in pdf.objects if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == "/Image"]
        kinds = sorted((str(obj.get("/ColorSpace") if not isinstance(obj.get("/ColorSpace"), pikepdf.Array) else obj.ColorSpace[0]),
                        int(obj.BitsPerComponent), str(obj.Filter), int(obj.Width)) for obj in images)
    # The palette and the one bit stay without loss; the CMYK JPEG stays CMYK.
    assert kinds == [("/DeviceCMYK", 8, "/DCTDecode", 300), ("/DeviceGray", 1, "/FlateDecode", 300), ("/Indexed", 8, "/FlateDecode", 300)]


def test_a_picture_left_below_the_threshold_makes_the_copy_partial(tmp_path: Path) -> None:
    """A picture written into the page itself (BI ... EI) is never rewritten: the copy is not called done."""
    pdf = pikepdf.new()
    content = b"q 72 0 0 72 72 600 cm BI /W 10 /H 10 /CS /G /BPC 8 ID " + bytes(range(100)) + b" EI Q"
    page = pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, 612, 792], Contents=pikepdf.Stream(pdf, content))
    pdf.pages.append(pikepdf.Page(page))
    path = tmp_path / "inline.pdf"
    pdf.save(path)
    found = scan(path)
    assert [(p.picture.part, round(p.ppi)) for p in found.placements] == [("inline", 10)]
    outcome = raise_document(found, tmp_path / "out" / "inline.pdf", Options(threshold=300))
    assert outcome.status == "partial"
    assert any(not ok and "left below: 1" in text and "inline" in text for ok, text in outcome.checks)


def test_a_signed_docx_and_an_encrypted_pdf_are_refused(tmp_path: Path) -> None:
    signed = make_docx(tmp_path / "signed.docx", {"image1.png": picture((100, 100))}, inline("rId5", INCH, INCH), {"rId5": "media/image1.png"}, signed=True)
    outcome = raise_document(scan(signed), tmp_path / "out" / "signed.docx", Options())
    assert outcome.status == "refused" and "signature" in outcome.reason
    plain = make_pdf(tmp_path / "plain.pdf")
    locked = tmp_path / "locked.pdf"
    with pikepdf.open(plain) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(owner="o", user="", R=6))
    outcome = raise_document(scan(locked), tmp_path / "out" / "locked.pdf", Options())
    assert outcome.status == "refused" and "encrypted" in outcome.reason
    assert not (tmp_path / "out" / "locked.pdf").exists()


def test_a_label_is_rewritten_without_touching_a_pixel() -> None:
    jpeg = picture((64, 48), "JPEG", dpi=72)
    stated = restate_jpeg(jpeg, 300)
    with Image.open(io.BytesIO(stated)) as after, Image.open(io.BytesIO(jpeg)) as before:
        assert after.info["dpi"] == (300, 300) and after.tobytes() == before.tobytes()
    bare = picture((64, 48), "JPEG", dpi=None)
    with Image.open(io.BytesIO(restate_jpeg(bare, 300))) as after:
        assert after.info["dpi"] == (300, 300)
    png = picture((64, 48), "PNG", dpi=None)
    stated = restate_png(png, 300)
    with Image.open(io.BytesIO(stated)) as after, Image.open(io.BytesIO(png)) as before:
        assert round(after.info["dpi"][0]) == 300 and after.tobytes() == before.tobytes()
    assert restate_png(restate_png(png, 150), 300).count(b"pHYs") == 1


def test_the_console_command_checks_and_raises(tmp_path: Path, docx: Path) -> None:
    source = tmp_path / "in"
    source.mkdir()
    docx.replace(source / "sample.docx")
    make_pdf(source / "sample.pdf")
    main = PROJECT / "system_core" / "main.py"
    done = subprocess.run([sys.executable, "-X", "utf8", str(main), "docs-dpi-check", "--input", str(source), "--threshold", "300",
                           "--report-dir", str(tmp_path / "report"), "--log-dir", str(tmp_path / "logs")], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    assert "4 of 7 placements below 300 ppi; 1 not measured" in done.stdout
    assert (tmp_path / "report" / "dpi_check.csv").exists() and (tmp_path / "report" / "dpi_check.md").exists()
    done = subprocess.run([sys.executable, "-X", "utf8", str(main), "docs-dpi-raise", "--input", str(source), "--output", str(tmp_path / "out"),
                           "--report-dir", str(tmp_path / "report"), "--log-dir", str(tmp_path / "logs")], capture_output=True, text=True, encoding="utf-8")
    # The DOCX holds a linked picture: partial, and the run says so by its exit code.
    assert done.returncode == 1, done.stdout + done.stderr
    assert "1 of 2 documents done and checked" in done.stdout
    assert (tmp_path / "out" / "sample.docx").exists() and (tmp_path / "out" / "sample.pdf").exists()
    report = json.loads(sorted((tmp_path / "logs").glob("run_*.json"))[-1].read_text(encoding="utf-8"))
    assert {Path(item["document"]).name: item["status"] for item in report["documents"]} == {"sample.docx": "partial", "sample.pdf": "done"}
    # The Target may not be the folder of the documents themselves.
    done = subprocess.run([sys.executable, "-X", "utf8", str(main), "docs-dpi-raise", "--input", str(source), "--output", str(source),
                           "--log-dir", str(tmp_path / "logs")], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 2
    # Nor a folder inside them: its copies would be read as originals and land on them (F01).
    done = subprocess.run([sys.executable, "-X", "utf8", str(main), "docs-dpi-raise", "--input", str(source), "--output", str(source / "copies"),
                           "--log-dir", str(tmp_path / "logs")], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 2 and "inside the Source" in done.stdout, done.stdout
