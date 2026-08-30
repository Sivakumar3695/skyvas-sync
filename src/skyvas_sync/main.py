"""Application entry point."""

from __future__ import annotations

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from skyvas_sync.auth.cognito_auth import CognitoAuth
from skyvas_sync.auth.token_store import TokenStore
from skyvas_sync.api.client import ApiClient
from skyvas_sync.config import get_config
from skyvas_sync.ui.main_window import MainWindow
from skyvas_sync.ui.theme import APP_QSS


def _resolve_icon() -> QIcon:
    """Return the application icon, handling both dev and frozen (PyInstaller) modes."""
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base_dir = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'),
        )
    icon_path = os.path.join(base_dir, 'assets', 'icon.png')
    return QIcon(icon_path)


def main() -> None:  # pragma: no cover
    """Launch the Skyvas Sync desktop application."""
    # On Linux/Wayland, WM_CLASS must be set before QApplication is created
    # so the window manager can match the window to the correct icon.
    os.environ.setdefault('RESOURCE_NAME', 'skyvassync')

    app = QApplication(sys.argv)
    app.setApplicationName("Skyvas Sync")
    app.setDesktopFileName("skyvassync")
    app.setWindowIcon(_resolve_icon())
    app.setStyleSheet(APP_QSS)

    config = get_config()
    auth = CognitoAuth(config)
    token_store = TokenStore(auth=auth)
    api_client = ApiClient(config, token_store)

    window = MainWindow(config, token_store, api_client)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
