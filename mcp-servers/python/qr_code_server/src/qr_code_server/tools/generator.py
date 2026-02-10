# -*- coding: utf-8 -*-
import base64
import logging
import os
import zipfile
from io import BytesIO
from typing import Literal

from pydantic import BaseModel, field_validator
from qrcode.image.pil import PilImage

from qr_code_server.config import config
from qr_code_server.utils.file_utils import resolve_output_path
from qr_code_server.utils.image_utils import ImageAscii, create_qr_image, index_image_generator

logger = logging.getLogger(__name__)

DEFAULT_ZIP_FILE_NAME = "qr.zip"


class QRCodeResult(BaseModel):
    success: bool
    output_format: Literal["png", "svg", "ascii"] | None = None
    file_path: str | None = None
    image_base64: str | None = None
    message: str | None = None
    error: str | None = None


class BatchQRCodeResult(BaseModel):
    success: bool
    message: str | None = None
    error: str | None = None
    zip_file_path: str | None = None
    output_directory: str | None = None


class QRGenerationRequest(BaseModel):
    data: str
    format: Literal["png", "svg", "ascii"] = "png"
    size: int = config.qr_generation.default_size
    border: int = config.qr_generation.default_border
    error_correction: Literal["L", "M", "Q", "H"] = config.qr_generation.default_error_correction
    fill_color: str = "black"
    back_color: str = "white"
    save_path: str | None = None
    return_base64: bool = False

    @field_validator("data")
    @classmethod
    def validate_data_length(cls, v: str) -> str:
        """Validate data length without modifying content (whitespace is preserved)."""
        if len(v) > config.qr_generation.max_data_length:
            raise ValueError("Data length exceeds maximum allowed")
        return v

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        """Validate format against configured supported formats."""
        v = v.lower().strip()
        if v not in config.qr_generation.supported_formats:
            raise ValueError("Unsupported format. Supported formats: png, svg, ascii")
        return v

    @field_validator("border")
    @classmethod
    def validate_border_size(cls, v: int) -> int:
        """Cap border between 0 and 100 to avoid invalid values and memory issues."""
        return max(0, min(v, 100))


class BatchQRGenerationRequest(BaseModel):
    data_list: list[str]  # List of data to encode
    format: Literal["png", "svg", "ascii"] = "png"
    size: int = config.qr_generation.default_size
    border: int = config.qr_generation.default_border
    error_correction: Literal["L", "M", "Q", "H"] = config.qr_generation.default_error_correction
    naming_pattern: str = "qr_{index}"
    output_directory: str = config.output.default_directory
    zip_output: bool = config.output.enable_zip_export

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in config.qr_generation.supported_formats:
            raise ValueError("Unsupported format. Supported formats: png, svg, ascii")
        return v

    @field_validator("border")
    @classmethod
    def validate_border_size(cls, v: int) -> int:
        """Cap border between 0 and 100 to avoid invalid values and memory issues."""
        return max(0, min(v, 100))

    @field_validator("naming_pattern")
    @classmethod
    def validate_naming_pattern(cls, v: str) -> str:
        """Validate naming_pattern to prevent path traversal attacks."""
        # Reject patterns containing path separators or parent directory references
        if ".." in v or "/" in v or "\\" in v or os.sep in v:
            raise ValueError("naming_pattern cannot contain path separators or '..'")
        # Reject absolute paths
        if os.path.isabs(v):
            raise ValueError("naming_pattern cannot be an absolute path")
        return v

    @field_validator("data_list")
    @classmethod
    def validate_batch_size(cls, v: list[str]) -> list[str]:
        """Validate batch size and individual data lengths (whitespace preserved)."""
        max_size = config.output.max_batch_size
        max_data_length = config.qr_generation.max_data_length
        for data in v:
            if len(data) > max_data_length:
                raise ValueError(f"Data length exceeds maximum allowed of {max_data_length}")
        if len(v) > max_size:
            raise ValueError(f"Batch size {len(v)} exceeds limit {max_size}")
        if len(v) == 0:
            raise ValueError("data_list cannot be empty")
        return v


def create_qr_code(request: QRGenerationRequest) -> QRCodeResult:
    img = create_qr_image(
        data=request.data,
        format=request.format,
        error_correction=request.error_correction,
        size=request.size,
        border=request.border,
        fill_color=request.fill_color,
        back_color=request.back_color,
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
            return QRCodeResult(
                success=True,
                output_format=request.format,
                image_base64=img_base64,
                message="QR code generated as base64 image",
            )

        except Exception as e:
            logger.error(
                "Failed to encode QR to base64: format=%s ec=%s error=%s",
                request.format,
                request.error_correction,
                e,
            )
            return QRCodeResult(success=False, error=str(e))

    try:
        save_path = resolve_output_path(
            output_path=request.save_path or config.output.default_directory,
            file_extension=request.format,
        )
    except Exception as e:
        # propagate as structured result so callers/tests can handle it
        logger.error("Error resolving output path: %s", e)
        return QRCodeResult(success=False, error=str(e))

    try:
        img.save(save_path)  # type: ignore[arg-type]
        return QRCodeResult(
            success=True,
            output_format=request.format,
            file_path=save_path,
            message=f"QR code image saved at {save_path}",
        )
    except Exception as e:
        logger.error(
            "Failed to save QR code image: path=%s format=%s error=%s", save_path, request.format, e
        )
        return QRCodeResult(success=False, error=str(e))


def create_batch_qr_codes(request: BatchQRGenerationRequest) -> BatchQRCodeResult:
    try:
        os.makedirs(request.output_directory, exist_ok=True)
    except OSError as e:
        logger.error("Failed to create output directory %s: %s", request.output_directory, e)
        return BatchQRCodeResult(success=False, error=str(e))

    if request.zip_output:
        zip_file_path = os.path.join(request.output_directory, DEFAULT_ZIP_FILE_NAME)
        with zipfile.ZipFile(zip_file_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for index, img in index_image_generator(
                data=request.data_list,
                format=request.format,
                size=request.size,
                border=request.border,
                error_correction=request.error_correction,
            ):
                filename = f"{request.naming_pattern.format(index=index)}.{request.format}"
                logger.info("Adding image index=%d filename=%s to zip", index, filename)
                # yield acii as string and pil as bytes

                if hasattr(img, "to_string"):
                    img = img.to_string()
                elif isinstance(img, PilImage):
                    buffer = BytesIO()
                    img.save(buffer, format=request.format)
                    img = buffer.getvalue()
                else:
                    raise TypeError(f"Unsupported image type: {type(img)}")
                try:
                    zf.writestr(filename, img)  # type: ignore[arg-type]
                except Exception as e:
                    logger.error(
                        "Failed to add image to zip: index=%d filename=%s error=%s",
                        index,
                        filename,
                        e,
                    )
                    return BatchQRCodeResult(success=False, error=str(e))
        return BatchQRCodeResult(
            success=True,
            zip_file_path=zip_file_path,
            output_directory=request.output_directory,
            message=f"QR code images saved in zip archive at {zip_file_path}",
        )

    else:
        for index, img in index_image_generator(
            data=request.data_list,
            format=request.format,
            size=request.size,
            border=request.border,
            error_correction=request.error_correction,
        ):
            filename = f"{request.naming_pattern.format(index=index)}.{request.format}"
            file_path = os.path.join(request.output_directory, filename)
            logger.info("Saving image index=%d to %s", index, file_path)
            try:
                img.save(file_path)
            except Exception as e:
                logger.error("Failed to save image: index=%d path=%s error=%s", index, file_path, e)
                return BatchQRCodeResult(success=False, error=str(e))
        return BatchQRCodeResult(
            success=True,
            output_directory=request.output_directory,
            message=f"QR code images saved at {request.output_directory}",
        )
