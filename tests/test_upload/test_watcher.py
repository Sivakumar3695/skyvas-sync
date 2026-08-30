"""Tests for skyvas_sync.upload.watcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication

from skyvas_sync.upload.watcher import FolderWatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_image(path: Path, size: tuple[int, int] = (10, 10)) -> None:
    img = Image.new("RGB", size, color="blue")
    img.save(path)


# ---------------------------------------------------------------------------
# FolderWatcher — start / stop / properties
# ---------------------------------------------------------------------------

class TestFolderWatcherInit:
    def test_initial_state(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path)

        assert w.root == tmp_path
        assert not w.is_active
        assert w.known_files == frozenset()

    def test_start_with_empty_folder(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()
        assert w.is_active
        assert w.known_files == frozenset()
        w.stop()

    def test_start_returns_existing_images(self, qtbot, tmp_path: Path):
        _create_image(tmp_path / "a.jpg")
        _create_image(tmp_path / "b.png")
        (tmp_path / "notes.txt").write_text("skip")

        w = FolderWatcher(tmp_path, stabilize_ms=0)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()
        assert len(w.known_files) == 2
        names = {Path(p).name for p in w.known_files}
        assert "a.jpg" in names
        assert "b.png" in names
        assert w.is_active
        w.stop()

    def test_start_includes_subfolder_images(self, qtbot, tmp_path: Path):
        sub = tmp_path / "day1"
        sub.mkdir()
        _create_image(tmp_path / "root.jpg")
        _create_image(sub / "sub.jpg")

        w = FolderWatcher(tmp_path, stabilize_ms=0)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()
        assert len(w.known_files) == 2
        w.stop()

    def test_start_twice_returns_cached(self, qtbot, tmp_path: Path):
        _create_image(tmp_path / "a.jpg")
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()
        kf1 = frozenset(w.known_files)
        w.start()  # second call is a no-op
        assert w.known_files == kf1
        w.stop()

    def test_start_nonexistent_folder(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path / "nope", stabilize_ms=0)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()
        assert w.known_files == frozenset()
        w.stop()

    def test_stop_clears_active(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        w.start()
        assert w.is_active
        w.stop()
        assert not w.is_active

    def test_stop_when_not_started(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        w.stop()  # Should not raise
        assert not w.is_active


class TestFolderWatcherKnownFiles:
    def test_known_files_returns_frozenset(self, qtbot, tmp_path: Path):
        _create_image(tmp_path / "a.jpg")
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()
        kf = w.known_files
        assert isinstance(kf, frozenset)
        assert len(kf) == 1
        w.stop()


# ---------------------------------------------------------------------------
# FolderWatcher — new file detection via _process_pending
# ---------------------------------------------------------------------------

class TestFolderWatcherNewFiles:
    def test_new_image_emits_file_found(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        w.start()

        # Create a new image file after starting
        _create_image(tmp_path / "new.jpg")

        # Simulate what QFileSystemWatcher would do
        signals = []
        w.file_found.connect(lambda p: signals.append(p))
        w._pending_dirs.add(str(tmp_path))
        w._process_pending()

        assert len(signals) == 1
        assert "new.jpg" in signals[0]
        w.stop()

    def test_non_image_ignored(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        w.start()

        (tmp_path / "readme.txt").write_text("hello")

        signals = []
        w.file_found.connect(lambda p: signals.append(p))
        w._pending_dirs.add(str(tmp_path))
        w._process_pending()

        assert len(signals) == 0
        w.stop()

    def test_existing_files_not_signalled(self, qtbot, tmp_path: Path):
        _create_image(tmp_path / "existing.jpg")
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()

        signals = []
        w.file_found.connect(lambda p: signals.append(p))
        # Process the root dir — existing file should be in known_files already
        w._pending_dirs.add(str(tmp_path))
        w._process_pending()

        assert len(signals) == 0
        w.stop()

    def test_duplicate_file_not_signalled_twice(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        w.start()

        _create_image(tmp_path / "dup.jpg")

        signals = []
        w.file_found.connect(lambda p: signals.append(p))
        w._pending_dirs.add(str(tmp_path))
        w._process_pending()
        assert len(signals) == 1

        # Process again — should not emit duplicate
        w._pending_dirs.add(str(tmp_path))
        w._process_pending()
        assert len(signals) == 1  # still 1
        w.stop()


# ---------------------------------------------------------------------------
# FolderWatcher — new subdirectory handling
# ---------------------------------------------------------------------------

class TestFolderWatcherSubdirs:
    def test_new_subdir_with_images(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        w.start()

        # Create a new subdirectory with an image
        sub = tmp_path / "day2"
        sub.mkdir()
        _create_image(sub / "photo.jpg")

        signals = []
        w.file_found.connect(lambda p: signals.append(p))
        w._pending_dirs.add(str(tmp_path))
        w._process_pending()

        assert len(signals) == 1
        assert "photo.jpg" in signals[0]
        w.stop()

    def test_deeply_nested_new_subdir(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        w.start()

        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        _create_image(deep / "deep.jpg")

        signals = []
        w.file_found.connect(lambda p: signals.append(p))
        w._pending_dirs.add(str(tmp_path))
        w._process_pending()

        assert len(signals) == 1
        assert "deep.jpg" in signals[0]
        w.stop()

    def test_new_file_in_existing_subdir(self, qtbot, tmp_path: Path):
        sub = tmp_path / "existing_sub"
        sub.mkdir()
        _create_image(sub / "old.jpg")

        w = FolderWatcher(tmp_path, stabilize_ms=0)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()
        assert len(w.known_files) == 1

        # Add new file to existing subdir
        _create_image(sub / "new.jpg")

        signals = []
        w.file_found.connect(lambda p: signals.append(p))
        w._pending_dirs.add(str(sub))
        w._process_pending()

        assert len(signals) == 1
        assert "new.jpg" in signals[0]
        w.stop()


# ---------------------------------------------------------------------------
# FolderWatcher — _on_dir_changed debouncing
# ---------------------------------------------------------------------------

class TestFolderWatcherDebounce:
    def test_on_dir_changed_adds_to_pending(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=5000)

        w.start()

        w._on_dir_changed(str(tmp_path))
        assert str(tmp_path) in w._pending_dirs
        w.stop()

    def test_on_dir_changed_inactive_ignored(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        # Not started
        w._on_dir_changed(str(tmp_path))
        assert len(w._pending_dirs) == 0

    def test_process_pending_inactive_ignored(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        # Not started -> _active is False
        _create_image(tmp_path / "test.jpg")
        w._pending_dirs.add(str(tmp_path))
        signals = []
        w.file_found.connect(lambda p: signals.append(p))
        w._process_pending()
        assert len(signals) == 0

    def test_process_pending_nonexistent_dir(self, qtbot, tmp_path: Path):
        w = FolderWatcher(tmp_path, stabilize_ms=0)

        w.start()

        signals = []
        w.file_found.connect(lambda p: signals.append(p))
        w._pending_dirs.add(str(tmp_path / "nonexistent"))
        w._process_pending()  # Should not raise
        assert len(signals) == 0
        w.stop()


# ---------------------------------------------------------------------------
# FolderWatcher — polling fallback (MTP/GVFS support)
# ---------------------------------------------------------------------------

class TestFolderWatcherPolling:
    def test_poll_detects_new_file(self, qtbot, tmp_path: Path):
        """A file added after baseline is discovered on the next poll tick."""
        w = FolderWatcher(tmp_path, stabilize_ms=0, poll_interval_ms=100)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()

        # Drop a new image after the baseline is established
        _create_image(tmp_path / "new.jpg")

        with qtbot.waitSignal(w.file_found, timeout=3000) as blocker:
            pass  # poll timer fires within 100 ms

        assert "new.jpg" in blocker.args[0]
        w.stop()

    def test_poll_does_not_re_emit_known_files(self, qtbot, tmp_path: Path):
        """Files that existed at baseline are never re-emitted during polling."""
        _create_image(tmp_path / "existing.jpg")
        w = FolderWatcher(tmp_path, stabilize_ms=0, poll_interval_ms=100)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()

        signals: list[str] = []
        w.file_found.connect(signals.append)

        # Let two poll ticks fire
        qtbot.wait(300)

        assert len(signals) == 0
        w.stop()

    def test_poll_detects_file_in_new_subfolder(self, qtbot, tmp_path: Path):
        """A file in a brand-new subfolder is found on the next poll tick."""
        w = FolderWatcher(tmp_path, stabilize_ms=0, poll_interval_ms=100)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()

        sub = tmp_path / "camera"
        sub.mkdir()
        _create_image(sub / "photo.jpg")

        with qtbot.waitSignal(w.file_found, timeout=3000) as blocker:
            pass

        assert "photo.jpg" in blocker.args[0]
        w.stop()

    def test_no_poll_timer_when_interval_zero(self, qtbot, tmp_path: Path):
        """poll_interval_ms=0 disables the polling timer entirely."""
        w = FolderWatcher(tmp_path, stabilize_ms=0, poll_interval_ms=0)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()

        assert w._poll_timer is None
        w.stop()

    def test_stop_while_poll_scan_running(self, qtbot, tmp_path: Path):
        """stop() safely cancels an in-flight poll scan without hanging."""
        # Use a large directory tree to increase the chance the thread is mid-scan
        for i in range(10):
            sub = tmp_path / f"dir{i}"
            sub.mkdir()
            _create_image(sub / f"img{i}.jpg")

        w = FolderWatcher(tmp_path, stabilize_ms=0, poll_interval_ms=50)

        with qtbot.waitSignal(w.scan_completed, timeout=3000):
            w.start()

        # Let the poll timer fire at least once so a poll scan starts
        qtbot.wait(100)
        w.stop()  # Must not hang or raise
        assert not w.is_active
