# -*- coding: utf-8 -*-
import logging

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

# based on https://www.thonky.com/qr-code-tutorial/error-correction-table
DATA_CODEWORDS = {
    1: {"L": 19, "M": 16, "Q": 13, "H": 9},
    2: {"L": 34, "M": 28, "Q": 22, "H": 16},
    3: {"L": 55, "M": 44, "Q": 34, "H": 26},
    4: {"L": 80, "M": 64, "Q": 48, "H": 36},
    5: {"L": 108, "M": 86, "Q": 62, "H": 46},
    6: {"L": 136, "M": 108, "Q": 76, "H": 60},
    7: {"L": 156, "M": 124, "Q": 88, "H": 66},
    8: {"L": 194, "M": 154, "Q": 110, "H": 86},
    9: {"L": 232, "M": 182, "Q": 132, "H": 100},
    10: {"L": 274, "M": 216, "Q": 154, "H": 122},
    11: {"L": 324, "M": 254, "Q": 180, "H": 140},
    12: {"L": 370, "M": 290, "Q": 206, "H": 158},
    13: {"L": 428, "M": 334, "Q": 244, "H": 180},
    14: {"L": 461, "M": 365, "Q": 261, "H": 197},
    15: {"L": 523, "M": 415, "Q": 295, "H": 223},
    16: {"L": 589, "M": 453, "Q": 325, "H": 253},
    17: {"L": 647, "M": 507, "Q": 367, "H": 283},
    18: {"L": 721, "M": 563, "Q": 397, "H": 313},
    19: {"L": 795, "M": 627, "Q": 445, "H": 341},
    20: {"L": 861, "M": 669, "Q": 485, "H": 385},
    21: {"L": 932, "M": 714, "Q": 512, "H": 406},
    22: {"L": 1006, "M": 782, "Q": 568, "H": 442},
    23: {"L": 1094, "M": 860, "Q": 614, "H": 464},
    24: {"L": 1174, "M": 914, "Q": 664, "H": 514},
    25: {"L": 1276, "M": 1000, "Q": 718, "H": 538},
    26: {"L": 1370, "M": 1062, "Q": 754, "H": 596},
    27: {"L": 1468, "M": 1128, "Q": 808, "H": 628},
    28: {"L": 1531, "M": 1193, "Q": 871, "H": 661},
    29: {"L": 1631, "M": 1267, "Q": 911, "H": 701},
    30: {"L": 1735, "M": 1373, "Q": 985, "H": 745},
    31: {"L": 1843, "M": 1455, "Q": 1033, "H": 793},
    32: {"L": 1955, "M": 1541, "Q": 1115, "H": 845},
    33: {"L": 2071, "M": 1631, "Q": 1171, "H": 901},
    34: {"L": 2191, "M": 1725, "Q": 1231, "H": 961},
    35: {"L": 2306, "M": 1812, "Q": 1286, "H": 986},
    36: {"L": 2434, "M": 1914, "Q": 1354, "H": 1054},
    37: {"L": 2566, "M": 1992, "Q": 1426, "H": 1096},
    38: {"L": 2702, "M": 2102, "Q": 1502, "H": 1142},
    39: {"L": 2812, "M": 2216, "Q": 1582, "H": 1222},
    40: {"L": 2956, "M": 2334, "Q": 1666, "H": 1276},
}


class QRValidationResult(BaseModel):
    valid: bool
    fits: bool | None = None
    error: str | None = None
    suggested_version: int | None = None


class QRValidationRequest(BaseModel):
    data: str
    target_version: int | None = None  # QR code version (1-40)
    error_correction: str = "M"
    check_capacity: bool = True
    suggest_optimization: bool = True

    @field_validator("target_version")
    @classmethod
    def validate_version(cls, v: int | None) -> int | None:
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


def encoded_bits(text: str, version: int) -> int:
    """
    Estimate the total number of bits required to encode `text` in QR byte mode
    for a given QR version.

    This uses:
    - Byte mode indicator: 4 bits
    - Character count indicator: 8 bits for versions 1-9, else 16 bits
    - Data bits: 8 x number of bytes (UTF-8)
    - Terminator: up to 4 bits

    Parameters
    ----------
    text : str
        The text to encode.
    version : int
        QR code version (1-40).

    Returns
    -------
    int
        Estimated number of bits required.
    """
    raw = text.encode("utf-8")
    mode_bits = 4  # Byte mode indicator
    cc_bits = 8 if version <= 9 else 16  # Character count indicator
    data_bits = len(raw) * 8  # Actual data
    terminator_bits = 4  # Terminator (up to 4 bits)
    return mode_bits + cc_bits + data_bits + terminator_bits


def smallest_fitting_version(text: str, ecc: str) -> int | None:
    """
    Find the smallest QR version (1-40) that can hold the text under the given
    error-correction level.

    Parameters
    ----------
    text : str
        Text to encode.
    ecc : str
        Error correction level: 'L', 'M', 'Q', 'H'.

    Returns
    -------
    int | None
        The smallest version that fits the data, or None if none fit.
    """
    for v in range(1, 41):
        capacity = DATA_CODEWORDS[v][ecc] * 8
        if encoded_bits(text, v) <= capacity:
            return v
    return None


def validate(request: QRValidationRequest) -> QRValidationResult:
    """
    Validate whether the given request's text fits into the specified QR version
    and error-correction level. Optionally returns suggestions for the smallest
    fitting QR version.
    """
    text = request.data
    version = request.target_version
    ecc = request.error_correction.upper()

    result = QRValidationResult(valid=True)

    if request.check_capacity:
        if version is None:
            best = smallest_fitting_version(text, ecc)
            result.fits = best is not None
            if best is None:
                result.valid = False
                result.error = "Data too large for any QR version"
                logger.warning(
                    "Validation failed: data too large (len=%d) for any QR version, ecc=%s",
                    len(text),
                    ecc,
                )
            else:
                logger.info(
                    "Validation passed: smallest fitting version=%d for data length=%d ecc=%s",
                    best,
                    len(text),
                    ecc,
                )
        else:
            capacity_bits = DATA_CODEWORDS[version][ecc] * 8
            needed_bits = encoded_bits(text, version)
            result.fits = needed_bits <= capacity_bits
            if not result.fits:
                result.valid = False
                result.error = "Data does not fit in specified version"
                logger.info(
                    "Data did not fit: version=%d ecc=%s needed_bits=%d capacity_bits=%d",
                    version,
                    ecc,
                    needed_bits,
                    capacity_bits,
                )

    if request.suggest_optimization:
        suggested = smallest_fitting_version(text, ecc)
        result.suggested_version = suggested
        logger.info(
            "Suggested optimal version=%s for data length=%d ecc=%s",
            suggested,
            len(text),
            ecc,
        )

    return result
