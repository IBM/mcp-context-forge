# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/openapi_schema_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

OpenAPI Schema Generation Router.

This module provides a versioned REST API endpoint for generating MCP tool
input/output schemas from OpenAPI specifications. It mirrors the functionality
of the admin endpoint but without CSRF protection, making it suitable for
API consumers and integrations.
"""

# Standard
import logging
import urllib.parse

# Third-Party
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.openapi_service import fetch_and_extract_schemas
from mcpgateway.utils.orjson_response import ORJSONResponse

# Initialize router
router = APIRouter(prefix="/v1/tools", tags=["Tools"])
logger = logging.getLogger(__name__)


class GenerateSchemaRequest(BaseModel):
    """Request body for generating schemas from OpenAPI specification."""

    url: str = Field(..., description="The tool URL (e.g., http://localhost:8100/calculate)")
    request_type: str = Field("GET", description="HTTP method (GET, POST, etc.)")
    openapi_url: str = Field("", description="Direct OpenAPI spec URL (optional, auto-discovered if empty)")


@router.post("/generate-schemas-from-openapi")
@require_permission("tools.create", allow_admin_bypass=False)
async def generate_schemas_from_openapi(
    body: GenerateSchemaRequest = Body(...),
    _user=Depends(get_current_user_with_permissions),
) -> JSONResponse:
    """
    Generate input_schema and output_schema from OpenAPI specification.

    This endpoint is part of the versioned REST API and does not require
    admin UI access. It delegates to the same service logic as the admin
    endpoint but without CSRF protection.

    Args:
        body: Request body with url, request_type, and openapi_url
        _user: Authenticated user from RBAC dependency

    Returns:
        JSONResponse with generated schemas or error message.
    """
    # Security validation
    try:
        SecurityValidator.validate_url(body.url, "Tool URL")
    except ValueError as e:
        return ORJSONResponse(
            content={"message": str(e), "success": False},
            status_code=400,
        )

    # Parse URL to extract base and path
    parsed = urllib.parse.urlparse(body.url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    tool_path = parsed.path

    # Fetch and extract schemas
    try:
        input_schema, output_schema, spec_url = await fetch_and_extract_schemas(
            base_url=base_url,
            path=tool_path,
            method=body.request_type,
            openapi_url=body.openapi_url or "",
            timeout=10.0,
        )
    except ValueError as e:
        return ORJSONResponse(
            content={"message": f"Security validation failed: {str(e)}", "success": False},
            status_code=400,
        )
    except KeyError as e:
        return ORJSONResponse(
            content={"message": str(e), "success": False},
            status_code=404,
        )
    except httpx.HTTPStatusError as e:
        logger.warning("OpenAPI spec server returned HTTP %s", e.response.status_code, exc_info=True)
        return ORJSONResponse(
            content={"message": f"OpenAPI spec server returned HTTP {e.response.status_code}", "success": False},
            status_code=502,
        )
    except httpx.HTTPError:
        logger.warning("Failed to fetch OpenAPI spec", exc_info=True)
        return ORJSONResponse(
            content={"message": "Failed to fetch OpenAPI spec from the provided URL", "success": False},
            status_code=502,
        )
    except Exception:
        logger.error("Error fetching OpenAPI spec", exc_info=True)
        return ORJSONResponse(
            content={"message": "An unexpected error occurred while processing the OpenAPI spec", "success": False},
            status_code=500,
        )

    return ORJSONResponse(
        content={
            "message": "Schemas generated successfully from OpenAPI spec",
            "success": True,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "spec_url": spec_url,
        },
        status_code=200,
    )
