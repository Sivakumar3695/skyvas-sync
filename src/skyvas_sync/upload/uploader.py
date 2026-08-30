"""Background upload worker using QThread."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QThread, Signal

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.upload.scanner import scan_folder
from skyvas_sync.utils.image_utils import prepare_for_upload

# Maximum concurrent upload threads.
_MAX_WORKERS = 4


class UploadWorker(QThread):
    """Uploads images from a local folder to a Skyvas event in the background.

    Up to ``_MAX_WORKERS`` files are uploaded concurrently via a thread pool.

    Signals
    -------
    progress(uploaded, total, current_file)
        Emitted after each file is processed.
    file_done(file_path)
        Emitted when a single file has been uploaded successfully.
    file_error(file_path, error_message)
        Emitted when a single file fails to upload.
    finished_all()
        Emitted when the entire upload run completes (success or partial).
    error(message)
        Emitted on a fatal error that aborts the run.
    """

    progress = Signal(int, int, str)
    file_done = Signal(str)
    file_error = Signal(str, str)
    finished_all = Signal()
    error = Signal(str)

    def __init__(
        self,
        api_client: ApiClient,
        event_id: str,
        folders: list[Path],
        parent: object | None = None,
        *,
        files: list[Path] | None = None,
    ) -> None:
        super().__init__(parent)
        self.api_client = api_client
        self.event_id = event_id
        self.folders = folders
        self._files = files  # when set, skip folder scanning
        self._cancelled = False

    # -- public control -----------------------------------------------------

    def cancel(self) -> None:
        """Request cancellation (checked between files)."""
        self._cancelled = True

    # -- QThread entry point -------------------------------------------------

    def run(self) -> None:
        try:
            if self._files is not None:
                images: list[Path] = list(self._files)
            else:
                images = []
                seen: set[Path] = set()
                for folder in self.folders:
                    for img in scan_folder(folder):
                        resolved = img.resolve()
                        if resolved not in seen:
                            seen.add(resolved)
                            images.append(img)
            total = len(images)
            if total == 0:
                self.error.emit("No images found in the selected folder.")
                return

            # Signal initial status update on the event, but only when
            # it is still in "Created" state to avoid overwriting later
            # statuses (e.g. after a re-upload).
            try:
                event = self.api_client.get_event(self.event_id)
                if event.status_code == 0:
                    self.api_client.update_event_status(
                        self.event_id, "UPLOAD_IN_PROGRESS",
                    )
            except ApiError:
                pass  # non-fatal — proceed with uploads

            uploaded = 0
            lock = Lock()

            def _upload_task(image_path: Path) -> tuple[Path, Exception | None]:
                """Upload one file; return (path, None) on success or (path, exc) on failure."""
                if self._cancelled:
                    return image_path, Exception("Cancelled")
                try:
                    self._upload_single(image_path)
                    return image_path, None
                except Exception as exc:  # noqa: BLE001
                    return image_path, exc

            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                futures = {pool.submit(_upload_task, img): img for img in images}
                for future in as_completed(futures):
                    if self._cancelled:
                        # Cancel remaining futures; already-running ones will
                        # finish naturally but we stop queuing new work.
                        for f in futures:
                            f.cancel()
                        break
                    image_path, exc = future.result()
                    with lock:
                        if exc is None:
                            uploaded += 1
                            self.file_done.emit(str(image_path))
                        else:
                            self.file_error.emit(str(image_path), str(exc))
                        self.progress.emit(uploaded, total, image_path.name)

            self.progress.emit(uploaded, total, "")
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
        finally:
            self.finished_all.emit()

    # -- internal -----------------------------------------------------------

    _RETRY_DELAYS = (1, 3, 9)  # exponential backoff intervals in seconds

    def _upload_single(self, path: Path) -> None:
        """Upload a single image via the presigned-URL flow.

        Images over :data:`~skyvas_sync.utils.image_utils.MAX_UPLOAD_BYTES`
        are compressed first. Retries up to 3 times on failure with
        exponential backoff intervals of 1 s, 3 s, and 9 s.
        """
        image = prepare_for_upload(path)

        last_exc: Exception | None = None
        for attempt, delay in enumerate((*self._RETRY_DELAYS, None), start=1):
            try:
                url_info = self.api_client.get_upload_url(
                    self.event_id, image.filename, image.width, image.height,
                )
                self.api_client.upload_to_s3(
                    url_info.upload_url,
                    image.data,
                    image.mime_type,
                    image.width,
                    image.height,
                )
                return  # success
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if delay is None:
                    break  # all retries exhausted
                time.sleep(delay)

        raise last_exc  # type: ignore[misc]
