"""Uploader view — folder selection, upload start/cancel, progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from skyvas_sync.ui.folder_dialog import AsyncFolderDialog

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.api.models import Event, UploadStatus
from skyvas_sync.settings_store import SettingsStore
from skyvas_sync.upload.instant_sync import InstantSyncManager
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
        self._failed_paths: list[Path] = []
        self._instant_sync: InstantSyncManager | None = None
        self._instant_sync_folder: Path | None = None
        self._poll_countdown: int = 0
        self._poll_tick_timer: QTimer | None = None
        self._setup_ui()

    # -- UI -----------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Folder selection header + browse button
        folder_header = QHBoxLayout()
        self._folder_heading = QLabel("Selected folders:")
        self._folder_heading.setStyleSheet("color: #6B7280; font-weight: 600;")
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
        self._no_folder_label.setStyleSheet("color: #9CA3AF; font-style: italic;")
        self._folders_layout.addWidget(self._no_folder_label)

        layout.addWidget(self._folders_widget)

        # Image count
        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #374151; margin: 4px 0;")
        layout.addWidget(self._count_label)

        # Locked notice (shown when event status >= 2 and uploads are disabled)
        self._locked_label = QLabel("")
        self._locked_label.setStyleSheet(
            "color: #B45309; background: #FEF3C7; border-radius: 4px;"
            "padding: 4px 8px; font-size: 13px;"
        )
        self._locked_label.setVisible(False)
        layout.addWidget(self._locked_label)

        # Action buttons
        btn_layout = QHBoxLayout()
        self._start_btn = QPushButton("Start Upload")
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start)
        btn_layout.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setProperty("styleClass", "secondary")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._cancel_btn)

        self._complete_btn = QPushButton("Mark Upload Complete")
        self._complete_btn.setEnabled(False)
        self._complete_btn.setVisible(False)
        self._complete_btn.clicked.connect(self._on_mark_complete)
        btn_layout.addWidget(self._complete_btn)

        self._retry_btn = QPushButton("Retry Failed")
        self._retry_btn.setEnabled(False)
        self._retry_btn.setVisible(False)
        self._retry_btn.setProperty("styleClass", "danger")
        self._retry_btn.clicked.connect(self._on_retry_failed)
        btn_layout.addWidget(self._retry_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        # Current file label
        self._current_file = QLabel("")
        self._current_file.setStyleSheet("color: #6B7280; font-size: 14px;")
        layout.addWidget(self._current_file)

        # Log area
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(150)
        self._log.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._log)

        # ── Instant Sync section ────────────────────────────────────
        sync_heading = QLabel("Instant Sync")
        sync_heading.setStyleSheet(
            "font-size: 16px; font-weight: 700; margin-top: 14px; color: #1A1A2E;"
        )
        layout.addWidget(sync_heading)

        sync_row = QHBoxLayout()
        self._sync_folder_label = QLabel("No folder selected")
        self._sync_folder_label.setStyleSheet(
            "color: #9CA3AF; font-style: italic;"
        )
        sync_row.addWidget(self._sync_folder_label, stretch=1)

        self._sync_browse_btn = QPushButton("Select Folder")
        self._sync_browse_btn.setProperty("styleClass", "secondary")
        self._sync_browse_btn.clicked.connect(self._on_sync_browse)
        sync_row.addWidget(self._sync_browse_btn)

        self._sync_clear_btn = QPushButton("\u2715")
        self._sync_clear_btn.setFixedSize(22, 22)
        self._sync_clear_btn.setProperty("styleClass", "ghost")
        self._sync_clear_btn.setToolTip("Stop instant sync and remove folder")
        self._sync_clear_btn.setEnabled(False)
        self._sync_clear_btn.clicked.connect(self._on_sync_clear)
        sync_row.addWidget(self._sync_clear_btn)

        layout.addLayout(sync_row)

        self._sync_status = QLabel("")
        self._sync_status.setStyleSheet("color: #6B7280; font-size: 14px;")
        layout.addWidget(self._sync_status)

        # Polling status row
        poll_row = QHBoxLayout()
        self._poll_indicator = QLabel("")
        self._poll_indicator.setStyleSheet("color: #888; font-size: 13px;")
        poll_row.addWidget(self._poll_indicator, stretch=1)
        self._poll_countdown_label = QLabel("")
        self._poll_countdown_label.setStyleSheet("color: #888; font-size: 13px;")
        poll_row.addWidget(self._poll_countdown_label)
        layout.addLayout(poll_row)

        self._sync_log = QTextEdit()
        self._sync_log.setReadOnly(True)
        self._sync_log.setMaximumHeight(100)
        self._sync_log.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._sync_log)

        layout.addStretch()

    # -- public API ---------------------------------------------------------

    @property
    def instant_sync_folder(self) -> Path | None:
        """The active instant-sync folder, if any."""
        return self._instant_sync_folder

    @property
    def _is_upload_locked(self) -> bool:
        """Return True when the event status no longer allows new uploads."""
        return self._event is not None and self._event.status_code >= 2

    def set_event(self, event: Event) -> None:
        """Configure the view for a specific event."""
        self._event = event
        self._status = UploadStatus(event_id=event.id)
        self._reset_ui()
        # Restore all previously selected folders for this event
        saved_folders = self._settings.get_event_folders(event.id)
        for folder in saved_folders:
            self._apply_folder(folder)
        # Restore instant-sync folder if previously configured
        saved_sync = self._settings.get_instant_sync_folder(event.id)
        if saved_sync is not None:
            self._start_instant_sync(saved_sync)
        # Lock upload controls when the event is past the upload stage
        if self._is_upload_locked:
            self._browse_btn.setEnabled(False)
            self._start_btn.setEnabled(False)
            self._locked_label.setText(
                f"\u26a0\ufe0f Uploads are disabled — event status is \"{event.status_label}\"."
            )
            self._locked_label.setVisible(True)

    # -- handlers -----------------------------------------------------------

    def _make_folder_dialog(self, title: str) -> AsyncFolderDialog:
        """Create an async folder browser safe for MTP/GVFS devices."""
        return AsyncFolderDialog(self, title)

    def _on_browse(self) -> None:
        dlg = self._make_folder_dialog("Select image folder")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.selected_path()
        if selected is None:
            return
        self._apply_folder(selected)

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
        label.setStyleSheet("color: #374151;")
        row_layout.addWidget(label, stretch=1)

        remove_btn = QPushButton("\u2715")
        remove_btn.setFixedSize(22, 22)
        remove_btn.setProperty("styleClass", "ghost")
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
        self._start_btn.setEnabled(total > 0 and not self._is_upload_locked)

    def _on_start(self) -> None:
        if self._event is None or not self._folders:
            return
        self._start_upload_worker(list(self._folders))

    def _on_retry_failed(self) -> None:
        if self._event is None or not self._failed_paths:
            return
        self._start_upload_worker([], files=list(self._failed_paths))

    def _start_upload_worker(
        self,
        folders: list[Path],
        *,
        files: list[Path] | None = None,
    ) -> None:
        if self._event is None:
            return
        self._start_btn.setEnabled(False)
        self._browse_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._complete_btn.setEnabled(False)
        self._retry_btn.setEnabled(False)
        self._retry_btn.setVisible(False)
        self._log.clear()
        self._status.uploaded = 0
        self._status.failed = 0
        self._status.errors.clear()
        self._failed_paths = []

        self._worker = UploadWorker(
            self._api, self._event.id, folders, files=files,
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
        self._failed_paths.append(Path(path))

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
        # Show "Retry Failed" button when there are failed files
        if failed > 0:
            self._retry_btn.setText(f"Retry Failed ({failed})")
            self._retry_btn.setVisible(True)
            self._retry_btn.setEnabled(True)
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
        # Stop instant sync when upload is marked complete
        self._stop_instant_sync()
        if self._event is not None:
            self._settings.clear_instant_sync_folder(self._event.id)
        self._sync_folder_label.setText("No folder selected")
        self._sync_folder_label.setStyleSheet("color: #9CA3AF; font-style: italic;")
        self._sync_clear_btn.setEnabled(False)
        self._sync_status.setText("")
        self._poll_indicator.setText("")
        self._poll_countdown_label.setText("")

    def _on_fatal_error(self, message: str) -> None:
        self._log.append(f"ERROR: {message}")

    # -- instant-sync handlers -----------------------------------------------

    def _on_sync_browse(self) -> None:
        dlg = self._make_folder_dialog("Select instant sync folder")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.selected_path()
        if selected is None:
            return
        self._start_instant_sync(selected)

    def _start_instant_sync(self, folder: Path) -> None:
        """Start instant-sync on *folder* (stops any previous sync first)."""
        self._stop_instant_sync()
        if self._event is None:
            return

        self._instant_sync_folder = folder
        self._settings.set_instant_sync_folder(self._event.id, folder)

        self._sync_folder_label.setText(str(folder))
        self._sync_folder_label.setStyleSheet("color: #374151;")
        self._sync_clear_btn.setEnabled(True)
        self._sync_status.setText("\u25cf Active")
        self._sync_status.setStyleSheet("color: #2E7D32; font-size: 14px;")
        self._sync_log.clear()

        self._instant_sync = InstantSyncManager(
            self._api, self._event.id, folder,
        )
        self._instant_sync.file_uploaded.connect(self._on_sync_file_uploaded)
        self._instant_sync.file_error.connect(self._on_sync_file_error)
        self._instant_sync.upload_progress.connect(self._on_sync_progress)
        self._instant_sync.poll_started.connect(self._on_poll_started)
        self._instant_sync.poll_finished.connect(self._on_poll_finished)
        self._instant_sync.start()

        # Start UI countdown timer (ticks every 1 s)
        self._poll_countdown = 5
        self._poll_indicator.setText("⏳ Polling idle")
        self._poll_countdown_label.setText("Next poll in 5s")
        self._poll_tick_timer = QTimer(self)
        self._poll_tick_timer.setInterval(1000)
        self._poll_tick_timer.timeout.connect(self._on_poll_ui_tick)
        self._poll_tick_timer.start()

        # The user can mark upload complete while sync is running
        self._complete_btn.setVisible(True)
        self._complete_btn.setEnabled(True)

    def _stop_instant_sync(self) -> None:
        """Stop the current instant-sync session, if any."""
        if self._poll_tick_timer is not None:
            self._poll_tick_timer.stop()
            self._poll_tick_timer = None
        self._poll_indicator.setText("")
        self._poll_countdown_label.setText("")
        if self._instant_sync is not None:
            self._instant_sync.stop()
            self._instant_sync = None

    def _on_sync_clear(self) -> None:
        """Remove the instant-sync folder and stop watching."""
        self._stop_instant_sync()
        self._instant_sync_folder = None
        if self._event is not None:
            self._settings.clear_instant_sync_folder(self._event.id)
        self._sync_folder_label.setText("No folder selected")
        self._sync_folder_label.setStyleSheet("color: #9CA3AF; font-style: italic;")
        self._sync_clear_btn.setEnabled(False)
        self._sync_status.setText("")
        self._poll_indicator.setText("")
        self._poll_countdown_label.setText("")

    def _on_sync_file_uploaded(self, path: str) -> None:
        self._sync_log.append(f"\u2713 {Path(path).name}")

    def _on_sync_file_error(self, path: str, error: str) -> None:
        self._sync_log.append(f"\u2717 {Path(path).name}: {error}")

    def _on_sync_progress(self, uploaded: int, total: int, current: str) -> None:
        self._sync_status.setText(
            f"\u25cf Active \u2014 {uploaded}/{total} uploaded",
        )
        self._sync_status.setStyleSheet("color: #2E7D32; font-size: 14px;")

    # -- polling UI slots ----------------------------------------------------

    def _on_poll_started(self) -> None:
        """Watcher started scanning the folder tree."""
        self._poll_indicator.setText("\U0001f504 Scanning…")
        self._poll_indicator.setStyleSheet("color: #D97706; font-size: 13px;")
        self._poll_countdown_label.setText("")

    def _on_poll_finished(self, new_files: int) -> None:
        """Watcher finished a poll scan."""
        if new_files:
            self._poll_indicator.setText(f"\u2714 Found {new_files} new file{'s' if new_files != 1 else ''}")
            self._poll_indicator.setStyleSheet("color: #2E7D32; font-size: 13px;")
        else:
            self._poll_indicator.setText("\u2714 No new files")
            self._poll_indicator.setStyleSheet("color: #6B7280; font-size: 13px;")
        # Reset countdown
        self._poll_countdown = 5
        self._poll_countdown_label.setText("Next poll in 5s")
        self._poll_countdown_label.setStyleSheet("color: #6B7280; font-size: 13px;")

    def _on_poll_ui_tick(self) -> None:
        """Tick the countdown label every second."""
        if self._poll_countdown > 0:
            self._poll_countdown -= 1
            self._poll_countdown_label.setText(f"Next poll in {self._poll_countdown}s")

    # -- helpers ------------------------------------------------------------

    def _reset_ui(self) -> None:
        # Stop instant sync from previous event
        self._stop_instant_sync()
        self._instant_sync_folder = None

        self._folders = []
        # Remove folder row widgets (skip the _no_folder_label at index 0)
        while self._folders_layout.count() > 1:
            item = self._folders_layout.takeAt(1)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._no_folder_label.setVisible(True)
        self._count_label.setText("")
        self._browse_btn.setEnabled(True)
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._complete_btn.setEnabled(False)
        self._complete_btn.setVisible(False)
        self._retry_btn.setEnabled(False)
        self._retry_btn.setVisible(False)
        self._progress_bar.setValue(0)
        self._current_file.setText("")
        self._log.clear()
        self._locked_label.setVisible(False)
        # Reset instant-sync UI
        self._sync_folder_label.setText("No folder selected")
        self._sync_folder_label.setStyleSheet("color: #9CA3AF; font-style: italic;")
        self._sync_clear_btn.setEnabled(False)
        self._sync_status.setText("")
        self._poll_indicator.setText("")
        self._poll_countdown_label.setText("")
        self._sync_log.clear()
