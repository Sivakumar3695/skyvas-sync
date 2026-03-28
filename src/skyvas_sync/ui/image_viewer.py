"""Full-screen image viewer dialog with navigation and zoom."""

from __future__ import annotations

from pathlib import Path

from PIL import ImageOps, Image as PILImage
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QImage,
    QKeyEvent,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


_ZOOM_IN_FACTOR = 1.25
_ZOOM_OUT_FACTOR = 1 / _ZOOM_IN_FACTOR
_MIN_ZOOM = 0.1
_MAX_ZOOM = 10.0


class _ZoomableView(QGraphicsView):
    """A QGraphicsView that supports mouse-wheel zoom."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._zoom_level: float = 1.0
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setRenderHints(
            self.renderHints()
            | self.renderHints().__class__.SmoothPixmapTransform
            | self.renderHints().__class__.Antialiasing
        )
        self.setStyleSheet("background: transparent; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    @property
    def zoom_level(self) -> float:
        return self._zoom_level

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def zoom_in(self) -> None:
        if self._zoom_level * _ZOOM_IN_FACTOR <= _MAX_ZOOM:
            self._zoom_level *= _ZOOM_IN_FACTOR
            self.scale(_ZOOM_IN_FACTOR, _ZOOM_IN_FACTOR)

    def zoom_out(self) -> None:
        if self._zoom_level * _ZOOM_OUT_FACTOR >= _MIN_ZOOM:
            self._zoom_level *= _ZOOM_OUT_FACTOR
            self.scale(_ZOOM_OUT_FACTOR, _ZOOM_OUT_FACTOR)

    def fit_in_view(self, item: QGraphicsPixmapItem) -> None:
        """Reset zoom and fit the item in the viewport."""
        self.resetTransform()
        self._zoom_level = 1.0
        self.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)
        # Record the actual scale that fitInView applied
        self._zoom_level = self.transform().m11()


class ImageViewer(QDialog):
    """Frameless dialog that displays a full-size image with navigation and zoom.

    Signals
    -------
    closed()
        Emitted when the viewer is closed.
    """

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._images: list[Path] = []
        self._current_index: int = 0
        self._pixmap_item: QGraphicsPixmapItem | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setModal(True)
        self._setup_ui()

    # -- UI -----------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setStyleSheet("QDialog { background: #1a1a1a; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar: filename | zoom controls | counter | close
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(12, 8, 12, 4)

        self._filename_label = QLabel("")
        self._filename_label.setStyleSheet("color: #ccc; font-size: 13px;")
        top_bar.addWidget(self._filename_label, stretch=1)

        # Zoom buttons
        btn_style = (
            "QPushButton { color: white; background: #444; border: none; "
            "border-radius: 4px; font-size: 14px; padding: 2px 8px; }"
            "QPushButton:hover { background: #666; }"
        )
        self._zoom_in_btn = QPushButton("+")
        self._zoom_in_btn.setFixedSize(28, 28)
        self._zoom_in_btn.setStyleSheet(btn_style)
        self._zoom_in_btn.clicked.connect(self._on_zoom_in)
        top_bar.addWidget(self._zoom_in_btn)

        self._zoom_out_btn = QPushButton("\u2212")
        self._zoom_out_btn.setFixedSize(28, 28)
        self._zoom_out_btn.setStyleSheet(btn_style)
        self._zoom_out_btn.clicked.connect(self._on_zoom_out)
        top_bar.addWidget(self._zoom_out_btn)

        self._fit_btn = QPushButton("Fit")
        self._fit_btn.setFixedSize(36, 28)
        self._fit_btn.setStyleSheet(btn_style)
        self._fit_btn.clicked.connect(self._on_fit)
        top_bar.addWidget(self._fit_btn)

        self._counter_label = QLabel("")
        self._counter_label.setStyleSheet(
            "color: #ccc; font-size: 13px; margin-left: 12px; margin-right: 8px;"
        )
        top_bar.addWidget(self._counter_label)

        self._close_btn = QPushButton("\u2715")
        self._close_btn.setFixedSize(32, 32)
        self._close_btn.setStyleSheet(
            "QPushButton { color: white; background: #555; border: none; "
            "border-radius: 16px; font-size: 16px; font-weight: bold; }"
            "QPushButton:hover { background: #d44; }"
        )
        self._close_btn.clicked.connect(self._on_close)
        top_bar.addWidget(self._close_btn)

        layout.addLayout(top_bar)

        # Middle: prev | graphics view | next
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(0)

        nav_style = (
            "QPushButton { color: white; background: transparent; border: none; "
            "font-size: 28px; padding: 0; }"
            "QPushButton:hover { background: rgba(255,255,255,30); }"
            "QPushButton:disabled { color: #555; }"
        )
        self._prev_btn = QPushButton("\u25c0")
        self._prev_btn.setFixedWidth(48)
        self._prev_btn.setStyleSheet(nav_style)
        self._prev_btn.clicked.connect(self._show_prev)
        mid.addWidget(self._prev_btn)

        self._scene = QGraphicsScene(self)
        self._view = _ZoomableView(self)
        self._view.setScene(self._scene)
        mid.addWidget(self._view, stretch=1)

        self._next_btn = QPushButton("\u25b6")
        self._next_btn.setFixedWidth(48)
        self._next_btn.setStyleSheet(nav_style)
        self._next_btn.clicked.connect(self._show_next)
        mid.addWidget(self._next_btn)

        layout.addLayout(mid, stretch=1)

    # -- public API ---------------------------------------------------------

    def show_image(self, images: list[Path], index: int) -> None:
        """Open the viewer at the given *index* within *images*."""
        if not images or not (0 <= index < len(images)):
            return
        self._images = images
        self._current_index = index

        # Size dialog to fill the parent window
        parent = self.parent()
        if parent is not None:
            win = parent.window() if hasattr(parent, "window") else parent
            self.setGeometry(win.geometry())
        else:
            self.resize(900, 620)

        self.show()
        self._load_current()
        self.raise_()
        self.setFocus()

    # -- navigation ---------------------------------------------------------

    def _show_prev(self) -> None:
        if self._current_index > 0:
            self._current_index -= 1
            self._load_current()

    def _show_next(self) -> None:
        if self._current_index < len(self._images) - 1:
            self._current_index += 1
            self._load_current()

    def _on_close(self) -> None:
        self.hide()
        self.closed.emit()

    # -- zoom ---------------------------------------------------------------

    def _on_zoom_in(self) -> None:
        self._view.zoom_in()

    def _on_zoom_out(self) -> None:
        self._view.zoom_out()

    def _on_fit(self) -> None:
        if self._pixmap_item is not None:
            self._view.fit_in_view(self._pixmap_item)

    # -- image loading ------------------------------------------------------

    def _load_current(self) -> None:
        path = self._images[self._current_index]
        self._filename_label.setText(path.name)
        self._counter_label.setText(
            f"{self._current_index + 1} / {len(self._images)}"
        )
        self._prev_btn.setEnabled(self._current_index > 0)
        self._next_btn.setEnabled(self._current_index < len(self._images) - 1)

        self._scene.clear()
        self._pixmap_item = None

        try:
            with PILImage.open(path) as img:
                img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")
                data = img.tobytes("raw", "RGB")
                qimg = QImage(
                    data, img.width, img.height,
                    3 * img.width, QImage.Format.Format_RGB888,
                )
                pixmap = QPixmap.fromImage(qimg.copy())
                self._pixmap_item = self._scene.addPixmap(pixmap)
                self._scene.setSceneRect(pixmap.rect().toRectF())
                self._view.fit_in_view(self._pixmap_item)
        except Exception:  # noqa: BLE001
            text_item = self._scene.addText("Unable to load image")
            text_item.setDefaultTextColor(Qt.GlobalColor.gray)

    # -- keyboard -----------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._on_close()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._show_prev()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._show_next()
        elif key == Qt.Key.Key_Plus or key == Qt.Key.Key_Equal:
            self._on_zoom_in()
        elif key == Qt.Key.Key_Minus:
            self._on_zoom_out()
        elif key == Qt.Key.Key_0:
            self._on_fit()
        else:
            super().keyPressEvent(event)
