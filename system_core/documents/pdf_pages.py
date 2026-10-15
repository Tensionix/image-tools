"""The pages of a PDF: turned, put together, parted, the properties taken away - nothing on a page is drawn anew.

rotate_pages   the pages asked for get a quarter or a half turn in /Rotate: a viewer and a printer turn them
merge          every PDF of the Source, in the order of their names, into one
split          a PDF into one file a page, a file every N pages, or a file a range ("1-3, 4-10")
clean_meta     the properties of the document (author, title, the program that made it, dates) and its XMP gone

Every result is read back before it is called done: its pages counted, the text of every page compared.
"""
from __future__ import annotations

import re
from pathlib import Path

from .placements import pdf_refusal
from .raise_dpi import Outcome

TURNS = {"cw90": 90, "ccw90": -90, "180": 180}


def parse_pages(text: str, count: int) -> list[int]:
    """ "1-3, 5, 8-" as page numbers from 1; "" - every page. Pages past the end are an error, not a silence."""
    text = (text or "").strip()
    if not text or text.lower() in ("all", "все"):
        return list(range(1, count + 1))
    pages: list[int] = []
    for part in re.split(r"[,;\s]+", text):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)?\s*-\s*(\d+)?|(\d+)", part)
        if not match:
            raise ValueError(f"not a page or a range: {part}")
        if match.group(3):
            first = last = int(match.group(3))
        else:
            first = int(match.group(1) or 1)
            last = int(match.group(2) or count)
        if first < 1 or last > count or first > last:
            raise ValueError(f"{part}: the document has pages 1-{count}")
        pages.extend(range(first, last + 1))
    return sorted(set(pages))


def _texts(path: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def rotate_pages(source: Path, output: Path, turn: str, pages_text: str) -> Outcome:
    import pikepdf

    outcome = Outcome(source, output)
    if refusal := pdf_refusal(source):
        return Outcome(source, None, status="refused", reason=refusal)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".writing")
    try:
        with pikepdf.open(source) as pdf:
            pages = parse_pages(pages_text, len(pdf.pages))
            before = {number: int(pdf.pages[number - 1].obj.get("/Rotate", 0)) for number in pages}
            for number in pages:
                pdf.pages[number - 1].rotate(TURNS[turn], relative=True)
            pdf.save(temp)
        temp.replace(output)
    except Exception as error:
        temp.unlink(missing_ok=True)
        return Outcome(source, None, status="failed", reason=f"{type(error).__name__}: {error}")
    with pikepdf.open(output) as pdf:
        wrong = [number for number in pages if (int(pdf.pages[number - 1].obj.get("/Rotate", 0)) - before[number] - TURNS[turn]) % 360]
        outcome.check(not wrong, f"the pages asked for are turned: {len(pages)}" + (f"; not: {wrong[:5]}" if wrong else ""))
    outcome.check(_texts(source) == _texts(output), "the text of every page is the same")
    outcome.notes.append(f"turned pages: {len(pages)}")
    outcome.facts = {"turned": len(pages)}
    return outcome


def clean_meta(source: Path, output: Path) -> Outcome:
    import pikepdf

    outcome = Outcome(source, output)
    if refusal := pdf_refusal(source):
        return Outcome(source, None, status="refused", reason=refusal)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".writing")
    try:
        with pikepdf.open(source) as pdf:
            told = sorted(str(key) for key in pdf.docinfo.keys())
            had_xmp = "/Metadata" in pdf.Root
            if had_xmp:
                del pdf.Root.Metadata
            for key in list(pdf.docinfo.keys()):
                del pdf.docinfo[key]
            pdf.save(temp, fix_metadata_version=False)
        temp.replace(output)
    except Exception as error:
        temp.unlink(missing_ok=True)
        return Outcome(source, None, status="failed", reason=f"{type(error).__name__}: {error}")
    with pikepdf.open(output) as pdf:
        left = [str(key) for key in pdf.docinfo.keys()]
        outcome.check(not left and "/Metadata" not in pdf.Root, "no property of the document is left" + (f": {left}" if left else ""))
    outcome.check(_texts(source) == _texts(output), "the text of every page is the same")
    taken = [key.lstrip("/") for key in told] + (["XMP"] if had_xmp else [])
    outcome.notes.append("taken away: " + (", ".join(taken) or "nothing - the document told no property"))
    outcome.facts = {"taken": taken}
    return outcome


def merge(documents: list[Path], output: Path) -> Outcome:
    import pikepdf

    outcome = Outcome(documents[0] if documents else output, output)
    for document in documents:
        if refusal := pdf_refusal(document):
            return Outcome(document, None, status="refused", reason=f"{document.name}: {refusal}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".writing")
    counts = []
    marked = 0
    try:
        with pikepdf.new() as merged:
            for document in documents:
                with pikepdf.open(document) as part:
                    counts.append(len(part.pages))
                    marked += "/Outlines" in part.Root
                    merged.pages.extend(part.pages)
            merged.save(temp)
        temp.replace(output)
    except Exception as error:
        temp.unlink(missing_ok=True)
        return Outcome(outcome.document, None, status="failed", reason=f"{type(error).__name__}: {error}")
    with pikepdf.open(output) as pdf:
        outcome.check(len(pdf.pages) == sum(counts), f"pages: {sum(counts)} of {len(documents)} documents, {len(pdf.pages)} in the result")
    together = _texts(output)
    expected = [text for document in documents for text in _texts(document)]
    outcome.check(together == expected, "the text of every page is the same and in the order of the documents")
    outcome.notes.append(f"{len(documents)} documents, {sum(counts)} pages, in the order of their names")
    if marked:
        outcome.notes.append(f"bookmarks of {marked} documents are not carried into the result")
    outcome.facts = {"documents": len(documents), "pages": sum(counts), "bookmarks": marked}
    return outcome


def split(source: Path, folder: Path, mode: str, every: int, ranges: str) -> Outcome:
    import pikepdf

    outcome = Outcome(source, folder)
    if refusal := pdf_refusal(source):
        return Outcome(source, None, status="refused", reason=refusal)
    folder.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Path, list[int]]] = []
    try:
        with pikepdf.open(source) as pdf:
            count = len(pdf.pages)
            if mode == "each":
                parts = [[number] for number in range(1, count + 1)]
            elif mode == "every":
                every = max(1, int(every))
                parts = [list(range(first, min(count, first + every - 1) + 1)) for first in range(1, count + 1, every)]
            else:
                parts = []
                for chunk in re.split(r"[,;]+", ranges or ""):
                    if chunk.strip():
                        parts.append(parse_pages(chunk, count))
                if not parts:
                    raise ValueError("no range is given")
            width = max(3, len(str(len(parts))))
            for index, numbers in enumerate(parts, 1):
                piece = pikepdf.new()
                for number in numbers:
                    piece.pages.append(pdf.pages[number - 1])
                target = folder / f"{source.stem}_{index:0{width}d}.pdf"
                # Beside its place first: a stop in the middle leaves a piece written before as it was.
                temp = target.with_name(target.name + ".writing")
                piece.save(temp)
                piece.close()
                temp.replace(target)
                written.append((target, numbers))
    except Exception as error:
        return Outcome(source, None, status="failed", reason=f"{type(error).__name__}: {error}")
    texts = _texts(source)
    wrong = []
    for target, numbers in written:
        if _texts(target) != [texts[number - 1] for number in numbers]:
            wrong.append(target.name)
    outcome.check(not wrong, f"every file holds its pages, the text of each the same: {len(written)} files" + (f"; not: {wrong[:3]}" if wrong else ""))
    outcome.notes.append(f"{len(written)} files in {folder}")
    outcome.facts = {"files": len(written)}
    return outcome
