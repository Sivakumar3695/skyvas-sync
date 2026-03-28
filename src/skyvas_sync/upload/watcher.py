"""Filesystem watcher for detecting new images in a folder tree."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from skyvas_sync.utils.image_utils import is_image


class FolderWatcher(QObject):
    """Watches a folder and its subfolders for new image files.

    Emits ``file_found`` for every new image that appears after
    :meth:`start` is called.  Existing files at start-up are recorded
    but **not** signalled.
    """

    file_found = Signal(str)  # absolute path of new image

    def __init__(
        self,
        root: Path,
        parent: QObject | None = None,
        stabilize_ms: int = 1000,
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._stabilize_ms = stabilize_ms
        self._fs_watcher = QFileSystemWatcher(parent=self)
        self._known_files: set[str] = set()
        self._active = False
        self._pending_dirs: set[str] = set()
        self._timer: QTimer | None = None

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

    def start(self) -> list[str]:
        """Begin watching.  Returns paths of existing image files (resolved)."""
        if self._active:
            return list(self._known_files)

        self._active = True

        # Collect all directories to watch (root + every sub-directory)
        dirs: list[str] = []
        if self._root.is_dir():
            dirs.append(str(self._root))
            for d in sorted(self._root.rglob("*")):
                if d.is_dir():
                    dirs.append(str(d))
        if dirs:
            self._fs_watcher.addPaths(dirs)

        self._fs_watcher.directoryChanged.connect(self._on_dir_changed)

        # Scan existing files as baseline
        if self._root.is_dir():
            for p in sorted(self._root.rglob("*")):
                if p.is_file() and is_image(p):
                    self._known_files.add(str(p.resolve()))

        return list(self._known_files)

    def stop(self) -> None:
        """Stop watching and clean up resources."""
        self._active = False

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
            changed = Path(dir_path)
            if not changed.is_dir():
                continue

            for entry in sorted(changed.iterdir()):
                if entry.is_dir():
                    # Watch newly created sub-directories
                    entry_str = str(entry)
                    watched = self._fs_watcher.directories()
                    if entry_str not in watched:
                        self._fs_watcher.addPath(entry_str)
                        # Recursively watch and discover images in new trees
                        for sub in sorted(entry.rglob("*")):
                            if sub.is_dir():
                                self._fs_watcher.addPath(str(sub))
                            elif sub.is_file() and is_image(sub):
                                resolved = str(sub.resolve())
                                if resolved not in self._known_files:
                                    self._known_files.add(resolved)
                                    self.file_found.emit(str(sub))
                elif entry.is_file() and is_image(entry):
                    resolved = str(entry.resolve())
                    if resolved not in self._known_files:
                        self._known_files.add(resolved)
                        self.file_found.emit(str(entry))
