#!/usr/bin/env bash
# Build Skyvas Sync for the CURRENT platform.
# Run this script on each target OS (Linux, macOS, Windows via Git Bash / WSL).
# Usage: build_all.sh [staging|production]   (default: staging)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

ENV="${1:-staging}"

OS="$(uname -s)"
case "$OS" in
    Linux*)   bash "$SCRIPT_DIR/build_linux.sh" "$ENV" ;;
    Darwin*)  bash "$SCRIPT_DIR/build_macos.sh" "$ENV" ;;
    MINGW*|MSYS*|CYGWIN*)
              echo "On Windows, run:  scripts\\build_windows.bat $ENV"
              exit 1 ;;
    *)        echo "Unknown OS: $OS"; exit 1 ;;
esac
