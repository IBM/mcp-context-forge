import base64
import logging
import os
from collections.abc import Generator
from io import BytesIO

import cv2
import numpy as np
import qrcode
from PIL import Image
from qrcode.image.base import BaseImage
from qrcode.image.pil import PilImage
from qrcode.image.svg import SvgImage

logger = logging.getLogger(__name__)


class SaveImageError(Exception):
    pass


class LoadImageError(Exception):
    pass


class ImageAscii(BaseImage):

    def __init__(self, border, width, box_size, qrcode_modules=None, **kwargs):
        self.border = border
        self.width = width
        self.box_size = box_size
        self.image = qrcode_modules

    def to_string(self) -> str:
        img_arr = np.array(self.image)
        block = np.array(["  ", "██"], dtype=str)
        mapped = block[img_arr.astype(int)]
        return "\n".join("".join(row) for row in mapped)

    def save(self, target):
        ascii_qr = self.to_string()
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(ascii_qr)
        except Exception as e:
            raise SaveImageError(f"Error saving ASCII image: {e}") from e


def index_image_generator(
    data: list[str],
    format: str = "png",
    size: int = 10,
    border: int = 4,
    error_correction: str = "M",
    fill_color: str = "black",
    back_color: str = "white",
) -> Generator[tuple[int, BaseImage], None, None]:
    """Generator that yields indexed QR code images."""
    for index, item in enumerate(data):
        img = create_qr_image(
            data=item,
            format=format,
            error_correction=error_correction,
            size=size,
            border=border,
            fill_color=fill_color,
            back_color=back_color,
        )
        yield index, img


def create_qr_image(
    data: str,
    format: str = "png",
    size: int = 10,
    border: int = 4,
    error_correction: str = "M",
    fill_color: str = "black",
    back_color: str = "white",
) -> BaseImage:
    """Create a QR code image."""

    ec_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }

    factory_map = {"png": PilImage, "svg": SvgImage, "ascii": ImageAscii}

    qr = qrcode.QRCode(
        version=None,
        error_correction=ec_map[error_correction],
        box_size=size,
        border=border,
    )

    qr.add_data(data)
    qr.make(fit=True)

    factory = factory_map.get(format, PilImage)

    return qr.make_image(
        image_factory=factory,
        fill_color=fill_color,
        back_color=back_color,
    )


def load_image(image_data: str, max_image_size: int, preprocessing: bool) -> np.ndarray:
    """Load an image from a file path and convert to OpenCV format."""

    if os.path.isfile(image_data):
        if os.path.getsize(image_data) > max_image_size:
            raise LoadImageError(f"Image file too large: {image_data}")
        try:
            img = Image.open(image_data)
        except Exception as e:
            raise LoadImageError(f"Failed to open image file: {image_data}") from e

    else:
        b64_str = image_data.strip()
        padding = b64_str.count("=")
        estimated_size = len(b64_str) * 3 // 4 - padding
        # approximate size validation before decoding base64
        if estimated_size > max_image_size:
            raise LoadImageError("Base64 image data too large")
        try:
            img_bytes = base64.b64decode(image_data.strip())
            img = Image.open(BytesIO(img_bytes))
        except Exception as e:
            raise LoadImageError("Could not load image from file or as base64") from e

    if getattr(img, "is_animated", False):
        img.seek(0)

    if preprocessing:
        img = img_preprocessing(img)

    else:
        img = np.array(img.convert("L"))
        logger.info("Converted image to grayscale")

    # last size validation before exiting
    if img.nbytes > max_image_size:
        raise LoadImageError(f"Image too large in memory: {img.nbytes} bytes")

    return img


def img_preprocessing(img: Image.Image) -> np.ndarray:
    """
    Preprocess a grayscale or single-channel image for QR decoding.

    Steps:
    1. If the image is smaller than 100 pixels in any dimension, upscale it to 100x100.
    2. Apply Gaussian blur with a 5x5 kernel to reduce noise.
    3. Apply Otsu's thresholding to binarize the image.

    Args:
        img (Image.Image): Input image as a PIL Image.

    Returns:
        np.ndarray: Preprocessed binary image as a NumPy array.
    """

    logger.info("Starting image preprocessing...")
    if min(img.size) < 100:
        logger.info("Image size %s too small, resizing to 100x100", img.size)
        img = img.resize((100, 100), Image.Resampling.LANCZOS)

    img = np.array(img.convert("L"))
    logger.info("Converted image to grayscale")

    blur = cv2.GaussianBlur(img, (5, 5), 0)
    _, img = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    logger.info("Applied Gaussian blur with kernel size (5,5) and Otsu Treshold")

    return img
