# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/oauth_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OAuth Router for MCP Gateway.

This module handles OAuth 2.0 Authorization Code flow endpoints including:
- Initiating OAuth flows
- Handling OAuth callbacks
- Token management
"""

# Standard
import logging
from typing import Any, Dict

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway, get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.schemas import EmailUserResponse
from mcpgateway.services.dcr_service import DcrError, DcrService
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager
from mcpgateway.services.token_storage_service import TokenStorageService

logger = logging.getLogger(__name__)

oauth_router = APIRouter(prefix="/oauth", tags=["oauth"])


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

        if not gateway.oauth_config:
            raise HTTPException(status_code=400, detail="Gateway is not configured for OAuth")

        if gateway.oauth_config.get("grant_type") != "authorization_code":
            raise HTTPException(status_code=400, detail="Gateway is not configured for Authorization Code flow")

        oauth_config = gateway.oauth_config.copy()  # Work with a copy to avoid mutating the original

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
                        decrypted_secret = encryption.decrypt_secret(registered_client.client_secret_encrypted)

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

                    # Update gateway's oauth_config and auth_type in database for future use
                    gateway.oauth_config = oauth_config
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
        oauth_manager = OAuthManager(token_storage=TokenStorageService(db))
        auth_data = await oauth_manager.initiate_authorization_code_flow(gateway_id, oauth_config, app_user_email=current_user.get("email"))

        logger.info(f"Initiated OAuth flow for gateway {gateway_id} by user {current_user.get('email')}")

        # Redirect user to OAuth provider
        return RedirectResponse(url=auth_data["authorization_url"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initiate OAuth flow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to initiate OAuth flow: {str(e)}")


@oauth_router.get("/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from OAuth provider"),
    state: str = Query(..., description="State parameter for CSRF protection"),
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

        # Extract gateway_id from state parameter
        # Try new base64-encoded JSON format first
        # Standard
        import base64

        # Third-Party
        import orjson

        try:
            # Expect state as base64url(payload || signature) where the last 32 bytes
            # are the signature. Decode to bytes first so we can split payload vs sig.
            state_raw = base64.urlsafe_b64decode(state.encode())
            if len(state_raw) <= 32:
                raise ValueError("State too short to contain payload and signature")

            # Split payload and signature. Signature is the last 32 bytes.
            payload_bytes = state_raw[:-32]
            # signature_bytes = state_raw[-32:]

            # Parse the JSON payload only (not including signature bytes)
            try:
                state_data = orjson.loads(payload_bytes)
            except Exception as decode_exc:
                raise ValueError(f"Failed to parse state payload JSON: {decode_exc}")

            gateway_id = state_data.get("gateway_id")
            if not gateway_id:
                raise ValueError("No gateway_id in state")
        except Exception as e:
            # Fallback to legacy format (gateway_id_random)
            logger.warning(f"Failed to decode state as JSON, trying legacy format: {e}")
            if "_" not in state:
                return HTMLResponse(content="<h1>❌ Invalid state parameter</h1>", status_code=400)
            gateway_id = state.split("_")[0]

        # Get gateway configuration
        gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()

        if not gateway:
            return HTMLResponse(
                content="""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p>Error: Gateway not found</p>
                    <a href="{root_path}/admin#gateways">Return to Admin Panel</a>
                </body>
                </html>
                """,
                status_code=404,
            )

        if not gateway.oauth_config:
            return HTMLResponse(
                content="""
                <!DOCTYPE html>
                <html>
                <head><title>OAuth Authorization Failed</title></head>
                <body>
                    <h1>❌ OAuth Authorization Failed</h1>
                    <p>Error: Gateway has no OAuth configuration</p>
                    <a href="{root_path}/admin#gateways">Return to Admin Panel</a>
                </body>
                </html>
                """,
                status_code=400,
            )

        # Complete OAuth flow
        oauth_manager = OAuthManager(token_storage=TokenStorageService(db))

        result = await oauth_manager.complete_authorization_code_flow(gateway_id, code, state, gateway.oauth_config)

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
                <p><strong>Gateway:</strong> {gateway.name}</p>
                <p><strong>User ID:</strong> {result.get("user_id", "Unknown")}</p>
                <p><strong>Expires:</strong> {result.get("expires_at", "Unknown")}</p>
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

            <a href="{root_path}/admin#gateways" class="button">Return to Admin Panel</a>

            <script>
            async function fetchTools() {{
                const button = event.target;
                const statusDiv = document.getElementById('fetch-status');

                button.disabled = true;
                button.textContent = '⏳ Fetching Tools...';
                statusDiv.innerHTML = '<p style="color: #2563eb;">Fetching tools from MCP server...</p>';

                try {{
                    const response = await fetch('{root_path}/oauth/fetch-tools/{gateway_id}', {{
                        method: 'POST'
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
            <p><strong>Error:</strong> {str(e)}</p>
            <p>Please check your OAuth configuration and try again.</p>
            <a href="{root_path}/admin#gateways" class="button">Return to Admin Panel</a>
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
            <p><strong>Unexpected Error:</strong> {str(e)}</p>
            <p>Please contact your administrator for assistance.</p>
            <a href="{root_path}/admin#gateways" class="button">Return to Admin Panel</a>
        </body>
        </html>
        """,
            status_code=500,
        )


@oauth_router.get("/status/{gateway_id}")
async def get_oauth_status(gateway_id: str, db: Session = Depends(get_db)) -> dict:
    """Get OAuth status for a gateway.

    Args:
        gateway_id: ID of the gateway
        db: Database session

    Returns:
        OAuth status information

    Raises:
        HTTPException: If gateway not found or error retrieving status
    """
    try:
        # Get gateway configuration
        gateway = db.execute(select(Gateway).where(Gateway.id == gateway_id)).scalar_one_or_none()

        if not gateway:
            raise HTTPException(status_code=404, detail="Gateway not found")

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
async def fetch_tools_after_oauth(gateway_id: str, current_user: EmailUserResponse = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Fetch tools from MCP server after OAuth completion for Authorization Code flow.

    Args:
        gateway_id: ID of the gateway to fetch tools for
        current_user: The authenticated user fetching tools
        db: Database session

    Returns:
        Dict containing success status and message with number of tools fetched

    Raises:
        HTTPException: If fetching tools fails
    """
    try:
        # First-Party
        from mcpgateway.services.gateway_service import GatewayService

        gateway_service = GatewayService()
        result = await gateway_service.fetch_tools_after_oauth(db, gateway_id, current_user.get("email"))
        tools_count = len(result.get("tools", []))

        return {"success": True, "message": f"Successfully fetched and created {tools_count} tools"}

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

        logger.info(f"Deleted registered OAuth client {client_id} for gateway {gateway_id} (issuer: {issuer})")

        return {"success": True, "message": f"Registered OAuth client {client_id} deleted successfully", "gateway_id": gateway_id, "issuer": issuer}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete registered client {client_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete registered client: {str(e)}")
