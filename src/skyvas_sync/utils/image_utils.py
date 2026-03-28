"""Image utilities — dimension reading, thumbnail creation, format detection."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

#: Supported image extensions (lowercase, with dot).
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif", ".heic"}
)

#: Default thumbnail size (width, height).
THUMBNAIL_SIZE: tuple[int, int] = (200, 200)


def is_image(path: Path) -> bool:
    """Return *True* if *path* has a recognised image extension."""
    return path.suffix.lower() in IMAGE_EXTENSIONS


def get_image_dimensions(path: Path) -> tuple[int, int]:
    """Return ``(width, height)`` of an image file.

    Raises :class:`OSError` / :class:`PIL.UnidentifiedImageError` on failure.
    """
    with Image.open(path) as img:
        return img.size  # (width, height)


def create_thumbnail(path: Path, size: tuple[int, int] = THUMBNAIL_SIZE) -> Image.Image:
    """Return a thumbnail :class:`~PIL.Image.Image` for *path*.

    The returned image is in RGB mode and fits within *size* while preserving
    the aspect ratio.
    """
    with Image.open(path) as img:
        # Apply EXIF orientation so images are not displayed rotated
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail(size, Image.Resampling.LANCZOS)
        return img.copy()


def get_mime_type(path: Path) -> str:
    """Return a MIME type string suitable for the ``Content-Type`` header."""
    ext = path.suffix.lower()
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".heic": "image/heic",
    }
    return mapping.get(ext, "application/octet-stream")
