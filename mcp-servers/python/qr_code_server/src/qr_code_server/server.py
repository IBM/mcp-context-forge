import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from qr_code_server.config import config
from qr_code_server.tools.decoder import QRCodeDecodeResult, QRDecodingRequest, qr_decode
from qr_code_server.tools.generator import (
    BatchQRCodeResult,
    BatchQRGenerationRequest,
    QRCodeResult,
    QRGenerationRequest,
    create_batch_qr_codes,
    create_qr_code,
)
from qr_code_server.tools.validator import QRValidationRequest, QRValidationResult, validate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("qr_code_server")


# Concurrency control
_request_semaphore = asyncio.Semaphore(config.performance.max_concurrent_requests)
_pending_requests = 0
_max_queue_size = config.performance.max_concurrent_requests * 3


# Initialize server
mcp = FastMCP(name="qr-code-server", version="0.1.0")


@asynccontextmanager
async def _acquire_request_slot(request_name: str):
    """Acquire a request slot with queue size checks."""
    global _pending_requests

    if _pending_requests >= _max_queue_size:
        logger.warning(f"Queue full ({_pending_requests}). Rejecting {request_name}")
        raise RuntimeError(f"Server overloaded. Max queue size ({_max_queue_size}) exceeded.")

    _pending_requests += 1
    try:
        async with _request_semaphore:
            yield
    finally:
        _pending_requests -= 1


@mcp.tool(description="Generate QR code")
async def generate_qr_code(
    data: str,
    format: str = "png",
    size: int = config.qr_generation.default_size,
    border: int = config.qr_generation.default_border,
    error_correction: str = config.qr_generation.default_error_correction,
    fill_color: str = "black",
    back_color: str = "white",
    save_path: str | None = config.output.default_directory,
    return_base64: bool = False,
) -> QRCodeResult:
    try:
        async with _acquire_request_slot("generate_qr_code"):
            request = QRGenerationRequest(
                data=data,
                format=format,
                size=size,
                border=border,
                error_correction=error_correction,
                fill_color=fill_color,
                back_color=back_color,
                save_path=save_path,
                return_base64=return_base64,
            )
            return create_qr_code(request)
    except RuntimeError as e:
        return QRCodeResult(
            success=False,
            error=str(e)
        )
    except Exception as e:
        logger.error(f"generate_qr_code error: {e}")
        return QRCodeResult(
            success=False,
            error=str(e)
        )


@mcp.tool(description="Generate multiple QR codes")
async def generate_batch_qr_codes(
    data_list: list[str],
    format: str = "png",
    size: int = 10,
    naming_pattern: str = "qr_{index}",
    output_directory: str = "./qr_codes/",
    zip_output: bool = False,
) -> BatchQRCodeResult:
    try:
        async with _acquire_request_slot("generate_batch_qr_codes"):
            request = BatchQRGenerationRequest(
                data_list=data_list,
                format=format,
                size=size,
                naming_pattern=naming_pattern,
                output_directory=output_directory,
                zip_output=zip_output,
            )
            return create_batch_qr_codes(request)
    except RuntimeError as e:
        return BatchQRCodeResult(
            success=False,
            error=str(e)
        )
    except Exception as e:
        logger.error(f"generate_batch_qr_codes error: {e}")
        return BatchQRCodeResult(
            success=False,
            error=str(e)
        )


@mcp.tool(description="Decode QR code from image file")
async def decode_qr_code(
    image_data: str,
    image_format: str = "auto",
    multiple_codes: bool = False,
    return_positions: bool = False,
    preprocessing: bool = True,
) -> QRCodeDecodeResult:
    try:
        async with _acquire_request_slot("generate_batch_qr_codes"):
            request = QRDecodingRequest(
                image_data=image_data,
                image_format=image_format,
                multiple_codes=multiple_codes,
                return_positions=return_positions,
                preprocessing=preprocessing,
            )
            return qr_decode(request)
    except RuntimeError as e:
        return QRCodeDecodeResult(
            success=False,
            error=str(e)
        )
    except Exception as e:
        logger.error(f"Decode QR code data error: {e}")
        return QRCodeDecodeResult(
            success=False,
            error=str(e)
        )


@mcp.tool(description="Validate and analyze QR code data before generation")
async def validate_qr_data(
    data: str,
    target_version: int | None = None,  # QR code version (1-40),
    error_correction: str = "M",
    check_capacity: bool = True,
    suggest_optimization: bool = True,
) -> QRValidationResult:
    try:
        async with _acquire_request_slot("generate_batch_qr_codes"):
            request = QRValidationRequest(
                data=data,
                target_version=target_version,
                error_correction=error_correction,
                check_capacity=check_capacity,
                suggest_optimization=suggest_optimization,
            )
            return validate(request)
    except RuntimeError as e:
        return QRValidationResult(
            valid=False,
            error=str(e)
        )
    except Exception as e:
        logger.error(f"Validate QR code data error: {e}")
        return QRValidationResult(
            valid=False,
            error=str(e)
        )


def main():
    """Main entry point for the FastMCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="QR Code FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9001, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting QR Code FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting QR Code FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
