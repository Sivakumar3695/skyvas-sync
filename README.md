# Skyvas Sync

A cross-platform desktop application for instant photo sync from local folders to Skyvas events.

## Features

- **Google OAuth login** via AWS Cognito (same backend as the web UI)
- **Event browsing** — view all your existing events
- **Folder-based upload** — select a folder and recursively upload all images
- **Live upload progress** — track uploads with a progress bar and file counts
- **Instant Sync** — watch a folder (including MTP-mounted Android phones) for new photos and upload them automatically
- **Upload status** — see per-event upload counts in the events list

## Prerequisites

- Python 3.10+
- A Skyvas account (Google sign-in)

> **Cognito Setup**: Add `http://localhost:8585/callback` to the **Allowed callback URLs**
> in your Cognito User Pool App Client settings to enable desktop OAuth login.

## Installation

```bash
# Clone the repository
git clone <repo-url> skyvas-sync
cd skyvas-sync

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -e ".[dev]"
```

## Running

```bash
# Run the application
skyvas-sync

# Or run directly
python -m skyvas_sync.main

# Use production backend
SKYVAS_ENV=production skyvas-sync
```

## Testing

```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/test_api/test_client.py -v

# Generate HTML coverage report
pytest --cov-report=html
open htmlcov/index.html
```

## Building Executables

Each build script accepts an optional environment argument: `staging` (default) or `production`.
The target environment is **baked into the binary** at build time via a PyInstaller runtime hook,
so the correct backend APIs are always used without any extra configuration on the end-user's machine.
Outputs are written to `dist/<env>/` so both variants can coexist.

### Linux

```bash
# Staging (default)
bash scripts/build_linux.sh
# Output: dist/staging/SkyvasSync

# Production
bash scripts/build_linux.sh production
# Output: dist/production/SkyvasSync
```

### macOS

```bash
# Staging (default)
bash scripts/build_macos.sh
# Output: dist/staging/SkyvasSync.app

# Production
bash scripts/build_macos.sh production
# Output: dist/production/SkyvasSync.app
```

### Windows

```bat
REM Staging (default)
scripts\build_windows.bat
REM Output: dist\staging\SkyvasSync.exe

REM Production
scripts\build_windows.bat production
REM Output: dist\production\SkyvasSync.exe
```

### All Platforms (from the current OS)

```bash
# Staging (default)
bash scripts/build_all.sh

# Production
bash scripts/build_all.sh production
```

> **Note:** On Windows, `build_all.sh` will prompt you to run `build_windows.bat` directly instead.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SKYVAS_ENV` | `staging` | `staging` or `production` |

## Instant Sync — Polling Configuration

Instant Sync watches a folder for new images and uploads them automatically.
New-file detection uses two complementary mechanisms:

| Mechanism | How it works | Works on MTP? |
|---|---|---|
| **inotify** (`QFileSystemWatcher`) | Kernel-level instant notification when a file appears | ❌ No — MTP/GVFS is a userspace filesystem |
| **Polling** | Background thread re-scans the folder tree at a fixed interval | ✅ Yes |

Polling is the only reliable detection method for MTP-mounted devices (e.g. Android
phones connected via USB). It is enabled by default.

### Configuration

The poll interval is set via the `poll_interval_ms` parameter on `FolderWatcher`
(in `src/skyvas_sync/upload/watcher.py`):

| Parameter | Default | Description |
|---|---|---|
| `poll_interval_ms` | `5000` (5 s) | How often to re-scan the watched folder for new images. Set to `0` to disable polling entirely. |
| `stabilize_ms` | `1000` (1 s) | Debounce delay for inotify events before processing. |

### Latency

| Scenario | Typical latency | Notes |
|---|---|---|
| Local folder (inotify) | < 1 s | Instant kernel notification |
| MTP device (polling) | 3–7 s | Depends on folder size and USB speed |
| MTP device (worst case) | ~10 s | Poll fires just before photo appears + slow rglob |

To reduce latency for live events, lower the poll interval:

```python
# In src/skyvas_sync/upload/instant_sync.py
self._watcher = FolderWatcher(folder, parent=self, poll_interval_ms=2000)  # 2 seconds
```

> **Trade-off:** A shorter interval increases USB/MTP traffic and may cause slightly
> higher battery drain on the connected device.

## Architecture

```
src/skyvas_sync/
├── main.py              # Application entry point
├── config.py            # Environment configuration
├── auth/
│   ├── cognito_auth.py  # OAuth flow (PKCE + local callback server)
│   └── token_store.py   # Token persistence and refresh
├── api/
│   ├── client.py        # HTTP API client
│   └── models.py        # Data models
├── upload/
│   ├── scanner.py       # Recursive folder image scanner
│   ├── uploader.py      # Background upload worker (QThread)
│   ├── watcher.py       # Filesystem watcher with inotify + polling fallback
│   └── instant_sync.py  # Automatic upload of new images from a watched folder
├── ui/
│   ├── main_window.py   # Main window with view stack
│   ├── login_view.py    # Google sign-in view
│   ├── events_list_view.py  # Events table with upload status
│   ├── uploader_view.py # Folder picker + progress
    └── login_view.py    # Google sign-in view
└── utils/
    └── image_utils.py   # Image dimension/thumbnail helpers
```

## License

MIT
