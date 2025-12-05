import logging
import base64
from logging import config
from typing import Any

from pydantic import BaseModel, field_validator
import cv2
import numpy as np

from qr_code_server.utils.file_utils import convert_to_bytes
from qr_code_server.utils.image_utils import LoadImageError, load_image

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = ["png", "jpg", "jpeg", "gif", "bmp", "tiff"]


class QRDecodingRequest(BaseModel):
    image_data: str  # base64 image data or file path
    image_format: str = "auto"  # auto, png, jpg, jpeg, gif, bmp, tiff
    multiple_codes: bool = False  # Detect multiple QR codes
    return_positions: bool = False  # Return QR code positions
    preprocessing: bool = True  # Image preprocessing for better detection

    @field_validator("image_format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ["auto"] + config.decoder.supported_formats:
            raise ValueError(f"Unsupported format '{v}'. Supported: {SUPPORTED_FORMATS}")
        return v
