import base64
from io import BytesIO

import qrcode
from pydantic import BaseModel


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


def create_qr(req: QRGenerationRequest):

    ec_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }

    qr = qrcode.QRCode(
        version=None,
        error_correction=ec_map[req.error_correction],
        box_size=req.size,
        border=req.border,
    )

    qr.add_data(req.data)
    qr.make(fit=True)

    img = qr.make_image(fill_color=req.fill_color, back_color=req.back_color)

    if req.save_path:
        img.save(req.save_path, format=req.format.upper())

    if req.return_base64:
        buffer = BytesIO()
        img.save(buffer, format=req.format.upper())
        return base64.b64encode(buffer.getvalue()).decode()

    return img


if __name__ == "__main__":

    req = QRGenerationRequest(
        data="https://github.com/IBM/mcp-context-forge",
        format="png",
        size=10,
        border=4,
        error_correction="M",
        fill_color="black",
        back_color="white",
        save_path=None,
        return_base64=False,
    )

    img = create_qr(req)

    img.show()
