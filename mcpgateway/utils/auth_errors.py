# -*- coding: utf-8 -*-
"""Shared auth error helpers.

Centralises ErrorResponse and raise_auth_error so both mcpgateway.auth and
mcpgateway.routers.app can import from a leaf module, breaking the circular
dependency that would arise if auth.py imported from routers/.
"""

from typing import NoReturn, Optional

from fastapi import HTTPException
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Structured error response payload."""

    error: str
    message: str
    correlation_id: Optional[str] = None


def raise_auth_error(
    error: str,
    message: str,
    status_code: int = 401,
    correlation_id: Optional[str] = None,
) -> NoReturn:
    """Raise HTTPException with a structured ErrorResponse detail.

    Args:
        error: Machine-readable error code (e.g. 'not_authenticated', 'csrf_mismatch')
        message: Human-readable description
        status_code: HTTP status code (default 401)
        correlation_id: Optional tracing identifier

    Raises:
        HTTPException: Always raised; never returns.
    """
    raise HTTPException(
        status_code=status_code,
        detail=ErrorResponse(
            error=error,
            message=message,
            correlation_id=correlation_id,
        ).model_dump(),
    )
