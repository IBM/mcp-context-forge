# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/vault_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Vault OAuth Router for ContextForge.

This module provides a simplified OAuth 2.0 Authorization Code flow endpoint:
- GET /vault/authorize/{server_id} - Initiate OAuth flow using virtual server ID

This endpoint redirects to the standard /oauth/callback endpoint which handles
token storage based on the OAUTH_TOKEN_BACKEND environment variable (database or vault).

The /vault/authorize endpoint allows clients to authorize using only their virtual
server ID, without needing to know internal gateway details.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.common.validators import SecurityValidator
from mcpgateway.db import Gateway, Server, Tool, get_db, server_tool_association
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.token_storage_service import TokenStorageService
from mcpgateway.utils.paths import resolve_root_path

logger = logging.getLogger(__name__)

vault_router = APIRouter(prefix="/vault", tags=["vault-oauth"])


def _resolve_oauth_gateway(
    server: Server,
    db: Session,
    preferred_url: str | None = None,
) -> Gateway | None:
    """Resolve OAuth-enabled gateway for a virtual server.

    Args:
        server: Virtual server record
        db: Database session
        preferred_url: Optional gateway URL to select (for multi-gateway servers)

    Returns:
        Gateway record or None if no OAuth gateways found
    """
    # Query all gateway_ids linked to this server via tools
    gateway_ids_result = db.execute(
        select(Tool.gateway_id)
        .join(server_tool_association, server_tool_association.c.tool_id == Tool.id)
        .where(server_tool_association.c.server_id == server.id)
        .where(Tool.gateway_id.isnot(None))
        .distinct()
    )
    gateway_ids = [row[0] for row in gateway_ids_result.all()]

    if not gateway_ids:
        return None

    # Filter to OAuth-enabled gateways
    gateways_result = db.execute(select(Gateway).where(Gateway.id.in_(gateway_ids)).where(Gateway.auth_type == "oauth"))
    gateways = list(gateways_result.scalars().all())

    if not gateways:
        return None

    # If preferred URL specified, find matching gateway
    if preferred_url:
        for gateway in gateways:
            if gateway.url == preferred_url:
                return gateway
        return None  # Preferred URL not found

    # Return first OAuth gateway
    return gateways[0]


@vault_router.get("/authorize/{server_id}")
async def vault_authorize(
    request: Request,
    server_id: str,
    gateway_url: Annotated[str | None, Query(max_length=500, description="Optional: select specific gateway URL for multi-gateway servers")] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_with_permissions),
) -> RedirectResponse:
    """
    Initiate OAuth flow using virtual server ID.

    This endpoint allows clients to authorize using only their virtual server URL,
    without needing to know gateway details. The service resolves:
    server_id → server_tool_association → tools.gateway_id → gateways

    After authorization, the OAuth provider redirects to /oauth/callback which
    handles token storage based on OAUTH_TOKEN_BACKEND (database or vault).

    Args:
        server_id: Virtual server ID (from client's MCP config URL)
        gateway_url: Optional gateway URL to select (for servers with multiple OAuth gateways)
        request: HTTP request object
        db: Database session
        current_user: Authenticated user (requires ContextForge Bearer token)

    Returns:
        RedirectResponse: 302 redirect to OAuth provider authorization URL

    Raises:
        HTTPException:
            - 404: Server not found
            - 400: No OAuth gateways configured for this server
            - 403: User lacks access to this server
    """
    try:
        # Lookup virtual server
        server = db.get(Server, server_id)
        if not server:
            logger.warning(
                "Vault OAuth authorize: server not found, server_id=%s, user=%s",
                SecurityValidator.sanitize_log_message(server_id),
                SecurityValidator.sanitize_log_message(current_user["email"]),
            )
            raise HTTPException(status_code=404, detail="Server not found")

        # Resolve OAuth-enabled gateway
        gateway = _resolve_oauth_gateway(server, db, gateway_url)
        if not gateway:
            logger.warning(
                "Vault OAuth authorize: no OAuth gateways for server, server_id=%s, user=%s",
                SecurityValidator.sanitize_log_message(server_id),
                SecurityValidator.sanitize_log_message(current_user["email"]),
            )
            raise HTTPException(
                status_code=400,
                detail="No OAuth gateways configured for this server. Please contact your administrator.",
            )

        if not gateway.oauth_config:
            logger.warning(
                "Vault OAuth authorize: gateway missing oauth_config, gateway_id=%s",
                SecurityValidator.sanitize_log_message(gateway.id),
            )
            raise HTTPException(
                status_code=400,
                detail="Gateway OAuth configuration is incomplete.",
            )

        # Build user context for token storage (uses already-resolved token_teams).
        # SECURITY: token_teams is the authoritative scope from resolve_session_teams()
        # or normalize_token_teams() — do NOT re-query database to avoid scope widening.
        # A missing "token_teams" key means Admin UI session → None (shared Vault path).
        token_teams_value = current_user.get("token_teams") if "token_teams" in current_user else None
        user_context = {
            "email": current_user["email"],
            "teams": token_teams_value,  # Keep as-is: None/[]/["team"] all have distinct meanings
            "is_admin": current_user.get("is_admin", False),
        }

        # Initialize OAuth manager with Vault-backed token storage
        oauth_manager = OAuthManager(token_storage=TokenStorageService(db, user_context))

        # Build authorization URL with user email embedded in state
        # Use the standard /oauth/callback endpoint (it already handles both Database and Vault backends)
        request_origin = f"{request.url.scheme}://{request.url.netloc}"
        root_path = resolve_root_path(request) if request else ""
        callback_url = f"{request_origin}{root_path}/oauth/callback"

        # Add callback URL to oauth_config for this flow
        oauth_config_with_callback = gateway.oauth_config.copy()
        oauth_config_with_callback["redirect_uri"] = callback_url

        result = await oauth_manager.initiate_authorization_code_flow(
            gateway_id=gateway.id,
            credentials=oauth_config_with_callback,
            app_user_email=current_user["email"],
        )
        auth_url = result["authorization_url"]

        logger.info(
            "Vault OAuth authorize: redirecting to IdP, gateway_id=%s, gateway_url=%s, user=%s",
            SecurityValidator.sanitize_log_message(gateway.id),
            SecurityValidator.sanitize_log_message(gateway.url),
            SecurityValidator.sanitize_log_message(current_user["email"]),
        )

        return RedirectResponse(url=auth_url, status_code=302)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Vault OAuth authorize failed: %s, server_id=%s, user=%s",
            str(e),
            SecurityValidator.sanitize_log_message(server_id),
            SecurityValidator.sanitize_log_message(current_user.get("email", "unknown")) if current_user else "unknown",
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate OAuth authorization. Please try again or contact your administrator.",
        )


# REMOVED: /vault/callback endpoint
# The standard /oauth/callback endpoint already handles both Database and Vault backends
# based on OAUTH_TOKEN_BACKEND environment variable. No need for a separate endpoint.
#
# The /vault/authorize endpoint now redirects to /oauth/callback instead.
