# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/sso_user_provisioning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

JSON automation API for administrator-driven passwordless SSO provisioning.
"""

# Standard
from typing import Any

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
import orjson
from pydantic import ValidationError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_context import get_user_email
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_db, require_permission
from mcpgateway.schemas import AdminCreateSSOUserRequest, EmailUserResponse
from mcpgateway.services.email_auth_service import EmailAuthService, EmailValidationError, UserExistsError
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.sso_provider_ids import SSOProviderValidationError

logger = LoggingService().get_logger(__name__)
router = APIRouter(prefix="/admin/users", tags=["SSO User Provisioning"])


@router.post(
    "/sso",
    response_model=EmailUserResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": AdminCreateSSOUserRequest.model_json_schema()}}}},
)
@require_permission("admin.user_management")  # type: ignore[untyped-decorator]  # Existing RBAC decorator lacks a typed signature.
async def create_sso_user(request: Request, current_user_ctx: dict[str, Any] = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> EmailUserResponse:
    """Provision a passwordless user using an enabled, configured SSO provider.

    Args:
        request: JSON request, parsed after authentication and authorization.
        current_user_ctx: Authenticated caller context.
        db: Request-scoped database session.

    Returns:
        The created user's public details.

    Raises:
        HTTPException: Unsupported media type, malformed JSON, password input,
            invalid provider/email, duplicate user, or unexpected service failure.
        RequestValidationError: JSON does not match the request schema.
    """
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")
    try:
        payload = orjson.loads(await request.body())
    except orjson.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body") from exc
    if isinstance(payload, dict) and "password" in payload:
        raise HTTPException(status_code=400, detail="password not allowed for SSO users")
    try:
        user_request = AdminCreateSSOUserRequest.model_validate(payload)
    except ValidationError as exc:
        errors = [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
        raise RequestValidationError(errors) from exc

    actor_email = get_user_email(current_user_ctx)
    try:
        user = await EmailAuthService(db).create_sso_user(**user_request.model_dump(), granted_by=actor_email)
    except (EmailValidationError, SSOProviderValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UserExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("SSO user provisioning failed")
        raise HTTPException(status_code=500, detail="User creation failed") from exc

    logger.info("Admin %s provisioned SSO user %s", SecurityValidator.sanitize_log_message(actor_email), SecurityValidator.sanitize_log_message(user.email))
    return EmailUserResponse.from_email_user(user)
