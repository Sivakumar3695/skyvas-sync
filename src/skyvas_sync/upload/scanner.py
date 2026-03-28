"""Recursive image scanner for local folders."""

from __future__ import annotations

from pathlib import Path

from skyvas_sync.utils.image_utils import is_image


def scan_folder(root: Path) -> list[Path]:
    """Recursively discover image files under *root*.

    Returns a sorted list of absolute :class:`~pathlib.Path` objects for every
    file whose extension matches :data:`~skyvas_sync.utils.image_utils.IMAGE_EXTENSIONS`.
    Symbolic links are followed but the paths are resolved to avoid
    duplicates.
    """
    if not root.is_dir():
        return []

    images: list[Path] = []
    seen: set[Path] = set()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if is_image(path):
            images.append(path)

    return images


def build_folder_tree(root: Path) -> dict[str, list[Path]]:
    """Build a mapping of ``relative_folder → [image_paths]``.

    The keys are the relative directory paths (as POSIX strings) starting from
    *root*.  The root itself is represented by ``"."``.  Only directories that
    contain at least one image (directly) are included.
    """
    if not root.is_dir():
        return {}

    tree: dict[str, list[Path]] = {}

    for path in sorted(root.rglob("*")):
        if not path.is_file() or not is_image(path):
            continue
        rel_dir = path.parent.relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = "."
        tree.setdefault(rel_dir, []).append(path)

    return tree
