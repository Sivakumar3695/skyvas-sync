"""Image utilities — dimension reading, thumbnail creation, format detection."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

#: Supported image extensions (lowercase, with dot).
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif", ".heic"}
)

#: Default thumbnail size (width, height).
THUMBNAIL_SIZE: tuple[int, int] = (200, 200)

#: Images larger than this are re-encoded before upload.
MAX_UPLOAD_BYTES: int = 2 * 1024 * 1024  # 2 MB

#: JPEG quality levels tried, in order, before falling back to downscaling.
_QUALITY_STEPS: tuple[int, ...] = (85, 70, 55)

#: Factor applied to both dimensions on each downscale pass.
_SCALE_STEP: float = 0.75

#: Never downscale below this on the shorter edge.
_MIN_DIMENSION: int = 640


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


@dataclass(frozen=True)
class PreparedImage:
    """An image ready to be uploaded.

    ``filename``, ``mime_type``, ``width`` and ``height`` always describe
    :attr:`data`, which may be a re-encoded copy rather than the file on disk.
    """

    data: bytes
    filename: str
    mime_type: str
    width: int
    height: int
    compressed: bool


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buffer.getvalue()


def compress_image(
    path: Path, max_bytes: int = MAX_UPLOAD_BYTES
) -> tuple[bytes, int, int]:
    """Re-encode *path* as JPEG so it fits within *max_bytes*.

    Quality is lowered first; if the smallest quality still exceeds
    *max_bytes* the image is downscaled repeatedly and the quality sweep is
    retried. Downscaling stops once the shorter edge would drop below
    :data:`_MIN_DIMENSION`, in which case the smallest encoding produced is
    returned even though it is still over the limit.

    Returns ``(jpeg_bytes, width, height)`` of the encoded image.
    """
    with Image.open(path) as opened:
        # Bake in EXIF orientation — re-encoding drops the EXIF tag.
        working = ImageOps.exif_transpose(opened).convert("RGB")

    while True:
        for quality in _QUALITY_STEPS:
            data = _encode_jpeg(working, quality)
            if len(data) <= max_bytes:
                return data, working.width, working.height

        new_size = (
            int(working.width * _SCALE_STEP),
            int(working.height * _SCALE_STEP),
        )
        if min(new_size) < _MIN_DIMENSION:
            return data, working.width, working.height  # best effort
        working = working.resize(new_size, Image.Resampling.LANCZOS)


def prepare_for_upload(
    path: Path, max_bytes: int = MAX_UPLOAD_BYTES
) -> PreparedImage:
    """Return the bytes and metadata to upload for *path*.

    Files at or below *max_bytes* are uploaded untouched. Larger files are
    compressed via :func:`compress_image`; the returned filename then carries
    a ``.jpg`` suffix to match the re-encoded content. If compression fails
    the original file is used unchanged.
    """
    width, height = get_image_dimensions(path)
    if path.stat().st_size <= max_bytes:
        return PreparedImage(
            data=path.read_bytes(),
            filename=path.name,
            mime_type=get_mime_type(path),
            width=width,
            height=height,
            compressed=False,
        )

    try:
        data, width, height = compress_image(path, max_bytes)
    except OSError:
        return PreparedImage(
            data=path.read_bytes(),
            filename=path.name,
            mime_type=get_mime_type(path),
            width=width,
            height=height,
            compressed=False,
        )

    return PreparedImage(
        data=data,
        filename=Path(path.name).with_suffix(".jpg").name,
        mime_type="image/jpeg",
        width=width,
        height=height,
        compressed=True,
    )
