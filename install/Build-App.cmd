@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Audion Image Tools - Build App

rem Builds App\ from Source\: the window of the program, AudionImageTools.exe, and the
rem PowerShell 7 it carries, AudionPs.exe (the scripts of the builder and of the
rem cleanup run with it; no PowerShell is downloaded or taken from the machine).
rem
rem Self-contained for win-x64: App\ carries its own .NET runtime, so the program
rem runs on a machine with nothing installed. The new copy is put together in
rem ._runtime\app_stage and checked there; App\ is replaced only by a copy that is
rem whole, so a failed build leaves the working one in place. The version comes
rem from config\version.json - the project files read it - and is written into the
rem executables.
rem
rem The checks of the window run first: the console command and the layout of the
rem window (tests\test_cli_command.py, tests\test_window_layout.py), and the
rem dictionary of the window - every Russian text it shows has its English pair
rem (Source\Tools\check_i18n.py). The built copy then checks itself (--self-test):
rem the answer of the console command reads, every place of an operation has its
rem node and its fields, every choice goes in the type of its option; --just-built
rem adds that the number of the executable is the number of config\version.json.
rem
rem Needs the .NET 10 SDK and the Python of the project (builder_main.cmd).
rem The step is run by hand when Source\ changes: a release does not rebuild the window.
rem
rem Usage: install\Build-App.cmd [/NOPAUSE]

for %%I in ("%~dp0..") do set "BASE_DIR=%%~fI"
set "NO_PAUSE=0"
if /I "%~1"=="/NOPAUSE" set "NO_PAUSE=1"

set "STEP_ERROR=0"
set "STAGE=%BASE_DIR%\._runtime\app_stage"
set "OLD=%BASE_DIR%\._runtime\app_old"
set "SAID=%BASE_DIR%\._runtime\app_self_test.txt"
set "PYTHON=%BASE_DIR%\runtime\python.exe"
set "WINDOW=AudionImageTools.exe"

if not exist "!PYTHON!" (
  echo [ERROR] Python of the project was not found: !PYTHON!
  echo         Build the environment first: builder_main.cmd
  set "STEP_ERROR=1"
)

set "DOTNET=%ProgramFiles%\dotnet\dotnet.exe"
if not exist "!DOTNET!" set "DOTNET="
if not defined DOTNET for %%P in (dotnet.exe) do if not defined DOTNET set "DOTNET=%%~$PATH:P"
if not defined DOTNET (
  echo [ERROR] .NET SDK was not found. Install the .NET 10 SDK: https://dotnet.microsoft.com/download
  set "STEP_ERROR=1"
)

if "!STEP_ERROR!"=="0" (
  echo [STEP] The checks of the window
  pushd "%BASE_DIR%"
  "!PYTHON!" -X utf8 -B -m pytest -q -p no:cacheprovider tests\test_cli_command.py tests\test_window_layout.py
  if errorlevel 1 (
    echo [ERROR] The checks of the console command or of the layout failed - App\ was not rebuilt.
    set "STEP_ERROR=1"
  )
  if "!STEP_ERROR!"=="0" (
    "!PYTHON!" -X utf8 -B "Source\Tools\check_i18n.py"
    if errorlevel 1 (
      echo [ERROR] The dictionary of the window lacks a pair - App\ was not rebuilt.
      set "STEP_ERROR=1"
    )
  )
  popd
)

if "!STEP_ERROR!"=="0" (
  echo [STEP] The PowerShell of the program - into App\
  if exist "!STAGE!" rd /s /q "!STAGE!"
  "!DOTNET!" publish "%BASE_DIR%\Source\Ps\AudionPs.csproj" -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -p:DebugType=None -o "!STAGE!" --nologo
  if errorlevel 1 (
    echo [ERROR] dotnet publish of Source\Ps failed.
    set "STEP_ERROR=1"
  )
)

if "!STEP_ERROR!"=="0" (
  echo [STEP] The window - into App\
  rem ReadyToRun: the window and Avalonia are compiled here, once, instead of at every start.
  "!DOTNET!" publish "%BASE_DIR%\Source\AudionImageTools.csproj" -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -p:PublishReadyToRun=true -p:DebugType=None -o "!STAGE!" --nologo
  if errorlevel 1 (
    echo [ERROR] dotnet publish of Source failed.
    set "STEP_ERROR=1"
  )
)

if "!STEP_ERROR!"=="0" (
  for %%F in ("!WINDOW!" "AudionPs.exe" "config\i18n.json" "Modules\Microsoft.PowerShell.Management" "ref") do (
    if not exist "!STAGE!\%%~F" (
      echo [ERROR] %%~F is missing in the build.
      set "STEP_ERROR=1"
    )
  )
)

if "!STEP_ERROR!"=="0" (
  rem Native packages bring their debug symbols along: megabytes nobody running the program needs.
  del /s /q "!STAGE!\*.pdb" >nul 2>nul
  "!STAGE!\AudionPs.exe" -NoLogo -NoProfile -NonInteractive -Command "exit 0" >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] The built AudionPs.exe does not start.
    set "STEP_ERROR=1"
  )
)

if "!STEP_ERROR!"=="0" (
  echo [STEP] The built window checks itself
  if exist "!SAID!" del /q "!SAID!"
  if exist "!SAID!.sent.json" del /q "!SAID!.sent.json"
  rem "start /wait": a windowed program is not waited for otherwise, and its exit code is lost.
  start "" /wait "!STAGE!\!WINDOW!" --self-test --just-built --to "!SAID!"
  if errorlevel 1 (
    echo [ERROR] The self-test of the window failed:
    if exist "!SAID!" findstr /B /C:"FAIL" "!SAID!"
    set "STEP_ERROR=1"
  ) else (
    echo [OK] The window came up and every check of it passed.
  )
  rem The check ran outside App\ and kept its own files beside itself: none of them is the program.
  if exist "!STAGE!\._runtime" rd /s /q "!STAGE!\._runtime"
  if exist "!STAGE!\logs" rd /s /q "!STAGE!\logs"
  if exist "!STAGE!\window_settings.json" del /q "!STAGE!\window_settings.json"
)

if "!STEP_ERROR!"=="0" (
  if exist "!OLD!" rd /s /q "!OLD!"
  if exist "%BASE_DIR%\App" move "%BASE_DIR%\App" "!OLD!" >nul 2>nul
  if exist "%BASE_DIR%\App" (
    echo [ERROR] App\ is in use and was not replaced: close the window, then run the step again. The new copy waits in ._runtime\app_stage.
    set "STEP_ERROR=1"
  ) else (
    move "!STAGE!" "%BASE_DIR%\App" >nul 2>nul
    if exist "%BASE_DIR%\App\!WINDOW!" (
      if exist "!OLD!" rd /s /q "!OLD!" >nul 2>nul
      echo [OK] App\ is built: !WINDOW! and AudionPs.exe.
    ) else (
      rem The new copy did not move in - something still holds a file of it. A program without
      rem its App\ starts nothing, so the working copy goes back before anything is said.
      if exist "!OLD!" move "!OLD!" "%BASE_DIR%\App" >nul 2>nul
      if exist "%BASE_DIR%\App\!WINDOW!" (
        echo [ERROR] The new App\ could not be moved into place; the former one was put back. The new copy waits in ._runtime\app_stage - run the step again.
      ) else (
        echo [ERROR] The new App\ could not be moved into place and there is no App\ now. The new copy waits in ._runtime\app_stage, a former one - in ._runtime\app_old: move one of them to App\ by hand.
      )
      set "STEP_ERROR=1"
    )
  )
)

if "%NO_PAUSE%"=="0" pause
endlocal & exit /b %STEP_ERROR%
