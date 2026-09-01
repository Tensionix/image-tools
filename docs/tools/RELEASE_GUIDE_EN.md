# Release Preparation

This is the English companion to `RELEASE_GUIDE_RU.md`.

## Quick Check

From the project root:

```bat
runtime\python.exe -m py_compile system_core\main.py system_core\image_tools\commands.py system_core\image_tools\pipeline.py system_core\services\image_tools_gui.py system_core\ui_nicegui\app.py system_core\ui_nicegui\window.py
```

Check the environment:

```bat
runtime\python.exe system_core\doctor.py
```

Check GUI smoke:

```bat
runtime\python.exe system_core\ui_nicegui\app.py --smoke
```

Check new CLI surfaces before packaging:

```bat
runtime\python.exe system_core\main.py trim-border --help
runtime\python.exe system_core\main.py smart-crop-white --help
runtime\python.exe system_core\main.py images-to-pdf --help
```

## Cleanup

`cleanup_project.cmd` is the interactive CMD cleanup script for final project cleanup before rebuild or packaging. It shows the cleanup plan and asks for `Y/N/Q`.

It clears managed working/runtime/generated areas such as `input\`, `output\`, `logs\`, `report\`, `workspace\`, `data\`, `release\`, `runtime\`, `wheelhouse\`, `install\download\`, runtime temp folders, Python caches, generated logs, and selected generated tools.

It does not clear:

- `config\`;
- `docs\`;
- `GitHub\`;
- launchers and CMD scripts;
- source code except explicitly generated files listed by the cleanup plan.

After cleanup, the script calls `install\init_folders.cmd` to recreate the managed folder set.

## Release Order

1. Close the GUI and terminals that may hold project files.
2. Run `runtime\python.exe system_core\doctor.py`.
3. Run `cleanup_project.cmd` and confirm only if the deletion list is expected.
4. Rebuild portable runtime and wheelhouse if needed.
5. Build the release through `launcher_tools.cmd` or `install\make_release_archive.cmd`.
6. Check that the archive contains the GUI launcher, RU launcher, configs, runtime, `system_core\main.py`, user docs, and `AGENTS.md`.

## Rules

- Do not run cleanup if current `input\`, `output\`, logs, or built runtime must be preserved.
- Do not remove `config\icc\` or `config\ui_colors.yaml`.
- Do not rename files during conversion; output structure depends on format and mode.
- Slice operations write flat numbered outputs with suffixes such as `_01` through `_100`.
- DPI/roll fitting without resolution change does not change pixels.
