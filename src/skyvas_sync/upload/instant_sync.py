"""Instant sync — automatic upload of new images detected in a watched folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.upload.watcher import FolderWatcher
from skyvas_sync.utils.image_utils import get_image_dimensions, get_mime_type


class _BatchUploadThread(QThread):
    """Uploads a batch of image files in the background."""

    file_done = Signal(str)
    file_error = Signal(str, str)
    finished_all = Signal()

    def __init__(
        self,
        api_client: ApiClient,
        event_id: str,
        files: list[Path],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._event_id = event_id
        self._files = files
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for path in self._files:
            if self._cancelled:
                break
            try:
                width, height = get_image_dimensions(path)
                mime = get_mime_type(path)
                url_info = self._api.get_upload_url(
                    self._event_id, path.name, width, height,
                )
                file_bytes = path.read_bytes()
                self._api.upload_to_s3(
                    url_info.upload_url, file_bytes, mime, width, height,
                )
                self.file_done.emit(str(path))
            except Exception as exc:
                self.file_error.emit(str(path), str(exc))
        self.finished_all.emit()


class InstantSyncManager(QObject):
    """Watches a folder for new images and uploads them automatically.

    Lifecycle:
      1. ``start()`` — begin watching; existing images in the folder are
         recorded as baseline (not uploaded).
      2. New images appearing in the folder or its sub-folders are queued
         and uploaded in background batches.
      3. ``stop()`` — stop watching and cancel any in-flight upload.
    """

    file_uploaded = Signal(str)
    file_error = Signal(str, str)
    upload_progress = Signal(int, int, str)  # uploaded, total, current_file
    sync_started = Signal()
    sync_stopped = Signal()

    def __init__(
        self,
        api_client: ApiClient,
        event_id: str,
        folder: Path,
        parent: QObject | None = None,
        *,
        stabilize_ms: int = 1000,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._event_id = event_id
        self._folder = folder
        self._watcher = FolderWatcher(folder, parent=self, stabilize_ms=stabilize_ms)
        self._queue: list[Path] = []
        self._worker: _BatchUploadThread | None = None
        self._uploaded = 0
        self._total = 0
        self._failed = 0
        self._active = False
        self._status_updated = False

    # -- public properties ---------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def uploaded_count(self) -> int:
        return self._uploaded

    @property
    def total_count(self) -> int:
        return self._total

    @property
    def failed_count(self) -> int:
        return self._failed

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Start watching the folder and uploading new images."""
        if self._active:
            return

        self._active = True
        self._uploaded = 0
        self._total = 0
        self._failed = 0
        self._status_updated = False
        self._queue.clear()

        self._watcher.file_found.connect(self._on_new_file)
        self._watcher.start()

        self.sync_started.emit()

    def stop(self) -> None:
        """Stop watching and cancel any in-progress upload."""
        if not self._active:
            return

        self._active = False
        self._watcher.stop()
        try:
            self._watcher.file_found.disconnect(self._on_new_file)
        except (RuntimeError, TypeError):
            pass

        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        self._worker = None
        self.sync_stopped.emit()

    # -- internal slots ------------------------------------------------------

    def _on_new_file(self, path_str: str) -> None:
        if not self._active:
            return
        self._queue.append(Path(path_str))
        self._total += 1
        self.upload_progress.emit(self._uploaded, self._total, "")
        self._process_queue()

    def _process_queue(self) -> None:
        if not self._active:
            return
        if self._worker is not None and self._worker.isRunning():
            return  # Will be called again when current batch finishes
        if not self._queue:
            return

        # Update event status to "Upload In Progress" on the first batch,
        # but only if the event is still in "Created" state.
        if not self._status_updated:
            self._status_updated = True
            try:
                event = self._api.get_event(self._event_id)
                if event.status_code == 0:
                    self._api.update_event_status(
                        self._event_id, "UPLOAD_IN_PROGRESS",
                    )
            except ApiError:
                pass  # non-fatal — proceed with uploads

        batch = list(self._queue)
        self._queue.clear()

        self._worker = _BatchUploadThread(self._api, self._event_id, batch)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.file_error.connect(self._on_file_error)
        self._worker.finished_all.connect(self._on_batch_finished)
        self._worker.start()

    def _on_file_done(self, path: str) -> None:
        self._uploaded += 1
        self.file_uploaded.emit(path)
        self.upload_progress.emit(self._uploaded, self._total, Path(path).name)

    def _on_file_error(self, path: str, error: str) -> None:
        self._failed += 1
        self.file_error.emit(path, error)

    def _on_batch_finished(self) -> None:
        self._worker = None
        # Process any files that arrived during the current batch
        self._process_queue()
