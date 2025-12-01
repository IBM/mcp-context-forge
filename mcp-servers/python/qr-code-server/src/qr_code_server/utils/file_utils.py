import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_FILE_NAME = "qr"


def resolve_output_path(output_path: str, default_path: str, file_extension: str) -> str:
    """
    Resolve the final file path for saving output.

    - If output_path is a full file path with the correct extension, return it.
    - If output_path is a directory, use DEFAULT_FILE_NAME inside it.
    """

    raw_path = os.path.expanduser(output_path or default_path)
    if raw_path.endswith(os.sep):
        base = raw_path
        filename = ""
    else:
        base, filename = os.path.split(raw_path)
    try:
        os.makedirs(base, exist_ok=True)
    except OSError as e:
        logger.error("Error creating output folder '%s': %s", base, e)
        # img.save will handle the error

    _, ext = os.path.splitext(filename)
    # in case the user gave path + filename.ext with correct extension
    if ext.lstrip(".").lower() == file_extension.lower():
        return raw_path

    return os.path.join(base, f"{DEFAULT_FILE_NAME}.{file_extension}")
