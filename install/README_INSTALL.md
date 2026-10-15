# Audion Image Tools - build notes

## What a build is for

A build brings back fresh components, and nothing else is downloaded:

- the embedded Python `3.12.x` of the day with the packages of `install\requirements_full.in` -
  the image core (Pillow, pillow-heif, numpy, rawpy), PDF and documents (PyMuPDF, img2pdf,
  pikepdf, lxml), PyYAML and tqdm, the build bootstrap (`setuptools`, `wheel`, `packaging`) and
  `pytest`;
- jpegtran of libjpeg-turbo, which turns a JPEG without loss (`system_core\jpegtran`). The
  official installer is checked by its SHA-256 and opened by the 7z of PeaZip, never run
  (`install\get_jpegtran.py`). Without jpegtran a JPEG is turned by its pixels; a build warns
  and goes on.

`App\` - the window and the PowerShell the program carries - is **not** a product of a build.
It stays through a cleanup and travels in a release as it is. It is rebuilt only when
`Source\` changes, and that needs the .NET 10 SDK.

## The builder

```bat
builder_main.cmd
```

```text
[01] PYTHON ENV CMD        build the portable runtime with curl and tar
[02] PYTHON ENV PS         the same through PowerShell
[03] JPEGTRAN              libjpeg-turbo: turns of a JPEG without loss
[04] START LAUNCHER        rebuild Start.exe
[05] WINDOW                rebuild App\ - only after a change in Source\
[09] PORTABLE OFFLINE      install from the local runtime and wheelhouse
[70] CLEAN INSTALL CACHE   the cache of the install, bytecode, bin and obj of Source
[71] VERIFY / DOCTOR       the environment, the console command and the built window
[72] CMD ENCODING CHECK    UTF-8 without BOM, CRLF
[73] UPDATE REQUIREMENTS LOCK
[95]-[98] OPEN install, runtime, wheelhouse, licenses
[00] EXIT
```

What a release build runs, in this order: `02`, `71`, `70`. Steps `01` and `02` bring jpegtran
too; `03` brings it alone.

The scripts take the PowerShell of the program first, `App\AudionPs.exe`, so a build runs on
the same PowerShell on every machine; the one of Windows is used only where `App\` is not
built yet.

## The steps of the portable environment

1. Make the folders (`install\init_folders.cmd`) and check the encoding of the `.cmd` files.
2. Find and download the latest Python Embedded `3.12.x`.
3. Unpack it into `runtime\`.
4. Enable `import site` in `python3<minor>._pth`.
5. Download `get-pip.py` and install pip.
6. Install the build bootstrap, rebuild `wheelhouse\` as installable wheels - what was there is
   removed first - and install the packages into the runtime from the local `wheelhouse\`.
7. Bring jpegtran into `system_core\jpegtran`.
8. Verify with `system_core\doctor.py`.

## Offline

With `runtime\` and `wheelhouse\` already filled:

```bat
install\install_portable_offline.cmd
install\verify_portable_env.cmd
```

`verify_portable_env.cmd` checks the environment (`system_core\doctor.py`), that the console
command reads the manifest, jpegtran (a warning when it is missing), `Start.exe` and the
self-check of the built window against the manifest.

## The window

```bat
install\Build-App.cmd
```

The checks of the console command and of the layout, the dictionary of the window, the
PowerShell of the program (`Source\Ps`), the window (`Source\`), the self-check of the built copy
against the manifest - and only then the swap of `App\`. A build that fails leaves the working
`App\` in place.

`install\Build-StartLauncher.cmd` rebuilds `Start.exe`, which opens
`App\AudionImageTools.exe` and steps aside.

## Release archives

The archives of a release, with the third-party notices and the license files in them, are
made by Audion Build Orchestrator and Audion Build Licenses. The builder of this project
makes none.

## Hygiene

- Python Embedded follows the latest `3.12.x`; no patch version is pinned in a script or a
  document.
- `runtime\`, `wheelhouse\` and `system_core\jpegtran\` are reproducible payloads. A script
  cleanly replaces only the target it owns.
- `install\Clean-Install-Cache.cmd` clears what an install leaves behind: the transient files
  of `install\download\`, Python bytecode outside the runtime, `bin` and `obj` under `Source\`.
- `cleanup_project.cmd` is a different tool: it returns the project to its sources - the
  environment, the downloads and the working folders go. It is not part of an install and is
  never run by one.
- `.cmd` files are UTF-8 without BOM and CRLF. A running `.cmd` cannot be rewritten from
  inside, so builds only check; `[72]` repairs, and the builder is started anew after it.
- A builder stops at a failed command. `[SUCCESS]` is not printed after pip failed.
