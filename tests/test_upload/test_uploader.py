"""Tests for skyvas_sync.upload.uploader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.api.models import Event, UploadUrl
from skyvas_sync.upload.uploader import UploadWorker


@pytest.fixture()
def mock_api() -> MagicMock:
    api = MagicMock(spec=ApiClient)
    api.get_upload_url.return_value = UploadUrl(
        upload_url="https://s3.example.com/put",
        file_url="https://s3.example.com/file.jpg",
    )
    api.upload_to_s3.return_value = None
    api.update_event_status.return_value = None
    api.get_event.return_value = Event(
        id="evt-1", name="Test", place="", date="",
        event_type="", status_code=0,
    )
    return api


@pytest.fixture()
def small_folder(tmp_path: Path) -> Path:
    root = tmp_path / "imgs"
    root.mkdir()
    for i in range(3):
        img = Image.new("RGB", (50 + i, 40 + i))
        img.save(root / f"img{i}.jpg")
    return root


class TestUploadWorker:
    def test_cancel(self, mock_api: MagicMock, small_folder: Path):
        worker = UploadWorker(mock_api, "evt-1", [small_folder])
        worker.cancel()
        assert worker._cancelled is True

    def test_upload_all_files(self, qtbot, mock_api: MagicMock, small_folder: Path):
        worker = UploadWorker(mock_api, "evt-1", [small_folder])

        progress_calls: list = []
        done_files: list = []
        finished = []

        worker.progress.connect(lambda u, t, f: progress_calls.append((u, t, f)))
        worker.file_done.connect(lambda p: done_files.append(p))
        worker.finished_all.connect(lambda: finished.append(True))

        with qtbot.waitSignal(worker.finished_all, timeout=10000):
            worker.start()

        assert len(done_files) == 3
        assert mock_api.get_upload_url.call_count == 3
        assert mock_api.upload_to_s3.call_count == 3
        # Only UPLOAD_IN_PROGRESS is called; UPLOADED is manual now
        assert mock_api.update_event_status.call_count == 1
        assert finished

    def test_upload_with_error(self, qtbot, mock_api: MagicMock, small_folder: Path):
        # Make the second upload fail
        call_count = {"n": 0}
        original = mock_api.upload_to_s3

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise ApiError(500, "server error")

        mock_api.upload_to_s3.side_effect = side_effect

        worker = UploadWorker(mock_api, "evt-1", [small_folder])
        error_files: list = []
        done_files: list = []
        worker.file_done.connect(lambda p: done_files.append(p))
        worker.file_error.connect(lambda p, e: error_files.append((p, e)))

        with qtbot.waitSignal(worker.finished_all, timeout=10000):
            worker.start()

        assert len(done_files) == 2
        assert len(error_files) == 1
        assert "server error" in error_files[0][1]

    def test_empty_folder_emits_error(self, qtbot, mock_api: MagicMock, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        worker = UploadWorker(mock_api, "evt-1", [empty])
        errors: list = []
        worker.error.connect(lambda msg: errors.append(msg))

        with qtbot.waitSignal(worker.finished_all, timeout=5000):
            worker.start()

        assert len(errors) == 1
        assert "No images" in errors[0]

    def test_cancel_stops_upload(self, qtbot, mock_api: MagicMock, small_folder: Path):
        worker = UploadWorker(mock_api, "evt-1", [small_folder])
        done_files: list = []
        worker.file_done.connect(lambda p: done_files.append(p))

        # Cancel immediately after starting
        def cancel_after_first(*args, **kwargs):
            worker.cancel()

        mock_api.upload_to_s3.side_effect = cancel_after_first

        with qtbot.waitSignal(worker.finished_all, timeout=10000):
            worker.start()

        # Should have uploaded 1 file and then stopped
        assert len(done_files) <= 1

    def test_update_status_failure_is_non_fatal(self, qtbot, mock_api: MagicMock, small_folder: Path):
        mock_api.get_event.side_effect = ApiError(500, "fail")

        worker = UploadWorker(mock_api, "evt-1", [small_folder])
        done_files: list = []
        worker.file_done.connect(lambda p: done_files.append(p))

        with qtbot.waitSignal(worker.finished_all, timeout=10000):
            worker.start()

        # Upload should still succeed even if status update fails
        assert len(done_files) == 3


class TestUploadSingle:
    def test_upload_single_file(self, mock_api: MagicMock, tmp_path: Path):
        img = Image.new("RGB", (100, 80))
        path = tmp_path / "test.jpg"
        img.save(path)

        worker = UploadWorker(mock_api, "evt-1", [tmp_path])
        worker._upload_single(path)

        mock_api.get_upload_url.assert_called_once_with("evt-1", "test.jpg", 100, 80)
        mock_api.upload_to_s3.assert_called_once()
        args = mock_api.upload_to_s3.call_args
        assert args[0][0] == "https://s3.example.com/put"
        assert args[0][2] == "image/jpeg"


class TestUploadWorkerRunDirect:
    """Call run() directly to ensure coverage of the method body."""

    def test_run_uploads_all(self, mock_api: MagicMock, small_folder: Path):
        worker = UploadWorker(mock_api, "evt-1", [small_folder])
        progress_calls: list = []
        done_files: list = []
        worker.progress.connect(lambda u, t, f: progress_calls.append((u, t, f)))
        worker.file_done.connect(lambda p: done_files.append(p))

        worker.run()

        assert len(done_files) == 3
        assert mock_api.get_upload_url.call_count == 3
        assert mock_api.upload_to_s3.call_count == 3
        # Only UPLOAD_IN_PROGRESS is called; UPLOADED is manual now
        calls = mock_api.update_event_status.call_args_list
        assert len(calls) == 1
        assert calls[0][0] == ("evt-1", "UPLOAD_IN_PROGRESS")

    def test_run_empty_folder(self, mock_api: MagicMock, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        worker = UploadWorker(mock_api, "evt-1", [empty])
        errors: list = []
        worker.error.connect(lambda msg: errors.append(msg))
        finished: list = []
        worker.finished_all.connect(lambda: finished.append(True))

        worker.run()

        assert len(errors) == 1
        assert "No images" in errors[0]
        assert finished

    def test_run_with_cancel(self, mock_api: MagicMock, small_folder: Path):
        worker = UploadWorker(mock_api, "evt-1", [small_folder])
        done_files: list = []
        worker.file_done.connect(lambda p: done_files.append(p))

        def cancel_after_first(*args, **kwargs):
            worker.cancel()

        mock_api.upload_to_s3.side_effect = cancel_after_first

        worker.run()

        assert len(done_files) <= 1

    def test_run_file_error_continues(self, mock_api: MagicMock, small_folder: Path):
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise ApiError(500, "server error")

        mock_api.upload_to_s3.side_effect = side_effect

        worker = UploadWorker(mock_api, "evt-1", [small_folder])
        done_files: list = []
        error_files: list = []
        worker.file_done.connect(lambda p: done_files.append(p))
        worker.file_error.connect(lambda p, e: error_files.append((p, e)))

        worker.run()

        assert len(done_files) == 2
        assert len(error_files) == 1

    def test_run_update_status_failure_nonfatal(self, mock_api: MagicMock, small_folder: Path):
        mock_api.get_event.side_effect = ApiError(500, "fail")
        worker = UploadWorker(mock_api, "evt-1", [small_folder])
        done_files: list = []
        worker.file_done.connect(lambda p: done_files.append(p))

        worker.run()

        assert len(done_files) == 3

    def test_run_fatal_exception(self, mock_api: MagicMock, tmp_path: Path):
        """Test the outer except block when scan_folder raises."""
        worker = UploadWorker(mock_api, "evt-1", [tmp_path / "nonexistent"])
        errors: list = []
        finished: list = []
        worker.error.connect(lambda msg: errors.append(msg))
        worker.finished_all.connect(lambda: finished.append(True))

        with patch("skyvas_sync.upload.uploader.scan_folder", side_effect=RuntimeError("crash")):
            worker.run()

        assert len(errors) == 1
        assert "crash" in errors[0]
        assert finished

    def test_run_skips_status_update_when_not_created(self, mock_api: MagicMock, small_folder: Path):
        """Status update should be skipped when event is not in CREATED state."""
        mock_api.get_event.return_value = Event(
            id="evt-1", name="Test", place="", date="",
            event_type="", status_code=1,  # UPLOAD_IN_PROGRESS
        )
        worker = UploadWorker(mock_api, "evt-1", [small_folder])
        done_files: list = []
        worker.file_done.connect(lambda p: done_files.append(p))

        worker.run()

        assert len(done_files) == 3
        mock_api.get_event.assert_called_once_with("evt-1")
        mock_api.update_event_status.assert_not_called()
