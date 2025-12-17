import logging
from typing import Any

import cv2
from pydantic import BaseModel, field_validator

from qr_code_server.config import config
from qr_code_server.utils.file_utils import convert_to_bytes
from qr_code_server.utils.image_utils import LoadImageError, load_image

logger = logging.getLogger(__name__)


class QRDecodingError(Exception):
    pass


class QRDecodingRequest(BaseModel):
    image_data: str  # base64 image data or file path
    image_format: str = "auto"  # auto, png, jpg, jpeg, gif, bmp, tiff
    multiple_codes: bool = False  # Detect multiple QR codes
    return_positions: bool = False  # Return QR code positions
    preprocessing: bool = True  # Apply preprocessing for better detection

    @field_validator("image_format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ["auto"] + config.decoding.supported_image_formats:
            raise ValueError(f"Unsupported format '{v}'.")
        return v


def qr_decode(request: QRDecodingRequest) -> dict[str, Any]:
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
        return {"success": False, "error": str(e)}

    detector = cv2.QRCodeDetector()

    try:
        retval, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
    except Exception as e:
        logger.error("Failed to decode QR code, %s", str(e))
        return {"success": False, "error": str(e)}

    if not retval or not any(decoded_info):
        logger.warning("Failed to retrieve qrcode data")
        return {"success": False, "error": "Failed to decode QR code."}

    data = []
    positions = []

    for info, p in zip(decoded_info, points, strict=True):
        if info:
            data.append(info)
            positions.append(p)

    if not data:
        logger.warning("Failed to retrieve qrcode data")
        return {"success": False, "error": "No QR codes decoded."}

    response = {"success": True}

    if request.multiple_codes:
        response["data"] = data
        if request.return_positions:
            response["positions"] = positions
    else:
        response["data"] = data[0]
        if request.return_positions:
            response["positions"] = positions[0]

    return response
