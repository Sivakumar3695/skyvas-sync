"""Tests for skyvas_sync.ui.events_list_view."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.api.models import Event, UploadStatus
from skyvas_sync.ui.events_list_view import EventsListView


@pytest.fixture()
def mock_api() -> MagicMock:
    return MagicMock(spec=ApiClient)


@pytest.fixture()
def events_view(qtbot, mock_api: MagicMock) -> EventsListView:
    view = EventsListView(mock_api)
    qtbot.addWidget(view)
    return view


class TestEventsListView:
    def test_initial_state(self, events_view: EventsListView):
        assert events_view._table.rowCount() == 0
        assert events_view._refresh_btn.isEnabled()

    def test_columns(self, events_view: EventsListView):
        for i, label in enumerate(EventsListView.COLUMNS):
            assert events_view._table.horizontalHeaderItem(i).text() == label

    def test_load_events_populates_table(self, events_view: EventsListView, mock_api: MagicMock, sample_event: Event):
        mock_api.list_events.return_value = [sample_event]
        events_view.load_events()
        assert events_view._table.rowCount() == 1
        assert events_view._table.item(0, 0).text() == "Wedding Ceremony"
        assert events_view._table.item(0, 1).text() == "09/Mar/2026"
        assert events_view._table.item(0, 2).text() == "Grand Hall"
        assert events_view._table.item(0, 3).text() == "WEDDING"
        assert events_view._table.item(0, 4).text() == "Event Created"
        assert events_view._table.item(0, 5).text() == "—"

    def test_load_events_empty(self, events_view: EventsListView, mock_api: MagicMock):
        mock_api.list_events.return_value = []
        events_view.load_events()
        assert events_view._table.rowCount() == 0
        assert "0 events" in events_view._status.text()

    def test_load_events_error(self, events_view: EventsListView, mock_api: MagicMock):
        mock_api.list_events.side_effect = ApiError(500, "Internal Server Error")
        events_view.load_events()
        assert "Error" in events_view._status.text()

    def test_load_events_re_enables_button(self, events_view: EventsListView, mock_api: MagicMock):
        mock_api.list_events.return_value = []
        events_view.load_events()
        assert events_view._refresh_btn.isEnabled()

    def test_update_upload_status(self, events_view: EventsListView, mock_api: MagicMock, sample_event: Event):
        mock_api.list_events.return_value = [sample_event]
        events_view.load_events()

        status = UploadStatus(event_id="evt-1", total=100, uploaded=42)
        events_view.update_upload_status(status)
        assert events_view._table.item(0, 5).text() == "42/100"

    def test_update_upload_status_unknown_event(self, events_view: EventsListView, mock_api: MagicMock, sample_event: Event):
        mock_api.list_events.return_value = [sample_event]
        events_view.load_events()

        # Should not raise
        status = UploadStatus(event_id="unknown", total=10, uploaded=5)
        events_view.update_upload_status(status)

    def test_double_click_emits_event_selected(self, qtbot, events_view: EventsListView, mock_api: MagicMock, sample_event: Event):
        mock_api.list_events.return_value = [sample_event]
        events_view.load_events()

        signals = []
        events_view.event_selected.connect(lambda e: signals.append(e))
        # Simulate double-click via internal method
        index = events_view._table.model().index(0, 0)
        events_view._on_row_double_clicked(index)
        assert len(signals) == 1
        assert signals[0].id == "evt-1"

    def test_double_click_invalid_row(self, events_view: EventsListView, mock_api: MagicMock):
        mock_api.list_events.return_value = []
        events_view.load_events()

        signals = []
        events_view.event_selected.connect(lambda e: signals.append(e))

        # Create a mock index with out-of-range row
        mock_index = MagicMock()
        mock_index.row.return_value = 99
        events_view._on_row_double_clicked(mock_index)
        assert len(signals) == 0

    def test_logout_button_emits_signal(self, qtbot, events_view: EventsListView):
        signals = []
        events_view.logout_requested.connect(lambda: signals.append(True))
        events_view._logout_btn.click()
        assert len(signals) == 1

    def test_multiple_events(self, events_view: EventsListView, mock_api: MagicMock):
        events = [
            Event(id="1", name="Event A", place="P1", date="01/Jan/2026",
                  event_type="WEDDING", status_code=0),
            Event(id="2", name="Event B", place="P2", date="02/Feb/2026",
                  event_type="BIRTHDAY", status_code=4),
        ]
        mock_api.list_events.return_value = events
        events_view.load_events()
        assert events_view._table.rowCount() == 2
        assert events_view._table.item(1, 0).text() == "Event B"
        assert events_view._table.item(1, 4).text() == "Completed"

    def test_load_preserves_upload_status(self, events_view: EventsListView, mock_api: MagicMock, sample_event: Event):
        mock_api.list_events.return_value = [sample_event]
        events_view.load_events()
        status = UploadStatus(event_id="evt-1", total=50, uploaded=25)
        events_view.update_upload_status(status)

        # Reload events — status should be preserved
        events_view.load_events()
        assert events_view._table.item(0, 5).text() == "25/50"
