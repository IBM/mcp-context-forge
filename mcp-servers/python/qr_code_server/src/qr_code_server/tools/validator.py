from typing import Optional
from pydantic import BaseModel, field_validator


class QRValidationRequest(BaseModel):
    data: str
    target_version: Optional[int] = None  # QR code version (1-40)
    error_correction: str = "M"
    check_capacity: bool = True
    suggest_optimization: bool = True

    @field_validator("target_version")
    @classmethod
    def validate_version(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 1 or v > 40):
            raise ValueError("target_version must be between 1 and 40")
        return v

    @field_validator("error_correction")
    @classmethod
    def validate_error_correction(cls, v: str) -> str:
        v = v.upper().strip()
        if v not in ["L", "M", "Q", "H"]:
            raise ValueError("error_correction must be one of L, M, Q, H")
        return v
