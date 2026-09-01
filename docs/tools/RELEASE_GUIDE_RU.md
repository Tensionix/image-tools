# Релизная подготовка

## Быстрая проверка

Из корня проекта:

```bat
runtime\python.exe -m py_compile system_core\main.py system_core\image_tools\commands.py system_core\image_tools\pipeline.py system_core\services\image_tools_gui.py system_core\ui_nicegui\app.py system_core\ui_nicegui\window.py
```

Проверить окружение:

```bat
runtime\python.exe system_core\doctor.py
```

Проверить GUI smoke:

```bat
runtime\python.exe system_core\ui_nicegui\app.py --smoke
```

Проверить новые CLI-поверхности перед архивом:

```bat
runtime\python.exe system_core\main.py trim-border --help
runtime\python.exe system_core\main.py smart-crop-white --help
runtime\python.exe system_core\main.py images-to-pdf --help
```

## Очистка

`cleanup_project.cmd` - интерактивный CMD-скрипт для финальной чистки проекта перед пересборкой или упаковкой.
Он показывает список очищаемых зон и спрашивает подтверждение `Y/N/Q`.

Команда:

```bat
cleanup_project.cmd
```

Что очищается после ответа `Y`:

- содержимое `input\`, `output\`, `logs\`, `report\`, `workspace\`, `data\`, `release\`;
- содержимое `runtime\`, `wheelhouse\`, `install\download\`;
- все папки `.runtime\`, `_runtime\`, `._runtime\`, `__pycache__`;
- содержимое `system_core\powershell\`;
- `system_core\fzf.exe`;
- `licenses\licenses.zip`;
- generated-файлы `*.pyc`, `*.pyo`, `*.tmp`, `*.bak`, `*.log`, `Thumbs.db`, `desktop.ini`.

Что не трогается:

- `config\`
- `docs\`
- `GitHub\`
- `licenses\`, кроме генерируемого `licenses\licenses.zip`
- `install\`, кроме `install\download\`
- `system_core\`, кроме `system_core\fzf.exe` и содержимого `system_core\powershell\`
- launchers и CMD-скрипты
- `cleanup_project.cmd`

После чистки скрипт вызывает `install\init_folders.cmd`, чтобы вернуть актуальный набор пустых рабочих папок.

## Релизный порядок

1. Закрыть GUI и все терминалы, которые держат файлы проекта.
2. Запустить `runtime\python.exe system_core\doctor.py`.
3. Запустить `cleanup_project.cmd` и подтвердить `Y`, если список удаления выглядит правильно.
4. При необходимости заново собрать portable runtime и wheelhouse.
5. Запустить релизный сборщик из `launcher_tools.cmd` или `install\make_release_archive.cmd`.
6. После сборки проверить архив на наличие:
   - `launcher_gui.cmd`
   - `launcher_project_ru.cmd`
   - `config\tool_manifest.yaml`
   - `config\photo_sheet.yaml`
   - `config\gui_settings.yaml`
   - `config\ui_colors.yaml`
   - `runtime\python.exe`
   - `system_core\main.py`
   - `docs\USER_GUIDE_RU.md`
   - `docs\GUI_UI_LANGUAGE_THEME_RU.md`
   - `AGENTS.md`

## Важные правила

- `cleanup_project.cmd` используется перед релизной пересборкой и удаляет содержимое `runtime\`, `wheelhouse\`, рабочих папок и release-артефактов.
- Не запускать `cleanup_project.cmd`, если нужно сохранить уже собранное portable-окружение.
- Не запускать `cleanup_project.cmd`, если нужно сохранить текущие входные файлы, результаты или логи.
- Не чистить `config\icc\`: там лежат рабочие цветовые профили.
- Не удалять `config\ui_colors.yaml`: GUI читает из него темы и цветовые токены.
- Не менять имена файлов при конвертации; структура output зависит от формата и режима.
- Разрезание изображений пишет куски плоско в output с суффиксом `_01` ... `_100`.
- Подгонка под рулон и DPI без изменения пикселей не меняют пиксели.
