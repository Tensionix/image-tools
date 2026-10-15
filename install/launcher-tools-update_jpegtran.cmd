@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Audion - Update jpegtran

rem jpegtran of libjpeg-turbo into system_core\jpegtran: turns and mirrors of a JPEG without loss.
rem The official installer is opened by the 7z of PeaZip, never run; its SHA-256 is checked (install\get_jpegtran.py).

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%A in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fA"
set "PY=%ROOT%\runtime\python.exe"

if not exist "%PY%" (
  echo [ERROR] runtime\python.exe is not there: build the environment first - install\Build_Portable_Env.cmd
  set "CODE=1"
  goto END
)

"%PY%" -X utf8 "%ROOT%\install\get_jpegtran.py"
set "CODE=%ERRORLEVEL%"

:END
if /i not "%~1"=="/NOPAUSE" pause
exit /b %CODE%
