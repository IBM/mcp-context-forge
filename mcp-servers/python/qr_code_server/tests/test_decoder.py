# -*- coding: utf-8 -*-
import base64
import io
import logging
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from qr_code_server.tools.decoder import QRDecodingRequest, qr_decode

logger = logging.getLogger("qr_code_server")


def test_decode_qr_code_with_positions(tmp_path):
    """Test decoding a QR code with position data returned."""
    from qr_code_server.tools.generator import QRGenerationRequest, create_qr_code

    gen_path = tmp_path / "test_qr.png"
    gen_req = QRGenerationRequest(data="test_position", format="png", save_path=str(gen_path))
    gen_result = create_qr_code(gen_req)
    assert gen_result.success is True

    dec_req = QRDecodingRequest(
        image_data=str(gen_path), multiple_codes=False, return_positions=True, preprocessing=False
    )
    result = qr_decode(dec_req)

    assert result.success is True
    assert len(result.positions) > 0


def test_decode_invalid_image_file():
    """Test decoding with non-existent image file."""
    dec_req = QRDecodingRequest(image_data="/nonexistent/path/image.png")
    result = qr_decode(dec_req)

    assert result.success is False


def test_decode_invalid_base64():
    """Test decoding with invalid base64 data."""
    dec_req = QRDecodingRequest(image_data="not_valid_base64!!!")
    result = qr_decode(dec_req)

    assert result.success is False
    assert result.error == "Could not load image from file or as base64"


def test_decode_non_qr_image(tmp_path):
    """Test decoding an image without a QR code."""
    from PIL import Image

    # Create a simple image without QR code
    img = Image.new("RGB", (100, 100), color="red")
    img_path = Path(tmp_path / "no_qr.png")
    img.save(img_path)

    dec_req = QRDecodingRequest(image_data=str(img_path), multiple_codes=False)
    result = qr_decode(dec_req)

    assert result.success is False


def test_decode_multiple_qr_codes():
    """Test decoder decode multiple qr code"""
    image_file = "two_qr_test1_test2.png"
    image_path = Path(__file__).parent / "fixtures" / "test_images" / image_file
    dec_req = QRDecodingRequest(image_data=str(image_path), image_format="png", multiple_codes=True)
    result = qr_decode(dec_req)
    assert result.success is True
    assert isinstance(result.data, list)
    assert "test1" in result.data
    assert "test2" in result.data


def test_faild_decode_non_qr_image_multiple_codes(tmp_path):
    """Test fail decoding an image without a QR code multiple codes"""
    from PIL import Image

    # Create a simple image without QR code
    img = Image.new("RGB", (100, 100), color="red")
    img_path = Path(tmp_path / "no_qr.png")
    img.save(img_path)

    dec_req = QRDecodingRequest(
        image_data=str(img_path),
        multiple_codes=True,
    )
    with patch(
        "qr_code_server.tools.decoder.cv2.QRCodeDetector.detectAndDecodeMulti",
        side_effect=RuntimeError("decoding error"),
    ):
        result = qr_decode(dec_req)

    assert result.success is False
    assert "decoding error" in result.error


def test_decode_large_image():
    """Test that very large images are rejected to prevent DoS."""
    # Create a real large image (2000x2000 pixels = 4M pixels)
    large_array = np.zeros((2000, 2000), dtype=np.uint8)
    large_image = Image.fromarray(large_array)
    buffered = io.BytesIO()
    large_image.save(buffered, format="png")
    img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

    # Patch convert_to_bytes to return a tiny max size (smaller than the base64 encoded size)
    # This forces load_image to reject it as "too large"
    with patch("qr_code_server.tools.decoder.convert_to_bytes", return_value=1000):
        dec_req = QRDecodingRequest(image_data=img_base64)
        result = qr_decode(dec_req)

    assert result.success is False
    assert "too large" in result.error.lower()


def test_decode_with_preprocessing(tmp_path):
    """Test decoding with preprocessing enabled."""
    from qr_code_server.tools.generator import QRGenerationRequest, create_qr_code

    gen_path = tmp_path / "test_qr.png"
    gen_req = QRGenerationRequest(data="preprocess_test", format="png", save_path=str(gen_path))
    gen_result = create_qr_code(gen_req)
    assert gen_result.success is True

    dec_req = QRDecodingRequest(image_data=str(gen_path), preprocessing=True)
    result = qr_decode(dec_req)

    assert result.success is True
    assert result.data == "preprocess_test"


def test_decode_with_preprocessing_small_image(tmp_path):
    """Test decoding with preprocessing enabled small image"""
    from qr_code_server.tools.generator import QRGenerationRequest, create_qr_code

    gen_path = tmp_path / "test_qr.png"
    gen_req = QRGenerationRequest(
        data="small",
        size=1,
        format="png",
        save_path=str(gen_path),
    )
    gen_result = create_qr_code(gen_req)
    assert gen_result.success is True

    dec_req = QRDecodingRequest(image_data=str(gen_path), preprocessing=True)
    result = qr_decode(dec_req)

    assert result.success is True
    assert result.data == "small"


def test_decode_without_preprocessing(tmp_path):
    """Test decoding with preprocessing disabled."""
    from qr_code_server.tools.generator import QRGenerationRequest, create_qr_code

    gen_path = tmp_path / "test_qr.png"
    gen_req = QRGenerationRequest(data="no_preprocess_test", format="png", save_path=str(gen_path))
    gen_result = create_qr_code(gen_req)
    assert gen_result.success is True

    dec_req = QRDecodingRequest(image_data=str(gen_path), preprocessing=False)
    result = qr_decode(dec_req)

    assert result.success is True


def test_decode_load_image_error():
    """Test handling of LoadImageError from load_image."""
    from qr_code_server.utils.image_utils import LoadImageError

    with patch("qr_code_server.tools.decoder.load_image", side_effect=LoadImageError("Test error")):
        dec_req = QRDecodingRequest(image_data="dummy.png")
        result = qr_decode(dec_req)

        assert result.success is False
        assert "Test error" in result.error


@pytest.mark.parametrize("file_format", ["png", "jpg", "jpeg", "gif", "bmp", "tiff"])
def test_decode_different_formats(file_format):
    """Test decoder can decode multiple formats"""
    image_file = f"test_{file_format}.{file_format}"
    image_path = Path(__file__).parent / "fixtures" / "test_images" / image_file
    dec_req = QRDecodingRequest(image_data=str(image_path), image_format=file_format)
    result = qr_decode(dec_req)
    assert result.success is True
    assert "test1" in result.data
