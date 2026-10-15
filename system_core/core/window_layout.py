"""Where every operation stands in the window: config\\window_layout.yaml read and checked.

The manifest says what an operation is, the layout - where it stands: a section, and inside it the
row of pictures, the row of documents or the block of quick buttons. The console command hands the
layout to the window in `describe`; the window draws what it is told and knows no operation by name.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_yaml_or_json

ROWS = ("images", "documents", "quick")


def load(config: Path) -> dict[str, Any]:
    path = config / "window_layout.yaml"
    raw = load_yaml_or_json(path) if path.is_file() else {}
    return raw if isinstance(raw, dict) else {}


# The documents an operation over documents may say it takes: the window draws the mark of each on its button.
FORMATS = ("docx", "pptx", "pdf")


def _place(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"op": item, "icon": "", "preview": False, "formats": []}
    return {"op": str(item.get("op", "")).strip(), "icon": str(item.get("icon", "")).strip(), "preview": bool(item.get("preview", False)),
            "formats": [str(kind).strip().lower() for kind in item.get("formats") or []]}


def describe(layout: dict[str, Any]) -> dict[str, Any]:
    """The layout as the window reads it: every row a list of {op, icon}, every text in both languages."""
    sections = []
    for section in layout.get("sections") or []:
        told = {key: str(section.get(key, "")) for key in ("id", "title", "title_ru", "about", "about_ru", "icon")}
        for row in ROWS:
            told[row] = [_place(item) for item in section.get(row) or []]
        sections.append(told)
    return {
        "sections": sections,
        "service": [_place(item) for item in layout.get("service") or []],
        "pending": [str(item) for item in layout.get("pending") or []],
    }


def placed(layout: dict[str, Any]) -> list[str]:
    """Every operation the layout names, as many times as it names it."""
    told = describe(layout)
    names = [place["op"] for section in told["sections"] for row in ROWS for place in section[row]]
    return names + [place["op"] for place in told["service"]] + told["pending"]


def problems(layout: dict[str, Any], operations: set[str]) -> list[str]:
    """What is wrong between the layout and the manifest; nothing when every operation stands once."""
    names = placed(layout)
    wrong = [f"stands nowhere in the window: {name}" for name in sorted(operations - set(names))]
    wrong += [f"is not an operation of the manifest: {name}" for name in sorted(set(names) - operations)]
    wrong += [f"stands more than once: {name}" for name in sorted({name for name in names if names.count(name) > 1})]
    told = describe(layout)
    ids = [section["id"] for section in told["sections"]]
    wrong += [f"a section without an id or with one taken: {name!r}" for name in sorted({i for i in ids if not i or ids.count(i) > 1})]
    wrong += [f"the section {section['id']} has no operation" for section in told["sections"] if not any(section[row] for row in ROWS)]
    wrong += [f"the section {section['id']} has no {key}" for section in told["sections"]
              for key in ("title", "title_ru", "about", "about_ru", "icon") if not section[key]]
    # Every operation over documents says what it takes - a button over a DOCX looked like one over a picture.
    wrong += [f"{place['op']} stands among the documents and says no formats" for section in told["sections"]
              for place in section["documents"] if not place["formats"]]
    wrong += [f"{place['op']}: a format of no known kind: {kind}" for section in told["sections"] for row in ROWS
              for place in section[row] for kind in place["formats"] if kind not in FORMATS]
    return wrong


QUICK = ("Quick", "Быстро")


def for_window(layout: dict[str, Any], manifest: Any) -> dict[str, Any]:
    """The layout as the window reads it: sections, the pages of each, the operations of every page.

    A page is an operation of the row of pictures or of the row of documents; the quick buttons of a
    section stand on its first page, as a block of buttons that run at once.
    """
    from . import operation_model as model

    told = describe(layout)

    def node(place: dict[str, Any], block: tuple[str, str] = ("", "")) -> dict[str, Any]:
        found = model.find_node(manifest, place["op"])
        if found is None:
            raise ValueError(f"the layout names an operation the manifest does not have: {place['op']}")
        return model.window_node(found, place["icon"], block)

    sections = []
    for section in told["sections"]:
        pages = []
        for row in ("images", "documents"):
            for place in section[row]:
                operation = node(place)
                pages.append({"id": operation["id"], "title": operation["title"], "title_ru": operation["title_ru"],
                              "icon": place["icon"], "about": operation["description"], "about_ru": operation["description_ru"],
                              "row": row, "source": True, "preview": place["preview"], "formats": place["formats"],
                              "operations": [operation]})
        if pages:
            pages[0]["operations"] += [node(place, QUICK) for place in section["quick"]]
        sections.append({key: section[key] for key in ("id", "title", "title_ru", "about", "about_ru", "icon")} | {"pages": pages})
    return {"sections": sections, "service": [node(place) for place in told["service"]], "folders": [], "shared": []}
