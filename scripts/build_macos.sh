#!/usr/bin/env bash
# Build Skyvas Sync application bundle for macOS using PyInstaller.
# Usage: build_macos.sh [staging|production]   (default: staging)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

ENV="${1:-staging}"
if [[ "$ENV" != "staging" && "$ENV" != "production" ]]; then
    echo "Error: ENV must be 'staging' or 'production' (got '$ENV')" >&2
    exit 1
fi

echo "==> Installing dependencies…"
pip install -e ".[dev]" --quiet

# Generate a runtime hook that bakes the target environment into the binary
HOOK_FILE="$(mktemp /tmp/hook_skyvas_env_XXXXXX.py)"
echo "import os; os.environ.setdefault('SKYVAS_ENV', '$ENV')" > "$HOOK_FILE"

echo "==> Building macOS app bundle (env=$ENV)…"
pyinstaller \
    --noconfirm \
    --onefile \
    --windowed \
    --name SkyvasSync \
    --distpath "dist/$ENV" \
    --add-data "README.md:." \
    --add-data "assets:assets" \
    --icon assets/icon.png \
    --osx-bundle-identifier "com.skyvas.sync" \
    --runtime-hook "$HOOK_FILE" \
    src/skyvas_sync/main.py

rm -f "$HOOK_FILE"

echo "==> Done! App at: dist/$ENV/SkyvasSync.app (or dist/$ENV/SkyvasSync)"
