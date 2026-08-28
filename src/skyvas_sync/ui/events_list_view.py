"""Events list view — table of all events with upload status."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.api.models import Event, UploadStatus


class EventsListView(QWidget):
    """Displays events in a table.  Double-click opens the event.

    Signals
    -------
    event_selected(event)
        Emitted when the user double-clicks an event row.
    logout_requested()
        Emitted when the user clicks "Logout".
    """

    event_selected = Signal(object)  # Event dataclass
    logout_requested = Signal()

    COLUMNS = ("Name", "Date", "Place", "Type", "Status", "Upload")

    def __init__(
        self,
        api_client: ApiClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api_client
        self._events: list[Event] = []
        self._upload_status: dict[str, UploadStatus] = {}
        self._setup_ui()

    # -- UI setup -----------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header_layout = QHBoxLayout()
        title = QLabel("Events")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setProperty("styleClass", "secondary")
        self._refresh_btn.clicked.connect(self.load_events)
        header_layout.addWidget(self._refresh_btn)

        self._logout_btn = QPushButton("Logout")
        self._logout_btn.setObjectName("logoutBtn")
        self._logout_btn.clicked.connect(self.logout_requested.emit)
        header_layout.addWidget(self._logout_btn)

        layout.addLayout(header_layout)

        # Status label
        self._status = QLabel("")
        self._status.setStyleSheet("color: #6B7280;")
        layout.addWidget(self._status)

        # Table
        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch,
        )
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows,
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table)

    # -- public API ---------------------------------------------------------

    def load_events(self) -> None:
        """Fetch events from the API and populate the table."""
        self._status.setText("Loading events…")
        self._refresh_btn.setEnabled(False)
        try:
            self._events = self._api.list_events()
            self._populate_table()
            self._status.setText(f"{len(self._events)} events loaded")
        except ApiError as exc:
            self._status.setText(f"Error: {exc}")
        finally:
            self._refresh_btn.setEnabled(True)

    def update_upload_status(self, status: UploadStatus) -> None:
        """Update the upload progress column for a specific event."""
        self._upload_status[status.event_id] = status
        for row, event in enumerate(self._events):
            if event.id == status.event_id:
                item = self._table.item(row, 5)
                if item:
                    item.setText(status.progress_text)
                break

    # -- internal -----------------------------------------------------------

    def _populate_table(self) -> None:
        self._table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            self._table.setItem(row, 0, QTableWidgetItem(event.name))
            self._table.setItem(row, 1, QTableWidgetItem(event.date))
            self._table.setItem(row, 2, QTableWidgetItem(event.place))
            self._table.setItem(row, 3, QTableWidgetItem(event.event_type))
            self._table.setItem(row, 4, QTableWidgetItem(event.status_label))
            upload = self._upload_status.get(event.id)
            upload_text = upload.progress_text if upload else "—"
            self._table.setItem(row, 5, QTableWidgetItem(upload_text))

    def _on_row_double_clicked(self, index: object) -> None:
        row = index.row()
        if 0 <= row < len(self._events):
            self.event_selected.emit(self._events[row])
