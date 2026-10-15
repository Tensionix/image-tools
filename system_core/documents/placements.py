"""Where every picture of a document stands, and at what size: one record for PDF, DOCX and PPTX.

The resolution a picture really has in a document is its pixels against the size it is placed at -
not the number its file states of itself (that one is `label`, and changes nothing on the page).
Where the size is written:

  PDF   the matrix a picture is drawn with on its page (MuPDF traces the page: forms, rotation,
        a picture drawn twice - every drawing is a placement of its own)
  DOCX  `wp:extent` of the drawing; a picture inside a group - its own `a:ext` scaled by the groups
        over it; old VML - the width and height of `v:shape`
  PPTX  `a:ext` of the picture or of the shape it fills, scaled by the groups over it; a placeholder
        without a size of its own takes the one of its layout, then of its master; a background - the slide

A crop (`a:srcRect`) is counted: the visible part of the picture is what fills the frame. A picture
that is linked and not inside the document, and a vector picture (EMF, WMF, SVG), are named and not
measured.
"""
from __future__ import annotations

import io
import math
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from PIL import Image

EMU_PER_INCH = 914400
MM_PER_INCH = 25.4

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
R_EMBED = f"{{{NS['r']}}}embed"
R_LINK = f"{{{NS['r']}}}link"
R_ID = f"{{{NS['r']}}}id"
O_RELID = f"{{{NS['o']}}}relid"
VECTOR = {".emf", ".wmf", ".svg", ".emz", ".wmz"}
SIGNATURE_PART = re.compile(r"^_xmlsignatures/", re.IGNORECASE)


@dataclass
class Picture:
    """A picture file of a document as it is stored: one record however many times it is placed."""

    part: str
    pixels: tuple[int, int] | None = None
    stored: str = ""
    label: tuple[float, float] | None = None
    alpha: bool = False
    mode: str = ""
    note: str = ""


@dataclass
class Placement:
    """One placement of a picture: where, how large, and the resolution that comes of it."""

    document: Path
    place: str
    picture: Picture
    size_in: tuple[float, float] | None
    crop: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    note: str = ""

    @property
    def size_mm(self) -> tuple[float, float] | None:
        return None if self.size_in is None else (self.size_in[0] * MM_PER_INCH, self.size_in[1] * MM_PER_INCH)

    @property
    def ppi(self) -> float | None:
        """Pixels of the visible part against the size it fills, by the lower of the two sides."""
        if self.picture.pixels is None or self.size_in is None:
            return None
        width, height = self.size_in
        if width <= 0 or height <= 0:
            return None
        left, top, right, bottom = self.crop
        seen_x = self.picture.pixels[0] * (1 - left - right)
        seen_y = self.picture.pixels[1] * (1 - top - bottom)
        if seen_x <= 0 or seen_y <= 0:
            return None
        return min(seen_x / width, seen_y / height)


@dataclass
class Scan:
    """What a document holds: its placements, and what keeps it from being changed."""

    document: Path
    kind: str
    placements: list[Placement] = field(default_factory=list)
    pictures: dict[str, Picture] = field(default_factory=dict)
    refusal: str = ""
    notes: list[str] = field(default_factory=list)


def kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    return {".pdf": "pdf", ".docx": "docx", ".docm": "docx", ".pptx": "pptx", ".pptm": "pptx"}.get(suffix, "")


def discover_documents(path: Path, kinds: tuple[str, ...] = ("docx", "pptx", "pdf")) -> list[Path]:
    """A document, or the documents of a folder and the folders inside it, of the kinds asked for, in a stable order.
    A file Word or PowerPoint keeps beside an open document ("~$name") is no document."""
    if path.is_file():
        return [path] if kind_of(path) in kinds else []
    return sorted(item for item in path.rglob("*") if item.is_file() and kind_of(item) in kinds and not item.name.startswith("~$"))


def scan(path: Path) -> Scan:
    kind = kind_of(path)
    try:
        if kind == "pdf":
            return scan_pdf(path)
        if kind in ("docx", "pptx"):
            return scan_ooxml(path, kind)
    except Exception as error:  # noqa: BLE001 - one document that does not read is its own refusal
        # A part that does not parse stopped the whole batch, the documents after it untouched and
        # the summary unwritten (the audit of 15.10.2026, F10).
        return Scan(path, kind, refusal=f"the document does not read: {type(error).__name__}: {error}")
    return Scan(path, "", refusal=f"not a DOCX, PPTX or PDF: {path.name}")


# ------------------------------------------------------------------------------------------ pictures


def read_picture(part: str, data: bytes) -> Picture:
    """What a picture file is: its pixels, how it is stored, the density it states, whether it has a mask."""
    picture = Picture(part=part)
    if Path(part).suffix.lower() in VECTOR:
        picture.stored = Path(part).suffix.lower().lstrip(".")
        picture.note = "vector picture: not measured, not changed"
        return picture
    try:
        with Image.open(io.BytesIO(data)) as image:
            picture.pixels = (int(image.width), int(image.height))
            picture.stored = (image.format or Path(part).suffix.lstrip(".")).lower()
            picture.mode = image.mode
            dpi = image.info.get("dpi")
            if dpi and all(float(value) > 0 for value in dpi[:2]):
                picture.label = (round(float(dpi[0]), 2), round(float(dpi[1]), 2))
            picture.alpha = image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)
    except Exception as error:  # a picture Pillow does not read is named, not guessed
        picture.stored = Path(part).suffix.lower().lstrip(".")
        picture.note = f"not read: {error}"
    return picture


def jfif_density(raw: bytes) -> tuple[float, float] | None:
    """The density a JPEG stream states of itself in JFIF, in dots per inch; None when it states none."""
    if raw[:2] != b"\xff\xd8":
        return None
    at = 2
    while at + 4 <= len(raw) and raw[at] == 0xFF:
        marker = raw[at + 1]
        size = int.from_bytes(raw[at + 2:at + 4], "big")
        if marker == 0xE0 and raw[at + 4:at + 9] == b"JFIF\x00":
            units = raw[at + 11]
            x, y = int.from_bytes(raw[at + 12:at + 14], "big"), int.from_bytes(raw[at + 14:at + 16], "big")
            if units == 1 and x and y:
                return float(x), float(y)
            if units == 2 and x and y:
                return round(x * 2.54, 2), round(y * 2.54, 2)
            return None
        if marker == 0xDA:
            break
        at += 2 + size
    return None


# ------------------------------------------------------------------------------------------ PDF


def _signed_field(fields, kind=None, depth: int = 0) -> bool:
    """A filled signature field among the fields of a form and their kids; the kind of a field is inherited (/FT)."""
    if fields is None or depth > 32:
        return False
    for entry in fields:
        try:
            own = entry.get("/FT", kind)
            if own == "/Sig" and entry.get("/V") is not None:
                return True
            if _signed_field(entry.get("/Kids"), own, depth + 1):
                return True
        except (AttributeError, TypeError):
            continue
    return False


def pdf_refusal(path: Path) -> str:
    """Why a PDF must not be changed: it is encrypted, or it carries a signature a change would break.

    A signature is known by any of its marks, none taken as the only one: the flag of the form
    (/SigFlags), a filled field of the kind /Sig, a signature dictionary - /ByteRange with its
    /Contents, whatever its /Type says (the key is optional, ISO 32000-1, table 252) - and the
    rights of the document (/Perms). Known by /Type /Sig alone, a signed PDF without that optional
    key was changed and called done (the audit of 15.10.2026, F03)."""
    import pikepdf

    signed = "the PDF is signed: a change would break the signature, refused"
    try:
        with pikepdf.open(path) as pdf:
            if pdf.is_encrypted:
                return "the PDF is encrypted: a change is refused"
            root = pdf.Root
            if "/Perms" in root:
                return signed
            form = root.get("/AcroForm")
            if form is not None and (int(form.get("/SigFlags", 0)) & 1 or _signed_field(form.get("/Fields"))):
                return signed
            for obj in pdf.objects:
                if isinstance(obj, pikepdf.Dictionary) and "/ByteRange" in obj and ("/Contents" in obj or obj.get("/Type") == "/Sig"):
                    return signed
    except pikepdf.PasswordError:
        return "the PDF asks for a password: refused"
    return ""


def scan_pdf(path: Path) -> Scan:
    import pymupdf

    result = Scan(path, "pdf")
    try:
        result.refusal = pdf_refusal(path)
    except Exception as error:
        result.refusal = f"the PDF is not read: {error}"
        return result
    doc = pymupdf.open(path)
    try:
        for page in doc:
            for info in page.get_image_info(xrefs=True):
                xref = int(info.get("xref") or 0)
                a, b, c, d, _e, _f = info["transform"]
                size = (math.hypot(a, b) / 72, math.hypot(c, d) / 72)
                if xref == 0:
                    # A picture written into the page itself (BI ... EI): named, never rewritten.
                    picture = Picture(part="inline", pixels=(int(info["width"]), int(info["height"])), stored="inline",
                                      note="inline picture of the page: not changed")
                    result.placements.append(Placement(path, f"page {page.number + 1}", picture, size, note=picture.note))
                    continue
                key = f"xref {xref}"
                picture = result.pictures.get(key)
                if picture is None:
                    picture = Picture(part=key, pixels=(int(info["width"]), int(info["height"])))
                    kind, filters = doc.xref_get_key(xref, "Filter")
                    picture.stored = "uncompressed" if kind == "null" else filters.replace("/", "").replace("[", "").replace("]", "").strip()
                    picture.alpha = doc.xref_get_key(xref, "SMask")[0] not in ("null", "")
                    if "DCT" in picture.stored:
                        try:
                            picture.label = jfif_density(doc.xref_stream_raw(xref)[:65536])
                        except Exception:
                            picture.label = None
                    result.pictures[key] = picture
                result.placements.append(Placement(path, f"page {page.number + 1}", picture, size))
    finally:
        doc.close()
    return result


# ------------------------------------------------------------------------------------------ DOCX and PPTX


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, bool]]:
    """The relationships of a part: id -> (the part it points to, or the outside target; whether it is outside)."""
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", name + ".rels")
    if rels_name not in archive.namelist():
        return {}
    root = etree.fromstring(archive.read(rels_name))
    found: dict[str, tuple[str, bool]] = {}
    for rel in root.findall("rel:Relationship", NS):
        target = rel.get("Target", "")
        outside = rel.get("TargetMode") == "External"
        if not outside:
            target = posixpath.normpath(posixpath.join(folder, target)) if not target.startswith("/") else target.lstrip("/")
        found[rel.get("Id", "")] = (target, outside)
    return found


def _rels_of_type(archive: zipfile.ZipFile, part: str, kind: str) -> list[str]:
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", name + ".rels")
    if rels_name not in archive.namelist():
        return []
    root = etree.fromstring(archive.read(rels_name))
    return [posixpath.normpath(posixpath.join(folder, rel.get("Target", ""))) for rel in root.findall("rel:Relationship", NS)
            if rel.get("Type", "").endswith("/" + kind)]


def _local(element) -> str:
    return etree.QName(element).localname


def _ext(xfrm) -> tuple[float, float] | None:
    if xfrm is None:
        return None
    ext = xfrm.find("a:ext", NS)
    if ext is None:
        return None
    try:
        return float(ext.get("cx")), float(ext.get("cy"))
    except (TypeError, ValueError):
        return None


def _group_scale(element) -> tuple[float, float, object]:
    """How much the groups over an element stretch it, and the outermost group (None when there is none)."""
    scale_x = scale_y = 1.0
    top = None
    for ancestor in element.iterancestors():
        name = _local(ancestor)
        if name not in ("grpSp", "wgp"):
            continue
        group_pr = next((child for child in ancestor if _local(child) == "grpSpPr"), None)
        xfrm = group_pr.find("a:xfrm", NS) if group_pr is not None else None
        if xfrm is not None:
            ext, child = xfrm.find("a:ext", NS), xfrm.find("a:chExt", NS)
            try:
                if ext is not None and child is not None and float(child.get("cx")) > 0 and float(child.get("cy")) > 0:
                    scale_x *= float(ext.get("cx")) / float(child.get("cx"))
                    scale_y *= float(ext.get("cy")) / float(child.get("cy"))
            except (TypeError, ValueError):
                pass
        top = ancestor
    return scale_x, scale_y, top


def _crop(blip_fill) -> tuple[float, float, float, float]:
    rect = blip_fill.find("a:srcRect", NS) if blip_fill is not None else None
    if rect is None:
        return (0.0, 0.0, 0.0, 0.0)
    def share(name: str) -> float:
        try:
            return float(rect.get(name, "0")) / 100000
        except ValueError:
            return 0.0
    return (share("l"), share("t"), share("r"), share("b"))


def _own_xfrm(holder):
    """The `a:xfrm` of the picture or of the shape a picture fills."""
    if _local(holder) == "spPr":
        return holder.find("a:xfrm", NS)
    sp_pr = next((child for child in holder if _local(child) == "spPr"), None)
    return sp_pr.find("a:xfrm", NS) if sp_pr is not None else None


def _drawing_size(blip, holder) -> tuple[float, float] | None:
    """The size a DrawingML picture is placed at, in EMU."""
    scale_x, scale_y, top = _group_scale(holder)
    anchor = next((ancestor for ancestor in holder.iterancestors() if _local(ancestor) in ("inline", "anchor")
                   and etree.QName(ancestor).namespace == NS["wp"]), None)
    extent = None
    if anchor is not None:
        node = anchor.find("wp:extent", NS)
        if node is not None:
            try:
                extent = (float(node.get("cx")), float(node.get("cy")))
            except (TypeError, ValueError):
                extent = None
    own = _ext(_own_xfrm(holder))
    if top is None:
        # A picture of its own in a Word drawing is as large as the drawing; elsewhere its own size counts.
        return extent or own
    if own is None:
        return None
    size = (own[0] * scale_x, own[1] * scale_y)
    if extent is not None:
        # The outermost group of a Word drawing may stand at another size than the drawing: the drawing counts.
        group_pr = next((child for child in top if _local(child) == "grpSpPr"), None)
        outer = _ext(group_pr.find("a:xfrm", NS)) if group_pr is not None else None
        if outer and outer[0] > 0 and outer[1] > 0:
            size = (size[0] * extent[0] / outer[0], size[1] * extent[1] / outer[1])
    return size


_LENGTH = re.compile(r"(-?[\d.]+)\s*(pt|in|cm|mm|px|pc|emu)?", re.IGNORECASE)


def _vml_length(text: str) -> float | None:
    """A VML length as EMU: "123.4pt", "2in", "5cm"."""
    match = _LENGTH.fullmatch(text.strip())
    if not match:
        return None
    value, unit = float(match.group(1)), (match.group(2) or "px").lower()
    per_inch = {"pt": 72, "in": 1, "cm": 2.54, "mm": 25.4, "px": 96, "pc": 6, "emu": EMU_PER_INCH}[unit]
    return value / per_inch * EMU_PER_INCH


def _vml_size(shape) -> tuple[float, float] | None:
    style = dict(
        (key.strip().lower(), value.strip())
        for key, _, value in (item.partition(":") for item in (shape.get("style") or "").split(";"))
        if key.strip()
    )
    width, height = _vml_length(style.get("width", "")), _vml_length(style.get("height", ""))
    return (width, height) if width and height else None


def _placeholder_size(archive: zipfile.ZipFile, part: str, holder) -> tuple[float, float] | None:
    """A placeholder picture without a size of its own: the size of its placeholder in the layout, then in the master."""
    ph = holder.find(".//p:nvPr/p:ph", NS)
    if ph is None:
        return None
    idx, kind = ph.get("idx"), ph.get("type")
    for parent_kind in ("slideLayout", "slideMaster"):
        parents = _rels_of_type(archive, part, parent_kind)
        if not parents:
            continue
        part = parents[0]
        root = etree.fromstring(archive.read(part))
        for other in root.iter(f"{{{NS['p']}}}ph"):
            if (idx is not None and other.get("idx") == idx) or (idx is None and kind is not None and other.get("type") == kind):
                shape = next((ancestor for ancestor in other.iterancestors() if _local(ancestor) in ("sp", "pic")), None)
                size = _ext(_own_xfrm(shape)) if shape is not None else None
                if size:
                    return size
    return None


def _slide_size(archive: zipfile.ZipFile) -> tuple[float, float] | None:
    if "ppt/presentation.xml" not in archive.namelist():
        return None
    node = etree.fromstring(archive.read("ppt/presentation.xml")).find("p:sldSz", NS)
    try:
        return (float(node.get("cx")), float(node.get("cy"))) if node is not None else None
    except (TypeError, ValueError):
        return None


def _place_name(part: str, kind: str) -> str:
    name = posixpath.basename(part)
    number = re.search(r"(\d+)\.xml$", name)
    if kind == "pptx":
        for folder, word in (("ppt/slides/", "slide"), ("ppt/slideLayouts/", "layout"), ("ppt/slideMasters/", "master")):
            if part.startswith(folder):
                return f"{word} {number.group(1)}" if number else word
    # word/document.xml - "document", word/header2.xml - "header2".
    return posixpath.splitext(name)[0]


def _ooxml_parts(archive: zipfile.ZipFile, kind: str) -> list[str]:
    names = archive.namelist()
    if kind == "docx":
        parts = [name for name in names if re.fullmatch(r"word/[^/]+\.xml", name) and posixpath.join("word/_rels", posixpath.basename(name) + ".rels") in names]
    else:
        parts = [name for name in names if re.fullmatch(r"ppt/(slides|slideLayouts|slideMasters)/[^/]+\.xml", name)]
    def order(name: str):
        number = re.search(r"(\d+)\.xml$", name)
        group = 0 if "/slides/" in name or name == "word/document.xml" else 1 if "Layouts" in name else 2
        return (group, posixpath.dirname(name), int(number.group(1)) if number else 0, name)
    return sorted(parts, key=order)


def ooxml_refusal(archive: zipfile.ZipFile) -> str:
    if any(SIGNATURE_PART.match(name) for name in archive.namelist()):
        return "the document carries a digital signature: a change would break it, refused"
    return ""


def scan_ooxml(path: Path, kind: str) -> Scan:
    result = Scan(path, kind)
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        result.refusal = "not a DOCX or PPTX package (not a ZIP)"
        return result
    with archive:
        names = set(archive.namelist())
        marker = "word/document.xml" if kind == "docx" else "ppt/presentation.xml"
        if marker not in names:
            result.refusal = f"the package has no {marker}: not a {kind.upper()}"
            return result
        result.refusal = ooxml_refusal(archive)
        slide = _slide_size(archive) if kind == "pptx" else None

        def picture_of(target: str, outside: bool) -> Picture:
            if outside:
                return Picture(part=target, note="linked picture outside the document: not changed")
            if target not in result.pictures:
                if target not in names:
                    result.pictures[target] = Picture(part=target, note="the picture named by the document is missing in it")
                else:
                    result.pictures[target] = read_picture(target, archive.read(target))
            return result.pictures[target]

        for part in _ooxml_parts(archive, kind):
            rels = _rels(archive, part)
            if not rels:
                continue
            root = etree.fromstring(archive.read(part))
            place = _place_name(part, kind)
            for blip in root.iter(f"{{{NS['a']}}}blip"):
                rid = blip.get(R_EMBED) or blip.get(R_LINK)
                if not rid or rid not in rels:
                    continue
                target, outside = rels[rid]
                outside = outside or (blip.get(R_LINK) is not None and blip.get(R_EMBED) is None)
                picture = picture_of(target, outside)
                blip_fill = blip.getparent()
                holder = blip_fill.getparent() if blip_fill is not None else None
                if holder is None:
                    continue
                note = picture.note
                if _local(holder) == "bgPr":
                    size = slide
                    if blip_fill.find("a:tile", NS) is not None:
                        note = note or "tiled background: drawn at its own size, not measured"
                        size = None
                else:
                    size = _drawing_size(blip, holder)
                    if size is None and kind == "pptx":
                        size = _placeholder_size(archive, part, holder)
                in_inches = None if size is None else (size[0] / EMU_PER_INCH, size[1] / EMU_PER_INCH)
                if in_inches is None and not note:
                    note = "the size it is placed at is not written: not measured"
                result.placements.append(Placement(path, place, picture, in_inches, _crop(blip_fill), note))
            if kind == "docx":
                for data in root.iter(f"{{{NS['v']}}}imagedata"):
                    rid = data.get(R_ID) or data.get(O_RELID)
                    if not rid or rid not in rels:
                        continue
                    target, outside = rels[rid]
                    picture = picture_of(target, outside)
                    shape = data.getparent()
                    size = _vml_size(shape) if shape is not None else None
                    in_inches = None if size is None else (size[0] / EMU_PER_INCH, size[1] / EMU_PER_INCH)
                    note = picture.note or ("" if in_inches else "the size it is placed at is not written: not measured")
                    result.placements.append(Placement(path, place + " (VML)", picture, in_inches, note=note))
    return result


def lowest_ppi(placements: list[Placement]) -> dict[str, float]:
    """The resolution of every picture by its largest placement - the lowest of its placements."""
    lowest: dict[str, float] = {}
    for placement in placements:
        ppi = placement.ppi
        if ppi is None:
            continue
        part = placement.picture.part
        lowest[part] = min(lowest.get(part, ppi), ppi)
    return lowest
