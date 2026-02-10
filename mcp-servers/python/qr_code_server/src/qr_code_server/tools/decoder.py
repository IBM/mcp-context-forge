# -*- coding: utf-8 -*-
import logging
from typing import Any, Literal

import cv2
from pydantic import BaseModel, field_validator

from qr_code_server.config import config
from qr_code_server.utils.file_utils import convert_to_bytes
from qr_code_server.utils.image_utils import LoadImageError, load_image

logger = logging.getLogger(__name__)


class QRDecodingError(Exception):
    pass


class QRCodeDecodeResult(BaseModel):
    success: bool
    data: str | list[str] | None = None
    positions: list[Any] | None = None
    error: str | None = None


class QRDecodingRequest(BaseModel):
    image_data: str  # base64 image data or file path
    image_format: Literal["auto", "png", "jpg", "jpeg", "gif", "bmp", "tiff"] = "auto"
    multiple_codes: bool = False  # Detect multiple QR codes
    return_positions: bool = False  # Return QR code positions
    preprocessing: bool = True  # Apply preprocessing for better detection

    @field_validator("image_format")
    @classmethod
    def validate_image_format(cls, v: str) -> str:
        """Validate image format against configured supported formats."""
        v = v.lower().strip()
        if v != "auto" and v not in config.decoding.supported_image_formats:
            supported = ", ".join(config.decoding.supported_image_formats)
            raise ValueError(f"Unsupported image format '{v}'. Supported: {supported}")
        return v


def qr_decode(request: QRDecodingRequest) -> QRCodeDecodeResult:
    """
    Decode QR codes from an image. Handles single/multi code detection, image preprocessing,
    and robust OpenCV signature differences.

    Returns a consistent dict with success status, decoded data, and optional positions.
    """
    max_image_size = convert_to_bytes(config.decoding.max_image_size)

    try:
        img = load_image(request.image_data, max_image_size, request.preprocessing)
        logger.info("Image loaded correctly. Image size %s", img.shape)
    except LoadImageError as e:
        logger.error(f"Error loading image: {e}")
        return QRCodeDecodeResult(success=False, error=str(e))

    detector = cv2.QRCodeDetector()

    try:
        retval, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
    except Exception as e:
        logger.error("Failed to decode QR code, %s", str(e))
        return QRCodeDecodeResult(success=False, error=str(e))

    if not retval or not any(decoded_info):
        logger.warning("Failed to retrieve qrcode data")
        return QRCodeDecodeResult(success=False, error="Failed to decode QR code.")

    data = []
    positions = []

    for info, p in zip(decoded_info, points, strict=True):
        if info:
            data.append(info)
            # Convert NumPy array to list for JSON serialization
            positions.append(p.tolist() if hasattr(p, "tolist") else p)

    if not data:
        logger.warning("Failed to retrieve qrcode data")
        return QRCodeDecodeResult(success=False, error="No QR codes decoded.")

    if request.multiple_codes:
        return QRCodeDecodeResult(
            success=True,
            data=data,
            positions=positions if request.return_positions else None,
        )
    else:
        return QRCodeDecodeResult(
            success=True,
            data=data[0],
            positions=positions[0] if request.return_positions else None,
        )
