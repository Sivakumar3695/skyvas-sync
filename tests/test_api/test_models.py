"""Tests for skyvas_sync.api.models."""

from __future__ import annotations

from skyvas_sync.api.models import Event, UploadStatus, UploadUrl, STATUS_LABELS


class TestEvent:
    def test_from_dict(self, sample_event_dict: dict):
        event = Event.from_dict(sample_event_dict)
        assert event.id == "evt-1"
        assert event.name == "Wedding Ceremony"
        assert event.place == "Grand Hall"
        assert event.date == "09/Mar/2026"
        assert event.event_type == "WEDDING"
        assert event.status_code == 0
        assert event.total_photos == 0
        assert event.pricing_category == "STANDARD"

    def test_from_dict_with_event_type_key(self):
        data = {"id": "2", "name": "Party", "place": "Home", "date": "01/Jan/2026",
                "event_type": "BIRTHDAY", "status_code": 4}
        event = Event.from_dict(data)
        assert event.event_type == "BIRTHDAY"

    def test_from_dict_missing_fields(self):
        event = Event.from_dict({})
        assert event.id == ""
        assert event.name == ""
        assert event.status_code == 0

    def test_status_label(self):
        for code, label in STATUS_LABELS.items():
            event = Event(id="1", name="E", place="P", date="D", event_type="T", status_code=code)
            assert event.status_label == label

    def test_unknown_status_label(self):
        event = Event(id="1", name="E", place="P", date="D", event_type="T", status_code=99)
        assert event.status_label == "Unknown"


class TestUploadUrl:
    def test_from_dict(self):
        data = {"uploadUrl": "https://s3/put", "fileUrl": "https://s3/file.jpg"}
        url = UploadUrl.from_dict(data)
        assert url.upload_url == "https://s3/put"
        assert url.file_url == "https://s3/file.jpg"

    def test_missing_key_raises(self):
        import pytest
        with pytest.raises(KeyError):
            UploadUrl.from_dict({})


class TestUploadStatus:
    def test_defaults(self):
        status = UploadStatus(event_id="e1")
        assert status.total == 0
        assert status.uploaded == 0
        assert status.failed == 0
        assert status.errors == []

    def test_progress_text_no_total(self):
        status = UploadStatus(event_id="e1")
        assert status.progress_text == "—"

    def test_progress_text_with_counts(self):
        status = UploadStatus(event_id="e1", total=10, uploaded=3)
        assert status.progress_text == "3/10"

    def test_is_complete_false(self):
        status = UploadStatus(event_id="e1", total=10, uploaded=5)
        assert not status.is_complete

    def test_is_complete_true(self):
        status = UploadStatus(event_id="e1", total=10, uploaded=10)
        assert status.is_complete

    def test_is_complete_with_failures(self):
        status = UploadStatus(event_id="e1", total=10, uploaded=7, failed=3)
        assert status.is_complete

    def test_is_complete_zero_total(self):
        status = UploadStatus(event_id="e1", total=0)
        assert not status.is_complete
