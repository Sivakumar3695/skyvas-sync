"""Cognito OAuth authentication with PKCE and local callback server."""

from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

import requests as http_requests

from skyvas_sync.config import Config


class AuthError(Exception):
    """Raised when an authentication operation fails."""


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for the S256 method."""
    verifier = secrets.token_urlsafe(96)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ---------------------------------------------------------------------------
# Local callback HTTP server
# ---------------------------------------------------------------------------

class CallbackServer:
    """Tiny HTTP server that captures the OAuth redirect on *localhost*.

    Usage::

        server = CallbackServer(port=8585)
        server.start()          # starts serving in background thread
        webbrowser.open(url)
        code, error = server.wait(timeout=120)
        server.shutdown()
    """

    def __init__(self, port: int = 8585) -> None:
        self.port = port
        self.auth_code: str | None = None
        self.error: str | None = None
        self._httpd: HTTPServer | None = None

    # -- public API ---------------------------------------------------------

    def start(self) -> None:
        """Create and start the HTTP server (blocks until a request arrives)."""
        parent = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if "code" in params:
                    parent.auth_code = params["code"][0]
                    self._respond(200, "Login successful! You can close this window.")
                elif "error" in params:
                    desc = params.get("error_description", params["error"])
                    parent.error = desc[0] if isinstance(desc, list) else str(desc)
                    self._respond(400, f"Login failed: {parent.error}")
                else:
                    self._respond(404, "Not found")

            def _respond(self, code: int, body: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = f"<html><body><h2>{body}</h2></body></html>"
                self.wfile.write(html.encode())

            def log_message(self, *_args: Any) -> None:  # pragma: no cover
                pass  # silence request logs

        self._httpd = HTTPServer(("127.0.0.1", self.port), _Handler)
        self._httpd.timeout = 1  # allow periodic checks

    def wait(self, timeout: int = 120) -> tuple[str | None, str | None]:
        """Block until the callback is received or *timeout* seconds elapse.

        Returns ``(auth_code, error)``.
        """
        if self._httpd is None:
            raise RuntimeError("Server not started")

        import time

        deadline = time.monotonic() + timeout
        while self.auth_code is None and self.error is None:
            if time.monotonic() >= deadline:
                break
            self._httpd.handle_request()

        return self.auth_code, self.error

    def shutdown(self) -> None:
        """Close the server socket."""
        if self._httpd is not None:
            self._httpd.server_close()
            self._httpd = None


# ---------------------------------------------------------------------------
# High-level Cognito auth
# ---------------------------------------------------------------------------

class CognitoAuth:
    """Handles the Cognito Hosted-UI OAuth code flow with PKCE."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._verifier: str | None = None

    # -- URL helpers --------------------------------------------------------

    def build_login_url(self) -> str:
        """Return the Cognito authorize URL (generates fresh PKCE pair)."""
        self._verifier, challenge = generate_pkce()
        params = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "scope": self.config.oauth_scopes,
            "redirect_uri": self.config.redirect_uri,
            "identity_provider": "Google",
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        return f"{self.config.authorize_url}?{urllib.parse.urlencode(params)}"

    # -- Token exchange -----------------------------------------------------

    def exchange_code(self, code: str) -> dict:
        """Exchange an authorization *code* for tokens.

        Returns the raw Cognito token response containing ``id_token``,
        ``access_token``, ``refresh_token``, and ``expires_in``.
        """
        if self._verifier is None:
            raise AuthError("No PKCE verifier — call build_login_url first")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id,
            "code_verifier": self._verifier,
        }
        resp = http_requests.post(
            self.config.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise AuthError(f"Token exchange failed ({resp.status_code}): {resp.text}")
        return resp.json()

    def refresh_tokens(self, refresh_token: str) -> dict:
        """Use a *refresh_token* to obtain fresh id/access tokens.

        Returns the raw Cognito token response (no ``refresh_token`` field).
        """
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.config.client_id,
        }
        resp = http_requests.post(
            self.config.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise AuthError(f"Token refresh failed ({resp.status_code}): {resp.text}")
        return resp.json()

    # -- Convenience: full browser-based login cycle -------------------------

    def login_with_browser(self) -> dict:
        """Open browser, wait for callback, exchange code. Returns tokens."""
        server = CallbackServer(self.config.local_server_port)
        server.start()
        try:
            url = self.build_login_url()
            webbrowser.open(url)
            code, error = server.wait(timeout=120)
        finally:
            server.shutdown()

        if error:
            raise AuthError(error)
        if code is None:
            raise AuthError("Login timed out — no callback received")
        return self.exchange_code(code)
