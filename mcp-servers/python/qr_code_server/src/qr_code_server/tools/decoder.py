
from pydantic import BaseModel


class QRDecodingRequest(BaseModel):
    image_data: str  # base64 image data or file path
    image_format: str = "auto"  # auto, png, jpg, gif
    multiple_codes: bool = False  # Detect multiple QR codes
    return_positions: bool = False  # Return QR code positions
    preprocessing: bool = True  # Image preprocessing for better detection
