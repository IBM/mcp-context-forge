# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/credential_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Personal Credential Router for ContextForge.

This module provides REST endpoints for users to manage their personal
credentials (API keys, PATs, basic auth) for gateways where OAuth is not
supported or not sufficient for all endpoints.

Endpoints:
- POST   /credentials/{gateway_id} — store a personal credential
- GET    /credentials/{gateway_id} — get credential status for current user
- DELETE /credentials/{gateway_id} — revoke stored credential
- GET    /credentials              — list all stored credentials for current user
"""

# Standard
import logging
from typing import Any, Dict, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.db import Gateway, get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.schemas import EmailUserResponse
from mcpgateway.services.credential_storage_service import VALID_CREDENTIAL_TYPES, CredentialStorageService

logger = logging.getLogger(__name__)

credential_router = APIRouter(prefix="/credentials", tags=["credentials"])


# ---------------------------------------------------------------------------
# Helpers (reused patterns from oauth_router)
# ---------------------------------------------------------------------------


def _extract_user_email(current_user: EmailUserResponse | dict) -> str | None:
    """Extract requester email from typed or dict user contexts."""
    if hasattr(current_user, "email"):
        email = getattr(current_user, "email", None)
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
    if isinstance(current_user, dict):
        email = current_user.get("email") or current_user.get("user", {}).get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
    return None


def _extract_is_admin(current_user: EmailUserResponse | dict) -> bool:
    """Extract admin flag from typed or dict user contexts."""
    if hasattr(current_user, "is_admin"):
        return bool(getattr(current_user, "is_admin", False))
    if isinstance(current_user, dict):
        return bool(current_user.get("is_admin", False) or current_user.get("user", {}).get("is_admin", False))
    return False


async def _enforce_gateway_access(gateway_id: str, gateway: Gateway, current_user: EmailUserResponse, db: Session) -> None:
    """Enforce gateway visibility and ownership checks."""
    requester_email = _extract_user_email(current_user)
    if not requester_email:
        raise HTTPException(status_code=401, detail="User authentication required")

    requester_is_admin = _extract_is_admin(current_user)
    if requester_is_admin:
        return

    visibility = str(getattr(gateway, "visibility", "team") or "team").lower()
    gateway_owner = getattr(gateway, "owner_email", None)
    gateway_team_id = getattr(gateway, "team_id", None)

    if visibility == "public":
        return

    if visibility == "team":
        if not gateway_team_id:
            raise HTTPException(status_code=403, detail="You don't have access to this gateway")
        from mcpgateway.services.email_auth_service import EmailAuthService
        auth_service = EmailAuthService(db)
        user = await auth_service.get_user_by_email(requester_email)
        if not user or not user.is_team_member(gateway_team_id):
            raise HTTPException(status_code=403, detail="You don't have access to this gateway")
        return

    if visibility in {"private", "user"}:
        if gateway_owner and gateway_owner.strip().lower() == requester_email:
            return
        raise HTTPException(status_code=403, detail="You don't have access to this gateway")

    if gateway_owner and gateway_owner.strip().lower() == requester_email:
        return
    if gateway_team_id:
        from mcpgateway.services.email_auth_service import EmailAuthService
        auth_service = EmailAuthService(db)
        user = await auth_service.get_user_by_email(requester_email)
        if user and user.is_team_member(gateway_team_id):
            return

    raise HTTPException(status_code=403, detail="You don't have access to this gateway")


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class CredentialStoreRequest(BaseModel):
    """Request body for storing a personal credential."""

    credential_type: str = Field(
        ...,
        description=f"Type of credential. Must be one of: {', '.join(sorted(VALID_CREDENTIAL_TYPES))}",
    )
    credential_value: str = Field(..., min_length=1, description="The credential value (API key, token, or username:password)")
    label: Optional[str] = Field(None, max_length=255, description="Optional user-friendly label for the credential")


class CredentialInfoResponse(BaseModel):
    """Response for credential info queries."""

    gateway_id: str
    gateway_name: Optional[str] = None
    app_user_email: str
    credential_type: str
    label: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@credential_router.post("/{gateway_id}")
async def store_credential(
    gateway_id: str,
    body: CredentialStoreRequest,
    current_user: EmailUserResponse = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Store a personal credential for a gateway.

    Allows authenticated users to store a personal API key, bearer token, or basic auth
    credential for a specific gateway. This credential is used instead of the gateway's
    shared credentials when the user invokes tools on this gateway.

    The credential is encrypted at rest using the platform encryption service.
    """
    requester_email = _extract_user_email(current_user)
    if not requester_email:
        raise HTTPException(status_code=401, detail="User authentication required")

    gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()
    if not gateway:
        raise HTTPException(status_code=404, detail="Gateway not found")

    await _enforce_gateway_access(gateway_id, gateway, current_user, db)

    if body.credential_type not in VALID_CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid credential_type '{body.credential_type}'. Must be one of: {', '.join(sorted(VALID_CREDENTIAL_TYPES))}",
        )

    try:
        credential_service = CredentialStorageService(db)
        await credential_service.store_credential(
            gateway_id=gateway_id,
            app_user_email=requester_email,
            credential_type=body.credential_type,
            credential_value=body.credential_value,
            label=body.label,
        )

        logger.info(
            f"Credential stored via API for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, "
            f"user {SecurityValidator.sanitize_log_message(requester_email)}"
        )

        return {
            "success": True,
            "gateway_id": gateway_id,
            "app_user_email": requester_email,
            "credential_type": body.credential_type,
            "label": body.label,
            "message": "Personal credential stored successfully",
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            f"Failed to store credential for gateway {SecurityValidator.sanitize_log_message(gateway_id)}: {e}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to store credential: {str(e)}")


@credential_router.get("/{gateway_id}")
async def get_credential_status(
    gateway_id: str,
    current_user: EmailUserResponse = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get credential status for the authenticated user on a gateway.

    Returns metadata about the stored credential without exposing the secret value.
    """
    requester_email = _extract_user_email(current_user)
    if not requester_email:
        raise HTTPException(status_code=401, detail="User authentication required")

    gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()
    if not gateway:
        raise HTTPException(status_code=404, detail="Gateway not found")

    await _enforce_gateway_access(gateway_id, gateway, current_user, db)

    try:
        credential_service = CredentialStorageService(db)
        info = await credential_service.get_credential_info(gateway_id, requester_email)

        if not info:
            return {"has_credential": False, "gateway_id": gateway_id, "message": "No personal credential stored for this gateway"}

        return {
            "has_credential": True,
            "gateway_id": gateway_id,
            **info,
        }

    except Exception as e:
        logger.error(
            f"Failed to get credential status for gateway {SecurityValidator.sanitize_log_message(gateway_id)}: {e}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to get credential status: {str(e)}")


@credential_router.delete("/{gateway_id}")
async def revoke_credential(
    gateway_id: str,
    current_user: EmailUserResponse = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Revoke stored personal credential for the authenticated user on a gateway."""
    requester_email = _extract_user_email(current_user)
    if not requester_email:
        raise HTTPException(status_code=401, detail="User authentication required")

    gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()
    if not gateway:
        raise HTTPException(status_code=404, detail="Gateway not found")

    await _enforce_gateway_access(gateway_id, gateway, current_user, db)

    try:
        credential_service = CredentialStorageService(db)
        revoked = await credential_service.revoke_credential(gateway_id, requester_email)

        if revoked:
            logger.info(
                f"Credential revoked via API for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, "
                f"user {SecurityValidator.sanitize_log_message(requester_email)}"
            )
            return {"success": True, "gateway_id": gateway_id, "message": "Personal credential revoked successfully"}

        return {"success": False, "gateway_id": gateway_id, "message": "No personal credential found for this gateway"}

    except Exception as e:
        logger.error(
            f"Failed to revoke credential for gateway {SecurityValidator.sanitize_log_message(gateway_id)}: {e}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to revoke credential: {str(e)}")


@credential_router.get("")
async def list_credentials(
    current_user: EmailUserResponse = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """List all gateways where the authenticated user has stored personal credentials.

    Returns metadata about each credential without exposing secret values.
    """
    requester_email = _extract_user_email(current_user)
    if not requester_email:
        raise HTTPException(status_code=401, detail="User authentication required")

    try:
        credential_service = CredentialStorageService(db)
        credentials = await credential_service.list_user_credentials(requester_email)

        # Enrich with gateway names
        for cred in credentials:
            gateway = db.execute(select(Gateway).where(Gateway.id == cred["gateway_id"])).scalar_one_or_none()
            cred["gateway_name"] = gateway.name if gateway else cred["gateway_id"]

        return {
            "credentials": credentials,
            "count": len(credentials),
        }

    except Exception as e:
        logger.error(f"Failed to list credentials: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list credentials: {str(e)}")
