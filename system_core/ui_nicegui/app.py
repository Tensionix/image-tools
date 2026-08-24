from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable
import atexit
import argparse
import contextlib
import ctypes
from ctypes import wintypes
import io
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import app as nicegui_app, run, ui  # type: ignore
from system_core.ui_nicegui.workbench import (
    WorkbenchAdapter,
    WorkbenchConfig,
    WorkbenchHandlers,
    WorkbenchRenderer,
    WorkbenchRole,
    WORKBENCH_FEEDBACK_CSS,
    WORKBENCH_LAYOUT_CSS,
    WORKBENCH_OVERRIDE_CSS,
    canonical_role,
)

AUDION_CANONICAL_TOOLTIP_DELAY_MS = 1500
AUDION_CANONICAL_TOOLTIP_HIDE_DELAY_MS = 100
AUDION_CANONICAL_TOOLTIP_TRANSITION_MS = 100


def install_audion_canonical_tooltip_defaults() -> None:
    try:
        from nicegui.elements.tooltip import Tooltip as NiceGuiTooltip  # type: ignore
    except Exception:
        return
    if getattr(NiceGuiTooltip, "_audion_canonical_tooltip_defaults", False):
        return
    original_init = NiceGuiTooltip.__init__

    def audion_tooltip_init(self: Any, text: str = "") -> None:
        original_init(self, text)
        self.props["delay"] = AUDION_CANONICAL_TOOLTIP_DELAY_MS
        self.props["hide-delay"] = AUDION_CANONICAL_TOOLTIP_HIDE_DELAY_MS
        self.props["transition-duration"] = AUDION_CANONICAL_TOOLTIP_TRANSITION_MS
        self.classes("audion-tooltip")

    NiceGuiTooltip.__init__ = audion_tooltip_init  # type: ignore[method-assign]
    NiceGuiTooltip._audion_canonical_tooltip_defaults = True  # type: ignore[attr-defined]


install_audion_canonical_tooltip_defaults()


AUDION_CANONICAL_UI_CSS = """
<style id="audion-canonical-tooltip-icon-style">
  html body .q-tooltip,
  html body .audion-tooltip {
    background: rgb(23, 33, 43) !important;
    background-color: rgb(23, 33, 43) !important;
    color: #f4f8fb !important;
    border: 1px solid rgba(88, 166, 255, 0.24) !important;
    border-radius: 8px !important;
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.34) !important;
  }
  html body .q-icon.material-icons,
  html body .q-icon.material-symbols-outlined,
  html body .q-icon.material-symbols-rounded,
  html body i.material-icons,
  html body i.material-symbols-outlined,
  html body i.material-symbols-rounded,
  html body .q-btn .q-icon,
  html body .q-btn .material-icons,
  html body .q-btn .material-symbols-outlined,
  html body .q-btn .material-symbols-rounded,
  html body .q-field .q-field__append .q-icon,
  html body .q-field .q-field__prepend .q-icon,
  html body .q-item .q-icon,
  html body .q-menu .q-icon,
  html body .audion-label-icon,
  html body .audion-path-option-pin,
  html body .audion-select-option-pin {
    font-size: 14px !important;
    width: 14px !important;
    min-width: 14px !important;
    height: 14px !important;
    line-height: 14px !important;
  }
  html body .material-icons,
  html body .q-icon.material-icons {
    font-family: "Material Icons" !important;
  }
  html body .material-symbols-outlined,
  html body .q-icon.material-symbols-outlined {
    font-family: "Material Symbols Outlined" !important;
  }
  html body .material-symbols-rounded,
  html body .q-icon.material-symbols-rounded {
    font-family: "Material Symbols Rounded" !important;
  }
</style>
"""


def add_audion_canonical_ui_styles() -> None:
    ui.add_head_html(AUDION_CANONICAL_UI_CSS)



def audion_tooltip_path_text(path_value: Any) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        return str(path)
    except Exception:
        return raw


def audion_folder_button_tooltip(folder_id: str, path_value: Any) -> str:
    key = str(folder_id or "folder").strip().lower()
    path_text = audion_tooltip_path_text(path_value)
    if getattr(settings, "language", "ru") == "ru":
        descriptions = {
            "logs": "папку логов запусков и вывода терминала",
            "report": "папку отчётов и результатов операций",
            "reports": "папку отчётов и результатов операций",
            "config": "папку конфигурации проекта: manifest, GUI-настройки и кэши",
            "state": "папку рабочего состояния GUI",
            "project": "корневую папку проекта",
            "root": "корневую папку проекта",
            "data": "папку данных проекта",
            "pipeline": "папку pipeline-артефактов и промежуточных результатов",
            "github": "папку GitHub-артефактов проекта",
            "install": "папку install/runtime-артефактов проекта",
        }
        description = descriptions.get(key, f"папку {folder_id}")
        return f"Открыть {description}: {path_text}" if path_text else f"Открыть {description}."
    descriptions = {
        "logs": "the logs folder with run and terminal output",
        "report": "the reports/results folder",
        "reports": "the reports/results folder",
        "config": "the project config folder with manifest, GUI settings, and caches",
        "state": "the GUI state folder",
        "project": "the project root folder",
        "root": "the project root folder",
        "data": "the project data folder",
        "pipeline": "the pipeline artifacts and intermediate results folder",
        "github": "the project GitHub artifacts folder",
        "install": "the project install/runtime artifacts folder",
    }
    description = descriptions.get(key, f"the {folder_id} folder")
    return f"Open {description}: {path_text}" if path_text else f"Open {description}."


def audion_terminal_action_tooltip(action: str) -> str:
    key = str(action or "").strip().lower()
    if getattr(settings, "language", "ru") == "ru":
        tips = {
            "clear_terminal_window": "Очистить только видимое окно терминала. Файлы логов, отчёты и результаты операций не удаляются.",
            "expand": "Открыть терминал в большом окне, чтобы читать длинный вывод без тесной панели.",
            "expand_log": "Открыть терминал в большом окне, чтобы читать длинный вывод без тесной панели.",
            "pin_command": "Закрепить текущую команду в истории терминала для быстрого повторного запуска.",
            "unpin_command": "Открепить текущую команду от верхней части истории терминала.",
            "clear_history": "Очистить историю команд терминала. Закреплённые команды и файлы логов не удаляются.",
            "terminal_shell": "Выбрать оболочку, в которой будут запускаться команды терминала.",
            "terminal_history": "Выбрать ранее сохранённую или закреплённую команду терминала.",
            "terminal_command": "Команда, которая будет выполнена из выбранной рабочей папки.",
            "terminal_cwd": "Рабочая папка терминала. Команда будет запущена именно отсюда.",
            "pick_folder": "Выбрать рабочую папку терминала через системный диалог.",
            "terminal_run": "Запустить введённую команду в выбранной оболочке и рабочей папке.",
            "latest_report": "Открыть последний созданный отчёт, если он уже есть.",
            "command_preview": "Показать команду, которая будет запущена с текущими параметрами, без выполнения операции.",
            "report_view": "Открыть встроенный список отчётов без перехода в проводник.",
            "close": "Закрыть большое окно терминала и вернуться к основной панели.",
        }
    else:
        tips = {
            "clear_terminal_window": "Clear only the visible terminal window. Log files, reports, and operation results are not deleted.",
            "expand": "Open the terminal in a large window for reading long output comfortably.",
            "expand_log": "Open the terminal in a large window for reading long output comfortably.",
            "pin_command": "Pin the current terminal command for quick reuse.",
            "unpin_command": "Remove the current command from the pinned command list.",
            "clear_history": "Clear terminal command history. Pinned commands and log files are not deleted.",
            "terminal_shell": "Choose the shell used to run terminal commands.",
            "terminal_history": "Pick a saved or pinned terminal command.",
            "terminal_command": "Command to run from the selected working folder.",
            "terminal_cwd": "Terminal working folder. Commands are started from here.",
            "pick_folder": "Choose the terminal working folder with the system dialog.",
            "terminal_run": "Run the entered command in the selected shell and working folder.",
            "latest_report": "Open the latest generated report, if one exists.",
            "command_preview": "Show the command that would run with the current settings, without executing it.",
            "report_view": "Open the built-in reports list without switching to the file explorer.",
            "close": "Close the large terminal window and return to the main panel.",
        }
    return tips.get(key, key.replace("_", " ").strip())


from system_core.core.ansi import terminal_lines_html as _terminal_lines_html
from system_core.core.config import load_yaml_or_json
from system_core.core.jobs import execute_operation
from system_core.core.manifest import CommandNode, Operation, load_manifest
from system_core.core.paths import ensure_project_dirs, get_project_paths, open_folder
from system_core.core.ui_settings import load_ui_settings


paths = get_project_paths(ROOT)
ensure_project_dirs(paths)
manifest = load_manifest(paths.config / "tool_manifest.yaml")
settings_path = paths.config / "gui_settings.yaml"
settings = load_ui_settings(settings_path)
tool_info: dict[str, Any] = manifest.raw.get("tool", {})
ui_info: dict[str, Any] = manifest.raw.get("ui", {})
TERMINAL_HISTORY_LIMIT = 1500

DEFAULT_THEME_ID = "code_dark"
THEME_ALIASES = {"dark": "code_dark", "light": "code_light"}
PARALLEL_SETTINGS_FILE = "parallel_settings.json"
DEFAULT_PARALLEL_ENABLED = False
DEFAULT_WORKER_COUNT = 8
MIN_WORKER_COUNT = 1
MAX_WORKER_COUNT = 24


def terminal_lines_html(lines, *, leading_newline: bool = False) -> str:
    return _terminal_lines_html(lines, leading_newline=False).replace("\n", "")


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_worker_count(value: Any) -> int:
    try:
        number = int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        number = DEFAULT_WORKER_COUNT
    return max(MIN_WORKER_COUNT, min(MAX_WORKER_COUNT, number))


def parallel_settings_path() -> Path:
    return paths.config / PARALLEL_SETTINGS_FILE


def load_parallel_settings() -> dict[str, Any]:
    path = parallel_settings_path()
    if not path.exists():
        return {"parallel_enabled": DEFAULT_PARALLEL_ENABLED, "worker_count": DEFAULT_WORKER_COUNT}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "parallel_enabled": normalize_bool(raw.get("parallel_enabled", raw.get("global_parallel_enabled", DEFAULT_PARALLEL_ENABLED))),
        "worker_count": normalize_worker_count(raw.get("worker_count", raw.get("global_worker_count", DEFAULT_WORKER_COUNT))),
    }


def save_parallel_settings() -> None:
    payload = {
        "parallel_enabled": bool(state.get("parallel_enabled", DEFAULT_PARALLEL_ENABLED)),
        "worker_count": normalize_worker_count(state.get("worker_count", DEFAULT_WORKER_COUNT)),
    }
    path = parallel_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key).strip(): str(item).strip() for key, item in value.items() if str(key).strip()}


def load_ui_colors(path: Path) -> dict[str, Any]:
    data = load_yaml_or_json(path) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    themes: dict[str, dict[str, Any]] = {}
    themes_raw = data.get("themes", {})
    if not isinstance(themes_raw, dict):
        themes_raw = {}
    for theme_id, theme_data in themes_raw.items():
        if not isinstance(theme_data, dict):
            continue
        normalized_id = str(theme_id).strip().lower()
        if not normalized_id:
            continue
        themes[normalized_id] = {
            "label": str(theme_data.get("label") or normalized_id).strip(),
            "label_ru": str(theme_data.get("label_ru") or theme_data.get("label") or normalized_id).strip(),
            "mode": "dark" if str(theme_data.get("mode", "dark")).lower() == "dark" else "light",
            "tokens": _string_map(theme_data.get("tokens", {})),
        }
    if DEFAULT_THEME_ID not in themes:
        themes[DEFAULT_THEME_ID] = {
            "label": "Code Dark",
            "label_ru": "Code Темная",
            "mode": "dark",
            "tokens": {
                "color-background-primary": "#141413",
                "color-background-secondary": "#1f1e1a",
                "color-background-tertiary": "#0f0f0e",
                "color-text-primary": "#faf9f5",
                "color-text-secondary": "#e8e6dc",
                "color-text-tertiary": "#b0aea5",
                "color-border-tertiary": "rgba(250, 249, 245, 0.15)",
                "color-border-secondary": "rgba(250, 249, 245, 0.3)",
                "color-border-primary": "rgba(250, 249, 245, 0.4)",
                "color-accent-primary": "#6a9bcc",
            },
        }
    return {
        "ramps": data.get("ramps", {}) if isinstance(data.get("ramps", {}), dict) else {},
        "tokens": _string_map(data.get("tokens", {})),
        "themes": themes,
    }


ui_colors = load_ui_colors(paths.config / "ui_colors.yaml")


def _workspace_history_file() -> Path:
    return paths.config / "path_history.json"


def _startup_workspace_path(role: str, configured: str, legacy: str, default_path: Path) -> str:
    return str(default_path)


def load_workspace_route_settings() -> tuple[str, str]:
    return (
        _startup_workspace_path("source", "", "", paths.input),
        _startup_workspace_path("target", "", "", paths.output),
    )


def _yaml_string(value: Any) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _workspace_setting_for_disk(role: str, path_value: Any, default_path: Path) -> str:
    return ""


def display_path(path_value: Any) -> str:
    text = str(path_value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(ROOT)
    except (OSError, ValueError):
        return str(path)
    return str(relative) or "."

def save_app_settings() -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = _workspace_setting_for_disk("source", getattr(settings, "source_path", ""), paths.input)
    destination_path = _workspace_setting_for_disk("target", getattr(settings, "destination_path", ""), paths.output)
    text = (
        "gui:\n"
        "  # Change to \"en\" for public GitHub builds.\n"
        f"  language: \"{settings.language if settings.language in {'en', 'ru'} else 'ru'}\"\n"
        f"  theme: \"{normalize_theme_id(settings.theme)}\"\n"
        f"  emoji: {str(bool(getattr(settings, 'emoji', False))).lower()}\n"
        f"  allow_runtime_switching: {str(bool(getattr(settings, 'allow_runtime_switching', True))).lower()}\n"
        f"  advanced_open: {str(bool(getattr(settings, 'advanced_open', False))).lower()}\n"
        f"  source_path: {_yaml_string(source_path)}\n"
        f"  destination_path: {_yaml_string(destination_path)}\n"
    )
    settings_path.write_text(text, encoding="utf-8", newline="\n")

settings.source_path, settings.destination_path = load_workspace_route_settings()


def tolerate_missing_process_pool() -> None:
    """Keep the GUI usable when a portable environment blocks multiprocessing."""
    try:
        import nicegui.run as nicegui_run  # type: ignore
    except Exception:
        return

    original_setup = getattr(nicegui_run, "setup", None)
    if not callable(original_setup):
        return

    def safe_setup() -> None:
        try:
            original_setup()
        except (OSError, PermissionError) as exc:
            logging.warning("NiceGUI process pool disabled: %s", exc)
            nicegui_run.process_pool = None

    nicegui_run.setup = safe_setup


tolerate_missing_process_pool()

LABELS = {
    "ru": {
        "workspace": "Рабочие папки",
        "operations": "Операции",
        "maintenance": "Обслуживание",
        "status": "Статус",
        "log": "Журнал операции",
        "idle": "Ожидание",
        "running": "Выполняется",
        "done": "Готово",
        "error": "Ошибка",
        "cancel": "Отменить",
        "another_running": "Другая операция уже выполняется.",
        "confirm_title": "Подтвердите действие",
        "confirm_note": "Действие может изменить управляемую рабочую область.",
        "run": "Запустить",
        "back": "Назад",
        "selected_operation": "Выбрана команда",
        "open_menu": "Открыть",
        "parameters": "Параметры",
        "section_encoding": "Кодирование",
        "section_format": "Формат",
        "section_options": "Опции",
        "section_output": "Результат",
        "section_parameters": "Параметры",
        "section_preset": "Профиль",
        "section_run": "Запуск",
        "section_source": "Источник",
        "section_thumbnail": "Миниатюра",
        "folder_paths": "Папки",
        "source_folder": "Источник",
        "target_folder": "Назначение",
        "source_selected": "Источник выбран.",
        "target_selected": "Назначение выбрано.",
        "source_folder_missing": "Источник не найден: {path}",
        "clear_io_short": "Сбросить",
        "delete_io_short": "Удалить",
        "add_file_short": "Добавить файл...",
        "path_required": "Выберите путь.",
        "path_pinned": "Путь закреплен.",
        "path_unpinned": "Закрепление снято.",
        "path_removed": "Путь удален из истории.",
        "path_selected": "Путь выбран.",
        "resize_panels": "Изменить ширину панелей",
        "close": "Закрыть",
        "logs": "Журнал",
        "report": "Отчёт",
        "config": "CONFIG",
        "expand": "Развернуть",
        "clear_terminal_window": "Очистить окно терминала",
        "add_files": "Добавить файлы...",
        "add_folder": "Добавить папку...",
        "copy_output_to_input": "КОПИРОВАТЬ Output в Input",
        "copy_output_to_input_confirm": "Содержимое текущей папки Output будет скопировано в текущую папку Input с перезаписью совпадающих файлов. После успешного копирования Output будет очищен.",
        "copy_output_to_input_tooltip": "Копирует всё из текущего Output в текущий Input с перезаписью совпадающих имён, затем очищает Output. Удобно для цепочки: обрезка -> следующая обработка.",
        "copy_output_to_input_empty": "Output пуст: копировать нечего.",
        "copy_output_to_input_done": "Output скопирован в Input: {copied} элемент(ов), очищено {removed} элемент(ов).",
        "copy_output_to_input_same_path": "Input и Output указывают на одну папку.",
        "copy_output_to_input_nested_input": "Input находится внутри Output. Очистка Output в таком режиме могла бы удалить Input.",
        "file_list": "File List",
        "file_list_button": "Список",
        "file_list_empty": "INPUT has no files.",
        "file_list_missing": "INPUT was not found: {path}",
        "file_list_ready": "File list generated: {count}.",
        "terminal_file": "File",
        "choose_folder": "Выбрать...",
        "stage_files": "Добавление файлов в input",
        "stage_folder": "Добавление папки в input",
        "pick_folder": "Выбор папки",
        "picker_cancelled": "Выбор отменён.",
        "operation_done": "Операция завершена.",
        "operation_failed": "Операция завершилась с кодом {code}.",
        "field_required": "Заполните поле: {field}",
        "select_required": "Выберите хотя бы один пункт: {field}",
        "theme": "Тема",
        "theme_saved": "Тема сохранена. Перезагружаю интерфейс.",
        "lang_switch": "EN",
    },
    "en": {
        "workspace": "Workspace folders",
        "operations": "Operations",
        "maintenance": "Maintenance",
        "status": "Status",
        "log": "Operation log",
        "idle": "Idle",
        "running": "Running",
        "done": "Done",
        "error": "Error",
        "cancel": "Cancel",
        "another_running": "Another operation is already running.",
        "confirm_title": "Confirm action",
        "confirm_note": "This action may change the managed workspace.",
        "run": "Run",
        "back": "Back",
        "selected_operation": "Selected command",
        "open_menu": "Open",
        "parameters": "Parameters",
        "section_encoding": "Encoding",
        "section_format": "Format",
        "section_options": "Options",
        "section_output": "Output",
        "section_parameters": "Parameters",
        "section_preset": "Profile",
        "section_run": "Run",
        "section_source": "Source",
        "section_thumbnail": "Thumbnail",
        "folder_paths": "Folders",
        "source_folder": "Source",
        "target_folder": "Target",
        "source_selected": "Source selected.",
        "target_selected": "Target selected.",
        "source_folder_missing": "Source was not found: {path}",
        "clear_io_short": "Reset",
        "delete_io_short": "Delete",
        "add_file_short": "Add file...",
        "path_required": "Choose a path.",
        "path_pinned": "Path pinned.",
        "path_unpinned": "Path unpinned.",
        "path_removed": "Path removed from history.",
        "path_selected": "Path selected.",
        "resize_panels": "Resize panels",
        "close": "Close",
        "logs": "Logs",
        "report": "Report",
        "config": "CONFIG",
        "expand": "Expand",
        "clear_terminal_window": "Clear terminal window",
        "add_files": "Add files...",
        "add_folder": "Add folder...",
        "copy_output_to_input": "COPY Output to Input",
        "copy_output_to_input_confirm": "The current Output folder will be copied into the current Input folder with same-name files overwritten. After a successful copy, Output will be cleared.",
        "copy_output_to_input_tooltip": "Copies everything from current Output to current Input with same-name overwrites, then clears Output. Useful for a crop -> next processing chain.",
        "copy_output_to_input_empty": "Output is empty: nothing to copy.",
        "copy_output_to_input_done": "Output copied to Input: {copied} item(s), cleared {removed} item(s).",
        "copy_output_to_input_same_path": "Input and Output point to the same folder.",
        "copy_output_to_input_nested_input": "Input is inside Output. Clearing Output in this mode could delete Input.",
        "file_list": "File List",
        "file_list_button": "List",
        "file_list_empty": "INPUT has no files.",
        "file_list_missing": "INPUT was not found: {path}",
        "file_list_ready": "File list generated: {count}.",
        "terminal_file": "File",
        "choose_folder": "Choose...",
        "stage_files": "Adding files to input",
        "stage_folder": "Adding folder to input",
        "pick_folder": "Pick folder",
        "picker_cancelled": "Selection cancelled.",
        "operation_done": "Operation finished.",
        "operation_failed": "Operation finished with exit code {code}.",
        "field_required": "Fill in: {field}",
        "select_required": "Select at least one item: {field}",
        "theme": "Theme",
        "theme_saved": "Theme saved. Reloading UI.",
        "lang_switch": "RU",
    },
}

PICKER_BOOTSTRAP = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class AudionDpiAwareness {
  [DllImport("user32.dll")]
  public static extern bool SetProcessDpiAwarenessContext(IntPtr dpiContext);
  [DllImport("shcore.dll")]
  public static extern int SetProcessDpiAwareness(int value);
}
"@
  try { [AudionDpiAwareness]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null }
  catch { [AudionDpiAwareness]::SetProcessDpiAwareness(2) | Out-Null }
} catch {}
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
"""

parallel_settings = load_parallel_settings()

state: dict[str, Any] = {
    "running": False,
    "cancel": False,
    "progress": 0.0,
    "status": "",
    "lines": [],
    "line_serial": 0,
    "terminal_reset_id": 0,
    "terminal_scroll_top_seq": 0,
    "log_version": 0,
    "exit_code": None,
    "command_path": [],
    "pending_command": None,
    "field_values": {},
    "source_path": str(getattr(settings, "source_path", "") or ""),
    "destination_path": str(getattr(settings, "destination_path", "") or ""),
    "parallel_enabled": bool(parallel_settings.get("parallel_enabled", DEFAULT_PARALLEL_ENABLED)),
    "worker_count": normalize_worker_count(parallel_settings.get("worker_count", DEFAULT_WORKER_COUNT)),
}


def tr(key: str, **kwargs: Any) -> str:
    lang = settings.language if settings.language in LABELS else "en"
    text = LABELS.get(lang, LABELS["en"]).get(key, key)
    return text.format(**kwargs) if kwargs else text


SECTION_ICONS = {
    "workspace": "folder",
    "operations": "explore",
    "maintenance": "home_repair_service",
    "status": "radio_button_checked",
    "log": "terminal",
    "folder_paths": "folder_open",
    "parameters": "tune",
    "actions": "play_arrow",
}


COMMAND_ICONS = {
    "convert": "sync_alt",
    "photo_sheet": "photo_library",
    "color": "palette",
    "crop": "crop",
    "size": "straighten",
    "pdf": "picture_as_pdf",
    "sheets_and_marks": "label",
    "diagnostics": "health_and_safety",
    "quick_jpg_75": "bolt",
    "quick_png": "bolt",
    "quick_gray_png": "bolt",
    "quick_2160_jpg": "bolt",
    "quick_169_jpg": "bolt",
    "paper_saver": "photo_library",
    "cut_lines": "crop",
    "convert_images": "sync_alt",
    "normalize_profile": "tune",
    "trim_border": "crop_free",
    "smart_crop_white": "center_focus_strong",
    "split_half": "vertical_split",
    "resize_screen": "desktop_windows",
    "aspect_fit": "aspect_ratio",
    "downscale_percent": "compress",
    "plotter_size": "architecture",
    "plotter_dpi_only": "explore",
    "pdf_export": "picture_as_pdf",
    "pdf_extract": "image_search",
    "images_to_pdf": "collections_bookmark",
    "contact_sheet": "grid_view",
    "split_tiff": "view_column",
    "watermark": "branding_watermark",
    "formats": "fact_check",
    "info": "info",
    "cleanup_input_output": "warning",
    "doctor": "health_and_safety",
}

ROOT_COMMAND_ORDER = (
    "convert",
    "pdf",
    "crop",
    "size",
    "color",
    "photo_sheet",
    "sheets_and_marks",
    "contact_sheet",
    "diagnostics",
)

QUICK_RUN_COMMAND_IDS = {
    "formats",
    "info",
    "quick_jpg_75",
    "quick_png",
    "quick_gray_png",
    "quick_2160_jpg",
    "quick_169_jpg",
}

ROOT_QUICK_COMMAND_IDS = (
    "quick_jpg_75",
    "quick_png",
    "images_to_pdf",
    "pdf_extract",
)

CONVERT_QUICK_COMMAND_IDS = (
    "quick_jpg_75",
    "quick_png",
    "quick_gray_png",
    "quick_2160_jpg",
    "quick_169_jpg",
)

CONVERT_MAIN_COMMAND_ID = "convert_images"

DEFAULT_CHILD_COMMAND_IDS = {
    "photo_sheet": "paper_saver",
    "color": "normalize_profile",
    "pdf": "images_to_pdf",
    "crop": "trim_border",
    "size": "downscale_percent",
    "sheets_and_marks": "tile_sheet",
}


def material_icons_enabled() -> bool:
    return bool(getattr(settings, "emoji", False))


def section_icon(key: str) -> str | None:
    if not material_icons_enabled():
        return None
    return SECTION_ICONS.get(key)


def command_icon(command_id: str, kind: str = "safe") -> str | None:
    if not material_icons_enabled():
        return None
    if kind == "dangerous":
        return "warning"
    return COMMAND_ICONS.get(command_id)


def icon_kwargs(icon: str | None) -> dict[str, str]:
    return {"icon": icon} if icon else {}


def tooltip_text(*parts: Any) -> str:
    result: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in result:
            result.append(text)
    return "\n".join(result)


def add_tooltip(element: Any, *parts: Any) -> Any:
    text = tooltip_text(*parts)
    if text:
        from nicegui.elements.tooltip import Tooltip

        tooltip = Tooltip(text)
        tooltip.props["target"] = f"#{element.html_id}"
        tooltip.classes("audion-tooltip")
    return element


def section_heading(icon_key: str, label: str, label_classes: str) -> None:
    icon = section_icon(icon_key)
    with ui.row().classes("audion-icon-label items-center gap-1"):
        if icon:
            ui.icon(icon).classes("audion-label-icon")
        add_tooltip(ui.label(label).classes(label_classes), label)


def operation_title(operation: Operation) -> str:
    return operation.display_title(settings.language)


def node_title(node: CommandNode) -> str:
    return node.display_title(settings.language)


def app_title() -> str:
    title = str(ui_info.get("title") or tool_info.get("name") or "Audion GUI Tool")
    return title[:-3] if title.endswith(" UI") else title


def normalize_theme_id(theme_id: Any) -> str:
    text = str(theme_id or DEFAULT_THEME_ID).strip().lower()
    cleaned = "".join(char for char in text if char.isalnum() or char in {"_", "-"})
    return THEME_ALIASES.get(cleaned, cleaned or DEFAULT_THEME_ID)


def active_theme() -> str:
    theme_id = normalize_theme_id(settings.theme)
    themes = ui_colors["themes"]
    if theme_id in themes:
        return theme_id
    return DEFAULT_THEME_ID if DEFAULT_THEME_ID in themes else next(iter(themes))


def active_theme_data() -> dict[str, Any]:
    return dict(ui_colors["themes"][active_theme()])


def active_theme_mode() -> str:
    return str(active_theme_data().get("mode", "dark"))


def theme_label(theme_id: str) -> str:
    theme_data = ui_colors["themes"].get(theme_id, {})
    label_key = "label_ru" if settings.language == "ru" else "label"
    return str(theme_data.get(label_key) or theme_data.get("label") or theme_id)


def theme_options() -> dict[str, str]:
    return {theme_id: theme_label(theme_id) for theme_id in ui_colors["themes"]}


def set_theme(theme_id: Any) -> None:
    selected = normalize_theme_id(theme_id)
    if selected not in ui_colors["themes"]:
        return
    settings.theme = selected
    save_app_settings()
    safe_notify(tr("theme_saved"), "positive")
    ui.run_javascript("window.location.reload()")


def theme_change_handler(event: Any) -> None:
    set_theme(getattr(event, "value", None))


def theme_variables() -> dict[str, str]:
    variables: dict[str, str] = {}
    for ramp_name, stops in ui_colors["ramps"].items():
        if not isinstance(stops, dict):
            continue
        for stop, color in stops.items():
            variables[f"color-{ramp_name}-{stop}"] = str(color).strip()
    variables.update(ui_colors["tokens"])
    variables.update(_string_map(active_theme_data().get("tokens", {})))
    variables.setdefault("color-background-primary", "#141413")
    variables.setdefault("color-background-secondary", "#1f1e1a")
    variables.setdefault("color-background-tertiary", "#0f0f0e")
    variables.setdefault("color-text-primary", "#faf9f5")
    variables.setdefault("color-text-secondary", "#e8e6dc")
    variables.setdefault("color-text-tertiary", "#b0aea5")
    variables.setdefault("color-border-tertiary", "rgba(250, 249, 245, 0.15)")
    variables.setdefault("color-border-secondary", "rgba(250, 249, 245, 0.3)")
    variables.setdefault("color-border-primary", "rgba(250, 249, 245, 0.4)")
    variables.setdefault("color-accent-primary", "#6a9bcc")
    variables.setdefault("font-sans", "Inter, Segoe UI, Arial, sans-serif")
    variables.setdefault("font-mono", "Cascadia Mono, Consolas, monospace")
    variables.setdefault("border-radius-md", "8px")
    variables.setdefault("border-radius-lg", "12px")
    return variables


def add_log(message: str) -> None:
    if not str(message).strip():
        return
    state["lines"].append(str(message).rstrip())
    state["lines"] = state["lines"][-TERMINAL_HISTORY_LIMIT:]
    state["line_serial"] = int(state.get("line_serial", 0)) + 1
    state["log_version"] = int(state["log_version"]) + 1


def clear_terminal_log() -> None:
    state["lines"] = []
    state["line_serial"] = 0
    state["terminal_reset_id"] = int(state.get("terminal_reset_id", 0)) + 1
    state["terminal_scroll_top_seq"] = 0
    state["log_version"] = int(state["log_version"]) + 1


PATH_HISTORY_LIMIT = 100


def current_source_path() -> Path:
    return Path(str(state.get("source_path") or getattr(settings, "source_path", "") or paths.input)).expanduser()


def current_target_path() -> Path:
    return Path(str(state.get("destination_path") or getattr(settings, "destination_path", "") or paths.output)).expanduser()


def active_project_paths():
    return replace(paths, input=current_source_path(), output=current_target_path())


def save_workspace_path(kind: str, value: Any) -> None:
    text = str(value or "").strip()
    if kind == "source":
        settings.source_path = text
        state["source_path"] = text
    elif kind == "destination":
        settings.destination_path = text
        state["destination_path"] = text
    else:
        raise RuntimeError(f"Unknown workspace path kind: {kind}")
    save_app_settings()


def reload_ui(delay_ms: int = 0) -> None:
    script = f"window.setTimeout(() => window.location.reload(), {max(0, int(delay_ms))})"
    delivered = False
    for client in list(nicegui_app.clients()):
        if getattr(client, "_deleted", False) or not client.has_socket_connection:
            continue
        client.run_javascript(script)
        delivered = True
    if not delivered:
        ui.run_javascript(script)


def terminal_shell_html(element_id: str) -> str:
    return f'<pre id="{element_id}" class="audion-terminal-content"></pre>'


def progress_text() -> str:
    return f"{round(max(0.0, min(1.0, float(state['progress']))) * 100):.0f}%"


def result_warning_message(data: dict[str, Any]) -> str:
    if data.get("warning_code") == "dpi_auto_adjusted":
        requested = data.get("requested_dpi", "")
        auto_dpi = data.get("dpi", data.get("auto_dpi", ""))
        required = data.get("required_dpi", auto_dpi)
        width = data.get("width_mm", data.get("page_width_mm", ""))
        if settings.language == "ru":
            return (
                f"DPI листа {requested:g} недостаточен для исходных пикселей при ширине {width:g} мм. "
                f"Автоматически поставлено {auto_dpi:g} DPI; требуется минимум {required:g} DPI."
            )
        return (
            f"Sheet DPI {requested:g} is too low for unchanged source pixels at {width:g} mm. "
            f"Automatically set to {auto_dpi:g} DPI; required minimum is {required:g} DPI."
        )
    if data.get("warning_code") == "page_width_auto_adjusted":
        requested = data.get("requested_width_mm", data.get("requested_page_width_mm", ""))
        auto_width = data.get("width_mm", data.get("auto_page_width_mm", ""))
        required = data.get("required_page_width_mm", "")
        if settings.language == "ru":
            return (
                f"Ширина листа {requested:g} мм меньше нужной. "
                f"Автоматически поставлено {auto_width:g} мм; требуется более {required:.3f} мм."
            )
        return (
            f"Sheet width {requested:g} mm was too small. "
            f"Automatically set to {auto_width:g} mm; required width is more than {required:.3f} mm."
        )
    return str(data.get("warning_message") or "")


def safe_notify(message: str, kind: str = "info", **notify_kwargs: Any) -> None:
    notify_type = str(notify_kwargs.pop("type", kind))
    options = {"message": str(message), "type": notify_type, **notify_kwargs}
    delivered = False
    for client in list(nicegui_app.clients()):
        if getattr(client, "_deleted", False) or not client.has_socket_connection:
            continue
        try:
            client.outbox.enqueue_message("notify", options, client.id)
            delivered = True
        except Exception as exc:
            logging.warning("NiceGUI notification delivery failed for client %s: %s", getattr(client, "id", "?"), exc)
    if delivered:
        return

    try:
        ui.notify(message, type=notify_type, **notify_kwargs)
    except RuntimeError as exc:
        message_text = str(exc)
        if "slot belongs to has been deleted" not in message_text and "current slot cannot be determined" not in message_text:
            raise
        logging.warning("NiceGUI notification skipped because no live client slot was available: %s", message)


RUN_STATE_LABELS = {
    "idle": ("idle", "audion-status-idle"),
    "running": ("running", "audion-status-running"),
    "done": ("done", "audion-status-done"),
    "error": ("error", "audion-status-error"),
}


def run_state() -> str:
    """Which of the four states the panel is showing.

    Colour carries this everywhere it appears, so it is decided once.
    """
    if bool(state["running"]):
        return "running"
    exit_code = state.get("exit_code")
    if exit_code is None:
        return "idle"
    return "done" if int(exit_code or 0) == 0 else "error"


def status_row_classes() -> str:
    return f"audion-status-row {RUN_STATE_LABELS[run_state()][1]}"


def status_state_text() -> str:
    return tr(RUN_STATE_LABELS[run_state()][0]).upper()


def elapsed_text(seconds: float | None) -> str:
    """A run's own clock, mm:ss, or an em dash before anything has run.

    The start is noticed by the refresh timer rather than written by the code that
    starts a run: there are several such places, and none of them has to know
    about the panel.
    """
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def status_dot_classes() -> str:
    base = "audion-status-dot text-lg leading-none"
    if bool(state["running"]):
        return f"{base} text-sky-400 animate-pulse"
    if state.get("exit_code") is None:
        return f"{base} text-gray-500"
    if int(state.get("exit_code") or 0) == 0:
        return f"{base} text-green-400"
    return f"{base} text-red-400"


def set_progress(value: float) -> None:
    state["progress"] = max(0.0, min(1.0, float(value)))


def cancel_requested() -> bool:
    return bool(state["cancel"])


def hidden_subprocess_flags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def hidden_subprocess_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def resolve_dialog_powershell() -> list[str]:
    candidates = [
        [str(paths.system_core / "powershell" / "pwsh.exe"), "-NoLogo", "-NoProfile", "-STA", "-Command"],
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-STA", "-Command"],
        ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command"],
    ]
    for candidate in candidates:
        exe = candidate[0]
        if Path(exe).exists() or shutil.which(exe):
            return candidate
    raise RuntimeError("PowerShell was not found for Windows picker.")


_PICKER_RUN_LOCK = threading.Lock()
_PICKER_JOB_LOCK = threading.Lock()
_PICKER_JOB_HANDLE: int | None = None


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def close_picker_job() -> None:
    global _PICKER_JOB_HANDLE
    with _PICKER_JOB_LOCK:
        handle = _PICKER_JOB_HANDLE
        _PICKER_JOB_HANDLE = None
    if os.name == "nt" and handle:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(wintypes.HANDLE(handle))


def _picker_job_handle() -> int | None:
    global _PICKER_JOB_HANDLE
    if os.name != "nt":
        return None
    with _PICKER_JOB_LOCK:
        if _PICKER_JOB_HANDLE:
            return _PICKER_JOB_HANDLE
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            logging.warning("Could not create the Windows picker job: %s", ctypes.get_last_error())
            return None
        info = _JobObjectExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            wintypes.HANDLE(job),
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not configured:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(wintypes.HANDLE(job))
            logging.warning("Could not configure the Windows picker job: %s", error)
            return None
        _PICKER_JOB_HANDLE = int(job)
        return _PICKER_JOB_HANDLE


def _assign_picker_to_job(process: subprocess.Popen[str]) -> None:
    handle = _picker_job_handle()
    if os.name != "nt" or not handle:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    assigned = kernel32.AssignProcessToJobObject(
        wintypes.HANDLE(handle),
        wintypes.HANDLE(int(process._handle)),  # type: ignore[attr-defined]
    )
    if not assigned:
        logging.warning("Could not attach picker PID %s to its Windows job: %s", process.pid, ctypes.get_last_error())


def run_picker_script(script: str, failure_message: str) -> str:
    if not _PICKER_RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("A Windows picker is already open.")
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [*resolve_dialog_powershell(), script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=hidden_subprocess_flags(),
            startupinfo=hidden_subprocess_startupinfo(),
        )
        _assign_picker_to_job(process)
        try:
            stdout, stderr = process.communicate(timeout=3600)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise RuntimeError("Windows picker timed out.") from exc
        if process.returncode != 0:
            raise RuntimeError(stderr.strip() or failure_message)
        return stdout
    finally:
        if process is not None and process.poll() is None:
            process.kill()
        _PICKER_RUN_LOCK.release()


atexit.register(close_picker_job)
nicegui_app.on_shutdown(close_picker_job)


def parse_picker_paths(text: str) -> list[Path]:
    import json

    payload = text.strip()
    if not payload:
        return []
    data = json.loads(payload)
    if isinstance(data, str):
        data = [data]
    return [Path(str(item)).resolve() for item in data if str(item).strip()]


def pick_files() -> list[Path]:
    script = PICKER_BOOTSTRAP + r"""
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Add files to input'
$dialog.Multiselect = $true
$dialog.Filter = 'All supported files|*.*|All files|*.*'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  $dialog.FileNames | ConvertTo-Json -Compress
}
"""
    return parse_picker_paths(run_picker_script(script, "File picker failed."))


def pick_single_file() -> list[Path]:
    script = PICKER_BOOTSTRAP + r"""
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Choose one source file'
$dialog.Multiselect = $false
$dialog.Filter = 'All supported files|*.*|All files|*.*'
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  $dialog.FileName | ConvertTo-Json -Compress
}
"""
    return parse_picker_paths(run_picker_script(script, "File picker failed."))


def pick_folder(description: str = "Add folder to input", show_new_folder_button: bool = False) -> list[Path]:
    dialog_description = str(description).replace("'", "''")
    show_new_folder_button_value = "$true" if show_new_folder_button else "$false"
    script = PICKER_BOOTSTRAP + f"""
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '{dialog_description}'
$dialog.ShowNewFolderButton = {show_new_folder_button_value}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  @($dialog.SelectedPath) | ConvertTo-Json -Compress
}}
"""
    return parse_picker_paths(run_picker_script(script, "Folder picker failed."))


def folder_field_click_handler(key: str, label: str, control: Any, show_new_folder_button: bool = False):
    async def handler() -> None:
        try:
            selected = await run.io_bound(pick_folder, label or tr("pick_folder"), show_new_folder_button)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")
            return
        if not selected:
            add_log(tr("picker_cancelled"))
            return
        value = str(selected[0])
        set_field_value(key, value)
        control.value = value

    return handler


def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate a unique target name for {path.name}")


def absolute_project_path(path_value: Any) -> Path:
    path = Path(str(path_value or "")).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def remove_path_tree(path: Path) -> int:
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(path))
    if path.is_symlink() or is_junction:
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
        return 1
    if path.is_file():
        path.unlink()
        return 1
    if path.is_dir():
        shutil.rmtree(path)
        return 1
    return 0


def clear_directory_contents(folder: Path) -> int:
    removed = 0
    if not folder.exists():
        return removed
    for child in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        # .gitkeep is not spared: input and output must be genuinely empty after
        # a clear, so nobody has to wonder what the leftover file is or whether it
        # is safe to delete. The folders come from install/init_folders.cmd.
        removed += remove_path_tree(child)
    return removed


def normalized_absolute_path(path_value: Any) -> Path:
    return absolute_project_path(path_value).resolve(strict=False)


def paths_equal(left: Any, right: Any) -> bool:
    return os.path.normcase(str(normalized_absolute_path(left))) == os.path.normcase(str(normalized_absolute_path(right)))


def validate_workspace_delete_target(path_value: Any) -> Path:
    target = normalized_absolute_path(path_value)
    if target.parent == target:
        raise RuntimeError(f"Refusing to delete a filesystem root: {target}")
    if paths_equal(target, ROOT):
        raise RuntimeError(f"Refusing to delete the project root: {target}")
    return target


def delete_workspace_path_contents(path_value: Any) -> dict[str, Any]:
    target = validate_workspace_delete_target(path_value)
    if not target.exists() and not target.is_symlink():
        return {"path": str(target), "kind": "missing", "removed": 0}
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(target))
    if target.is_file() or target.is_symlink() or is_junction:
        removed = remove_path_tree(target)
        return {"path": str(target), "kind": "file", "removed": removed}
    if not target.is_dir():
        raise RuntimeError(f"Unsupported workspace path: {target}")
    removed = clear_directory_contents(target)
    return {"path": str(target), "kind": "folder", "removed": removed}


def delete_workspace_io_contents(source: Path, target: Path) -> dict[str, Any]:
    source_result = delete_workspace_path_contents(source)
    if paths_equal(source, target):
        target_result = {"path": str(normalized_absolute_path(target)), "kind": "same", "removed": 0}
    else:
        target_result = delete_workspace_path_contents(target)
    return {"source": source_result, "target": target_result}


def copy_path_overwrite(source: Path, target: Path) -> int:
    if target.exists() or target.is_symlink():
        remove_path_tree(target)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, target)
        return 1
    if source.is_file() or source.is_symlink():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return 1
    raise RuntimeError(f"Unsupported source path: {source}")


def copy_output_to_input_and_clear() -> dict[str, Any]:
    input_folder = absolute_project_path(current_source_path())
    output_path = absolute_project_path(current_target_path())
    input_folder.mkdir(parents=True, exist_ok=True)

    input_resolved = input_folder.resolve(strict=False)
    output_resolved = output_path.resolve(strict=False)
    if input_resolved == output_resolved:
        raise RuntimeError(tr("copy_output_to_input_same_path"))
    if input_resolved.is_relative_to(output_resolved):
        raise RuntimeError(tr("copy_output_to_input_nested_input"))

    if not output_path.exists():
        return {"copied": 0, "removed": 0, "input": str(input_folder), "output": str(output_path)}

    copied = 0
    if output_path.is_file() or output_path.is_symlink():
        target = input_folder / output_path.name
        target_resolved = target.resolve(strict=False)
        if target_resolved == output_resolved or target_resolved.is_relative_to(output_resolved):
            raise RuntimeError(f"Unsafe copy target inside Output: {target}")
        copied += copy_path_overwrite(output_path, target)
        removed = remove_path_tree(output_path)
        return {"copied": copied, "removed": removed, "input": str(input_folder), "output": str(output_path)}

    if not output_path.is_dir():
        raise RuntimeError(f"Output is not a file or folder: {output_path}")

    items = sorted(output_path.iterdir(), key=lambda item: item.name.casefold())
    if not items:
        return {"copied": 0, "removed": 0, "input": str(input_folder), "output": str(output_path)}

    for item in items:
        target = input_folder / item.name
        target_resolved = target.resolve(strict=False)
        if target_resolved == output_resolved or target_resolved.is_relative_to(output_resolved):
            raise RuntimeError(f"Unsafe copy target inside Output: {target}")
        copied += copy_path_overwrite(item, target)

    removed = clear_directory_contents(output_path)
    return {"copied": copied, "removed": removed, "input": str(input_folder), "output": str(output_path)}


def copy_item_to_input(source: Path) -> Path:
    input_folder = current_source_path()
    input_folder.mkdir(parents=True, exist_ok=True)
    input_resolved = input_folder.resolve()
    source_resolved = source.resolve()

    if source_resolved == input_resolved:
        raise RuntimeError("Cannot import the input folder into itself.")
    if input_resolved.is_relative_to(source_resolved):
        raise RuntimeError(f"Cannot import a parent folder of input: {source}")
    if source_resolved.is_relative_to(input_resolved):
        add_log(f"SKIP already in input -> {source}")
        return source

    target = unique_target(input_folder / source.name)
    if source.is_dir():
        shutil.copytree(source, target)
        return target
    if source.is_file():
        shutil.copy2(source, target)
        return target
    raise RuntimeError(f"Unsupported source path: {source}")


def import_to_input(kind: str) -> int:
    sources = pick_files() if kind == "files" else pick_folder()
    if not sources:
        add_log(tr("picker_cancelled"))
        return 0

    total = len(sources)
    for index, source in enumerate(sources, start=1):
        if cancel_requested():
            add_log("Cancellation requested.")
            return 2
        target = copy_item_to_input(source)
        add_log(f"[{index}/{total}] COPIED -> {target}")
        set_progress(index / max(1, total))
    return 0


def input_file_list_lines(source: Path) -> list[str]:
    if not source.exists():
        return [tr("file_list_missing", path=source)]
    if source.is_file():
        names = [source.name]
    elif source.is_dir():
        names = sorted(
            (path.name for path in source.rglob("*") if path.is_file()),
            key=lambda item: item.casefold(),
        )
    else:
        return [f"Unsupported INPUT path: {source}"]
    if not names:
        return [tr("file_list_empty")]

    number_width = max(3, len(str(len(names))))
    lines = [
        f"{'No.':>{number_width}}  List",
        f"{'-' * number_width}  ----",
    ]
    lines.extend(f"{index:0{number_width}d}. {name}" for index, name in enumerate(names, start=1))
    return lines


async def show_input_file_list() -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    state.update(
        {
            "running": True,
            "cancel": False,
            "progress": 0.02,
            "status": f"{tr('running')}: {tr('file_list')}",
            "lines": [],
            "line_serial": 0,
            "terminal_reset_id": int(state.get("terminal_reset_id", 0)) + 1,
            "log_version": int(state["log_version"]) + 1,
            "exit_code": None,
        }
    )
    try:
        lines = await run.io_bound(input_file_list_lines, current_source_path())
        for line in lines:
            add_log(line)
        count = max(0, len(lines) - 2)
        state["terminal_scroll_top_seq"] = int(state.get("line_serial", 0))
        state["exit_code"] = 0
        state["progress"] = 1.0
        state["status"] = f"{tr('done')}: {tr('file_list')} [{count}]"
        safe_notify(tr("file_list_ready", count=count), "positive")
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {exc}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False


async def copy_output_to_input_click_handler() -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    input_path = absolute_project_path(current_source_path())
    output_path = absolute_project_path(current_target_path())
    with ui.dialog() as dialog, ui.card().classes("rounded-lg"):
        add_tooltip(ui.label(tr("confirm_title")).classes("text-base font-semibold"), tr("confirm_title"))
        ui.label(tr("copy_output_to_input_confirm")).classes("text-sm text-gray-300")
        ui.label(f"Input: {input_path}").classes("max-w-3xl break-all font-mono text-xs text-gray-400")
        ui.label(f"Output: {output_path}").classes("max-w-3xl break-all font-mono text-xs text-gray-400")
        with ui.row().classes("gap-2"):
            add_tooltip(ui.button(tr("cancel"), on_click=dialog.close).props("dense flat"), tr("cancel"))
            add_tooltip(ui.button(
                tr("copy_output_to_input"),
                icon="drive_file_move",
                on_click=lambda: dialog.submit(True),
            ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button rounded-lg"), tr("copy_output_to_input"), tr("copy_output_to_input_tooltip"))
    confirmed = await dialog
    if not confirmed:
        return

    state.update(
        {
            "running": True,
            "cancel": False,
            "progress": 0.02,
            "status": f"{tr('running')}: {tr('copy_output_to_input')}",
            "lines": [],
            "line_serial": 0,
            "terminal_reset_id": int(state.get("terminal_reset_id", 0)) + 1,
            "log_version": int(state["log_version"]) + 1,
            "exit_code": None,
        }
    )
    started = time.perf_counter()
    try:
        result = await run.io_bound(copy_output_to_input_and_clear)
        copied = int(result.get("copied", 0))
        removed = int(result.get("removed", 0))
        elapsed = time.perf_counter() - started
        add_log("[OUTPUT -> INPUT]")
        add_log(f"Input : {result.get('input')}")
        add_log(f"Output: {result.get('output')}")
        add_log(f"Copied top-level item(s): {copied}")
        add_log(f"Cleared output item(s): {removed}")
        state["exit_code"] = 0
        state["progress"] = 1.0
        state["status"] = f"{tr('done')}: {tr('copy_output_to_input')} [{copied}] {elapsed:.1f}s"
        if copied <= 0:
            safe_notify(tr("copy_output_to_input_empty"), "warning")
        else:
            safe_notify(tr("copy_output_to_input_done", copied=copied, removed=removed), "positive")
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {exc}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False


async def start_import(kind: str) -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    title = tr("stage_files") if kind == "files" else tr("stage_folder")
    state.update(
        {
            "running": True,
            "cancel": False,
            "progress": 0.02,
            "status": f"{tr('running')}: {title}",
            "lines": [],
            "line_serial": 0,
            "log_version": int(state["log_version"]) + 1,
            "exit_code": None,
        }
    )
    try:
        exit_code = await run.io_bound(import_to_input, kind)
        state["exit_code"] = exit_code
        state["progress"] = 1.0
        state["status"] = f"{tr('done')}: {title} [{exit_code}]"
        safe_notify(tr("operation_done") if exit_code == 0 else tr("operation_failed", code=exit_code), "positive" if exit_code == 0 else "negative")
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {exc}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False


async def start_operation(operation: Operation) -> None:
    if state["running"]:
        safe_notify(tr("another_running"), "warning")
        return

    if operation.kind == "dangerous":
        with ui.dialog() as dialog, ui.card().classes("rounded-lg"):
            add_tooltip(ui.label(tr("confirm_title")).classes("text-base font-semibold"), tr("confirm_title"))
            ui.label(operation.display_description(settings.language)).classes("text-sm text-gray-400")
            ui.label(tr("confirm_note")).classes("text-xs text-gray-500")
            with ui.row().classes("gap-2"):
                add_tooltip(ui.button(tr("cancel"), on_click=dialog.close).props("dense flat"), tr("cancel"))
                add_tooltip(ui.button(tr("run"), on_click=lambda: dialog.submit(True)).props("dense color=negative"), tr("run"), operation_title(operation))
        confirmed = await dialog
        if not confirmed:
            return

    state.update(
        {
            "running": True,
            "cancel": False,
            "progress": 0.02,
            "status": f"{tr('running')}: {operation_title(operation)}",
            "lines": [],
            "line_serial": 0,
            "log_version": int(state["log_version"]) + 1,
            "exit_code": None,
        }
    )
    started = time.perf_counter()
    try:
        result = await run.io_bound(
            execute_operation,
            active_project_paths(),
            operation,
            add_log,
            set_progress,
            cancel_requested,
        )
        elapsed = time.perf_counter() - started
        state["exit_code"] = 0 if result.ok else 1
        state["progress"] = 1.0
        state["status"] = f"{tr('done') if result.ok else tr('error')}: {operation_title(operation)} [{state['exit_code']}] {elapsed:.1f}s"
        warning_message = result_warning_message(result.data) if isinstance(result.data, dict) else ""
        safe_notify(
            str(warning_message or result.message),
            "warning" if result.ok and warning_message else ("positive" if result.ok else "negative"),
        )
    except Exception as exc:
        state["exit_code"] = 1
        state["progress"] = max(float(state["progress"]), 0.98)
        state["status"] = f"{tr('error')}: {exc}"
        add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        safe_notify(str(exc), "negative")
    finally:
        state["running"] = False


def toggle_language() -> None:
    settings.language = "en" if settings.language == "ru" else "ru"
    save_app_settings()
    ui.run_javascript("window.location.reload()")


def folder_button(label: str, folder: Path) -> None:
    with ui.row().classes("w-full items-center gap-3"):
        add_tooltip(ui.button(label, on_click=lambda item=folder: open_folder(item)).props("dense flat no-wrap").classes("audion-action w-20 rounded-lg"), label, folder)
        ui.label(str(folder)).classes("min-w-0 flex-1 truncate font-mono text-xs text-gray-300")


def open_workspace_folder(role: str) -> None:
    folder = current_target_path() if role == "target" else current_source_path()
    if role != "target" and not folder.exists():
        raise FileNotFoundError(tr("source_folder_missing", path=folder))
    if folder.is_file():
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", f"/select,{folder}"])
        else:
            open_folder(folder.parent)
        return
    open_folder(folder)


def mark_workspace_feedback(role: str, action: str) -> None:
    role_key = canonical_role(role)
    state["workspace_feedback"] = {"role": role_key, "action": str(action or "path")}


def _save_workspace_adapter_path(role: WorkbenchRole, value: Any) -> None:
    save_workspace_path("destination" if role == "target" else "source", value)


def _workspace_feedback() -> dict[str, str]:
    value = state.get("workspace_feedback")
    return dict(value) if isinstance(value, dict) else {}


def _clear_workspace_feedback() -> None:
    state["workspace_feedback"] = {}


WORKBENCH_CONFIG = WorkbenchConfig(
    root=ROOT,
    input_path=paths.input,
    output_path=paths.output,
    history_path=_workspace_history_file(),
    history_limit=PATH_HISTORY_LIMIT,
)
WORKBENCH_ADAPTER = WorkbenchAdapter(
    config=WORKBENCH_CONFIG,
    current_path_callback=lambda role: current_target_path() if role == "target" else current_source_path(),
    save_path_callback=_save_workspace_adapter_path,
    language_callback=lambda: settings.language,
    translate_callback=tr,
    log_callback=add_log,
    notify_callback=safe_notify,
    reload_callback=reload_ui,
    busy_callback=lambda: bool(state.get("running")),
    feedback_callback=_workspace_feedback,
    set_feedback_callback=mark_workspace_feedback,
    clear_feedback_callback=_clear_workspace_feedback,
)
WORKBENCH_ADAPTER.validate()
WORKBENCH_ADAPTER.ensure_initial_history()


def workspace_pin_click_handler(role: str, pinned: bool):
    async def handler() -> None:
        path_value = str(current_target_path() if role == "target" else current_source_path())
        if not path_value:
            safe_notify(tr("path_required"), "warning")
            return
        try:
            await run.io_bound(WORKBENCH_ADAPTER.set_path_pinned, role, path_value, pinned)
            mark_workspace_feedback(role, "pin" if pinned else "unpin")
            add_log(f"{'Pinned' if pinned else 'Unpinned'} {role} path: {path_value}")
            reload_ui(150)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def workspace_delete_path_click_handler(role: str):
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        path = current_target_path() if role == "target" else current_source_path()
        path_value = str(path)
        if not path_value:
            safe_notify(tr("path_required"), "warning")
            return
        external_source = role != "target" and not paths_equal(path, paths.input)
        if external_source:
            is_file = path.is_file()
            with ui.dialog() as dialog, ui.card().classes("audion-dialog rounded-lg"):
                title = "Удалить исходный файл?" if is_file else "Очистить внешний ИСТОЧНИК?"
                if settings.language != "ru":
                    title = "Delete the source file?" if is_file else "Clear the external SOURCE?"
                ui.label(title).classes("text-base font-semibold")
                warning = (
                    "Будет удалён исходный файл. Другой копии может не существовать."
                    if is_file
                    else "Будут безвозвратно удалены все файлы и вложенные папки."
                )
                if settings.language != "ru":
                    warning = (
                        "The source file will be deleted. Another copy may not exist."
                        if is_file
                        else "All files and nested folders will be permanently deleted."
                    )
                ui.label(warning).classes("text-sm text-gray-300")
                ui.label(str(normalized_absolute_path(path))).classes("max-w-3xl break-all font-mono text-xs text-gray-400")
                with ui.row().classes("gap-2"):
                    ui.button(tr("cancel"), on_click=dialog.close).props("dense flat")
                    ui.button(tr("delete_io_short"), on_click=lambda: dialog.submit(True)).props("dense color=negative")
            confirmed = await dialog
            if not confirmed:
                return
        try:
            result = await run.io_bound(delete_workspace_path_contents, path)
            if result.get("kind") == "file":
                await run.io_bound(WORKBENCH_ADAPTER.delete_path_history, role, path_value)
                save_workspace_path("destination" if role == "target" else "source", "")
            mark_workspace_feedback(role, "delete")
            add_log(
                f"Cleared {'TARGET' if role == 'target' else 'SOURCE'}: {result.get('path')} "
                f"[kind={result.get('kind')}, removed={result.get('removed', 0)}]"
            )
            reload_ui(150)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def workspace_single_file_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        try:
            selected = await run.io_bound(pick_single_file)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")
            return
        if not selected:
            add_log(tr("picker_cancelled"))
            return
        path_value = str(selected[0])
        save_workspace_path("source", path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, "source", path_value)
        mark_workspace_feedback("source", "path")
        add_log(f"SOURCE FILE -> {path_value}")
        reload_ui(150)

    return handler


def workspace_open_click_handler(role: str):
    async def handler() -> None:
        try:
            await run.io_bound(open_workspace_folder, role)
            add_log(f"Opened {'target' if role == 'target' else 'source'} folder: {current_target_path() if role == 'target' else current_source_path()}")
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")

    return handler


def reset_workspace_paths_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        result = await run.io_bound(WORKBENCH_ADAPTER.clear_path_history_cache_keep_pins)
        save_workspace_path("source", "")
        save_workspace_path("destination", "")
        add_log(f"Workspace route reset: SOURCE -> {paths.input}")
        add_log(f"Workspace route reset: TARGET -> {paths.output}")
        add_log(
            "Workspace path cache cleared: "
            f"sources={result.get('removed_sources', 0)}, targets={result.get('removed_targets', 0)}, "
            f"pins kept={result.get('kept_pins', 0)}"
        )
        safe_notify(tr("operation_done"), "positive")
        reload_ui()

    return handler


def workspace_path_select_handler(role: str):
    async def handler(event: Any) -> None:
        path_value = str(getattr(event, "value", "") or "").strip()
        if not path_value:
            return
        save_workspace_path("destination" if role == "target" else "source", path_value)
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, role, path_value)
        mark_workspace_feedback(role, "path")
        add_log(f"{'TARGET' if role == 'target' else 'SOURCE'} -> {path_value}")
        reload_ui(150)

    return handler


def workspace_delete_both_click_handler():
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        source = current_source_path()
        target = current_target_path()
        source_external = not paths_equal(source, paths.input)
        with ui.dialog() as dialog, ui.card().classes("audion-dialog rounded-lg"):
            ui.label("Удалить содержимое I/O?" if settings.language == "ru" else "Delete I/O contents?").classes("text-base font-semibold")
            warning = (
                "Будут удалены файлы ИСТОЧНИКА и НАЗНАЧЕНИЯ. Внешний ИСТОЧНИК может быть единственным экземпляром."
                if source_external
                else "Будут удалены файлы ИСТОЧНИКА и НАЗНАЧЕНИЯ."
            )
            if settings.language != "ru":
                warning = (
                    "SOURCE and TARGET files will be deleted. The external SOURCE may be the only copy."
                    if source_external
                    else "SOURCE and TARGET files will be deleted."
                )
            ui.label(warning).classes("text-sm text-gray-300")
            ui.label(f"SOURCE: {normalized_absolute_path(source)}").classes("max-w-3xl break-all font-mono text-xs text-gray-400")
            ui.label(f"TARGET: {normalized_absolute_path(target)}").classes("max-w-3xl break-all font-mono text-xs text-gray-400")
            with ui.row().classes("gap-2"):
                ui.button(tr("cancel"), on_click=dialog.close).props("dense flat")
                ui.button(tr("delete_io_short"), on_click=lambda: dialog.submit(True)).props("dense color=negative")
        confirmed = await dialog
        if not confirmed:
            return
        state["running"] = True
        try:
            result = await run.io_bound(delete_workspace_io_contents, source, target)
            source_result = result.get("source", {})
            target_result = result.get("target", {})
            if source_result.get("kind") == "file":
                await run.io_bound(WORKBENCH_ADAPTER.delete_path_history, "source", str(source))
                save_workspace_path("source", "")
            if target_result.get("kind") == "file":
                await run.io_bound(WORKBENCH_ADAPTER.delete_path_history, "target", str(target))
                save_workspace_path("destination", "")
            add_log(
                f"Cleared SOURCE: {source_result.get('path')} "
                f"[kind={source_result.get('kind')}, removed={source_result.get('removed', 0)}]"
            )
            add_log(
                f"Cleared TARGET: {target_result.get('path')} "
                f"[kind={target_result.get('kind')}, removed={target_result.get('removed', 0)}]"
            )
            mark_workspace_feedback("source", "delete")
            reload_ui(150)
        except Exception as exc:
            add_log(f"ERROR: {exc.__class__.__name__}: {exc}")
            safe_notify(str(exc), "negative")
        finally:
            state["running"] = False

    return handler


def workspace_pick_click_handler(role: str):
    async def handler() -> None:
        if state["running"]:
            safe_notify(tr("another_running"), "warning")
            return
        try:
            selected = await run.io_bound(pick_folder)
        except Exception as exc:
            safe_notify(str(exc), "negative")
            return
        if not selected:
            add_log(tr("picker_cancelled"))
            return
        save_workspace_path("destination" if role == "target" else "source", str(selected[0]))
        await run.io_bound(WORKBENCH_ADAPTER.remember_path, role, str(selected[0]))
        mark_workspace_feedback(role, "path")
        add_log(f"{'TARGET' if role == 'target' else 'SOURCE'} -> {selected[0]}")
        reload_ui(150)

    return handler


WORKBENCH_RENDERER = WorkbenchRenderer(
    adapter=WORKBENCH_ADAPTER,
    handlers=WorkbenchHandlers(
        delete_path=workspace_delete_path_click_handler,
        pin_path=workspace_pin_click_handler,
        select_path=workspace_path_select_handler,
        pick_path=workspace_pick_click_handler,
        open_path=workspace_open_click_handler,
        add_file=workspace_single_file_click_handler,
        reset_paths=reset_workspace_paths_click_handler,
        delete_io=workspace_delete_both_click_handler,
        list_files=show_input_file_list,
    ),
    display_path_callback=display_path,
)


def operation_button(operation: Operation) -> None:
    with ui.element("div").classes("audion-operation-row"):
        add_tooltip(ui.button(
            operation_title(operation),
            **icon_kwargs(command_icon(operation.id, operation.kind)),
            on_click=operation_click_handler(operation),
        ).props("dense flat no-wrap").classes("audion-action audion-operation-button rounded-lg"), operation_title(operation), operation.display_description(settings.language))


def operation_click_handler(operation: Operation):
    async def handler() -> None:
        await start_operation(operation)

    return handler


def import_click_handler(kind: str):
    async def handler() -> None:
        await start_import(kind)

    return handler


def operation_to_command_node(operation: Operation) -> CommandNode:
    return CommandNode(
        id=operation.id,
        title=operation.title,
        description=operation.description,
        service=operation.service,
        kind=operation.kind,
        title_ru=operation.title_ru,
        description_ru=operation.description_ru,
        parameters=dict(operation.parameters),
        fields=operation.fields,
    )


def root_command_nodes() -> list[CommandNode]:
    if manifest.operation_groups:
        order = {command_id: index for index, command_id in enumerate(ROOT_COMMAND_ORDER)}
        return sorted(manifest.operation_groups, key=lambda node: (order.get(node.id, len(order)), node.id))
    return [operation_to_command_node(operation) for operation in manifest.operations]


def current_command_level() -> tuple[list[CommandNode], list[CommandNode]]:
    level = command_level_for_path(list(state.get("command_path", [])))
    if level is None:
        state["command_path"] = []
        state["pending_command"] = None
        return [], root_command_nodes()
    return level


def command_level_for_path(command_path: list[str]) -> tuple[list[CommandNode], list[CommandNode]] | None:
    trail: list[CommandNode] = []
    nodes = root_command_nodes()
    for node_id in command_path:
        node = next((candidate for candidate in nodes if candidate.id == node_id), None)
        if node is None:
            return None
        trail.append(node)
        nodes = list(node.children)
    return trail, nodes


def compact_single_child_command_path(command_path: list[str]) -> list[str]:
    compacted = list(command_path)
    while compacted:
        level = command_level_for_path(compacted)
        if level is None:
            return []
        _trail, nodes = level
        if len(nodes) != 1:
            break
        compacted.pop()
    return compacted


def enter_command_path(command_path: list[str]) -> None:
    state["pending_command"] = None
    state["command_path"] = command_path
    command_tree.refresh()


def enter_command_node(node: CommandNode) -> None:
    enter_command_path([*state.get("command_path", []), node.id])


def select_command_node(node: CommandNode) -> None:
    state["pending_command"] = node
    command_tree.refresh()


def main_convert_child(node: CommandNode) -> CommandNode | None:
    if node.id != "convert":
        return None
    return next((child for child in node.children if child.id == CONVERT_MAIN_COMMAND_ID), None)


def default_child_command(node: CommandNode) -> CommandNode | None:
    convert_child = main_convert_child(node)
    if convert_child is not None:
        return convert_child
    preferred_id = DEFAULT_CHILD_COMMAND_IDS.get(node.id, "")
    if not preferred_id:
        return None
    return next((child for child in node.children if child.id == preferred_id), None)


async def activate_command_node(node: CommandNode, path_prefix: list[str] | None = None) -> None:
    prefix = list(state.get("command_path", [])) if path_prefix is None else list(path_prefix)
    if node.children:
        convert_child = main_convert_child(node)
        if convert_child is not None:
            state["command_path"] = compact_single_child_command_path([*prefix, node.id])
            select_command_node(convert_child)
            return
        default_child = default_child_command(node)
        if default_child is not None:
            state["command_path"] = compact_single_child_command_path([*prefix, node.id])
            select_command_node(default_child)
            return
        if len(node.children) == 1:
            await activate_command_node(node.children[0], [*prefix, node.id])
            return
        enter_command_path([*prefix, node.id])
        return
    state["command_path"] = compact_single_child_command_path(prefix)
    if node.id in QUICK_RUN_COMMAND_IDS:
        state["pending_command"] = None
        await start_operation(operation_from_quick_command(node))
        return
    select_command_node(node)


def command_click_handler(node: CommandNode):
    async def handler() -> None:
        await activate_command_node(node)

    return handler


def go_back_command() -> None:
    if state.get("pending_command") is not None:
        path = list(state.get("command_path", []))
        level = command_level_for_path(path)
        parent = level[0][-1] if level and level[0] else None
        if parent is not None and default_child_command(parent) is not None:
            path.pop()
            state["command_path"] = compact_single_child_command_path(path)
        else:
            state["command_path"] = compact_single_child_command_path(path)
        state["pending_command"] = None
    else:
        path = list(state.get("command_path", []))
        if path:
            path.pop()
        state["command_path"] = compact_single_child_command_path(path)
    command_tree.refresh()


def field_id(field: dict[str, Any]) -> str:
    return str(field.get("id") or field.get("name") or "").strip()


def field_label(field: dict[str, Any]) -> str:
    language = settings.language
    if language == "ru" and field.get("label_ru"):
        return str(field["label_ru"])
    return str(field.get("label") or field.get("title") or field_id(field))


def field_hint(field: dict[str, Any]) -> str:
    language = settings.language
    if language == "ru" and field.get("hint_ru"):
        return str(field["hint_ru"])
    if language == "ru" and field.get("description_ru"):
        return str(field["description_ru"])
    return str(field.get("hint") or field.get("description") or "")


def is_workbench_route_field(field: dict[str, Any]) -> bool:
    key = field_id(field).strip().lower()
    return key in {
        "source",
        "source_dir",
        "source_path",
        "input",
        "input_dir",
        "input_path",
        "target_dir",
        "target_path",
        "destination",
        "destination_dir",
        "destination_path",
        "output",
        "output_dir",
        "output_path",
    }


def command_visible_fields(fields: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [field for field in fields if not is_workbench_route_field(field)]


def workbench_value_for_field(field: dict[str, Any]) -> str:
    key = field_id(field).strip().lower()
    if any(part in key for part in ("target", "destination", "output")):
        return str(current_target_path())
    return str(current_source_path())


def explicit_workbench_value_for_field(field: dict[str, Any]) -> str:
    key = field_id(field).strip().lower()
    if any(part in key for part in ("target", "destination", "output")):
        return str(state.get("destination_path") or getattr(settings, "destination_path", "") or "").strip()
    return str(state.get("source_path") or getattr(settings, "source_path", "") or "").strip()


def operation_from_quick_command(node: CommandNode) -> Operation:
    parameters = dict(node.parameters)
    for field in node.fields:
        if not is_workbench_route_field(field):
            continue
        key = field_id(field)
        value = explicit_workbench_value_for_field(field)
        if key and value:
            parameters[key] = value
    return node.to_operation(parameters)


def field_default(field: dict[str, Any]) -> Any:
    if "default" in field:
        return field["default"]
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    options = field.get("options", [])
    if kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        if not isinstance(options, list):
            return []
        selected: list[Any] = []
        for option in options:
            if isinstance(option, dict) and option.get("default", False):
                selected.append(option.get("value", option.get("id", option.get("label"))))
        return selected
    if isinstance(options, list) and options:
        first = options[0]
        if isinstance(first, dict):
            return first.get("value", first.get("id", ""))
        return first
    return ""


def current_field_value(field: dict[str, Any]) -> Any:
    key = field_id(field)
    values = state.setdefault("field_values", {})
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    if key not in values:
        values[key] = field_default(field)
    elif kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"} and not isinstance(values[key], list):
        values[key] = field_default(field)
    elif kind in {"radio", "radiobuttons", "radio-buttons"} and isinstance(values[key], list):
        values[key] = field_default(field)
    elif kind in {"radio", "radiobuttons", "radio-buttons", "select", "choice", "format"}:
        valid_values = {option_value(option) for option in field.get("options", []) if isinstance(field.get("options", []), list)}
        if valid_values and values[key] not in valid_values:
            values[key] = field_default(field)
    elif is_checkbox_group(field):
        valid_values = {option_value(option) for option in field.get("options", []) if isinstance(field.get("options", []), list)}
        if valid_values:
            selected = values[key] if isinstance(values[key], list) else []
            values[key] = [item for item in selected if item in valid_values]
            min_selected = int(field.get("min_selected", 0) or 0)
            if len(values[key]) < min_selected:
                values[key] = field_default(field)
    return values[key]


def set_field_value(key: str, value: Any, refresh: bool = False) -> None:
    state.setdefault("field_values", {})[key] = value
    if refresh:
        try:
            command_tree.refresh()
        except NameError:
            pass


def refresh_command_tree() -> None:
    try:
        command_tree.refresh()
    except NameError:
        pass


def set_number_field_value(field: dict[str, Any], key: str, value: Any, refresh: bool = False) -> None:
    state.setdefault("field_values", {})[key] = value
    if value in {None, ""}:
        if refresh:
            refresh_command_tree()
        return
    try:
        number_value = float(str(value).replace(",", "."))
    except ValueError:
        if refresh:
            refresh_command_tree()
        return
    min_value = field.get("min")
    max_value = field.get("max")
    if min_value is not None and number_value < float(min_value):
        safe_notify(f"{field_label(field)}: minimum is {min_value}.", "warning")
    if max_value is not None and number_value > float(max_value):
        safe_notify(f"{field_label(field)}: maximum is {max_value}.", "warning")
    if refresh:
        refresh_command_tree()


def adjusted_number_value(field: dict[str, Any], current: Any, direction: int) -> int | float:
    step_raw = field.get("step", 1)
    try:
        step = float(step_raw)
    except (TypeError, ValueError):
        step = 1.0

    seed = current
    if seed is None or seed == "":
        seed = field_default(field) or 0
    try:
        value = float(seed)
    except (TypeError, ValueError):
        value = 0.0

    value += step * (1 if direction > 0 else -1)
    for bound_key, clamp in (("min", max), ("max", min)):
        bound = field.get(bound_key)
        if bound is None or bound == "":
            continue
        try:
            value = clamp(value, float(bound))
        except (TypeError, ValueError):
            continue

    kind = str(field.get("type", field.get("kind", "number"))).lower()
    integer_like = kind in {"number", "int", "integer", "quality", "quality_percent", "quality-percent"} and float(step).is_integer()
    return int(round(value)) if integer_like else round(value, 6)


def spin_number_field(key: str, field: dict[str, Any], control: Any, direction: int, refresh: bool = False) -> None:
    value = adjusted_number_value(field, state.setdefault("field_values", {}).get(key), direction)
    set_number_field_value(field, key, value)
    control.set_value(value)
    if refresh:
        refresh_command_tree()


def normalize_rgb_component(value: Any, default: int = 0) -> int:
    try:
        number = int(round(float(str(value).replace(",", "."))))
    except (TypeError, ValueError):
        number = default
    return max(0, min(255, number))


def current_rgb_component(key: str, default: int = 0) -> int:
    values = state.setdefault("field_values", {})
    value = normalize_rgb_component(values.get(key, default), default)
    values[key] = value
    return value


def set_rgb_component(key: str, value: Any, default: int = 0) -> None:
    state.setdefault("field_values", {})[key] = normalize_rgb_component(value, default)
    refresh_command_tree()


def spin_rgb_component(key: str, control: Any, direction: int, default: int = 0) -> None:
    value = current_rgb_component(key, default) + direction
    value = normalize_rgb_component(value, default)
    state.setdefault("field_values", {})[key] = value
    control.set_value(value)
    refresh_command_tree()


def parallel_control_text(key: str) -> str:
    ru = settings.language == "ru"
    texts = {
        "enabled": ("Многопоточность", "Multithreading"),
        "workers": ("Потоки", "Workers"),
        "tooltip": (
            "Глобально включает параллельную обработку изображений для пакетных режимов. "
            "На 16 ГБ памяти лучше оставить 1-4 потока; для тяжёлых карт 8 потоков уже заметно нагружает память.",
            "Globally enables parallel image processing for batch modes. "
            "On 16 GB RAM use 1-4 workers; heavy maps can stress memory even at 8 workers.",
        ),
    }
    return texts[key][0 if ru else 1]


def set_parallel_enabled(value: Any) -> None:
    state["parallel_enabled"] = bool(value)
    save_parallel_settings()


def set_parallel_worker_count(value: Any, control: Any | None = None) -> None:
    workers = normalize_worker_count(value)
    state["worker_count"] = workers
    if control is not None and getattr(control, "value", None) != workers:
        control.set_value(workers)
    save_parallel_settings()


def spin_parallel_worker_count(control: Any, direction: int) -> None:
    workers = normalize_worker_count(state.get("worker_count", DEFAULT_WORKER_COUNT)) + direction
    set_parallel_worker_count(workers, control)


def render_global_parallel_control() -> None:
    tooltip = parallel_control_text("tooltip")
    with ui.element("div").classes("audion-parallel-control"):
        checkbox = ui.checkbox(
            parallel_control_text("enabled"),
            value=bool(state.get("parallel_enabled", DEFAULT_PARALLEL_ENABLED)),
            on_change=lambda event: set_parallel_enabled(event.value),
        ).props("dense").classes("audion-parallel-checkbox")
        add_tooltip(checkbox, parallel_control_text("enabled"), tooltip)

        add_tooltip(ui.label(parallel_control_text("workers")).classes("audion-parallel-label"), parallel_control_text("workers"), tooltip)

        worker_input = ui.number(
            value=normalize_worker_count(state.get("worker_count", DEFAULT_WORKER_COUNT)),
            min=MIN_WORKER_COUNT,
            max=MAX_WORKER_COUNT,
            step=1,
            on_change=lambda event: set_parallel_worker_count(event.value),
        ).props("dense outlined hide-bottom-space").classes("audion-number audion-parallel-number")
        add_tooltip(worker_input, parallel_control_text("workers"), tooltip)
        with worker_input.add_slot("append"):
            with ui.element("div").classes("audion-number-spinner audion-parallel-spinner"):
                add_tooltip(ui.button(
                    icon="keyboard_arrow_up",
                    on_click=lambda control=worker_input: spin_parallel_worker_count(control, 1),
                ).props("dense flat round tabindex=-1").classes("audion-number-spin-button"), parallel_control_text("workers"), tooltip)
                add_tooltip(ui.button(
                    icon="keyboard_arrow_down",
                    on_click=lambda control=worker_input: spin_parallel_worker_count(control, -1),
                ).props("dense flat round tabindex=-1").classes("audion-number-spin-button"), parallel_control_text("workers"), tooltip)


def render_maintenance_controls() -> None:
    with ui.element("div").classes("audion-maintenance-row"):
        render_global_parallel_control()
        add_tooltip(ui.button(
            tr("copy_output_to_input"),
            icon="drive_file_move",
            on_click=copy_output_to_input_click_handler,
        ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button audion-output-to-input-button rounded-lg"), tr("copy_output_to_input"), tr("copy_output_to_input_tooltip"))


def select_options(field: dict[str, Any]) -> dict[Any, str] | list[Any]:
    options = field.get("options", [])
    if not isinstance(options, list):
        return []
    if all(isinstance(option, dict) for option in options):
        result: dict[Any, str] = {}
        for option in options:
            value = option.get("value", option.get("id", ""))
            if settings.language == "ru" and option.get("label_ru"):
                label = str(option["label_ru"])
            else:
                label = str(option.get("label") or option.get("title") or value)
            result[value] = label
        return result
    return options


def option_value(option: Any) -> Any:
    if isinstance(option, dict):
        return option.get("value", option.get("id", option.get("label", "")))
    return option


def option_label(option: Any) -> str:
    if not isinstance(option, dict):
        return str(option)
    language = settings.language
    if language == "ru" and option.get("label_ru"):
        return str(option["label_ru"])
    return str(option.get("label") or option.get("title") or option_value(option))


IMAGE_FORMAT_LOSSLESS_TOKENS = {"png", "tif", "tiff"}
IMAGE_FORMAT_LOSSY_TOKENS = {"avif", "heic", "heif", "jpg", "jpeg", "webp"}
IMAGE_FORMAT_SOURCE_TOKENS = {"original", "source", "native"}
IMAGE_FORMAT_HINTS = ("format", "formats", "формат", "форматы")


def choice_tone_slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.strip().lower()).strip("-")


def choice_tokens(value: Any, label: str) -> set[str]:
    raw = f"{value} {label}".lower()
    compact = re.sub(r"[^a-z0-9а-яё]+", "_", raw).strip("_")
    tokens = {part for part in re.split(r"[^a-z0-9а-яё]+", raw) if part}
    if compact:
        tokens.add(compact)
    return tokens


def image_format_field_enabled(field: dict[str, Any], option_items: list[dict[str, Any]] | None = None) -> bool:
    key = field_id(field).lower()
    group = str(field.get("group") or field.get("ui_group") or field.get("section_group") or "").strip().lower()
    label = field_label(field).lower()
    if key in {"to", "output_format", "input_format", "format"}:
        return True
    if any(hint in key or hint in group or hint in label for hint in IMAGE_FORMAT_HINTS):
        return True
    if option_items:
        format_values = IMAGE_FORMAT_LOSSLESS_TOKENS | IMAGE_FORMAT_LOSSY_TOKENS | IMAGE_FORMAT_SOURCE_TOKENS
        return any(choice_tokens(item["value"], item["label"]) & format_values for item in option_items)
    return False


def detected_image_format_tone(field: dict[str, Any], value: Any, label: str) -> str:
    tokens = choice_tokens(value, label)
    if tokens & IMAGE_FORMAT_SOURCE_TOKENS:
        return "source"
    if tokens & IMAGE_FORMAT_LOSSLESS_TOKENS:
        return "lossless"
    if tokens & IMAGE_FORMAT_LOSSY_TOKENS:
        return "lossy"
    return ""


def choice_option_tone(field: dict[str, Any], option: Any, value: Any, label: str) -> str:
    if image_format_field_enabled(field):
        detected = detected_image_format_tone(field, value, label)
        if detected:
            return detected
    if isinstance(option, dict) and (option.get("tone") or option.get("category") or option.get("group")):
        return choice_tone_slug(str(option.get("tone") or option.get("category") or option.get("group") or ""))
    tokens = choice_tokens(value, label)
    key = field_id(field).lower()
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


def checkbox_options(field: dict[str, Any]) -> list[tuple[Any, str]]:
    options = field.get("options", [])
    if not isinstance(options, list):
        return []
    return [(option_value(option), option_label(option)) for option in options]


def option_disabled(option: Any) -> bool:
    return isinstance(option, dict) and bool(option.get("disabled", False))


def choice_option_items(field: dict[str, Any]) -> list[dict[str, Any]]:
    options = field.get("options", [])
    if not isinstance(options, list):
        return []
    items: list[dict[str, Any]] = []
    for option in options:
        value = option_value(option)
        label = option_label(option)
        items.append({
            "value": value,
            "label": label,
            "disabled": option_disabled(option),
            "tone": choice_option_tone(field, option, value, label),
            "swatch": str(option.get("swatch") or option.get("color") or "").strip() if isinstance(option, dict) else "",
        })
    return items


def checkbox_option_rows(field: dict[str, Any]) -> list[list[tuple[Any, str]]]:
    options = field.get("options", [])
    if not isinstance(options, list):
        return []
    rows: list[list[tuple[Any, str]]] = [[]]
    for option in options:
        if isinstance(option, dict) and option.get("new_row") and rows[-1]:
            rows.append([])
        rows[-1].append((option_value(option), option_label(option)))
    return [row for row in rows if row]


def matching_option_value(value: Any, options: list[Any]) -> Any:
    for option in options:
        if value == option:
            return option
        try:
            if float(str(value).replace(",", ".")) == float(str(option).replace(",", ".")):
                return option
        except (TypeError, ValueError):
            pass
    return None


def is_checkbox_group(field: dict[str, Any]) -> bool:
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    return kind in {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}


def is_empty_field_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def field_condition_matches(condition: Any) -> bool:
    if not isinstance(condition, dict):
        return True
    if isinstance(condition.get("all"), list):
        return all(field_condition_matches(item) for item in condition["all"])
    if isinstance(condition.get("any"), list):
        return any(field_condition_matches(item) for item in condition["any"])
    key = str(condition.get("field") or condition.get("id") or "").strip()
    if not key:
        return True
    values = state.setdefault("field_values", {})
    actual = values.get(key, condition.get("default"))
    if "equals" in condition:
        expected = condition.get("equals")
        expected_values = expected if isinstance(expected, list) else [expected]
        return actual in expected_values
    if "not_equals" in condition:
        blocked = condition.get("not_equals")
        blocked_values = blocked if isinstance(blocked, list) else [blocked]
        return actual not in blocked_values
    if "in" in condition:
        expected_values = condition.get("in")
        if not isinstance(expected_values, list):
            return False
        if isinstance(actual, list):
            return any(item in expected_values for item in actual)
        return actual in expected_values
    if "not_in" in condition:
        blocked_values = condition.get("not_in")
        if not isinstance(blocked_values, list):
            return True
        if isinstance(actual, list):
            return all(item not in blocked_values for item in actual)
        return actual not in blocked_values
    if "contains" in condition:
        expected = condition.get("contains")
        expected_values = expected if isinstance(expected, list) else [expected]
        actual_values = actual if isinstance(actual, list) else [actual]
        return any(item in actual_values for item in expected_values)
    if "not_contains" in condition:
        blocked = condition.get("not_contains")
        blocked_values = blocked if isinstance(blocked, list) else [blocked]
        actual_values = actual if isinstance(actual, list) else [actual]
        return all(item not in actual_values for item in blocked_values)
    if "contains_any" in condition:
        expected_values = condition.get("contains_any")
        if not isinstance(expected_values, list):
            return False
        actual_values = actual if isinstance(actual, list) else [actual]
        return any(item in actual_values for item in expected_values)
    if "not_contains_any" in condition:
        blocked_values = condition.get("not_contains_any")
        if not isinstance(blocked_values, list):
            return True
        actual_values = actual if isinstance(actual, list) else [actual]
        return all(item not in actual_values for item in blocked_values)
    if "contains_all" in condition:
        expected_values = condition.get("contains_all")
        if not isinstance(expected_values, list):
            return False
        actual_values = actual if isinstance(actual, list) else [actual]
        return all(item in actual_values for item in expected_values)
    return True


def field_is_visible(field: dict[str, Any]) -> bool:
    if "visible_if" in field and not field_condition_matches(field.get("visible_if")):
        return False
    if "hidden_if" in field and field_condition_matches(field.get("hidden_if")):
        return False
    if "visible_if_any" in field:
        conditions = field.get("visible_if_any")
        if isinstance(conditions, list) and not any(field_condition_matches(condition) for condition in conditions):
            return False
    return True


def field_is_disabled(field: dict[str, Any]) -> bool:
    if "disabled_if" in field and field_condition_matches(field.get("disabled_if")):
        return True
    if "disabled_if_any" in field:
        conditions = field.get("disabled_if_any")
        if isinstance(conditions, list) and any(field_condition_matches(condition) for condition in conditions):
            return True
    if "enabled_if" in field and not field_condition_matches(field.get("enabled_if")):
        return True
    return False


def field_choice_layout(field: dict[str, Any]) -> str:
    return str(field.get("layout") or field.get("choices_layout") or field.get("option_layout") or "").strip().lower()


def field_choice_columns(field: dict[str, Any]) -> int:
    aliases = {
        "two_columns": 2,
        "three_columns": 3,
        "four_columns": 4,
        "five_columns": 5,
        "six_columns": 6,
        "seven_columns": 7,
    }
    layout = field_choice_layout(field)
    raw = field.get("columns", field.get("choice_columns", aliases.get(layout, 0)))
    try:
        columns = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return columns if 2 <= columns <= 7 else 0


def field_choice_style(field: dict[str, Any], option_count: int = 0) -> str:
    explicit = str(field.get("style") or field.get("choice_style") or field.get("variant") or "").strip().lower()
    if explicit:
        return explicit
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    if kind in {"radio", "radiobuttons", "radio-buttons"} and 2 <= option_count <= 7:
        return "segmented"
    return ""


def field_choice_row_classes(field: dict[str, Any]) -> str:
    if field_choice_layout(field) == "vertical":
        return "audion-choice-row audion-choice-column"
    columns = field_choice_columns(field)
    suffix = f" audion-choice-cols-{columns}" if columns else ""
    return f"audion-choice-row{suffix}"


def is_module_path_field(field: dict[str, Any]) -> bool:
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    return not is_workbench_route_field(field) and field_id(field) in {"input_path", "output_path"} and kind in {"path", "folder"}


def module_path_fields(node: CommandNode | None) -> list[dict[str, Any]]:
    if node is None:
        return []
    return [field for field in node.fields if is_module_path_field(field)]


def field_identity_classes(field: dict[str, Any]) -> str:
    key = field_id(field)
    if not key:
        return ""
    safe = "".join(char if char.isalnum() else "-" for char in key.lower()).strip("-")
    return f" audion-field-id-{safe}" if safe else ""


def field_container_classes(field: dict[str, Any], disabled: bool = False, *, flat: bool = False) -> str:
    span = str(field.get("span") or field.get("width") or "").lower()
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    identity = field_identity_classes(field)
    choice_class = ""
    if kind in {"radio", "radiobuttons", "radio-buttons"}:
        choice_class = " audion-field-radio"
    elif is_checkbox_group(field):
        choice_class = " audion-field-checks"
    if choice_class and field_choice_layout(field) == "vertical":
        choice_class += " audion-choice-vertical"
    flat_class = " audion-field-flat" if flat else ""
    disabled_class = " audion-field-disabled" if disabled else ""
    if span in {"full", "wide", "100%", "1/-1"}:
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}{disabled_class}"
    if kind in {"radio", "radiobuttons", "radio-buttons"}:
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}{disabled_class}"
    if kind in {"select", "choice", "format"}:
        return f"audion-field audion-field-select{identity}{choice_class}{flat_class}{disabled_class}"
    if kind in {"textarea", "multiline", "path", "file", "folder"}:
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}{disabled_class}"
    if is_checkbox_group(field):
        return f"audion-field audion-field-wide{identity}{choice_class}{flat_class}{disabled_class}"
    return f"audion-field{identity}{choice_class}{flat_class}{disabled_class}"


def choice_tone_class(item: dict[str, Any]) -> str:
    tone = str(item.get("tone") or "").strip()
    return f" audion-choice-tone-{tone}" if tone else ""


def choice_swatch_class(item: dict[str, Any]) -> str:
    return " audion-color-choice" if str(item.get("swatch") or "").strip() else ""


def format_choice_chip_field(field: dict[str, Any], option_items: list[dict[str, Any]]) -> bool:
    return image_format_field_enabled(field, option_items) and any(item.get("tone") for item in option_items)


def render_segmented_choice(field: dict[str, Any], option_items: list[dict[str, Any]], value: Any, disabled: bool = False) -> None:
    key = field_id(field)
    label = field_label(field)
    hint = field_hint(field)
    with ui.element("div").classes(f"{field_choice_row_classes(field)} audion-mode-toggle audion-segmented-choice w-full"):
        for item in option_items:
            item_value = item["value"]
            item_disabled = disabled or item["disabled"]
            item_tone = item.get("tone") or choice_option_tone(field, item, item_value, item.get("label", "")) or "process"
            classes = "audion-mode-option"
            if item_tone:
                classes += f" audion-mode-tone-{item_tone}"
            if item_value == value:
                classes += " audion-mode-option-active"
            if item_disabled:
                classes += " audion-mode-option-disabled"
            option = ui.element("button").props(
                f"type=button aria-pressed={'true' if item_value == value else 'false'}{' disabled' if item_disabled else ''}"
            ).classes(classes)
            if not item_disabled:
                option.on("click", lambda event, item_key=key, option_value=item_value: set_field_value(item_key, option_value, refresh=True))
            with option:
                ui.label(item["label"]).classes("audion-mode-option-label")
            add_tooltip(option, label, item["label"], hint)


def render_radio_choice(field: dict[str, Any], option_items: list[dict[str, Any]], value: Any, disabled: bool = False) -> None:
    key = field_id(field)
    label = field_label(field)
    hint = field_hint(field)
    disable_prop = " disable" if disabled else ""
    with ui.element("div").classes(field_choice_row_classes(field)):
        for item in option_items:
            item_value = item["value"]
            classes = f"audion-choice-option{choice_tone_class(item)}{choice_swatch_class(item)}"
            if item["disabled"]:
                classes += " audion-disabled-choice"
            radio = ui.radio(
                options={item_value: item["label"]},
                value=item_value if item_value == value else None,
                on_change=lambda event, option_value=item_value: set_field_value(key, option_value, refresh=True) if event.value is not None else refresh_command_tree(),
            ).props(f"dense{disable_prop}").classes(classes)
            swatch = str(item.get("swatch") or "").strip()
            if swatch:
                radio.style(f"--audion-choice-swatch: {swatch};")
            if item["disabled"]:
                radio.props("disable")
            add_tooltip(radio, label, item["label"], hint)


def render_field(field: dict[str, Any], *, flat: bool = False) -> None:
    key = field_id(field)
    if not key:
        return
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    label = field_label(field)
    value = current_field_value(field)
    hint = field_hint(field)
    disabled = field_is_disabled(field)
    disable_prop = " disable" if disabled else ""

    with ui.element("div").classes(field_container_classes(field, disabled, flat=flat)):
        if kind in {"select", "choice", "format"}:
            add_tooltip(ui.select(
                options=select_options(field),
                label=label,
                value=value,
                on_change=lambda event, item_key=key: set_field_value(item_key, event.value, refresh=True),
            ).props(f"dense outlined options-dense popup-content-class=audion-select-popup{disable_prop}").classes("audion-select w-full"), label, hint)
            return

        if kind in {"quality", "quality_percent", "quality-percent"}:
            add_tooltip(ui.label(label).classes("audion-field-label"), label, hint)
            quality_options = select_options(field)
            if not isinstance(quality_options, dict):
                quality_options = {}
            preset_value = matching_option_value(value, list(quality_options.keys()))
            with ui.row().classes("audion-quality-row"):
                quality_items = [
                    {"value": option_key, "label": option_text, "disabled": False}
                    for option_key, option_text in quality_options.items()
                ]
                with ui.element("div").classes("audion-quality-presets"):
                    render_segmented_choice(field, quality_items, preset_value, disabled=disabled)
                number_input = ui.number(
                    value=value if value != "" else None,
                    min=field.get("min"),
                    max=field.get("max"),
                    step=field.get("step", 1),
                    on_change=lambda event, item_key=key, item_field=field: set_number_field_value(item_field, item_key, event.value, refresh=True),
                ).props(f"dense outlined suffix=%{disable_prop}").classes("audion-number audion-quality-number")
                with number_input.add_slot("append"):
                    with ui.element("div").classes("audion-number-spinner"):
                        add_tooltip(ui.button(
                            icon="keyboard_arrow_up",
                            on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_key, item_field, control, 1, refresh=True),
                        ).props(f"dense flat round tabindex=-1{disable_prop}").classes("audion-number-spin-button"), label, hint)
                        add_tooltip(ui.button(
                            icon="keyboard_arrow_down",
                            on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_key, item_field, control, -1, refresh=True),
                        ).props(f"dense flat round tabindex=-1{disable_prop}").classes("audion-number-spin-button"), label, hint)
            return

        if kind in {"radio", "radiobuttons", "radio-buttons"}:
            if not flat:
                add_tooltip(ui.label(label).classes("audion-field-label"), label, hint)
            option_items = choice_option_items(field)
            enabled_values = [item["value"] for item in option_items if not item["disabled"]]
            option_values = [item["value"] for item in option_items]
            if option_values and (value not in option_values or any(item["value"] == value and item["disabled"] for item in option_items)):
                value = enabled_values[0] if enabled_values else option_values[0]
                set_field_value(key, value)
            if format_choice_chip_field(field, option_items):
                render_radio_choice(field, option_items, value, disabled=disabled)
                return
            if field_choice_style(field, len(option_items)) in {"segmented", "tabs", "buttons", "button-toggle", "button_toggle"}:
                render_segmented_choice(field, option_items, value, disabled=disabled)
                return
            render_radio_choice(field, option_items, value, disabled=disabled)
            return

        if kind in {"rgb_color", "rgb-color", "color_rgb", "color-rgb"}:
            red = current_rgb_component("color_r", 204)
            green = current_rgb_component("color_g", 0)
            blue = current_rgb_component("color_b", 0)
            rgb_fields = [
                ("color_r", "R", red, 204),
                ("color_g", "G", green, 0),
                ("color_b", "B", blue, 0),
            ]
            with ui.element("div").classes("audion-rgb-control"):
                add_tooltip(ui.label(label).classes("audion-rgb-label"), label, hint)
                patch = ui.element("div").classes("audion-rgb-patch").style(
                    f"background: rgb({red}, {green}, {blue});"
                )
                add_tooltip(patch, label, f"RGB {red}, {green}, {blue}", hint)
                for component_key, component_label, component_value, component_default in rgb_fields:
                    with ui.element("div").classes("audion-rgb-channel"):
                        add_tooltip(ui.label(component_label).classes("audion-rgb-channel-label"), label, component_label, hint)
                        component_input = add_tooltip(ui.number(
                            value=component_value,
                            min=0,
                            max=255,
                            step=1,
                            on_change=lambda event, item_key=component_key, item_default=component_default: set_rgb_component(
                                item_key,
                                event.value,
                                item_default,
                            ),
                        ).props(f"dense outlined hide-bottom-space{disable_prop}").classes("audion-number audion-rgb-number"), label, component_label, hint)
                        with component_input.add_slot("append"):
                            with ui.element("div").classes("audion-number-spinner audion-rgb-spinner"):
                                add_tooltip(ui.button(
                                    icon="keyboard_arrow_up",
                                    on_click=lambda item_key=component_key, control=component_input, item_default=component_default: spin_rgb_component(
                                        item_key,
                                        control,
                                        1,
                                        item_default,
                                    ),
                                ).props(f"dense flat round tabindex=-1{disable_prop}").classes("audion-number-spin-button"), label, component_label, hint)
                                add_tooltip(ui.button(
                                    icon="keyboard_arrow_down",
                                    on_click=lambda item_key=component_key, control=component_input, item_default=component_default: spin_rgb_component(
                                        item_key,
                                        control,
                                        -1,
                                        item_default,
                                    ),
                                ).props(f"dense flat round tabindex=-1{disable_prop}").classes("audion-number-spin-button"), label, component_label, hint)
            return

        if kind in {"number", "int", "integer", "float"}:
            number_input = add_tooltip(ui.number(
                label=label,
                value=value if value != "" else None,
                min=field.get("min"),
                max=field.get("max"),
                step=field.get("step", 1),
                on_change=lambda event, item_key=key, item_field=field: set_number_field_value(item_field, item_key, event.value),
            ).props(f"dense outlined{disable_prop}").classes("audion-number w-full"), label, hint)
            with number_input.add_slot("append"):
                with ui.element("div").classes("audion-number-spinner"):
                    add_tooltip(ui.button(
                        icon="keyboard_arrow_up",
                        on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_key, item_field, control, 1),
                    ).props(f"dense flat round tabindex=-1{disable_prop}").classes("audion-number-spin-button"), label, hint)
                    add_tooltip(ui.button(
                        icon="keyboard_arrow_down",
                        on_click=lambda item_key=key, item_field=field, control=number_input: spin_number_field(item_key, item_field, control, -1),
                    ).props(f"dense flat round tabindex=-1{disable_prop}").classes("audion-number-spin-button"), label, hint)
            return

        if kind in {"path", "folder"}:
            with ui.row().classes("w-full items-start gap-2"):
                path_input = add_tooltip(ui.input(
                    label=label,
                    value=str(value) if value is not None else "",
                    placeholder=str(field.get("placeholder", "")),
                    on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
                ).props(f"dense outlined{disable_prop}").classes("min-w-0 flex-1"), label, hint)
                add_tooltip(ui.button(
                    tr("choose_folder"),
                    on_click=folder_field_click_handler(
                        key,
                        label,
                        path_input,
                        bool(field.get("show_new_folder_button", False)),
                    ),
                ).props(f"dense flat no-wrap{disable_prop}").classes("audion-action w-36 rounded-lg"), tr("choose_folder"), label, hint)
            return

        if kind in {"checkbox", "bool", "boolean", "toggle"}:
            add_tooltip(ui.checkbox(
                label,
                value=bool(value),
                on_change=lambda event, item_key=key: set_field_value(item_key, bool(event.value)),
            ).props(f"dense{disable_prop}").classes("audion-single-checkbox"), label, hint)
            return

        if is_checkbox_group(field):
            selected = set(value if isinstance(value, list) else [])
            controls: dict[Any, Any] = {}

            def sync_checkboxes(item_key: str = key) -> None:
                set_field_value(
                    item_key,
                    [option_key for option_key, checkbox in controls.items() if bool(checkbox.value)],
                )

            add_tooltip(ui.label(label).classes("audion-field-label"), label, hint)
            with ui.element("div").classes(field_choice_row_classes(field)):
                for item in choice_option_items(field):
                    option_key = item["value"]
                    option_text = item["label"]
                    classes = f"audion-choice-option{choice_tone_class(item)}"
                    if item["disabled"]:
                        classes += " audion-disabled-choice"
                    checkbox = add_tooltip(ui.checkbox(
                        option_text,
                        value=option_key in selected and not item["disabled"],
                        on_change=lambda _event: sync_checkboxes(),
                    ).props(f"dense{disable_prop}").classes(classes), label, option_text, hint)
                    if item["disabled"]:
                        checkbox.props("disable")
                    controls[option_key] = checkbox
            sync_checkboxes()
            return

        add_tooltip(ui.input(
            label=label,
            value=str(value) if value is not None else "",
            placeholder=str(field.get("placeholder", "")),
            on_change=lambda event, item_key=key: set_field_value(item_key, event.value),
        ).props(f"dense outlined{disable_prop}").classes("w-full"), label, hint)


def render_fields_grid(fields: list[dict[str, Any]]) -> None:
    if not fields:
        return
    for field in fields:
        current_field_value(field)
    fields = [field for field in command_visible_fields(fields) if field_is_visible(field)]
    if not fields:
        return
    with ui.element("div").classes("audion-fields-grid"):
        for section_id, section_fields in group_fields_by_section(fields):
            with ui.element("section").classes(f"audion-field-section audion-field-section-{section_id}"):
                add_tooltip(ui.label(field_section_label(section_id)).classes("audion-section-title"), field_section_label(section_id))
                with ui.element("div").classes("audion-section-fields"):
                    for field in section_fields:
                        render_field(field)


def field_section_id(field: dict[str, Any]) -> str:
    key = field_id(field)
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    section = str(field.get("section") or "").strip().lower()
    explicit = str(field.get("group") or field.get("ui_group") or field.get("section_group") or "").strip().lower()
    if not explicit and section and section not in {"advanced", "expert", "rare"}:
        explicit = section
    if explicit:
        return explicit
    if kind in {"profile_select", "profile-select", "preset_select", "preset-select", "preset_buttons", "presets", "profile_buttons", "profiles"}:
        return "preset"
    if key in {"overwrite", "dry_run", "limit_first_file", "test_first_file"} or key.endswith(("_dry_run", "_overwrite")):
        return "run"
    if any(part in key for part in ("source", "input", "url", "file", "folder", "path")):
        return "source"
    if any(part in key for part in ("output", "report", "export", "package", "release")):
        return "output"
    if any(part in key for part in ("format", "container", "profile", "preset", "quality", "dpi", "bitrate", "resolution")):
        return "format"
    if any(part in key for part in ("codec", "encode", "model", "engine")):
        return "encoding"
    if kind in {"checkbox", "bool", "boolean", "toggle", "checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}:
        return "options"
    return "parameters"


def field_section_label(section_id: str) -> str:
    key = f"section_{section_id}"
    label = tr(key)
    if label != key:
        return label
    return section_id.replace("_", " ").title()


def group_fields_by_section(fields: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    group_index: dict[str, int] = {}
    for field in fields:
        section_id = field_section_id(field)
        if section_id not in group_index:
            group_index[section_id] = len(groups)
            groups.append((section_id, [field]))
        else:
            groups[group_index[section_id]][1].append(field)
    return groups


def operation_from_pending_command(node: CommandNode) -> Operation:
    parameters = dict(node.parameters)
    values = state.setdefault("field_values", {})
    for field in node.fields:
        if is_workbench_route_field(field):
            key = field_id(field)
            if key:
                parameters[key] = workbench_value_for_field(field)
            continue
        if not field_is_visible(field) or field_is_disabled(field):
            continue
        key = field_id(field)
        if key:
            value = values.get(key, field_default(field))
            if bool(field.get("omit_if_empty", False)) and value in {None, ""}:
                continue
            parameters[key] = value
    return node.to_operation(parameters)


def validate_pending_fields(node: CommandNode) -> bool:
    values = state.setdefault("field_values", {})
    for field in command_visible_fields(node.fields):
        if not field_is_visible(field) or field_is_disabled(field):
            continue
        key = field_id(field)
        kind = str(field.get("type", field.get("kind", "text"))).lower()
        raw_value = values.get(key, field_default(field)) if key else field_default(field)
        if bool(field.get("required", False)):
            if is_checkbox_group(field):
                selected = raw_value if isinstance(raw_value, list) else []
                if not selected:
                    safe_notify(tr("select_required", field=field_label(field)), "warning")
                    return False
            elif kind in {"checkbox", "bool", "boolean", "toggle"}:
                if not bool(raw_value):
                    safe_notify(tr("field_required", field=field_label(field)), "warning")
                    return False
            elif is_empty_field_value(raw_value):
                safe_notify(tr("field_required", field=field_label(field)), "warning")
                return False

        if kind in {"number", "int", "integer", "float", "quality", "quality_percent", "quality-percent"}:
            if raw_value in {None, ""}:
                continue
            try:
                number_value = float(str(raw_value).replace(",", "."))
            except ValueError:
                safe_notify(f"{field_label(field)}: enter a number.", "warning")
                return False
            min_value = field.get("min")
            max_value = field.get("max")
            if min_value is not None and number_value < float(min_value):
                safe_notify(f"{field_label(field)}: minimum is {min_value}.", "warning")
                return False
            if max_value is not None and number_value > float(max_value):
                safe_notify(f"{field_label(field)}: maximum is {max_value}.", "warning")
                return False
            continue

        if not is_checkbox_group(field):
            continue
        min_selected = int(field.get("min_selected", 0) or 0)
        if min_selected <= 0:
            continue
        selected = values.get(key, field_default(field))
        if not isinstance(selected, list) or len(selected) < min_selected:
            safe_notify(tr("select_required", field=field_label(field)), "warning")
            return False
    return True


async def run_pending_command(node: CommandNode) -> None:
    if validate_pending_fields(node):
        await start_operation(operation_from_pending_command(node))


def run_pending_click_handler(node: CommandNode):
    async def handler() -> None:
        await run_pending_command(node)

    return handler


def default_field_values_for_node(node: CommandNode) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in node.fields:
        key = field_id(field)
        if key:
            values[key] = field_default(field)
    return values


async def run_command_with_defaults(node: CommandNode) -> None:
    previous_values = state.get("field_values", {})
    state["field_values"] = default_field_values_for_node(node)
    try:
        operation = operation_from_pending_command(node) if validate_pending_fields(node) else None
    finally:
        state["field_values"] = previous_values
    if operation is not None:
        await start_operation(operation)


def run_defaults_click_handler(node: CommandNode):
    async def handler() -> None:
        await run_command_with_defaults(node)

    return handler


def field_signature(fields: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(field_id(field) for field in command_visible_fields(fields) if field_id(field))


def iter_command_nodes(nodes: list[CommandNode] | tuple[CommandNode, ...]) -> Iterable[CommandNode]:
    for node in nodes:
        yield node
        yield from iter_command_nodes(node.children)


def root_quick_action_nodes(nodes: list[CommandNode]) -> list[CommandNode]:
    candidates = {node.id: node for node in iter_command_nodes(nodes)}
    return [candidates[command_id] for command_id in ROOT_QUICK_COMMAND_IDS if command_id in candidates]


def ordered_child_nodes(parent: CommandNode | None, command_ids: tuple[str, ...]) -> list[CommandNode]:
    if parent is None:
        return []
    candidates = {node.id: node for node in parent.children}
    return [candidates[command_id] for command_id in command_ids if command_id in candidates]


def convert_quick_action_nodes(parent: CommandNode | None) -> list[CommandNode]:
    if parent is None or parent.id != "convert":
        return []
    return ordered_child_nodes(parent, CONVERT_QUICK_COMMAND_IDS)


def switchable_child_nodes(parent: CommandNode | None) -> list[CommandNode]:
    if parent is None or parent.id == "convert":
        return []
    result: list[CommandNode] = []
    for node in parent.children:
        if node.children or node.id in QUICK_RUN_COMMAND_IDS:
            continue
        if command_visible_fields(node.fields):
            result.append(node)
    return result if len(result) > 1 else []


def select_child_command_click_handler(node: CommandNode):
    def handler() -> None:
        select_command_node(node)

    return handler


def render_convert_quick_actions(parent: CommandNode | None) -> None:
    actions = convert_quick_action_nodes(parent)
    if not actions:
        return
    with ui.element("div").classes("audion-convert-quick-actions"):
        for node in actions:
            add_tooltip(ui.button(
                node.display_title(settings.language),
                **icon_kwargs(command_icon(node.id, node.kind)),
                on_click=run_defaults_click_handler(node),
            ).props("dense flat no-wrap").classes("audion-action audion-convert-quick-button rounded-lg"), node.display_title(settings.language), node.display_description(settings.language))


def render_child_window_switcher(parent: CommandNode | None, pending: CommandNode | None) -> None:
    nodes = switchable_child_nodes(parent)
    if not nodes:
        return
    with ui.element("div").classes(f"audion-command-switcher audion-command-switcher-count-{len(nodes)}"):
        for node in nodes:
            classes = "audion-action audion-command-switch-button rounded-md"
            if pending is not None and node.id == pending.id:
                classes += " audion-command-switch-button-active"
            add_tooltip(ui.button(
                node.display_title(settings.language),
                **icon_kwargs(command_icon(node.id, node.kind)),
                on_click=select_child_command_click_handler(node),
            ).props("dense flat no-wrap").classes(classes), node.display_title(settings.language), node.display_description(settings.language))


def command_node_button(node: CommandNode, *, root_level: bool = False) -> None:
    has_children = bool(node.children)
    label = node_title(node)
    description = node.display_description(settings.language)
    if has_children and not description:
        description = tr("open_menu")

    row_classes = "audion-operation-row"
    button_classes = "audion-action audion-operation-button rounded-lg"
    if not has_children and not root_level:
        row_classes += " audion-operation-row-leaf"
        button_classes += " audion-operation-button-leaf"

    with ui.element("div").classes(row_classes):
        add_tooltip(ui.button(
            label,
            **icon_kwargs(command_icon(node.id, node.kind)),
            on_click=command_click_handler(node),
        ).props("dense flat no-wrap").classes(button_classes), label, description)
        if description and (root_level or has_children):
            add_tooltip(ui.label(description).classes("audion-operation-description"), label, description)


def command_nav_row(
    trail: list[CommandNode],
    pending: CommandNode | None,
) -> None:
    can_go_back = pending is not None or bool(trail)
    if pending is not None:
        title = node_title(pending)
    elif trail:
        title = " / ".join(node_title(node) for node in trail)
    else:
        title = ""

    if not can_go_back and not title:
        return

    with ui.row().classes("audion-command-nav w-full items-center gap-2"):
        if can_go_back:
            ui.button(
                tr("back"),
                icon="arrow_back",
                on_click=go_back_command,
            ).props("dense flat no-wrap").classes("audion-action w-28 rounded-lg")
        add_tooltip(ui.label(title).classes("audion-command-title min-w-0 flex-1 truncate text-sm text-gray-400"), title)
        if pending is not None:
            add_tooltip(ui.button(
                tr("run"),
                icon="play_arrow",
                on_click=run_pending_click_handler(pending),
            ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button rounded-lg"), tr("run"), pending.display_title(settings.language), pending.display_description(settings.language))


@ui.refreshable
def command_tree() -> None:
    trail, nodes = current_command_level()
    pending = state.get("pending_command")
    parent = trail[-1] if trail else None
    if pending is None and parent is not None:
        default_child = default_child_command(parent)
        if default_child is not None:
            state["pending_command"] = default_child
            pending = default_child
    command_nav_row(trail, pending)

    if pending is not None:
        if pending.id == CONVERT_MAIN_COMMAND_ID:
            render_convert_quick_actions(parent)
        else:
            render_child_window_switcher(parent, pending)
        if command_visible_fields(pending.fields):
            section_heading("parameters", tr("parameters"), "text-sm font-semibold text-gray-300")
            render_fields_grid(command_visible_fields(pending.fields))
        return

    parent_path_fields = module_path_fields(parent)
    if parent_path_fields:
        section_heading("folder_paths", tr("folder_paths"), "text-sm font-semibold text-gray-300")
        render_fields_grid(parent_path_fields)

    quick_actions = root_quick_action_nodes(nodes) if not trail else []
    if quick_actions:
        with ui.element("div").classes("audion-root-quick-actions"):
            for node in quick_actions:
                add_tooltip(ui.button(
                    node.display_title(settings.language),
                    **icon_kwargs(command_icon(node.id, node.kind)),
                    on_click=run_defaults_click_handler(node),
                ).props("dense flat no-wrap").classes("audion-action audion-nav-run-button audion-root-quick-button rounded-lg"), node.display_title(settings.language), node.display_description(settings.language))

    list_classes = "audion-operation-list"
    if nodes and all(not node.children for node in nodes):
        list_classes += " audion-operation-list-leaf"
        if 2 <= len(nodes) <= 6:
            list_classes += f" audion-operation-list-leaf-count-{len(nodes)}"
    with ui.element("div").classes(list_classes):
        for node in nodes:
            command_node_button(node, root_level=not trail)


def operation_by_id(operation_id: str) -> Operation | None:
    for operation in [*manifest.operations, *manifest.maintenance_operations]:
        if operation.id == operation_id:
            return operation
    return None


_application_css_cache: dict[str, str] = {}


def application_css(name: str) -> str:
    """A stylesheet that lives next to this module rather than inside it."""
    if name not in _application_css_cache:
        path = Path(__file__).resolve().with_name(name)
        _application_css_cache[name] = path.read_text(encoding="utf-8")
    return _application_css_cache[name]


def add_styles() -> None:
    add_audion_canonical_ui_styles()
    variables_css = "\n".join(
        f"            --{key}: {value};"
        for key, value in sorted(theme_variables().items())
    )
    ui.add_head_html(
        "<style>\n"
        ":root {\n"
        f"{variables_css}\n"
        "}\n"
        + application_css("tokens.css")
        + application_css("base.css")
        + WORKBENCH_LAYOUT_CSS
        + application_css("theme.css")
        + WORKBENCH_OVERRIDE_CSS
        + "\n</style>\n"
    )


def build_ui() -> None:
    ensure_project_dirs(paths)
    if not state["status"]:
        state["status"] = tr("idle")
    if active_theme_mode() == "dark":
        ui.dark_mode().enable()
    else:
        ui.dark_mode().disable()
    add_styles()
    ui.add_head_html(WORKBENCH_FEEDBACK_CSS)

    with ui.header().classes("audion-header h-[42px] items-center justify-between px-4"):
        add_tooltip(ui.label(app_title()).classes("audion-header-title text-lg font-bold"), app_title())
        with ui.row().classes("audion-header-controls items-center gap-2"):
            add_tooltip(ui.icon("palette").classes("text-lg"), tr("theme"))
            add_tooltip(ui.select(
                options=theme_options(),
                value=active_theme(),
                on_change=theme_change_handler,
            ).props("dense outlined options-dense").classes("audion-theme-select"), tr("theme"))
            add_tooltip(ui.button(tr("lang_switch"), on_click=toggle_language).props("dense flat").classes("audion-action rounded-lg"), tr("lang_switch"))
            cancel_button = add_tooltip(ui.button(tr("cancel"), on_click=lambda: state.update({"cancel": True})).props("dense flat color=negative"), tr("cancel"))
            cancel_button.visible = False

    with ui.element("div").classes("audion-shell"):
        with ui.column().classes("audion-pane audion-scroll gap-3"):
            with ui.column().classes("audion-panel audion-workspace-panel w-full gap-2 p-2"):
                WORKBENCH_RENDERER.render_address_rows()
                WORKBENCH_RENDERER.render_action_bar()

            section_heading("operations", tr("operations"), "text-lg font-bold")
            command_tree()

            if manifest.maintenance_operations:
                section_heading("maintenance", tr("maintenance"), "text-lg font-bold pt-2")
                render_maintenance_controls()
                for operation in manifest.maintenance_operations:
                    if operation.id == "cleanup_input_output":
                        continue
                    operation_button(operation)

        ui.element("div").classes("audion-splitter").props(f'title="{tr("resize_panels")}"')

        with ui.element("div").classes("audion-pane audion-right gap-2 pt-3"):
            with ui.column().classes("audion-panel w-full gap-2 p-3"):
                with ui.element("div").classes(status_row_classes()) as status_row:
                    status_dot_main = ui.element("span").classes("audion-status-dot-mark")
                    status_state_label = ui.label(status_state_text()).classes("audion-status-state")
                    status_label = ui.label(str(state["status"])).classes("audion-status-message")
                    status_clock = ui.label(elapsed_text(None)).classes("audion-status-clock")
                    with ui.element("div").classes("audion-status-bar"):
                        status_bar_fill = ui.element("i").style("width: 0%")
                    status_percent = ui.label(progress_text()).classes("audion-status-percent")

            with ui.column().classes("audion-terminal-panel w-full gap-2 p-3"):
                with ui.row().classes("audion-log-toolbar w-full items-center gap-2"):
                    section_heading("log", tr("log"), "text-base font-semibold")
                    ui.space()
                    add_tooltip(ui.button(tr("logs"), icon="article", on_click=lambda: open_folder(paths.logs)).props("dense flat").classes("audion-action rounded-lg"), tr("logs"), paths.logs)
                    add_tooltip(ui.button(tr("report"), icon="assessment", on_click=lambda: open_folder(paths.report)).props("dense flat").classes("audion-action rounded-lg"), tr("report"), paths.report)
                    add_tooltip(ui.button(tr("config"), icon="settings", on_click=lambda: open_folder(paths.config)).props("dense flat").classes("audion-action rounded-lg"), tr("config"), paths.config)
                    clear_log_button = ui.button(icon="delete_sweep", on_click=clear_terminal_log).props("dense flat round").classes("audion-action audion-log-icon-button")
                    add_tooltip(clear_log_button, audion_terminal_action_tooltip("clear_terminal_window"))
                    expand_log_button = ui.button(icon="open_in_full", on_click=lambda: log_dialog.open()).props("dense flat round").classes("audion-action audion-log-icon-button")
                    add_tooltip(expand_log_button, audion_terminal_action_tooltip("expand"))
                log_view = ui.html(terminal_shell_html("audion-terminal-main"), sanitize=False).classes("audion-terminal w-full min-h-[66vh]")
                with ui.row().classes("audion-terminal-footer w-full items-center gap-2 px-1 pt-1"):
                    status_dot = ui.label("●").classes(status_dot_classes())
                    terminal_status_label = ui.label(str(state["status"])).classes("min-w-0 flex-1 truncate text-xs")

    with ui.dialog() as log_dialog:
        with ui.card().classes("audion-dialog h-[92vh] w-[92vw] rounded-lg p-3"):
            with ui.row().classes("w-full items-center gap-2"):
                section_heading("log", tr("log"), "text-base font-semibold")
                ui.space()
                add_tooltip(ui.button(tr("config"), icon="settings", on_click=lambda: open_folder(paths.config)).props("dense flat").classes("audion-action rounded-lg"), tr("config"), paths.config)
                clear_expanded_log_button = ui.button(icon="delete_sweep", on_click=clear_terminal_log).props("dense flat round").classes("audion-action audion-log-icon-button")
                add_tooltip(clear_expanded_log_button, audion_terminal_action_tooltip("clear_terminal_window"))
                add_tooltip(ui.button(tr("close"), icon="close", on_click=log_dialog.close).props("dense flat").classes("audion-action rounded-lg"), tr("close"))
            expanded_log_view = ui.html(terminal_shell_html("audion-terminal-expanded"), sanitize=False).classes("audion-terminal audion-terminal-expanded w-full")

    ui.run_javascript(
        """
        (() => {
          const storageKey = 'audion_image_tools_terminal_width_px';
          const defaultWidth = 520;
          const legacyDefaultWidth = 640;
          const minLeft = 520;
          const minRight = 320;

          const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
          const storedOrDefault = () => {
            const saved = localStorage.getItem(storageKey);
            if (!saved || saved === String(legacyDefaultWidth)) return defaultWidth;
            return saved;
          };

          const applyWidth = (width) => {
            const shell = document.querySelector('.audion-shell');
            if (!shell) return;
            const rect = shell.getBoundingClientRect();
            const maxRight = Math.max(minRight, rect.width - minLeft - 40);
            const next = clamp(Number(width) || defaultWidth, minRight, maxRight);
            shell.style.setProperty('--audion-terminal-width', `${Math.round(next)}px`);
            localStorage.setItem(storageKey, String(Math.round(next)));
          };

          const setup = () => {
            const shell = document.querySelector('.audion-shell');
            const splitter = document.querySelector('.audion-splitter');
            if (!shell || !splitter) {
              setTimeout(setup, 80);
              return;
            }
            if (splitter.dataset.audionReady === '1') return;
            splitter.dataset.audionReady = '1';

            applyWidth(storedOrDefault());

            let dragging = false;
            const updateFromEvent = (event) => {
              if (!dragging) return;
              const rect = shell.getBoundingClientRect();
              const rightWidth = rect.right - event.clientX - 10;
              applyWidth(rightWidth);
            };

            splitter.addEventListener('pointerdown', (event) => {
              dragging = true;
              splitter.setPointerCapture?.(event.pointerId);
              document.body.classList.add('audion-resizing');
              event.preventDefault();
            });
            splitter.addEventListener('pointermove', updateFromEvent);
            splitter.addEventListener('pointerup', (event) => {
              dragging = false;
              splitter.releasePointerCapture?.(event.pointerId);
              document.body.classList.remove('audion-resizing');
            });
            splitter.addEventListener('pointercancel', () => {
              dragging = false;
              document.body.classList.remove('audion-resizing');
            });
            window.addEventListener('resize', () => applyWidth(storedOrDefault()));
          };

          setup();
        })();
        """
    )

    last_log_version = {"value": -1}
    rendered_line_serial = {"value": -1}
    rendered_terminal_reset = {"value": -1}

    refresh_timer: Any | None = None

    def update_terminal_dom(fragment: str, *, reset: bool = False, scroll_top: bool = False) -> None:
        payload = json.dumps(fragment, ensure_ascii=False)
        reset_payload = "true" if reset else "false"
        scroll_top_payload = "true" if scroll_top else "false"
        ui.run_javascript(
            f"""
            requestAnimationFrame(() => {{
              const html = {payload};
              const reset = {reset_payload};
              const scrollTop = {scroll_top_payload};
              const maxLines = {TERMINAL_HISTORY_LIMIT};
              document.querySelectorAll('.audion-terminal-content').forEach((pre) => {{
                const terminal = pre.closest('.audion-terminal') || pre;
                const selection = window.getSelection ? window.getSelection() : null;
                const selectingHere = selection && !selection.isCollapsed && (
                  terminal.contains(selection.anchorNode) || terminal.contains(selection.focusNode)
                );
                const distanceFromBottom = terminal.scrollHeight - terminal.scrollTop - terminal.clientHeight;
                const shouldScroll = distanceFromBottom <= 24 && !selectingHere;
                if (reset) {{
                  pre.innerHTML = '';
                }}
                if (html) {{
                  pre.insertAdjacentHTML('beforeend', html);
                }}
                while (pre.children.length > maxLines) {{
                  pre.removeChild(pre.firstElementChild);
                }}
                if (scrollTop) {{
                  terminal.scrollTop = 0;
                }} else if (shouldScroll) {{
                  terminal.scrollTop = terminal.scrollHeight;
                }}
              }});
            }});
            """
        )

    # Every one of these used to be written twice a second whether or not it had
    # changed, so an idle window still sent ten element updates a second. Holding
    # the last value makes an idle panel cost nothing and pays for the clock.
    shown = {"status": None, "state": None, "row": None, "clock": None, "percent": None, "fill": None}
    run_clock: dict[str, float | None] = {"started": None, "frozen": None}

    def refresh() -> None:
        nonlocal refresh_timer
        try:
            running = bool(state["running"])
            if running and run_clock["started"] is None:
                run_clock["started"] = time.monotonic()
                run_clock["frozen"] = None
            elif not running and run_clock["started"] is not None:
                run_clock["frozen"] = time.monotonic() - run_clock["started"]
                run_clock["started"] = None
            seconds = (
                time.monotonic() - run_clock["started"]
                if run_clock["started"] is not None
                else run_clock["frozen"]
            )

            def show(key: str, value: Any, assign: Any) -> None:
                if shown[key] != value:
                    shown[key] = value
                    assign(value)

            message = str(state["status"])
            show("status", message, lambda value: (
                setattr(status_label, "text", value),
                setattr(terminal_status_label, "text", value),
            ))
            show("state", status_state_text(), lambda value: setattr(status_state_label, "text", value))
            show("row", status_row_classes(), lambda value: (
                status_row.classes(replace=value),
                status_dot.classes(replace=status_dot_classes()),
            ))
            show("clock", elapsed_text(seconds), lambda value: setattr(status_clock, "text", value))
            show("percent", progress_text(), lambda value: setattr(status_percent, "text", value))
            show("fill", f"{float(state['progress']) * 100:.1f}%",
                 lambda value: status_bar_fill.style(f"width: {value}"))
            log_version = int(state["log_version"])
            if log_version != last_log_version["value"]:
                last_log_version["value"] = log_version
                line_serial = int(state.get("line_serial", 0))
                reset_id = int(state.get("terminal_reset_id", 0))
                previous_serial = int(rendered_line_serial["value"])
                lines = list(state["lines"])
                reset_terminal = reset_id != rendered_terminal_reset["value"] or previous_serial < 0 or line_serial < previous_serial
                append_count = line_serial - previous_serial if not reset_terminal else len(lines)
                if append_count > len(lines):
                    reset_terminal = True
                    append_count = len(lines)
                fragment_lines = lines if reset_terminal else lines[-max(0, append_count):]
                scroll_top = int(state.get("terminal_scroll_top_seq", 0)) and int(state.get("terminal_scroll_top_seq", 0)) <= line_serial
                if scroll_top:
                    state["terminal_scroll_top_seq"] = 0
                update_terminal_dom(terminal_lines_html(fragment_lines), reset=reset_terminal, scroll_top=bool(scroll_top))
                rendered_line_serial["value"] = line_serial
                rendered_terminal_reset["value"] = reset_id
            cancel_button.visible = bool(state["running"])
        except RuntimeError as exc:
            message = str(exc)
            if "slot belongs to has been deleted" not in message and "current slot cannot be determined" not in message:
                raise
            logging.warning("NiceGUI refresh timer stopped because the client slot was deleted.")
            if refresh_timer is not None:
                refresh_timer.deactivate()

    refresh_timer = ui.timer(0.5, refresh)


GUI_SMOKE_SERVICE_ONLY = {
    "system_core.services.image_tools_gui:cleanup_input_output",
    "system_core.services.image_tools_gui:run_doctor",
}

GUI_SMOKE_BESPOKE_FIELD_KEYS = {
    "system_core.services.image_tools_gui:run_photo_sheet": {
        "input_path",
        "output_path",
        "page_width_mm",
        "dpi",
        "gap_mm",
        "height_tolerance_mm",
        "recursive",
        "background",
        "to",
        "jpeg_quality",
    },
    "system_core.services.image_tools_gui:run_tile_sheet": {
        "input_path",
        "output_path",
        "paper",
        "orientation",
        "margin_mm",
        "gap_mm",
        "dpi",
        "to",
        "size_mode",
        "item_width_mm",
        "item_height_mm",
        "box_fit",
        "count_mode",
        "roll_count_mode",
        "copies",
        "rows",
        "roll_width_mm",
        "frame_mm",
        "frame_color",
        "background",
    },
    "system_core.services.image_tools_gui:run_plotter_dpi_only": {
        "input_path",
        "output_path",
        "dpi_preset",
        "dpi_custom",
        "to",
    },
}


def _leaf_command_nodes(nodes: list[CommandNode] | tuple[CommandNode, ...], path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], CommandNode]]:
    leaves: list[tuple[tuple[str, ...], CommandNode]] = []
    for node in nodes:
        node_path = (*path, node.id)
        if node.children:
            leaves.extend(_leaf_command_nodes(node.children, node_path))
        else:
            leaves.append((node_path, node))
    return leaves


def _gui_smoke_nodes() -> list[tuple[tuple[str, ...], CommandNode]]:
    if manifest.operation_groups:
        nodes = _leaf_command_nodes(tuple(manifest.operation_groups))
    else:
        nodes = [((operation.id,), operation_to_command_node(operation)) for operation in manifest.operations]
    nodes.extend(((operation.id,), operation_to_command_node(operation)) for operation in manifest.maintenance_operations)
    return nodes


def _smoke_field_state(node: CommandNode, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in node.fields:
        key = field_id(field)
        if key:
            values[key] = _smoke_field_default(field)
    values.update(overrides or {})
    return values


def _smoke_field_default(field: dict[str, Any]) -> Any:
    value = field_default(field)
    if not bool(field.get("required", False)) or not is_empty_field_value(value):
        return value
    kind = str(field.get("type", field.get("kind", "text"))).lower()
    options = _field_option_values(field)
    if is_checkbox_group(field):
        return [options[0]] if options else []
    if options:
        return options[0]
    if kind in {"number", "int", "integer", "quality", "quality_percent", "quality-percent"}:
        return field.get("min", 1)
    if kind == "checkbox":
        return True
    return "smoke"


def _operation_from_node_for_smoke(node: CommandNode, overrides: dict[str, Any] | None = None) -> Operation:
    previous_values = state.get("field_values", {})
    state["field_values"] = _smoke_field_state(node, overrides)
    try:
        if node.id in QUICK_RUN_COMMAND_IDS:
            return operation_from_quick_command(node)
        return operation_from_pending_command(node)
    finally:
        state["field_values"] = previous_values


def _visible_field_ids_for_smoke(node: CommandNode, overrides: dict[str, Any] | None = None) -> set[str]:
    previous_values = state.get("field_values", {})
    state["field_values"] = _smoke_field_state(node, overrides)
    try:
        visible: set[str] = set()
        for field in node.fields:
            key = field_id(field)
            if key and (is_workbench_route_field(field) or (field_is_visible(field) and not field_is_disabled(field))):
                visible.add(key)
        return visible
    finally:
        state["field_values"] = previous_values


def _generic_consumed_field_ids(operation: Operation) -> set[str]:
    params = dict(operation.parameters)
    consumed: set[str] = set()

    def add_condition_fields(condition: Any) -> None:
        if not isinstance(condition, dict):
            return
        for branch_key in ("all", "any"):
            if isinstance(condition.get(branch_key), list):
                for item in condition[branch_key]:
                    add_condition_fields(item)
        key = str(condition.get("field") or condition.get("id") or "").strip()
        if key:
            consumed.add(key)

    value_args = params.get("value_args", {})
    if isinstance(value_args, dict):
        consumed.update(str(value_key) for value_key in value_args.values())
    composite_args = params.get("composite_args", {})
    if isinstance(composite_args, dict):
        for spec in composite_args.values():
            if isinstance(spec, dict):
                field_key = str(spec.get("field") or spec.get("value_field") or "").strip()
                if field_key:
                    consumed.add(field_key)
                add_condition_fields(spec.get("custom_if") or spec.get("manual_if"))
                field_keys = spec.get("fields") or spec.get("parts") or []
                if isinstance(field_keys, list):
                    consumed.update(str(field_key) for field_key in field_keys)
            else:
                consumed.add(str(spec))
    flag_args = params.get("flag_args", {})
    if isinstance(flag_args, dict):
        consumed.update(str(value_key) for value_key in flag_args.values())
    multi_field = str(params.get("multi_field") or "").strip()
    if multi_field:
        consumed.add(multi_field)
    multi_output_key = str(params.get("multi_output_key") or "").strip()
    if multi_output_key:
        consumed.add(multi_output_key)
    if "output_file" in consumed:
        consumed.add("output_path")
    ui_only_fields = params.get("ui_only_fields", [])
    if isinstance(ui_only_fields, list):
        consumed.update(str(field_key) for field_key in ui_only_fields)
    consumed.update({"pdf_after_crop", "pdf_embed_mode", "pdf_output_file"})
    return consumed


def _consumed_field_ids_for_smoke(operation: Operation) -> set[str]:
    if operation.service == "system_core.services.image_tools_gui:run_manifest_cli":
        return _generic_consumed_field_ids(operation)
    return set(GUI_SMOKE_BESPOKE_FIELD_KEYS.get(operation.service, set()))


def _visibility_condition_overrides(condition: Any) -> dict[str, Any]:
    if not isinstance(condition, dict):
        return {}
    merged: dict[str, Any] = {}
    if isinstance(condition.get("all"), list):
        for item in condition["all"]:
            merged.update(_visibility_condition_overrides(item))
        return merged
    if isinstance(condition.get("any"), list) and condition["any"]:
        return _visibility_condition_overrides(condition["any"][0])
    key = str(condition.get("field") or condition.get("id") or "").strip()
    if not key:
        return {}
    if "equals" in condition:
        expected = condition["equals"]
        return {key: expected[0] if isinstance(expected, list) and expected else expected}
    if "in" in condition:
        expected_values = condition["in"]
        if isinstance(expected_values, list) and expected_values:
            return {key: expected_values[0]}
    return {}


def _visibility_overrides_for_field(field: dict[str, Any]) -> dict[str, Any]:
    overrides = _visibility_condition_overrides(field.get("visible_if"))
    visible_if_any = field.get("visible_if_any")
    if isinstance(visible_if_any, list) and visible_if_any:
        overrides.update(_visibility_condition_overrides(visible_if_any[0]))
    return overrides


def _field_option_values(field: dict[str, Any]) -> list[Any]:
    options = field.get("options", [])
    if not isinstance(options, list):
        return []
    return [option_value(option) for option in options]


def _smoke_variants_for_node(node: CommandNode) -> list[tuple[str, dict[str, Any]]]:
    variants: list[tuple[str, dict[str, Any]]] = [("defaults", {})]
    for field in node.fields:
        key = field_id(field)
        if not key:
            continue
        base = _visibility_overrides_for_field(field)
        values = _field_option_values(field)
        if is_checkbox_group(field):
            for value in values:
                variants.append((f"{key}={value}", {**base, key: [value]}))
        elif values:
            for value in values:
                variants.append((f"{key}={value}", {**base, key: value}))
        else:
            kind = str(field.get("type", field.get("kind", ""))).lower()
            if kind == "checkbox":
                variants.append((f"{key}=true", {**base, key: True}))
                variants.append((f"{key}=false", {**base, key: False}))
            elif kind in {"number", "int", "integer", "quality", "quality_percent", "quality-percent"}:
                step = field.get("step", 1)
                try:
                    integer_like = float(step).is_integer()
                except (TypeError, ValueError):
                    integer_like = True
                if integer_like:
                    value = field_default(field)
                    if is_empty_field_value(value):
                        value = field.get("min", 1)
                    try:
                        variants.append((f"{key}=float-int", {**base, key: float(value)}))
                    except (TypeError, ValueError):
                        pass

    fields_by_id = {field_id(field): field for field in node.fields if field_id(field)}
    pdf_embed_field = fields_by_id.get("pdf_embed_mode")
    if "pdf_after_crop" in fields_by_id and pdf_embed_field:
        for value in _field_option_values(pdf_embed_field):
            variants.append((f"pdf_after_crop+pdf_embed_mode={value}", {"pdf_after_crop": True, "pdf_embed_mode": value}))

    seen: set[str] = set()
    unique: list[tuple[str, dict[str, Any]]] = []
    for label, overrides in variants:
        signature = json.dumps(overrides, ensure_ascii=False, sort_keys=True, default=str)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append((label, overrides))
    return unique


def _cli_args_for_smoke(operation: Operation) -> list[list[str]]:
    from system_core.services import image_tools_gui

    if operation.service == "system_core.services.image_tools_gui:run_manifest_cli":
        return image_tools_gui.build_manifest_cli_args(paths.root, operation)
    if operation.service == "system_core.services.image_tools_gui:run_cli_command":
        return [image_tools_gui.build_cli_command_args(paths.root, operation)]
    if operation.service == "system_core.services.image_tools_gui:run_photo_sheet":
        return [image_tools_gui.build_photo_sheet_cli_args(paths.root, operation)]
    if operation.service == "system_core.services.image_tools_gui:run_tile_sheet":
        return [image_tools_gui.build_tile_sheet_cli_args(paths.root, operation)]
    if operation.service == "system_core.services.image_tools_gui:run_plotter_dpi_only":
        return [image_tools_gui.build_plotter_dpi_only_cli_args(paths.root, operation)]
    if operation.service in GUI_SMOKE_SERVICE_ONLY:
        return []
    raise RuntimeError(f"No GUI smoke argv builder for service: {operation.service}")


def _parse_main_cli_args(parser: argparse.ArgumentParser, args: list[str]) -> tuple[bool, str]:
    argv = [str(part) for part in args[2:]]
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            parser.parse_args(argv)
    except SystemExit as exc:
        detail = stderr.getvalue().strip() or f"argparse exited with {exc.code}"
        return False, f"{' '.join(argv)} -> {detail}"
    return True, " ".join(argv)


def run_gui_smoke() -> int:
    from system_core.main import build_parser as build_main_parser

    parser = build_main_parser()
    failures: list[str] = []
    variant_count = 0
    argv_count = 0
    skipped_count = 0

    for node_path, node in _gui_smoke_nodes():
        path_label = " / ".join(node_path)
        for variant_label, overrides in _smoke_variants_for_node(node):
            variant_count += 1
            try:
                operation = _operation_from_node_for_smoke(node, overrides)
                visible_fields = _visible_field_ids_for_smoke(node, overrides)
                consumed_fields = _consumed_field_ids_for_smoke(operation)
                unhandled_fields = sorted(visible_fields - consumed_fields)
                if unhandled_fields:
                    failures.append(f"{path_label} [{variant_label}] has unhandled GUI fields: {', '.join(unhandled_fields)}")

                cli_args_list = _cli_args_for_smoke(operation)
            except Exception as exc:
                failures.append(f"{path_label} [{variant_label}] failed to assemble argv: {exc.__class__.__name__}: {exc}")
                continue

            if not cli_args_list:
                skipped_count += 1
                continue

            for cli_args in cli_args_list:
                ok, detail = _parse_main_cli_args(parser, cli_args)
                argv_count += 1
                if not ok:
                    failures.append(f"{path_label} [{variant_label}] parser rejected argv: {detail}")

    if failures:
        print("FAIL GUI smoke:")
        for failure in failures[:80]:
            print(f"  - {failure}")
        if len(failures) > 80:
            print(f"  - ... {len(failures) - 80} more failure(s)")
        return 1

    print(
        f"OK GUI smoke: {variant_count} GUI state(s), "
        f"{argv_count} main.py argv check(s), {skipped_count} service-only state(s) skipped."
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audion NiceGUI shell.")
    parser.add_argument("--host", default=str(ui_info.get("host", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=int(ui_info.get("port", 8080)))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args()


def port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def build_ui_once() -> dict[str, int]:
    """Build the whole page once, headlessly, and report what came of it.

    `--smoke` used to print a line and return, so an app could ship a `build_ui`
    that raised on its first statement and still pass — twice in this fleet it did.
    Here the page is actually built: no browser and no HTTP request, so whatever
    the app defers until a client attaches is skipped, but every widget is
    constructed and the stylesheet has to arrive.
    """
    import asyncio
    import logging
    import re

    from nicegui import core
    from nicegui.client import Client
    from nicegui.page import page as page_definition

    async def build() -> tuple[int, str]:
        core.loop = asyncio.get_running_loop()
        # Work deferred to a connected browser fails here and says nothing about
        # the build. An exception raised by build_ui itself still propagates.
        core.loop.set_exception_handler(lambda _loop, _context: None)
        logging.getLogger("nicegui").setLevel(logging.CRITICAL)
        client = Client(page_definition("/__smoke__"))
        with client:
            build_ui()
        report = len(client.elements), client.shared_head_html + client.head_html
        # The page starts work that waits for a browser to attach. Nothing will
        # attach, so stop it deliberately instead of letting the loop close on it.
        pending = asyncio.all_tasks(core.loop) - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return report

    element_count, head = asyncio.run(build())
    if element_count < 2:
        raise RuntimeError("build_ui produced no widgets")
    # Token prefixes differ between apps, so look for any custom property rather
    # than for one project's naming.
    if not re.search(r"--[\w-]+\s*:", head):
        raise RuntimeError("the stylesheet never reached the page")
    return {"elements": element_count, "stylesheet_bytes": len(head)}


def main() -> int:
    args = parse_args()
    ensure_project_dirs(paths)
    if args.smoke:
        try:
            report = build_ui_once()
        except Exception as error:  # noqa: BLE001
            print(f"FAIL nicegui shell: {ROOT}: {error}")
            return 1
        print(
            f"OK nicegui build: {ROOT}"
            f" | widgets={report['elements']}"
            f" | stylesheet={report['stylesheet_bytes']} bytes"
        )
        return run_gui_smoke()

    if port_is_open(args.host, args.port):
        url = f"http://{args.host}:{args.port}/"
        print(f"GUI already appears to be running: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    ui.run(
        root=build_ui,
        title=app_title(),
        host=args.host,
        port=args.port,
        reload=False,
        native=False,
        show=not args.no_browser,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
