import base64
import logging
from io import BytesIO

import qrcode
from pydantic import BaseModel
from qrcode import QRCode
from qrcode.image.pil import PilImage
from qrcode.image.svg import SvgImage

from qr_code_server.config import config
from qr_code_server.utils.file_utils import resolve_output_path
from qr_code_server.utils.image_utils import ImageAscii

logger = logging.getLogger(__name__)


class QRGenerationRequest(BaseModel):
    data: str
    format: str = "png"
    size: int = 10
    border: int = 4
    error_correction: str = "M"
    fill_color: str = "black"
    back_color: str = "white"
    save_path: str | None = None
    return_base64: bool = False


def create_qr_code(request: QRGenerationRequest):

    ec_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }

    request.format = "txt" if request.format == "ascii" else request.format

    factory_map = {
        "png": PilImage,
        "svg": SvgImage,
        "txt": ImageAscii
    }

    qr = QRCode(
        version=None,
        error_correction=ec_map[request.error_correction],
        box_size=request.size,
        border=request.border,
    )

    qr.add_data(request.data)
    qr.make(fit=True)

    factory = factory_map.get(request.format, PilImage)

    img = qr.make_image(
        image_factory=factory,
        fill_color=request.fill_color,
        back_color=request.back_color,
    )

    if request.return_base64:
        try:
            buffer = BytesIO()
            img.save(buffer)
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            return {
                "success": True,
                "output_format": request.format,
                "image_base64": img_base64,
                "message": "QR code generated as base64 image",
            }
        except Exception as e:
            logger.error(f"Error encoding qr code to base 64: {e}")
            return {"success": False, "error": str(e)}

    save_path = resolve_output_path(
        output_path=request.save_path,
        default_path=config.output.default_directory,
        file_extension=request.format
    )

    try:
        img.save(save_path)
        return {
            "success": True,
            "output_format": request.format,
            "message": f"QR code image saved at {save_path}",
        }
    except Exception as e:
        logger.error(f"Error saving qr code image: {e}")
        return {"success": False, "error": str(e)}
