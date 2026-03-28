"""Tests for skyvas_sync.upload.scanner."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from skyvas_sync.upload.scanner import build_folder_tree, scan_folder


class TestScanFolder:
    def test_finds_all_images(self, image_folder: Path):
        images = scan_folder(image_folder)
        names = [p.name for p in images]
        assert "photo1.jpg" in names
        assert "photo2.png" in names
        assert "photo3.jpeg" in names
        assert len(images) == 3

    def test_ignores_non_images(self, image_folder: Path):
        images = scan_folder(image_folder)
        names = [p.name for p in images]
        assert "notes.txt" not in names

    def test_empty_folder(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert scan_folder(empty) == []

    def test_non_existent_folder(self, tmp_path: Path):
        assert scan_folder(tmp_path / "nope") == []

    def test_returns_sorted(self, image_folder: Path):
        images = scan_folder(image_folder)
        paths_str = [str(p) for p in images]
        assert paths_str == sorted(paths_str)

    def test_supports_multiple_extensions(self, tmp_path: Path):
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"):
            img = Image.new("RGB", (10, 10))
            img.save(tmp_path / f"test{ext}")
        # .heic can't be saved by Pillow without plugin, create a dummy
        (tmp_path / "test.heic").write_bytes(b"fake")
        images = scan_folder(tmp_path)
        exts = {p.suffix.lower() for p in images}
        assert ".jpg" in exts
        assert ".png" in exts
        # .heic is listed (by extension match) even if not a valid image
        assert ".heic" in exts

    def test_deduplicate_symlinks(self, tmp_path: Path):
        original = tmp_path / "a.jpg"
        img = Image.new("RGB", (10, 10))
        img.save(original)
        link = tmp_path / "b.jpg"
        link.symlink_to(original)
        images = scan_folder(tmp_path)
        assert len(images) == 1  # deduplicated

    def test_recursive_subfolder(self, image_folder: Path):
        images = scan_folder(image_folder)
        subfolder_images = [p for p in images if "day2" in str(p)]
        assert len(subfolder_images) == 1

    def test_nested_subfolders(self, tmp_path: Path):
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        img = Image.new("RGB", (10, 10))
        img.save(deep / "deep.jpg")
        images = scan_folder(tmp_path)
        assert len(images) == 1
        assert images[0].name == "deep.jpg"


class TestBuildFolderTree:
    def test_basic_structure(self, image_folder: Path):
        tree = build_folder_tree(image_folder)
        assert "." in tree
        assert "day2" in tree
        assert len(tree["."]) == 2  # photo1.jpg, photo2.png
        assert len(tree["day2"]) == 1

    def test_empty_folder(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert build_folder_tree(empty) == {}

    def test_non_existent_folder(self, tmp_path: Path):
        assert build_folder_tree(tmp_path / "nope") == {}

    def test_only_image_dirs_included(self, tmp_path: Path):
        (tmp_path / "only_text").mkdir()
        (tmp_path / "only_text" / "readme.txt").write_text("hello")
        img = Image.new("RGB", (10, 10))
        img.save(tmp_path / "photo.jpg")
        tree = build_folder_tree(tmp_path)
        assert "." in tree
        assert "only_text" not in tree

    def test_nested_paths(self, tmp_path: Path):
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        img = Image.new("RGB", (10, 10))
        img.save(deep / "img.png")
        tree = build_folder_tree(tmp_path)
        assert "a/b" in tree
        assert len(tree["a/b"]) == 1
