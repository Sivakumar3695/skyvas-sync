"""Main window — orchestrates login, events list, and event detail views."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from skyvas_sync.api.client import ApiClient
from skyvas_sync.api.models import Event, UploadStatus
from skyvas_sync.auth.token_store import TokenStore
from skyvas_sync.config import Config
from skyvas_sync.settings_store import SettingsStore
from skyvas_sync.ui.album_view import AlbumView
from skyvas_sync.ui.events_list_view import EventsListView
from skyvas_sync.ui.login_view import LoginView
from skyvas_sync.ui.uploader_view import UploaderView

_VIEW_LOGIN = 0
_VIEW_EVENTS = 1
_VIEW_DETAIL = 2


class MainWindow(QMainWindow):
    """Top-level application window with a stacked view controller."""

    def __init__(
        self,
        config: Config,
        token_store: TokenStore,
        api_client: ApiClient,
    ) -> None:
        super().__init__()
        self._config = config
        self._token_store = token_store
        self._api = api_client
        self._settings = SettingsStore()
        self._current_event: Event | None = None

        self.setWindowTitle("Skyvas Sync")
        self.resize(900, 620)

        # -- stacked views --------------------------------------------------
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # View 0: Login
        self._login_view = LoginView(config, token_store)
        self._login_view.login_success.connect(self._go_events)
        self._stack.addWidget(self._login_view)

        # View 1: Events list
        self._events_view = EventsListView(api_client)
        self._events_view.event_selected.connect(self._go_detail)
        self._events_view.logout_requested.connect(self._logout)
        self._stack.addWidget(self._events_view)

        # View 2: Event detail (uploader + album tabs)
        self._detail_widget = self._build_detail_view()
        self._stack.addWidget(self._detail_widget)

        # -- decide initial view --------------------------------------------
        if self._token_store.has_tokens and not self._token_store.is_expired():
            self._go_events()
        else:
            self._stack.setCurrentIndex(_VIEW_LOGIN)

    # -- detail view builder ------------------------------------------------

    def _build_detail_view(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        # Header
        header = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._back_btn.clicked.connect(self._go_back)
        header.addWidget(self._back_btn)

        self._event_title = QLabel("")
        self._event_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(self._event_title, stretch=1)
        layout.addLayout(header)

        self._event_info = QLabel("")
        self._event_info.setStyleSheet("color: #666; margin-bottom: 8px;")
        layout.addWidget(self._event_info)

        # Tabs: Upload / Album
        self._tabs = QTabWidget()

        self._uploader_view = UploaderView(self._api, self._settings)
        self._uploader_view.upload_status_changed.connect(self._on_upload_status)
        self._tabs.addTab(self._uploader_view, "Upload")

        self._album_view = AlbumView()
        self._tabs.addTab(self._album_view, "Album")
        self._tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self._tabs)
        return container

    # -- navigation ---------------------------------------------------------

    def _go_events(self) -> None:
        self._stack.setCurrentIndex(_VIEW_EVENTS)
        self._events_view.load_events()

    def _go_detail(self, event: Event) -> None:
        self._current_event = event
        self._event_title.setText(event.name)
        self._event_info.setText(
            f"{event.date}  •  {event.place}  •  {event.event_type}  •  {event.status_label}",
        )
        self._uploader_view.set_event(event)
        self._stack.setCurrentIndex(_VIEW_DETAIL)

    def _go_back(self) -> None:
        self._stack.setCurrentIndex(_VIEW_EVENTS)
        self._events_view.load_events()

    def _logout(self) -> None:
        self._token_store.clear()
        self._stack.setCurrentIndex(_VIEW_LOGIN)

    # -- upload status propagation ------------------------------------------

    def _on_upload_status(self, status: UploadStatus) -> None:
        self._events_view.update_upload_status(status)

    # -- album tab switching ------------------------------------------------

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            folders = self._uploader_view.all_folders
            if folders:
                self._album_view.set_folders(folders)
