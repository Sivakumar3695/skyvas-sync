"""Tests for skyvas_sync.api.client."""

from __future__ import annotations

import pytest
import responses

from skyvas_sync.api.client import ApiClient, ApiError
from skyvas_sync.api.models import Event, UploadUrl
from skyvas_sync.config import Config


class TestApiClientHeaders:
    def test_headers_include_token(self, api_client: ApiClient, valid_jwt: str):
        headers = api_client._headers()
        assert headers["X-Login-Token"] == valid_jwt

    def test_headers_empty_when_no_token(self, config: Config, empty_token_store):
        client = ApiClient(config, empty_token_store)
        headers = client._headers()
        assert "X-Login-Token" not in headers

    def test_url_construction(self, api_client: ApiClient):
        assert api_client._url("/events") == "http://localhost:9999/api/v1/events"


class TestApiClientListEvents:
    @responses.activate
    def test_success(self, api_client: ApiClient, sample_event_dict: dict):
        responses.add(
            responses.GET,
            "http://localhost:9999/api/v1/events",
            json={"events": [sample_event_dict]},
            status=200,
        )
        events = api_client.list_events()
        assert len(events) == 1
        assert events[0].name == "Wedding Ceremony"
        assert events[0].id == "evt-1"

    @responses.activate
    def test_empty(self, api_client: ApiClient):
        responses.add(
            responses.GET,
            "http://localhost:9999/api/v1/events",
            json={"events": []},
            status=200,
        )
        assert api_client.list_events() == []

    @responses.activate
    def test_api_error(self, api_client: ApiClient):
        responses.add(
            responses.GET,
            "http://localhost:9999/api/v1/events",
            json={"error": "unauthorized"},
            status=401,
        )
        with pytest.raises(ApiError) as exc_info:
            api_client.list_events()
        assert exc_info.value.status_code == 401


class TestApiClientGetEvent:
    @responses.activate
    def test_success(self, api_client: ApiClient, sample_event_dict: dict):
        responses.add(
            responses.GET,
            "http://localhost:9999/api/v1/events/evt-1",
            json={"event_details": sample_event_dict},
            status=200,
        )
        event = api_client.get_event("evt-1")
        assert event.name == "Wedding Ceremony"

    @responses.activate
    def test_not_found(self, api_client: ApiClient):
        responses.add(
            responses.GET,
            "http://localhost:9999/api/v1/events/missing",
            json={"error": "not found"},
            status=404,
        )
        with pytest.raises(ApiError) as exc_info:
            api_client.get_event("missing")
        assert exc_info.value.status_code == 404


class TestApiClientUpdateEventStatus:
    @responses.activate
    def test_success(self, api_client: ApiClient):
        responses.add(
            responses.PUT,
            "http://localhost:9999/api/v1/events/evt-1",
            json={},
            status=200,
        )
        api_client.update_event_status("evt-1", "UPLOADED")
        assert responses.calls[-1].request.body
        import json
        body = json.loads(responses.calls[-1].request.body)
        assert body["status"] == "UPLOADED"

    @responses.activate
    def test_failure(self, api_client: ApiClient):
        responses.add(
            responses.PUT,
            "http://localhost:9999/api/v1/events/evt-1",
            status=500,
        )
        with pytest.raises(ApiError):
            api_client.update_event_status("evt-1", "UPLOADED")


class TestApiClientGetUploadUrl:
    @responses.activate
    def test_success(self, api_client: ApiClient):
        responses.add(
            responses.POST,
            "http://localhost:9999/api/v1/events/evt-1/get-upload-url",
            json={"uploadUrl": "https://s3.example.com/put", "fileUrl": "https://s3.example.com/file.jpg"},
            status=200,
        )
        result = api_client.get_upload_url("evt-1", "photo.jpg", 800, 600)
        assert isinstance(result, UploadUrl)
        assert result.upload_url == "https://s3.example.com/put"
        assert result.file_url == "https://s3.example.com/file.jpg"

    @responses.activate
    def test_failure(self, api_client: ApiClient):
        responses.add(
            responses.POST,
            "http://localhost:9999/api/v1/events/evt-1/get-upload-url",
            status=400,
        )
        with pytest.raises(ApiError):
            api_client.get_upload_url("evt-1", "photo.jpg", 800, 600)


class TestApiClientUploadToS3:
    @responses.activate
    def test_success(self, api_client: ApiClient):
        responses.add(
            responses.PUT,
            "https://s3.example.com/put",
            status=200,
        )
        api_client.upload_to_s3(
            "https://s3.example.com/put",
            b"image-bytes",
            "image/jpeg",
            800,
            600,
        )
        req = responses.calls[-1].request
        assert req.headers["Content-Type"] == "image/jpeg"
        assert req.headers["Cache-Control"] == "max-age=31536000"
        assert req.headers["x-amz-meta-width"] == "800"
        assert req.headers["x-amz-meta-height"] == "600"

    @responses.activate
    def test_failure(self, api_client: ApiClient):
        responses.add(
            responses.PUT,
            "https://s3.example.com/put",
            status=403,
        )
        with pytest.raises(ApiError):
            api_client.upload_to_s3(
                "https://s3.example.com/put",
                b"data",
                "image/jpeg",
                100,
                100,
            )


class TestRequestEmptyBody:
    @responses.activate
    def test_no_content_response(self, api_client: ApiClient):
        responses.add(
            responses.PUT,
            "http://localhost:9999/api/v1/events/evt-1",
            status=204,
            body=b"",
        )
        result = api_client._request("PUT", "/events/evt-1", {"status": "UPLOADED"})
        assert result is None
