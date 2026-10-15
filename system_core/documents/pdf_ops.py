"""Two operations over a PDF: its pictures made lighter, and a watermark over its pages - each checked before it is done.

shrink_pdf     a picture placed above the target resolution gets fewer pixels (Lanczos) and is written
               as a JPEG; a palette, one bit to a pixel and a mask stay without loss. Only the streams of
               the pictures change; a picture whose new stream would not be lighter keeps the old one.
watermark_pdf  a line of text across every page, along its diagonal, half transparent: written as text
               over the page (pymupdf TextWriter), the page is not drawn anew - its own text stays text.

A PDF that is encrypted or signed is refused before anything is written (placements.pdf_refusal).
"""
from __future__ import annotations

import io
import math
import zlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from .placements import Scan, lowest_ppi, pdf_refusal
from .raise_dpi import Change, Outcome, _pdf_picture, walk_pdf
from .density import restate_jpeg


@dataclass
class ShrinkOptions:
    target: int = 200
    jpeg_quality: int = 82
    keep_lossless: bool = False


def _smaller(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    whole = image.mode in ("P", "1", "PA")
    return image.resize(size, Image.NEAREST if whole else Image.LANCZOS)


def _jpeg(image: Image.Image, quality: int, density: int) -> bytes:
    if image.mode not in ("RGB", "L", "CMYK"):
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality, optimize=True, dpi=(density, density))
    return restate_jpeg(out.getvalue(), density)


def shrink_pdf(found: Scan, output: Path, options: ShrinkOptions, step=None) -> Outcome:
    import pikepdf

    outcome = Outcome(found.document, output)
    if found.refusal:
        return Outcome(found.document, None, status="refused", reason=found.refusal)
    lowest = lowest_ppi(found.placements)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with pikepdf.open(found.document) as pdf:
            for part, picture in found.pictures.items():
                if step:
                    step()
                ppi = lowest.get(part)
                change = Change(part, "", picture.pixels, picture.pixels, ppi, ppi, picture.stored, picture.stored)
                outcome.changes.append(change)
                if ppi is None or picture.pixels is None:
                    change.action = "kept: " + (picture.note or "its placement has no size")
                    continue
                if ppi <= options.target * 1.05:
                    change.action = f"kept: at {ppi:.0f} ppi already"
                    continue
                scale = options.target / ppi
                size = (max(1, math.ceil(picture.pixels[0] * scale)), max(1, math.ceil(picture.pixels[1] * scale)))
                obj = pdf.get_object((int(part.split()[1]), 0))
                image, why = _pdf_picture(obj)
                if image is None:
                    change.action = "kept: " + why
                    continue
                before = len(obj.read_raw_bytes())
                smaller = _smaller(image, size)
                is_jpeg = obj.get("/Filter") == "/DCTDecode"
                indexed = image.mode == "P" and isinstance(obj.get("/ColorSpace"), pikepdf.Array) and str(obj.ColorSpace[0]) == "/Indexed"
                if indexed:
                    bits = int(obj.get("/BitsPerComponent", 8))
                    data, name, depth, stored = zlib.compress(smaller.tobytes("raw", {1: "P;1", 2: "P;2", 4: "P;4", 8: "P"}[bits]), 9), pikepdf.Name.FlateDecode, bits, "Flate"
                elif image.mode == "1":
                    data, name, depth, stored = zlib.compress(smaller.tobytes("raw", "1"), 9), pikepdf.Name.FlateDecode, 1, "Flate"
                elif options.keep_lossless and not is_jpeg and smaller.mode in ("L", "RGB", "CMYK"):
                    data, name, depth, stored = zlib.compress(smaller.tobytes(), 9), pikepdf.Name.FlateDecode, 8, "Flate"
                else:
                    data, name, depth, stored = _jpeg(smaller, options.jpeg_quality, options.target), pikepdf.Name.DCTDecode, 8, "DCT"
                if len(data) >= before:
                    change.action = "kept: the smaller picture would not be lighter"
                    continue
                obj.write(data, filter=name)
                obj.BitsPerComponent = depth
                if "/DecodeParms" in obj:
                    del obj["/DecodeParms"]
                obj.Width, obj.Height = size
                mask = obj.get("/SMask")
                if mask is not None:
                    alpha = pikepdf.PdfImage(mask).as_pil_image().convert("L")
                    mask.write(zlib.compress(alpha.resize(size, Image.LANCZOS).tobytes(), 9), filter=pikepdf.Name.FlateDecode)
                    mask.Width, mask.Height = size
                    mask.BitsPerComponent = 8
                    if "/DecodeParms" in mask:
                        del mask["/DecodeParms"]
                change.pixels_after = size
                change.ppi_after = ppi * size[0] / picture.pixels[0]
                change.stored_after = stored
                change.action = f"made lighter: {before // 1024} KB -> {len(data) // 1024} KB"
            temp = output.with_name(output.name + ".writing")
            pdf.save(temp, object_stream_mode=pikepdf.ObjectStreamMode.preserve, compress_streams=True)
        temp.replace(output)
    except Exception as error:
        try:
            output.with_name(output.name + ".writing").unlink()
        except OSError:
            pass
        return Outcome(found.document, None, status="failed", reason=f"{type(error).__name__}: {error}")
    check_shrunk(found, outcome, options)
    return outcome


def _pages_apart(source: Path, copy: Path, pages: list[int], dpi: int = 100) -> list[str]:
    import pymupdf

    far = []
    doc_a, doc_b = pymupdf.open(source), pymupdf.open(copy)
    try:
        for number in pages:
            pa, pb = doc_a[number - 1].get_pixmap(dpi=dpi), doc_b[number - 1].get_pixmap(dpi=dpi)
            ia = Image.frombytes("RGB" if pa.n < 4 else "RGBA", (pa.width, pa.height), pa.samples).convert("RGB")
            ib = Image.frombytes("RGB" if pb.n < 4 else "RGBA", (pb.width, pb.height), pb.samples).convert("RGB")
            mean = sum(ImageStat.Stat(ImageChops.difference(ia, ib)).mean) / 3
            far.append((number, mean))
    finally:
        doc_a.close()
        doc_b.close()
    return far


def check_shrunk(found: Scan, outcome: Outcome, options: ShrinkOptions) -> None:
    import pikepdf
    import pymupdf

    with pikepdf.open(found.document) as before, pikepdf.open(outcome.output) as after:
        check = getattr(after, "check_pdf_syntax", None) or getattr(after, "check")
        problems = check()
        outcome.check(not problems, "qpdf finds nothing wrong in the copy" + (f": {problems[:2]}" if problems else ""))
        outcome.check(len(before.pages) == len(after.pages), f"pages: {len(before.pages)} before, {len(after.pages)} after")
    was, now = walk_pdf(found.document), walk_pdf(outcome.output)
    outcome.check(len(was) == len(now), f"pictures drawn, counted by pikepdf: {len(was)} before, {len(now)} after")
    moved = [f"page {a[0]}" for a, b in zip(was, now) if a[0] != b[0] or abs(a[4] - b[4]) > 1e-6 or abs(a[5] - b[5]) > 1e-6]
    outcome.check(not moved, "every picture is drawn in the same place at the same size" + (f": {moved[:3]}" if moved else ""))
    lighter = {int(change.part.split()[1]) for change in outcome.changes if change.action.startswith("made lighter")}
    drawn = [b for a, b in zip(was, now) if a[1] in lighter]
    low = [f"page {b[0]}: {min(b[2] / b[4], b[3] / b[5]):.0f}" for b in drawn if min(b[2] / b[4], b[3] / b[5]) < options.target - 0.5]
    outcome.check(not low, f"no picture made lighter is below {options.target} ppi: {len(drawn)} drawings" + (f"; below: {low[:3]}" if low else ""))
    doc_a, doc_b = pymupdf.open(found.document), pymupdf.open(outcome.output)
    try:
        pymupdf.TOOLS.mupdf_warnings()
        texts = sum(1 for a, b in zip(doc_a, doc_b) if a.get_text() == b.get_text())
        outcome.check(texts == doc_a.page_count, f"the text of the pages is the same: {texts} of {doc_a.page_count}")
        warnings = pymupdf.TOOLS.mupdf_warnings()
    finally:
        doc_a.close()
        doc_b.close()
    pages = sorted({b[0] for b in drawn})
    apart = [f"page {number}: {mean:.2f}" for number, mean in _pages_apart(found.document, outcome.output, pages) if mean >= 4.0]
    outcome.check(not apart, f"the pages with a lighter picture look as before at 100 dpi (mean difference under 4 of 255): {len(pages)} pages"
                  + (f"; apart: {apart[:3]}" if apart else ""))
    outcome.check(not warnings, "MuPDF opens and draws the copy without a warning" + (f": {warnings[:200]}" if warnings else ""))
    size_before, size_after = found.document.stat().st_size, outcome.output.stat().st_size
    outcome.notes.append(f"{size_before / 1048576:.1f} MB -> {size_after / 1048576:.1f} MB")


# ------------------------------------------------------------------------------------------ the watermark

FONTS = [Path(r"C:\Windows\Fonts\arialbd.ttf"), Path(r"C:\Windows\Fonts\arial.ttf"), Path(r"C:\Windows\Fonts\segoeuib.ttf")]
NAMED = {"red": (0.8, 0.0, 0.0), "black": (0.0, 0.0, 0.0), "grey": (0.4, 0.4, 0.4), "blue": (0.0, 0.4, 0.8)}


def colour_of(text: str) -> tuple[float, float, float]:
    text = (text or "grey").strip().lower()
    if text in NAMED:
        return NAMED[text]
    text = text.lstrip("#")
    if "," in text:
        parts = [int(part) for part in text.split(",")]
    else:
        parts = [int(text[at:at + 2], 16) for at in (0, 2, 4)]
    return tuple(min(255, max(0, value)) / 255 for value in parts[:3])


def watermark_pdf(source: Path, output: Path, text: str, opacity: float, coverage: float, colour: tuple[float, float, float]) -> Outcome:
    import pymupdf

    outcome = Outcome(source, output)
    refusal = pdf_refusal(source)
    if refusal:
        return Outcome(source, None, status="refused", reason=refusal)
    font_file = next((path for path in FONTS if path.is_file()), None)
    if font_file is None:
        return Outcome(source, None, status="failed", reason="no font with Cyrillic letters: Arial is not in C:\\Windows\\Fonts")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".writing")
    try:
        doc = pymupdf.open(source)
        font = pymupdf.Font(fontfile=str(font_file))
        for page in doc:
            # The page as a person sees it - turned by its /Rotate - and the line along its diagonal, bottom left to top right.
            seen = page.rect
            width, height = seen.width, seen.height
            angle = math.degrees(math.atan2(height, width))
            length = math.hypot(width, height) * coverage
            size = length / max(1e-6, font.text_length(text, fontsize=1))
            centre = pymupdf.Point(width / 2, height / 2)
            writer = pymupdf.TextWriter(page.rect, opacity=opacity, color=colour)
            start = pymupdf.Point(centre.x - font.text_length(text, fontsize=size) / 2, centre.y + size * 0.35)
            writer.append(start, text, font=font, fontsize=size)
            # The turn of the page is taken back from the angle: on a turned page the line rises along the diagonal a person sees.
            morph = (centre * page.derotation_matrix, pymupdf.Matrix(angle - page.rotation))
            writer.write_text(page, morph=morph, overlay=True)
        doc.subset_fonts()
        doc.save(temp, garbage=3, deflate=True)
        doc.close()
        temp.replace(output)
    except Exception as error:
        try:
            temp.unlink()
        except OSError:
            pass
        return Outcome(source, None, status="failed", reason=f"{type(error).__name__}: {error}")
    check_watermark(source, outcome, text)
    return outcome


def check_watermark(source: Path, outcome: Outcome, text: str) -> None:
    import pymupdf

    doc_a, doc_b = pymupdf.open(source), pymupdf.open(outcome.output)
    try:
        pymupdf.TOOLS.mupdf_warnings()
        outcome.check(doc_a.page_count == doc_b.page_count, f"pages: {doc_a.page_count} before, {doc_b.page_count} after")
        lost = []
        marked = 0
        for a, b in zip(doc_a, doc_b):
            old, new = a.get_text().split(), b.get_text()
            words = new.split()
            if any(word not in words for word in old):
                lost.append(a.number + 1)
            if all(word in words for word in text.split()):
                marked += 1
        outcome.check(not lost, "the text of every page is still text, every word of it in place" + (f"; not on pages: {lost[:5]}" if lost else ""))
        outcome.check(marked == doc_b.page_count, f"the watermark stands on every page as text: {marked} of {doc_b.page_count}")
        warnings = pymupdf.TOOLS.mupdf_warnings()
        outcome.check(not warnings, "MuPDF opens and draws the copy without a warning" + (f": {warnings[:200]}" if warnings else ""))
    finally:
        doc_a.close()
        doc_b.close()
    apart = _pages_apart(source, outcome.output, [1])
    outcome.check(bool(apart) and apart[0][1] > 0.05, "the first page shows the watermark (it differs from the page without it)")
