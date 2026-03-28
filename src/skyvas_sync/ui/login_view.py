"""Login view — Google sign-in via Cognito hosted UI."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from skyvas_sync.auth.cognito_auth import CognitoAuth, AuthError
from skyvas_sync.auth.token_store import TokenStore
from skyvas_sync.config import Config


class _LoginThread(QThread):
    """Performs the browser-based OAuth flow in a background thread."""

    success = Signal(dict)
    failed = Signal(str)

    def __init__(self, auth: CognitoAuth, parent: QThread | None = None) -> None:
        super().__init__(parent)
        self._auth = auth

    def run(self) -> None:
        try:
            tokens = self._auth.login_with_browser()
            self.success.emit(tokens)
        except AuthError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class LoginView(QWidget):
    """Simple login screen with a *Sign in with Google* button.

    Signals
    -------
    login_success()
        Emitted after tokens have been saved successfully.
    """

    login_success = Signal()

    def __init__(
        self,
        config: Config,
        token_store: TokenStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._token_store = token_store
        self._auth = CognitoAuth(config)
        self._thread: _LoginThread | None = None
        self._setup_ui()

    # -- UI setup -----------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Skyvas Sync")
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 8px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Sign in to sync photos from your computer")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #666; margin-bottom: 24px;")

        self._btn = QPushButton("Sign in with Google")
        self._btn.setFixedWidth(220)
        self._btn.setFixedHeight(40)
        self._btn.clicked.connect(self._on_login_clicked)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #888; margin-top: 12px;")

        layout.addStretch()
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

    # -- handlers -----------------------------------------------------------

    def _on_login_clicked(self) -> None:
        self._btn.setEnabled(False)
        self._status.setText("Opening browser for sign-in…")
        self._thread = _LoginThread(self._auth)
        self._thread.success.connect(self._on_success)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_success(self, tokens: dict) -> None:
        self._token_store.save(tokens)
        self._status.setText("Signed in!")
        self._btn.setEnabled(True)
        self.login_success.emit()

    def _on_failed(self, message: str) -> None:
        self._status.setText(f"Sign-in failed: {message}")
        self._btn.setEnabled(True)
