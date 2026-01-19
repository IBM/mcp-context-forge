# -*- coding: utf-8 -*-
import base64
import types
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from qr_code_server.tools.generator import (
    DEFAULT_ZIP_FILE_NAME,
    BatchQRGenerationRequest,
    QRGenerationRequest,
    create_batch_qr_codes,
    create_qr_code,
)


def test_qr_code_tool_schema_importable():
    # Basic import test ensures package structure is valid
    mod = __import__("qr_code_server.server", fromlist=["server"])
    assert isinstance(mod, types.ModuleType)


@pytest.mark.parametrize("file_format", ["png", "svg", "ascii"])
def test_create_qr_saves_file_different_formats(tmp_path, file_format):
    """Test that create_qr saves a files in different formats"""

    file_path = tmp_path

    req = QRGenerationRequest(data="https://test.com", format=file_format, save_path=str(file_path))
    result = create_qr_code(req)
    assert result.success is True
    assert result.output_format == req.format


@pytest.mark.parametrize("file_format", ["png", "svg", "ascii"])
def test_create_qr_saves_file_different_formats_base_64(tmp_path, file_format):
    """Test that create_qr saves a files in different formats"""

    file_path = tmp_path

    req = QRGenerationRequest(
        data="https://test.com", format=file_format, return_base64=True, save_path=str(file_path)
    )

    result = create_qr_code(req)

    assert result.success is True
    assert result.output_format == file_format


def test_create_qr_fail_to_save_file(tmp_path):
    """Test that create_qr handles file save errors gracefully."""

    file_path = tmp_path
    req = QRGenerationRequest(data="https://test.com", save_path=str(file_path))
    dummy_img = MagicMock()
    dummy_img.save.side_effect = OSError("file error")
    with patch("qr_code_server.tools.generator.create_qr_image", return_value=dummy_img):
        result = create_qr_code(req)

    assert result.error == "file error"
    assert result.success is False


def test_create_qr_fails_to_create_ascii_image(tmp_path):
    """Test that create_qr handles ascii image creation errors gracefully."""
    file_path = tmp_path
    req = QRGenerationRequest(data="https://test.com", format="ascii", save_path=str(file_path))
    with patch("builtins.open", side_effect=OSError("file error")):
        result = create_qr_code(req)
    assert result.error == "Error saving ASCII image: file error"
    assert result.success is False


def test_create_qr_returns_valid_base64_png():
    """create_qr_code should return a valid base64-encoded PNG when requested."""
    req = QRGenerationRequest(
        data="https://test.com",
        return_base64=True,
    )
    result = create_qr_code(req)
    assert result.success is True
    assert isinstance(result.image_base64, str)

    # Validate it's real base64
    decoded = base64.b64decode(result.image_base64, validate=True)
    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")


def test_return_base_64_fail_encoding():
    """Test that create_qr handles base64 encoding errors gracefully."""
    req = QRGenerationRequest(data="https://test.com", return_base64=True)
    dummy_img = MagicMock()
    dummy_img.save.side_effect = Exception("encoding error")
    with patch("qr_code_server.tools.generator.create_qr_image", return_value=dummy_img):
        result = create_qr_code(req)
    assert result.success is False
    assert result.error == "encoding error"


def test_create_qr_invalid_error_correction():
    """Test that create_qr handles invalid error correction level."""
    try:
        QRGenerationRequest(data="https://test.com", error_correction="Z")
    except ValidationError as e:
        errors = e.errors()
        assert errors[0]["loc"] == ("error_correction",)
        assert errors[0]["type"] == "literal_error"
        assert "L" in errors[0]["msg"] and "H" in errors[0]["msg"]


def test_resolve_output_path_fail():
    """Test that create_qr handles resolve output path errors gracefully."""
    req = QRGenerationRequest(data="https://test.com", save_path="/invalid_path/qr_code.png")
    with patch(
        "qr_code_server.tools.generator.resolve_output_path", side_effect=Exception("path error")
    ):
        result = create_qr_code(req)
    assert result.success is False
    assert result.error == "path error"


# Batch gereration tests


def test_create_batch_qr_codes_creates_output_directory(tmp_path):
    """Test that create_batch_qr_codes creates the output directory if it doesn't exist."""
    output_dir = tmp_path / "new_folder"

    req = BatchQRGenerationRequest(data_list=["https://test.com"], output_directory=str(output_dir))
    result = create_batch_qr_codes(req)
    assert result.success is True
    assert output_dir.exists()
    assert output_dir.is_dir()


def test_create_batch_qr_codes_fail_create_output_directory(tmp_path):
    """Test that create_batch_qr_codes handles failure to create output directory."""
    output_dir = tmp_path / "new_folder"

    req = BatchQRGenerationRequest(data_list=["https://test.com"], output_directory=str(output_dir))
    from qr_code_server.tools.generator import create_batch_qr_codes

    with patch("os.makedirs", side_effect=OSError("disk error")):
        result = create_batch_qr_codes(req)

    assert result.success is False
    assert result.error == "disk error"


@pytest.mark.parametrize("file_format", ["png", "svg", "ascii"])
def test_create_batch_qr_codes_different_formats(file_format, tmp_path):
    """Test that create_batch_qr_codes creates files in different formats."""
    output_dir = tmp_path

    req = BatchQRGenerationRequest(
        data_list=["test1", "test2"],
        format=file_format,
        output_directory=str(output_dir),
        zip_output=False,
    )
    result = create_batch_qr_codes(req)
    assert result.success is True
    # Check that files are created
    for index in range(2):
        file_path = output_dir / f"qr_{index}.{file_format}"
        assert file_path.exists()
        assert file_path.is_file()


@pytest.mark.parametrize("file_format", ["png", "svg", "ascii"])
def test_create_batch_qr_codes_different_formats_zipped(file_format, tmp_path):
    """Test that create_batch_qr_codes creates zipped files in different formats."""
    output_dir = tmp_path

    req = BatchQRGenerationRequest(
        data_list=["test1", "test2"],
        format=file_format,
        output_directory=str(output_dir),
        zip_output=True,
    )
    result = create_batch_qr_codes(req)
    assert result.success is True
    # Check that zip file is created
    zip_file_path = output_dir / DEFAULT_ZIP_FILE_NAME
    assert zip_file_path.exists()
    assert zip_file_path.is_file()


def test_create_batch_qr_codes_fail_save_file(tmp_path):
    """Test that create_batch_qr_codes handles file save errors gracefully."""
    output_dir = tmp_path

    req = BatchQRGenerationRequest(
        data_list=["test1", "test2"],
        output_directory=str(output_dir),
        zip_output=False,
    )
    dummy_img = MagicMock()
    dummy_img.save.side_effect = OSError("file error")
    with patch("qr_code_server.utils.image_utils.create_qr_image", return_value=dummy_img):
        result = create_batch_qr_codes(req)
    assert result.error == "file error"
    assert result.success is False


def test_create_batch_qr_codes_fail_add_to_zip(tmp_path):
    """Test that create_batch_qr_codes handles zip file errors gracefully."""
    output_dir = tmp_path

    req = BatchQRGenerationRequest(
        data_list=["test1", "test2"], output_directory=str(output_dir), zip_output=True
    )
    dummy_img = MagicMock()
    with patch("qr_code_server.utils.image_utils.create_qr_image", return_value=dummy_img):
        with patch("zipfile.ZipFile.writestr", side_effect=OSError("zip error")):
            result = create_batch_qr_codes(req)
    assert result.error == "zip error"
    assert result.success is False


def test_batch_generator_unziped_valid_png_images(tmp_path):
    """Test that batch generator zipped folder contains valid png images"""
    import puremagic

    output_dir = tmp_path
    unziped_path = Path(tmp_path / "extracted")

    req = BatchQRGenerationRequest(
        data_list=["test1", "test2"], output_directory=str(output_dir), format="png"
    )
    _ = create_batch_qr_codes(req)
    with zipfile.ZipFile(Path(tmp_path / "qr.zip"), "r") as zip:
        zip.extractall(unziped_path)
    for index in range(2):
        file_path = unziped_path / f"qr_{index}.png"
        assert file_path.exists()
        assert file_path.is_file()
        # check if file is png image
        assert puremagic.from_file(file_path) == ".png"


# Path traversal security tests


@pytest.mark.parametrize(
    "bad_pattern",
    [
        "../escape_{index}",
        "..\\escape_{index}",
        "/absolute_{index}",
        "path/with/slash_{index}",
        "path\\with\\backslash_{index}",
    ],
)
def test_naming_pattern_rejects_path_traversal(tmp_path, bad_pattern):
    """Test that naming_pattern rejects path traversal attempts."""
    with pytest.raises(ValidationError) as exc_info:
        BatchQRGenerationRequest(
            data_list=["test"],
            output_directory=str(tmp_path),
            naming_pattern=bad_pattern,
        )
    assert "naming_pattern" in str(exc_info.value)


def test_naming_pattern_accepts_safe_patterns(tmp_path):
    """Test that naming_pattern accepts safe patterns."""
    safe_patterns = ["qr_{index}", "code-{index}", "image_{index}_v2", "{index}"]
    for pattern in safe_patterns:
        req = BatchQRGenerationRequest(
            data_list=["test"],
            output_directory=str(tmp_path),
            naming_pattern=pattern,
        )
        assert req.naming_pattern == pattern


def test_border_validation_clamps_negative_values():
    """Test that negative border values are clamped to 0."""
    req = QRGenerationRequest(data="test", border=-5)
    assert req.border == 0


def test_border_validation_clamps_large_values():
    """Test that large border values are clamped to 100."""
    req = QRGenerationRequest(data="test", border=500)
    assert req.border == 100
