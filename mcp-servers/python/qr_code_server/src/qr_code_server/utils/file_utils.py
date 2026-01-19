# -*- coding: utf-8 -*-
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_FILE_NAME = "qr"


def resolve_output_path(output_path: str, file_extension: str) -> str:
    """
    Return a resolved file path for saving output.

    - If output_path ends with os.sep, or is dir treat it as a directory.
    - If output_path includes a filename:
        - return it unchanged when it already has an extension.
        - otherwise append the given file_extension.
    - If no filename is provided, use DEFAULT_FILE_NAME.
    The function will attempt to create the target directory.
    file_extension should not include a leading dot.
    """

    filename = ""
    ext = ""
    if output_path == "":
        output_path = os.getcwd()

    # case 1: output_path is a folder
    if output_path.endswith(os.sep) or os.path.isdir(output_path):
        base = os.path.abspath(output_path)
    else:
        base, filename = os.path.split(output_path)
        _, ext = os.path.splitext(filename)

    base = base or os.getcwd()

    try:
        os.makedirs(base, exist_ok=True)
    except OSError as e:
        logger.error("Error creating output folder '%s': %s", base, e)
        # img.save will handle the error

    # case 2: output_path has a meaningful file extension matching target format
    if ext and ext.lstrip(".").lower() == file_extension.lower():
        return output_path
    # case 3: output_path has filename (with or without extension) - append target extension
    elif filename:
        return os.path.join(base, f"{filename.rstrip('.')}.{file_extension}")

    # case 4: output_path does not have filename
    return os.path.join(base, f"{DEFAULT_FILE_NAME}.{file_extension}")


def convert_to_bytes(size_str: str) -> int:
    """Convert a human-readable size string (e.g., '10MB', '500KB') to bytes."""

    unit_factors = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
    }

    size_str = size_str.strip().upper()

    if not size_str:
        raise ValueError("Size string cannot be empty")

    # Extract numbers and units
    numbers = [n for n in size_str if n.isdigit() or n == "."]
    units = "".join([u for u in size_str if not (u.isdigit() or u == "." or u.isspace())])

    if not numbers:
        raise ValueError(f"No numeric value found in size string: '{size_str}'")

    # Validate that the number comes first, then unit (no interleaving)
    if not size_str.startswith("".join(numbers)):
        raise ValueError(f"Invalid format for size string: '{size_str}'")

    if units not in unit_factors and units != "":
        raise ValueError(f"Unknown unit '{units}' in size string: '{size_str}'")

    size_value = float("".join(numbers))
    unit_factor = unit_factors.get(units, 1)  # default to bytes if no unit

    return int(size_value * unit_factor)
