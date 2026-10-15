from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from system_core.core.lines import paint
from system_core.core.jobs import (
    JobContext,
    UserFacingError,
    decoded_process_lines,
    hidden_subprocess_kwargs,
    is_python_command,
    unbuffer_python_command,
    utf8_subprocess_env,
)
from system_core.image_tools.photo_sheet import load_photo_sheet_config, mode_config


# What a run that was stopped before its engine started answers with: the code a console gives a stopped command.
STOPPED_EXIT_CODE = 130
PARALLEL_SETTINGS_FILE = 'parallel_settings.json'
DEFAULT_PARALLEL_SETTINGS = {
    'parallel_enabled': False,
    'worker_count': 8,
}


def _console_python(root: Path) -> str:
    candidates = [
        root / 'runtime' / 'python.exe',
        root / 'runtime' / 'python' / 'python.exe',
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    executable = Path(sys.executable)
    if executable.name.lower() == 'pythonw.exe':
        sibling = executable.with_name('python.exe')
        if sibling.exists():
            return str(sibling)

    return sys.executable


def _main_cli_prefix(root: Path) -> list[str]:
    return [_console_python(root), str(root / 'system_core' / 'main.py')]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _as_float(value: Any, default: float) -> float:
    if value is None or value == '':
        return default
    return float(str(value).replace(',', '.'))


def _as_int(value: Any, default: int) -> int:
    if value is None or value == '':
        return default
    return int(float(str(value).replace(',', '.')))


def _parallel_settings_path(root: Path) -> Path:
    return root / 'config' / PARALLEL_SETTINGS_FILE


def _normalize_parallel_settings(values: dict[str, Any]) -> dict[str, Any]:
    enabled = _as_bool(values.get('parallel_enabled', values.get('global_parallel_enabled', False)))
    workers = max(1, min(24, _as_int(values.get('worker_count', values.get('global_worker_count')), 8)))
    return {'parallel_enabled': enabled, 'worker_count': workers}


def _load_parallel_settings(root: Path) -> dict[str, Any]:
    path = _parallel_settings_path(root)
    if not path.exists():
        return dict(DEFAULT_PARALLEL_SETTINGS)
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_PARALLEL_SETTINGS)
    if not isinstance(raw, dict):
        return dict(DEFAULT_PARALLEL_SETTINGS)
    return _normalize_parallel_settings(raw)


def _append_parallel_args(args: list[str], values: dict[str, Any], root: Path | None = None) -> None:
    if _as_bool(values.get('parallel_enabled')):
        workers = max(1, min(24, _as_int(values.get('worker_count'), 8)))
    elif root is not None:
        global_settings = _load_parallel_settings(root)
        if not _as_bool(global_settings.get('parallel_enabled')):
            return
        workers = max(1, min(24, _as_int(global_settings.get('worker_count'), 8)))
    else:
        return
    args.extend(['--workers', str(workers)])


def _values_condition_matches(values: dict[str, Any], condition: Any) -> bool:
    if not isinstance(condition, dict):
        return False
    if isinstance(condition.get('all'), list):
        return all(_values_condition_matches(values, item) for item in condition['all'])
    if isinstance(condition.get('any'), list):
        return any(_values_condition_matches(values, item) for item in condition['any'])
    key = str(condition.get('field') or condition.get('id') or '').strip()
    if not key:
        return False
    actual = values.get(key)
    if 'equals' in condition:
        expected = condition.get('equals')
        expected_values = expected if isinstance(expected, list) else [expected]
        return actual in expected_values
    if 'in' in condition:
        expected_values = condition.get('in')
        return isinstance(expected_values, list) and actual in expected_values
    if 'not_equals' in condition:
        blocked = condition.get('not_equals')
        blocked_values = blocked if isinstance(blocked, list) else [blocked]
        return actual not in blocked_values
    return False


def _clean_path_value(value: Any) -> str:
    return str(value or '').strip()


def _output_file_inside_folder(folder: str, current_file: Any) -> str:
    current_path = Path(str(current_file or 'output/result'))
    filename = current_path.name or 'result'
    return str(Path(folder) / filename)


def _pdf_output_for_folder(folder: Any) -> str:
    output_path = Path(str(folder or 'output/result').strip() or 'output/result')
    if output_path.suffix.lower() == '.pdf':
        return str(output_path)
    if output_path.suffix:
        return str(output_path.with_suffix('.pdf'))
    return str(output_path.parent / f'{output_path.name}.pdf')


def _pdf_after_mode(value: Any) -> str:
    mode = str(value or 'png_embedded').strip().lower()
    if mode in {'jpg75_embedded', 'jpg75', 'jpg_75', 'jpeg75'}:
        return 'jpg75'
    return 'lossless'


def _build_pdf_after_crop_args(root: Path, operation_id: str, values: dict[str, Any]) -> list[list[str]]:
    if not _as_bool(values.get('pdf_after_crop')):
        return []

    crop_output = str(values.get('output_path') or 'output').strip() or 'output'
    pdf_mode_value = str(values.get('pdf_embed_mode') or 'png_embedded').strip().lower()
    pdf_cli_mode = _pdf_after_mode(pdf_mode_value)
    pdf_source = crop_output
    pdf_output = _pdf_output_for_folder(values.get('pdf_output_file') or crop_output)
    prefix = _main_cli_prefix(root)
    args: list[list[str]] = []

    if pdf_cli_mode == 'lossless' and str(values.get('to') or '').lower() != 'png':
        workspace_source = root / 'workspace' / 'pdf_after_crop' / str(operation_id)
        args.append([
            *prefix,
            'convert',
            '--input',
            crop_output,
            '--output',
            str(workspace_source),
            '--to',
            'png',
        ])
        pdf_source = str(workspace_source)

    args.append([
        *prefix,
        'images-to-pdf',
        '--input',
        pdf_source,
        '--output',
        pdf_output,
        '--mode',
        pdf_cli_mode,
    ])
    return args


def _run_pdf_after_crop(context: JobContext, values: dict[str, Any]) -> None:
    post_args = _build_pdf_after_crop_args(context.paths.root, str(context.operation.id), values)
    for args in post_args:
        command = args[2] if len(args) > 2 else ''
        if command == 'convert':
            workspace_source = context.paths.workspace / 'pdf_after_crop' / str(context.operation.id)
            if workspace_source.exists():
                shutil.rmtree(workspace_source)
            workspace_source.mkdir(parents=True, exist_ok=True)
            context.log('Preparing PNG source for PDF...')
        elif command == 'images-to-pdf':
            context.log('Building PDF after crop...')
        exit_code = _run_cli(context, args)
        if exit_code != 0:
            if command == 'convert':
                raise RuntimeError(f'PDF PNG source conversion failed with exit code {exit_code}')
            raise RuntimeError(f'PDF export after crop failed with exit code {exit_code}')


def _resolve_photo_sheet_settings_from_params(root: Path, params: dict[str, Any]) -> dict[str, Any]:
    mode_name = str(params.get('config_mode') or 'paper_saver')
    config_path = root / str(params.get('config') or 'config/photo_sheet.yaml')
    config = load_photo_sheet_config(config_path)
    settings = mode_config(config, mode_name)

    if 'page_width_mm' in params:
        settings['page_width_mm'] = _as_float(params.get('page_width_mm'), float(settings['page_width_mm']))
    if 'dpi' in params:
        settings['dpi'] = _as_int(params.get('dpi'), int(settings['dpi']))
    if 'gap_mm' in params:
        settings['gap_mm'] = _as_float(params.get('gap_mm'), float(settings['gap_mm']))
    if 'height_tolerance_mm' in params:
        settings['height_tolerance_mm'] = _as_float(params.get('height_tolerance_mm'), float(settings['height_tolerance_mm']))
    if 'recursive' in params:
        settings['recursive'] = _as_bool(params.get('recursive'))
    if params.get('background'):
        settings['background'] = str(params['background'])
    if params.get('to'):
        settings['to'] = str(params['to'])
    if 'jpeg_quality' in params:
        settings['jpeg_quality'] = _as_int(params.get('jpeg_quality'), int(settings.get('jpeg_quality') or 90))
    if _clean_path_value(params.get('input_path')):
        settings['input'] = _clean_path_value(params.get('input_path'))
    if _clean_path_value(params.get('output_path')):
        settings['output'] = _clean_path_value(params.get('output_path'))

    return settings


def _resolve_photo_sheet_settings(context: JobContext) -> dict[str, Any]:
    return _resolve_photo_sheet_settings_from_params(context.paths.root, dict(context.operation.parameters))


def _resolved_output_dir(root: Path, value: Any) -> Path:
    output_dir = Path(str(value or 'output'))
    return output_dir if output_dir.is_absolute() else root / output_dir


def _photo_sheet_validation_message(settings: dict[str, Any], summary: dict[str, Any]) -> str:
    page_width = _as_float(summary.get('page_width_mm'), _as_float(settings.get('page_width_mm'), 0.0))
    required = _as_float(summary.get('required_page_width_mm'), 0.0)
    unplaced = _as_int(summary.get('unplaced'), 0)
    if required > 0:
        return (
            f'Ширина листа {page_width:g} мм меньше нужной. '
            f'Требуется лист более {required:.3f} мм. '
            f'Не размещено файлов: {unplaced}.'
        )
    return 'Не удалось разместить изображения на листе. Проверьте ширину листа, DPI и режим размера.'


def _raise_photo_sheet_validation_error(context: JobContext, settings: dict[str, Any], exit_code: int) -> None:
    summary_path = _resolved_output_dir(context.paths.root, settings.get('output')) / 'layout_summary.json'
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
        except Exception:
            summary = {}
        if summary.get('error_code') == 'page_width_too_small' or summary.get('unplaced_reason') == 'page_width_too_small':
            raise UserFacingError(_photo_sheet_validation_message(settings, summary), summary)
    raise RuntimeError(f'photo-sheet-width failed with exit code {exit_code}')


def _read_photo_sheet_summary(root: Path, settings: dict[str, Any]) -> dict[str, Any]:
    summary_path = _resolved_output_dir(root, settings.get('output')) / 'layout_summary.json'
    if not summary_path.exists():
        return {}
    try:
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return summary if isinstance(summary, dict) else {}


def _run_cli(context: JobContext, args: list[str]) -> int:
    args = unbuffer_python_command(args)
    use_python_text_stream = is_python_command(args)
    context.log(paint('Command:', 'muted'))
    context.log(paint(' '.join(f'"{part}"' if ' ' in str(part) else str(part) for part in args), 'muted'))

    # A stop asked for before the engine is started: there is nothing to end, and nothing is begun.
    if context.cancelled():
        context.log(paint('Stop requested: the engine is not started.', 'warn'))
        return STOPPED_EXIT_CODE

    # Python speaks UTF-8 text; another tool of Windows is read as bytes and decoded line by line.
    as_text = {'text': True, 'encoding': 'utf-8', 'errors': 'replace'} if use_python_text_stream else {}
    process = subprocess.Popen(
        args,
        cwd=str(context.paths.root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=utf8_subprocess_env(),
        **as_text,
        **hidden_subprocess_kwargs(),
    )
    assert process.stdout is not None

    # The output is read aside, so that a stop is seen while the engine is silent. Until 3.0.0 the
    # stop was looked at only after a line of output: an engine busy with one large file went on
    # to its end, and the window showed the stop as an error.
    lines: queue.Queue = queue.Queue()

    def read() -> None:
        try:
            for raw_line in process.stdout:
                lines.put(raw_line)
        finally:
            lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    stopping = False
    while True:
        try:
            raw_line = lines.get(timeout=0.25)
        except queue.Empty:
            raw_line = ''
        if raw_line is None:
            break
        if raw_line:
            for line in decoded_process_lines(raw_line):
                context.log(line)
        if not stopping and context.cancelled() and process.poll() is None:
            context.log(paint('Stop requested: ending the engine...', 'warn'))
            process.terminate()
            stopping = True

    code = process.wait()
    if stopping:
        _clear_parts(args)
    return code


def _clear_parts(args: list[str]) -> None:
    """The copies an ended engine left half written beside their places - `*.writing`, the suffix every writer of the
    engine gives them before a copy takes its place - taken out of the Target: a stop leaves what lay there before and
    what was done, nothing half made."""
    if '--output' not in args or args.index('--output') + 1 >= len(args):
        return
    target = Path(args[args.index('--output') + 1])
    folder = target if target.is_dir() else target.parent
    try:
        for part in folder.rglob('*.writing*'):
            # `doc.docx.writing` of a document, `photo.writing.jpg` of a picture (io_utils.written_whole).
            if part.is_file() and (part.name.endswith('.writing') or '.writing.' in part.name):
                part.unlink(missing_ok=True)
    except OSError:
        pass


def build_photo_sheet_cli_args(root: Path, operation: Any) -> list[str]:
    settings = _resolve_photo_sheet_settings_from_params(root, dict(operation.parameters))
    args = [
        *_main_cli_prefix(root),
        'photo-sheet-width',
        '--input',
        str(settings['input']),
        '--output',
        str(settings['output']),
        '--to',
        str(settings.get('to') or 'png'),
        '--jpeg-quality',
        str(settings.get('jpeg_quality') or 90),
        '--page-width-mm',
        str(settings['page_width_mm']),
        '--dpi',
        str(settings['dpi']),
        '--gap-mm',
        str(settings['gap_mm']),
        '--size-source',
        str(settings['size_source']),
        '--layout',
        str(settings['layout']),
        '--height-tolerance-mm',
        str(settings['height_tolerance_mm']),
        '--background',
        str(settings['background']),
        '--preview-width-px',
        str(settings['preview_width_px']),
    ]
    if _as_bool(settings.get('recursive')):
        args.append('--recursive')
    _append_parallel_args(args, dict(operation.parameters), root)
    return args


def run_photo_sheet(context: JobContext) -> dict[str, Any]:
    settings = _resolve_photo_sheet_settings(context)
    args = build_photo_sheet_cli_args(context.paths.root, context.operation)
    context.progress(0.05)
    exit_code = _run_cli(context, args)
    context.progress(1.0)
    if exit_code != 0:
        _raise_photo_sheet_validation_error(context, settings, exit_code)
    return {
        'mode': context.operation.parameters.get('config_mode'),
        'settings': settings,
        **_read_photo_sheet_summary(context.paths.root, settings),
    }


def _tile_sheet_values(operation: Any) -> dict[str, Any]:
    params = dict(operation.parameters)
    defaults = params.get('defaults') if isinstance(params.get('defaults'), dict) else {}
    return {**defaults, **params}


def _given(values: dict[str, Any], key: str, fallback: Any) -> Any:
    """The value of a field, a nought among them; the fallback only for a field left empty.

    `values.get(key) or fallback` turned a margin of 0 into 7 and 0 rows into 1, though the
    manifest allows both (the inventory of the former window, 12.7).
    """
    value = values.get(key)
    return fallback if value in (None, '') else value


def build_tile_sheet_cli_args(root: Path, operation: Any) -> list[str]:
    values = _tile_sheet_values(operation)
    paper = str(values.get('paper') or 'a4').lower()
    count_mode = str(values.get('roll_count_mode') if paper == 'roll' else values.get('count_mode') or 'fill').lower()

    args = [
        *_main_cli_prefix(root),
        'tile-sheet',
        '--input',
        str(values.get('input_path') or 'input'),
        '--output',
        str(values.get('output_path') or 'output/tile_sheet'),
        '--paper',
        paper,
        '--orientation',
        str(values.get('orientation') or 'portrait'),
        '--margin-mm',
        str(_given(values, 'margin_mm', 7)),
        '--gap-mm',
        str(_given(values, 'gap_mm', 0)),
        '--dpi',
        str(values.get('dpi') or 300),
        '--to',
        str(values.get('to') or 'tiff'),
        '--size-mode',
        str(values.get('size_mode') or 'source'),
        '--item-width-mm',
        str(values.get('item_width_mm') or 40),
        '--item-height-mm',
        str(values.get('item_height_mm') or 30),
        '--box-fit',
        str(values.get('box_fit') or 'contain'),
        '--count-mode',
        count_mode,
        '--copies',
        str(_given(values, 'copies', 0)),
        '--rows',
        str(_given(values, 'rows', 1)),
        '--frame-mm',
        str(values.get('frame_mm') if values.get('frame_mm') not in {None, ''} else 0.2),
        '--frame-color',
        str(values.get('frame_color') or '#999999'),
        '--background',
        str(values.get('background') or 'white'),
    ]
    if paper == 'roll':
        args.extend(['--roll-width-mm', str(values.get('roll_width_mm') or 600)])
    _append_parallel_args(args, values, root)
    return args


def run_tile_sheet(context: JobContext) -> dict[str, Any]:
    values = _tile_sheet_values(context.operation)
    paper = str(values.get('paper') or 'a4').lower()
    count_mode = str(values.get('roll_count_mode') if paper == 'roll' else values.get('count_mode') or 'fill').lower()
    args = build_tile_sheet_cli_args(context.paths.root, context.operation)
    context.progress(0.05)
    exit_code = _run_cli(context, args)
    context.progress(1.0)
    if exit_code != 0:
        raise RuntimeError(f'tile-sheet failed with exit code {exit_code}')
    return {'paper': paper, 'count_mode': count_mode}


def build_cli_command_args(root: Path, operation: Any) -> list[str]:
    cli_args = operation.parameters.get('args')
    if not isinstance(cli_args, list):
        raise RuntimeError('GUI operation must provide parameters.args as a list.')
    return [*_main_cli_prefix(root), *map(str, cli_args)]


def run_cli_command(context: JobContext) -> dict[str, Any]:
    cli_args = context.operation.parameters.get('args')
    args = build_cli_command_args(context.paths.root, context.operation)
    context.progress(0.1)
    exit_code = _run_cli(context, args)
    context.progress(1.0)
    if exit_code != 0:
        raise RuntimeError(f'CLI command failed with exit code {exit_code}')
    return {'args': cli_args}


def _manifest_cli_runs(root: Path, operation: Any) -> list[tuple[list[str], dict[str, Any]]]:
    params = dict(operation.parameters)
    defaults = params.get('defaults') if isinstance(params.get('defaults'), dict) else {}
    values = {**defaults, **params}
    output_folder_override = _clean_path_value(params.get('output_path'))
    if output_folder_override and _clean_path_value(values.get('output_file')):
        values['output_file'] = _output_file_inside_folder(output_folder_override, values.get('output_file'))

    fixed_args = values.get('fixed_args')
    if not isinstance(fixed_args, list):
        raise RuntimeError('GUI CLI operation must provide parameters.fixed_args as a list.')

    multi_field = str(values.get('multi_field') or '')
    if multi_field and isinstance(values.get(multi_field), list):
        selected_values = list(values.get(multi_field) or [])
    else:
        selected_values = [None]

    if not selected_values:
        raise RuntimeError(f'No values selected for {multi_field}.')

    runs: list[tuple[list[str], dict[str, Any]]] = []
    for selected_value in selected_values:
        run_values = dict(values)
        if selected_value is not None:
            run_values[multi_field] = selected_value
            output_key = str(run_values.get('multi_output_key') or 'output_path')
            output_value = run_values.get(output_key)
            if output_value:
                output_path = Path(str(output_value))
                suffix = str(selected_value).replace('/', '_').replace('\\', '_')
                if output_path.suffix:
                    run_values[output_key] = str(output_path.parent / suffix / output_path.name)
                else:
                    run_values[output_key] = str(output_path / suffix)

        args = [*_main_cli_prefix(root), *map(str, fixed_args)]

        value_args = run_values.get('value_args', {})
        if isinstance(value_args, dict):
            for option, value_key in value_args.items():
                value = run_values.get(str(value_key), '')
                # A list of ticks that is not run one value at a time (multi_field) goes as one word: "docx,pdf".
                if isinstance(value, (list, tuple)):
                    value = ','.join(str(item) for item in value)
                if value is None or value == '':
                    continue
                args.extend([str(option), str(value)])

        composite_args = run_values.get('composite_args', {})
        if isinstance(composite_args, dict):
            for option, spec in composite_args.items():
                value = ''
                if isinstance(spec, dict):
                    use_parts = _values_condition_matches(run_values, spec.get('custom_if') or spec.get('manual_if'))
                    field_key = str(spec.get('field') or spec.get('value_field') or '').strip()
                    field_value = run_values.get(field_key, '') if field_key else ''
                    custom_values = spec.get('custom_values') or spec.get('manual_values') or []
                    if not isinstance(custom_values, list):
                        custom_values = [custom_values]
                    if not use_parts and field_key and field_value not in custom_values and field_value not in {None, ''}:
                        value = str(field_value)
                    if value:
                        args.extend([str(option), str(value)])
                        continue

                    field_keys = spec.get('fields') or spec.get('parts') or []
                    separator = str(spec.get('separator', ''))
                    if not isinstance(field_keys, list):
                        continue
                    parts: list[str] = []
                    missing_part = False
                    for field_key in field_keys:
                        part = run_values.get(str(field_key), '')
                        if part is None or part == '':
                            missing_part = True
                            break
                        parts.append(str(part))
                    if missing_part:
                        continue
                    value = separator.join(parts)
                else:
                    value = run_values.get(str(spec), '')
                if value is None or value == '':
                    continue
                args.extend([str(option), str(value)])

        flag_args = run_values.get('flag_args', {})
        if isinstance(flag_args, dict):
            for option, value_key in flag_args.items():
                if _as_bool(run_values.get(str(value_key))):
                    args.append(str(option))

        _append_parallel_args(args, run_values, root)
        runs.append((args, run_values))

    return runs


def run_manifest_cli(context: JobContext) -> dict[str, Any]:
    runs = _manifest_cli_runs(context.paths.root, context.operation)
    exit_codes: list[int] = []
    for index, (args, run_values) in enumerate(runs, start=1):
        # The engine once for every format ticked: the runs are parted by this line, a single run is not.
        context.log(paint(f'Run {index}/{len(runs)}', 'head' if len(runs) > 1 else 'muted'))
        context.progress(max(0.05, (index - 1) / max(1, len(runs))))
        exit_code = _run_cli(context, args)
        exit_codes.append(exit_code)
        if exit_code != 0:
            raise RuntimeError(f'CLI command failed with exit code {exit_code}')
        context.progress(max(0.05, index / max(1, len(runs))) * 0.75)
        _run_pdf_after_crop(context, run_values)

    context.progress(1.0)
    return {'runs': len(runs), 'exit_codes': exit_codes}


def run_documents_cli(context: JobContext) -> dict[str, Any]:
    """An operation over the pictures inside documents: the command of the manifest, told where its report goes."""
    runs = _manifest_cli_runs(context.paths.root, context.operation)
    exit_codes: list[int] = []
    for index, (args, _run_values) in enumerate(runs, start=1):
        context.progress(max(0.05, (index - 1) / max(1, len(runs))))
        exit_code = _run_cli(context, [*args, '--report-dir', str(context.report_dir)])
        exit_codes.append(exit_code)
        if exit_code != 0:
            raise RuntimeError(f'CLI command failed with exit code {exit_code}: the reason is in the journal and in {context.report_dir}')
    context.progress(1.0)
    return {'runs': len(runs), 'exit_codes': exit_codes, 'report': str(context.report_dir)}


def _plotter_dpi_only_values(operation: Any) -> dict[str, Any]:
    params = dict(operation.parameters)
    defaults = params.get('defaults') if isinstance(params.get('defaults'), dict) else {}
    return {**defaults, **params}


def _plotter_dpi_from_values(values: dict[str, Any]) -> int:
    preset = str(values.get('dpi_preset') or values.get('dpi') or '300').lower()
    if preset in {'custom', 'manual', 'other'}:
        dpi = _as_int(values.get('dpi_custom'), 300)
    else:
        dpi = _as_int(preset, 300)
    if dpi <= 0:
        raise RuntimeError('DPI must be greater than zero.')
    return dpi


def build_plotter_dpi_only_cli_args(root: Path, operation: Any) -> list[str]:
    values = _plotter_dpi_only_values(operation)
    dpi = _plotter_dpi_from_values(values)
    args = [
        *_main_cli_prefix(root),
        'plotter-dpi-only',
        '--input',
        str(values.get('input_path') or 'input'),
        '--output',
        str(values.get('output_path') or 'output/plotter_dpi_only'),
        '--to',
        str(values.get('to') or 'png'),
        '--dpi',
        str(dpi),
    ]
    _append_parallel_args(args, values, root)
    return args


def run_plotter_dpi_only(context: JobContext) -> dict[str, Any]:
    values = _plotter_dpi_only_values(context.operation)
    dpi = _plotter_dpi_from_values(values)
    args = build_plotter_dpi_only_cli_args(context.paths.root, context.operation)
    context.progress(0.05)
    exit_code = _run_cli(context, args)
    context.progress(1.0)
    if exit_code != 0:
        raise RuntimeError(f'plotter-dpi-only failed with exit code {exit_code}')
    return {'dpi': dpi}


def run_doctor(context: JobContext) -> dict[str, Any]:
    args = [_console_python(context.paths.root), str(context.paths.system_core / 'doctor.py')]
    context.progress(0.1)
    exit_code = _run_cli(context, args)
    context.progress(1.0)
    if exit_code != 0:
        raise RuntimeError(f'Doctor failed with exit code {exit_code}')
    return {'script': 'doctor.py'}

