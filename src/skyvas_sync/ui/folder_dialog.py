"""Async folder browser dialog — safe for MTP/GVFS mounted devices.

``QFileDialog`` (both native GTK and Qt's own) performs blocking
``readdir()`` + ``stat()`` calls on the main thread when navigating
into a directory.  On MTP-mounted Android phones this freezes the
entire application for many seconds.

This module provides :class:`AsyncFolderDialog`, a custom folder
picker that loads directory contents in a background ``QThread``,
keeping the UI responsive even when targeting slow external devices.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QStandardPaths,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


# ---------------------------------------------------------------------------
# Background thread for listing subdirectories
# ---------------------------------------------------------------------------

class _ListDirsThread(QThread):
    """List immediate subdirectories of *path* without blocking the UI."""

    finished = Signal(list)  # list[tuple[str, str]]  — (name, full_path)

    def __init__(self, path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        results: list[tuple[str, str]] = []
        try:
            root = Path(self._path)
            if root.is_dir():
                for entry in sorted(root.iterdir()):
                    if self.isInterruptionRequested():
                        return
                    try:
                        if entry.is_dir():
                            results.append((entry.name, str(entry)))
                    except OSError:
                        pass  # permission error, broken symlink, etc.
        except OSError:
            pass
        self.finished.emit(results)


# ---------------------------------------------------------------------------
# Async folder browser dialog
# ---------------------------------------------------------------------------

_DIALOG_QSS = """
/* ── Dialog shell ───────────────────────────────────────────────────────── */
QDialog {
    background-color: #FFFFFF;
}

/* ── Sidebar ────────────────────────────────────────────────────────────── */
QListWidget#sidebar {
    background-color: #F5F7FA;
    border: none;
    border-right: 1px solid #DDE1E7;
    border-radius: 0;
    padding: 8px 0;
    font-size: 14px;
    outline: none;
}
QListWidget#sidebar::item {
    padding: 9px 16px;
    border-radius: 0;
    color: #374151;
}
QListWidget#sidebar::item:selected {
    background-color: #EEF2FC;
    color: #4A6FE3;
    font-weight: 600;
}
QListWidget#sidebar::item:hover:!selected {
    background-color: #EAECF0;
}

/* ── Directory list ─────────────────────────────────────────────────────── */
QListWidget#dirList {
    background-color: #FFFFFF;
    border: none;
    font-size: 15px;
    outline: none;
}
QListWidget#dirList::item {
    padding: 8px 12px;
    border-radius: 6px;
    margin: 1px 4px;
    color: #1A1A2E;
}
QListWidget#dirList::item:selected {
    background-color: #EEF2FC;
    color: #4A6FE3;
    font-weight: 600;
}
QListWidget#dirList::item:hover:!selected {
    background-color: #F5F7FA;
}

/* ── Path bar ───────────────────────────────────────────────────────────── */
QLineEdit#pathEdit {
    background-color: #F5F7FA;
    border: 1.5px solid #DDE1E7;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 14px;
    color: #374151;
    selection-background-color: #4A6FE3;
}
QLineEdit#pathEdit:focus {
    border-color: #4A6FE3;
    background-color: #FFFFFF;
}

/* ── Up button ──────────────────────────────────────────────────────────── */
QPushButton#upBtn {
    background-color: #F5F7FA;
    color: #374151;
    border: 1.5px solid #DDE1E7;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 14px;
    font-weight: 500;
    min-height: 0;
}
QPushButton#upBtn:hover {
    background-color: #EEF2FC;
    border-color: #4A6FE3;
    color: #4A6FE3;
}

/* ── Bottom bar ─────────────────────────────────────────────────────────── */
QFrame#bottomBar {
    background-color: #F5F7FA;
    border-top: 1px solid #DDE1E7;
}

/* ── Choose / Cancel buttons ────────────────────────────────────────────── */
QPushButton#chooseBtn {
    background-color: #4A6FE3;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 22px;
    font-size: 15px;
    font-weight: 600;
    min-height: 0;
}
QPushButton#chooseBtn:hover  { background-color: #3558C8; }
QPushButton#chooseBtn:disabled {
    background-color: #DDE1E7;
    color: #9CA3AF;
}

QPushButton#cancelBtn {
    background-color: transparent;
    color: #4A6FE3;
    border: 1.5px solid #4A6FE3;
    border-radius: 6px;
    padding: 8px 22px;
    font-size: 15px;
    font-weight: 500;
    min-height: 0;
}
QPushButton#cancelBtn:hover { background-color: #EEF2FC; }
"""


class AsyncFolderDialog(QDialog):
    """A folder picker that loads directory listings asynchronously.

    Unlike ``QFileDialog``, this dialog never blocks the main thread
    while reading directory contents — the listing happens in a
    background ``QThread``.  This makes it safe for MTP/GVFS paths
    that are extremely slow to enumerate.

    Usage::

        dlg = AsyncFolderDialog(parent, "Select instant sync folder")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            chosen = dlg.selected_path()  # Path or None
    """

    def __init__(
        self,
        parent=None,
        title: str = "Select folder",
        start_path: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(680, 480)
        self.resize(760, 540)
        self.setStyleSheet(_DIALOG_QSS)

        self._current_path: str = start_path or str(Path.home())
        self._selected_path: Path | None = None
        self._worker: _ListDirsThread | None = None

        self._build_ui()
        self._navigate(self._current_path)

    # -- public API ----------------------------------------------------------

    def selected_path(self) -> Path | None:
        """Return the folder chosen by the user, or ``None``."""
        return self._selected_path

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title bar ────────────────────────────────────────────────────
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(20, 18, 20, 10)

        title_lbl = QLabel(self.windowTitle())
        title_lbl.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #1A1A2E;"
        )
        title_bar.addWidget(title_lbl)
        root.addLayout(title_bar)

        # ── Divider ───────────────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #DDE1E7;")
        root.addWidget(divider)

        # ── Body (sidebar + right pane) ───────────────────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar
        self._sidebar = QListWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(170)
        self._sidebar.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._sidebar.itemClicked.connect(self._on_sidebar_clicked)
        self._populate_sidebar()
        body.addWidget(self._sidebar)

        # Right pane
        right_widget = QFrame()
        right_widget.setStyleSheet("background: #FFFFFF;")
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(12, 12, 12, 8)
        right.setSpacing(8)

        # Path bar row
        path_row = QHBoxLayout()
        path_row.setSpacing(8)

        self._up_btn = QPushButton("↑  Up")
        self._up_btn.setObjectName("upBtn")
        self._up_btn.setFixedWidth(72)
        self._up_btn.clicked.connect(self._go_up)
        path_row.addWidget(self._up_btn)

        self._path_edit = QLineEdit()
        self._path_edit.setObjectName("pathEdit")
        self._path_edit.setPlaceholderText("Type a path and press Enter…")
        self._path_edit.returnPressed.connect(self._on_path_edited)
        path_row.addWidget(self._path_edit)
        right.addLayout(path_row)

        # Directory list
        self._dir_list = QListWidget()
        self._dir_list.setObjectName("dirList")
        self._dir_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._dir_list.itemClicked.connect(self._on_item_clicked)
        right.addWidget(self._dir_list)

        # Loading indicator
        self._loading_label = QLabel("")
        self._loading_label.setStyleSheet(
            "color: #9CA3AF; font-style: italic; font-size: 13px; padding: 4px 0;"
        )
        right.addWidget(self._loading_label)

        body.addWidget(right_widget, stretch=1)
        root.addLayout(body, stretch=1)

        # ── Bottom bar ────────────────────────────────────────────────────
        bottom_frame = QFrame()
        bottom_frame.setObjectName("bottomBar")
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(20, 12, 20, 14)
        bottom_layout.setSpacing(10)

        sel_col = QVBoxLayout()
        sel_col.setSpacing(2)
        sel_hint = QLabel("Selected folder")
        sel_hint.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self._selected_label = QLabel("—")
        self._selected_label.setStyleSheet(
            "color: #1A1A2E; font-size: 14px; font-weight: 500;"
        )
        self._selected_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._selected_label.setWordWrap(True)
        sel_col.addWidget(sel_hint)
        sel_col.addWidget(self._selected_label)
        bottom_layout.addLayout(sel_col, stretch=1)

        self._choose_btn = QPushButton("Choose")
        self._choose_btn.setObjectName("chooseBtn")
        self._choose_btn.setEnabled(False)
        self._choose_btn.setDefault(True)
        self._choose_btn.clicked.connect(self._on_choose)
        bottom_layout.addWidget(self._choose_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(cancel_btn)

        root.addWidget(bottom_frame)

    def _populate_sidebar(self) -> None:
        """Add Home, /, and any GVFS-mounted devices to the sidebar."""
        home = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.HomeLocation,
        )
        self._add_sidebar_item("🏠  Home", home)
        self._add_sidebar_item("💻  Root  /", "/")

        # GVFS mounts (MTP phones, cameras, etc.)
        gvfs_root = Path(f"/run/user/{os.getuid()}/gvfs")
        if gvfs_root.is_dir():
            for entry in sorted(gvfs_root.iterdir()):
                if entry.is_dir():
                    label = self._friendly_device_name(entry.name)
                    self._add_sidebar_item(f"📱  {label}", str(entry))

    @staticmethod
    def _friendly_device_name(raw: str) -> str:
        """Turn ``mtp:host=Google_Pixel_6a_29231…`` into ``Pixel 6a``."""
        name = raw
        if "=" in name:
            name = name.split("=", 1)[1]
        parts = name.split("_")
        if len(parts) > 1 and (len(parts[-1]) > 8 or parts[-1].isdigit()):
            parts = parts[:-1]
        known_brands = {"Google", "Samsung", "Xiaomi", "OnePlus", "Sony", "LG", "Motorola"}
        if parts and parts[0] in known_brands:
            parts = parts[1:]
        return " ".join(parts) if parts else raw

    def _add_sidebar_item(self, label: str, path: str) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, path)
        self._sidebar.addItem(item)

    # -- navigation ----------------------------------------------------------

    def _navigate(self, path: str) -> None:
        """Start loading the contents of *path* in the background."""
        if self._worker is not None:
            self._worker.finished.disconnect(self._on_listing_done)
            self._worker.requestInterruption()
            self._worker.quit()
            self._worker.wait()
            self._worker = None

        self._current_path = path
        self._path_edit.setText(path)
        self._dir_list.clear()
        self._loading_label.setText("⏳  Loading…")
        self._choose_btn.setEnabled(False)
        self._selected_label.setText(path)

        self._worker = _ListDirsThread(path, parent=self)
        self._worker.finished.connect(self._on_listing_done)
        self._worker.start()

    def _on_listing_done(self, dirs: list[tuple[str, str]]) -> None:
        """Populate the list widget with the subdirectories found."""
        self._worker = None
        self._loading_label.setText("")
        self._dir_list.clear()

        if not dirs:
            self._loading_label.setText("No subfolders found")
        else:
            for name, full_path in dirs:
                item = QListWidgetItem(f"📁  {name}")
                item.setData(Qt.ItemDataRole.UserRole, full_path)
                self._dir_list.addItem(item)

        self._choose_btn.setEnabled(True)
        self._selected_label.setText(self._current_path)

    # -- slots ---------------------------------------------------------------

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._navigate(path)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._selected_path = Path(path)
            self._selected_label.setText(path)
            self._choose_btn.setEnabled(True)

    def _on_sidebar_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._navigate(path)

    def _go_up(self) -> None:
        parent = str(Path(self._current_path).parent)
        if parent != self._current_path:
            self._navigate(parent)

    def _on_path_edited(self) -> None:
        text = self._path_edit.text().strip()
        if text and Path(text).is_dir():
            self._navigate(text)

    def _on_choose(self) -> None:
        sel = self._dir_list.currentItem()
        if sel:
            path = sel.data(Qt.ItemDataRole.UserRole)
            if path:
                self._selected_path = Path(path)
        else:
            self._selected_path = Path(self._current_path)
        self.accept()

    # -- cleanup -------------------------------------------------------------

    def reject(self) -> None:
        self._selected_path = None
        self._cancel_worker()
        super().reject()

    def _cancel_worker(self) -> None:
        if self._worker is not None:
            self._worker.finished.disconnect(self._on_listing_done)
            self._worker.requestInterruption()
            self._worker.quit()
            self._worker.wait()
            self._worker = None



# ---------------------------------------------------------------------------
# Background thread for listing subdirectories
# ---------------------------------------------------------------------------

class _ListDirsThread(QThread):
    """List immediate subdirectories of *path* without blocking the UI."""

    finished = Signal(list)  # list[tuple[str, str]]  — (name, full_path)

    def __init__(self, path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        results: list[tuple[str, str]] = []
        try:
            root = Path(self._path)
            if root.is_dir():
                for entry in sorted(root.iterdir()):
                    if self.isInterruptionRequested():
                        return
                    try:
                        if entry.is_dir():
                            results.append((entry.name, str(entry)))
                    except OSError:
                        pass  # permission error, broken symlink, etc.
        except OSError:
            pass
        self.finished.emit(results)
