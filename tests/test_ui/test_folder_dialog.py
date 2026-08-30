"""Tests for skyvas_sync.ui.folder_dialog."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from skyvas_sync.ui import folder_dialog as fd
from skyvas_sync.ui.folder_dialog import AsyncFolderDialog


class _WindowsOS:
    """Stand-in for the ``os`` module as it behaves on Windows.

    ``os.getuid`` is Unix-only; touching it on Windows raises
    ``AttributeError``.  Patching the module reference held by
    ``folder_dialog`` (rather than ``os.name``) leaves the real stdlib
    untouched for everything else.
    """

    name = "nt"

    def __getattr__(self, attr: str):
        if attr == "getuid":
            raise AttributeError("module 'os' has no attribute 'getuid'")
        return getattr(os, attr)


@pytest.fixture()
def fake_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fd, "os", _WindowsOS())


def _make_dialog(qtbot, start_path: Path) -> AsyncFolderDialog:
    dlg = AsyncFolderDialog(None, "Select folder", start_path=str(start_path))
    qtbot.addWidget(dlg)
    return dlg


def _sidebar_paths(dlg: AsyncFolderDialog) -> list[str]:
    return [
        dlg._sidebar.item(i).data(fd.Qt.ItemDataRole.UserRole)
        for i in range(dlg._sidebar.count())
    ]


class TestAsyncFolderDialog:
    def test_opens_on_windows(self, qtbot, fake_windows, tmp_path: Path) -> None:
        """The dialog must construct on Windows, where ``os.getuid`` is absent.

        Regression test: ``_populate_sidebar`` called ``os.getuid()``
        unconditionally, so on Windows the constructor raised inside the
        button's click handler and the picker silently never appeared.
        """
        dlg = _make_dialog(qtbot, tmp_path)
        assert dlg.windowTitle() == "Select folder"
        assert dlg._sidebar.count() >= 1

    def test_windows_sidebar_lists_drives(
        self, qtbot, fake_windows, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Windows gets one entry per mounted drive, not the Unix ``/`` root."""
        class _FakeDrive:
            def __init__(self, path: str) -> None:
                self._path = path

            def absoluteFilePath(self) -> str:  # noqa: N802  (Qt naming)
                return self._path

        monkeypatch.setattr(
            fd.QDir, "drives", staticmethod(lambda: [_FakeDrive("C:/"), _FakeDrive("D:/")])
        )
        dlg = _make_dialog(qtbot, tmp_path)

        assert "C:/" in _sidebar_paths(dlg)
        assert "D:/" in _sidebar_paths(dlg)
        labels = [dlg._sidebar.item(i).text() for i in range(dlg._sidebar.count())]
        assert any(label.endswith("C:") for label in labels)

    def test_unix_sidebar_has_root(self, qtbot, tmp_path: Path) -> None:
        """On Unix the sidebar still offers Home and ``/``."""
        dlg = _make_dialog(qtbot, tmp_path)
        assert "/" in _sidebar_paths(dlg)

    def test_gvfs_scan_survives_oserror(
        self, qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unreadable /run/user/<uid>/gvfs must not break the sidebar."""
        dlg = _make_dialog(qtbot, tmp_path)
        before = dlg._sidebar.count()

        class _RaisingPath:
            def __init__(self, *_a, **_kw) -> None:
                pass

            def is_dir(self) -> bool:
                raise PermissionError("gvfs is not readable")

        monkeypatch.setattr(fd, "Path", _RaisingPath)
        dlg._populate_gvfs_mounts()  # must not raise
        assert dlg._sidebar.count() == before
