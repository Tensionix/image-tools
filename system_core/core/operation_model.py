"""How the values of a form become what an operation is run with.

One copy of the rules. Until 3.0.0 they lived in the window on NiceGUI (ui_nicegui\\app.py), so an
operation could be run "as the window runs it" only from the window. They are taken from there as
they were - the defaults of a field, the conditions that hide or switch it off, the refusals before
a run, the fields that are the Source and the Target - and are held to a record of what that
window did: tests\\former_window_parameters.json, 915 states of 27 operations.

The window on Avalonia reads the same rules from `describe` and applies them to what it shows; the
console command applies them to what it runs. Neither knows an operation by its name.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterable

# The fields that are not of a form: the window keeps the Source and the Target beside the journal.
ROUTE_FIELDS = frozenset({
    "source", "source_dir", "source_path", "input", "input_dir", "input_path",
    "target_dir", "target_path", "destination", "destination_dir", "destination_path",
    "output", "output_dir", "output_path",
})
TICK_LISTS = frozenset({"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"})
TICKS = frozenset({"checkbox", "bool", "boolean", "toggle"})
NUMBERS = frozenset({"number", "int", "integer", "float", "quality", "quality_percent", "quality-percent", "slider"})
CHOICES = frozenset({"radio", "radiobuttons", "radio-buttons", "select", "choice", "format"})

LANGUAGES = ("en", "ru")
WORDS = {
    "en": {
        "fill": "Fill in: {field}",
        "tick": "Select at least one item: {field}",
        "number": "{field}: enter a number.",
        "whole": "{field}: enter a whole number.",
        "least": "{field}: minimum is {limit}.",
        "most": "{field}: maximum is {limit}.",
        "choice": "{field}: not one of its options - {value}",
    },
    "ru": {
        "fill": "Заполните поле: {field}",
        "tick": "Выберите хотя бы один пункт: {field}",
        "number": "{field}: нужно число.",
        "whole": "{field}: нужно целое число.",
        "least": "{field}: не меньше {limit}.",
        "most": "{field}: не больше {limit}.",
        "choice": "{field}: такого варианта нет - {value}",
    },
}


def safe_language(language: str | None) -> str:
    return language if language in LANGUAGES else "en"


# --- a field ---------------------------------------------------------------------------------


def field_id(field: dict[str, Any]) -> str:
    return str(field.get("id") or field.get("name") or "").strip()


def field_kind(field: dict[str, Any]) -> str:
    return str(field.get("type", field.get("kind", "text"))).lower()


def field_label(field: dict[str, Any], language: str = "en") -> str:
    if language == "ru" and field.get("label_ru"):
        return str(field["label_ru"])
    return str(field.get("label") or field.get("title") or field_id(field))


def is_route_field(field: dict[str, Any]) -> bool:
    return field_id(field).lower() in ROUTE_FIELDS


def is_whole(field: dict[str, Any], kind: str) -> bool:
    """A number typed and told whole - "75", never "75.0" - and taken so by the engine: its step and its limits are
    whole. A field whose least value is 0.1 takes fractions whatever its step (the custom percent of a scale)."""
    if kind == "float":
        return False
    for key in ("step", "min", "max"):
        value = field.get(key)
        if value not in (None, "") and not float(value).is_integer():
            return False
    return True


def is_target_field(field: dict[str, Any]) -> bool:
    key = field_id(field).lower()
    return any(part in key for part in ("target", "destination", "output"))


def option_value(option: Any) -> Any:
    if isinstance(option, dict):
        return option.get("value", option.get("id", option.get("label")))
    return option


def option_values(field: dict[str, Any]) -> list[Any]:
    options = field.get("options", [])
    return [option_value(option) for option in options] if isinstance(options, list) else []


# A colour of one's own begins as the red the engine draws a mark in.
RGB_DEFAULT = "204,0,0"


def field_default(field: dict[str, Any]) -> Any:
    if field_kind(field) == "rgb_color" and field.get("default") in (None, ""):
        return RGB_DEFAULT
    if "default" in field:
        return field["default"]
    options = field.get("options", [])
    if field_kind(field) in TICK_LISTS:
        if not isinstance(options, list):
            return []
        return [option_value(option) for option in options if isinstance(option, dict) and option.get("default", False)]
    if isinstance(options, list) and options:
        first = options[0]
        return first.get("value", first.get("id", "")) if isinstance(first, dict) else first
    return ""


def limits(field: dict[str, Any]) -> tuple[Any, Any]:
    """The least and the most a number may be. A quality the manifest gives no limits is 1-100: the engine takes nothing else."""
    least, most = field.get("min"), field.get("max")
    if field_kind(field).startswith("quality"):
        least, most = (1 if least is None else least), (100 if most is None else most)
    return least, most


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


# --- the conditions of a field ---------------------------------------------------------------


def _listed(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def matches(condition: Any, values: dict[str, Any]) -> bool:
    """A condition of the manifest against the values of the form. What it does not understand holds."""
    if not isinstance(condition, dict):
        return True
    if isinstance(condition.get("all"), list):
        return all(matches(item, values) for item in condition["all"])
    if isinstance(condition.get("any"), list):
        return any(matches(item, values) for item in condition["any"])
    key = str(condition.get("field") or condition.get("id") or "").strip()
    if not key:
        return True
    actual = values.get(key, condition.get("default"))
    if "equals" in condition:
        return actual in _listed(condition.get("equals"))
    if "not_equals" in condition:
        return actual not in _listed(condition.get("not_equals"))
    if "in" in condition:
        expected = condition.get("in")
        if not isinstance(expected, list):
            return False
        return any(item in expected for item in actual) if isinstance(actual, list) else actual in expected
    if "not_in" in condition:
        blocked = condition.get("not_in")
        if not isinstance(blocked, list):
            return True
        return all(item not in blocked for item in actual) if isinstance(actual, list) else actual not in blocked
    if "contains" in condition:
        return any(item in _listed(actual) for item in _listed(condition.get("contains")))
    if "not_contains" in condition:
        return all(item not in _listed(actual) for item in _listed(condition.get("not_contains")))
    if "contains_any" in condition:
        expected = condition.get("contains_any")
        return isinstance(expected, list) and any(item in _listed(actual) for item in expected)
    if "not_contains_any" in condition:
        blocked = condition.get("not_contains_any")
        return not isinstance(blocked, list) or all(item not in _listed(actual) for item in blocked)
    if "contains_all" in condition:
        expected = condition.get("contains_all")
        return isinstance(expected, list) and all(item in _listed(actual) for item in expected)
    return True


def is_visible(field: dict[str, Any], values: dict[str, Any]) -> bool:
    if "visible_if" in field and not matches(field.get("visible_if"), values):
        return False
    if "hidden_if" in field and matches(field.get("hidden_if"), values):
        return False
    several = field.get("visible_if_any")
    if "visible_if_any" in field and isinstance(several, list) and not any(matches(item, values) for item in several):
        return False
    return True


def is_disabled(field: dict[str, Any], values: dict[str, Any]) -> bool:
    if "disabled_if" in field and matches(field.get("disabled_if"), values):
        return True
    several = field.get("disabled_if_any")
    if "disabled_if_any" in field and isinstance(several, list) and any(matches(item, values) for item in several):
        return True
    if "enabled_if" in field and not matches(field.get("enabled_if"), values):
        return True
    return False


def is_live(field: dict[str, Any], values: dict[str, Any]) -> bool:
    """A field the person can set now: it is shown and not switched off."""
    return is_visible(field, values) and not is_disabled(field, values)


# --- a form ----------------------------------------------------------------------------------


def form_fields(node: Any) -> list[dict[str, Any]]:
    """The fields a form shows: all of the node but the Source and the Target."""
    return [field for field in node.fields if not is_route_field(field)]


def form_values(node: Any, values: dict[str, Any] | None = None) -> dict[str, Any]:
    """The default of every field of the node, what was given over them."""
    filled = {field_id(field): field_default(field) for field in node.fields if field_id(field)}
    filled.update(values or {})
    return filled


def unknown_values(node: Any, values: dict[str, Any]) -> list[str]:
    known = {field_id(field) for field in node.fields}
    return sorted(name for name in values if name not in known)


def refusal(node: Any, values: dict[str, Any], language: str = "en") -> str:
    """Why the form may not be run as it stands - the first reason, as the window gave it; "" when it may."""
    words = WORDS[safe_language(language)]
    for field in form_fields(node):
        if not is_live(field, values):
            continue
        key, kind, label = field_id(field), field_kind(field), field_label(field, language)
        raw = values.get(key, field_default(field)) if key else field_default(field)
        if bool(field.get("required", False)):
            if kind in TICK_LISTS:
                if not (raw if isinstance(raw, list) else []):
                    return words["tick"].format(field=label)
            elif kind in TICKS:
                if not bool(raw):
                    return words["fill"].format(field=label)
            elif is_empty(raw):
                return words["fill"].format(field=label)
        if kind in NUMBERS:
            if raw in {None, ""}:
                continue
            try:
                number = float(str(raw).replace(",", "."))
            except ValueError:
                return words["number"].format(field=label)
            # "nan" passes every comparison with a limit, and 1.5 went to an engine that takes a whole number:
            # the engine was started and failed instead of the call being refused (the audit of 15.10.2026, F11).
            if not math.isfinite(number):
                return words["number"].format(field=label)
            if is_whole(field, kind) and not number.is_integer():
                return words["whole"].format(field=label)
            least, most = limits(field)
            if least is not None and number < float(least):
                return words["least"].format(field=label, limit=least)
            if most is not None and number > float(most):
                return words["most"].format(field=label, limit=most)
            continue
        if kind not in TICK_LISTS:
            continue
        least = int(field.get("min_selected", 0) or 0)
        if least > 0 and (not isinstance(raw, list) or len(raw) < least):
            return words["tick"].format(field=label)
    return ""


def wrong_choices(node: Any, values: dict[str, Any], language: str = "en") -> list[str]:
    """A value that is none of the options of its field: the window could not set one, a caller can."""
    words, wrong = WORDS[safe_language(language)], []
    for field in form_fields(node):
        key, allowed = field_id(field), option_values(field)
        if key not in values or not allowed or not is_live(field, values):
            continue
        kind, value = field_kind(field), values[key]
        if kind in TICK_LISTS:
            strange = [item for item in (value if isinstance(value, list) else [value]) if item not in allowed]
        elif kind in CHOICES:
            strange = [] if value in allowed else [value]
        else:
            strange = []
        wrong.extend(words["choice"].format(field=field_label(field, language), value=item) for item in strange)
    return wrong


def rgb_channels(value: Any) -> list[int] | None:
    """ "R,G,B" or "#RRGGBB" as three numbers 0-255; None for anything else."""
    text = str(value or "").strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", text):
        text = text.lstrip("#")
        return [int(text[at:at + 2], 16) for at in (0, 2, 4)]
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return [min(255, int(part)) for part in parts]


def rgb_parts(node: Any, field: dict[str, Any]) -> list[str]:
    """
    The names the service joins a colour from: the `fields` of the composite argument that is
    custom when the field that shows this one says so (watermark: color_mode = custom -> color_r,
    color_g, color_b). The window on NiceGUI kept the channels apart and never told them: the
    service took the red of its defaults whatever was set (the inventory of the former window, 12.1).
    """
    shown_by = str((field.get("visible_if") or {}).get("field") or "")
    for spec in (node.parameters.get("composite_args") or {}).values():
        if isinstance(spec, dict) and str((spec.get("custom_if") or spec.get("manual_if") or {}).get("field") or "") == shown_by:
            return [str(name) for name in spec.get("fields") or []]
    return []


def build_parameters(node: Any, values: dict[str, Any], source: Path | str, target: Path | str) -> dict[str, Any]:
    """What the service of the operation is handed.

    The parameters of the node; the Source and the Target under the names of the fields that ask
    for them; then every field the person could set - one that is hidden or switched off is not
    told, and one left empty is not told where the manifest says so (`omit_if_empty`).
    """
    parameters = dict(node.parameters)
    for field in node.fields:
        key = field_id(field)
        if not key:
            continue
        if is_route_field(field):
            parameters[key] = str(target if is_target_field(field) else source)
            continue
        if not is_live(field, values):
            continue
        value = values.get(key, field_default(field))
        if field_kind(field) == "rgb_color":
            # A field of the window alone: what goes is its three channels, under the names the service reads.
            parts, channels = rgb_parts(node, field), rgb_channels(value)
            if len(parts) == 3 and channels is not None:
                parameters.update(zip(parts, channels))
            continue
        if bool(field.get("omit_if_empty", False)) and value in {None, ""}:
            continue
        parameters[key] = value
    return parameters


def coerce(field: dict[str, Any], text: str) -> Any:
    """`--set name=value`: the text of a console as the value its field holds."""
    kind = field_kind(field)
    if kind in TICK_LISTS:
        return [part.strip() for part in text.split(",") if part.strip()]
    if kind in TICKS:
        lowered = text.strip().lower()
        if lowered in {"1", "true", "yes", "on", "да"}:
            return True
        if lowered in {"0", "false", "no", "off", "нет", ""}:
            return False
        raise ValueError(f"true or false is expected, got {text!r}")
    if kind in NUMBERS and text.strip() != "":
        try:
            number = float(text.replace(",", "."))
        except ValueError as error:
            raise ValueError(f"a number is expected, got {text!r}") from error
        return int(number) if number.is_integer() and kind != "float" else number
    # A switch keeps the kind of its options: True and False of "Unsharp Mask" are not words.
    for option in option_values(field):
        if not isinstance(option, str) and str(option).lower() == text.strip().lower():
            return option
    return text


# --- the manifest ----------------------------------------------------------------------------


def iter_nodes(nodes: Iterable[Any]) -> Iterable[Any]:
    for node in nodes:
        yield node
        yield from iter_nodes(getattr(node, "children", ()))


def all_nodes(manifest: Any) -> list[Any]:
    return list(iter_nodes(manifest.operation_groups))


def find_node(manifest: Any, operation_id: str, runs: bool = True) -> Any | None:
    """The node of the name; with `runs` - only one that runs something."""
    for node in all_nodes(manifest):
        if node.id == operation_id and (node.service or not runs):
            return node
    for operation in [*manifest.operations, *manifest.maintenance_operations]:
        if operation.id == operation_id:
            return operation
    return None


def describe_field(field: dict[str, Any]) -> dict[str, Any]:
    """A field as the window draws it: what the manifest says, the default worked out, the place named."""
    told = dict(field)
    told["id"], told["type"], told["default"] = field_id(field), field_kind(field), field_default(field)
    told["route"] = ("target" if is_target_field(field) else "source") if is_route_field(field) else ""
    options = field.get("options", [])
    if isinstance(options, list):
        told["options"] = [dict(option, value=option_value(option)) if isinstance(option, dict)
                           else {"value": option, "label": str(option)} for option in options]
    return told


def describe_node(node: Any) -> dict[str, Any]:
    return {
        "id": node.id, "title": node.title, "title_ru": node.title_ru,
        "description": node.description, "description_ru": node.description_ru,
        "kind": node.kind, "runs": bool(node.service),
        "fields": [describe_field(field) for field in node.fields],
        "children": [describe_node(child) for child in getattr(node, "children", ())],
    }


def describe(manifest: Any) -> dict[str, Any]:
    tool = manifest.raw.get("tool", {}) if isinstance(manifest.raw.get("tool"), dict) else {}
    return {
        "tool": {"id": tool.get("id", ""), "name": tool.get("name", "")},
        "nodes": [describe_node(node) for node in manifest.operation_groups],
        "maintenance": [describe_node(operation) for operation in manifest.maintenance_operations],
        "operations": sum(1 for node in all_nodes(manifest) if node.service),
    }


# --- what the window draws -------------------------------------------------------------------

# The colour a choice wears. The window on NiceGUI worked it out from the words of a choice every
# time it drew one; it is worked out here, once, and told to the window as data - the window does
# not guess. A `tone` written in the manifest wins.
_LOSSLESS = {"png", "tif", "tiff"}
_LOSSY = {"avif", "heic", "heif", "jpg", "jpeg", "webp"}
_AS_IS = {"original", "source", "native"}
_FORMAT_FIELDS = {"to", "output_format", "input_format", "format"}
_FORMAT_HINTS = ("format", "formats", "формат", "форматы")
_WORD = re.compile(r"[^a-z0-9а-яё]+")


def _tokens(*texts: Any) -> set[str]:
    raw = " ".join(str(text) for text in texts).lower()
    found = {part for part in _WORD.split(raw) if part}
    compact = _WORD.sub("_", raw).strip("_")
    return found | ({compact} if compact else set())


def option_tone(field: dict[str, Any], option: Any) -> str:
    if isinstance(option, dict) and option.get("tone"):
        return str(option["tone"]).strip().lower()
    labels = [option.get("label", ""), option.get("label_ru", "")] if isinstance(option, dict) else [option]
    tokens, key = _tokens(option_value(option), *labels), field_id(field).lower()
    names = (key, str(field.get("group") or "").lower(), str(field.get("label", "")).lower(), str(field.get("label_ru", "")).lower())
    if key in _FORMAT_FIELDS or any(hint in name for hint in _FORMAT_HINTS for name in names):
        if tokens & _AS_IS:
            return "source"
        if tokens & _LOSSLESS:
            return "lossless"
        if tokens & _LOSSY:
            return "lossy"
    if key in {"algorithm", "resample", "resampling", "interpolation"}:
        return "process"
    if tokens & {"lanczos", "bicubic", "photo", "jpg", "jpeg", "webp", "avif", "heif", "heic"}:
        return "photo"
    if tokens & {"box", "png", "tif", "tiff", "srgb", "a4", "a3", "a5", "portrait", "landscape"}:
        return "graphics"
    if tokens & {"nearest", "keep", "source", "raw", "as_is", "как_есть", "без_обрезки", "off", "выкл", "black", "white"}:
        return "raw"
    if tokens & {"target", "fit", "подогнать", "custom", "свой", "crop", "cmyk", "strip", "удалить", "jpg75", "embedded"}:
        return "warn"
    if tokens & {"on", "вкл", "scale", "dpi", "contain", "pad", "preserve", "сохранить", "one", "multiple", "several"}:
        return "process"
    if key in {"scale_mode", "print_size_mode", "metadata", "target_profile", "mode", "fit_mode"}:
        return "process"
    return ""


# The kinds of field of the manifest under the names the window draws them by.
WINDOW_KINDS = {"radio": "radio", "select": "radio", "checkboxes": "checkboxes", "checkbox": "checkbox",
                "number": "number", "float": "number", "text": "text", "quality": "quality", "rgb_color": "rgb_color",
                # A number between two ends, with a slider beside its field: brightness, contrast, a tolerance.
                "slider": "slider"}
CONDITIONS = ("visible_if", "hidden_if", "visible_if_any", "disabled_if", "disabled_if_any", "enabled_if")


def window_field(field: dict[str, Any]) -> dict[str, Any]:
    """A field of a form as the window draws it."""
    kind = field_kind(field)
    told: dict[str, Any] = {
        "id": field_id(field), "kind": WINDOW_KINDS.get(kind, kind), "default": field_default(field),
        "group": str(field.get("group") or ""), "label": str(field.get("label") or field_id(field)),
        "label_ru": str(field.get("label_ru") or ""), "hint": str(field.get("hint") or ""), "hint_ru": str(field.get("hint_ru") or ""),
        "placeholder": str(field.get("placeholder") or ""), "min_selected": int(field.get("min_selected", 0) or 0),
        # A whole number is typed and told as one: "75", never "75.0".
        "whole": is_whole(field, kind),
        "required": bool(field.get("required", False)), "wide": str(field.get("span", "")).lower() in {"full", "wide", "100%"},
    }
    # A slider drawn in what it does - dark to light, grey to colour: its colours from end to end, no words needed.
    if isinstance(field.get("track"), list):
        told["track"] = [str(colour) for colour in field["track"]]
    least, most = limits(field)
    for limit, value in (("min", least), ("max", most), ("step", field.get("step"))):
        if value is not None:
            told[limit] = value
    for condition in CONDITIONS:
        if condition in field:
            told[condition] = field[condition]
    options = field.get("options", [])
    if isinstance(options, list) and options:
        told["options"] = []
        for option in options:
            given = option if isinstance(option, dict) else {}
            item = {"value": option_value(option), "label": str(given.get("label", option_value(option))),
                    "label_ru": str(given.get("label_ru", "")), "tone": option_tone(field, option)}
            if given.get("swatch") or given.get("color"):
                item["swatch"] = str(given.get("swatch") or given.get("color"))
            told["options"].append(item)
    return told


def window_node(node: Any, icon: str = "", block: tuple[str, str] = ("", "")) -> dict[str, Any]:
    """An operation as a button and a form of the window. The Source and the Target are not of a form and are not told."""
    fields = [window_field(field) for field in form_fields(node)]
    return {
        "id": node.id, "title": node.title, "title_ru": node.title_ru,
        "description": node.description, "description_ru": node.description_ru,
        # The one filled button is the run of a form, at the top right; a button of a block runs at once and is quiet.
        "kind": node.kind, "icon": icon, "tone": "quick" if block[0] else "run" if fields else "", "block": block[0], "block_ru": block[1],
        # Only a button of a block runs at a press with no form; the operation of a page is a form, with fields or without.
        "runs": bool(node.service), "direct": bool(block[0]) and not fields, "parameters": {}, "fields": fields,
    }
