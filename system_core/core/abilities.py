"""What the engine can do on this machine: the badges in the header of the window.

A badge says at once why an operation will not take a file - a HEIC that does not read, a RAW
without its reader - and its tooltip says what stands behind it. Word and PowerPoint are no
condition of any operation (a DOCX, a PPTX and a PDF are changed without Office); their badges say
whether the old formats could be taken through them.
"""
from __future__ import annotations

from typing import Any

WORDS = {
    "heic_ok": ("HEIC and HEIF are read (pillow-heif {0}).", "HEIC и HEIF читаются (pillow-heif {0})."),
    "heic_no": ("HEIC and HEIF are not read: pillow-heif is missing in the environment - build it anew (builder_main.cmd).",
                "HEIC и HEIF не читаются: в окружении нет pillow-heif - соберите окружение заново (builder_main.cmd)."),
    "avif_ok": ("AVIF is read and written (Pillow {0}).", "AVIF читается и пишется (Pillow {0})."),
    "avif_no": ("AVIF is not read: this Pillow ({0}) has no AVIF.", "AVIF не читается: в этом Pillow ({0}) нет AVIF."),
    "raw_ok": ("RAW of cameras (CR2, CR3, DNG) is read (rawpy {0}).", "RAW камер (CR2, CR3, DNG) читается (rawpy {0})."),
    "raw_no": ("RAW of cameras is not read: rawpy is missing in the environment.", "RAW камер не читается: в окружении нет rawpy."),
    "word_ok": ("Microsoft Word is installed. No operation needs it: a DOCX is changed without it.",
                "Microsoft Word установлен. Ни одной операции он не нужен: DOCX правится без него."),
    "word_no": ("Microsoft Word is not found. No operation needs it: a DOCX is changed without it; an old .doc is not read.",
                "Microsoft Word не найден. Операциям он не нужен: DOCX правится без него; старый .doc не прочитать."),
    "powerpoint_ok": ("Microsoft PowerPoint is installed. No operation needs it: a PPTX is changed without it.",
                      "Microsoft PowerPoint установлен. Ни одной операции он не нужен: PPTX правится без него."),
    "powerpoint_no": ("Microsoft PowerPoint is not found. No operation needs it: a PPTX is changed without it; an old .ppt is not read.",
                      "Microsoft PowerPoint не найден. Операциям он не нужен: PPTX правится без него; старый .ppt не прочитать."),
}


def _say(key: str, *values: Any) -> dict[str, str]:
    """A tooltip in both languages: the window shows the one it speaks, and changes it without asking again."""
    english, russian = WORDS[key]
    return {"tip": english.format(*values), "tip_ru": russian.format(*values)}


def _office(program: str) -> bool:
    """Whether a program of Office is registered for automation on this machine (its ProgID has a CLSID)."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{program}.Application\\CLSID"):
            return True
    except OSError:
        return False
    except ImportError:  # not Windows
        return False


def abilities() -> list[dict[str, Any]]:
    import PIL
    from PIL import features

    rows: list[dict[str, Any]] = []
    try:
        import pillow_heif

        rows.append({"id": "heic", "text": "HEIC", "ok": True, **_say("heic_ok", pillow_heif.__version__)})
    except Exception:
        rows.append({"id": "heic", "text": "HEIC", "ok": False, **_say("heic_no")})
    try:
        avif = "avif" in features.get_supported() and bool(features.check("avif"))
    except Exception:
        avif = False
    rows.append({"id": "avif", "text": "AVIF", "ok": avif, **_say("avif_ok" if avif else "avif_no", PIL.__version__)})
    try:
        import rawpy

        rows.append({"id": "raw", "text": "RAW", "ok": True, **_say("raw_ok", rawpy.__version__)})
    except Exception:
        rows.append({"id": "raw", "text": "RAW", "ok": False, **_say("raw_no")})
    for key, program, text in (("word", "Word", "WORD"), ("powerpoint", "PowerPoint", "POWERPOINT")):
        found = _office(program)
        rows.append({"id": key, "text": text, "ok": found, **_say(f"{key}_{'ok' if found else 'no'}")})
    return rows
