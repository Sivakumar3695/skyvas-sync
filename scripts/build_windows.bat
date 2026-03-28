@echo off
REM Build Skyvas Sync executable for Windows using PyInstaller.
REM Usage: build_windows.bat [staging|production]   (default: staging)

cd /d "%~dp0\.."

SET ENV=%1
IF "%ENV%"=="" SET ENV=staging
IF NOT "%ENV%"=="staging" IF NOT "%ENV%"=="production" (
    echo Error: ENV must be 'staging' or 'production' (got '%ENV%')
    exit /b 1
)

echo ==> Installing dependencies...
pip install -e ".[dev]" --quiet

REM Generate a runtime hook that bakes the target environment into the binary
SET HOOK_FILE=%TEMP%\hook_skyvas_env.py
echo import os; os.environ.setdefault('SKYVAS_ENV', '%ENV%') > "%HOOK_FILE%"

echo ==> Building Windows executable (env=%ENV%)...
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

del "%HOOK_FILE%"

echo ==> Done! Binary at: dist\%ENV%\SkyvasSync.exe
