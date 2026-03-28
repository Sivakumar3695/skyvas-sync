"""Tests for skyvas_sync.ui.main_window."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skyvas_sync.api.client import ApiClient
from skyvas_sync.api.models import Event, UploadStatus
from skyvas_sync.auth.token_store import TokenStore
from skyvas_sync.config import Config
from skyvas_sync.ui.main_window import MainWindow, _VIEW_LOGIN, _VIEW_EVENTS, _VIEW_DETAIL


@pytest.fixture()
def mock_api(sample_event: Event) -> MagicMock:
    api = MagicMock(spec=ApiClient)
    api.list_events.return_value = [sample_event]
    return api


@pytest.fixture()
def window_logged_out(qtbot, config: Config, empty_token_store: TokenStore, mock_api: MagicMock) -> MainWindow:
    win = MainWindow(config, empty_token_store, mock_api)
    qtbot.addWidget(win)
    return win


@pytest.fixture()
def window_logged_in(qtbot, config: Config, token_store: TokenStore, mock_api: MagicMock) -> MainWindow:
    win = MainWindow(config, token_store, mock_api)
    qtbot.addWidget(win)
    return win


class TestMainWindowInit:
    def test_starts_at_login_when_no_tokens(self, window_logged_out: MainWindow):
        assert window_logged_out._stack.currentIndex() == _VIEW_LOGIN

    def test_starts_at_events_when_logged_in(self, window_logged_in: MainWindow):
        assert window_logged_in._stack.currentIndex() == _VIEW_EVENTS

    def test_window_title(self, window_logged_out: MainWindow):
        assert window_logged_out.windowTitle() == "Skyvas Sync"

    def test_window_size(self, window_logged_out: MainWindow):
        assert window_logged_out.width() >= 900
        assert window_logged_out.height() >= 620


class TestMainWindowNavigation:
    def test_go_events(self, window_logged_out: MainWindow, mock_api: MagicMock):
        window_logged_out._go_events()
        assert window_logged_out._stack.currentIndex() == _VIEW_EVENTS
        mock_api.list_events.assert_called()

    def test_go_detail(self, window_logged_in: MainWindow, sample_event: Event):
        window_logged_in._go_detail(sample_event)
        assert window_logged_in._stack.currentIndex() == _VIEW_DETAIL
        assert window_logged_in._event_title.text() == "Wedding Ceremony"
        assert "Grand Hall" in window_logged_in._event_info.text()

    def test_go_back(self, window_logged_in: MainWindow, mock_api: MagicMock, sample_event: Event):
        window_logged_in._go_detail(sample_event)
        mock_api.list_events.reset_mock()
        window_logged_in._go_back()
        assert window_logged_in._stack.currentIndex() == _VIEW_EVENTS
        mock_api.list_events.assert_called()

    def test_logout(self, window_logged_in: MainWindow):
        window_logged_in._logout()
        assert window_logged_in._stack.currentIndex() == _VIEW_LOGIN
        assert not window_logged_in._token_store.has_tokens


class TestMainWindowUploadStatus:
    def test_upload_status_forwarded(self, window_logged_in: MainWindow, sample_event: Event):
        status = UploadStatus(event_id="evt-1", total=50, uploaded=25)
        with patch.object(window_logged_in._events_view, "update_upload_status") as mock:
            window_logged_in._on_upload_status(status)
            mock.assert_called_once_with(status)


class TestMainWindowTabChange:
    def test_album_tab_loads_folders(self, window_logged_in: MainWindow, sample_event: Event, image_folder: Path):
        window_logged_in._go_detail(sample_event)
        window_logged_in._uploader_view._folders = [image_folder]

        with patch.object(window_logged_in._album_view, "set_folders") as mock:
            window_logged_in._on_tab_changed(1)
            mock.assert_called_once_with([image_folder])

    def test_album_tab_no_folder(self, window_logged_in: MainWindow, sample_event: Event):
        window_logged_in._go_detail(sample_event)
        window_logged_in._uploader_view._folders = []
        window_logged_in._uploader_view._instant_sync_folder = None

        with patch.object(window_logged_in._album_view, "set_folders") as mock:
            window_logged_in._on_tab_changed(1)
            mock.assert_not_called()

    def test_upload_tab_does_nothing(self, window_logged_in: MainWindow, sample_event: Event):
        window_logged_in._go_detail(sample_event)
        with patch.object(window_logged_in._album_view, "set_folders") as mock:
            window_logged_in._on_tab_changed(0)
            mock.assert_not_called()

    def test_album_tab_includes_instant_sync_folder(
        self, window_logged_in: MainWindow, sample_event: Event, image_folder: Path, tmp_path: Path,
    ):
        window_logged_in._go_detail(sample_event)
        window_logged_in._uploader_view._folders = [image_folder]
        sync_dir = tmp_path / "sync_album"
        sync_dir.mkdir()
        window_logged_in._uploader_view._instant_sync_folder = sync_dir

        with patch.object(window_logged_in._album_view, "set_folders") as mock:
            window_logged_in._on_tab_changed(1)
            mock.assert_called_once()
            folders = mock.call_args[0][0]
            assert image_folder in folders
            assert sync_dir in folders

    def test_album_tab_only_instant_sync_folder(
        self, window_logged_in: MainWindow, sample_event: Event, tmp_path: Path,
    ):
        window_logged_in._go_detail(sample_event)
        window_logged_in._uploader_view._folders = []
        sync_dir = tmp_path / "only_sync"
        sync_dir.mkdir()
        window_logged_in._uploader_view._instant_sync_folder = sync_dir

        with patch.object(window_logged_in._album_view, "set_folders") as mock:
            window_logged_in._on_tab_changed(1)
            mock.assert_called_once_with([sync_dir])


class TestMainWindowLoginSuccess:
    def test_login_navigates_to_events(self, window_logged_out: MainWindow, mock_api: MagicMock):
        window_logged_out._login_view.login_success.emit()
        assert window_logged_out._stack.currentIndex() == _VIEW_EVENTS

    def test_event_selected_navigates_to_detail(self, window_logged_in: MainWindow, sample_event: Event):
        window_logged_in._events_view.event_selected.emit(sample_event)
        assert window_logged_in._stack.currentIndex() == _VIEW_DETAIL

    def test_logout_requested_navigates_to_login(self, window_logged_in: MainWindow):
        window_logged_in._events_view.logout_requested.emit()
        assert window_logged_in._stack.currentIndex() == _VIEW_LOGIN
