"""Tests for skyvas_sync.ui.album_view."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from skyvas_sync.ui.album_view import AlbumView, _ThumbnailLoader


@pytest.fixture()
def album_view(qtbot) -> AlbumView:
    view = AlbumView()
    qtbot.addWidget(view)
    return view


class TestAlbumView:
    def test_initial_state(self, album_view: AlbumView):
        assert album_view._root is None
        assert album_view._folder_tree == {}
        assert album_view._thumb_labels == []

    def test_set_folder(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        assert album_view._root == image_folder
        assert "." in album_view._folder_tree
        assert "day2" in album_view._folder_tree

    def test_tree_model_populated(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        model = album_view._tree_model
        root = model.invisibleRootItem()
        assert root.rowCount() >= 2  # root folder + day2

    def test_set_empty_folder(self, album_view: AlbumView, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        album_view.set_folder(empty)
        assert album_view._folder_tree == {}
        model = album_view._tree_model
        assert model.invisibleRootItem().rowCount() == 0

    def test_clear_grid(self, album_view: AlbumView):
        # Add some dummy labels
        from PySide6.QtWidgets import QLabel
        for i in range(3):
            label = QLabel(f"test{i}")
            album_view._grid_layout.addWidget(label)
            album_view._thumb_labels.append(label)
        assert album_view._grid_layout.count() == 3

        album_view._clear_grid()
        assert album_view._grid_layout.count() == 0
        assert album_view._thumb_labels == []


class TestAlbumViewFolderSelection:
    def test_show_thumbnails_creates_labels(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        images = album_view._folder_tree.get(".", [])
        with patch("skyvas_sync.ui.album_view._ThumbnailLoader"):
            album_view._show_thumbnails(images)
        assert len(album_view._thumb_labels) == len(images)

    def test_show_thumbnails_empty(self, album_view: AlbumView):
        album_view._show_thumbnails([])
        assert len(album_view._thumb_labels) == 0

    def test_on_folder_selected(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        model = album_view._tree_model
        root = model.invisibleRootItem()

        # Find the root item and click it
        for i in range(root.rowCount()):
            item = root.child(i)
            if item.data(Qt.ItemDataRole.UserRole) == ".":
                index = model.indexFromItem(item)
                with patch("skyvas_sync.ui.album_view._ThumbnailLoader"):
                    album_view._on_folder_selected(index)
                assert len(album_view._thumb_labels) == 2  # 2 images in root
                break

    def test_on_folder_selected_none_item(self, album_view: AlbumView):
        # Should not raise when item is None
        mock_index = MagicMock()
        with patch.object(album_view._tree_model, "itemFromIndex", return_value=None):
            album_view._on_folder_selected(mock_index)


class TestAlbumViewThumbnails:
    def test_on_thumbnail_ready(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        images = album_view._folder_tree.get(".", [])
        with patch("skyvas_sync.ui.album_view._ThumbnailLoader"):
            album_view._show_thumbnails(images)

        # Simulate thumbnail ready
        img = Image.new("RGB", (100, 80), color="green")
        from PySide6.QtGui import QImage
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, 100, 80, 300, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        album_view._on_thumbnail_ready(0, pixmap)

        # Label should now have a pixmap (no text)
        assert album_view._thumb_labels[0].text() == ""

    def test_on_thumbnail_ready_out_of_range(self, album_view: AlbumView):
        # Should not raise
        pixmap = QPixmap(10, 10)
        album_view._on_thumbnail_ready(999, pixmap)

    def test_nested_folder_tree(self, album_view: AlbumView, tmp_path: Path):
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        img = Image.new("RGB", (10, 10))
        img.save(deep / "nested.jpg")
        img.save(tmp_path / "root.jpg")

        album_view.set_folder(tmp_path)
        assert "a/b/c" in album_view._folder_tree
        assert "." in album_view._folder_tree


class TestThumbnailLoader:
    def test_cancel_flag(self):
        loader = _ThumbnailLoader([])
        assert not loader._cancelled
        loader.cancel()
        assert loader._cancelled


class TestThumbnailLoaderDirect:
    """Call run() directly for coverage of the thread body."""

    def test_run_loads_thumbnails(self, tmp_path: Path):
        # Create dedicated images for this test to avoid PIL threading issues
        img = Image.new("RGB", (80, 60), color="blue")
        p1 = tmp_path / "a.jpg"
        img.save(p1)
        p2 = tmp_path / "b.png"
        img.save(p2)

        loader = _ThumbnailLoader([p1, p2])
        results = []
        loader.thumbnail_ready.connect(lambda idx, px: results.append((idx, px)))
        loader.run()
        assert len(results) == 2
        for idx, pixmap in results:
            assert isinstance(pixmap, QPixmap)

    def test_run_cancel(self, tmp_path: Path):
        img = Image.new("RGB", (10, 10))
        p = tmp_path / "c.jpg"
        img.save(p)
        loader = _ThumbnailLoader([p])
        loader.cancel()
        results = []
        loader.thumbnail_ready.connect(lambda idx, px: results.append(idx))
        loader.run()
        assert len(results) == 0

    def test_run_invalid_image_skipped(self, tmp_path: Path):
        bad_file = tmp_path / "bad.jpg"
        bad_file.write_text("not an image")
        loader = _ThumbnailLoader([bad_file])
        results = []
        loader.thumbnail_ready.connect(lambda idx, px: results.append(idx))
        loader.run()
        assert len(results) == 0


class TestAlbumViewSwitchFolder:
    def test_switching_folders_clears_old(self, album_view: AlbumView, image_folder: Path, tmp_path: Path):
        album_view.set_folder(image_folder)
        images = album_view._folder_tree.get(".", [])
        with patch("skyvas_sync.ui.album_view._ThumbnailLoader"):
            album_view._show_thumbnails(images)
        first_count = len(album_view._thumb_labels)
        assert first_count > 0

        # Switch to empty folder
        empty = tmp_path / "empty"
        empty.mkdir()
        album_view.set_folder(empty)
        assert album_view._thumb_labels == []

    def test_show_thumbnails_cancels_running_loader(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        images = album_view._folder_tree.get(".", [])

        # Give the loader a mock isRunning that returns True
        mock_loader = MagicMock()
        mock_loader.isRunning.return_value = True
        album_view._loader = mock_loader

        # Calling _show_thumbnails should cancel the "running" loader
        with patch("skyvas_sync.ui.album_view._ThumbnailLoader"):
            album_view._show_thumbnails(images)
        mock_loader.cancel.assert_called_once()
        mock_loader.wait.assert_called_once()


class TestAlbumViewFolderName:
    def test_root_shows_folder_name(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        model = album_view._tree_model
        root = model.invisibleRootItem()
        # Find the "." item and check its label uses the actual folder name
        for i in range(root.rowCount()):
            item = root.child(i)
            if item.data(Qt.ItemDataRole.UserRole) == ".":
                assert image_folder.name in item.text()
                assert "(root)" not in item.text()
                break
        else:
            pytest.fail("Root folder item not found")


class TestAlbumViewClickableThumbnail:
    def test_thumb_click_opens_viewer(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        images = album_view._folder_tree.get(".", [])
        with patch("skyvas_sync.ui.album_view._ThumbnailLoader"):
            album_view._show_thumbnails(images)
        with patch.object(album_view._image_viewer, "show_image") as mock_show:
            album_view._on_thumb_clicked(0)
            mock_show.assert_called_once_with(images, 0)

    def test_current_images_stored(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        images = album_view._folder_tree.get(".", [])
        with patch("skyvas_sync.ui.album_view._ThumbnailLoader"):
            album_view._show_thumbnails(images)
        assert album_view._current_images == images


class TestAlbumViewMultiRoot:
    def test_set_folders_multiple_roots(self, album_view: AlbumView, tmp_path: Path):
        """Multiple roots should show each root as a top-level node."""
        r1 = tmp_path / "folderA"
        r1.mkdir()
        r2 = tmp_path / "folderB"
        r2.mkdir()
        img = Image.new("RGB", (40, 30))
        img.save(r1 / "a.jpg")
        img.save(r2 / "b.jpg")

        album_view.set_folders([r1, r2])

        assert "folderA" in album_view._folder_tree
        assert "folderB" in album_view._folder_tree
        model = album_view._tree_model
        root = model.invisibleRootItem()
        assert root.rowCount() == 2

    def test_set_folders_single_uses_dot_key(self, album_view: AlbumView, image_folder: Path):
        """Single root should keep dot-key convention."""
        album_view.set_folders([image_folder])
        assert "." in album_view._folder_tree

    def test_set_folder_delegates_to_set_folders(self, album_view: AlbumView, image_folder: Path):
        album_view.set_folder(image_folder)
        assert album_view._roots == [image_folder]
        assert "." in album_view._folder_tree
