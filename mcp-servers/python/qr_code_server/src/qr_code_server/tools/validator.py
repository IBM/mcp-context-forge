from typing import Optional
from pydantic import BaseModel


class QRValidationRequest(BaseModel):
    data: str
    target_version: Optional[int] = None  # QR code version (1-40)
    error_correction: str = "M"
    check_capacity: bool = True
    suggest_optimization: bool = True
