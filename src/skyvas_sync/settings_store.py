"""Persistent application settings (folder-event mappings, etc.)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _default_settings_path() -> Path:
    """Return the default path for storing app settings."""
    return Path.home() / ".skyvas-sync" / "settings.json"


class SettingsStore:
    """JSON-backed key/value store for lightweight application state.

    Stores data such as the last-used folder for each event so the mapping
    survives application restarts.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = path or _default_settings_path()
        self._data: dict[str, Any] = {}
        self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    # -- folder ↔ event mapping --------------------------------------------

    def get_event_folder(self, event_id: str) -> Path | None:
        """Return the last stored folder path for *event_id*, or ``None``."""
        folder_map: dict[str, Any] = self._data.get("event_folders", {})
        raw = folder_map.get(event_id)
        if raw is None:
            return None
        # Support both legacy single-string and new list format
        if isinstance(raw, list):
            last = raw[-1] if raw else None
        else:
            last = raw
        if last is None:
            return None
        p = Path(last)
        return p if p.is_dir() else None

    def get_event_folders(self, event_id: str) -> list[Path]:
        """Return all stored folder paths for *event_id*."""
        folder_map: dict[str, Any] = self._data.get("event_folders", {})
        raw = folder_map.get(event_id)
        if raw is None:
            return []
        # Support both legacy single-string and new list format
        if isinstance(raw, str):
            raw = [raw]
        return [Path(r) for r in raw if Path(r).is_dir()]

    def add_event_folder(self, event_id: str, folder: Path) -> None:
        """Add *folder* to the stored list for *event_id* (no duplicates)."""
        folder_map: dict[str, Any] = self._data.setdefault("event_folders", {})
        raw = folder_map.get(event_id)
        if raw is None:
            folders: list[str] = []
        elif isinstance(raw, str):
            folders = [raw]
        else:
            folders = list(raw)
        folder_str = str(folder)
        if folder_str not in folders:
            folders.append(folder_str)
        folder_map[event_id] = folders
        self._save()

    def set_event_folder(self, event_id: str, folder: Path) -> None:
        """Persist the folder path for *event_id* (delegates to add)."""
        self.add_event_folder(event_id, folder)

    # -- instant-sync folder mapping ----------------------------------------

    def get_instant_sync_folder(self, event_id: str) -> Path | None:
        """Return the instant-sync folder for *event_id*, or ``None``."""
        sync_map: dict[str, str] = self._data.get("instant_sync_folders", {})
        raw = sync_map.get(event_id)
        if raw is None:
            return None
        p = Path(raw)
        return p if p.is_dir() else None

    def set_instant_sync_folder(self, event_id: str, folder: Path) -> None:
        """Save the instant-sync folder for *event_id*."""
        sync_map: dict[str, str] = self._data.setdefault("instant_sync_folders", {})
        sync_map[event_id] = str(folder)
        self._save()

    def clear_instant_sync_folder(self, event_id: str) -> None:
        """Remove the instant-sync folder setting for *event_id*."""
        sync_map: dict[str, str] = self._data.get("instant_sync_folders", {})
        sync_map.pop(event_id, None)
        self._save()
