"""HTTP client for the Skyvas API."""

from __future__ import annotations

from typing import Any

import requests as http_requests

from skyvas_sync.api.models import Event, UploadUrl
from skyvas_sync.auth.token_store import TokenStore
from skyvas_sync.config import Config


class ApiError(Exception):
    """Raised when an API call returns a non-success response."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        super().__init__(f"API error {status_code}: {detail}")


class ApiClient:
    """Thin wrapper around the Skyvas REST API.

    Each request automatically injects the ``X-Login-Token`` header from the
    :class:`TokenStore`.
    """

    def __init__(self, config: Config, token_store: TokenStore) -> None:
        self.config = config
        self.token_store = token_store
        self._session = http_requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # -- low level ----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        token = self.token_store.get_valid_id_token()
        headers: dict[str, str] = {}
        if token:
            headers["X-Login-Token"] = token
        return headers

    def _url(self, path: str) -> str:
        return f"{self.config.api_base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> Any:
        resp = self._session.request(
            method,
            self._url(path),
            json=json_body,
            headers=self._headers(),
            timeout=timeout,
        )
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        if resp.content:
            return resp.json()
        return None

    # -- events -------------------------------------------------------------

    def list_events(self) -> list[Event]:
        """Fetch all events for the logged-in user."""
        data = self._request("GET", "/events")
        return [Event.from_dict(e) for e in data.get("events", [])]

    def get_event(self, event_id: str) -> Event:
        """Fetch details for a single event."""
        data = self._request("GET", f"/events/{event_id}")
        return Event.from_dict(data.get("event_details", data))

    def update_event_status(self, event_id: str, status: str) -> None:
        """Update event status (e.g. ``UPLOAD_IN_PROGRESS``, ``UPLOADED``)."""
        self._request("PUT", f"/events/{event_id}", {"status": status})

    # -- upload -------------------------------------------------------------

    def get_upload_url(
        self,
        event_id: str,
        filename: str,
        width: int,
        height: int,
    ) -> UploadUrl:
        """Request a presigned S3 upload URL for a single image."""
        data = self._request(
            "POST",
            f"/events/{event_id}/get-upload-url",
            {"filename": filename, "width": width, "height": height},
        )
        return UploadUrl.from_dict(data)

    def upload_to_s3(
        self,
        upload_url: str,
        file_bytes: bytes,
        content_type: str,
        width: int,
        height: int,
    ) -> None:
        """PUT file bytes directly to the presigned S3 URL."""
        resp = http_requests.put(
            upload_url,
            data=file_bytes,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "max-age=31536000",
                "x-amz-meta-width": str(width),
                "x-amz-meta-height": str(height),
            },
            timeout=120,
        )
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
