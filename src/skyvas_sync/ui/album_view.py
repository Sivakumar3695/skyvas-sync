"""Album view — browse local folder images organised by subfolder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QLayout,
    QLayoutItem,
    QWidgetItem,
)
from PySide6.QtCore import QRect, QPoint

from skyvas_sync.ui.image_viewer import ImageViewer
from skyvas_sync.upload.scanner import build_folder_tree
from skyvas_sync.utils.image_utils import THUMBNAIL_SIZE, create_thumbnail

_THUMB_W, _THUMB_H = THUMBNAIL_SIZE
_THUMB_SPACING = 8


class _FlowLayout(QLayout):
    """A layout that arranges widgets in a flowing grid, wrapping to fill width."""

    def __init__(self, parent: QWidget | None = None, spacing: int = _THUMB_SPACING) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            item_size = item.sizeHint()
            next_x = x + item_size.width() + self._spacing
            if next_x - self._spacing > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + self._spacing
                next_x = x + item_size.width() + self._spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))
            x = next_x
            line_height = max(line_height, item_size.height())

        return y + line_height - rect.y() + m.bottom()


class _ClickableLabel(QLabel):
    """A QLabel that emits a signal with its index when clicked."""

    clicked = Signal(int)

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index

    def mousePressEvent(self, event: object) -> None:  # noqa: N802
        self.clicked.emit(self._index)
        super().mousePressEvent(event)


class _ThumbnailLoader(QThread):
    """Load thumbnails for a list of image paths in the background."""

    thumbnail_ready = Signal(int, QPixmap)  # index, pixmap

    def __init__(self, paths: list[Path], parent: QThread | None = None) -> None:
        super().__init__(parent)
        self._paths = paths
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for idx, path in enumerate(self._paths):
            if self._cancelled:
                break
            try:
                thumb = create_thumbnail(path)
                data = thumb.tobytes("raw", "RGB")
                qimg = QImage(
                    data, thumb.width, thumb.height, 3 * thumb.width, QImage.Format.Format_RGB888,
                )
                # Must copy — data buffer goes out of scope
                pixmap = QPixmap.fromImage(qimg.copy())
                self.thumbnail_ready.emit(idx, pixmap)
            except Exception:  # noqa: BLE001
                pass  # skip unreadable images


class AlbumView(QWidget):
    """Two-panel album browser: folder tree on the left, thumbnails on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._root: Path | None = None
        self._roots: list[Path] = []
        self._folder_tree: dict[str, list[Path]] = {}
        self._loader: _ThumbnailLoader | None = None
        self._thumb_labels: list[QLabel] = []
        self._current_images: list[Path] = []
        self._setup_ui()
        self._image_viewer = ImageViewer(self)

    # -- UI -----------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: folder tree
        self._tree_model = QStandardItemModel()
        self._tree_model.setHorizontalHeaderLabels(["Folders"])
        self._tree_view = QTreeView()
        self._tree_view.setModel(self._tree_model)
        self._tree_view.setHeaderHidden(False)
        self._tree_view.setMinimumWidth(180)
        self._tree_view.clicked.connect(self._on_folder_selected)
        splitter.addWidget(self._tree_view)

        # Right: thumbnail grid inside scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._grid_container = QWidget()
        self._grid_layout = _FlowLayout(self._grid_container)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(self._grid_container)
        splitter.addWidget(scroll)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # Set explicit initial sizes: ~20% folders, ~80% thumbnails
        splitter.setSizes([180, 720])

        layout.addWidget(splitter)

    # -- public API ---------------------------------------------------------

    def set_folder(self, root: Path) -> None:
        """Load a single folder and populate the tree view."""
        self.set_folders([root])

    def set_folders(self, roots: list[Path]) -> None:
        """Load one or more folders and populate the tree view."""
        self._roots = roots
        self._root = roots[0] if roots else None
        self._folder_tree = {}
        for root in roots:
            tree = build_folder_tree(root)
            if len(roots) == 1:
                # Single root — use keys as-is
                self._folder_tree.update(tree)
            else:
                # Multiple roots — prefix keys with root folder name
                for key, images in tree.items():
                    if key == ".":
                        full_key = root.name
                    else:
                        full_key = f"{root.name}/{key}"
                    self._folder_tree[full_key] = images
        self._build_tree()
        self._clear_grid()

    # -- tree ---------------------------------------------------------------

    def _build_tree(self) -> None:
        self._tree_model.clear()
        self._tree_model.setHorizontalHeaderLabels(["Folders"])
        root_item = self._tree_model.invisibleRootItem()

        single_root = len(self._roots) == 1

        # Determine display name for the root folder (single-root mode)
        root_name = self._root.name if self._root else "(root)"

        # Build nested items from folder keys
        nodes: dict[str, QStandardItem] = {}
        for folder_key in sorted(self._folder_tree.keys()):
            count = len(self._folder_tree[folder_key])
            if single_root and folder_key == ".":
                item = QStandardItem(f"{root_name} [{count}]")
                item.setData(".", Qt.ItemDataRole.UserRole)
                root_item.appendRow(item)
                nodes["."] = item
            else:
                parts = folder_key.split("/")
                parent = root_item
                for i, part in enumerate(parts):
                    path_so_far = "/".join(parts[: i + 1])
                    if path_so_far not in nodes:
                        label = part
                        if path_so_far in self._folder_tree:
                            label += f" [{len(self._folder_tree[path_so_far])}]"
                        node = QStandardItem(label)
                        node.setData(path_so_far, Qt.ItemDataRole.UserRole)
                        parent.appendRow(node)
                        nodes[path_so_far] = node
                    parent = nodes[path_so_far]

        self._tree_view.expandAll()

    # -- thumbnail grid -----------------------------------------------------

    def _on_folder_selected(self, index: object) -> None:
        item = self._tree_model.itemFromIndex(index)
        if item is None:
            return
        folder_key = item.data(Qt.ItemDataRole.UserRole)
        images = self._folder_tree.get(folder_key, [])
        self._show_thumbnails(images)

    def _show_thumbnails(self, images: list[Path]) -> None:
        # Cancel any running loader
        if self._loader and self._loader.isRunning():
            self._loader.cancel()
            self._loader.wait()

        self._clear_grid()
        self._current_images = list(images)

        # Create placeholder labels
        self._thumb_labels = []
        for idx, img_path in enumerate(images):
            label = _ClickableLabel(idx)
            label.setFixedSize(QSize(_THUMB_W, _THUMB_H))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setText(img_path.name[:15])
            label.setStyleSheet(
                "border: 1px solid #ccc; background: #f8f8f8; font-size: 10px;"
                "cursor: pointer;",
            )
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.setToolTip(str(img_path))
            label.clicked.connect(self._on_thumb_clicked)
            self._grid_layout.addWidget(label)
            self._thumb_labels.append(label)

        # Load thumbnails in background
        if images:
            self._loader = _ThumbnailLoader(images)
            self._loader.thumbnail_ready.connect(self._on_thumbnail_ready)
            self._loader.start()

    def _on_thumbnail_ready(self, idx: int, pixmap: QPixmap) -> None:
        if 0 <= idx < len(self._thumb_labels):
            scaled = pixmap.scaled(
                QSize(_THUMB_W, _THUMB_H),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._thumb_labels[idx].setPixmap(scaled)
            self._thumb_labels[idx].setText("")

    def _on_thumb_clicked(self, index: int) -> None:
        """Open the full image viewer at the clicked thumbnail."""
        self._image_viewer.show_image(self._current_images, index)

    def _clear_grid(self) -> None:
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._thumb_labels = []
