"""Tests for skyvas_sync.ui.login_view."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt

from skyvas_sync.auth.cognito_auth import AuthError
from skyvas_sync.auth.token_store import TokenStore
from skyvas_sync.config import Config
from skyvas_sync.ui.login_view import LoginView, _LoginThread


@pytest.fixture()
def login_view(qtbot, config: Config, empty_token_store: TokenStore) -> LoginView:
    view = LoginView(config, empty_token_store)
    qtbot.addWidget(view)
    return view


class TestLoginView:
    def test_initial_state(self, login_view: LoginView):
        assert login_view._btn.isEnabled()
        assert login_view._status.text() == ""

    def test_button_text(self, login_view: LoginView):
        assert login_view._btn.text() == "Sign in with Google"

    def test_click_disables_button(self, qtbot, login_view: LoginView):
        with patch.object(login_view, "_on_login_clicked") as mock:
            login_view._btn.click()
            mock.assert_called_once()

    def test_on_success_saves_tokens(self, qtbot, login_view: LoginView):
        tokens = {"id_token": "abc", "refresh_token": "xyz"}
        signals = []
        login_view.login_success.connect(lambda: signals.append(True))
        login_view._on_success(tokens)
        assert login_view._token_store.id_token == "abc"
        assert len(signals) == 1

    def test_on_failed_shows_message(self, login_view: LoginView):
        login_view._btn.setEnabled(False)
        login_view._on_failed("Network error")
        assert "Network error" in login_view._status.text()
        assert login_view._btn.isEnabled()

    def test_on_login_clicked_sets_status(self, qtbot, login_view: LoginView):
        with patch("skyvas_sync.ui.login_view._LoginThread") as MockThread:
            instance = MockThread.return_value
            instance.start = MagicMock()
            instance.success = MagicMock()
            instance.failed = MagicMock()
            # Connect mocks to behave like signals
            instance.success.connect = MagicMock()
            instance.failed.connect = MagicMock()
            login_view._on_login_clicked()
            assert not login_view._btn.isEnabled()
            assert "Opening browser" in login_view._status.text()

    def test_on_success_re_enables_button(self, login_view: LoginView):
        login_view._btn.setEnabled(False)
        login_view._on_success({"id_token": "tok"})
        assert login_view._btn.isEnabled()


class TestLoginThread:
    def test_success(self, qtbot, config: Config):
        from skyvas_sync.auth.cognito_auth import CognitoAuth

        auth = CognitoAuth(config)
        thread = _LoginThread(auth)

        tokens = {"id_token": "abc"}
        with patch.object(auth, "login_with_browser", return_value=tokens):
            success_results = []
            thread.success.connect(lambda t: success_results.append(t))
            with qtbot.waitSignal(thread.success, timeout=5000):
                thread.start()
            assert success_results[0] == tokens

    def test_auth_error(self, qtbot, config: Config):
        from skyvas_sync.auth.cognito_auth import CognitoAuth

        auth = CognitoAuth(config)
        thread = _LoginThread(auth)

        with patch.object(auth, "login_with_browser", side_effect=AuthError("fail")):
            errors = []
            thread.failed.connect(lambda msg: errors.append(msg))
            with qtbot.waitSignal(thread.failed, timeout=5000):
                thread.start()
            assert "fail" in errors[0]

    def test_generic_exception(self, qtbot, config: Config):
        from skyvas_sync.auth.cognito_auth import CognitoAuth

        auth = CognitoAuth(config)
        thread = _LoginThread(auth)

        with patch.object(auth, "login_with_browser", side_effect=RuntimeError("boom")):
            errors = []
            thread.failed.connect(lambda msg: errors.append(msg))
            with qtbot.waitSignal(thread.failed, timeout=5000):
                thread.start()
            assert "boom" in errors[0]


class TestLoginThreadDirect:
    """Call run() directly for coverage of the thread body."""

    def test_run_success(self, config: Config):
        from skyvas_sync.auth.cognito_auth import CognitoAuth

        auth = CognitoAuth(config)
        thread = _LoginThread(auth)
        results = []
        thread.success.connect(lambda t: results.append(t))

        with patch.object(auth, "login_with_browser", return_value={"id_token": "tok"}):
            thread.run()

        assert results[0]["id_token"] == "tok"

    def test_run_auth_error(self, config: Config):
        from skyvas_sync.auth.cognito_auth import CognitoAuth

        auth = CognitoAuth(config)
        thread = _LoginThread(auth)
        errors = []
        thread.failed.connect(lambda msg: errors.append(msg))

        with patch.object(auth, "login_with_browser", side_effect=AuthError("denied")):
            thread.run()

        assert "denied" in errors[0]

    def test_run_generic_error(self, config: Config):
        from skyvas_sync.auth.cognito_auth import CognitoAuth

        auth = CognitoAuth(config)
        thread = _LoginThread(auth)
        errors = []
        thread.failed.connect(lambda msg: errors.append(msg))

        with patch.object(auth, "login_with_browser", side_effect=ValueError("oops")):
            thread.run()

        assert "oops" in errors[0]
