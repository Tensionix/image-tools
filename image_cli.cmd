@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem Audion Image Tools: the console command. A button of the window and this command run the
rem same thing - an operation of the manifest, with the same rules of its form.
rem
rem   image_cli.cmd describe
rem   image_cli.cmd run --operation downscale_percent --set scale_mode=custom --set custom_percent=75
rem   image_cli.cmd run --operation convert_images --source D:\Photos --target D:\Out --set to=jpg,png
rem   image_cli.cmd version
rem
rem Exit codes: 0 done, 1 the operation failed, 2 wrong call, 130 stopped.
rem
rem The folder of the caller stays the current one: a relative --params, --result or
rem --cancel-file is counted from it. A relative --source or --target is counted from
rem the program folder - the command does that itself.

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"

set "PYTHON_CMD="
if exist "%BASE_DIR%\runtime\python.exe" set "PYTHON_CMD=%BASE_DIR%\runtime\python.exe"
if not defined PYTHON_CMD if exist "%BASE_DIR%\runtime\python\python.exe" set "PYTHON_CMD=%BASE_DIR%\runtime\python\python.exe"
rem Not a block in brackets: a path with a bracket in it - "Program Files (x86)" - would close it.
if not defined PYTHON_CMD goto NO_PYTHON

rem The command is started as a file, not as a module: it puts the project on the
rem path itself, wherever the embedded Python looks for modules.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%PYTHON_CMD%" -u "%BASE_DIR%\system_core\cli.py" %*
exit /b %ERRORLEVEL%

:NO_PYTHON
echo [ERR] Python of the project was not found: "%BASE_DIR%\runtime\python.exe"
echo       Build the environment first: builder_main.cmd
exit /b 2
