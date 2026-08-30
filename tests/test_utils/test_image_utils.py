"""Tests for skyvas_sync.utils.image_utils."""

from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from skyvas_sync.utils.image_utils import (
    IMAGE_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    THUMBNAIL_SIZE,
    compress_image,
    create_thumbnail,
    get_image_dimensions,
    get_mime_type,
    is_image,
    prepare_for_upload,
)


class TestIsImage:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("photo.jpg", True),
            ("photo.JPEG", True),
            ("photo.png", True),
            ("photo.webp", True),
            ("photo.bmp", True),
            ("photo.gif", True),
            ("photo.tiff", True),
            ("photo.tif", True),
            ("photo.heic", True),
            ("document.pdf", False),
            ("readme.txt", False),
            ("video.mp4", False),
            ("noext", False),
        ],
    )
    def test_extension_detection(self, name: str, expected: bool):
        assert is_image(Path(name)) is expected


class TestGetImageDimensions:
    def test_returns_correct_size(self, tmp_path: Path):
        img = Image.new("RGB", (640, 480))
        path = tmp_path / "test.jpg"
        img.save(path)
        w, h = get_image_dimensions(path)
        assert w == 640
        assert h == 480

    def test_different_sizes(self, tmp_path: Path):
        img = Image.new("RGB", (1920, 1080))
        path = tmp_path / "test.png"
        img.save(path)
        assert get_image_dimensions(path) == (1920, 1080)

    def test_invalid_file_raises(self, tmp_path: Path):
        path = tmp_path / "bad.jpg"
        path.write_text("not an image")
        with pytest.raises(Exception):
            get_image_dimensions(path)

    def test_nonexistent_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            get_image_dimensions(tmp_path / "missing.jpg")


class TestCreateThumbnail:
    def test_default_size(self, tmp_path: Path):
        img = Image.new("RGB", (800, 600))
        path = tmp_path / "test.jpg"
        img.save(path)
        thumb = create_thumbnail(path)
        assert thumb.width <= THUMBNAIL_SIZE[0]
        assert thumb.height <= THUMBNAIL_SIZE[1]
        assert thumb.mode == "RGB"

    def test_custom_size(self, tmp_path: Path):
        img = Image.new("RGB", (800, 600))
        path = tmp_path / "test.jpg"
        img.save(path)
        thumb = create_thumbnail(path, size=(100, 100))
        assert thumb.width <= 100
        assert thumb.height <= 100

    def test_small_image_not_upscaled(self, tmp_path: Path):
        img = Image.new("RGB", (50, 30))
        path = tmp_path / "small.jpg"
        img.save(path)
        thumb = create_thumbnail(path)
        assert thumb.width == 50
        assert thumb.height == 30

    def test_preserves_aspect_ratio(self, tmp_path: Path):
        img = Image.new("RGB", (400, 200))
        path = tmp_path / "wide.jpg"
        img.save(path)
        thumb = create_thumbnail(path, size=(100, 100))
        assert thumb.width == 100
        assert thumb.height == 50

    def test_rgba_converted_to_rgb(self, tmp_path: Path):
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
        path = tmp_path / "alpha.png"
        img.save(path)
        thumb = create_thumbnail(path)
        assert thumb.mode == "RGB"

    def test_returns_copy(self, tmp_path: Path):
        img = Image.new("RGB", (100, 100))
        path = tmp_path / "test.jpg"
        img.save(path)
        thumb = create_thumbnail(path)
        # Should be usable after function returns (copy, not lazy)
        assert thumb.tobytes() is not None


class TestGetMimeType:
    @pytest.mark.parametrize(
        "name,expected_mime",
        [
            ("photo.jpg", "image/jpeg"),
            ("photo.jpeg", "image/jpeg"),
            ("photo.png", "image/png"),
            ("photo.webp", "image/webp"),
            ("photo.bmp", "image/bmp"),
            ("photo.gif", "image/gif"),
            ("photo.tiff", "image/tiff"),
            ("photo.tif", "image/tiff"),
            ("photo.heic", "image/heic"),
        ],
    )
    def test_known_types(self, name: str, expected_mime: str):
        assert get_mime_type(Path(name)) == expected_mime

    def test_unknown_extension(self):
        assert get_mime_type(Path("file.xyz")) == "application/octet-stream"

    def test_case_insensitive(self):
        assert get_mime_type(Path("PHOTO.JPG")) == "image/jpeg"
        assert get_mime_type(Path("photo.PNG")) == "image/png"


class TestImageExtensions:
    def test_is_frozenset(self):
        assert isinstance(IMAGE_EXTENSIONS, frozenset)

    def test_contains_common_formats(self):
        assert ".jpg" in IMAGE_EXTENSIONS
        assert ".png" in IMAGE_EXTENSIONS
        assert ".jpeg" in IMAGE_EXTENSIONS


def _make_large_image(path: Path, size: tuple[int, int] = (2400, 1800)) -> Path:
    """Write an image that is well over MAX_UPLOAD_BYTES on disk."""
    # Random pixels defeat compression, guaranteeing a large file.
    noise = os.urandom(size[0] * size[1] * 3)
    Image.frombytes("RGB", size, noise).save(path, quality=100)
    return path


class TestCompressImage:
    def test_fits_within_limit(self, tmp_path: Path):
        path = _make_large_image(tmp_path / "big.jpg")
        assert path.stat().st_size > MAX_UPLOAD_BYTES

        data, width, height = compress_image(path)

        assert len(data) <= MAX_UPLOAD_BYTES
        assert (width, height) == Image.open(io.BytesIO(data)).size

    def test_respects_custom_limit(self, tmp_path: Path):
        path = _make_large_image(tmp_path / "big.jpg")
        data, _, _ = compress_image(path, max_bytes=500 * 1024)
        assert len(data) <= 500 * 1024

    def test_output_is_jpeg(self, tmp_path: Path):
        path = _make_large_image(tmp_path / "big.png")
        data, _, _ = compress_image(path)
        assert Image.open(io.BytesIO(data)).format == "JPEG"

    def test_downscales_when_quality_is_not_enough(self, tmp_path: Path):
        path = _make_large_image(tmp_path / "big.jpg")
        _, width, height = compress_image(path, max_bytes=200 * 1024)
        assert (width, height) < (2400, 1800)

    def test_stops_downscaling_at_min_dimension(self, tmp_path: Path):
        # An unreachably small limit — best effort is returned instead of
        # shrinking forever.
        path = _make_large_image(tmp_path / "big.jpg")
        _, width, height = compress_image(path, max_bytes=1)
        assert min(width, height) >= 640 * 0.75


class TestPrepareForUpload:
    def test_small_image_is_untouched(self, tmp_path: Path):
        path = tmp_path / "small.png"
        Image.new("RGB", (640, 480)).save(path)

        prepared = prepare_for_upload(path)

        assert prepared.compressed is False
        assert prepared.data == path.read_bytes()
        assert prepared.filename == "small.png"
        assert prepared.mime_type == "image/png"
        assert (prepared.width, prepared.height) == (640, 480)

    def test_image_at_limit_is_untouched(self, tmp_path: Path):
        path = tmp_path / "exact.jpg"
        Image.new("RGB", (100, 100)).save(path)
        assert path.stat().st_size <= MAX_UPLOAD_BYTES

        prepared = prepare_for_upload(path, max_bytes=path.stat().st_size)

        assert prepared.compressed is False

    def test_large_image_is_compressed(self, tmp_path: Path):
        path = _make_large_image(tmp_path / "big.jpg")

        prepared = prepare_for_upload(path)

        assert prepared.compressed is True
        assert len(prepared.data) <= MAX_UPLOAD_BYTES
        assert len(prepared.data) < path.stat().st_size
        assert prepared.mime_type == "image/jpeg"
        assert (prepared.width, prepared.height) == Image.open(
            io.BytesIO(prepared.data)
        ).size

    def test_compressed_filename_gets_jpg_suffix(self, tmp_path: Path):
        path = _make_large_image(tmp_path / "big.png")
        assert prepare_for_upload(path).filename == "big.jpg"

    def test_falls_back_to_original_when_compression_fails(self, tmp_path: Path):
        path = _make_large_image(tmp_path / "big.jpg")

        with patch(
            "skyvas_sync.utils.image_utils.compress_image",
            side_effect=OSError("boom"),
        ):
            prepared = prepare_for_upload(path)

        assert prepared.compressed is False
        assert prepared.data == path.read_bytes()
        assert prepared.filename == "big.jpg"
