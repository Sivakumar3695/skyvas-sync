"""Tests for skyvas_sync.auth.cognito_auth."""

from __future__ import annotations

import urllib.parse
from unittest.mock import patch, MagicMock

import pytest
import responses

from skyvas_sync.auth.cognito_auth import (
    AuthError,
    CallbackServer,
    CognitoAuth,
    generate_pkce,
)
from skyvas_sync.config import Config


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

class TestGeneratePkce:
    def test_returns_verifier_and_challenge(self):
        verifier, challenge = generate_pkce()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)
        assert len(verifier) <= 128
        assert len(challenge) > 0

    def test_different_each_call(self):
        v1, c1 = generate_pkce()
        v2, c2 = generate_pkce()
        assert v1 != v2
        assert c1 != c2

    def test_challenge_is_base64url(self):
        _, challenge = generate_pkce()
        # Should not contain padding or non-url-safe chars
        assert "=" not in challenge
        assert "+" not in challenge
        assert "/" not in challenge


# ---------------------------------------------------------------------------
# CallbackServer
# ---------------------------------------------------------------------------

class TestCallbackServer:
    def test_start_and_shutdown(self):
        server = CallbackServer(port=18585)
        server.start()
        assert server._httpd is not None
        server.shutdown()
        assert server._httpd is None

    def test_wait_without_start_raises(self):
        server = CallbackServer(port=18586)
        with pytest.raises(RuntimeError, match="not started"):
            server.wait(timeout=1)

    def test_wait_timeout_returns_none(self):
        server = CallbackServer(port=18587)
        server.start()
        try:
            code, error = server.wait(timeout=1)
            assert code is None
            assert error is None
        finally:
            server.shutdown()

    def test_callback_with_code(self):
        import http.client
        import threading

        server = CallbackServer(port=18588)
        server.start()

        def send_request():
            import time
            time.sleep(0.3)
            conn = http.client.HTTPConnection("127.0.0.1", 18588)
            conn.request("GET", "/callback?code=test-auth-code")
            conn.getresponse()
            conn.close()

        t = threading.Thread(target=send_request)
        t.start()

        code, error = server.wait(timeout=5)
        t.join()
        server.shutdown()

        assert code == "test-auth-code"
        assert error is None

    def test_callback_with_error(self):
        import http.client
        import threading

        server = CallbackServer(port=18589)
        server.start()

        def send_request():
            import time
            time.sleep(0.3)
            conn = http.client.HTTPConnection("127.0.0.1", 18589)
            conn.request("GET", "/callback?error=access_denied&error_description=User+denied")
            conn.getresponse()
            conn.close()

        t = threading.Thread(target=send_request)
        t.start()

        code, error = server.wait(timeout=5)
        t.join()
        server.shutdown()

        assert code is None
        assert error == "User denied"

    def test_callback_with_404(self):
        import http.client
        import threading

        server = CallbackServer(port=18590)
        server.start()

        def send_request():
            import time
            time.sleep(0.3)
            conn = http.client.HTTPConnection("127.0.0.1", 18590)
            conn.request("GET", "/unknown")
            resp = conn.getresponse()
            assert resp.status == 404
            conn.close()

        t = threading.Thread(target=send_request)
        t.start()
        t.join(timeout=3)

        # After the 404, auth_code/error remain None
        server.shutdown()

    def test_double_shutdown_is_safe(self):
        server = CallbackServer(port=18591)
        server.start()
        server.shutdown()
        server.shutdown()  # Should not raise


# ---------------------------------------------------------------------------
# CognitoAuth
# ---------------------------------------------------------------------------

class TestCognitoAuth:
    @pytest.fixture()
    def auth(self, config: Config) -> CognitoAuth:
        return CognitoAuth(config)

    def test_build_login_url_contains_required_params(self, auth: CognitoAuth):
        url = auth.build_login_url()
        assert "auth.example.com/oauth2/authorize" in url
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        assert params["client_id"] == ["test-client-id"]
        assert params["response_type"] == ["code"]
        assert params["identity_provider"] == ["Google"]
        assert params["code_challenge_method"] == ["S256"]
        assert "code_challenge" in params

    def test_build_login_url_sets_verifier(self, auth: CognitoAuth):
        assert auth._verifier is None
        auth.build_login_url()
        assert auth._verifier is not None

    @responses.activate
    def test_exchange_code_success(self, auth: CognitoAuth, config: Config):
        responses.add(
            responses.POST,
            config.token_url,
            json={"id_token": "tok", "access_token": "acc", "refresh_token": "ref"},
            status=200,
        )
        auth.build_login_url()  # sets verifier
        result = auth.exchange_code("test-code")
        assert result["id_token"] == "tok"

    @responses.activate
    def test_exchange_code_failure(self, auth: CognitoAuth, config: Config):
        responses.add(
            responses.POST,
            config.token_url,
            body="invalid_grant",
            status=400,
        )
        auth.build_login_url()
        with pytest.raises(AuthError, match="Token exchange failed"):
            auth.exchange_code("bad-code")

    def test_exchange_code_without_verifier_raises(self, auth: CognitoAuth):
        with pytest.raises(AuthError, match="No PKCE verifier"):
            auth.exchange_code("code")

    @responses.activate
    def test_refresh_tokens_success(self, auth: CognitoAuth, config: Config):
        responses.add(
            responses.POST,
            config.token_url,
            json={"id_token": "new-tok", "access_token": "new-acc"},
            status=200,
        )
        result = auth.refresh_tokens("refresh-xyz")
        assert result["id_token"] == "new-tok"

    @responses.activate
    def test_refresh_tokens_failure(self, auth: CognitoAuth, config: Config):
        responses.add(
            responses.POST,
            config.token_url,
            body="invalid_grant",
            status=400,
        )
        with pytest.raises(AuthError, match="Token refresh failed"):
            auth.refresh_tokens("bad-refresh")

    @responses.activate
    def test_login_with_browser_error_path(self, auth: CognitoAuth, config: Config):
        """Test login_with_browser when the callback returns an error."""
        with patch.object(auth, "build_login_url", return_value="http://localhost"):
            with patch("skyvas_sync.auth.cognito_auth.webbrowser.open"):
                with patch("skyvas_sync.auth.cognito_auth.CallbackServer") as MockServer:
                    instance = MockServer.return_value
                    instance.start = MagicMock()
                    instance.wait = MagicMock(return_value=(None, "access_denied"))
                    instance.shutdown = MagicMock()
                    with pytest.raises(AuthError, match="access_denied"):
                        auth.login_with_browser()

    @responses.activate
    def test_login_with_browser_timeout(self, auth: CognitoAuth, config: Config):
        """Test login_with_browser when no callback received."""
        with patch.object(auth, "build_login_url", return_value="http://localhost"):
            with patch("skyvas_sync.auth.cognito_auth.webbrowser.open"):
                with patch("skyvas_sync.auth.cognito_auth.CallbackServer") as MockServer:
                    instance = MockServer.return_value
                    instance.start = MagicMock()
                    instance.wait = MagicMock(return_value=(None, None))
                    instance.shutdown = MagicMock()
                    with pytest.raises(AuthError, match="timed out"):
                        auth.login_with_browser()

    @responses.activate
    def test_login_with_browser_success(self, auth: CognitoAuth, config: Config):
        responses.add(
            responses.POST,
            config.token_url,
            json={"id_token": "tok", "access_token": "acc", "refresh_token": "ref"},
            status=200,
        )
        with patch("skyvas_sync.auth.cognito_auth.webbrowser.open"):
            with patch("skyvas_sync.auth.cognito_auth.CallbackServer") as MockServer:
                instance = MockServer.return_value
                instance.start = MagicMock()
                instance.wait = MagicMock(return_value=("auth-code-123", None))
                instance.shutdown = MagicMock()
                auth.build_login_url()  # set verifier
                with patch.object(auth, "build_login_url", return_value="http://localhost"):
                    # Re-call to test full flow — verifier is already set
                    tokens = auth.login_with_browser()
                    assert tokens["id_token"] == "tok"
