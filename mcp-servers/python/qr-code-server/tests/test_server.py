import logging
import types
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

from qr_code_server.tools.generator import QRGenerationRequest, create_qr

logger = logging.getLogger("qr_code_server")


def test_qr_code_tool_schema_importable():
    # Basic import test ensures package structure is valid
    mod = __import__('qr_code_server.server', fromlist=['server'])
    assert isinstance(mod, types.ModuleType)


def test_create_qr_saves_file():
    """Test that create_qr saves a file correctly."""
    with TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "test"

        req = QRGenerationRequest(
            data="https://test.com",
            save_path=str(file_path),
        )
        result = create_qr(req)
        # Assert the file exists
        assert file_path.exists()
        assert file_path.is_file()
        assert result["success"] is True


# @pytest.mark.parametrize("file_format", ["png", "svg", "ascii"])
# def test_create_qr_saves_file_different_formats(file_format):
#     """Test that create_qr saves a files in different formats"""

#     output_format = "txt" if file_format == "ascii" else file_format

#     with TemporaryDirectory() as tmpdir:
#         file_path = Path(tmpdir) / "test"

#         req = QRGenerationRequest(
#             data="https://test.com",
#             format=file_format
#         )
#         result = create_qr(req)
#         # Assert the file exists
#         assert result["success"] is True
#         assert result["output_format"] is output_format



def test_create_qr_fail_to_save_file():
    """Test that create_qr handles file save errors gracefully."""

    req = QRGenerationRequest(
        data="https://test.com",
    )
    dummy_img = MagicMock()
    dummy_img.save.side_effect = IOError("disk error")
    with patch("qr_code_server.tools.generator.QRCode.make_image", return_value=dummy_img):
        with patch("qr_code_server.tools.generator.os.makedirs", return_value=""):
            result = create_qr(req)
    # Assert the file exists
    assert result["error"] == "disk error"
    assert result["success"] is False


def test_create_qr_save_base64():
    """Test that create_qr returns base64 encoded image."""
    req = QRGenerationRequest(
        data="https://test.com",
        return_base64=True
    )
    result = create_qr(req)
    # Assert the file exists
    assert result["success"] is True
    assert result["image_base64"] is not None


def test_return_base_64_fail_encoding():
    """Test that create_qr handles base64 encoding errors gracefully."""
    req = QRGenerationRequest(
        data="https://test.com",
        return_base64=True
    )
    dummy_img = MagicMock()
    dummy_img.save.side_effect = Exception("encoding error")
    with patch("qr_code_server.tools.generator.QRCode.make_image", return_value=dummy_img):
        result = create_qr(req)
    assert result["success"] is False


def test_create_qr_invalid_error_correction():
    """Test that create_qr handles invalid error correction level."""
    req = QRGenerationRequest(
        data="https://test.com",
        error_correction="Z"
    )
    try:
        create_qr(req)
    except KeyError as e:
        assert str(e) == "'Z'"
