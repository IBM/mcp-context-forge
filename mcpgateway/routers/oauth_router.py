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
from mcpgateway.auth import get_current_user
from mcpgateway.db import Gateway, get_db
from mcpgateway.schemas import EmailUserResponse
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager
from mcpgateway.services.token_storage_service import TokenStorageService

logger = logging.getLogger(__name__)

oauth_router = APIRouter(prefix="/oauth", tags=["oauth"])


@oauth_router.get("/authorize/{gateway_id}")
async def initiate_oauth_flow(gateway_id: str, request: Request, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> RedirectResponse:
    """Initiates the OAuth 2.0 Authorization Code flow for a specified gateway.

    This endpoint retrieves the OAuth configuration for the given gateway, validates that
    the gateway supports the Authorization Code flow, and redirects the user to the OAuth
    provider's authorization URL to begin the OAuth process.

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

        # Initiate OAuth flow with user context
        oauth_manager = OAuthManager(token_storage=TokenStorageService(db))
        auth_data = await oauth_manager.initiate_authorization_code_flow(gateway_id, gateway.oauth_config, app_user_email=current_user.email)

        logger.info(f"Initiated OAuth flow for gateway {gateway_id} by user {current_user.email}")

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
        import json

        try:
            state_decoded = base64.urlsafe_b64decode(state.encode()).decode()
            state_data = json.loads(state_decoded)
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
async def fetch_tools_after_oauth(gateway_id: str, current_user: EmailUserResponse = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
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
        result = await gateway_service.fetch_tools_after_oauth(db, gateway_id, current_user.email)
        tools_count = len(result.get("tools", []))

        return {"success": True, "message": f"Successfully fetched and created {tools_count} tools"}

    except Exception as e:
        logger.error(f"Failed to fetch tools after OAuth for gateway {gateway_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch tools: {str(e)}")
