
import base64
from io import BytesIO
import os
import cv2
import numpy as np
import qrcode
from qrcode.image.pil import PilImage
from qrcode.image.svg import SvgImage
from qrcode.image.base import BaseImage
from collections.abc import Generator
from PIL import Image
import numpy as np


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
    """Generator that yields indexed QR code images.
    """
    for index, item in enumerate(data):
        img = create_qr_image(
            data=item,
            format=format,
            error_correction=error_correction,
            size=size,
            border=border,
            fill_color=fill_color,
            back_color=back_color
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
    """Create a QR code image.
    """

    ec_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }

    factory_map = {
        "png": PilImage,
        "svg": SvgImage,
        "ascii": ImageAscii
    }

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


def load_image(image_data: str):
    """Load an image from a file path and convert to OpenCV format."""

    if os.path.isfile(image_data):
        try:
            img = Image.open(image_data)
        except Exception as e:
            raise LoadImageError(f"Failed to open image file: {image_data}") from e

    else:
        try:
            img_bytes = base64.b64decode(image_data.strip())
            img = Image.open(BytesIO(img_bytes))
        except Exception as e:
            raise LoadImageError("Invalid base64 image data") from e

    if getattr(img, "is_animated", False):
        img.seek(0)

    return np.array(img.convert("L"))
