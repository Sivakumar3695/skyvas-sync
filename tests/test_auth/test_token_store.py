"""Tests for skyvas_sync.auth.token_store."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skyvas_sync.auth.cognito_auth import AuthError, CognitoAuth
from skyvas_sync.auth.token_store import TokenStore, _decode_jwt_payload


# ---------------------------------------------------------------------------
# JWT payload decoding
# ---------------------------------------------------------------------------

class TestDecodeJwtPayload:
    def test_valid_jwt(self, valid_jwt: str):
        payload = _decode_jwt_payload(valid_jwt)
        assert payload["email"] == "test@example.com"
        assert payload["sub"] == "user1"
        assert "exp" in payload

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid JWT"):
            _decode_jwt_payload("not-a-jwt")

    def test_two_parts_raises(self):
        with pytest.raises(ValueError, match="Invalid JWT"):
            _decode_jwt_payload("header.payload")

    def test_handles_padding(self, valid_jwt: str):
        # The fixture JWT may or may not need padding — this just verifies
        # the function handles any base64url payload length.
        payload = _decode_jwt_payload(valid_jwt)
        assert isinstance(payload, dict)


# ---------------------------------------------------------------------------
# TokenStore — persistence
# ---------------------------------------------------------------------------

class TestTokenStorePersistence:
    def test_save_creates_file(self, tmp_path: Path):
        token_path = tmp_path / "sub" / "tokens.json"
        store = TokenStore(path=token_path)
        store.save({"id_token": "abc"})
        assert token_path.exists()
        data = json.loads(token_path.read_text())
        assert data["id_token"] == "abc"

    def test_load_existing(self, tmp_path: Path, sample_tokens: dict):
        token_path = tmp_path / "tokens.json"
        token_path.write_text(json.dumps(sample_tokens))
        store = TokenStore(path=token_path)
        assert store.id_token == sample_tokens["id_token"]
        assert store.refresh_token == "refresh-xyz"

    def test_load_missing_file(self, tmp_path: Path):
        store = TokenStore(path=tmp_path / "missing.json")
        assert not store.has_tokens
        assert store.id_token is None

    def test_load_corrupt_file(self, tmp_path: Path):
        token_path = tmp_path / "tokens.json"
        token_path.write_text("not json!!!")
        store = TokenStore(path=token_path)
        assert not store.has_tokens

    def test_clear_removes_file(self, token_store: TokenStore):
        assert token_store.has_tokens
        token_store.clear()
        assert not token_store.has_tokens
        assert token_store.id_token is None

    def test_clear_when_no_file(self, empty_token_store: TokenStore):
        empty_token_store.clear()  # should not raise
        assert not empty_token_store.has_tokens

    def test_save_merges(self, tmp_path: Path):
        token_path = tmp_path / "tokens.json"
        store = TokenStore(path=token_path)
        store.save({"id_token": "a", "refresh_token": "r"})
        store.save({"id_token": "b"})
        assert store.id_token == "b"
        assert store.refresh_token == "r"


# ---------------------------------------------------------------------------
# TokenStore — accessors
# ---------------------------------------------------------------------------

class TestTokenStoreAccessors:
    def test_has_tokens_true(self, token_store: TokenStore):
        assert token_store.has_tokens

    def test_has_tokens_false(self, empty_token_store: TokenStore):
        assert not empty_token_store.has_tokens

    def test_id_token(self, token_store: TokenStore, valid_jwt: str):
        assert token_store.id_token == valid_jwt

    def test_access_token(self, token_store: TokenStore):
        assert token_store.access_token == "access-abc"

    def test_refresh_token(self, token_store: TokenStore):
        assert token_store.refresh_token == "refresh-xyz"


# ---------------------------------------------------------------------------
# TokenStore — expiry
# ---------------------------------------------------------------------------

class TestTokenStoreExpiry:
    def test_not_expired(self, token_store: TokenStore):
        assert not token_store.is_expired()

    def test_expired(self, tmp_path: Path, expired_jwt: str):
        token_path = tmp_path / "tokens.json"
        token_path.write_text(json.dumps({"id_token": expired_jwt}))
        store = TokenStore(path=token_path)
        assert store.is_expired()

    def test_no_token_is_expired(self, empty_token_store: TokenStore):
        assert empty_token_store.is_expired()

    def test_bad_jwt_is_expired(self, tmp_path: Path):
        token_path = tmp_path / "tokens.json"
        token_path.write_text(json.dumps({"id_token": "bad.jwt.data"}))
        store = TokenStore(path=token_path)
        assert store.is_expired()


# ---------------------------------------------------------------------------
# TokenStore — get_valid_id_token
# ---------------------------------------------------------------------------

class TestGetValidIdToken:
    def test_returns_valid_token(self, token_store: TokenStore, valid_jwt: str):
        token = token_store.get_valid_id_token()
        assert token == valid_jwt

    def test_returns_none_when_empty(self, empty_token_store: TokenStore):
        assert empty_token_store.get_valid_id_token() is None

    def test_refreshes_expired_token(self, tmp_path: Path, expired_jwt: str, valid_jwt: str, config):
        token_path = tmp_path / "tokens.json"
        token_path.write_text(json.dumps({
            "id_token": expired_jwt,
            "refresh_token": "refresh-xyz",
        }))
        auth = CognitoAuth(config)
        store = TokenStore(path=token_path, auth=auth)

        with patch.object(auth, "refresh_tokens", return_value={"id_token": valid_jwt}) as mock:
            token = store.get_valid_id_token()
            mock.assert_called_once_with("refresh-xyz")
            assert token == valid_jwt

    def test_refresh_failure_returns_none(self, tmp_path: Path, expired_jwt: str, config):
        token_path = tmp_path / "tokens.json"
        token_path.write_text(json.dumps({
            "id_token": expired_jwt,
            "refresh_token": "refresh-xyz",
        }))
        auth = CognitoAuth(config)
        store = TokenStore(path=token_path, auth=auth)

        with patch.object(auth, "refresh_tokens", side_effect=AuthError("fail")):
            assert store.get_valid_id_token() is None

    def test_no_auth_no_refresh(self, tmp_path: Path, expired_jwt: str):
        token_path = tmp_path / "tokens.json"
        token_path.write_text(json.dumps({
            "id_token": expired_jwt,
            "refresh_token": "refresh-xyz",
        }))
        store = TokenStore(path=token_path, auth=None)
        assert store.get_valid_id_token() is None


# ---------------------------------------------------------------------------
# TokenStore — get_user_email
# ---------------------------------------------------------------------------

class TestGetUserEmail:
    def test_returns_email(self, token_store: TokenStore):
        assert token_store.get_user_email() == "test@example.com"

    def test_no_token_returns_none(self, empty_token_store: TokenStore):
        assert empty_token_store.get_user_email() is None

    def test_bad_jwt_returns_none(self, tmp_path: Path):
        token_path = tmp_path / "tokens.json"
        token_path.write_text(json.dumps({"id_token": "x.y.z"}))
        store = TokenStore(path=token_path)
        assert store.get_user_email() is None
