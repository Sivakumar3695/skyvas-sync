@echo off
setlocal
REM Build Skyvas Sync executable for Windows using PyInstaller.
REM Usage: build_windows.bat [staging|production]   (default: staging)

cd /d "%~dp0.."
if errorlevel 1 (
    echo Error: could not enter project directory
    exit /b 1
)

set "ENV=%~1"
if "%ENV%"=="" set "ENV=staging"
REM Validate via goto: a ")" inside a parenthesised block would close it early.
if not "%ENV%"=="staging" if not "%ENV%"=="production" goto :bad_env

echo [build] Installing dependencies...
pip install -e ".[dev]"
if errorlevel 1 (
    echo Error: dependency installation failed
    exit /b 1
)

REM Generate a runtime hook that bakes the target environment into the binary
set "HOOK_FILE=%TEMP%\hook_skyvas_env.py"
> "%HOOK_FILE%" echo import os; os.environ.setdefault('SKYVAS_ENV', '%ENV%')

echo [build] Building Windows executable (env=%ENV%)...
pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name SkyvasSync ^
    --distpath "dist\%ENV%" ^
    --add-data "README.md;." ^
    --add-data "assets;assets" ^
    --icon assets\icon.png ^
    --runtime-hook "%HOOK_FILE%" ^
    src\skyvas_sync\main.py
set "RC=%ERRORLEVEL%"

del "%HOOK_FILE%" 2>nul

if not "%RC%"=="0" (
    echo Error: PyInstaller failed with exit code %RC%
    exit /b %RC%
)

echo [build] Done! Binary at: dist\%ENV%\SkyvasSync.exe
exit /b 0

:bad_env
echo Error: ENV must be 'staging' or 'production' ^(got '%ENV%'^)
exit /b 1
