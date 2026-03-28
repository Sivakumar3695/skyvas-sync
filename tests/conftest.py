"""Shared fixtures for the test suite."""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from skyvas_sync.api.client import ApiClient
from skyvas_sync.api.models import Event, UploadStatus
from skyvas_sync.auth.cognito_auth import CognitoAuth
from skyvas_sync.auth.token_store import TokenStore
from skyvas_sync.config import Config


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@pytest.fixture()
def config() -> Config:
    """Return a test configuration pointing at localhost."""
    return Config(
        cognito_domain="auth.example.com",
        client_id="test-client-id",
        user_pool_id="ap-south-1_TEST",
        region="ap-south-1",
        api_base_url="http://localhost:9999/api/v1",
        redirect_uri="http://localhost:8585/callback",
        local_server_port=8585,
    )


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _make_jwt(payload: dict) -> str:
    """Create a minimal (unsigned) JWT for testing."""
    import base64

    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


@pytest.fixture()
def valid_jwt() -> str:
    """JWT that expires far in the future."""
    return _make_jwt({"sub": "user1", "email": "test@example.com", "exp": int(time.time()) + 3600})


@pytest.fixture()
def expired_jwt() -> str:
    """JWT that has already expired."""
    return _make_jwt({"sub": "user1", "email": "test@example.com", "exp": int(time.time()) - 100})


@pytest.fixture()
def sample_tokens(valid_jwt: str) -> dict:
    return {
        "id_token": valid_jwt,
        "access_token": "access-abc",
        "refresh_token": "refresh-xyz",
        "expires_in": 3600,
    }


# ---------------------------------------------------------------------------
# Token store
# ---------------------------------------------------------------------------

@pytest.fixture()
def token_store(tmp_path: Path, config: Config, sample_tokens: dict) -> TokenStore:
    """A TokenStore pre-loaded with valid tokens in a temp directory."""
    token_path = tmp_path / "tokens.json"
    token_path.write_text(json.dumps(sample_tokens))
    auth = CognitoAuth(config)
    return TokenStore(path=token_path, auth=auth)


@pytest.fixture()
def empty_token_store(tmp_path: Path) -> TokenStore:
    """A TokenStore with no saved tokens."""
    return TokenStore(path=tmp_path / "tokens.json")


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_client(config: Config, token_store: TokenStore) -> ApiClient:
    return ApiClient(config, token_store)


# ---------------------------------------------------------------------------
# Sample event
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_event() -> Event:
    return Event(
        id="evt-1",
        name="Wedding Ceremony",
        place="Grand Hall",
        date="09/Mar/2026",
        event_type="WEDDING",
        status_code=0,
        total_photos=0,
        pricing_category="STANDARD",
    )


@pytest.fixture()
def sample_event_dict() -> dict:
    return {
        "id": "evt-1",
        "name": "Wedding Ceremony",
        "place": "Grand Hall",
        "date": "09/Mar/2026",
        "type": "WEDDING",
        "status_code": 0,
        "total_photos": 0,
        "pricing_category": "STANDARD",
        "n_registrations": 0,
    }


# ---------------------------------------------------------------------------
# Image folder fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def image_folder(tmp_path: Path) -> Path:
    """Create a temp folder with a few small test images and a subfolder."""
    root = tmp_path / "photos"
    root.mkdir()

    # Root images
    for name in ("photo1.jpg", "photo2.png"):
        img = Image.new("RGB", (100, 80), color="blue")
        img.save(root / name)

    # Subfolder
    sub = root / "day2"
    sub.mkdir()
    img = Image.new("RGB", (200, 150), color="red")
    img.save(sub / "photo3.jpeg")

    # Non-image file (should be ignored)
    (root / "notes.txt").write_text("ignore me")

    return root
