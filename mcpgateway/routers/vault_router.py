# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/vault_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Vault OAuth Router for ContextForge.

This module provides OAuth 2.0 Authorization Code flow endpoints for the Vault backend:
- GET /vault/authorize/{server_id} - Initiate OAuth flow using virtual server ID
- GET /vault/callback - Handle OAuth callback and store tokens in Vault

These endpoints are only registered when OAUTH_TOKEN_BACKEND=vault.
They allow clients to authorize using only their virtual server URL, not gateway details.
"""

import logging
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.common.query_params import QueryErrorCode
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.db import Gateway, Server, Tool, get_db, server_tool_association
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.token_backends.base import normalize_resource_url
from mcpgateway.services.token_storage_service import TokenStorageService
from mcpgateway.utils.log_sanitizer import sanitize_for_log
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
    gateways_result = db.execute(
        select(Gateway)
        .where(Gateway.id.in_(gateway_ids))
        .where(Gateway.auth_type == "oauth")
    )
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
    server_id: str,
    gateway_url: Annotated[str | None, Query(max_length=500, description="Optional: select specific gateway URL for multi-gateway servers")] = None,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_with_permissions),
) -> RedirectResponse:
    """
    Initiate OAuth flow using virtual server ID.

    This endpoint allows clients to authorize using only their virtual server URL,
    without needing to know gateway details. The service resolves:
    server_id → server_tool_association → tools.gateway_id → gateways

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
        root_path = resolve_root_path(request) if request else ""
        callback_url = f"{root_path}/vault/callback"

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


@vault_router.get("/callback")
async def vault_callback(
    code: Annotated[str | None, Query(max_length=2048, description="Authorization code from OAuth provider")] = None,
    state: Annotated[str | None, Query(max_length=2048, description="State parameter for CSRF protection")] = None,
    error: QueryErrorCode = None,
    error_description: Annotated[str | None, Query(max_length=500, description="OAuth provider error description")] = None,
    request: Request = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """
    Handle OAuth callback and store tokens in Vault.

    This endpoint is called by the OAuth provider after user authorization.
    It exchanges the authorization code for tokens and stores them in Vault
    (not the database).

    Args:
        code: Authorization code from OAuth provider
        state: State parameter for CSRF protection
        error: OAuth provider error code (RFC 6749 Section 4.1.2.1)
        error_description: OAuth provider error description
        request: HTTP request object
        db: Database session

    Returns:
        HTMLResponse: Success or error page

    Note:
        This endpoint does NOT require authentication - the OAuth provider
        redirects here with code+state. State validation provides CSRF protection.
    """
    try:
        root_path = resolve_root_path(request) if request else ""
        safe_root_path = escape(str(root_path), quote=True)

        # Handle OAuth provider error
        if error:
            error_text = escape(error)
            description_text = escape(error_description or "OAuth provider returned an authorization error.")
            logger.warning(
                "Vault OAuth callback: provider error, error=%s, description=%s",
                sanitize_for_log(error),
                sanitize_for_log(error_description),
            )
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p><strong>Error:</strong> {error_text}</p>
                    <p><strong>Description:</strong> {description_text}</p>
                    <a href="{safe_root_path}/">Return to Home</a>
                </body>
                </html>
                """,
                status_code=400,
            )

        # Validate code parameter
        if not code:
            logger.warning("Vault OAuth callback: missing authorization code")
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p>Error: Missing authorization code in callback response.</p>
                    <a href="{safe_root_path}/">Return to Home</a>
                </body>
                </html>
                """,
                status_code=400,
            )

        # Validate state parameter
        def _invalid_state_response() -> HTMLResponse:
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p>Error: Invalid OAuth state parameter.</p>
                    <a href="{safe_root_path}/">Return to Home</a>
                </body>
                </html>
                """,
                status_code=400,
            )

        if not state:
            logger.warning("Vault OAuth callback: missing state parameter")
            return _invalid_state_response()

        # SECURITY: Extract gateway_id without consuming state (no TOCTOU risk - just for lookup)
        # complete_authorization_code_flow will atomically validate/consume state and return state_data
        temp_oauth_manager = OAuthManager(token_storage=None)

        # Extract gateway_id without consuming state
        gateway_id = await temp_oauth_manager.resolve_gateway_id_from_state(state, allow_legacy_fallback=False)
        if not gateway_id:
            logger.warning("Vault OAuth callback: invalid or unknown state token")
            return _invalid_state_response()

        # Get gateway configuration (before consuming state, to validate OAuth config exists)
        gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()
        if not gateway:
            logger.warning("Vault OAuth callback: gateway not found")
            return _invalid_state_response()

        # SECURITY FIX (TOCTOU): Complete OAuth code exchange WITHOUT token storage first
        # This atomically consumes state and returns state_data, eliminating the TOCTOU race
        no_storage_oauth_manager = OAuthManager(token_storage=None)

        # Use database OAuth credentials for the token exchange
        # NOTE: Vault-stored team-scoped OAuth credentials cannot be retrieved here without
        # peeking at state, which would introduce a TOCTOU race. For multi-team isolation,
        # use database OAuth config at callback time; team-scoped storage still applies.
        if not gateway.oauth_config:
            logger.warning("Vault OAuth callback: no OAuth config in database for gateway %s", gateway_id)
            return _invalid_state_response()

        oauth_config_with_resource = gateway.oauth_config.copy()

        # Ensure RFC 8707 resource parameter is set
        if not oauth_config_with_resource.get("resource"):
            normalized = normalize_resource_url(gateway.url)
            if normalized:
                oauth_config_with_resource["resource"] = normalized

        # Complete flow WITHOUT storing tokens (atomically returns state_data + token_response)
        result = await no_storage_oauth_manager.complete_authorization_code_flow(
            gateway_id=gateway_id,
            code=code,
            state=state,
            credentials=oauth_config_with_resource,
            ca_certificate=gateway.ca_certificate,
            client_cert=gateway.client_cert,
            client_key=gateway.client_key,
        )

        # Extract state_data from result (was atomically consumed and returned)
        state_data = result.get("state_data", {})
        app_user_email = state_data.get("app_user_email")
        if not app_user_email:
            logger.error("Vault OAuth callback: no app_user_email in state (CWE-287)")
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p>Error: User authentication context missing from OAuth state.</p>
                    <a href="{safe_root_path}/">Return to Home</a>
                </body>
                </html>
                """,
                status_code=400,
            )

        # Build user context for Vault token storage using stored team_id from OAuth state
        # SECURITY: Use team_id from OAuth state (which was derived from original token scope)
        # to preserve the authorization context from /vault/authorize. Do NOT re-query database
        # as that would widen a narrowed session token back to full DB membership.
        #
        # Token storage path mapping:
        # - stored_team_id present → teams=[team_id] → vault/oauth/{team_id}/...
        # - stored_team_id is None → teams=None → vault/oauth/shared/...
        stored_team_id = state_data.get("team_id")
        user_context = {
            "email": app_user_email,
            "teams": [stored_team_id] if stored_team_id else None,  # None = shared path
            "is_admin": False,
        }

        # Look up is_admin flag from EmailUser
        # NOTE: is_admin is not currently stored in OAuth state, so we query it here.
        # This is safe because is_admin is a global property, not token-scoped.
        from mcpgateway.db import EmailUser  # pylint: disable=import-outside-toplevel
        user = db.execute(select(EmailUser).where(EmailUser.email == app_user_email)).scalar_one_or_none()
        if user:
            user_context["is_admin"] = user.is_admin

        # Initialize token storage with proper user context for storing tokens
        token_storage = TokenStorageService(db, user_context)

        # Store tokens using the token_response from the atomically-completed flow.
        # NOTE: The authorization code has already been consumed above. If storage
        # fails here the user sees a clear error (not a false-success page). They
        # will need to re-authorize, but the flow cannot be retried with the same
        # code regardless — this is unavoidable in the Authorization Code grant.
        token_response = result.get("token_response", {})
        if token_response and token_response.get("access_token"):
            try:
                await token_storage.store_tokens(
                    gateway_id=gateway_id,
                    user_id=result.get("user_id", ""),
                    app_user_email=app_user_email,
                    access_token=token_response["access_token"],
                    refresh_token=token_response.get("refresh_token"),
                    expires_in=token_response.get("expires_in"),
                    scopes=token_response.get("scope", "").split() if token_response.get("scope") else [],
                )
            except Exception as store_exc:
                logger.error(
                    "Vault OAuth callback: code exchange succeeded but token storage failed "
                    "(code already consumed). gateway_id=%s, user=%s, error=%s",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                    str(store_exc),
                )
                return HTMLResponse(
                    content=f"""
                    <!DOCTYPE html>
                    <html>
                    <head><title>OAuth Authorization Failed</title></head>
                    <body>
                        <h1>❌ OAuth Authorization Failed</h1>
                        <p>Authorization was granted but credentials could not be stored.
                        Please try again or contact your administrator.</p>
                        <a href="{safe_root_path}/">Return to Home</a>
                    </body>
                    </html>
                    """,
                    status_code=500,
                )

        logger.info(
            "Vault OAuth callback: tokens stored in Vault, gateway_id=%s, user=%s",
            SecurityValidator.sanitize_log_message(gateway_id),
            SecurityValidator.sanitize_log_message(str(result.get("user_id"))),
        )

        # Success response
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>OAuth Authorization Successful</title></head>
            <body>
                <h1>✓ OAuth Authorization Successful</h1>
                <p>Your credentials have been securely stored in Vault.</p>
                <p>You can now close this window and use your MCP client.</p>
                <a href="{safe_root_path}/">Return to Home</a>
            </body>
            </html>
            """,
            status_code=200,
        )

    except Exception as e:
        logger.error("Vault OAuth callback failed: %s", str(e))
        root_path = resolve_root_path(request) if request else ""
        safe_root_path = escape(str(root_path), quote=True)
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>OAuth Authorization Failed</title></head>
            <body>
                <h1>❌ OAuth Authorization Failed</h1>
                <p>Error: An unexpected error occurred. Please try again or contact your administrator.</p>
                <a href="{safe_root_path}/">Return to Home</a>
            </body>
            </html>
            """,
            status_code=500,
        )
