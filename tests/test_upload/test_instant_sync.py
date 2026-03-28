"""Tests for skyvas_sync.upload.instant_sync."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.api.models import Event, UploadUrl
from skyvas_sync.upload.instant_sync import InstantSyncManager, _BatchUploadThread


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_image(path: Path, size: tuple[int, int] = (50, 40)) -> None:
    img = Image.new("RGB", size, color="green")
    img.save(path)


@pytest.fixture()
def mock_api() -> MagicMock:
    api = MagicMock(spec=ApiClient)
    api.get_upload_url.return_value = UploadUrl(
        upload_url="https://s3.example.com/put",
        file_url="https://s3.example.com/file.jpg",
    )
    api.upload_to_s3.return_value = None
    api.get_event.return_value = Event(
        id="evt-1", name="Test", place="", date="",
        event_type="", status_code=0,
    )
    return api


# ---------------------------------------------------------------------------
# _BatchUploadThread
# ---------------------------------------------------------------------------

class TestBatchUploadThread:
    def test_upload_all_files(self, mock_api: MagicMock, tmp_path: Path):
        for i in range(3):
            _create_image(tmp_path / f"img{i}.jpg")
        files = sorted(tmp_path.glob("*.jpg"))

        thread = _BatchUploadThread(mock_api, "evt-1", files)
        done: list[str] = []
        errors: list[tuple[str, str]] = []
        finished: list[bool] = []
        thread.file_done.connect(lambda p: done.append(p))
        thread.file_error.connect(lambda p, e: errors.append((p, e)))
        thread.finished_all.connect(lambda: finished.append(True))

        thread.run()

        assert len(done) == 3
        assert len(errors) == 0
        assert finished
        assert mock_api.get_upload_url.call_count == 3
        assert mock_api.upload_to_s3.call_count == 3

    def test_upload_with_error(self, mock_api: MagicMock, tmp_path: Path):
        _create_image(tmp_path / "a.jpg")
        _create_image(tmp_path / "b.jpg")
        files = sorted(tmp_path.glob("*.jpg"))

        call_count = {"n": 0}

        def side_effect(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise ApiError(500, "server error")

        mock_api.upload_to_s3.side_effect = side_effect

        thread = _BatchUploadThread(mock_api, "evt-1", files)
        done: list[str] = []
        errors: list[tuple[str, str]] = []
        thread.file_done.connect(lambda p: done.append(p))
        thread.file_error.connect(lambda p, e: errors.append((p, e)))

        thread.run()

        assert len(done) == 1
        assert len(errors) == 1
        assert "server error" in errors[0][1]

    def test_cancel_stops_upload(self, mock_api: MagicMock, tmp_path: Path):
        for i in range(3):
            _create_image(tmp_path / f"img{i}.jpg")
        files = sorted(tmp_path.glob("*.jpg"))

        thread = _BatchUploadThread(mock_api, "evt-1", files)
        done: list[str] = []
        thread.file_done.connect(lambda p: done.append(p))

        def cancel_after_first(*a, **kw):
            thread.cancel()

        mock_api.upload_to_s3.side_effect = cancel_after_first
        thread.run()

        assert len(done) <= 1

    def test_cancel_flag(self, mock_api: MagicMock, tmp_path: Path):
        thread = _BatchUploadThread(mock_api, "evt-1", [])
        assert not thread._cancelled
        thread.cancel()
        assert thread._cancelled

    def test_empty_file_list(self, mock_api: MagicMock, tmp_path: Path):
        thread = _BatchUploadThread(mock_api, "evt-1", [])
        finished: list[bool] = []
        thread.finished_all.connect(lambda: finished.append(True))
        thread.run()
        assert finished
        assert mock_api.get_upload_url.call_count == 0


# ---------------------------------------------------------------------------
# InstantSyncManager — lifecycle
# ---------------------------------------------------------------------------

class TestInstantSyncManagerLifecycle:
    def test_initial_state(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        assert not mgr.is_active
        assert mgr.folder == tmp_path
        assert mgr.uploaded_count == 0
        assert mgr.total_count == 0
        assert mgr.failed_count == 0

    def test_start_emits_signal(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        signals: list[bool] = []
        mgr.sync_started.connect(lambda: signals.append(True))
        mgr.start()
        assert mgr.is_active
        assert len(signals) == 1
        mgr.stop()

    def test_stop_emits_signal(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()
        signals: list[bool] = []
        mgr.sync_stopped.connect(lambda: signals.append(True))
        mgr.stop()
        assert not mgr.is_active
        assert len(signals) == 1

    def test_start_twice_is_noop(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        signals: list[bool] = []
        mgr.sync_started.connect(lambda: signals.append(True))
        mgr.start()
        mgr.start()
        assert len(signals) == 1
        mgr.stop()

    def test_stop_when_not_active(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        signals: list[bool] = []
        mgr.sync_stopped.connect(lambda: signals.append(True))
        mgr.stop()  # Should not raise
        assert len(signals) == 0

    def test_stop_cancels_running_worker(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()

        # Inject a mock running worker
        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mgr._worker = mock_worker

        mgr.stop()
        mock_worker.cancel.assert_called_once()
        mock_worker.wait.assert_called_once()


# ---------------------------------------------------------------------------
# InstantSyncManager — new file handling
# ---------------------------------------------------------------------------

class TestInstantSyncManagerNewFiles:
    def test_on_new_file_queues_and_uploads(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()

        _create_image(tmp_path / "new.jpg")

        progress: list[tuple[int, int, str]] = []
        mgr.upload_progress.connect(lambda u, t, c: progress.append((u, t, c)))

        # Simulate watcher detecting a new file
        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            instance = MockThread.return_value
            instance.file_done = MagicMock()
            instance.file_done.connect = MagicMock()
            instance.file_error = MagicMock()
            instance.file_error.connect = MagicMock()
            instance.finished_all = MagicMock()
            instance.finished_all.connect = MagicMock()
            instance.start = MagicMock()
            instance.isRunning.return_value = False

            mgr._on_new_file(str(tmp_path / "new.jpg"))

            assert mgr.total_count == 1
            assert len(progress) == 1
            MockThread.assert_called_once()
            instance.start.assert_called_once()

        mgr.stop()

    def test_on_new_file_inactive_ignored(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        # Not started
        mgr._on_new_file(str(tmp_path / "file.jpg"))
        assert mgr.total_count == 0

    def test_on_file_done_updates_counts(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()

        uploaded: list[str] = []
        progress: list[tuple[int, int, str]] = []
        mgr.file_uploaded.connect(lambda p: uploaded.append(p))
        mgr.upload_progress.connect(lambda u, t, c: progress.append((u, t, c)))

        mgr._total = 3
        mgr._on_file_done("/path/to/img.jpg")

        assert mgr.uploaded_count == 1
        assert len(uploaded) == 1
        assert len(progress) == 1
        assert progress[0] == (1, 3, "img.jpg")
        mgr.stop()

    def test_on_file_error_updates_counts(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()

        errors: list[tuple[str, str]] = []
        mgr.file_error.connect(lambda p, e: errors.append((p, e)))

        mgr._on_file_error("/path/to/bad.jpg", "timeout")

        assert mgr.failed_count == 1
        assert len(errors) == 1
        mgr.stop()


# ---------------------------------------------------------------------------
# InstantSyncManager — _process_queue
# ---------------------------------------------------------------------------

class TestInstantSyncManagerQueue:
    def test_process_queue_empty_is_noop(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()
        mgr._process_queue()  # Should not raise, no worker created
        assert mgr._worker is None
        mgr.stop()

    def test_process_queue_inactive_is_noop(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        # Not started
        mgr._queue.append(tmp_path / "test.jpg")
        mgr._process_queue()
        assert mgr._worker is None

    def test_process_queue_waits_for_running_worker(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()

        mock_worker = MagicMock()
        mock_worker.isRunning.return_value = True
        mgr._worker = mock_worker
        mgr._queue.append(tmp_path / "test.jpg")

        mgr._process_queue()
        # Queue should not be cleared because worker is running
        assert len(mgr._queue) == 1
        mgr.stop()

    def test_batch_finished_processes_remaining_queue(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()

        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            instance = MockThread.return_value
            instance.file_done = MagicMock()
            instance.file_done.connect = MagicMock()
            instance.file_error = MagicMock()
            instance.file_error.connect = MagicMock()
            instance.finished_all = MagicMock()
            instance.finished_all.connect = MagicMock()
            instance.start = MagicMock()
            instance.isRunning.return_value = False

            # Add a file to queue and process
            mgr._queue.append(tmp_path / "delayed.jpg")
            mgr._on_batch_finished()

            # Should have created a new worker for the queued file
            MockThread.assert_called_once()

        mgr.stop()


# ---------------------------------------------------------------------------
# InstantSyncManager — integration (mock thread, test wiring)
# ---------------------------------------------------------------------------

class TestInstantSyncManagerStatusUpdate:
    """Verify that the event status is set to UPLOAD_IN_PROGRESS on first batch."""

    def _make_mock_thread(self):
        instance = MagicMock()
        instance.file_done = MagicMock()
        instance.file_done.connect = MagicMock()
        instance.file_error = MagicMock()
        instance.file_error.connect = MagicMock()
        instance.finished_all = MagicMock()
        instance.finished_all.connect = MagicMock()
        instance.start = MagicMock()
        instance.isRunning.return_value = False
        return instance

    def test_status_updated_on_first_batch(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)
        mgr.start()

        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            MockThread.return_value = self._make_mock_thread()
            mgr._on_new_file(str(tmp_path / "first.jpg"))

        mock_api.update_event_status.assert_called_once_with("evt-1", "UPLOAD_IN_PROGRESS")
        mgr.stop()

    def test_status_not_updated_on_subsequent_batches(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)
        mgr.start()

        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            MockThread.return_value = self._make_mock_thread()
            mgr._on_new_file(str(tmp_path / "first.jpg"))

            mock_api.update_event_status.reset_mock()

            # Second batch
            MockThread.return_value = self._make_mock_thread()
            mgr._worker = None  # simulate previous worker finished
            mgr._on_new_file(str(tmp_path / "second.jpg"))

        mock_api.update_event_status.assert_not_called()
        mgr.stop()

    def test_status_update_api_error_is_non_fatal(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mock_api.get_event.side_effect = ApiError(500, "server error")

        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)
        mgr.start()

        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            MockThread.return_value = self._make_mock_thread()
            mgr._on_new_file(str(tmp_path / "file.jpg"))

            # Should still create the worker despite the status update error
            MockThread.assert_called_once()
            MockThread.return_value.start.assert_called_once()

        mgr.stop()

    def test_status_flag_resets_on_restart(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)
        mgr.start()

        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            MockThread.return_value = self._make_mock_thread()
            mgr._on_new_file(str(tmp_path / "f1.jpg"))

        mock_api.update_event_status.assert_called_once()
        mgr.stop()

        # Restart — flag should be reset
        mock_api.update_event_status.reset_mock()
        mgr.start()

        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            MockThread.return_value = self._make_mock_thread()
            mgr._on_new_file(str(tmp_path / "f2.jpg"))

        mock_api.update_event_status.assert_called_once_with("evt-1", "UPLOAD_IN_PROGRESS")
        mgr.stop()

    def test_status_not_updated_when_not_created(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        """Status update should be skipped when event is not in CREATED state."""
        mock_api.get_event.return_value = Event(
            id="evt-1", name="Test", place="", date="",
            event_type="", status_code=2,  # UPLOADED
        )
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)
        mgr.start()

        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            MockThread.return_value = self._make_mock_thread()
            mgr._on_new_file(str(tmp_path / "file.jpg"))

            MockThread.assert_called_once()
            MockThread.return_value.start.assert_called_once()

        mock_api.get_event.assert_called_once_with("evt-1")
        mock_api.update_event_status.assert_not_called()
        mgr.stop()


class TestInstantSyncManagerIntegration:
    def test_end_to_end_via_mock_thread(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        """Verify _on_new_file → _process_queue → worker creation → callbacks."""
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()

        _create_image(tmp_path / "live.jpg")

        uploaded: list[str] = []
        mgr.file_uploaded.connect(lambda p: uploaded.append(p))

        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            instance = MockThread.return_value
            instance.file_done = MagicMock()
            instance.file_done.connect = MagicMock()
            instance.file_error = MagicMock()
            instance.file_error.connect = MagicMock()
            instance.finished_all = MagicMock()
            instance.finished_all.connect = MagicMock()
            instance.start = MagicMock()
            instance.isRunning.return_value = False

            mgr._on_new_file(str(tmp_path / "live.jpg"))

            MockThread.assert_called_once()
            call_args = MockThread.call_args
            assert len(call_args[0][2]) == 1  # one file in batch
            instance.start.assert_called_once()

        assert mgr.total_count == 1

        # Simulate upload completion callback
        mgr._on_file_done(str(tmp_path / "live.jpg"))
        assert mgr.uploaded_count == 1
        assert len(uploaded) == 1
        assert "live.jpg" in uploaded[0]
        mgr.stop()

    def test_multiple_files_queued_before_worker(self, qtbot, tmp_path: Path, mock_api: MagicMock):
        mgr = InstantSyncManager(mock_api, "evt-1", tmp_path, stabilize_ms=0)

        mgr.start()

        for i in range(3):
            _create_image(tmp_path / f"batch{i}.jpg")

        with patch("skyvas_sync.upload.instant_sync._BatchUploadThread") as MockThread:
            instance = MockThread.return_value
            instance.file_done = MagicMock()
            instance.file_done.connect = MagicMock()
            instance.file_error = MagicMock()
            instance.file_error.connect = MagicMock()
            instance.finished_all = MagicMock()
            instance.finished_all.connect = MagicMock()
            instance.start = MagicMock()
            instance.isRunning.return_value = False

            # Queue 3 files manually
            for i in range(3):
                mgr._queue.append(tmp_path / f"batch{i}.jpg")
                mgr._total += 1

            mgr._process_queue()

            # Should have created one worker with all 3 files
            MockThread.assert_called_once()
            call_args = MockThread.call_args
            assert len(call_args[0][2]) == 3

        mgr.stop()
