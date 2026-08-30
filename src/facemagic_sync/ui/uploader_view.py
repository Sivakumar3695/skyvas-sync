"""Uploader view — folder selection, upload start/cancel, progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.api.models import Event, UploadStatus
from skyvas_sync.settings_store import SettingsStore
from skyvas_sync.upload.scanner import scan_folder
from skyvas_sync.upload.uploader import UploadWorker


class UploaderView(QWidget):
    """Upload tab: select a folder, start uploading, watch progress.

    Signals
    -------
    upload_status_changed(UploadStatus)
        Emitted whenever the upload progress changes.
    """

    upload_status_changed = Signal(object)
    backend_status_changed = Signal(str, str)

    def __init__(
        self,
        api_client: ApiClient,
        settings: SettingsStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._settings = settings
        self._event: Event | None = None
        self._folders: list[Path] = []
        self._worker: UploadWorker | None = None
        self._status = UploadStatus(event_id="")
        self._setup_ui()

    # -- UI -----------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Folder selection header + browse button
        folder_header = QHBoxLayout()
        self._folder_heading = QLabel("Selected folders:")
        self._folder_heading.setStyleSheet("color: #666; font-weight: bold;")
        folder_header.addWidget(self._folder_heading, stretch=1)

        self._browse_btn = QPushButton("Add Folder")
        self._browse_btn.clicked.connect(self._on_browse)
        folder_header.addWidget(self._browse_btn)
        layout.addLayout(folder_header)

        # Container for folder rows (each with label + remove button)
        self._folders_widget = QWidget()
        self._folders_layout = QVBoxLayout(self._folders_widget)
        self._folders_layout.setContentsMargins(0, 0, 0, 0)
        self._folders_layout.setSpacing(2)

        self._no_folder_label = QLabel("No folder selected")
        self._no_folder_label.setStyleSheet("color: #999; font-style: italic;")
        self._folders_layout.addWidget(self._no_folder_label)

        layout.addWidget(self._folders_widget)

        # Image count
        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #444; margin: 4px 0;")
        layout.addWidget(self._count_label)

        # Action buttons
        btn_layout = QHBoxLayout()
        self._start_btn = QPushButton("Start Upload")
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start)
        btn_layout.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._cancel_btn)

        self._complete_btn = QPushButton("Mark Upload Complete")
        self._complete_btn.setEnabled(False)
        self._complete_btn.setVisible(False)
        self._complete_btn.clicked.connect(self._on_mark_complete)
        btn_layout.addWidget(self._complete_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        # Current file label
        self._current_file = QLabel("")
        self._current_file.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._current_file)

        # Log area
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(150)
        self._log.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._log)

        layout.addStretch()

    # -- public API ---------------------------------------------------------

    def set_event(self, event: Event) -> None:
        """Configure the view for a specific event."""
        self._event = event
        self._status = UploadStatus(event_id=event.id)
        self._reset_ui()
        # Restore all previously selected folders for this event
        saved_folders = self._settings.get_event_folders(event.id)
        for folder in saved_folders:
            self._apply_folder(folder)

    # -- handlers -----------------------------------------------------------

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select image folder")
        if not folder:
            return
        self._apply_folder(Path(folder))

    def _apply_folder(self, folder: Path) -> None:
        """Add a folder to the list, update UI, and persist the mapping."""
        if folder in self._folders:
            return
        self._folders.append(folder)
        self._add_folder_row(folder)
        self._update_image_count()
        # Persist folder ↔ event mapping
        if self._event is not None:
            self._settings.set_event_folder(self._event.id, folder)

    def _add_folder_row(self, folder: Path) -> None:
        """Add a row widget for *folder* into the folders container."""
        # Hide the placeholder
        self._no_folder_label.setVisible(False)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        label = QLabel(str(folder))
        label.setStyleSheet("color: #333;")
        row_layout.addWidget(label, stretch=1)

        remove_btn = QPushButton("\u2715")
        remove_btn.setFixedSize(22, 22)
        remove_btn.setStyleSheet(
            "QPushButton { color: #888; background: transparent; border: none; font-size: 13px; }"
            "QPushButton:hover { color: #d44; }"
        )
        remove_btn.setToolTip("Remove this folder")
        remove_btn.clicked.connect(lambda checked=False, f=folder: self._remove_folder(f))
        row_layout.addWidget(remove_btn)

        # Store the folder path on the row widget for easy removal
        row.setProperty("folder_path", str(folder))
        self._folders_layout.addWidget(row)

    def _remove_folder(self, folder: Path) -> None:
        """Remove a folder from the list and update UI."""
        if folder not in self._folders:
            return
        self._folders.remove(folder)
        # Remove the row widget
        folder_str = str(folder)
        for i in range(self._folders_layout.count()):
            widget = self._folders_layout.itemAt(i).widget()
            if widget and widget.property("folder_path") == folder_str:
                widget.deleteLater()
                self._folders_layout.removeWidget(widget)
                break
        self._update_image_count()
        if not self._folders:
            self._no_folder_label.setVisible(True)

    def _update_image_count(self) -> None:
        """Recount images across all selected folders."""
        total = 0
        for folder in self._folders:
            total += len(scan_folder(folder))
        self._count_label.setText(f"{total} image(s) found")
        self._status.total = total
        self._start_btn.setEnabled(total > 0)

    def _on_start(self) -> None:
        if self._event is None or not self._folders:
            return
        # Mark the event as "in progress" on the backend immediately so the
        # events list can reflect the state without waiting for the worker.
        try:
            self._api.update_event_status(self._event.id, "UPLOAD_IN_PROGRESS")
            # Notify the main window so it can refresh the events list/UI.
            self.backend_status_changed.emit(self._event.id, "UPLOAD_IN_PROGRESS")
        except ApiError as exc:
            # Non-fatal — log and continue with uploads
            self._log.append(f"ERROR setting status: {exc}")
        self._start_btn.setEnabled(False)
        self._browse_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._complete_btn.setEnabled(False)
        self._log.clear()
        self._status.uploaded = 0
        self._status.failed = 0
        self._status.errors.clear()

        self._worker = UploadWorker(
            self._api, self._event.id, list(self._folders),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.file_error.connect(self._on_file_error)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.error.connect(self._on_fatal_error)
        self._worker.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._cancel_btn.setEnabled(False)

    def _on_progress(self, uploaded: int, total: int, current: str) -> None:
        pct = int(uploaded / total * 100) if total else 0
        self._progress_bar.setValue(pct)
        count_str = f"{uploaded} / {total}" if total else ""
        if current:
            self._current_file.setText(f"Uploading {count_str}: {current}")
        elif count_str:
            self._current_file.setText(f"Uploading {count_str}…")
        else:
            self._current_file.setText("")
        self._status.uploaded = uploaded
        self._status.total = total
        self.upload_status_changed.emit(self._status)

    def _on_file_done(self, path: str) -> None:
        self._log.append(f"✓ {Path(path).name}")

    def _on_file_error(self, path: str, error: str) -> None:
        self._status.failed += 1
        self._status.errors.append(f"{path}: {error}")
        self._log.append(f"✗ {Path(path).name}: {error}")

    def _on_finished(self) -> None:
        self._start_btn.setEnabled(True)
        self._browse_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        uploaded = self._status.uploaded
        total = self._status.total
        failed = self._status.failed
        self._current_file.setText(
            f"Done — {uploaded} uploaded, {failed} failed out of {total}",
        )
        # Show the "Mark Upload Complete" button so the user can finalise
        self._complete_btn.setVisible(True)
        self._complete_btn.setEnabled(True)
        self.upload_status_changed.emit(self._status)
        self._worker = None

    def _on_mark_complete(self) -> None:
        """Mark the event upload as completed via the API."""
        if self._event is None:
            return
        try:
            self._api.update_event_status(self._event.id, "UPLOADED")
            self._complete_btn.setEnabled(False)
            self._current_file.setText("Upload marked as complete.")
        except ApiError as exc:
            self._log.append(f"ERROR marking complete: {exc}")

    def _on_fatal_error(self, message: str) -> None:
        self._log.append(f"ERROR: {message}")

    # -- helpers ------------------------------------------------------------

    def _reset_ui(self) -> None:
        self._folders = []
        # Remove folder row widgets (skip the _no_folder_label at index 0)
        while self._folders_layout.count() > 1:
            item = self._folders_layout.takeAt(1)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._no_folder_label.setVisible(True)
        self._count_label.setText("")
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._complete_btn.setEnabled(False)
        self._complete_btn.setVisible(False)
        self._progress_bar.setValue(0)
        self._current_file.setText("")
        self._log.clear()
