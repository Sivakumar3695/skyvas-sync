"""Tests for skyvas_sync.ui.uploader_view."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from PySide6.QtWidgets import QDialog

from skyvas_sync.api.client import ApiClient
from skyvas_sync.api.models import Event, UploadStatus
from skyvas_sync.settings_store import SettingsStore
from skyvas_sync.ui.folder_dialog import AsyncFolderDialog
from skyvas_sync.ui.uploader_view import UploaderView


def _mock_folder_dialog(folder: str | None):
    """Return a context manager that patches ``_make_folder_dialog``.

    When *folder* is a non-empty string the mock dialog returns ``Accepted``
    and reports the path as the selected folder.  When *folder* is ``None``
    or empty the dialog returns ``Rejected``.
    """
    dlg = MagicMock(spec=AsyncFolderDialog)
    if folder:
        dlg.exec.return_value = QDialog.DialogCode.Accepted
        dlg.selected_path.return_value = Path(folder)
    else:
        dlg.exec.return_value = QDialog.DialogCode.Rejected
        dlg.selected_path.return_value = None
    return patch.object(UploaderView, "_make_folder_dialog", return_value=dlg)


@pytest.fixture()
def mock_api() -> MagicMock:
    return MagicMock(spec=ApiClient)


@pytest.fixture()
def settings(tmp_path: Path) -> SettingsStore:
    return SettingsStore(path=tmp_path / "settings.json")


@pytest.fixture()
def uploader_view(qtbot, mock_api: MagicMock, settings: SettingsStore) -> UploaderView:
    view = UploaderView(mock_api, settings)
    qtbot.addWidget(view)
    return view


@pytest.fixture()
def event() -> Event:
    return Event(
        id="evt-1", name="Test Event", place="Hall", date="09/Mar/2026",
        event_type="WEDDING", status_code=0,
    )


class TestUploaderViewInit:
    def test_initial_state(self, uploader_view: UploaderView):
        assert uploader_view._folders == []
        assert not uploader_view._start_btn.isEnabled()
        assert not uploader_view._cancel_btn.isEnabled()
        assert uploader_view._progress_bar.value() == 0

    def test_set_event_resets_ui(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        assert uploader_view._event == event
        assert uploader_view._folders == []
        assert not uploader_view._no_folder_label.isHidden()
        assert not uploader_view._start_btn.isEnabled()

    def test_set_event_locked_when_status_gte_2(self, uploader_view: UploaderView):
        locked_event = Event(
            id="evt-2", name="Done Event", place="Hall", date="09/Mar/2026",
            event_type="WEDDING", status_code=2,
        )
        uploader_view.set_event(locked_event)
        assert not uploader_view._browse_btn.isEnabled()
        assert not uploader_view._start_btn.isEnabled()
        assert not uploader_view._locked_label.isHidden()
        assert "Photo Uploaded" in uploader_view._locked_label.text()

    def test_set_event_unlocked_when_status_lt_2(self, uploader_view: UploaderView, image_folder: Path):
        unlocked_event = Event(
            id="evt-3", name="Active Event", place="Hall", date="09/Mar/2026",
            event_type="WEDDING", status_code=1,
        )
        uploader_view.set_event(unlocked_event)
        assert uploader_view._browse_btn.isEnabled()
        assert uploader_view._locked_label.isHidden()


class TestUploaderViewBrowse:
    def test_browse_selects_folder(self, qtbot, uploader_view: UploaderView, image_folder: Path, event: Event):
        uploader_view.set_event(event)
        with _mock_folder_dialog(str(image_folder)):
            uploader_view._on_browse()
        assert image_folder in uploader_view._folders
        assert "3 image(s)" in uploader_view._count_label.text()
        assert uploader_view._start_btn.isEnabled()

    def test_browse_cancelled(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        with _mock_folder_dialog(None):
            uploader_view._on_browse()
        assert uploader_view._folders == []
        assert not uploader_view._start_btn.isEnabled()

    def test_browse_empty_folder(self, qtbot, uploader_view: UploaderView, event: Event, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        uploader_view.set_event(event)
        with _mock_folder_dialog(str(empty)):
            uploader_view._on_browse()
        assert "0 image(s)" in uploader_view._count_label.text()
        assert not uploader_view._start_btn.isEnabled()

    def test_browse_second_folder_preserves_first(self, qtbot, uploader_view: UploaderView, event: Event, image_folder: Path, tmp_path: Path):
        """Selecting a second folder must not wipe out the first."""
        uploader_view.set_event(event)
        second = tmp_path / "extra"
        second.mkdir()
        img = Image.new("RGB", (50, 50))
        img.save(second / "extra.jpg")

        uploader_view._apply_folder(image_folder)
        uploader_view._apply_folder(second)

        assert image_folder in uploader_view._folders
        assert second in uploader_view._folders
        assert len(uploader_view._folders) == 2
        assert "4 image(s)" in uploader_view._count_label.text()

    def test_duplicate_folder_ignored(self, uploader_view: UploaderView, event: Event, image_folder: Path):
        uploader_view.set_event(event)
        uploader_view._apply_folder(image_folder)
        uploader_view._apply_folder(image_folder)
        assert len(uploader_view._folders) == 1

    def test_remove_folder(self, uploader_view: UploaderView, event: Event, image_folder: Path, tmp_path: Path):
        uploader_view.set_event(event)
        second = tmp_path / "extra"
        second.mkdir()
        img = Image.new("RGB", (50, 50))
        img.save(second / "x.jpg")
        uploader_view._apply_folder(image_folder)
        uploader_view._apply_folder(second)
        assert len(uploader_view._folders) == 2
        uploader_view._remove_folder(image_folder)
        assert len(uploader_view._folders) == 1
        assert second in uploader_view._folders
        assert image_folder not in uploader_view._folders

    def test_remove_last_folder_shows_placeholder(self, uploader_view: UploaderView, event: Event, image_folder: Path):
        uploader_view.set_event(event)
        uploader_view._apply_folder(image_folder)
        uploader_view._remove_folder(image_folder)
        assert not uploader_view._no_folder_label.isHidden()

    def test_remove_nonexistent_noop(self, uploader_view: UploaderView, event: Event, tmp_path: Path):
        uploader_view.set_event(event)
        uploader_view._remove_folder(tmp_path / "nope")  # Should not raise


class TestUploaderViewRestore:
    def test_set_event_restores_all_folders(self, qtbot, mock_api: MagicMock, tmp_path: Path):
        settings = SettingsStore(path=tmp_path / "s.json")
        view = UploaderView(mock_api, settings)
        qtbot.addWidget(view)

        # Create two folders and save them manually
        f1 = tmp_path / "a"
        f1.mkdir()
        f2 = tmp_path / "b"
        f2.mkdir()
        img = Image.new("RGB", (40, 30))
        img.save(f1 / "img.jpg")
        img.save(f2 / "img.jpg")

        settings.add_event_folder("evt-1", f1)
        settings.add_event_folder("evt-1", f2)

        event = Event(id="evt-1", name="E", place="P", date="01/Jan/2026", event_type="WEDDING", status_code=0)
        view.set_event(event)

        assert f1 in view._folders
        assert f2 in view._folders
        assert len(view._folders) == 2
        assert "2 image(s)" in view._count_label.text()


class TestUploaderViewProgress:
    def test_on_progress(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        status_updates: list = []
        uploader_view.upload_status_changed.connect(lambda s: status_updates.append(s))

        uploader_view._on_progress(5, 20, "photo.jpg")
        assert uploader_view._progress_bar.value() == 25
        label = uploader_view._current_file.text()
        assert "photo.jpg" in label
        assert "5 / 20" in label
        assert len(status_updates) == 1

    def test_on_progress_zero_total(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        uploader_view._on_progress(0, 0, "")
        assert uploader_view._progress_bar.value() == 0

    def test_on_progress_empty_current(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        uploader_view._on_progress(10, 10, "")
        assert "10 / 10" in uploader_view._current_file.text()


class TestUploaderViewCallbacks:
    def test_on_file_done(self, uploader_view: UploaderView):
        uploader_view._on_file_done("/path/to/photo.jpg")
        assert "photo.jpg" in uploader_view._log.toPlainText()

    def test_on_file_error(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        uploader_view._on_file_error("/path/to/bad.jpg", "timeout")
        assert "bad.jpg" in uploader_view._log.toPlainText()
        assert "timeout" in uploader_view._log.toPlainText()
        assert uploader_view._status.failed == 1

    def test_on_finished(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        uploader_view._status.total = 10
        uploader_view._status.uploaded = 8
        uploader_view._status.failed = 2

        status_updates: list = []
        uploader_view.upload_status_changed.connect(lambda s: status_updates.append(s))

        uploader_view._on_finished()
        assert uploader_view._start_btn.isEnabled()
        assert uploader_view._browse_btn.isEnabled()
        assert not uploader_view._cancel_btn.isEnabled()
        assert "8 uploaded" in uploader_view._current_file.text()
        assert "2 failed" in uploader_view._current_file.text()
        assert len(status_updates) == 1

    def test_on_fatal_error(self, uploader_view: UploaderView):
        uploader_view._on_fatal_error("Something broke")
        assert "Something broke" in uploader_view._log.toPlainText()


class TestUploaderViewStartCancel:
    def test_start_without_event_noop(self, uploader_view: UploaderView):
        uploader_view._on_start()  # Should not raise

    def test_start_without_folder_noop(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        uploader_view._on_start()  # Should not raise

    def test_cancel_without_worker(self, uploader_view: UploaderView):
        uploader_view._on_cancel()  # Should not raise

    def test_start_configures_worker(self, qtbot, uploader_view: UploaderView, event: Event, image_folder: Path):
        uploader_view.set_event(event)
        uploader_view._folders = [image_folder]

        with patch("skyvas_sync.ui.uploader_view.UploadWorker") as MockWorker:
            instance = MockWorker.return_value
            instance.progress = MagicMock()
            instance.progress.connect = MagicMock()
            instance.file_done = MagicMock()
            instance.file_done.connect = MagicMock()
            instance.file_error = MagicMock()
            instance.file_error.connect = MagicMock()
            instance.finished_all = MagicMock()
            instance.finished_all.connect = MagicMock()
            instance.error = MagicMock()
            instance.error.connect = MagicMock()
            instance.start = MagicMock()

            uploader_view._on_start()

            MockWorker.assert_called_once()
            instance.start.assert_called_once()
            assert not uploader_view._start_btn.isEnabled()
            assert not uploader_view._browse_btn.isEnabled()
            assert uploader_view._cancel_btn.isEnabled()
            assert not uploader_view._complete_btn.isEnabled()

    def test_cancel_calls_worker_cancel(self, uploader_view: UploaderView):
        mock_worker = MagicMock()
        uploader_view._worker = mock_worker
        uploader_view._cancel_btn.setEnabled(True)
        uploader_view._on_cancel()
        mock_worker.cancel.assert_called_once()
        assert not uploader_view._cancel_btn.isEnabled()


class TestUploaderViewMarkComplete:
    def test_complete_btn_hidden_initially(self, uploader_view: UploaderView):
        assert uploader_view._complete_btn.isHidden()
        assert not uploader_view._complete_btn.isEnabled()

    def test_complete_btn_shown_after_finished(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        uploader_view._status.total = 5
        uploader_view._status.uploaded = 5
        uploader_view._on_finished()
        assert not uploader_view._complete_btn.isHidden()
        assert uploader_view._complete_btn.isEnabled()

    def test_mark_complete_calls_api(self, uploader_view: UploaderView, mock_api: MagicMock, event: Event):
        uploader_view.set_event(event)
        uploader_view._on_finished()
        uploader_view._on_mark_complete()
        mock_api.update_event_status.assert_called_once_with("evt-1", "UPLOADED")
        assert not uploader_view._complete_btn.isEnabled()
        assert "complete" in uploader_view._current_file.text().lower()

    def test_mark_complete_api_error(self, uploader_view: UploaderView, mock_api: MagicMock, event: Event):
        from skyvas_sync.api.client import ApiError
        uploader_view.set_event(event)
        uploader_view._on_finished()
        mock_api.update_event_status.side_effect = ApiError(500, "fail")
        uploader_view._on_mark_complete()
        assert "ERROR" in uploader_view._log.toPlainText()

    def test_complete_btn_hidden_on_set_event(self, uploader_view: UploaderView, event: Event):
        uploader_view._complete_btn.setVisible(True)
        uploader_view._complete_btn.setEnabled(True)
        uploader_view.set_event(event)
        assert uploader_view._complete_btn.isHidden()
        assert not uploader_view._complete_btn.isEnabled()

    def test_mark_complete_no_event_noop(self, uploader_view: UploaderView, mock_api: MagicMock):
        uploader_view._on_mark_complete()
        mock_api.update_event_status.assert_not_called()


# ==========================================================================
# Instant-sync UI tests
# ==========================================================================

class TestUploaderViewInstantSyncInit:
    def test_initial_sync_state(self, uploader_view: UploaderView):
        assert uploader_view._instant_sync is None
        assert uploader_view._instant_sync_folder is None
        assert uploader_view._sync_folder_label.text() == "No folder selected"
        assert not uploader_view._sync_clear_btn.isEnabled()
        assert uploader_view._sync_status.text() == ""

    def test_instant_sync_folder_property_none(self, uploader_view: UploaderView):
        assert uploader_view.instant_sync_folder is None


class TestUploaderViewInstantSyncBrowse:
    def test_browse_selects_folder(self, uploader_view: UploaderView, event: Event, tmp_path: Path):
        sync_dir = tmp_path / "sync_folder"
        sync_dir.mkdir()
        uploader_view.set_event(event)

        with _mock_folder_dialog(str(sync_dir)):
            with patch("skyvas_sync.ui.uploader_view.InstantSyncManager") as MockSync:
                instance = MockSync.return_value
                instance.file_uploaded = MagicMock()
                instance.file_uploaded.connect = MagicMock()
                instance.file_error = MagicMock()
                instance.file_error.connect = MagicMock()
                instance.upload_progress = MagicMock()
                instance.upload_progress.connect = MagicMock()
                instance.start = MagicMock()
                instance.stop = MagicMock()
                instance.is_active = True

                uploader_view._on_sync_browse()

                MockSync.assert_called_once()
                instance.start.assert_called_once()
                assert uploader_view._instant_sync_folder == sync_dir
                assert uploader_view._sync_clear_btn.isEnabled()
                assert "Active" in uploader_view._sync_status.text()

    def test_browse_cancelled(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        with _mock_folder_dialog(None):
            uploader_view._on_sync_browse()
        assert uploader_view._instant_sync is None

    def test_browse_no_event_noop(self, uploader_view: UploaderView, tmp_path: Path):
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        # No event set → _start_instant_sync returns early
        uploader_view._start_instant_sync(sync_dir)
        assert uploader_view._instant_sync is None


class TestUploaderViewInstantSyncClear:
    def test_clear_stops_sync(self, uploader_view: UploaderView, event: Event, tmp_path: Path, settings: SettingsStore):
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        uploader_view.set_event(event)

        # Set up instant sync folder directly
        uploader_view._instant_sync_folder = sync_dir
        mock_mgr = MagicMock()
        uploader_view._instant_sync = mock_mgr
        settings.set_instant_sync_folder("evt-1", sync_dir)

        uploader_view._on_sync_clear()

        mock_mgr.stop.assert_called_once()
        assert uploader_view._instant_sync is None
        assert uploader_view._instant_sync_folder is None
        assert settings.get_instant_sync_folder("evt-1") is None
        assert uploader_view._sync_folder_label.text() == "No folder selected"
        assert not uploader_view._sync_clear_btn.isEnabled()

    def test_clear_without_sync_noop(self, uploader_view: UploaderView, event: Event):
        uploader_view.set_event(event)
        uploader_view._on_sync_clear()  # Should not raise


class TestUploaderViewInstantSyncCallbacks:
    def test_on_sync_file_uploaded(self, uploader_view: UploaderView):
        uploader_view._on_sync_file_uploaded("/tmp/photo.jpg")
        assert "photo.jpg" in uploader_view._sync_log.toPlainText()

    def test_on_sync_file_error(self, uploader_view: UploaderView):
        uploader_view._on_sync_file_error("/tmp/bad.jpg", "timeout")
        text = uploader_view._sync_log.toPlainText()
        assert "bad.jpg" in text
        assert "timeout" in text

    def test_on_sync_progress(self, uploader_view: UploaderView):
        uploader_view._on_sync_progress(5, 10, "current.jpg")
        assert "5/10" in uploader_view._sync_status.text()
        assert "Active" in uploader_view._sync_status.text()


class TestUploaderViewInstantSyncRestore:
    def test_set_event_restores_sync_folder(self, qtbot, mock_api: MagicMock, tmp_path: Path):
        settings = SettingsStore(path=tmp_path / "s.json")
        view = UploaderView(mock_api, settings)
        qtbot.addWidget(view)

        sync_dir = tmp_path / "sync_restore"
        sync_dir.mkdir()
        settings.set_instant_sync_folder("evt-1", sync_dir)

        event = Event(id="evt-1", name="E", place="P", date="D", event_type="T", status_code=0)

        with patch("skyvas_sync.ui.uploader_view.InstantSyncManager") as MockSync:
            instance = MockSync.return_value
            instance.file_uploaded = MagicMock()
            instance.file_uploaded.connect = MagicMock()
            instance.file_error = MagicMock()
            instance.file_error.connect = MagicMock()
            instance.upload_progress = MagicMock()
            instance.upload_progress.connect = MagicMock()
            instance.start = MagicMock()
            instance.stop = MagicMock()

            view.set_event(event)

            # Should have restored and started instant sync
            MockSync.assert_called_once()
            instance.start.assert_called_once()
            assert view._instant_sync_folder == sync_dir

    def test_set_event_no_saved_sync(self, uploader_view: UploaderView, event: Event):
        with patch("skyvas_sync.ui.uploader_view.InstantSyncManager") as MockSync:
            uploader_view.set_event(event)
            MockSync.assert_not_called()


class TestUploaderViewMarkCompleteStopsSync:
    def test_mark_complete_stops_instant_sync(self, uploader_view: UploaderView, mock_api: MagicMock, event: Event, settings: SettingsStore, tmp_path: Path):
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        uploader_view.set_event(event)

        # Simulate active instant sync
        mock_mgr = MagicMock()
        uploader_view._instant_sync = mock_mgr
        uploader_view._instant_sync_folder = sync_dir
        settings.set_instant_sync_folder("evt-1", sync_dir)

        uploader_view._on_finished()  # Make complete btn visible
        uploader_view._on_mark_complete()

        mock_mgr.stop.assert_called_once()
        assert uploader_view._instant_sync is None
        assert settings.get_instant_sync_folder("evt-1") is None
        assert uploader_view._sync_folder_label.text() == "No folder selected"

    def test_complete_btn_visible_when_sync_active(self, uploader_view: UploaderView, event: Event, tmp_path: Path):
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        uploader_view.set_event(event)

        with patch("skyvas_sync.ui.uploader_view.InstantSyncManager") as MockSync:
            instance = MockSync.return_value
            instance.file_uploaded = MagicMock()
            instance.file_uploaded.connect = MagicMock()
            instance.file_error = MagicMock()
            instance.file_error.connect = MagicMock()
            instance.upload_progress = MagicMock()
            instance.upload_progress.connect = MagicMock()
            instance.start = MagicMock()
            instance.stop = MagicMock()

            uploader_view._start_instant_sync(sync_dir)

        assert not uploader_view._complete_btn.isHidden()
        assert uploader_view._complete_btn.isEnabled()


class TestUploaderViewResetClearsSync:
    def test_reset_stops_sync(self, uploader_view: UploaderView, event: Event, tmp_path: Path):
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        uploader_view.set_event(event)

        mock_mgr = MagicMock()
        uploader_view._instant_sync = mock_mgr
        uploader_view._instant_sync_folder = sync_dir

        uploader_view._reset_ui()

        mock_mgr.stop.assert_called_once()
        assert uploader_view._instant_sync is None
        assert uploader_view._instant_sync_folder is None
        assert uploader_view._sync_status.text() == ""
