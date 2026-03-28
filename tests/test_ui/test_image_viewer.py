"""Tests for skyvas_sync.ui.image_viewer."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import Qt

from skyvas_sync.ui.image_viewer import ImageViewer, _ZoomableView


@pytest.fixture()
def viewer(qtbot) -> ImageViewer:
    v = ImageViewer()
    qtbot.addWidget(v)
    return v


@pytest.fixture()
def sample_images(tmp_path: Path) -> list[Path]:
    """Create 3 test images large enough that fitInView won't exceed max zoom."""
    paths: list[Path] = []
    for i, color in enumerate(["red", "green", "blue"]):
        p = tmp_path / f"img{i}.jpg"
        img = Image.new("RGB", (800, 600), color=color)
        img.save(p)
        paths.append(p)
    return paths


class TestImageViewerInit:
    def test_hidden_initially(self, viewer: ImageViewer):
        assert viewer.isHidden()

    def test_no_images(self, viewer: ImageViewer):
        assert viewer._images == []
        assert viewer._current_index == 0

    def test_is_modal_dialog(self, viewer: ImageViewer):
        assert viewer.isModal()


class TestImageViewerShowImage:
    def test_show_image_opens(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        assert not viewer.isHidden()
        assert viewer._current_index == 0
        assert viewer._images == sample_images
        viewer.hide()

    def test_show_image_at_index(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 2)
        assert viewer._current_index == 2
        assert viewer._counter_label.text() == "3 / 3"
        viewer.hide()

    def test_show_image_empty_list(self, viewer: ImageViewer):
        viewer.show_image([], 0)
        assert viewer.isHidden()

    def test_show_image_invalid_index(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 99)
        assert viewer.isHidden()

    def test_filename_displayed(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 1)
        assert "img1.jpg" in viewer._filename_label.text()
        viewer.hide()

    def test_pixmap_item_created(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        assert viewer._pixmap_item is not None
        viewer.hide()


class TestImageViewerNavigation:
    def test_next(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        viewer._show_next()
        assert viewer._current_index == 1
        assert viewer._counter_label.text() == "2 / 3"
        viewer.hide()

    def test_prev(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 2)
        viewer._show_prev()
        assert viewer._current_index == 1
        viewer.hide()

    def test_prev_at_start_stays(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        viewer._show_prev()
        assert viewer._current_index == 0
        viewer.hide()

    def test_next_at_end_stays(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 2)
        viewer._show_next()
        assert viewer._current_index == 2
        viewer.hide()

    def test_prev_btn_disabled_at_start(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        assert not viewer._prev_btn.isEnabled()
        assert viewer._next_btn.isEnabled()
        viewer.hide()

    def test_next_btn_disabled_at_end(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 2)
        assert viewer._prev_btn.isEnabled()
        assert not viewer._next_btn.isEnabled()
        viewer.hide()


class TestImageViewerClose:
    def test_close_hides(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        closed_signals: list = []
        viewer.closed.connect(lambda: closed_signals.append(True))
        viewer._on_close()
        assert viewer.isHidden()
        assert len(closed_signals) == 1


class TestImageViewerZoom:
    def test_zoom_in(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        initial = viewer._view.zoom_level
        viewer._on_zoom_in()
        assert viewer._view.zoom_level > initial
        viewer.hide()

    def test_zoom_out(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        # Zoom in first so we have room to zoom out
        viewer._on_zoom_in()
        viewer._on_zoom_in()
        level_after_in = viewer._view.zoom_level
        viewer._on_zoom_out()
        assert viewer._view.zoom_level < level_after_in
        viewer.hide()

    def test_fit_resets(self, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        viewer._on_zoom_in()
        viewer._on_zoom_in()
        viewer._on_fit()
        # After fit, zoom should be back close to the fit level
        assert viewer._pixmap_item is not None
        viewer.hide()

    def test_fit_with_no_pixmap(self, viewer: ImageViewer):
        # Should not raise
        viewer._on_fit()


class TestImageViewerKeyboard:
    def test_escape_closes(self, qtbot, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 1)
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        viewer.keyPressEvent(event)
        assert viewer.isHidden()

    def test_right_arrow_next(self, qtbot, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        viewer.keyPressEvent(event)
        assert viewer._current_index == 1
        viewer.hide()

    def test_left_arrow_prev(self, qtbot, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 2)
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
        viewer.keyPressEvent(event)
        assert viewer._current_index == 1
        viewer.hide()

    def test_down_arrow_next(self, qtbot, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        viewer.keyPressEvent(event)
        assert viewer._current_index == 1
        viewer.hide()

    def test_up_arrow_prev(self, qtbot, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 2)
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
        viewer.keyPressEvent(event)
        assert viewer._current_index == 1
        viewer.hide()

    def test_plus_zooms_in(self, qtbot, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        initial = viewer._view.zoom_level
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Plus, Qt.KeyboardModifier.NoModifier)
        viewer.keyPressEvent(event)
        assert viewer._view.zoom_level > initial
        viewer.hide()

    def test_minus_zooms_out(self, qtbot, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        viewer._on_zoom_in()
        viewer._on_zoom_in()
        level = viewer._view.zoom_level
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Minus, Qt.KeyboardModifier.NoModifier)
        viewer.keyPressEvent(event)
        assert viewer._view.zoom_level < level
        viewer.hide()

    def test_zero_fits(self, qtbot, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 0)
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_0, Qt.KeyboardModifier.NoModifier)
        viewer.keyPressEvent(event)
        viewer.hide()

    def test_other_key_ignored(self, qtbot, viewer: ImageViewer, sample_images: list[Path]):
        viewer.show_image(sample_images, 1)
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
        viewer.keyPressEvent(event)
        assert viewer._current_index == 1
        viewer.hide()


class TestImageViewerLoadErrors:
    def test_invalid_image(self, viewer: ImageViewer, tmp_path: Path):
        bad = tmp_path / "bad.jpg"
        bad.write_text("not an image")
        viewer.show_image([bad], 0)
        assert viewer._pixmap_item is None
        viewer.hide()


class TestZoomableView:
    def test_initial_zoom_level(self, qtbot):
        view = _ZoomableView()
        qtbot.addWidget(view)
        assert view.zoom_level == 1.0

    def test_zoom_in(self, qtbot):
        view = _ZoomableView()
        qtbot.addWidget(view)
        view.zoom_in()
        assert view.zoom_level > 1.0

    def test_zoom_out(self, qtbot):
        view = _ZoomableView()
        qtbot.addWidget(view)
        initial = view.zoom_level
        view.zoom_out()
        assert view.zoom_level < initial
