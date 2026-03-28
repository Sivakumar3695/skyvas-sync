"""Tests for skyvas_sync.settings_store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skyvas_sync.settings_store import SettingsStore


@pytest.fixture()
def store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(path=tmp_path / "settings.json")


class TestSettingsStoreBasic:
    def test_empty_by_default(self, store: SettingsStore):
        assert store.get_event_folder("evt-1") is None
        assert store.get_event_folders("evt-1") == []

    def test_set_and_get(self, store: SettingsStore, tmp_path: Path):
        folder = tmp_path / "photos"
        folder.mkdir()
        store.set_event_folder("evt-1", folder)
        assert store.get_event_folder("evt-1") == folder

    def test_get_event_folders_returns_list(self, store: SettingsStore, tmp_path: Path):
        f1 = tmp_path / "folder1"
        f1.mkdir()
        f2 = tmp_path / "folder2"
        f2.mkdir()
        store.add_event_folder("evt-1", f1)
        store.add_event_folder("evt-1", f2)
        result = store.get_event_folders("evt-1")
        assert result == [f1, f2]

    def test_add_no_duplicates(self, store: SettingsStore, tmp_path: Path):
        folder = tmp_path / "photos"
        folder.mkdir()
        store.add_event_folder("evt-1", folder)
        store.add_event_folder("evt-1", folder)
        result = store.get_event_folders("evt-1")
        assert len(result) == 1

    def test_get_event_folder_returns_last(self, store: SettingsStore, tmp_path: Path):
        f1 = tmp_path / "folder1"
        f1.mkdir()
        f2 = tmp_path / "folder2"
        f2.mkdir()
        store.add_event_folder("evt-1", f1)
        store.add_event_folder("evt-1", f2)
        assert store.get_event_folder("evt-1") == f2


class TestSettingsStorePersistence:
    def test_persisted_to_disk(self, tmp_path: Path):
        path = tmp_path / "settings.json"
        folder = tmp_path / "imgs"
        folder.mkdir()

        store1 = SettingsStore(path=path)
        store1.set_event_folder("evt-1", folder)

        store2 = SettingsStore(path=path)
        assert store2.get_event_folder("evt-1") == folder

    def test_handles_corrupt_file(self, tmp_path: Path):
        path = tmp_path / "settings.json"
        path.write_text("not json!!!")
        store = SettingsStore(path=path)
        assert store.get_event_folder("evt-1") is None


class TestSettingsStoreLegacyFormat:
    def test_legacy_string_format(self, tmp_path: Path):
        """Older settings stored a single string, not a list."""
        path = tmp_path / "settings.json"
        folder = tmp_path / "photos"
        folder.mkdir()
        path.write_text(json.dumps({"event_folders": {"evt-1": str(folder)}}))
        store = SettingsStore(path=path)
        assert store.get_event_folder("evt-1") == folder
        assert store.get_event_folders("evt-1") == [folder]

    def test_legacy_string_add_converts(self, tmp_path: Path):
        """Adding a folder when legacy format exists should convert to list."""
        path = tmp_path / "settings.json"
        f1 = tmp_path / "photos1"
        f1.mkdir()
        f2 = tmp_path / "photos2"
        f2.mkdir()
        path.write_text(json.dumps({"event_folders": {"evt-1": str(f1)}}))
        store = SettingsStore(path=path)
        store.add_event_folder("evt-1", f2)
        assert store.get_event_folders("evt-1") == [f1, f2]


class TestSettingsStoreMissing:
    def test_nonexistent_folder_skipped(self, store: SettingsStore, tmp_path: Path):
        folder = tmp_path / "does_not_exist"
        store._data = {"event_folders": {"evt-1": [str(folder)]}}
        assert store.get_event_folder("evt-1") is None
        assert store.get_event_folders("evt-1") == []


class TestInstantSyncFolder:
    def test_get_returns_none_by_default(self, store: SettingsStore):
        assert store.get_instant_sync_folder("evt-1") is None

    def test_set_and_get(self, store: SettingsStore, tmp_path: Path):
        folder = tmp_path / "sync"
        folder.mkdir()
        store.set_instant_sync_folder("evt-1", folder)
        assert store.get_instant_sync_folder("evt-1") == folder

    def test_clear(self, store: SettingsStore, tmp_path: Path):
        folder = tmp_path / "sync"
        folder.mkdir()
        store.set_instant_sync_folder("evt-1", folder)
        store.clear_instant_sync_folder("evt-1")
        assert store.get_instant_sync_folder("evt-1") is None

    def test_clear_nonexistent_noop(self, store: SettingsStore):
        store.clear_instant_sync_folder("evt-1")  # Should not raise
        assert store.get_instant_sync_folder("evt-1") is None

    def test_nonexistent_folder_returns_none(self, store: SettingsStore, tmp_path: Path):
        store.set_instant_sync_folder("evt-1", tmp_path / "gone")
        assert store.get_instant_sync_folder("evt-1") is None

    def test_persisted_to_disk(self, tmp_path: Path):
        path = tmp_path / "settings.json"
        folder = tmp_path / "sync_dir"
        folder.mkdir()

        store1 = SettingsStore(path=path)
        store1.set_instant_sync_folder("evt-1", folder)

        store2 = SettingsStore(path=path)
        assert store2.get_instant_sync_folder("evt-1") == folder

    def test_independent_of_event_folders(self, store: SettingsStore, tmp_path: Path):
        upload_folder = tmp_path / "upload"
        upload_folder.mkdir()
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()

        store.add_event_folder("evt-1", upload_folder)
        store.set_instant_sync_folder("evt-1", sync_folder)

        assert store.get_event_folders("evt-1") == [upload_folder]
        assert store.get_instant_sync_folder("evt-1") == sync_folder
