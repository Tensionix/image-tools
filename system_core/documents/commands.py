"""The commands of the engine over the pictures inside documents: what main.py runs.

docs-dpi-check   reads every document of the Source, writes nothing into them: a line for every
                 placement of a picture - where, its pixels, the size it is placed at, its resolution,
                 the density it states - and the total "N of M below the threshold". The table goes
                 to the journal and, as CSV and Markdown, into the folder of the report.
docs-dpi-raise   writes a copy of every document of the Source into the Target, its pictures at the
                 threshold (raise_dpi.py), and checks every copy before calling it done.

Exit code: 0 - every document went as asked; 1 - one was refused, failed or did not pass its check.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from .placements import Placement, discover_documents, scan
from .raise_dpi import Options, raise_document

try:  # imported as system_core.documents
    from ..core.lines import detail, item, paint, tally
    from ..core.paths import routes_cross
except ImportError:  # run by main.py, where the packages of system_core are top-level
    from core.lines import detail, item, paint, tally
    from core.paths import routes_cross

COLUMNS = ("document", "place", "picture", "pixels", "placed, mm", "ppi", "states, dpi", "stored", "note")


def _row(placement: Placement, root: Path) -> list[str]:
    picture = placement.picture
    try:
        document = str(placement.document.relative_to(root)) if root.is_dir() else placement.document.name
    except ValueError:
        document = placement.document.name
    pixels = f"{picture.pixels[0]} x {picture.pixels[1]}" if picture.pixels else "-"
    size = placement.size_mm
    placed = f"{size[0]:.1f} x {size[1]:.1f}" if size else "-"
    ppi = f"{placement.ppi:.0f}" if placement.ppi is not None else "-"
    label = picture.label
    # A PNG keeps its density per metre: 220 dpi comes back as 219.99 - told whole.
    states = "-" if not label else f"{round(label[0])}" if round(label[0]) == round(label[1]) else f"{round(label[0])} x {round(label[1])}"
    return [document, placement.place, picture.part, pixels, placed, ppi, states, picture.stored, placement.note or picture.note]


def _write_json(log_dir: Path, payload: dict) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (log_dir / f"run_{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _summary(report: Path, payload: dict) -> None:
    (report / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _table_lines(rows: list[list[str]], columns: tuple[str, ...] = COLUMNS) -> list[str]:
    widths = [max(len(columns[i]), *(len(row[i]) for row in rows)) if rows else len(columns[i]) for i in range(len(columns))]
    widths[-1] = 0
    line = lambda cells: "  ".join(cell.ljust(widths[i]) if widths[i] else cell for i, cell in enumerate(cells)).rstrip()
    return [line(columns)] + [line(row) for row in rows]


def _markdown(rows: list[list[str]], title: str, total: str) -> str:
    def cell(text: str) -> str:
        return text.replace("|", "\\|")
    head = "| " + " | ".join(COLUMNS) + " |\n|" + "---|" * len(COLUMNS) + "\n"
    body = "".join("| " + " | ".join(cell(c) for c in row) + " |\n" for row in rows)
    return f"# {title}\n\n{head}{body}\n{total}\n"


def _kinds(args) -> tuple[str, ...]:
    asked = tuple(part.strip().lower() for part in str(getattr(args, "kinds", "") or "").split(",") if part.strip())
    return asked or ("docx", "pptx", "pdf")


def cmd_docs_dpi_check(args) -> int:
    source = Path(args.input)
    documents = discover_documents(source, _kinds(args))
    threshold = int(args.threshold)
    report = Path(args.report_dir) if args.report_dir else None
    if not documents:
        print(f"No {', '.join(kind.upper() for kind in _kinds(args))} in {source}")
        return 1
    rows: list[list[str]] = []
    below = measured = 0
    refused = []
    summary = []
    blocks = []
    for document in tqdm(documents, desc="Processing", unit="file"):
        found = scan(document)
        if found.refusal and not found.placements:
            refused.append(f"{document.name}: {found.refusal}")
        low = unknown = 0
        own = []
        for placement in found.placements:
            own.append(_row(placement, source))
            if placement.ppi is not None:
                measured += 1
                if placement.ppi < threshold:
                    below += 1
                    low += 1
            else:
                unknown += 1
        rows.extend(own)
        blocks.append((document, found.refusal if not found.placements else "", own, low, unknown))
        summary.append({"document": str(document), "placements": len(found.placements), "below": low, "refusal": found.refusal})
    # The table goes to the journal by documents: a document, and its placements under it, a placement
    # below the threshold or not measured in amber. A document with such a placement is a finding, not a
    # trouble (INFO): the window folds every checked document into its live line and shows the table
    # in its panel RESULT; it keeps in its journal the documents that could not be read (core\lines.py).
    table = _table_lines([row[1:] for row in rows], COLUMNS[1:])
    head, cells = table[0], iter(table[1:])
    for at, (document, refusal, own, low, unknown) in enumerate(blocks, start=1):
        if refusal:
            tqdm.write(item("ERR", document.name, refusal, at, len(blocks)))
            continue
        said = f"{len(own)} placements" + (f", {low} below {threshold} ppi" if low else f", none below {threshold} ppi")
        said += f", {unknown} not measured" if unknown else ""
        tqdm.write(item("INFO" if low or unknown else "OK", document.name, said, at, len(blocks)))
        if own:
            tqdm.write(detail(head))
        for row in own:
            tqdm.write(detail(next(cells), "warn" if row[5] == "-" or float(row[5]) < threshold else "muted"))
    total = f"{below} of {measured} placements below {threshold} ppi"
    unmeasured = len(rows) - measured
    if unmeasured:
        total += f"; {unmeasured} not measured (named in the table)"
    tqdm.write("")
    tqdm.write(paint(total, "warn" if below or unmeasured else "ok"))
    if report is not None:
        report.mkdir(parents=True, exist_ok=True)
        with (report / "dpi_check.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(COLUMNS)
            writer.writerows(rows)
        (report / "dpi_check.md").write_text(_markdown(rows, f"DPI of the pictures: {source}", total), encoding="utf-8")
        # What the panel RESULT of the window shows: the numbers - it says them in its own language - and the table.
        _summary(report, {"kind": "dpi_check", "threshold": threshold, "below": below, "measured": measured,
                          "unmeasured": unmeasured, "refused": len(refused), "table": "dpi_check.csv", "report": "dpi_check.md"})
        tqdm.write(f"Report: {report / 'dpi_check.md'}")
    _write_json(Path(args.log_dir), {"command": "docs-dpi-check", "threshold": threshold, "below": below, "measured": measured,
                                     "documents": summary})
    return 1 if refused else 0


def _output_for(document: Path, source: Path, target: Path) -> Path:
    if source.is_file():
        return target / document.name
    return target / document.relative_to(source)


def cmd_docs_dpi_raise(args) -> int:
    source = Path(args.input)
    target = Path(args.output)
    documents = discover_documents(source, _kinds(args))
    if not documents:
        print(f"No {', '.join(kind.upper() for kind in _kinds(args))} in {source}")
        return 1
    if crossing := routes_cross(source, target):
        print(crossing[0].upper() + crossing[1:])
        return 2
    options = Options(threshold=int(args.threshold), what=args.what, method=args.method, jpeg_quality=int(args.jpeg_quality),
                      keep_lossless=bool(args.keep_lossless), office_may_compress=bool(args.office_may_compress))
    found = [scan(document) for document in documents]
    total = sum(len(item.pictures) for item in found)
    outcomes = []
    lines: list[str] = []
    with tqdm(total=max(1, total), desc="Processing", unit="picture") as bar:
        for at, scanned in enumerate(found, start=1):
            outcome = raise_document(scanned, _output_for(scanned.document, source, target), options, step=lambda: bar.update(1))
            if outcome.status in ("refused", "failed"):
                bar.update(len(scanned.pictures))
            outcomes.append(outcome)
            name = scanned.document.name
            said = outcome.status + (f" - {outcome.reason}" if outcome.reason else "")
            tqdm.write(item(STATUS[outcome.status], name, said, at, len(found)))
            lines.append(f"## {name}: {said}")
            for change in outcome.changes:
                before = f"{change.pixels_before[0]} x {change.pixels_before[1]}" if change.pixels_before else "-"
                after = f"{change.pixels_after[0]} x {change.pixels_after[1]}" if change.pixels_after else "-"
                ppi = "" if change.ppi_before is None else f", {change.ppi_before:.0f} -> {change.ppi_after:.0f} ppi"
                text = f"{change.part}: {change.action} ({before} -> {after}{ppi})" + (f", now {change.renamed_to}" if change.renamed_to else "")
                tqdm.write(detail(text))
                lines.append("- " + text)
            _tell_checks(outcome, lines)
    done = sum(1 for one in outcomes if one.status == "done")
    tqdm.write("")
    tqdm.write(tally(done, len(outcomes), f"documents done and checked; copies in {target}"))
    if args.report_dir:
        report = Path(args.report_dir)
        report.mkdir(parents=True, exist_ok=True)
        (report / "dpi_raise.md").write_text(f"# Raise to {options.threshold} DPI: {source}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
        _summary(report, {"kind": "dpi_raise", "threshold": options.threshold, "done": done, "documents": len(outcomes),
                          "target": str(target), "report": "dpi_raise.md",
                          "rows": [[item.document.name, item.status, item.reason or next((text for ok, text in item.checks if not ok), "")]
                                   for item in outcomes]})
    _write_json(Path(args.log_dir), {
        "command": "docs-dpi-raise", "threshold": options.threshold, "what": options.what, "method": options.method,
        "documents": [{"document": str(item.document), "output": str(item.output) if item.output else "", "status": item.status,
                       "reason": item.reason, "checks": [{"ok": ok, "text": text} for ok, text in item.checks],
                       "changes": [change.__dict__ for change in item.changes]} for item in outcomes],
    })
    return 0 if done == len(outcomes) else 1


def _pdf_route(args) -> tuple[Path, Path, list[Path]] | int:
    """The Source, the Target and the PDF of the Source; an exit code when there is nothing to do or the Target is the Source."""
    source, target = Path(args.input), Path(args.output)
    documents = discover_documents(source, ("pdf",))
    if not documents:
        print(f"No PDF in {source}")
        return 1
    if crossing := routes_cross(source, target):
        print(crossing[0].upper() + crossing[1:])
        return 2
    return source, target, documents


# The word of the line of a document by what became of it (core\lines.py).
STATUS = {"done": "OK", "partial": "WARN", "refused": "ERR", "failed": "ERR"}


def _tell_checks(outcome, lines: list[str]) -> None:
    """The checks and the notes of one document, under its line: a check that did not hold in amber."""
    for ok, text in outcome.checks:
        tqdm.write(detail(f"checked: {text}") if ok else detail(f"[WARN] not held: {text}", "warn"))
        lines.append(f"- {'checked' if ok else 'NOT HELD'}: {text}")
    for note in outcome.notes:
        tqdm.write(detail(note))
        lines.append(f"- {note}")


def _tell(name: str, outcome, lines: list[str], at: int | None = None, of: int | None = None) -> None:
    """What became of one document - to the journal and to the lines of the report."""
    said = outcome.status + (f" - {outcome.reason}" if outcome.reason else "")
    tqdm.write(item(STATUS[outcome.status], name, said, at, of))
    lines.append(f"## {name}: {said}")
    for change in outcome.changes:
        tqdm.write(detail(f"{change.part}: {change.action}"))
        lines.append(f"- {change.part}: {change.action}")
    _tell_checks(outcome, lines)


def _write_documents(args, name: str, kind: str, work, summary_extra: dict) -> int:
    """A command that writes a copy of every PDF of the Source into the Target: the journal, the report, summary.json."""
    route = _pdf_route(args)
    if isinstance(route, int):
        return route
    source, target, documents = route
    outcomes, lines = [], []
    for at, document in enumerate(tqdm(documents, desc="Processing", unit="file"), start=1):
        outcome = work(document, _output_for(document, source, target))
        outcomes.append(outcome)
        _tell(document.name, outcome, lines, at, len(documents))
    return _finish(args, name, kind, source, target, outcomes, lines, summary_extra)


def _finish(args, name: str, kind: str, source: Path, target: Path, outcomes: list, lines: list[str], summary_extra: dict) -> int:
    done = sum(1 for item in outcomes if item.status == "done")
    tqdm.write("")
    tqdm.write(tally(done, len(outcomes), f"documents done and checked; copies in {target}"))
    if args.report_dir:
        report = Path(args.report_dir)
        report.mkdir(parents=True, exist_ok=True)
        (report / f"{kind}.md").write_text(f"# {name}: {source}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
        _summary(report, {"kind": kind, "done": done, "documents": len(outcomes), "target": str(target), "report": f"{kind}.md",
                          **summary_extra,
                          "rows": [[item.document.name, item.status,
                                    item.reason or next((text for ok, text in item.checks if not ok), "") or "; ".join(item.notes),
                                    item.facts]
                                   for item in outcomes]})
    _write_json(Path(args.log_dir), {"command": kind, "documents": [
        {"document": str(item.document), "output": str(item.output) if item.output else "", "status": item.status, "reason": item.reason,
         "checks": [{"ok": ok, "text": text} for ok, text in item.checks], "notes": item.notes} for item in outcomes]})
    return 0 if done == len(outcomes) else 1


def cmd_docs_pdf_shrink(args) -> int:
    from .pdf_ops import ShrinkOptions, shrink_pdf

    options = ShrinkOptions(target=int(args.target_ppi), jpeg_quality=int(args.jpeg_quality), keep_lossless=bool(args.keep_lossless))
    return _write_documents(args, f"Pictures of PDF made lighter to {options.target} ppi", "pdf_shrink",
                            lambda document, output: shrink_pdf(scan(document), output, options), {"threshold": options.target})


def cmd_docs_pdf_watermark(args) -> int:
    from .pdf_ops import colour_of, watermark_pdf

    if not str(args.text).strip():
        print("The watermark has no text")
        return 2
    colour = colour_of(args.color)
    return _write_documents(args, f"Watermark \"{args.text}\" over PDF", "pdf_watermark",
                            lambda document, output: watermark_pdf(document, output, str(args.text), float(args.opacity) / 100,
                                                                   float(args.coverage) / 100, colour), {})


def cmd_docs_pdf_rotate(args) -> int:
    from .pdf_pages import rotate_pages

    return _write_documents(args, f"Pages of PDF turned ({args.turn})", "pdf_rotate",
                            lambda document, output: rotate_pages(document, output, args.turn, args.pages), {})


def cmd_docs_pdf_clean_meta(args) -> int:
    from .pdf_pages import clean_meta

    return _write_documents(args, "Properties of PDF taken away", "pdf_clean_meta", clean_meta, {})


def cmd_docs_pdf_split(args) -> int:
    from .pdf_pages import split

    if args.mode == "ranges" and not str(args.ranges).strip():
        print("No range is given: write them as 1-3, 4-10")
        return 2
    return _write_documents(args, "PDF split", "pdf_split",
                            lambda document, output: split(document, output.parent, args.mode, args.every, args.ranges), {})


def _natural(path: Path) -> list:
    """2 before 10: the order of names as a person reads it."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(path))]


def cmd_docs_pdf_merge(args) -> int:
    from .pdf_pages import merge

    route = _pdf_route(args)
    if isinstance(route, int):
        return route
    source, target, documents = route
    documents = sorted(documents, key=_natural)
    name = (str(args.name).strip() or "merged").removesuffix(".pdf").removesuffix(".PDF")
    if re.search(r'[\\/:*?"<>|]', name):
        print(f"The name of the file cannot hold \\ / : * ? \" < > |: {name}")
        return 2
    output = target / f"{name}.pdf"
    # The order the documents go in, in one line: a hundred of them are not a hundred lines.
    tqdm.write(detail("in this order: " + ", ".join(str(document.relative_to(source) if source.is_dir() else document.name)
                                                    for document in documents)))
    outcome = merge(documents, output)
    lines: list[str] = []
    _tell(output.name, outcome, lines)
    outcome.document = output
    return _finish(args, "PDF merged", "pdf_merge", source, target, [outcome], lines, {})


def add_parsers(sub) -> None:
    """The commands over documents, on the parser of main.py: the two of DPI, then those of the Office Image Optimizer."""
    from .office_commands import add_parsers as add_office_parsers

    add_office_parsers(sub)
    check = sub.add_parser("docs-dpi-check", help="Report the resolution of every picture placed in DOCX, PPTX and PDF")
    check.add_argument("--input", required=True, help="A document or a folder of documents")
    check.add_argument("--threshold", type=int, default=300)
    check.add_argument("--kinds", default="docx,pptx,pdf", help="Which documents: docx, pptx, pdf, joined by commas")
    check.add_argument("--report-dir", default="", help="Where dpi_check.csv and dpi_check.md go")
    check.add_argument("--log-dir", default="logs")
    check.set_defaults(func=cmd_docs_dpi_check)

    raise_ = sub.add_parser("docs-dpi-raise", help="Copy DOCX, PPTX and PDF with their pictures raised to a resolution")
    raise_.add_argument("--input", required=True, help="A document or a folder of documents")
    raise_.add_argument("--output", required=True, help="The folder for the copies")
    raise_.add_argument("--threshold", type=int, default=300)
    raise_.add_argument("--kinds", default="docx,pptx,pdf", help="Which documents: docx, pptx, pdf, joined by commas")
    raise_.add_argument("--what", choices=["actual", "label"], default="actual",
                        help="actual - add pixels and state the threshold; label - only state it")
    raise_.add_argument("--method", choices=["repeat", "smooth"], default="repeat")
    raise_.add_argument("--jpeg-quality", type=int, default=95)
    raise_.add_argument("--keep-lossless", action="store_true", help="A picture stored without loss stays without loss")
    raise_.add_argument("--office-may-compress", action="store_true", help="Do not set the flag that keeps Word and PowerPoint from compressing")
    raise_.add_argument("--report-dir", default="")
    raise_.add_argument("--log-dir", default="logs")
    raise_.set_defaults(func=cmd_docs_dpi_raise)

    shrink = sub.add_parser("docs-pdf-shrink", help="Copy PDF with its pictures made lighter to a resolution")
    shrink.add_argument("--input", required=True, help="A PDF or a folder of them")
    shrink.add_argument("--output", required=True, help="The folder for the copies")
    shrink.add_argument("--target-ppi", type=int, default=200, help="A picture above it gets fewer pixels, down to it")
    shrink.add_argument("--jpeg-quality", type=int, default=82)
    shrink.add_argument("--keep-lossless", action="store_true", help="A picture stored without loss stays without loss")
    shrink.add_argument("--report-dir", default="")
    shrink.add_argument("--log-dir", default="logs")
    shrink.set_defaults(func=cmd_docs_pdf_shrink)

    mark = sub.add_parser("docs-pdf-watermark", help="Copy PDF with a line of text across every page, half transparent")
    mark.add_argument("--input", required=True, help="A PDF or a folder of them")
    mark.add_argument("--output", required=True, help="The folder for the copies")
    mark.add_argument("--text", required=True)
    mark.add_argument("--opacity", type=float, default=25, help="Percent: 100 - opaque")
    mark.add_argument("--coverage", type=float, default=70, help="Percent of the diagonal of a page the line takes")
    mark.add_argument("--color", default="red", help="red, black, grey, blue, R,G,B or #RRGGBB")
    mark.add_argument("--report-dir", default="")
    mark.add_argument("--log-dir", default="logs")
    mark.set_defaults(func=cmd_docs_pdf_watermark)

    def pages_command(name: str, help_text: str, func):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--input", required=True, help="A PDF or a folder of them")
        command.add_argument("--output", required=True, help="The folder for the result")
        command.add_argument("--report-dir", default="")
        command.add_argument("--log-dir", default="logs")
        command.set_defaults(func=func)
        return command

    rotate = pages_command("docs-pdf-rotate", "Copy PDF with pages turned - nothing on a page drawn anew", cmd_docs_pdf_rotate)
    rotate.add_argument("--turn", choices=["cw90", "ccw90", "180"], default="cw90")
    rotate.add_argument("--pages", default="", help="1-3, 5, 8- ; empty - every page")

    merge = pages_command("docs-pdf-merge", "Put every PDF of the Source into one, in the order of their names", cmd_docs_pdf_merge)
    merge.add_argument("--name", default="merged", help="The name of the file it makes")

    split = pages_command("docs-pdf-split", "Part a PDF into files: one a page, every N pages, or by ranges", cmd_docs_pdf_split)
    split.add_argument("--mode", choices=["each", "every", "ranges"], default="each")
    split.add_argument("--every", type=int, default=10, help="Pages a file, for --mode every")
    split.add_argument("--ranges", default="", help="A file a range: 1-3, 4-10, 11-")

    pages_command("docs-pdf-clean-meta", "Copy PDF without the properties of the document: author, title, program, dates, XMP",
                  cmd_docs_pdf_clean_meta)
