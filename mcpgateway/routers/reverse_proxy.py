# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

FastAPI router for handling reverse proxy connections.

This module provides the WebSocket endpoint for reverse proxy clients
to connect and tunnel their local MCP servers through the gateway.
It keeps only WebSocket concerns — admission (authentication and both
authorization layers), accept/denial, and transport wrapping; the
connection lifecycle itself lives in
``mcpgateway.services.reverse_proxy_lifecycle``.
"""

# Standard
from typing import Any, Final, Optional

# Third-Party
import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status, WebSocket
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.auth_context import get_user_email
from mcpgateway.db import get_db, Permissions
from mcpgateway.middleware.rbac import _ACCESS_DENIED_MSG, PermissionChecker, token_scope_grants
from mcpgateway.middleware.token_scoping import token_scoping_middleware
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.reverse_proxy_lifecycle import _LockedConnectionIO, ReverseProxyAuthenticatedContext, run_proxied_connection
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.routers.reverse_proxy")

router = APIRouter(prefix="/reverse-proxy", tags=["reverse-proxy"])


_REVERSE_PROXY_CONNECT_PERMISSIONS: Final = (Permissions.GATEWAYS_CREATE, Permissions.SERVERS_CREATE)


def _get_websocket_bearer_token(websocket: WebSocket) -> Optional[str]:
    """Extract a bearer token only from the WebSocket Authorization header.

    Args:
        websocket: Incoming WebSocket connection.

    Returns:
        Bearer token value when present, otherwise None.
    """
    authorization = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
    if not authorization:
        return None
    scheme, separator, credentials = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not credentials.strip():
        return None
    return credentials.strip()


async def _authenticate_reverse_proxy_websocket(websocket: WebSocket) -> ReverseProxyAuthenticatedContext:
    """Authenticate and authorize a reverse-proxy WebSocket connection.

    Args:
        websocket: Incoming WebSocket connection.

    Returns:
        Canonical authenticated owner and server-derived team context.

    Raises:
        HTTPException: If authentication fails or required permissions are missing.
    """
    auth_token = _get_websocket_bearer_token(websocket)
    if auth_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_token)
    auth_scope = dict(websocket.scope)
    auth_scope["type"] = "http"
    auth_request = Request(auth_scope)
    user = await get_current_user(credentials, request=auth_request)
    owner_email = get_user_email(user)
    team_id: str | None = getattr(auth_request.state, "team_id", None)
    token_teams: list[str] | None = getattr(auth_request.state, "token_teams", None)
    token_scopes: list[str] | None = getattr(auth_request.state, "token_scopes", None)

    cached_payload = getattr(auth_request.state, "_jwt_verified_payload", None)
    if isinstance(cached_payload, tuple) and len(cached_payload) == 2 and cached_payload[0] == auth_token and isinstance(cached_payload[1], dict):
        token_payload = await verify_jwt_token_cached(auth_token, auth_request)
    elif getattr(auth_request.state, "auth_method", None) == "jwt":
        token_payload = await verify_jwt_token_cached(auth_token, auth_request)
    else:
        token_payload = {"scopes": {}}

    # Layer-1 parity with HTTP admission: revalidate claimed team membership
    # for non-session (API/legacy) tokens before restrictions, scopes, and RBAC.
    if token_payload.get("token_use") != "session" and not token_scoping_middleware.check_team_membership(token_payload):  # nosec B105 - Not a password; token_use is a JWT claim type
        LOGGER.warning(
            "Reverse proxy WebSocket admission denied: token team membership is no longer valid",
            extra={"event": "reverse_proxy.websocket.permission_denied", "owner_email": owner_email, "layer": "team_membership"},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is invalid: User is no longer a member of the associated team")
    request_path = str(websocket.scope.get("path") or "/reverse-proxy/ws")
    client_ip = websocket.client.host if websocket.client else "unknown"
    token_scoping_middleware.enforce_non_permission_restrictions(token_payload, request_path, client_ip)

    for permission in _REVERSE_PROXY_CONNECT_PERMISSIONS:
        if not token_scope_grants(token_scopes, permission):
            LOGGER.warning(
                "Reverse proxy WebSocket permission denied",
                extra={"event": "reverse_proxy.websocket.permission_denied", "owner_email": owner_email, "permission": permission, "layer": "token_scope"},
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)

    user_context: dict[str, Any] = {
        "email": owner_email,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
        "ip_address": websocket.client.host if websocket.client else None,
        "user_agent": websocket.headers.get("user-agent"),
        "team_id": team_id,
        "token_teams": token_teams,
        "token_use": getattr(auth_request.state, "token_use", None),
    }
    checker = PermissionChecker(user_context)
    for permission in _REVERSE_PROXY_CONNECT_PERMISSIONS:
        if not await checker.has_permission(permission, team_id=team_id):
            LOGGER.warning(
                "Reverse proxy WebSocket permission denied",
                extra={"event": "reverse_proxy.websocket.permission_denied", "owner_email": owner_email, "permission": permission, "layer": "rbac"},
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)

    return ReverseProxyAuthenticatedContext(owner_email=owner_email, team_id=team_id)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    db: Session = Depends(get_db),
):
    """WebSocket endpoint for reverse proxy connections.

    Authentication always requires a Bearer token in the Authorization header.
    The maintained client contract drives the lifecycle: ``register`` is
    acknowledged as ``register_ack(processing)`` before catalog persistence
    and MCP discovery run, then ``register_complete(success|error)`` closes
    the registration exchange. Heartbeats are acknowledgements, not pongs.
    One continuously-running receive pump owns every inbound frame while
    registration and discovery run as a sibling task, so the client's own
    JSON-RPC discovery responses always resolve.

    Args:
        websocket: WebSocket connection.
        db: Database session.
    """
    try:
        authenticated_context = await _authenticate_reverse_proxy_websocket(websocket)
    except HTTPException as exc:
        LOGGER.warning(
            "Reverse proxy WebSocket admission rejected",
            extra={"event": "reverse_proxy.websocket.rejected", "status_code": exc.status_code, "reason": str(exc.detail)},
        )
        await websocket.send_denial_response(JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}))
        return

    # Accept only after authentication and both authorization layers succeed.
    await websocket.accept()

    # Wrap the transport in the connection's shared I/O lock, then hand the
    # accepted connection to the lifecycle service.
    connection_io = _LockedConnectionIO(websocket, anyio.Lock())
    await run_proxied_connection(connection_io, authenticated_context, db)
