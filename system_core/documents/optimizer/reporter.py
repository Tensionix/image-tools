from __future__ import annotations

from collections import Counter

from .models import ProcessResult


def _format_bytes(value: int) -> str:
    if value == 0:
        return "0 B"
    sign = "-" if value < 0 else ""
    units = ("B", "KB", "MB", "GB")
    size = float(abs(value))
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    return f"{sign}{size:.1f} {unit}" if unit != "B" else f"{sign}{int(size)} B"


def render_process_report(result: ProcessResult, analysis_label: str | None = None) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("AUDION OFFICE IMAGE OPTIMIZER - PROCESS REPORT")
    lines.append("=" * 72)
    lines.append(f"Document      : {result.document_path}")
    lines.append(f"Output        : {result.output_path}")
    lines.append(f"Package type  : {result.package_type}")
    if analysis_label:
        lines.append(f"Analysis mode : {analysis_label}")
    else:
        lines.append(f"Analysis mode : {result.mode.upper()} / {result.preset.upper()} / {'BATCH' if result.batch else 'ASK'}")
    lines.append("")

    if result.errors:
        lines.append("Errors:")
        for err in result.errors:
            lines.append(f"  - {err}")
        return "\n".join(lines)

    lines.append(f"Images found  : {result.total_images}")
    lines.append(f"Unsupported   : {result.unsupported_count}")
    lines.append(f"Input size    : {_format_bytes(result.input_size_bytes)}")
    lines.append(f"Output size   : {_format_bytes(result.output_size_bytes)}")
    if result.input_size_bytes and result.output_size_bytes:
        saved = result.input_size_bytes - result.output_size_bytes
        saved_percent = saved / result.input_size_bytes * 100
        size_delta_label = "Saved" if saved >= 0 else "Added"
        lines.append(f"{size_delta_label:<14}: {_format_bytes(abs(saved))} ({abs(saved_percent):.1f}%)")
    lines.append("")

    decisions = Counter()
    changed_count = 0
    for index, item in enumerate(result.items, start=1):
        transparency = "yes" if item.has_transparency else "no"
        if item.changed:
            changed_count += 1
        decisions[item.executed_action] += 1
        action_label = "selected" if not result.batch else "executed"
        lines.append(f"[{index:03d}] {item.package_path}")
        lines.append(f"      document      : {item.document_path}")
        lines.append(f"      format        : {item.detected_format or 'unknown'}")
        lines.append(f"      width         : {item.width if item.width else 'unknown'}")
        lines.append(f"      height        : {item.height if item.height else 'unknown'}")
        lines.append(f"      transparency  : {transparency}")
        lines.append(f"      recommend     : {item.recommended_action}")
        lines.append(f"      {action_label:<13}: {item.executed_action}")
        lines.append(f"      changed       : {'yes' if item.changed else 'no'}")
        lines.append(f"      size          : {_format_bytes(item.bytes_before)} -> {_format_bytes(item.bytes_after)}")
        if item.output_package_path != item.package_path:
            lines.append(f"      output part   : {item.output_package_path}")
        if item.note:
            lines.append(f"      note          : {item.note}")
        lines.append("")

    lines.append(f"Changed items : {changed_count}")
    if changed_count == 0:
        if result.mode == "safe":
            lines.append("No JPEG parts were changed.")
        else:
            lines.append("No image parts were changed.")
    lines.append("Summary by executed action:")
    for key in sorted(decisions):
        lines.append(f"  - {key}: {decisions[key]}")

    return "\n".join(lines)
