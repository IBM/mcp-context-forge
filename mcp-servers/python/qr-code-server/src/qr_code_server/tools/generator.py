import base64
from io import BytesIO
import os
import logging
from typing import Optional
import qrcode
from qrcode import QRCode
from pydantic import BaseModel
import numpy as np

from qr_code_server.config import config

logger = logging.getLogger(__name__)


class QRGenerationRequest(BaseModel):
    data: str
    format: str = "png"
    size: int = 10
    border: int = 4
    error_correction: str = "M"
    fill_color: str = "black"
    back_color: str = "white"
    save_path: Optional[str] = None
    return_base64: bool = False


def create_qr(request: QRGenerationRequest):

    ec_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }

    qr = QRCode(
        version=None,
        error_correction=ec_map[request.error_correction],
        box_size=request.size,
        border=request.border,
    )

    qr.add_data(request.data)
    qr.make(fit=True)

    img = qr.make_image(fill_color=request.fill_color, back_color=request.back_color)

    if request.return_base64:
        try:
            buffer = BytesIO()
            img.save(buffer, format=request.format)
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

    if request.save_path:
        save_path = request.save_path
    else:
        save_path = os.path.join(config.output.default_directory, f"qr_code.{request.format}")

    # Ensure the output directory exists
    output_dir = os.path.dirname(save_path)
    os.makedirs(output_dir, exist_ok=True)

    if request.format == "ascii":
        arr = np.array(img)
        block = np.array(["  ", "██"])
        mapped = block[arr.astype(int)]
        ascii_qr = "\n".join("".join(row) for row in mapped)
        try:
            with open(save_path, "w", encoding="utf8") as f:
                f.write(ascii_qr)
        except Exception as e:
            logger.error(f"Error saving qr code image: {e}")
        return {"success": False, "error": str(e)}

    try:
        img.save(save_path, format=request.format)
        return {
            "success": True,
            "output_format": request.format,
            "message": f"QR code image saved at {save_path}",
        }
    except Exception as e:
        logger.error(f"Error saving qr code image: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    req = QRGenerationRequest(
        data="https://test.com",
        format="tiff"
    )
    result = create_qr(req)
    print(result)
