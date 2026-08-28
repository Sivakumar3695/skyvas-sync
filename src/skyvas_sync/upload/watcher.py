"""Filesystem watcher for detecting new images in a folder tree."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QThread, QTimer, Signal

from skyvas_sync.utils.image_utils import IMAGE_EXTENSIONS, is_image


class _ScanThread(QThread):
    """Background thread that recursively scans *root* without blocking the UI.

    Uses :func:`os.walk` instead of ``Path.rglob`` so that each directory
    is listed with a single ``readdir`` syscall.  File names are filtered
    by extension (a pure string check — no extra ``stat`` call), which
    makes scanning MTP/GVFS-mounted devices **dramatically** faster.

    Emits ``scan_done(dirs, files)`` on the main thread when finished, where
    *dirs* is the list of sub-directory paths and *files* is the list of
    image file paths found under *root*.
    """

    scan_done = Signal(list, list)  # dirs: list[str], files: list[str]

    def __init__(self, root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._root = root

    def run(self) -> None:  # executed in the background thread
        dirs: list[str] = []
        files: list[str] = []
        root_str = str(self._root)
        try:
            for dirpath, dirnames, filenames in os.walk(root_str):
                if self.isInterruptionRequested():
                    return  # cancelled — do not emit scan_done
                dirs.append(dirpath)
                for fname in filenames:
                    # Extension check is a pure string op — no stat() call.
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in IMAGE_EXTENSIONS:
                        files.append(os.path.join(dirpath, fname))
        except OSError:
            pass
        self.scan_done.emit(dirs, files)


class _PollScanThread(QThread):
    """Lightweight poll thread that detects new images via set-difference.

    For each directory that contained images (leaf dirs like ``Camera/``),
    calls ``os.listdir()`` to get the current filename set, then diffs
    against the snapshot stored after the previous poll.  Only truly new
    filenames are reported — no ``stat()`` calls at all.

    Directories that had **no** image files (e.g. ``DCIM/`` which only
    holds sub-directories) are skipped entirely, which avoids wasting
    USB round-trips on parent directories.

    Emits ``poll_done(new_files, updated_snapshots)`` where
    *updated_snapshots* is ``{dirpath: frozenset_of_image_names}`` for
    every directory that was listed.
    """

    # new_files: list[str], updated_snapshots: dict[str, frozenset[str]]
    poll_done = Signal(list, dict)

    def __init__(
        self,
        image_dirs: list[str],
        dir_snapshots: dict[str, frozenset[str]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._image_dirs = image_dirs
        self._dir_snapshots = dir_snapshots  # {dirpath: frozenset_of_image_names}

    def run(self) -> None:
        new_files: list[str] = []
        updated_snapshots: dict[str, frozenset[str]] = {}
        for dirpath in self._image_dirs:
            if self.isInterruptionRequested():
                return
            try:
                names = os.listdir(dirpath)
            except OSError:
                continue
            # Filter to image filenames (pure string ops — no stat)
            current_images = frozenset(
                fname for fname in names
                if os.path.splitext(fname)[1].lower() in IMAGE_EXTENSIONS
            )
            previous = self._dir_snapshots.get(dirpath, frozenset())
            new_names = current_images - previous
            if new_names:
                for fname in new_names:
                    new_files.append(os.path.join(dirpath, fname))
            # Always store the updated snapshot
            updated_snapshots[dirpath] = current_images
        self.poll_done.emit(new_files, updated_snapshots)


class FolderWatcher(QObject):
    """Watches a folder and its subfolders for new image files.

    Emits ``file_found`` for every new image that appears after
    :meth:`start` is called.  Existing files at start-up are recorded
    but **not** signalled.

    New-file detection uses two complementary mechanisms so it works on
    both normal filesystems and slow/virtual ones (e.g. MTP-mounted Android
    phones over USB):

    1. **inotify via QFileSystemWatcher** — instant on local/network drives,
       but *does not work* on MTP/GVFS mounts because inotify requires a
       real kernel-backed filesystem.
    2. **Periodic polling** — a background thread re-scans the folder tree
       every ``poll_interval_ms`` milliseconds and emits ``file_found`` for
       any newly appeared image.  This is the only reliable mechanism for
       MTP mounts.  Set ``poll_interval_ms=0`` to disable polling.
    """

    file_found = Signal(str)   # absolute path of new image
    scan_completed = Signal()  # emitted once the initial baseline scan is done
    poll_started = Signal()    # emitted when a periodic poll scan begins
    poll_finished = Signal(int)  # emitted when a poll scan ends (# new files)

    def __init__(
        self,
        root: Path,
        parent: QObject | None = None,
        stabilize_ms: int = 1000,
        poll_interval_ms: int = 5000,
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._stabilize_ms = stabilize_ms
        self._poll_interval_ms = poll_interval_ms
        self._fs_watcher = QFileSystemWatcher(parent=self)
        self._known_files: set[str] = set()
        self._known_dirs: list[str] = []
        self._image_dirs: list[str] = []  # dirs that actually contain images
        self._dir_snapshots: dict[str, frozenset[str]] = {}  # per-dir image names
        self._active = False
        self._pending_dirs: set[str] = set()
        self._timer: QTimer | None = None
        self._scan_thread: _ScanThread | None = None
        self._poll_timer: QTimer | None = None
        self._poll_scan_thread: _PollScanThread | None = None

    # -- public properties ---------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def known_files(self) -> frozenset[str]:
        return frozenset(self._known_files)

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Begin watching.

        Returns immediately; the initial directory scan runs in a background
        thread so the GUI stays responsive even when the folder is on a slow
        external device (e.g. an MTP-mounted Android phone).
        ``known_files`` will be populated once the background scan finishes.
        """
        if self._active:
            return

        self._active = True

        # Watch the root directory right away (fast — single path add)
        if self._root.is_dir():
            self._fs_watcher.addPath(str(self._root))

        self._fs_watcher.directoryChanged.connect(self._on_dir_changed)

        # Kick off the recursive scan in the background so we don't freeze
        # the main thread when the folder lives on an MTP/GVFS device.
        self._scan_thread = _ScanThread(self._root, parent=self)
        self._scan_thread.scan_done.connect(self._on_initial_scan_done)
        self._scan_thread.start()

    def stop(self) -> None:
        """Stop watching and clean up resources."""
        self._active = False

        # Stop polling timer first so no new poll scans are started
        if self._poll_timer is not None:
            self._poll_timer.stop()

        # Cancel any in-flight poll scan
        if self._poll_scan_thread is not None:
            self._poll_scan_thread.poll_done.disconnect(self._on_poll_scan_done)
            self._poll_scan_thread.requestInterruption()
            self._poll_scan_thread.quit()
            self._poll_scan_thread.wait()
            self._poll_scan_thread = None

        # Cancel any in-flight initial scan
        if self._scan_thread is not None:
            self._scan_thread.scan_done.disconnect(self._on_initial_scan_done)
            self._scan_thread.requestInterruption()
            self._scan_thread.quit()
            self._scan_thread.wait()
            self._scan_thread = None

        dirs = self._fs_watcher.directories()
        if dirs:
            self._fs_watcher.removePaths(dirs)

        try:
            self._fs_watcher.directoryChanged.disconnect(self._on_dir_changed)
        except (RuntimeError, TypeError):
            pass

        self._pending_dirs.clear()
        if self._timer is not None:
            self._timer.stop()

    # -- internal slots ------------------------------------------------------

    def _on_initial_scan_done(self, dirs: list[str], files: list[str]) -> None:
        """Called on the main thread when the initial background scan finishes."""
        self._scan_thread = None
        if not self._active:
            return
        # Register all discovered sub-directories with the filesystem watcher
        if dirs:
            self._fs_watcher.addPaths(dirs)
        # Record existing directories so poll scans only check known paths
        self._known_dirs = list(dirs)
        # Record existing files as baseline (they will NOT be uploaded)
        self._known_files.update(files)

        # Build per-directory filename snapshots so poll scans can detect
        # new files via cheap set-difference.  Only directories that actually
        # contain images are tracked — parent dirs (e.g. DCIM/) are skipped
        # to avoid wasting USB round-trips on large subdirectory trees.
        # The root is always included so new images landing there are detected
        # even if the folder started empty.
        dir_snapshots: dict[str, set[str]] = {}
        root_str = str(self._root)
        dir_snapshots[root_str] = set()  # ensure root is always polled
        for fpath in files:
            dirpath = os.path.dirname(fpath)
            fname = os.path.basename(fpath)
            dir_snapshots.setdefault(dirpath, set()).add(fname)
        self._dir_snapshots = {
            d: frozenset(names) for d, names in dir_snapshots.items()
        }
        self._image_dirs = list(self._dir_snapshots.keys())
        self.scan_completed.emit()

        # Start periodic polling — the only reliable new-file detection mechanism
        # for MTP/GVFS-mounted devices where inotify does not fire.
        if self._poll_interval_ms > 0:
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(self._poll_interval_ms)
            self._poll_timer.timeout.connect(self._on_poll_tick)
            self._poll_timer.start()

    def _on_poll_tick(self) -> None:
        """Periodic timer slot: kick off a background poll scan if none is running."""
        if not self._active or self._poll_scan_thread is not None:
            return  # previous poll still in progress — skip this tick
        self._poll_scan_thread = _PollScanThread(
            self._image_dirs,
            dict(self._dir_snapshots),
            parent=self,
        )
        self._poll_scan_thread.poll_done.connect(self._on_poll_scan_done)
        self._poll_scan_thread.start()
        self.poll_started.emit()

    def _on_poll_scan_done(
        self,
        new_files: list[str],
        updated_snapshots: dict[str, frozenset[str]],
    ) -> None:
        """Called on the main thread when a poll scan finishes."""
        self._poll_scan_thread = None
        if not self._active:
            return

        # Update the per-directory snapshots for next poll
        self._dir_snapshots.update(updated_snapshots)

        # Emit file_found for every newly discovered image
        for file_path in new_files:
            if file_path not in self._known_files:
                self._known_files.add(file_path)
                self.file_found.emit(file_path)
        self.poll_finished.emit(len(new_files))

    def _on_dir_changed(self, dir_path: str) -> None:
        """Called by QFileSystemWatcher when a directory's contents change."""
        if not self._active:
            return

        self._pending_dirs.add(dir_path)

        # Debounce: restart timer on each change so we wait until the burst
        # of filesystem operations settles down.
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._process_pending)
        self._timer.start(self._stabilize_ms)

    def _process_pending(self) -> None:
        """Scan pending directories for new images and sub-directories."""
        if not self._active:
            return

        dirs_to_check = set(self._pending_dirs)
        self._pending_dirs.clear()

        for dir_path in dirs_to_check:
            try:
                entries = os.scandir(dir_path)
            except OSError:
                continue

            with entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        entry_path = entry.path
                        watched = self._fs_watcher.directories()
                        if entry_path not in watched:
                            self._fs_watcher.addPath(entry_path)
                            self._known_dirs.append(entry_path)
                            # Recursively watch and discover images in new trees
                            for sub_dir, _, sub_files in os.walk(entry_path):
                                self._fs_watcher.addPath(sub_dir)
                                self._known_dirs.append(sub_dir)
                                for fname in sub_files:
                                    ext = os.path.splitext(fname)[1].lower()
                                    if ext in IMAGE_EXTENSIONS:
                                        fpath = os.path.join(sub_dir, fname)
                                        if fpath not in self._known_files:
                                            self._known_files.add(fpath)
                                            self.file_found.emit(fpath)
                                        # Track for future poll scans
                                        self.__add_to_image_dirs(sub_dir, fname)
                    elif entry.is_file(follow_symlinks=False):
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in IMAGE_EXTENSIONS:
                            fpath = entry.path
                            if fpath not in self._known_files:
                                self._known_files.add(fpath)
                                self.file_found.emit(fpath)
                            self.__add_to_image_dirs(dir_path, entry.name)

    def __add_to_image_dirs(self, dirpath: str, fname: str) -> None:
        """Register *dirpath* as an image directory for future poll scans."""
        if dirpath not in self._dir_snapshots:
            self._dir_snapshots[dirpath] = frozenset({fname})
            self._image_dirs.append(dirpath)
        else:
            self._dir_snapshots[dirpath] = self._dir_snapshots[dirpath] | {fname}
