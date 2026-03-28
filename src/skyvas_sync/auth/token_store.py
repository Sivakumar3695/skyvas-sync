"""Persistent token storage with automatic refresh."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from skyvas_sync.auth.cognito_auth import CognitoAuth, AuthError


def _default_token_path() -> Path:
    """Return the default path for storing tokens."""
    return Path.home() / ".skyvas-sync" / "tokens.json"


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode the payload segment of a JWT **without** verifying the signature."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    # Add padding
    payload_b64 = parts[1]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload_bytes = base64.urlsafe_b64decode(payload_b64)
    return json.loads(payload_bytes)


class TokenStore:
    """Persists Cognito tokens to disk and handles transparent refresh.

    Parameters
    ----------
    path:
        File path for the JSON token file.  Defaults to
        ``~/.skyvas-sync/tokens.json``.
    auth:
        Optional :class:`CognitoAuth` instance for automatic refresh.
    """

    def __init__(
        self,
        path: Path | None = None,
        auth: CognitoAuth | None = None,
    ) -> None:
        self._path: Path = path or _default_token_path()
        self._auth = auth
        self._tokens: dict[str, Any] = {}
        self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._tokens = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._tokens = {}

    def save(self, tokens: dict[str, Any]) -> None:
        """Merge *tokens* into the store and write to disk."""
        self._tokens.update(tokens)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._tokens, indent=2), encoding="utf-8")

    def clear(self) -> None:
        """Remove all stored tokens."""
        self._tokens = {}
        if self._path.exists():
            self._path.unlink()

    # -- accessors ----------------------------------------------------------

    @property
    def id_token(self) -> str | None:
        return self._tokens.get("id_token")

    @property
    def access_token(self) -> str | None:
        return self._tokens.get("access_token")

    @property
    def refresh_token(self) -> str | None:
        return self._tokens.get("refresh_token")

    @property
    def has_tokens(self) -> bool:
        return bool(self.id_token)

    # -- expiry check -------------------------------------------------------

    def is_expired(self) -> bool:
        """Return *True* if the stored ID token has expired (with 60 s margin)."""
        token = self.id_token
        if not token:
            return True
        try:
            payload = _decode_jwt_payload(token)
            exp = payload.get("exp", 0)
            return time.time() >= (exp - 60)
        except (ValueError, KeyError):
            return True

    # -- convenience --------------------------------------------------------

    def get_valid_id_token(self) -> str | None:
        """Return a valid ID token, refreshing if necessary.

        Returns ``None`` if no tokens are available or refresh fails.
        """
        if self.id_token and not self.is_expired():
            return self.id_token

        if self.refresh_token and self._auth:
            try:
                new_tokens = self._auth.refresh_tokens(self.refresh_token)
                self.save(new_tokens)
                return self.id_token
            except AuthError:
                return None

        return None

    def get_user_email(self) -> str | None:
        """Extract the user email from the stored ID token, if available."""
        token = self.id_token
        if not token:
            return None
        try:
            payload = _decode_jwt_payload(token)
            return payload.get("email")
        except (ValueError, KeyError):
            return None
