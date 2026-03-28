"""Background upload worker using QThread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.upload.scanner import scan_folder
from skyvas_sync.utils.image_utils import get_image_dimensions, get_mime_type


class UploadWorker(QThread):
    """Uploads images from a local folder to a Skyvas event in the background.

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
    ) -> None:
        super().__init__(parent)
        self.api_client = api_client
        self.event_id = event_id
        self.folders = folders
        self._cancelled = False

    # -- public control -----------------------------------------------------

    def cancel(self) -> None:
        """Request cancellation (checked between files)."""
        self._cancelled = True

    # -- QThread entry point -------------------------------------------------

    def run(self) -> None:
        try:
            images: list[Path] = []
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
            for image_path in images:
                if self._cancelled:
                    break

                file_name = image_path.name
                self.progress.emit(uploaded, total, file_name)

                try:
                    self._upload_single(image_path)
                    uploaded += 1
                    self.file_done.emit(str(image_path))
                except Exception as exc:  # noqa: BLE001
                    self.file_error.emit(str(image_path), str(exc))

            self.progress.emit(uploaded, total, "")
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
        finally:
            self.finished_all.emit()

    # -- internal -----------------------------------------------------------

    def _upload_single(self, path: Path) -> None:
        """Upload a single image via the presigned-URL flow."""
        width, height = get_image_dimensions(path)
        mime = get_mime_type(path)

        url_info = self.api_client.get_upload_url(
            self.event_id, path.name, width, height,
        )

        file_bytes = path.read_bytes()
        self.api_client.upload_to_s3(
            url_info.upload_url, file_bytes, mime, width, height,
        )
