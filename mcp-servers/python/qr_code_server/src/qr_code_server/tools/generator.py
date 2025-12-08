import base64
import logging
import os
import zipfile
from io import BytesIO

from pydantic import BaseModel, field_validator
from qrcode.image.pil import PilImage

from qr_code_server.config import config
from qr_code_server.utils.file_utils import resolve_output_path
from qr_code_server.utils.image_utils import ImageAscii, create_qr_image, index_image_generator

logger = logging.getLogger(__name__)

DEFAULT_ZIP_FILE_NAME = "qr.zip"


class QRGenerationRequest(BaseModel):
    data: str
    format: str = "png"
    size: int = config.qr_generation.default_size
    border: int = config.qr_generation.default_border
    error_correction: str = config.qr_generation.default_error_correction
    fill_color: str = "black"
    back_color: str = "white"
    save_path: str | None = None
    return_base64: bool = False

    @field_validator("data")
    @classmethod
    def validate_data_lenght(cls, v: str) -> str:
        v = v.strip()
        if len(v) > config.qr_generation.max_data_length:
            raise ValueError("Data length exceeds maximum allowed")
        return v


class BatchQRGenerationRequest(BaseModel):
    data_list: list[str]  # List of data to encode
    format: str = "png"
    size: int = config.qr_generation.default_size
    naming_pattern: str = "qr_{index}"
    output_directory: str = config.output.default_directory
    zip_output: bool = True

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in config.qr_generation.supported_formats:
            raise ValueError("Unsupported format. Supported formats: png, svg, ascii")
        return v

    @field_validator("data_list")
    @classmethod
    def validate_batch_size(cls, v: list[str]) -> list[str]:
        """Validate batch size does not exceed configured limit."""
        max_size = config.output.max_batch_size
        max_data_length = config.qr_generation.max_data_length
        for data in v:
            if len(data.strip()) > max_data_length:
                raise ValueError(f"Data length exceeds maximum allowed of {max_data_length}")
        if len(v) > max_size:
            raise ValueError(f"Batch size {len(v)} exceeds limit {max_size}")
        if len(v) == 0:
            raise ValueError("data_list cannot be empty")
        return v


def create_qr_code(request: QRGenerationRequest):

    img = create_qr_image(
        data=request.data,
        format=request.format,
        error_correction=request.error_correction,
        size=request.size,
        border=request.border,
        fill_color=request.fill_color,
        back_color=request.back_color
    )

    if request.return_base64:
        try:
            if isinstance(img, ImageAscii):
                img_base64 = base64.b64encode(img.to_string().encode()).decode()
            else:
                buffer = BytesIO()
                img.save(buffer)
                img_base64 = base64.b64encode(buffer.getvalue()).decode()
            logger.info("Base64 QR code created successfully: format=%s", request.format)
            return {
                "success": True,
                "output_format": request.format,
                "image_base64": img_base64,
                "message": "QR code generated as base64 image",
            }
        except Exception as e:
            logger.error(
                "Failed to encode QR to base64: format=%s ec=%s error=%s",
                request.format,
                request.error_correction,
                e
            )
            return {"success": False, "error": str(e)}

    try:
        save_path = resolve_output_path(
            output_path=request.save_path or config.output.default_directory,
            file_extension=request.format
        )
    except Exception as e:
        # propagate as structured result so callers/tests can handle it
        logger.error("Error resolving output path: %s", e)
        return {"success": False, "error": str(e)}

    try:
        img.save(save_path)
        return {
            "success": True,
            "output_format": request.format,
            "message": f"QR code image saved at {save_path}",
        }
    except Exception as e:
        logger.error(
            "Failed to save QR code image: path=%s format=%s error=%s",
            save_path,
            request.format,
            e
        )
        return {"success": False, "error": str(e)}


def create_batch_qr_codes(request: BatchQRGenerationRequest):

    try:
        os.makedirs(request.output_directory, exist_ok=True)
    except OSError as e:
        logger.error("Failed to create output directory %s: %s", request.output_directory, e)
        return {"success": False, "error": str(e)}

    if request.zip_output:
        zip_file_path = os.path.join(request.output_directory, DEFAULT_ZIP_FILE_NAME)
        with zipfile.ZipFile(zip_file_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for index, img in index_image_generator(
                data=request.data_list,
                format=request.format,
                size=request.size,
            ):
                filename = f"{request.naming_pattern.format(index=index)}.{request.format}"
                logger.info("Adding image index=%d filename=%s to zip", index, filename)
                # yield acii as string and pil as bytes
                if hasattr(img, "to_string"):
                    img = img.to_string()
                elif isinstance(img, PilImage):
                    img = img.tobytes()
                try:
                    zf.writestr(filename, img)
                except Exception as e:
                    logger.error(
                        "Failed to add image to zip: index=%d filename=%s error=%s",
                        index,
                        filename, e
                    )
                    return {"success": False, "error": str(e)}
        return {
            "success": True,
            "message": f"QR code images saved in zip archive at {zip_file_path}",
        }

    else:
        for index, img in index_image_generator(
            data=request.data_list,
            format=request.format,
            size=request.size,
        ):
            filename = f"{request.naming_pattern.format(index=index)}.{request.format}"
            file_path = os.path.join(request.output_directory, filename)
            logger.info("Saving image index=%d to %s", index, file_path)
            try:
                img.save(file_path)
            except Exception as e:
                logger.error("Failed to save image: index=%d path=%s error=%s", index, file_path, e)
                return {"success": False, "error": str(e)}
        return {
            "success": True,
            "message": f"QR code images saved at {request.output_directory}",
        }
