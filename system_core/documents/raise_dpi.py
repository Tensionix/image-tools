"""The copy of a document whose pictures reach a resolution, with the check of the copy built in.

Only the streams of the pictures are written: the text, the pages, the place and the size of every
picture stay as they are. A picture below the threshold gets pixels - every pixel repeated as a
square of 2 x 2 (3 x 3 when two are not enough), or a smooth Lanczos resample; a picture already at
the threshold keeps its pixels and only states the threshold of itself (JFIF and EXIF of a JPEG,
pHYs of a PNG, in place). A picture used several times is counted by its largest placement.

DOCX and PPTX get the flag that keeps Word and PowerPoint from compressing the pictures back when
they save the copy (measured 14.10.2026: without it Word took a picture of 1200 ppi back to 220 at
the first save): `w:doNotAutoCompressPictures` in word/settings.xml, `autoCompressPictures="0"` on
the presentation.

The copy is checked before it is called done: the resolution of every placement counted again (in
a PDF by a second reader, the page streams walked by pikepdf), the place and the size of every
placement, the pages and their text, the look of every page that holds a changed picture. What did
not hold makes the outcome "partial" and is named.
"""
from __future__ import annotations

import io
import math
import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from PIL import Image, ImageChops, ImageStat

from .density import restate, restate_jpeg
from .placements import NS, VECTOR, Scan, lowest_ppi, scan

# A picture is not raised past this many pixels: a document is no place for a poster.
MOST_PIXELS = 150_000_000
Image.MAX_IMAGE_PIXELS = MOST_PIXELS * 2


@dataclass
class Options:
    threshold: int = 300
    # "actual" - pixels and the label; "label" - the label alone, no pixel is added.
    what: str = "actual"
    # "repeat" - every pixel a square; "smooth" - Lanczos.
    method: str = "repeat"
    jpeg_quality: int = 95
    # A picture stored without loss (PNG, Flate) stays without loss; off - it becomes a JPEG.
    keep_lossless: bool = False
    # On - Word and PowerPoint stay free to compress the pictures when they save the copy.
    office_may_compress: bool = False


@dataclass
class Change:
    part: str
    action: str
    pixels_before: tuple[int, int] | None = None
    pixels_after: tuple[int, int] | None = None
    ppi_before: float | None = None
    ppi_after: float | None = None
    stored_before: str = ""
    stored_after: str = ""
    renamed_to: str = ""


@dataclass
class Outcome:
    document: Path
    output: Path | None
    status: str = "done"
    reason: str = ""
    changes: list[Change] = field(default_factory=list)
    checks: list[tuple[bool, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # The numbers of what was done, for the window to say in its own language (summary.json).
    facts: dict = field(default_factory=dict)

    def check(self, ok: bool, text: str) -> None:
        self.checks.append((ok, text))
        if not ok and self.status == "done":
            self.status = "partial"


# ------------------------------------------------------------------------------------------ pictures


def target_pixels(pixels: tuple[int, int], ppi: float, options: Options) -> tuple[int, int] | None:
    """The pixels a picture at `ppi` needs to reach the threshold; None when it is there already."""
    if ppi >= options.threshold:
        return None
    width, height = pixels
    if options.method == "repeat":
        times = max(2, math.ceil(options.threshold / ppi))
        return width * times, height * times
    scale = options.threshold * 1.01 / ppi
    return math.ceil(width * scale), math.ceil(height * scale)


def resized(image: Image.Image, size: tuple[int, int], method: str) -> Image.Image:
    # A palette, one bit to a pixel, a mask of ones and noughts: only whole pixels make sense.
    smooth = method == "smooth" and image.mode not in ("P", "1", "PA")
    return image.resize(size, Image.LANCZOS if smooth else Image.NEAREST)


def encode_jpeg(image: Image.Image, options: Options, icc: bytes | None, exif: bytes | None) -> bytes:
    if image.mode not in ("RGB", "L", "CMYK"):
        image = image.convert("RGB")
    out = io.BytesIO()
    extra = {}
    if icc:
        extra["icc_profile"] = icc
    if exif:
        extra["exif"] = exif
    image.save(out, "JPEG", quality=options.jpeg_quality, subsampling=0, optimize=True,
               dpi=(options.threshold, options.threshold), **extra)
    # Pillow writes the density into JFIF; an EXIF carried over still says the old one.
    return restate_jpeg(out.getvalue(), options.threshold)


def encode_png(image: Image.Image, options: Options, icc: bytes | None) -> bytes:
    out = io.BytesIO()
    extra = {"icc_profile": icc} if icc else {}
    image.save(out, "PNG", optimize=False, compress_level=6, dpi=(options.threshold, options.threshold), **extra)
    return out.getvalue()


def lossless_only(image: Image.Image) -> bool:
    """A picture that must stay without loss whatever the form says: a mask, a palette, one bit, more than 8 bits."""
    return image.mode in ("RGBA", "LA", "PA", "P", "1", "I", "I;16", "I;16B", "F") or "transparency" in image.info


# ------------------------------------------------------------------------------------------ DOCX and PPTX

CONTENT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}


def _free_name(part: str, extension: str, taken: set[str]) -> str:
    folder, name = posixpath.split(part)
    stem = posixpath.splitext(name)[0]
    candidate = posixpath.join(folder, f"{stem}.{extension}")
    number = 2
    while candidate in taken:
        candidate = posixpath.join(folder, f"{stem}_{number}.{extension}")
        number += 1
    return candidate


def _rewrite_rels(data: bytes, rels_name: str, renamed: dict[str, str]) -> bytes:
    """The targets of a relationships part that point to a renamed picture, pointed to its new name."""
    folder = posixpath.dirname(posixpath.dirname(rels_name))
    root = etree.fromstring(data)
    changed = False
    for rel in root.findall("rel:Relationship", NS):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        if resolved in renamed:
            new = renamed[resolved]
            rel.set("Target", "/" + new if target.startswith("/") else posixpath.relpath(new, folder or "."))
            changed = True
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if changed else data


def _rewrite_content_types(data: bytes, renamed: dict[str, str]) -> bytes:
    root = etree.fromstring(data)
    space = root.nsmap.get(None, "http://schemas.openxmlformats.org/package/2006/content-types")
    defaults = {(node.get("Extension") or "").lower() for node in root.findall(f"{{{space}}}Default")}
    for node in list(root.findall(f"{{{space}}}Override")):
        if (node.get("PartName") or "").lstrip("/") in renamed:
            root.remove(node)
    for new in renamed.values():
        extension = posixpath.splitext(new)[1].lstrip(".").lower()
        if extension not in defaults:
            element = etree.SubElement(root, f"{{{space}}}Default")
            element.set("Extension", extension)
            element.set("ContentType", CONTENT_TYPES[extension])
            # A Default stands before the first Override, as Office writes them.
            first = root.find(f"{{{space}}}Override")
            if first is not None:
                root.remove(element)
                first.addprevious(element)
            defaults.add(extension)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


# The elements of w:settings that come after w:doNotAutoCompressPictures in the order of the schema.
_AFTER_FLAG = re.compile(rb"<(w:forceUpgrade|w:captions|w:readModeInkLockDown|w:smartTagType|sl:schemaLibrary|w:shapeDefaults|"
                         rb"w:doNotEmbedSmartTags|w:decimalSymbol|w:listSeparator|w14:|w15:|w16)")


# The element in the settings of Word, with its prefix and its attributes; written empty or with its closing tag.
_WORD_FLAG = re.compile(rb"<(?P<prefix>[\w.-]+:)?doNotAutoCompressPictures\b(?P<attrs>[^>]*?)"
                        rb"(?:/>|>\s*</(?:[\w.-]+:)?doNotAutoCompressPictures>)")
_OFF = (b"0", b"false", b"off")


def word_compression_off(settings: bytes) -> bool:
    """Word is told not to compress the pictures: the element is there and does not say no (w:val 0, false, off)."""
    found = _WORD_FLAG.search(settings)
    if not found:
        return False
    value = re.search(rb'\bval="([^"]*)"', found["attrs"])
    return not value or value.group(1).strip().lower() not in _OFF


def powerpoint_compression_off(presentation: bytes) -> bool:
    return re.search(rb'<p:presentation\b[^>]*\sautoCompressPictures="(0|false)"', presentation) is not None


def keep_word_from_compressing(settings: bytes) -> bytes:
    """The settings of Word with the element on. One already there is written anew without its value: an element
    that says w:val="0" was taken for the flag set, and the copy let Word compress (the audit of 15.10.2026, F08)."""
    found = _WORD_FLAG.search(settings)
    if found:
        return settings[:found.start()] + b"<" + (found["prefix"] or b"") + b"doNotAutoCompressPictures/>" + settings[found.end():]
    match = _AFTER_FLAG.search(settings)
    at = match.start() if match else settings.rindex(b"</w:settings>")
    return settings[:at] + b"<w:doNotAutoCompressPictures/>" + settings[at:]


def keep_powerpoint_from_compressing(presentation: bytes) -> bytes:
    if re.search(rb'autoCompressPictures="(0|false)"', presentation):
        return presentation
    presentation = re.sub(rb'\sautoCompressPictures="[^"]*"', b"", presentation, count=1)
    return re.sub(rb"<p:presentation(\s|>)", rb'<p:presentation autoCompressPictures="0"\1', presentation, count=1)


def _new_picture(raw: bytes, part: str, size: tuple[int, int], options: Options) -> tuple[bytes, str, str]:
    """A picture of an OOXML package raised: its bytes, its extension, and how it is stored now.

    A JPEG stays a JPEG. A picture stored without loss becomes a JPEG unless the form keeps it without
    loss or it cannot lose anything - a mask, a palette, one bit, more than 8 bits: then a PNG.
    """
    with Image.open(io.BytesIO(raw)) as source:
        source.load()
        icc = source.info.get("icc_profile")
        was_jpeg = source.format == "JPEG"
        exif = source.info.get("exif") if was_jpeg else None
        must_keep = lossless_only(source)
        picture = resized(source, size, options.method)
    if was_jpeg:
        return encode_jpeg(picture, options, icc, exif), posixpath.splitext(part)[1].lstrip(".").lower(), "jpeg"
    if options.keep_lossless or must_keep:
        return encode_png(picture, options, icc), "png", "png"
    return encode_jpeg(picture, options, icc, None), "jpg", "jpeg"


def raise_ooxml(found: Scan, output: Path, options: Options, step=None) -> Outcome:
    outcome = Outcome(found.document, output)
    lowest = lowest_ppi(found.placements)
    replaced: dict[str, bytes] = {}
    renamed: dict[str, str] = {}
    with zipfile.ZipFile(found.document) as archive:
        taken = set(archive.namelist())
        for part, picture in found.pictures.items():
            if step:
                step()
            change = Change(part, "", picture.pixels, picture.pixels, lowest.get(part), lowest.get(part), picture.stored, picture.stored)
            outcome.changes.append(change)
            if picture.note or picture.pixels is None:
                change.action = "not changed: " + (picture.note or "not read")
                continue
            if part not in lowest:
                change.action = "not changed: its placement has no size"
                continue
            raw = archive.read(part)
            ppi = lowest[part]
            size = target_pixels(picture.pixels, ppi, options) if options.what == "actual" else None
            if size and size[0] * size[1] > MOST_PIXELS:
                change.action = f"not changed: {size[0]} x {size[1]} would be more than {MOST_PIXELS // 1_000_000} MP"
                continue
            if not size:
                stated = restate(raw, options.threshold)
                if stated is None:
                    change.action = f"not changed: a {picture.stored.upper()} file keeps no density to state in place"
                    continue
                replaced[part] = stated
                change.action = "label only" if picture.label != (options.threshold, options.threshold) else "label already right"
                if options.what == "label" and ppi < options.threshold:
                    change.action = "label only (pixels below the threshold, as asked)"
                continue
            data, extension, stored = _new_picture(raw, part, size, options)
            current = posixpath.splitext(part)[1].lstrip(".").lower()
            if extension != current and not (extension in ("jpg", "jpeg") and current in ("jpg", "jpeg")):
                new_part = _free_name(part, extension, taken | set(renamed.values()))
                renamed[part] = new_part
                change.renamed_to = new_part
            replaced[part] = data
            change.pixels_after = size
            change.ppi_after = ppi * size[0] / picture.pixels[0]
            change.stored_after = stored
            change.action = f"raised x{size[0] / picture.pixels[0]:.2f}".replace(".00", "")

        flag_part = "word/settings.xml" if found.kind == "docx" else "ppt/presentation.xml"
        temp = output.with_name(output.name + ".writing")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as copy:
            for info in archive.infolist():
                name = info.filename
                data = archive.read(name)
                if name in replaced:
                    data = replaced[name]
                    if name in renamed:
                        info = zipfile.ZipInfo(renamed[name], date_time=info.date_time)
                        info.compress_type = zipfile.ZIP_DEFLATED
                elif name.endswith(".rels") and renamed:
                    data = _rewrite_rels(data, name, renamed)
                elif name == "[Content_Types].xml" and renamed:
                    data = _rewrite_content_types(data, renamed)
                if name == flag_part and not options.office_may_compress:
                    data = keep_word_from_compressing(data) if found.kind == "docx" else keep_powerpoint_from_compressing(data)
                copy.writestr(info, data, compress_type=zipfile.ZIP_STORED if info.compress_type == zipfile.ZIP_STORED else zipfile.ZIP_DEFLATED)
        temp.replace(output)
    if not options.office_may_compress:
        # Said only as it is found in the copy written.
        with zipfile.ZipFile(output) as written:
            flag = written.read(flag_part) if flag_part in written.namelist() else b""
        held = word_compression_off(flag) if found.kind == "docx" else powerpoint_compression_off(flag)
        outcome.check(held, ("Word" if found.kind == "docx" else "PowerPoint") + " is told not to compress the pictures when it saves the copy")
    check_ooxml(found, outcome, options, renamed)
    return outcome


def check_reached(found: Scan, outcome: Outcome, options: Options) -> None:
    """A picture left below the threshold - inline in a PDF page, linked, too large to raise, of a kind not handled - is named:
    the copy is then not done but partial, whatever else holds."""
    if options.what != "actual":
        return
    why = {change.part: change.action for change in outcome.changes}
    left: dict[str, str] = {}
    for placement in found.placements:
        part = placement.picture.part
        if placement.ppi is None or placement.ppi >= options.threshold - 0.5 or why.get(part, "").startswith("raised"):
            continue
        left.setdefault(f"{placement.place} {part}", f"{placement.ppi:.0f} ppi, {why.get(part) or placement.note or 'not changed'}")
    outcome.check(not left, f"every picture below {options.threshold} ppi is raised"
                  + (f"; left below: {len(left)} - " + "; ".join(f"{key}: {value}" for key, value in list(left.items())[:3]) if left else ""))
    # A picture whose pixels are not known - linked from outside, missing, unreadable - is not checked against the
    # threshold: the copy is partial, not done. A vector picture has no pixels to count and is no such case. Skipped
    # silently, a linked picture let the copy be called done (the audit of 15.10.2026, F09).
    unknown = {f"{placement.place} {placement.picture.part}": placement.note or placement.picture.note or "not measured"
               for placement in found.placements
               if placement.ppi is None and Path(placement.picture.part).suffix.lower() not in VECTOR}
    if unknown:
        outcome.check(False, f"{len(unknown)} placements not measured - the threshold is not checked on them: "
                      + "; ".join(f"{key}: {value}" for key, value in list(unknown.items())[:3]))


def check_ooxml(found: Scan, outcome: Outcome, options: Options, renamed: dict[str, str]) -> None:
    """The copy read anew: the package, every placement, every changed picture."""
    check_reached(found, outcome, options)
    try:
        with zipfile.ZipFile(outcome.output) as archive:
            outcome.check(archive.testzip() is None, "the copy is a whole ZIP package")
            bad = []
            for name in archive.namelist():
                if name.endswith(".xml") or name.endswith(".rels"):
                    try:
                        etree.fromstring(archive.read(name))
                    except etree.XMLSyntaxError as error:
                        bad.append(f"{name}: {error}")
            outcome.check(not bad, "every XML part of the copy reads" + (f": {bad[:2]}" if bad else ""))
            with zipfile.ZipFile(found.document) as source:
                touched = set(found.pictures) | {"word/settings.xml", "ppt/presentation.xml", "[Content_Types].xml"}
                differ = [name for name in source.namelist()
                          if name not in touched and not name.endswith(".rels") and name in archive.namelist() and source.read(name) != archive.read(name)]
                outcome.check(not differ, "every part that is no picture is the same byte for byte" + (f": {differ[:3]}" if differ else ""))
    except zipfile.BadZipFile as error:
        outcome.check(False, f"the copy is not a ZIP package: {error}")
        return
    again = scan(outcome.output)
    outcome.check(len(again.placements) == len(found.placements), f"placements: {len(found.placements)} before, {len(again.placements)} after")
    moved = [a.place for a, b in zip(found.placements, again.placements)
             if a.place != b.place or (a.size_in is None) != (b.size_in is None)
             or (a.size_in and b.size_in and any(abs(x - y) > 1e-9 for x, y in zip(a.size_in, b.size_in)))]
    outcome.check(not moved, "every picture stands in the same place at the same size" + (f": {moved[:3]}" if moved else ""))
    raised = {change.renamed_to or change.part for change in outcome.changes if change.action.startswith("raised")}
    if options.what == "actual":
        low = [f"{p.place} {p.picture.part}: {p.ppi:.0f}" for p in again.placements
               if p.picture.part in raised and p.ppi is not None and p.ppi < options.threshold - 0.5]
        outcome.check(not low, f"every raised picture is at {options.threshold} ppi or more" + (f": {low[:3]}" if low else ""))
    labelled = {change.renamed_to or change.part for change in outcome.changes if change.action.startswith(("raised", "label"))}
    wrong = [part for part, picture in again.pictures.items() if part in labelled
             and (picture.label is None or (round(picture.label[0]), round(picture.label[1])) != (options.threshold, options.threshold))]
    outcome.check(not wrong, f"every written picture states {options.threshold} dpi of itself" + (f": {wrong[:3]}" if wrong else ""))
    if options.method == "repeat":
        far = []
        with zipfile.ZipFile(found.document) as source, zipfile.ZipFile(outcome.output) as copy:
            for change in outcome.changes:
                if not change.action.startswith("raised"):
                    continue
                with Image.open(io.BytesIO(source.read(change.part))) as old, Image.open(io.BytesIO(copy.read(change.renamed_to or change.part))) as new:
                    mean = _apart(old, new)
                    if mean >= 2.0:
                        far.append(f"{change.part}: {mean:.2f}")
        outcome.check(not far, "brought back to their old pixels, the raised pictures are the old ones (mean difference under 2 of 255)"
                      + (f": {far[:3]}" if far else ""))


def _apart(old: Image.Image, new: Image.Image) -> float:
    """How far a raised picture brought back to the old pixels is from the old one, on average, of 255."""
    mode = "RGB" if old.mode not in ("L", "1") else "L"
    back = new.convert(mode).resize(old.size, Image.BOX)
    diff = ImageChops.difference(old.convert(mode), back)
    stat = ImageStat.Stat(diff).mean
    return sum(stat) / len(stat)


# ------------------------------------------------------------------------------------------ PDF


def _pdf_matrix(m, n):
    return (m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3], m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5])


def walk_pdf(path: Path) -> list[tuple[int, int, int, int, float, float]]:
    """The second reader of a PDF: the page streams walked by pikepdf. (page, object, width, height, inches wide, inches high)."""
    import pikepdf

    found: list[tuple[int, int, int, int, float, float]] = []

    def walk(owner, resources, ctm, number, depth):
        if depth > 12:
            return
        stack = []
        for operands, operator in pikepdf.parse_content_stream(owner):
            op = str(operator)
            if op == "q":
                stack.append(ctm)
            elif op == "Q":
                ctm = stack.pop() if stack else ctm
            elif op == "cm":
                ctm = _pdf_matrix(tuple(float(v) for v in operands), ctm)
            elif op == "Do" and resources is not None and "/XObject" in resources:
                target = resources.XObject.get(str(operands[0]))
                if target is None:
                    continue
                if target.get("/Subtype") == "/Image":
                    found.append((number, target.objgen[0], int(target.Width), int(target.Height),
                                  math.hypot(ctm[0], ctm[1]) / 72, math.hypot(ctm[2], ctm[3]) / 72))
                elif target.get("/Subtype") == "/Form":
                    inner = tuple(float(v) for v in target.get("/Matrix", [1, 0, 0, 1, 0, 0]))
                    walk(target, target.get("/Resources", resources), _pdf_matrix(inner, ctm), number, depth + 1)

    with pikepdf.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            walk(page, page.get("/Resources"), (1, 0, 0, 1, 0, 0), number, 0)
    return found


def _pdf_picture(obj):
    """A picture of a PDF as Pillow reads it, with what is needed to write it back; None and the reason when it is not handled."""
    import pikepdf

    filters = obj.get("/Filter")
    names = [str(item) for item in filters] if isinstance(filters, pikepdf.Array) else [str(filters)] if filters is not None else []
    if any(name in ("/JBIG2Decode", "/JPXDecode") for name in names):
        return None, f"stored as {names[-1].lstrip('/')}: not changed"
    bits = int(obj.get("/BitsPerComponent", 8))
    space = obj.get("/ColorSpace")
    if bool(obj.get("/ImageMask", False)):
        return None, "a stencil mask: not changed"
    if names == ["/DCTDecode"]:
        raw = obj.read_raw_bytes()
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image, ""
    try:
        image = pikepdf.PdfImage(obj).as_pil_image()
    except Exception as error:
        return None, f"not read: {error}"
    if image.mode in ("RGBA", "LA") and "/SMask" in obj:
        # pikepdf hands the mask over with the picture; the mask is a stream of its own and is raised apart.
        image = image.convert(image.mode[:-1] if image.mode == "LA" else "RGB")
    if isinstance(space, pikepdf.Array) and str(space[0]) not in ("/ICCBased", "/Indexed"):
        return None, f"colour space {space[0]}: not changed"
    if bits not in (1, 8) and image.mode != "P":
        return None, f"{bits} bits to a component: not changed"
    return image, ""


def raise_pdf(found: Scan, output: Path, options: Options, step=None) -> Outcome:
    import pikepdf

    outcome = Outcome(found.document, output)
    lowest = lowest_ppi(found.placements)
    output.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.open(found.document) as pdf:
        for part, picture in found.pictures.items():
            if step:
                step()
            change = Change(part, "", picture.pixels, picture.pixels, lowest.get(part), lowest.get(part), picture.stored, picture.stored)
            outcome.changes.append(change)
            if part not in lowest or picture.pixels is None:
                change.action = "not changed: " + (picture.note or "its placement has no size")
                continue
            obj = pdf.get_object((int(part.split()[1]), 0))
            ppi = lowest[part]
            size = target_pixels(picture.pixels, ppi, options) if options.what == "actual" else None
            is_jpeg = obj.get("/Filter") == "/DCTDecode"
            if size and size[0] * size[1] > MOST_PIXELS:
                change.action = f"not changed: {size[0]} x {size[1]} would be more than {MOST_PIXELS // 1_000_000} MP"
                continue
            if not size:
                if is_jpeg:
                    obj.write(restate_jpeg(obj.read_raw_bytes(), options.threshold), filter=pikepdf.Name.DCTDecode)
                    change.action = "label only" if ppi >= options.threshold else "label only (pixels below the threshold, as asked)"
                else:
                    change.action = "not changed: a picture stored without JPEG states no density of itself"
                continue
            image, why = _pdf_picture(obj)
            if image is None:
                change.action = "not changed: " + why
                continue
            bigger = resized(image, size, options.method)
            lossless = options.keep_lossless and not is_jpeg or lossless_only(image) or image.mode in ("1", "P")
            if image.mode == "P" and isinstance(obj.get("/ColorSpace"), pikepdf.Array) and str(obj.ColorSpace[0]) == "/Indexed":
                # The indices themselves, repeated: the palette of the picture stays its own.
                bits = int(obj.get("/BitsPerComponent", 8))
                raw = bigger.tobytes("raw", {1: "P;1", 2: "P;2", 4: "P;4", 8: "P"}[bits])
                obj.write(zlib.compress(raw), filter=pikepdf.Name.FlateDecode)
                stored = "Flate"
            elif image.mode == "1":
                obj.write(zlib.compress(bigger.tobytes("raw", "1")), filter=pikepdf.Name.FlateDecode)
                obj.BitsPerComponent = 1
                stored = "Flate"
            elif lossless:
                mode = {"L": "L", "RGB": "RGB", "CMYK": "CMYK"}.get(bigger.mode)
                if mode is None:
                    change.action = f"not changed: a picture in {bigger.mode} kept without loss is not written"
                    continue
                obj.write(zlib.compress(bigger.tobytes()), filter=pikepdf.Name.FlateDecode)
                obj.BitsPerComponent = 8
                stored = "Flate"
            else:
                obj.write(encode_jpeg(bigger, options, None, None), filter=pikepdf.Name.DCTDecode)
                obj.BitsPerComponent = 8
                stored = "DCT"
            if "/DecodeParms" in obj:
                del obj["/DecodeParms"]
            obj.Width, obj.Height = size
            mask = obj.get("/SMask")
            if mask is not None:
                alpha = pikepdf.PdfImage(mask).as_pil_image().convert("L")
                mask.write(zlib.compress(resized(alpha, size, options.method).tobytes()), filter=pikepdf.Name.FlateDecode)
                mask.Width, mask.Height = size
                mask.BitsPerComponent = 8
                if "/DecodeParms" in mask:
                    del mask["/DecodeParms"]
            change.pixels_after = size
            change.ppi_after = ppi * size[0] / picture.pixels[0]
            change.stored_after = stored
            change.action = f"raised x{size[0] / picture.pixels[0]:.2f}".replace(".00", "")
        temp = output.with_name(output.name + ".writing")
        pdf.save(temp, object_stream_mode=pikepdf.ObjectStreamMode.preserve)
    temp.replace(output)
    check_pdf(found, outcome, options)
    return outcome


def check_pdf(found: Scan, outcome: Outcome, options: Options) -> None:
    import pikepdf
    import pymupdf

    check_reached(found, outcome, options)
    with pikepdf.open(found.document) as before, pikepdf.open(outcome.output) as after:
        check = getattr(after, "check_pdf_syntax", None) or getattr(after, "check")
        problems = check()
        outcome.check(not problems, "qpdf finds nothing wrong in the copy" + (f": {problems[:2]}" if problems else ""))
        outcome.check(len(before.pages) == len(after.pages), f"pages: {len(before.pages)} before, {len(after.pages)} after")
    was, now = walk_pdf(found.document), walk_pdf(outcome.output)
    outcome.check(len(was) == len(now), f"pictures drawn, counted by pikepdf: {len(was)} before, {len(now)} after")
    moved = [f"page {a[0]}" for a, b in zip(was, now) if a[0] != b[0] or abs(a[4] - b[4]) > 1e-6 or abs(a[5] - b[5]) > 1e-6]
    outcome.check(not moved, "every picture is drawn in the same place at the same size" + (f": {moved[:3]}" if moved else ""))
    # The copy is written with its objects numbered anew: a drawing of the copy is matched with the one
    # of the source by its place in the walk, never by the number of its object.
    raised_objects = {int(change.part.split()[1]) for change in outcome.changes if change.action.startswith("raised")}
    raised = [b for a, b in zip(was, now) if a[1] in raised_objects]
    outcome.check(len(raised) >= len(raised_objects), f"every raised picture is found drawn in the copy: {len(raised)} drawings of {len(raised_objects)} pictures")
    if options.what == "actual":
        low = [f"page {b[0]}: {min(b[2] / b[4], b[3] / b[5]):.0f}" for b in raised if min(b[2] / b[4], b[3] / b[5]) < options.threshold - 0.5]
        outcome.check(not low, f"pikepdf counts every raised picture at {options.threshold} ppi or more: {len(raised)} drawings" + (f"; below: {low[:3]}" if low else ""))
    # The density a JPEG states of itself, read back by MuPDF: placements in the order MuPDF traces the pages.
    written = {change.part for change in outcome.changes if change.action.startswith(("raised", "label")) and "DCT" in (change.stored_after or change.stored_before)}
    again = scan(outcome.output)
    wrong = [f"{a.place}" for a, b in zip(found.placements, again.placements) if a.picture.part in written
             and (b.picture.label is None or (round(b.picture.label[0]), round(b.picture.label[1])) != (options.threshold, options.threshold))]
    outcome.check(len(again.placements) == len(found.placements) and not wrong,
                  f"every written JPEG states {options.threshold} dpi of itself: {len(written)} pictures" + (f"; not: {wrong[:3]}" if wrong else ""))
    doc_a, doc_b = pymupdf.open(found.document), pymupdf.open(outcome.output)
    try:
        pymupdf.TOOLS.mupdf_warnings()
        texts = sum(1 for a, b in zip(doc_a, doc_b) if a.get_text() == b.get_text())
        outcome.check(texts == doc_a.page_count, f"the text of the pages is the same: {texts} of {doc_a.page_count}")
        pages = sorted({b[0] for b in raised})
        far = []
        for number in pages:
            pa, pb = doc_a[number - 1].get_pixmap(dpi=100), doc_b[number - 1].get_pixmap(dpi=100)
            ia = Image.frombytes("RGB" if pa.n < 4 else "RGBA", (pa.width, pa.height), pa.samples).convert("RGB")
            ib = Image.frombytes("RGB" if pb.n < 4 else "RGBA", (pb.width, pb.height), pb.samples).convert("RGB")
            mean = sum(ImageStat.Stat(ImageChops.difference(ia, ib)).mean) / 3
            if mean >= 3.0:
                far.append(f"page {number}: {mean:.2f}")
        outcome.check(not far, f"the pages with a raised picture look as before at 100 dpi (mean difference under 3 of 255): {len(pages)} pages"
                      + (f"; apart: {far[:3]}" if far else ""))
        warnings = pymupdf.TOOLS.mupdf_warnings()
        outcome.check(not warnings, "MuPDF opens and draws the copy without a warning" + (f": {warnings[:200]}" if warnings else ""))
    finally:
        doc_a.close()
        doc_b.close()


# ------------------------------------------------------------------------------------------ one document


def raise_document(found: Scan, output: Path, options: Options, step=None) -> Outcome:
    if found.refusal:
        return Outcome(found.document, None, status="refused", reason=found.refusal)
    try:
        if found.kind == "pdf":
            return raise_pdf(found, output, options, step)
        return raise_ooxml(found, output, options, step)
    except Exception as error:
        leftover = output.with_name(output.name + ".writing")
        try:
            leftover.unlink()
        except OSError:
            pass
        return Outcome(found.document, None, status="failed", reason=f"{type(error).__name__}: {error}")
