"""The commands of the engine that Audion Office Image Optimizer had: what main.py runs over DOCX and PPTX.

docs-shrink         the pictures of every document shrunk to a limit and recompressed (HARD: a PNG
                    without a mask becomes a JPEG; SAFE: only JPEGs are touched)
docs-fit-size       every document fitted under a size in megabytes, the limit lowered step by step
docs-color          every picture brought to sRGB or CMYK, with its ICC profile or without
docs-extract-media  the pictures of every document copied out into a folder named after it

The work is the Optimizer's own (system_core\\documents\\optimizer), as it did it there: the limits
and the quality its form had, its report of every picture. A PDF is not its business: it is named
and passed by. A copy keeps the name of its document, in the Target, in the folders the documents
stand in under the Source.

Exit code: 0 - every document went; 1 - one did not (its errors are in the journal).
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from .optimizer.media_extract import extract_media, render_media_extract_report
from .optimizer.models import build_optimization_policy
from .optimizer.ooxml_package import write_fit_size_document, write_hard_batch_document, write_profile_normalized_document, write_safe_document
from .optimizer.reporter import render_process_report
from .placements import discover_documents, ooxml_refusal

try:  # imported as system_core.documents
    from ..core.lines import detail, details, item, tally
    from ..core.paths import routes_cross
except ImportError:  # run by main.py, where the packages of system_core are top-level
    from core.lines import detail, details, item, tally
    from core.paths import routes_cross

# The limits of the form of the Optimizer: an ordinary document, a presentation, print or archive.
LIMITS = {"1920x1080": (1920, 1080), "2560x1440": (2560, 1440), "3840x2160": (3840, 2160)}
LEAST_CUSTOM = 400


def _write_json(log_dir: Path, payload: dict) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _documents(args) -> tuple[Path, Path, list[Path]] | int:
    """The DOCX and PPTX of the Source; a PDF among them is named. An int - the exit code of a refusal."""
    source, target = Path(args.input), Path(args.output)
    asked = tuple(part.strip().lower() for part in str(getattr(args, "kinds", "") or "docx,pptx").split(",") if part.strip()) or ("docx", "pptx")
    pdfs = discover_documents(source, ("pdf",)) if "pdf" in asked else []
    if len(pdfs) == 1:
        tqdm.write(item("INFO", pdfs[0].name, "a PDF - this operation is over DOCX and PPTX, passed by"))
    elif pdfs:
        tqdm.write(item("INFO", f"{len(pdfs)} PDF", "this operation is over DOCX and PPTX, passed by"))
        tqdm.write(detail(", ".join(pdf.name for pdf in pdfs)))
    documents = discover_documents(source, tuple(kind for kind in asked if kind in ("docx", "pptx")))
    if not documents:
        print(f"No DOCX or PPTX in {source}")
        return 1
    if crossing := routes_cross(source, target):
        print(crossing[0].upper() + crossing[1:])
        return 2
    return source, target, documents


def _folder_for(document: Path, source: Path, target: Path) -> Path:
    if source.is_file():
        return target
    return target / document.relative_to(source).parent


def _size(value: int) -> str:
    return f"{value / 1024 / 1024:.2f} MB"


def _tell(name: str, errors: list, note: str, report: str, at: int, of: int, status: str = "OK") -> None:
    """One document of the batch: its line, and the report of the Optimizer under it, indented (core\\lines.py)."""
    tqdm.write(item("ERR", name, "; ".join(errors), at, of) if errors else item(status, name, note, at, of))
    for line in details(report):
        tqdm.write(line)


def _refusal(document: Path) -> str:
    """Why the Optimizer may not change a document; "" - it may. A signed package is refused, as the commands of DPI
    refuse it: a changed part breaks the signature, and the copy would go on as if signed."""
    try:
        with zipfile.ZipFile(document) as archive:
            return ooxml_refusal(archive)
    except zipfile.BadZipFile:
        return "not a ZIP package - an encrypted or broken document, refused"


def _weight(result) -> str:
    changed = sum(1 for one in result.items if one.changed)
    return f"{result.total_images} pictures, {changed} changed; {_size(result.input_size_bytes)} -> {_size(result.output_size_bytes)}"


def cmd_docs_shrink(args) -> int:
    found = _documents(args)
    if isinstance(found, int):
        return found
    source, target, documents = found
    if args.limit == "custom":
        if not args.max_width or not args.max_height or args.max_width < LEAST_CUSTOM or args.max_height < LEAST_CUSTOM:
            print(f"An own limit must be at least {LEAST_CUSTOM} x {LEAST_CUSTOM} px")
            return 2
        width, height, mode = args.max_width, args.max_height, args.mode
    else:
        width, height = LIMITS[args.limit]
        mode = "hard"
    skip_area = round(args.min_skip_width * args.min_skip_height / 1_000_000, 2) if args.limit == "custom" else None
    policy = build_optimization_policy(
        "custom", max_width=width, max_height=height, max_megapixels=round(width * height / 1_000_000, 2),
        jpeg_quality=max(40, min(95, int(args.jpeg_quality))),
        min_skip_width=args.min_skip_width if args.limit == "custom" else None,
        min_skip_height=args.min_skip_height if args.limit == "custom" else None,
        min_skip_megapixels=max(0.01, skip_area) if skip_area is not None else None,
        keep_png_under_kb=max(0, int(args.keep_png_under_kb)),
    )
    failures, summary = 0, []
    for at, document in enumerate(tqdm(documents, desc="Processing", unit="file"), start=1):
        if refused := _refusal(document):
            _tell(document.name, [refused], "", "", at, len(documents))
            failures += 1
            summary.append({"document": str(document), "errors": [refused]})
            continue
        folder = _folder_for(document, source, target)
        if mode == "safe":
            result = write_safe_document(document, "custom", batch=True, output_dir=folder, policy=policy)
        else:
            result = write_hard_batch_document(document, "custom", output_dir=folder, policy=policy)
        _tell(document.name, result.errors, _weight(result), render_process_report(result), at, len(documents))
        failures += bool(result.errors)
        summary.append({"document": str(document), "output": str(result.output_path), "errors": result.errors,
                        "before": result.input_size_bytes, "after": result.output_size_bytes})
    tqdm.write(tally(len(documents) - failures, len(documents), f"documents shrunk to {width} x {height}, JPEG {policy.jpeg_quality}; copies in {target}"))
    _write_json(Path(args.log_dir), {"command": "docs-shrink", "limit": [width, height], "mode": mode, "documents": summary})
    return 1 if failures else 0


def cmd_docs_fit_size(args) -> int:
    found = _documents(args)
    if isinstance(found, int):
        return found
    source, target, documents = found
    target_mb = max(1.0, float(args.target_mb))
    failures, missed, summary = 0, 0, []
    for at, document in enumerate(tqdm(documents, desc="Processing", unit="file"), start=1):
        if refused := _refusal(document):
            _tell(document.name, [refused], "", "", at, len(documents))
            failures += 1
            summary.append({"document": str(document), "errors": [refused]})
            continue
        result, attempts = write_fit_size_document(document, target_size_mb=target_mb, output_dir=_folder_for(document, source, target),
                                                   keep_png_under_kb=max(0, int(args.keep_png_under_kb)))
        tries = "\n".join(f"[{index:02d}] {attempt.limit_label:<24} -> {_size(attempt.output_size_bytes):>10}  {'OK' if attempt.met_target else 'try next'}"
                          for index, attempt in enumerate(attempts, start=1))
        report = tries + "\n" + render_process_report(result, analysis_label=f"FIT SIZE <= {target_mb:g} MB / HARD JPG")
        failures += bool(result.errors)
        if not result.errors and result.output_size_bytes > int(target_mb * 1024 * 1024):
            missed += 1
            _tell(document.name, [], f"{target_mb:g} MB was not reached; the lowest limit was used: 1280x720, JPEG 65", report, at, len(documents), "WARN")
        else:
            _tell(document.name, result.errors, _weight(result), report, at, len(documents))
        summary.append({"document": str(document), "output": str(result.output_path), "errors": result.errors,
                        "after": result.output_size_bytes, "attempts": len(attempts)})
    tqdm.write(tally(len(documents) - failures - missed, len(documents), f"documents fit under {target_mb:g} MB; copies in {target}"))
    _write_json(Path(args.log_dir), {"command": "docs-fit-size", "target_mb": target_mb, "documents": summary})
    return 1 if failures else 0


def cmd_docs_color(args) -> int:
    found = _documents(args)
    if isinstance(found, int):
        return found
    source, target, documents = found
    mode = "normalize-cmyk" if args.profile == "cmyk" else "normalize-srgb"
    failures, summary = 0, []
    for at, document in enumerate(tqdm(documents, desc="Processing", unit="file"), start=1):
        if refused := _refusal(document):
            _tell(document.name, [refused], "", "", at, len(documents))
            failures += 1
            summary.append({"document": str(document), "errors": [refused]})
            continue
        result = write_profile_normalized_document(document, profile_mode=mode, embed_profile=bool(args.embed_icc),
                                                   output_dir=_folder_for(document, source, target))
        label = f"NORMALIZE TO {args.profile.upper()}{' + ICC' if args.embed_icc else ''} / PILLOW CMS / BATCH"
        _tell(document.name, result.errors, _weight(result), render_process_report(result, analysis_label=label), at, len(documents))
        failures += bool(result.errors)
        summary.append({"document": str(document), "output": str(result.output_path), "errors": result.errors})
    tqdm.write(tally(len(documents) - failures, len(documents), f"documents brought to {args.profile.upper()}"
                     f"{' with the ICC profile' if args.embed_icc else ''}; copies in {target}"))
    _write_json(Path(args.log_dir), {"command": "docs-color", "profile": args.profile, "embed_icc": bool(args.embed_icc), "documents": summary})
    return 1 if failures else 0


def cmd_docs_extract_media(args) -> int:
    found = _documents(args)
    if isinstance(found, int):
        return found
    source, target, documents = found
    failures, summary = 0, []
    for at, document in enumerate(tqdm(documents, desc="Processing", unit="file"), start=1):
        result = extract_media(document, output_root=_folder_for(document, source, target))
        _tell(document.name, result.errors, f"{len(result.extracted)} pictures -> {result.target_dir}", render_media_extract_report(result),
              at, len(documents), "WARN" if result.warnings else "OK")
        failures += bool(result.errors)
        summary.append({"document": str(document), "folder": str(result.target_dir), "files": len(result.extracted), "errors": result.errors})
    tqdm.write(tally(len(documents) - failures, len(documents), f"documents gave their pictures; folders in {target}"))
    _write_json(Path(args.log_dir), {"command": "docs-extract-media", "documents": summary})
    return 1 if failures else 0


def add_parsers(sub) -> None:
    def common(parser) -> None:
        parser.add_argument("--input", required=True, help="A document or a folder of documents")
        parser.add_argument("--output", required=True, help="The folder for the copies")
        parser.add_argument("--kinds", default="docx,pptx", help="Which documents: docx, pptx, joined by commas")
        parser.add_argument("--report-dir", default="")
        parser.add_argument("--log-dir", default="logs")

    shrink = sub.add_parser("docs-shrink", help="Shrink the pictures of DOCX and PPTX to a limit")
    common(shrink)
    shrink.add_argument("--limit", choices=[*LIMITS, "custom"], default="1920x1080")
    shrink.add_argument("--max-width", type=int, default=0)
    shrink.add_argument("--max-height", type=int, default=0)
    shrink.add_argument("--mode", choices=["hard", "safe"], default="hard", help="With an own limit: HARD or SAFE")
    shrink.add_argument("--jpeg-quality", type=int, default=82)
    shrink.add_argument("--min-skip-width", type=int, default=400, help="With an own limit: a smaller PNG stays as it is")
    shrink.add_argument("--min-skip-height", type=int, default=400)
    shrink.add_argument("--keep-png-under-kb", type=int, default=200,
                        help="A PNG (GIF, BMP, TIFF) lighter than this stays as it is: emblems, icons, line art; 0 - off")
    shrink.set_defaults(func=cmd_docs_shrink)

    fit = sub.add_parser("docs-fit-size", help="Fit DOCX and PPTX under a size in MB")
    common(fit)
    fit.add_argument("--target-mb", type=float, default=20.0)
    fit.add_argument("--keep-png-under-kb", type=int, default=200,
                     help="A PNG (GIF, BMP, TIFF) lighter than this stays as it is: emblems, icons, line art; 0 - off")
    fit.set_defaults(func=cmd_docs_fit_size)

    color = sub.add_parser("docs-color", help="Bring the pictures of DOCX and PPTX to sRGB or CMYK")
    common(color)
    color.add_argument("--profile", choices=["srgb", "cmyk"], default="srgb")
    color.add_argument("--embed-icc", action="store_true")
    color.set_defaults(func=cmd_docs_color)

    extract = sub.add_parser("docs-extract-media", help="Copy the pictures of DOCX and PPTX out")
    common(extract)
    extract.set_defaults(func=cmd_docs_extract_media)
