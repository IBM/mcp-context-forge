# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/oauth_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OAuth Router for ContextForge.

This module handles OAuth 2.0 Authorization Code flow endpoints including:
- Initiating OAuth flows
- Handling OAuth callbacks
- Token management
"""

# Standard
from html import escape
import logging
from typing import Annotated, Any, Dict
from urllib.parse import urlparse, urlunparse

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import normalize_token_teams
from mcpgateway.config import settings
from mcpgateway.db import Gateway, get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.middleware.token_scoping import token_scoping_middleware
from mcpgateway.schemas import EmailUserResponse
from mcpgateway.services.dcr_service import DcrError, DcrService
from mcpgateway.services.encryption_service import protect_oauth_config_for_storage
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager
from mcpgateway.services.token_storage_service import TokenStorageService

logger = logging.getLogger(__name__)


def _normalize_resource_url(url: str | None, *, preserve_query: bool = False) -> str | None:
    """Normalize URL for use as RFC 8707 resource parameter.

    Per RFC 8707 Section 2:
    - resource MUST be an absolute URI (scheme required; supports both URLs and URNs)
    - resource MUST NOT include a fragment component
    - resource SHOULD NOT include a query component (but allowed when necessary)

    Args:
        url: The resource URL to normalize
        preserve_query: If True, preserve query component (for explicitly configured resources).
                       If False, strip query (for auto-derived resources per RFC 8707 SHOULD NOT).

    Returns:
        Normalized URL suitable for RFC 8707 resource parameter, or None if invalid
    """
    if not url:
        return None
    parsed = urlparse(url)
    # RFC 8707: resource MUST be an absolute URI (requires scheme)
    # Support both hierarchical URIs (https://...) and URNs (urn:example:app)
    if not parsed.scheme:
        logger.warning(f"Invalid resource URL (must be absolute URI with scheme): {url}")
        return None
    # Remove fragment (MUST NOT per RFC 8707)
    # Query: strip for auto-derived (SHOULD NOT), preserve for explicit config (allowed when necessary)
    query = parsed.query if preserve_query else ""
    normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))
    return normalized


oauth_router = APIRouter(prefix="/oauth", tags=["oauth"])


def _require_admin_user(current_user: EmailUserResponse) -> None:
    """Require admin context for DCR management endpoints.

    Args:
        current_user: Authenticated user context from RBAC dependency.

    Raises:
        HTTPException: If requester is not an admin user.
    """
    is_admin = current_user.is_admin if hasattr(current_user, "is_admin") else current_user.get("is_admin", False)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin permissions required")


def _resolve_token_teams_for_scope_check(request: Request, current_user: EmailUserResponse) -> list[str] | None:
    """Resolve token teams for scoped ownership checks using normalized token semantics.

    Args:
        request: Incoming request with token scoping state.
        current_user: Authenticated user context.

    Returns:
        ``None`` for unrestricted admin scope, or a normalized team list for scoped access.
    """
    is_admin = False
    if hasattr(current_user, "is_admin"):
        is_admin = bool(getattr(current_user, "is_admin", False))
    elif isinstance(current_user, dict):
        is_admin = bool(current_user.get("is_admin", False) or current_user.get("user", {}).get("is_admin", False))

    _not_set = object()
    token_teams = getattr(request.state, "token_teams", _not_set)
    if token_teams is _not_set or not (token_teams is None or isinstance(token_teams, list)):
        cached = getattr(request.state, "_jwt_verified_payload", None)
        if cached and isinstance(cached, tuple) and len(cached) == 2:
            _, payload = cached
            if payload:
                token_teams = normalize_token_teams(payload)
                is_admin = bool(payload.get("is_admin", False) or payload.get("user", {}).get("is_admin", False))
        # Fail closed when request.state contains an unexpected token_teams value.
        if token_teams is not _not_set and not (token_teams is None or isinstance(token_teams, list)):
            token_teams = _not_set

    if token_teams is _not_set:
        token_teams = None if is_admin else []

    # Empty-team scoped tokens are public-only and must never receive admin bypass.
    if isinstance(token_teams, list) and len(token_teams) == 0:
        is_admin = False

    if is_admin and token_teams is None:
        return None
    return token_teams


def _extract_user_email(current_user: EmailUserResponse | dict) -> str | None:
    """Extract requester email from typed or dict user contexts.

    Args:
        current_user: Authenticated user context.

    Returns:
        Lowercased email when available, otherwise ``None``.
    """
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
    """Extract admin flag from typed or dict user contexts.

    Args:
        current_user: Authenticated user context.

    Returns:
        ``True`` when the user context indicates admin privileges.
    """
    if hasattr(current_user, "is_admin"):
        return bool(getattr(current_user, "is_admin", False))
    if isinstance(current_user, dict):
        return bool(current_user.get("is_admin", False) or current_user.get("user", {}).get("is_admin", False))
    return False


async def _enforce_gateway_access(
    gateway_id: str,
    gateway: Gateway,
    current_user: EmailUserResponse,
    db: Session,
    request: Request | None = None,
) -> None:
    """Enforce gateway visibility and ownership checks for OAuth endpoints.

    Args:
        gateway_id: Gateway identifier used for scoped ownership checks.
        gateway: Gateway record being accessed.
        current_user: Authenticated requester context.
        db: Active database session.
        request: Optional request carrying token-scoping context.

    Raises:
        HTTPException: If authentication is missing or access is not permitted.
    """
    requester_email = _extract_user_email(current_user)
    if not requester_email:
        raise HTTPException(status_code=401, detail="User authentication required")

    requester_is_admin = _extract_is_admin(current_user)

    if request is not None:
        token_teams = _resolve_token_teams_for_scope_check(request, current_user)
        if token_teams is None:
            if requester_is_admin:
                return
            token_teams = []

        if not token_scoping_middleware._check_resource_team_ownership(
            f"/gateways/{gateway_id}",
            token_teams,
            db=db,
            _user_email=requester_email,
        ):
            raise HTTPException(status_code=403, detail="You don't have access to this gateway")

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
        # First-Party
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
        # First-Party
        from mcpgateway.services.email_auth_service import EmailAuthService

        auth_service = EmailAuthService(db)
        user = await auth_service.get_user_by_email(requester_email)
        if user and user.is_team_member(gateway_team_id):
            return

    raise HTTPException(status_code=403, detail="You don't have access to this gateway")


@oauth_router.get("/authorize/{gateway_id}")
async def initiate_oauth_flow(
    gateway_id: str, request: Request, current_user: EmailUserResponse = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)
) -> RedirectResponse:  # noqa: ARG001
    """Initiates the OAuth 2.0 Authorization Code flow for a specified gateway.

    This endpoint retrieves the OAuth configuration for the given gateway, validates that
    the gateway supports the Authorization Code flow, and redirects the user to the OAuth
    provider's authorization URL to begin the OAuth process.

    **Phase 1.4: DCR Integration**
    If the gateway has an issuer but no client_id, and DCR is enabled, this endpoint will
    automatically register the gateway as an OAuth client with the Authorization Server
    using Dynamic Client Registration (RFC 7591).

    Args:
        gateway_id: The unique identifier of the gateway to authorize.
        request: The FastAPI request object.
        current_user: The authenticated user initiating the OAuth flow.
        db: The database session dependency.

    Returns:
        A redirect response to the OAuth provider's authorization URL.

    Raises:
        HTTPException: If the gateway is not found, not configured for OAuth, or not using
            the Authorization Code flow. If an unexpected error occurs during the initiation process.

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(initiate_oauth_flow)
        True
    """
    try:
        # Get gateway configuration
        gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()

        if not gateway:
            raise HTTPException(status_code=404, detail="Gateway not found")

        await _enforce_gateway_access(gateway_id, gateway, current_user, db, request=request)

        if not gateway.oauth_config:
            raise HTTPException(status_code=400, detail="Gateway is not configured for OAuth")

        if gateway.oauth_config.get("grant_type") != "authorization_code":
            raise HTTPException(status_code=400, detail="Gateway is not configured for Authorization Code flow")

        oauth_config = gateway.oauth_config.copy()  # Work with a copy to avoid mutating the original

        # RFC 8707: Set resource parameter for JWT access tokens
        # Respect pre-configured resource (e.g., for providers requiring pre-registered resources)
        # Only derive from gateway.url if not explicitly configured
        if oauth_config.get("resource"):
            # Normalize existing resource - preserve query for explicit config (RFC 8707 allows when necessary)
            existing = oauth_config["resource"]
            if isinstance(existing, list):
                original_count = len(existing)
                normalized = [_normalize_resource_url(r, preserve_query=True) for r in existing]
                oauth_config["resource"] = [r for r in normalized if r]
                if not oauth_config["resource"] and original_count > 0:
                    logger.warning(f"All {original_count} configured resource values were invalid and removed")
            else:
                oauth_config["resource"] = _normalize_resource_url(existing, preserve_query=True)
        else:
            # Default to gateway.url as the resource (strip query per RFC 8707 SHOULD NOT)
            oauth_config["resource"] = _normalize_resource_url(gateway.url)

        # Phase 1.4: Auto-trigger DCR if credentials are missing
        # Check if gateway has issuer but no client_id (DCR scenario)
        issuer = oauth_config.get("issuer")
        client_id = oauth_config.get("client_id")

        if issuer and not client_id:
            if settings.dcr_enabled and settings.dcr_auto_register_on_missing_credentials:
                logger.info(f"Gateway {gateway_id} has issuer but no client_id. Attempting DCR...")

                try:
                    # Initialize DCR service
                    dcr_service = DcrService()

                    # Check if client is already registered in database
                    registered_client = await dcr_service.get_or_register_client(
                        gateway_id=gateway_id,
                        gateway_name=gateway.name,
                        issuer=issuer,
                        redirect_uri=oauth_config.get("redirect_uri"),
                        scopes=oauth_config.get("scopes", settings.dcr_default_scopes),
                        db=db,
                    )

                    logger.info(f"✅ DCR successful for gateway {gateway_id}: client_id={registered_client.client_id}")

                    # Decrypt the client secret for use in OAuth flow (if present - public clients may not have secrets)
                    decrypted_secret = None
                    if registered_client.client_secret_encrypted:
                        # First-Party
                        from mcpgateway.services.encryption_service import get_encryption_service

                        encryption = get_encryption_service(settings.auth_encryption_secret)
                        decrypted_secret = await encryption.decrypt_secret_async(registered_client.client_secret_encrypted)

                    # Update oauth_config with registered credentials
                    oauth_config["client_id"] = registered_client.client_id
                    if decrypted_secret:
                        oauth_config["client_secret"] = decrypted_secret

                    # Discover AS metadata to get authorization/token endpoints if not already set
                    # Note: OAuthManager expects 'authorization_url' and 'token_url', not 'authorization_endpoint'/'token_endpoint'
                    if not oauth_config.get("authorization_url") or not oauth_config.get("token_url"):
                        metadata = await dcr_service.discover_as_metadata(issuer)
                        oauth_config["authorization_url"] = metadata.get("authorization_endpoint")
                        oauth_config["token_url"] = metadata.get("token_endpoint")
                        logger.info(f"Discovered OAuth endpoints for {issuer}")

                    # Update gateway's oauth_config and auth_type in database for future use.
                    # Protect sensitive fields before persistence to keep service-layer behavior consistent.
                    gateway.oauth_config = await protect_oauth_config_for_storage(oauth_config, existing_oauth_config=gateway.oauth_config)
                    gateway.auth_type = "oauth"  # Ensure auth_type is set for OAuth-protected servers
                    db.commit()

                    logger.info(f"Updated gateway {gateway_id} with DCR credentials and auth_type=oauth")

                except DcrError as dcr_err:
                    logger.error(f"DCR failed for gateway {gateway_id}: {dcr_err}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Dynamic Client Registration failed: {str(dcr_err)}. Please configure client_id and client_secret manually or check your OAuth server supports RFC 7591.",
                    )
                except Exception as dcr_ex:
                    logger.error(f"Unexpected error during DCR for gateway {gateway_id}: {dcr_ex}")
                    raise HTTPException(status_code=500, detail=f"Failed to register OAuth client: {str(dcr_ex)}")
            else:
                # DCR is disabled or auto-register is off
                logger.warning(f"Gateway {gateway_id} has issuer but no client_id, and DCR auto-registration is disabled")
                raise HTTPException(
                    status_code=400,
                    detail="Gateway OAuth configuration is incomplete. Please provide client_id and client_secret, or enable DCR (Dynamic Client Registration) by setting MCPGATEWAY_DCR_ENABLED=true and MCPGATEWAY_DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS=true",
                )

        # Validate required fields for OAuth flow
        if not oauth_config.get("client_id"):
            raise HTTPException(status_code=400, detail="OAuth configuration missing client_id")

        # Initiate OAuth flow with user context (now includes PKCE from existing implementation)
        requester_email = _extract_user_email(current_user)
        oauth_manager = OAuthManager(token_storage=TokenStorageService(db))
        auth_data = await oauth_manager.initiate_authorization_code_flow(gateway_id, oauth_config, app_user_email=requester_email)

        logger.info(f"Initiated OAuth flow for gateway {gateway_id} by user {requester_email}")

        # Redirect user to OAuth provider
        return RedirectResponse(url=auth_data["authorization_url"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initiate OAuth flow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to initiate OAuth flow: {str(e)}")


@oauth_router.get("/callback")
async def oauth_callback(
    code: Annotated[str | None, Query(description="Authorization code from OAuth provider")] = None,
    state: Annotated[str, Query(description="State parameter for CSRF protection")] = ...,
    error: Annotated[str | None, Query(description="OAuth provider error code")] = None,
    error_description: Annotated[str | None, Query(description="OAuth provider error description")] = None,
    # Remove the gateway_id parameter requirement
    request: Request = None,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Handle the OAuth callback and complete the authorization process.

    This endpoint is called by the OAuth provider after the user authorizes access.
    It receives the authorization code and state parameters, verifies the state,
    retrieves the corresponding gateway configuration, and exchanges the code for an access token.

    Args:
        code (str): The authorization code returned by the OAuth provider.
        state (str): The state parameter for CSRF protection, which encodes the gateway ID.
        error (str): OAuth provider error code from error callback (RFC 6749 Section 4.1.2.1).
        error_description (str): OAuth provider error description.
        request (Request): The incoming HTTP request object.
        db (Session): The database session dependency.

    Returns:
        HTMLResponse: An HTML response indicating the result of the OAuth authorization process.

    Raises:
        ValueError: Raised internally when state parameter is missing gateway_id (caught and handled).

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(oauth_callback)
        True
    """

    try:
        # Get root path for URL construction
        root_path = request.scope.get("root_path", "") if request else ""
        safe_root_path = escape(str(root_path), quote=True)

        # RFC 6749 Section 4.1.2.1: provider may return error instead of code
        if error:
            error_text = escape(error)
            description_text = escape(error_description or "OAuth provider returned an authorization error.")
            logger.warning(f"OAuth provider returned error callback: error={error}, description={error_description}")
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p><strong>Error:</strong> {error_text}</p>
                    <p><strong>Description:</strong> {description_text}</p>
                    <a href="{safe_root_path}/admin#gateways">Return to Admin Panel</a>
                </body>
                </html>
                """,
                status_code=400,
            )

        if not code:
            logger.warning("OAuth callback missing authorization code")
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p>Error: Missing authorization code in callback response.</p>
                    <a href="{safe_root_path}/admin#gateways">Return to Admin Panel</a>
                </body>
                </html>
                """,
                status_code=400,
            )

        oauth_manager = OAuthManager(token_storage=TokenStorageService(db))
        gateway_id = await oauth_manager.resolve_gateway_id_from_state(state)
        if not gateway_id:
            logger.warning("OAuth callback received invalid or unknown state token")
            return HTMLResponse(content="<h1>❌ Invalid state parameter</h1>", status_code=400)

        # Get gateway configuration
        gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()

        if not gateway:
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p>Error: Gateway not found</p>
                    <a href="{safe_root_path}/admin#gateways">Return to Admin Panel</a>
                </body>
                </html>
                """,
                status_code=404,
            )

        if not gateway.oauth_config:
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p>Error: Gateway has no OAuth configuration</p>
                    <a href="{safe_root_path}/admin#gateways">Return to Admin Panel</a>
                </body>
                </html>
                """,
                status_code=400,
            )

        # Complete OAuth flow

        # RFC 8707: Add resource parameter for JWT access tokens
        # Must be set here in callback, not just in /authorize, because complete_authorization_code_flow
        # needs it for the token exchange request
        # Respect pre-configured resource; only derive from gateway.url if not explicitly configured
        oauth_config_with_resource = gateway.oauth_config.copy()
        if oauth_config_with_resource.get("resource"):
            # Preserve query for explicit config (RFC 8707 allows when necessary)
            existing = oauth_config_with_resource["resource"]
            if isinstance(existing, list):
                original_count = len(existing)
                normalized = [_normalize_resource_url(r, preserve_query=True) for r in existing]
                oauth_config_with_resource["resource"] = [r for r in normalized if r]
                if not oauth_config_with_resource["resource"] and original_count > 0:
                    logger.warning(f"All {original_count} configured resource values were invalid and removed")
            else:
                oauth_config_with_resource["resource"] = _normalize_resource_url(existing, preserve_query=True)
        else:
            # Strip query for auto-derived (RFC 8707 SHOULD NOT)
            oauth_config_with_resource["resource"] = _normalize_resource_url(gateway.url)

        result = await oauth_manager.complete_authorization_code_flow(gateway_id, code, state, oauth_config_with_resource)

        logger.info(f"Completed OAuth flow for gateway {gateway_id}, user {result.get('user_id')}")

        # Return success page with option to return to admin
        return HTMLResponse(
            content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>OAuth Authorization Successful</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .success {{ color: #059669; }}
                .error {{ color: #dc2626; }}
                .info {{ color: #2563eb; }}
                .button {{
                    display: inline-block;
                    padding: 10px 20px;
                    background-color: #3b82f6;
                    color: white;
                    text-decoration: none;
                    border-radius: 5px;
                    margin-top: 20px;
                }}
                .button:hover {{ background-color: #2563eb; }}
            </style>
        </head>
        <body>
            <h1 class="success">✅ OAuth Authorization Successful</h1>
            <div class="info">
                <p><strong>Gateway:</strong> {escape(str(gateway.name))}</p>
                <p><strong>User ID:</strong> {escape(str(result.get("user_id", "Unknown")))}</p>
                <p><strong>Expires:</strong> {escape(str(result.get("expires_at", "Unknown")))}</p>
                <p><strong>Status:</strong> Authorization completed successfully</p>
            </div>

            <div style="margin: 30px 0;">
                <h3>Next Steps:</h3>
                <p>Now that OAuth authorization is complete, you can fetch tools from the MCP server:</p>
                <button onclick="fetchTools()" class="button" style="background-color: #059669;">
                    🔧 Fetch Tools from MCP Server
                </button>
                <div id="fetch-status" style="margin-top: 15px;"></div>
            </div>

            <a href="{safe_root_path}/admin#gateways" class="button">Return to Admin Panel</a>

            <script>
            async function fetchTools() {{
                const button = event.target;
                const statusDiv = document.getElementById('fetch-status');

                button.disabled = true;
                button.textContent = '⏳ Fetching Tools...';
                statusDiv.innerHTML = '<p style="color: #2563eb;">Fetching tools from MCP server...</p>';

                try {{
                    const response = await fetch('{safe_root_path}/oauth/fetch-tools/{escape(str(gateway_id))}', {{
                        method: 'POST',
                        credentials: 'include',
                        headers: {{ 'Accept': 'text/html' }}
                    }});

                    const result = await response.json();

                    if (response.ok) {{
                        statusDiv.innerHTML = `
                            <div style="color: #059669; padding: 15px; background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 5px;">
                                <h4>✅ Tools Fetched Successfully!</h4>
                                <p>${{result.message}}</p>
                            </div>
                        `;
                        button.textContent = '✅ Tools Fetched';
                        button.style.backgroundColor = '#059669';
                    }} else {{
                        throw new Error(result.detail || 'Failed to fetch tools');
                    }}
                }} catch (error) {{
                    statusDiv.innerHTML = `
                        <div style="color: #dc2626; padding: 15px; background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 5px;">
                            <h4>❌ Failed to Fetch Tools</h4>
                            <p><strong>Error:</strong> ${{error.message}}</p>
                            <p>You can still return to the admin panel and try again later.</p>
                        </div>
                    `;
                    button.textContent = '❌ Retry Fetch Tools';
                    button.style.backgroundColor = '#dc2626';
                    button.disabled = false;
                }}
            }}
            </script>
        </body>
        </html>
        """
        )

    except OAuthError as e:
        logger.error(f"OAuth callback failed: {str(e)}")
        return HTMLResponse(
            content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>OAuth Authorization Failed</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .error {{ color: #dc2626; }}
                .button {{
                    display: inline-block;
                    padding: 10px 20px;
                    background-color: #3b82f6;
                    color: white;
                    text-decoration: none;
                    border-radius: 5px;
                    margin-top: 20px;
                }}
                .button:hover {{ background-color: #2563eb; }}
            </style>
        </head>
        <body>
            <h1 class="error">❌ OAuth Authorization Failed</h1>
            <p><strong>Error:</strong> {escape(str(e))}</p>
            <p>Please check your OAuth configuration and try again.</p>
            <a href="{safe_root_path}/admin#gateways" class="button">Return to Admin Panel</a>
        </body>
        </html>
        """,
            status_code=400,
        )

    except Exception as e:
        logger.error(f"Unexpected error in OAuth callback: {str(e)}")
        return HTMLResponse(
            content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>OAuth Authorization Failed</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .error {{ color: #dc2626; }}
                .button {{
                    display: inline-block;
                    padding: 10px 20px;
                    background-color: #3b82f6;
                    color: white;
                    text-decoration: none;
                    border-radius: 5px;
                    margin-top: 20px;
                }}
                .button:hover {{ background-color: #2563eb; }}
            </style>
        </head>
        <body>
            <h1 class="error">❌ OAuth Authorization Failed</h1>
            <p><strong>Unexpected Error:</strong> {escape(str(e))}</p>
            <p>Please contact your administrator for assistance.</p>
            <a href="{safe_root_path}/admin#gateways" class="button">Return to Admin Panel</a>
        </body>
        </html>
        """,
            status_code=500,
        )


@oauth_router.get("/status/{gateway_id}")
async def get_oauth_status(
    gateway_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> dict:
    """Get OAuth status for a gateway.

    Requires authentication and authorization to prevent information disclosure
    about gateway OAuth configuration (client IDs, scopes, etc.).

    Args:
        gateway_id: ID of the gateway
        current_user: Authenticated user (enforces authentication)
        db: Database session
        request: Request with token-scoping context.

    Returns:
        OAuth status information

    Raises:
        HTTPException: If not authenticated, not authorized, gateway not found, or error
    """
    try:
        # Get gateway configuration
        gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()

        if not gateway:
            raise HTTPException(status_code=404, detail="Gateway not found")

        await _enforce_gateway_access(gateway_id, gateway, current_user, db, request=request)

        if not gateway.oauth_config:
            return {"oauth_enabled": False, "message": "Gateway is not configured for OAuth"}

        # Get OAuth configuration info
        oauth_config = gateway.oauth_config
        grant_type = oauth_config.get("grant_type")

        if grant_type == "authorization_code":
            # For now, return basic info - in a real implementation you might want to
            # show authorized users, token status, etc.
            return {
                "oauth_enabled": True,
                "grant_type": grant_type,
                "client_id": oauth_config.get("client_id"),
                "scopes": oauth_config.get("scopes", []),
                "authorization_url": oauth_config.get("authorization_url"),
                "redirect_uri": oauth_config.get("redirect_uri"),
                "message": "Gateway configured for Authorization Code flow",
            }
        else:
            return {
                "oauth_enabled": True,
                "grant_type": grant_type,
                "client_id": oauth_config.get("client_id"),
                "scopes": oauth_config.get("scopes", []),
                "message": f"Gateway configured for {grant_type} flow",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get OAuth status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get OAuth status: {str(e)}")


@oauth_router.post("/fetch-tools/{gateway_id}")
@require_permission("gateways.update")
async def fetch_tools_after_oauth(
    gateway_id: str,
    request: Request,
    current_user: EmailUserResponse = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Fetch tools from MCP server after OAuth completion for Authorization Code flow.

    Args:
        gateway_id: ID of the gateway to fetch tools for
        request: Incoming request used for token scope context
        current_user: The authenticated user fetching tools
        db: Database session

    Returns:
        Dict containing success status and message with number of tools fetched

    Raises:
        HTTPException: If fetching tools fails
    """
    try:
        gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()
        if not gateway:
            raise HTTPException(status_code=404, detail=f"Gateway not found: {gateway_id}")

        requester_email = current_user.get("email") if isinstance(current_user, dict) else getattr(current_user, "email", None)
        await _enforce_gateway_access(gateway_id, gateway, current_user, db, request=request)

        # First-Party
        from mcpgateway.services.gateway_service import GatewayService

        gateway_service = GatewayService()
        result = await gateway_service.fetch_tools_after_oauth(db, gateway_id, requester_email)
        tools_count = len(result.get("tools", []))

        return {"success": True, "message": f"Successfully fetched and created {tools_count} tools"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch tools after OAuth for gateway {gateway_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch tools: {str(e)}")


# ============================================================================
# Admin Endpoints for DCR Management
# ============================================================================


@oauth_router.get("/registered-clients")
async def list_registered_oauth_clients(current_user: EmailUserResponse = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> Dict[str, Any]:  # noqa: ARG001
    """List all registered OAuth clients (created via DCR).

    This endpoint shows OAuth clients that were dynamically registered with external
    Authorization Servers using RFC 7591 Dynamic Client Registration.

    Args:
        current_user: The authenticated user (admin access required)
        db: Database session

    Returns:
        Dict containing list of registered OAuth clients with metadata

    Raises:
        HTTPException: If user lacks permissions or database error occurs
    """
    _require_admin_user(current_user)

    try:
        # First-Party
        from mcpgateway.db import RegisteredOAuthClient

        # Query all registered clients
        clients = db.execute(select(RegisteredOAuthClient)).scalars().all()

        # Build response
        clients_data = []
        for client in clients:
            clients_data.append(
                {
                    "id": client.id,
                    "gateway_id": client.gateway_id,
                    "issuer": client.issuer,
                    "client_id": client.client_id,
                    "redirect_uris": client.redirect_uris.split(",") if isinstance(client.redirect_uris, str) else client.redirect_uris,
                    "grant_types": client.grant_types.split(",") if isinstance(client.grant_types, str) else client.grant_types,
                    "scope": client.scope,
                    "token_endpoint_auth_method": client.token_endpoint_auth_method,
                    "created_at": client.created_at.isoformat() if client.created_at else None,
                    "expires_at": client.expires_at.isoformat() if client.expires_at else None,
                    "is_active": client.is_active,
                }
            )

        return {"total": len(clients_data), "clients": clients_data}

    except Exception as e:
        logger.error(f"Failed to list registered OAuth clients: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list registered clients: {str(e)}")


@oauth_router.get("/registered-clients/{gateway_id}")
async def get_registered_client_for_gateway(
    gateway_id: str,
    current_user: EmailUserResponse = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),  # noqa: ARG001
) -> Dict[str, Any]:
    """Get the registered OAuth client for a specific gateway.

    Args:
        gateway_id: The gateway ID to lookup
        current_user: The authenticated user
        db: Database session

    Returns:
        Dict containing registered client information

    Raises:
        HTTPException: If gateway or registered client not found
    """
    _require_admin_user(current_user)

    try:
        # First-Party
        from mcpgateway.db import RegisteredOAuthClient

        # Query registered client for this gateway
        client = db.execute(select(RegisteredOAuthClient).where(RegisteredOAuthClient.gateway_id == gateway_id)).scalar_one_or_none()

        if not client:
            raise HTTPException(status_code=404, detail=f"No registered OAuth client found for gateway {gateway_id}")

        return {
            "id": client.id,
            "gateway_id": client.gateway_id,
            "issuer": client.issuer,
            "client_id": client.client_id,
            "redirect_uris": client.redirect_uris.split(",") if isinstance(client.redirect_uris, str) else client.redirect_uris,
            "grant_types": client.grant_types.split(",") if isinstance(client.grant_types, str) else client.grant_types,
            "scope": client.scope,
            "token_endpoint_auth_method": client.token_endpoint_auth_method,
            "registration_client_uri": client.registration_client_uri,
            "created_at": client.created_at.isoformat() if client.created_at else None,
            "expires_at": client.expires_at.isoformat() if client.expires_at else None,
            "is_active": client.is_active,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get registered client for gateway {gateway_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get registered client: {str(e)}")


@oauth_router.delete("/registered-clients/{client_id}")
async def delete_registered_client(client_id: str, current_user: EmailUserResponse = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> Dict[str, Any]:  # noqa: ARG001
    """Delete a registered OAuth client.

    This will revoke the client registration locally. Note: This does not automatically
    revoke the client at the Authorization Server. You may need to manually revoke the
    client using the registration_client_uri if available.

    Args:
        client_id: The registered client ID to delete
        current_user: The authenticated user (admin access required)
        db: Database session

    Returns:
        Dict containing success message

    Raises:
        HTTPException: If client not found or deletion fails
    """
    _require_admin_user(current_user)

    try:
        # First-Party
        from mcpgateway.db import RegisteredOAuthClient

        # Find the client
        client = db.execute(select(RegisteredOAuthClient).where(RegisteredOAuthClient.id == client_id)).scalar_one_or_none()

        if not client:
            raise HTTPException(status_code=404, detail=f"Registered client {client_id} not found")

        issuer = client.issuer
        gateway_id = client.gateway_id

        # Delete the client
        db.delete(client)
        db.commit()
        db.close()

        logger.info(f"Deleted registered OAuth client {client_id} for gateway {gateway_id} (issuer: {issuer})")

        return {"success": True, "message": f"Registered OAuth client {client_id} deleted successfully", "gateway_id": gateway_id, "issuer": issuer}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete registered client {client_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete registered client: {str(e)}")
