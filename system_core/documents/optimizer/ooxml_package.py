from __future__ import annotations

import posixpath
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from pathlib import PurePosixPath
from dataclasses import dataclass
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .converter import (
    has_visible_transparency,
    shrink_png_bytes,
    normalize_image_to_cmyk_bytes,
    normalize_image_to_srgb_bytes,
    process_hard_raster_bytes,
    process_safe_jpeg_bytes,
)
from .models import (
    Action,
    AppliedItem,
    Decision,
    OptimizationPolicy,
    ProcessResult,
    Preset,
    SUPPORTED_HARD,
    build_optimization_policy,
    policy_for_dimensions,
    policy_for_preset,
)
from .project_config import get_project_root, load_project_config
from .rules import is_light_lossless, light_reason, recommend
from .scanner import scan_document


def verified_package(path: Path) -> str:
    """Why a written package is not whole; "" - it is: every part reads back by its checksum, every XML part parses."""
    try:
        with ZipFile(path) as archive:
            broken = archive.testzip()
            if broken:
                return f"{broken}: the part does not read back"
            for name in archive.namelist():
                if name.lower().endswith((".xml", ".rels")):
                    try:
                        ET.fromstring(archive.read(name))
                    except ET.ParseError as error:
                        return f"{name}: its XML does not read ({error}) - it came so from the document"
    except Exception as error:  # noqa: BLE001 - whatever stops the reading, the copy is not whole
        return f"the copy does not read as a package: {type(error).__name__}: {error}"
    return ""


@contextmanager
def _whole_copy(destination: Path, result: ProcessResult) -> Iterator[Path]:
    """The copy is written beside its place, checked, and only a whole one takes the place: a stop, a failure or a
    copy that does not read back leave what lay there before as it was. Written straight over its place, a STOP in
    the middle left a broken ZIP where a good copy had been (the audit of 15.10.2026, F02)."""
    temp = destination.with_name(destination.name + ".writing")
    temp.unlink(missing_ok=True)
    try:
        yield temp
        wrong = verified_package(temp)
        if wrong:
            result.errors.append(f"the copy was not put in place: {wrong}")
        else:
            temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
ET.register_namespace("", REL_NS)
ET.register_namespace("", CONTENT_TYPES_NS)

FIT_SIZE_STAGES: tuple[tuple[int, int, int], ...] = (
    (3840, 2160, 82),
    (3840, 2160, 75),
    (2560, 1440, 75),
    (1920, 1080, 75),
    (1920, 1080, 65),
    (1600, 900, 65),
    (1280, 720, 65),
)


@dataclass(frozen=True, slots=True)
class FitSizeAttempt:
    width: int
    height: int
    quality: int
    output_size_bytes: int
    target_size_bytes: int
    met_target: bool

    @property
    def limit_label(self) -> str:
        return f"{self.width}x{self.height}, JPEG {self.quality}"


def _build_output_path(target_path: Path, output_dir: Path | None = None) -> Path:
    destination_dir = output_dir or (get_project_root() / "output")
    destination_dir.mkdir(parents=True, exist_ok=True)
    # The copy goes into a Target of its own and keeps the name of its document, as every copy of Audion Image Tools does.
    return destination_dir / target_path.name


def _clone_zip_info(info: ZipInfo) -> ZipInfo:
    cloned = ZipInfo(filename=info.filename, date_time=info.date_time)
    cloned.compress_type = info.compress_type
    cloned.comment = info.comment
    cloned.extra = info.extra
    cloned.create_system = info.create_system
    cloned.create_version = info.create_version
    cloned.extract_version = info.extract_version
    cloned.flag_bits = info.flag_bits
    cloned.volume = info.volume
    cloned.internal_attr = info.internal_attr
    cloned.external_attr = info.external_attr
    return cloned


def _relationship_source_dir(rel_path: str) -> str:
    if rel_path == "_rels/.rels":
        return ""

    rel_file = PurePosixPath(rel_path)
    parent_parts = list(rel_file.parts[:-1])
    if "_rels" not in parent_parts:
        return str(rel_file.parent).replace("\\", "/")

    rels_index = parent_parts.index("_rels")
    source_prefix = parent_parts[:rels_index]
    source_name = rel_file.name[:-5]
    source_part = PurePosixPath(*source_prefix, source_name)
    source_dir = source_part.parent
    return "" if str(source_dir) == "." else str(source_dir).replace("\\", "/")


def _resolve_relationship_target(rel_path: str, target: str) -> str:
    source_dir = _relationship_source_dir(rel_path)
    joined = posixpath.normpath(posixpath.join(source_dir, target))
    return joined.lstrip("./")


def _relative_relationship_target(rel_path: str, package_path: str) -> str:
    source_dir = _relationship_source_dir(rel_path)
    start = source_dir or "."
    return posixpath.relpath(package_path, start=start).replace("\\", "/")


def _rewrite_relationship_targets(data: bytes, rel_path: str, rename_map: dict[str, str]) -> bytes:
    if not rename_map:
        return data

    root = ET.fromstring(data)
    changed = False
    for relationship in root.findall(f"{{{REL_NS}}}Relationship"):
        if relationship.get("TargetMode") == "External":
            continue
        target = relationship.get("Target")
        if not target:
            continue
        resolved = _resolve_relationship_target(rel_path, target)
        new_target = rename_map.get(resolved)
        if not new_target:
            continue
        relationship.set("Target", _relative_relationship_target(rel_path, new_target))
        changed = True

    if not changed:
        return data
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rewrite_content_types(data: bytes, rename_map: dict[str, str], new_extensions: set[str]) -> bytes:
    root = ET.fromstring(data)
    changed = False

    defaults = {
        default.get("Extension", "").lower(): default
        for default in root.findall(f"{{{CONTENT_TYPES_NS}}}Default")
    }
    for extension in sorted(new_extensions):
        if extension not in defaults:
            default = ET.Element(f"{{{CONTENT_TYPES_NS}}}Default")
            default.set("Extension", extension)
            default.set("ContentType", "image/jpeg")
            root.append(default)
            changed = True
        else:
            content_type = defaults[extension].get("ContentType")
            if content_type != "image/jpeg":
                defaults[extension].set("ContentType", "image/jpeg")
                changed = True

    for override in root.findall(f"{{{CONTENT_TYPES_NS}}}Override"):
        part_name = (override.get("PartName") or "").lstrip("/")
        if part_name in rename_map:
            override.set("PartName", f"/{rename_map[part_name]}")
            override.set("ContentType", "image/jpeg")
            changed = True

    if not changed:
        return data
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _content_type_for_extension(extension: str) -> str:
    extension = extension.lower()
    mapping = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
    }
    return mapping.get(extension, "application/octet-stream")


def _rewrite_content_types_for_generated_parts(
    data: bytes,
    rename_map: dict[str, str],
) -> bytes:
    if not rename_map:
        return data

    root = ET.fromstring(data)
    changed = False
    defaults = {
        default.get("Extension", "").lower(): default
        for default in root.findall(f"{{{CONTENT_TYPES_NS}}}Default")
    }

    for new_path in rename_map.values():
        extension = PurePosixPath(new_path).suffix.lower().lstrip(".")
        if not extension:
            continue
        content_type = _content_type_for_extension(extension)
        existing = defaults.get(extension)
        if existing is None:
            default = ET.Element(f"{{{CONTENT_TYPES_NS}}}Default")
            default.set("Extension", extension)
            default.set("ContentType", content_type)
            root.append(default)
            changed = True
            defaults[extension] = default
        elif existing.get("ContentType") != content_type:
            existing.set("ContentType", content_type)
            changed = True

    for override in root.findall(f"{{{CONTENT_TYPES_NS}}}Override"):
        part_name = (override.get("PartName") or "").lstrip("/")
        if part_name in rename_map:
            new_path = rename_map[part_name]
            extension = PurePosixPath(new_path).suffix.lower().lstrip(".")
            override.set("PartName", f"/{new_path}")
            override.set("ContentType", _content_type_for_extension(extension))
            changed = True

    if not changed:
        return data
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _make_converted_package_path(package_path: str, occupied_paths: set[str], target_extension: str) -> str:
    source = PurePosixPath(package_path)
    stem = source.stem
    parent = "" if str(source.parent) == "." else str(source.parent).replace("\\", "/")
    target_extension = target_extension.lstrip(".").lower()

    candidate = f"{parent}/{stem}.{target_extension}" if parent else f"{stem}.{target_extension}"
    if candidate not in occupied_paths and candidate != package_path:
        return candidate

    index = 1
    while True:
        candidate = (
            f"{parent}/{stem}_converted{index}.{target_extension}"
            if parent else f"{stem}_converted{index}.{target_extension}"
        )
        if candidate not in occupied_paths and candidate != package_path:
            return candidate
        index += 1


def _item_exceeds_policy(item_width: int | None, item_height: int | None, item_megapixels: float, policy: OptimizationPolicy) -> bool:
    if not item_width or not item_height:
        return False
    return item_width > policy.max_width or item_height > policy.max_height or item_megapixels > policy.max_megapixels


def _force_jpeg_decision(item, preset: Preset, policy: OptimizationPolicy) -> Decision:
    item_policy = policy_for_dimensions(policy, item.width, item.height)
    ext = item.detected_format
    if ext not in SUPPORTED_HARD:
        return Decision("hard", preset, "unsupported", "Unsupported image format for HARD JPG fit-size mode.")
    exceeds = _item_exceeds_policy(item.width, item.height, item.megapixels, item_policy)
    if ext in {"jpg", "jpeg"}:
        action: Action = "resize+recompress" if exceeds else "recompress"
        reason = f"Forced HARD JPG fit-size pass at {item_policy.limit_label}."
        return Decision("hard", preset, action, reason)
    if is_light_lossless(item, item_policy):
        return Decision("hard", preset, "keep", light_reason(item_policy))
    action = "resize+convert" if exceeds else "convert"
    reason = f"Forced HARD JPG fit-size pass at {item_policy.limit_label}."
    return Decision("hard", preset, action, reason)


def write_safe_document(
    target_path: str | Path,
    preset: Preset,
    *,
    batch: bool,
    selected_actions: dict[str, Action] | None = None,
    output_dir: str | Path | None = None,
    policy: OptimizationPolicy | None = None,
) -> ProcessResult:
    source_path = Path(target_path).resolve()
    scan_result = scan_document(source_path)
    resolved_policy = policy or policy_for_preset(preset)
    destination_path = _build_output_path(source_path, Path(output_dir).resolve() if output_dir else None)
    result = ProcessResult(
        document_path=scan_result.document_path,
        output_path=destination_path,
        package_type=scan_result.package_type,
        mode="safe",
        preset=preset,
        batch=batch,
        unsupported_count=scan_result.unsupported_count,
        input_size_bytes=source_path.stat().st_size if source_path.exists() else 0,
    )
    result.errors.extend(scan_result.errors)
    if result.errors:
        return result

    replacement_map: dict[str, bytes] = {}
    with ZipFile(source_path, "r") as source_zip:
        for item in scan_result.items:
            decision = recommend(item, mode="safe", preset=preset, batch=batch, policy=resolved_policy)
            item_policy = policy_for_dimensions(resolved_policy, item.width, item.height)
            selected_action = (selected_actions or {}).get(item.package_path, decision.recommended_action)
            original_bytes = source_zip.read(item.package_path)
            bytes_before = len(original_bytes)
            bytes_after = bytes_before
            executed_action = selected_action
            changed = False

            if item.detected_format in {"jpg", "jpeg"} and selected_action in {"keep", "recompress", "resize", "resize+recompress", "skip"}:
                if selected_action == "skip":
                    processed_bytes = original_bytes
                else:
                    processed_bytes = process_safe_jpeg_bytes(original_bytes, selected_action, preset=preset, policy=item_policy)
                replacement_map[item.package_path] = processed_bytes
                bytes_after = len(processed_bytes)
                changed = processed_bytes != original_bytes
            else:
                executed_action = "skip" if selected_action == "unsupported" else selected_action
                replacement_map[item.package_path] = original_bytes

            result.items.append(
                AppliedItem(
                    document_path=item.document_path,
                    package_path=item.package_path,
                    output_package_path=item.package_path,
                    detected_format=item.detected_format,
                    width=item.width,
                    height=item.height,
                    has_transparency=item.has_transparency,
                    supported=item.supported,
                    recommended_action=decision.recommended_action,
                    executed_action=executed_action,
                    changed=changed,
                    bytes_before=bytes_before,
                    bytes_after=bytes_after,
                    note=item.note,
                )
            )

    with _whole_copy(destination_path, result) as temp, ZipFile(source_path, "r") as source_zip, ZipFile(temp, "w") as dest_zip:
        for info in source_zip.infolist():
            data = replacement_map.get(info.filename)
            if data is None:
                data = source_zip.read(info.filename)
            cloned = _clone_zip_info(info)
            if cloned.compress_type not in {0, ZIP_DEFLATED}:
                cloned.compress_type = info.compress_type
            dest_zip.writestr(cloned, data)

    result.output_size_bytes = destination_path.stat().st_size if destination_path.exists() and not result.errors else 0
    return result


def write_hard_batch_document(
    target_path: str | Path,
    preset: Preset,
    *,
    output_dir: str | Path | None = None,
    policy: OptimizationPolicy | None = None,
    force_jpeg: bool = False,
) -> ProcessResult:
    source_path = Path(target_path).resolve()
    scan_result = scan_document(source_path)
    resolved_policy = policy or policy_for_preset(preset)
    destination_path = _build_output_path(source_path, Path(output_dir).resolve() if output_dir else None)
    result = ProcessResult(
        document_path=scan_result.document_path,
        output_path=destination_path,
        package_type=scan_result.package_type,
        mode="hard",
        preset=preset,
        batch=True,
        unsupported_count=scan_result.unsupported_count,
        input_size_bytes=source_path.stat().st_size if source_path.exists() else 0,
    )
    result.errors.extend(scan_result.errors)
    if result.errors:
        return result

    replacement_map: dict[str, bytes] = {}
    added_parts: dict[str, bytes] = {}
    rename_map: dict[str, str] = {}
    removed_paths: set[str] = set()
    occupied_paths: set[str] = set()

    with ZipFile(source_path, "r") as source_zip:
        occupied_paths = {entry.filename for entry in source_zip.infolist()}

        for item in scan_result.items:
            item_policy = policy_for_dimensions(resolved_policy, item.width, item.height)
            if force_jpeg:
                decision = _force_jpeg_decision(item, preset, resolved_policy)
            else:
                decision = recommend(item, mode="hard", preset=preset, batch=True, policy=resolved_policy)
            original_bytes = source_zip.read(item.package_path)
            bytes_before = len(original_bytes)
            bytes_after = bytes_before
            executed_action = decision.recommended_action
            changed = False
            output_package_path = item.package_path
            item_note = item.note

            if item.detected_format in {"jpg", "jpeg"} and decision.recommended_action in {"keep", "recompress", "resize+recompress"}:
                processed_bytes = process_safe_jpeg_bytes(original_bytes, decision.recommended_action, preset=preset, policy=item_policy)
                replacement_map[item.package_path] = processed_bytes
                bytes_after = len(processed_bytes)
                changed = processed_bytes != original_bytes
            elif (item.detected_format in {"png", "gif", "bmp", "tif", "tiff"} and decision.recommended_action in {"convert", "resize+convert"}
                  and has_visible_transparency(original_bytes)):
                # Transparent: laid on white it would change on a coloured slide. It is not made a JPEG - a PNG over
                # the limit is made smaller and stays a PNG; anything else stays as it is.
                executed_action = "keep"
                said = "transparent: kept as it is"
                replacement_map[item.package_path] = original_bytes
                if item.detected_format == "png" and decision.recommended_action == "resize+convert":
                    smaller = shrink_png_bytes(original_bytes, item_policy)
                    if len(smaller) < bytes_before:
                        replacement_map[item.package_path] = smaller
                        executed_action, said, changed, bytes_after = "resize", "transparent: made smaller, kept a PNG", True, len(smaller)
                item_note = f"{item.note}; {said}" if item.note else said
            elif item.detected_format in {"png", "gif", "bmp", "tif", "tiff"} and decision.recommended_action in {"convert", "resize+convert"}:
                processed_bytes = process_hard_raster_bytes(original_bytes, decision.recommended_action, preset=preset, policy=item_policy)
                if len(processed_bytes) >= bytes_before:
                    # As a JPEG the picture came out heavier than it is: it stays as it is.
                    replacement_map[item.package_path] = original_bytes
                    executed_action = "keep"
                    heavier = f"JPEG would weigh {len(processed_bytes) / 1024:.1f} KB against {bytes_before / 1024:.1f} KB: kept"
                    item_note = f"{item.note}; {heavier}" if item.note else heavier
                else:
                    output_package_path = _make_converted_package_path(
                        item.package_path,
                        occupied_paths | set(added_parts),
                        "jpg",
                    )
                    added_parts[output_package_path] = processed_bytes
                    rename_map[item.package_path] = output_package_path
                    removed_paths.add(item.package_path)
                    occupied_paths.add(output_package_path)
                    bytes_after = len(processed_bytes)
                    changed = True
            elif decision.recommended_action == "keep":
                replacement_map[item.package_path] = original_bytes
            else:
                executed_action = "skip" if decision.recommended_action == "unsupported" else decision.recommended_action
                replacement_map[item.package_path] = original_bytes

            result.items.append(
                AppliedItem(
                    document_path=item.document_path,
                    package_path=item.package_path,
                    output_package_path=output_package_path,
                    detected_format=item.detected_format,
                    width=item.width,
                    height=item.height,
                    has_transparency=item.has_transparency,
                    supported=item.supported,
                    recommended_action=decision.recommended_action,
                    executed_action=executed_action,
                    changed=changed,
                    bytes_before=bytes_before,
                    bytes_after=bytes_after,
                    note=item_note,
                )
            )

    with _whole_copy(destination_path, result) as temp, ZipFile(source_path, "r") as source_zip, ZipFile(temp, "w") as dest_zip:
        for info in source_zip.infolist():
            if info.filename in removed_paths:
                continue

            data = replacement_map.get(info.filename)
            if data is None:
                data = source_zip.read(info.filename)

            if info.filename.endswith(".rels"):
                data = _rewrite_relationship_targets(data, info.filename, rename_map)
            elif info.filename == "[Content_Types].xml":
                data = _rewrite_content_types_for_generated_parts(data, rename_map)

            cloned = _clone_zip_info(info)
            if cloned.compress_type not in {0, ZIP_DEFLATED}:
                cloned.compress_type = info.compress_type
            dest_zip.writestr(cloned, data)

        for package_path, data in added_parts.items():
            info = ZipInfo(filename=package_path)
            info.compress_type = ZIP_DEFLATED
            dest_zip.writestr(info, data)

    result.output_size_bytes = destination_path.stat().st_size if destination_path.exists() and not result.errors else 0
    return result


def _fit_size_policy(width: int, height: int, quality: int, keep_png_under_kb: int = 0) -> OptimizationPolicy:
    return build_optimization_policy(
        "custom",
        max_width=width,
        max_height=height,
        max_megapixels=round((width * height) / 1_000_000, 2),
        jpeg_quality=quality,
        min_skip_width=0,
        min_skip_height=0,
        min_skip_megapixels=0.01,
        keep_png_under_kb=keep_png_under_kb,
    )


def write_fit_size_document(
    target_path: str | Path,
    *,
    target_size_mb: float = 20.0,
    output_dir: str | Path | None = None,
    keep_png_under_kb: int = 0,
) -> tuple[ProcessResult, list[FitSizeAttempt]]:
    target_size_bytes = max(1, int(float(target_size_mb) * 1024 * 1024))
    attempts: list[FitSizeAttempt] = []
    final_result: ProcessResult | None = None

    for width, height, quality in FIT_SIZE_STAGES:
        policy = _fit_size_policy(width, height, quality, keep_png_under_kb)
        result = write_hard_batch_document(
            target_path,
            preset="custom",
            output_dir=output_dir,
            policy=policy,
            force_jpeg=True,
        )
        final_result = result
        met_target = bool(result.output_size_bytes and result.output_size_bytes <= target_size_bytes)
        attempts.append(
            FitSizeAttempt(
                width=width,
                height=height,
                quality=quality,
                output_size_bytes=result.output_size_bytes,
                target_size_bytes=target_size_bytes,
                met_target=met_target,
            )
        )
        if result.errors or met_target:
            break

    if final_result is None:
        final_result = write_hard_batch_document(
            target_path,
            preset="custom",
            output_dir=output_dir,
            policy=_fit_size_policy(1280, 720, 65, keep_png_under_kb),
            force_jpeg=True,
        )
    return final_result, attempts


def write_profile_normalized_document(
    target_path: str | Path,
    *,
    profile_mode: Action,
    embed_profile: bool | None = None,
    output_dir: str | Path | None = None,
) -> ProcessResult:
    if profile_mode not in {"normalize-srgb", "normalize-cmyk"}:
        raise ValueError(f"Unsupported normalization mode: {profile_mode}")

    config = load_project_config()
    if embed_profile is None:
        embed_profile = profile_mode == "normalize-srgb"
    source_path = Path(target_path).resolve()
    scan_result = scan_document(source_path)
    destination_path = _build_output_path(source_path, Path(output_dir).resolve() if output_dir else None)
    result = ProcessResult(
        document_path=scan_result.document_path,
        output_path=destination_path,
        package_type=scan_result.package_type,
        mode=profile_mode,
        preset="uhd",
        batch=True,
        unsupported_count=scan_result.unsupported_count,
        input_size_bytes=source_path.stat().st_size if source_path.exists() else 0,
    )
    result.errors.extend(scan_result.errors)
    if result.errors:
        return result

    replacement_map: dict[str, bytes] = {}
    added_parts: dict[str, bytes] = {}
    rename_map: dict[str, str] = {}
    removed_paths: set[str] = set()

    with ZipFile(source_path, "r") as source_zip:
        occupied_paths = {entry.filename for entry in source_zip.infolist()}

        for item in scan_result.items:
            original_bytes = source_zip.read(item.package_path)
            bytes_before = len(original_bytes)
            bytes_after = bytes_before
            changed = False
            output_package_path = item.package_path
            executed_action = profile_mode

            if not item.supported:
                replacement_map[item.package_path] = original_bytes
                executed_action = "skip"
            else:
                if profile_mode == "normalize-srgb":
                    processed_bytes, target_extension = normalize_image_to_srgb_bytes(
                        original_bytes,
                        srgb_profile_path=str(config.icc.srgb_profile),
                        embed_profile=embed_profile,
                        quality=config.jpeg_quality_default,
                    )
                else:
                    processed_bytes, target_extension = normalize_image_to_cmyk_bytes(
                        original_bytes,
                        srgb_profile_path=str(config.icc.srgb_profile),
                        cmyk_profile_path=str(config.icc.cmyk_profile),
                        embed_profile=embed_profile,
                        quality=config.jpeg_quality_default,
                    )

                current_extension = PurePosixPath(item.package_path).suffix.lower().lstrip(".")
                if current_extension == target_extension:
                    replacement_map[item.package_path] = processed_bytes
                    changed = processed_bytes != original_bytes
                    bytes_after = len(processed_bytes)
                else:
                    output_package_path = _make_converted_package_path(
                        item.package_path,
                        occupied_paths | set(added_parts),
                        target_extension,
                    )
                    added_parts[output_package_path] = processed_bytes
                    rename_map[item.package_path] = output_package_path
                    removed_paths.add(item.package_path)
                    occupied_paths.add(output_package_path)
                    changed = True
                    bytes_after = len(processed_bytes)

            result.items.append(
                AppliedItem(
                    document_path=item.document_path,
                    package_path=item.package_path,
                    output_package_path=output_package_path,
                    detected_format=item.detected_format,
                    width=item.width,
                    height=item.height,
                    has_transparency=item.has_transparency,
                    supported=item.supported,
                    recommended_action=profile_mode,
                    executed_action=executed_action,
                    changed=changed,
                    bytes_before=bytes_before,
                    bytes_after=bytes_after,
                    note=item.note,
                )
            )

    with _whole_copy(destination_path, result) as temp, ZipFile(source_path, "r") as source_zip, ZipFile(temp, "w") as dest_zip:
        for info in source_zip.infolist():
            if info.filename in removed_paths:
                continue

            data = replacement_map.get(info.filename)
            if data is None:
                data = source_zip.read(info.filename)

            if info.filename.endswith(".rels"):
                data = _rewrite_relationship_targets(data, info.filename, rename_map)
            elif info.filename == "[Content_Types].xml":
                data = _rewrite_content_types_for_generated_parts(data, rename_map)

            cloned = _clone_zip_info(info)
            if cloned.compress_type not in {0, ZIP_DEFLATED}:
                cloned.compress_type = info.compress_type
            dest_zip.writestr(cloned, data)

        for package_path, data in added_parts.items():
            info = ZipInfo(filename=package_path)
            info.compress_type = ZIP_DEFLATED
            dest_zip.writestr(info, data)

    result.output_size_bytes = destination_path.stat().st_size if destination_path.exists() and not result.errors else 0
    return result

