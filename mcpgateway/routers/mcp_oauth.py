#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
"""MCP OAuth 2.0 Authorization Server proxy for virtual servers.

Enables MCP clients (VS Code, Cursor) to authenticate via an external IdP
(e.g. Microsoft Entra ID) without requiring Dynamic Client Registration
support from the IdP.  ContextForge acts as an OAuth 2.0 Authorization
Server for the client while proxying to the real IdP behind the scenes.

Implements RFC 6749 (OAuth 2.0), RFC 7636 (PKCE), RFC 7591 (DCR),
and RFC 8414 (Authorization Server Metadata).

Flow:
    1. Resource metadata (RFC 9728) → ContextForge as ``authorization_server``
    2. Auth server metadata (RFC 8414) → ContextForge endpoints
    3. DCR (RFC 7591) → returns pre-configured ``client_id``
    4. ``/authorize`` → redirects to external IdP (Entra)
    5. IdP callback → ContextForge validates, issues an authorization code
    6. ``/token`` → exchanges code for a ContextForge-signed JWT
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.db import Server as DbServer, get_db
from mcpgateway.services.encryption_service import decrypt_oauth_config_for_runtime
from mcpgateway.utils.create_jwt_token import create_jwt_token
from mcpgateway.utils.log_sanitizer import sanitize_for_log

logger = logging.getLogger(__name__)

mcp_oauth_router = APIRouter(prefix="/oauth", tags=["MCP OAuth"])

# ---------------------------------------------------------------------------
# Encrypted state — multi-pod safe (no shared storage needed).
# Session and auth-code data are encrypted with Fernet using the
# application's auth_secret.  The encrypted blob travels in the OAuth
# ``state`` parameter or the authorization code itself.
# ---------------------------------------------------------------------------

_SESSION_TTL = 600  # 10 minutes
_CODE_TTL = 300  # 5 minutes
_OIDC_CACHE_TTL = 3600  # 1 hour

# OIDC metadata discovery cache (safe as in-memory — read-only / idempotent)
_oidc_cache: Dict[str, Dict[str, Any]] = {}


def _get_fernet() -> Fernet:
    """Derive a Fernet key from the application secret."""
    secret = settings.jwt_secret_key.get_secret_value() if hasattr(settings.jwt_secret_key, "get_secret_value") else str(settings.jwt_secret_key)
    # Fernet requires a 32-byte url-safe base64-encoded key
    key_bytes = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def _encrypt_state(data: Dict[str, Any]) -> str:
    """Encrypt session data into a URL-safe token."""
    data["_ts"] = time.time()  # wall-clock for cross-pod TTL
    plaintext = json.dumps(data, separators=(",", ":")).encode()
    return _get_fernet().encrypt(plaintext).decode("ascii")


def _decrypt_state(token: str, ttl: int) -> Dict[str, Any]:
    """Decrypt and validate an encrypted state token.

    Raises HTTPException if invalid or expired.
    """
    try:
        plaintext = _get_fernet().decrypt(token.encode("ascii"))
        data = json.loads(plaintext)
    except (InvalidToken, json.JSONDecodeError, Exception):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    ts = data.get("_ts", 0)
    if time.time() - ts > ttl:
        raise HTTPException(status_code=400, detail="OAuth session expired")

    return data


# ---------------------------------------------------------------------------
# OIDC metadata discovery (cached)
# ---------------------------------------------------------------------------


async def _discover_oidc_metadata(issuer: str) -> Dict[str, Any]:
    """Fetch and cache OIDC metadata from the authorization server."""
    cached = _oidc_cache.get(issuer)
    if cached and (time.time() - cached.get("_ts", 0)) < _OIDC_CACHE_TTL:
        return cached["metadata"]

    oidc_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(oidc_url)
        resp.raise_for_status()
        metadata = resp.json()

    _oidc_cache[issuer] = {"metadata": metadata, "_ts": time.time()}

    return metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_server_oauth_config(db: Session, server_id: str) -> tuple[DbServer, Dict[str, Any]]:
    """Load virtual server, validate and decrypt MCP OAuth proxy config."""
    server = db.get(DbServer, server_id)
    if not server or not server.enabled:
        raise HTTPException(status_code=404, detail="Server not found")

    oauth_config = getattr(server, "oauth_config", None) or {}
    if not oauth_config.get("client_id"):
        raise HTTPException(
            status_code=404,
            detail="MCP OAuth proxy not configured for this server (missing client_id in oauth_config)",
        )

    # Decrypt secrets (client_secret is encrypted at rest)
    oauth_config = await decrypt_oauth_config_for_runtime(oauth_config)

    return server, oauth_config


def _s256(verifier: str) -> str:
    """Compute S256 code challenge from verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class DCRRequest(BaseModel):
    """RFC 7591 Dynamic Client Registration request (subset)."""

    redirect_uris: List[str] = Field(default_factory=list)
    client_name: Optional[str] = None
    grant_types: List[str] = Field(default_factory=lambda: ["authorization_code"])
    response_types: List[str] = Field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: str = "none"


class DCRResponse(BaseModel):
    """RFC 7591 Dynamic Client Registration response."""

    client_id: str
    client_id_issued_at: int = 0
    redirect_uris: List[str] = Field(default_factory=list)
    grant_types: List[str] = Field(default_factory=lambda: ["authorization_code"])
    response_types: List[str] = Field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: str = "none"


class TokenRequest(BaseModel):
    """OAuth 2.0 Token Exchange request."""

    grant_type: str
    code: str
    redirect_uri: str
    client_id: str
    code_verifier: Optional[str] = None


class TokenResponse(BaseModel):
    """OAuth 2.0 Token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(default=604800)


# ---------------------------------------------------------------------------
# 1. DCR — Dynamic Client Registration
# ---------------------------------------------------------------------------


@mcp_oauth_router.post("/register/{server_id}")
async def register_client(
    server_id: str,
    body: DCRRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """RFC 7591 DCR: return pre-configured client credentials.

    MCP clients call this to "register" — we return the pre-configured
    Entra app ``client_id`` from the virtual server's ``oauth_config``.
    No actual registration happens.
    """
    _, oauth_config = await _get_server_oauth_config(db, server_id)

    client_id = oauth_config["client_id"]
    response = DCRResponse(
        client_id=client_id,
        redirect_uris=body.redirect_uris,
    )

    logger.info("MCP OAuth DCR: returned client_id for server %s", sanitize_for_log(server_id))
    return JSONResponse(content=response.model_dump(), status_code=201)


# ---------------------------------------------------------------------------
# 2. Authorize — redirect user to external IdP
# ---------------------------------------------------------------------------


@mcp_oauth_router.get("/authorize/servers/{server_id}")
async def authorize(
    server_id: str,
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    state: Optional[str] = None,
    scope: Optional[str] = None,
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """OAuth 2.0 Authorization endpoint.

    Validates parameters, stores session state, and redirects the user
    to the external IdP (e.g. Entra).
    """
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only response_type=code is supported")

    _, oauth_config = await _get_server_oauth_config(db, server_id)

    # Validate client_id matches configured value
    if client_id != oauth_config["client_id"]:
        raise HTTPException(status_code=400, detail="Invalid client_id")

    # Discover IdP endpoints
    auth_server = oauth_config.get("authorization_server") or oauth_config.get("authorization_servers", [None])[0]
    if not auth_server:
        raise HTTPException(status_code=500, detail="authorization_server not configured")

    idp_metadata = await _discover_oidc_metadata(auth_server)
    idp_authorize_url = idp_metadata.get("authorization_endpoint")
    if not idp_authorize_url:
        raise HTTPException(status_code=500, detail="IdP authorization_endpoint not found")

    # Generate internal state for CF ↔ IdP leg
    # The state carries the encrypted session data — no server-side storage.
    # Generate PKCE for CF → IdP leg
    idp_code_verifier = secrets.token_urlsafe(64)
    idp_code_challenge = _s256(idp_code_verifier)

    # Generate nonce for OIDC
    nonce = secrets.token_urlsafe(16)

    # Build CF callback URL
    base_url = str(request.base_url).rstrip("/")
    # Respect X-Forwarded-* headers for reverse proxy
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if forwarded_proto and forwarded_host:
        base_url = f"{forwarded_proto}://{forwarded_host}"
    root_path = request.scope.get("root_path", "").rstrip("/")
    cf_callback_url = f"{base_url}{root_path}/oauth/callback/servers/{server_id}"

    # Encrypt session data into state
    session_data = {
        "sid": server_id,
        "cid": client_id,
        "ru": redirect_uri,
        "cs": state,
        "cc": code_challenge,
        "ccm": code_challenge_method,
        "icv": idp_code_verifier,
        "n": nonce,
        "cb": cf_callback_url,
    }

    internal_state = _encrypt_state(session_data)

    # Build IdP authorize URL
    scopes = oauth_config.get("scopes") or oauth_config.get("scopes_supported") or ["openid", "profile", "email"]
    idp_params = {
        "client_id": oauth_config["client_id"],
        "response_type": "code",
        "redirect_uri": cf_callback_url,
        "state": internal_state,
        "scope": " ".join(scopes) if isinstance(scopes, list) else scopes,
        "code_challenge": idp_code_challenge,
        "code_challenge_method": "S256",
        "nonce": nonce,
    }

    idp_auth_url = f"{idp_authorize_url}?{urllib.parse.urlencode(idp_params)}"
    logger.info("MCP OAuth: redirecting user to IdP for server %s", sanitize_for_log(server_id))
    return RedirectResponse(url=idp_auth_url, status_code=302)


# ---------------------------------------------------------------------------
# 3. Callback — handle IdP redirect
# ---------------------------------------------------------------------------


@mcp_oauth_router.get("/callback/servers/{server_id}")
async def callback(
    server_id: str,
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> RedirectResponse:
    """Handle the IdP callback after user authentication.

    Exchanges the IdP authorization code for tokens, authenticates
    the user in ContextForge, generates a CF authorization code,
    and redirects back to the MCP client (VS Code).
    """
    if error:
        logger.warning("MCP OAuth callback error from IdP: %s — %s", error, sanitize_for_log(error_description or ""))
        raise HTTPException(status_code=400, detail=f"IdP error: {error}")

    # Decrypt session from state (no server-side storage)
    session = _decrypt_state(state, _SESSION_TTL)

    if session.get("sid") != server_id:
        raise HTTPException(status_code=400, detail="Server ID mismatch")

    _, oauth_config = await _get_server_oauth_config(db, server_id)

    # Discover IdP token endpoint
    auth_server = oauth_config.get("authorization_server") or oauth_config.get("authorization_servers", [None])[0]
    idp_metadata = await _discover_oidc_metadata(auth_server)
    idp_token_url = idp_metadata.get("token_endpoint")
    if not idp_token_url:
        raise HTTPException(status_code=500, detail="IdP token_endpoint not found")

    # Exchange code with IdP
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": session["cb"],
        "client_id": oauth_config["client_id"],
        "code_verifier": session["icv"],
    }

    # Add client_secret if configured (confidential client)
    client_secret = oauth_config.get("client_secret")
    if client_secret:
        token_payload["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(idp_token_url, data=token_payload)

    if token_resp.status_code != 200:
        logger.error(
            "MCP OAuth: IdP token exchange failed: %s %s",
            token_resp.status_code,
            sanitize_for_log(token_resp.text[:200]),
        )
        raise HTTPException(status_code=502, detail="IdP token exchange failed")

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    id_token_raw = token_data.get("id_token")

    if not access_token:
        raise HTTPException(status_code=502, detail="IdP did not return access_token")

    # Extract user info from id_token (without full cryptographic verification
    # since we just received it directly from the IdP token endpoint over TLS)
    user_info = _extract_user_from_id_token(id_token_raw) if id_token_raw else None

    # Fallback: fetch userinfo endpoint
    if not user_info or not user_info.get("email"):
        userinfo_url = idp_metadata.get("userinfo_endpoint")
        if userinfo_url:
            async with httpx.AsyncClient(timeout=15) as client:
                ui_resp = await client.get(
                    userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if ui_resp.status_code == 200:
                    ui_data = ui_resp.json()
                    user_info = user_info or {}
                    user_info["email"] = ui_data.get("email") or ui_data.get("preferred_username") or ui_data.get("upn")
                    user_info["full_name"] = ui_data.get("name") or ui_data.get("display_name")

    if not user_info or not user_info.get("email"):
        raise HTTPException(status_code=502, detail="Could not determine user email from IdP")

    # Authenticate or create user in ContextForge (reuse SSO logic)
    cf_access_token = await _authenticate_user(db, user_info)
    if not cf_access_token:
        raise HTTPException(status_code=403, detail="User authentication failed")

    # Generate CF authorization code (encrypted — no server-side storage)
    code_data = {
        "at": cf_access_token,
        "ru": session["ru"],
        "cid": session["cid"],
        "cc": session["cc"],
        "ccm": session["ccm"],
    }
    cf_code = _encrypt_state(code_data)

    # Redirect to MCP client with authorization code
    redirect_params = {"code": cf_code}
    if session.get("cs"):
        redirect_params["state"] = session["cs"]

    redirect_url = f"{session['ru']}?{urllib.parse.urlencode(redirect_params)}"
    logger.info("MCP OAuth: redirecting to client callback for user %s", sanitize_for_log(user_info["email"]))
    return RedirectResponse(url=redirect_url, status_code=302)


# ---------------------------------------------------------------------------
# 4. Token — exchange CF authorization code for JWT
# ---------------------------------------------------------------------------


@mcp_oauth_router.post("/token/servers/{server_id}")
async def token_exchange(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """OAuth 2.0 Token endpoint.

    Exchanges a ContextForge authorization code for a ContextForge JWT.
    Validates PKCE ``code_verifier`` against the stored ``code_challenge``.
    """
    # Parse form body (OAuth 2.0 token endpoint uses application/x-www-form-urlencoded)
    form = await request.form()
    grant_type = form.get("grant_type")
    code = form.get("code")
    redirect_uri = form.get("redirect_uri")
    client_id = form.get("client_id")
    code_verifier = form.get("code_verifier")

    if grant_type != "authorization_code":
        return JSONResponse(
            content={"error": "unsupported_grant_type"},
            status_code=400,
        )

    if not code:
        return JSONResponse(content={"error": "invalid_request", "error_description": "Missing code"}, status_code=400)

    # Decrypt authorization code (no server-side storage)
    try:
        code_data = _decrypt_state(str(code), _CODE_TTL)
    except HTTPException:
        return JSONResponse(content={"error": "invalid_grant", "error_description": "Invalid or expired code"}, status_code=400)

    # Validate redirect_uri matches
    if redirect_uri and redirect_uri != code_data.get("ru"):
        return JSONResponse(content={"error": "invalid_grant", "error_description": "redirect_uri mismatch"}, status_code=400)

    # Validate client_id matches
    if client_id and client_id != code_data.get("cid"):
        return JSONResponse(content={"error": "invalid_grant", "error_description": "client_id mismatch"}, status_code=400)

    # Validate PKCE
    if code_data.get("cc"):
        if not code_verifier:
            return JSONResponse(
                content={"error": "invalid_grant", "error_description": "code_verifier required"},
                status_code=400,
            )
        method = code_data.get("ccm", "S256")
        if method == "S256":
            computed = _s256(str(code_verifier))
        else:
            computed = str(code_verifier)  # plain method

        if computed != code_data["cc"]:
            return JSONResponse(
                content={"error": "invalid_grant", "error_description": "PKCE verification failed"},
                status_code=400,
            )

    access_token = code_data["at"]
    response = TokenResponse(
        access_token=access_token,
        expires_in=settings.token_expiry * 60 if hasattr(settings, "token_expiry") else 604800,
    )

    logger.info("MCP OAuth: issued access token for server %s", sanitize_for_log(server_id))
    return JSONResponse(content=response.model_dump())


# ---------------------------------------------------------------------------
# User authentication helper
# ---------------------------------------------------------------------------


def _extract_user_from_id_token(id_token: str) -> Optional[Dict[str, Any]]:
    """Extract claims from an ID token without cryptographic verification.

    Safe because we received the token directly from the IdP token endpoint
    over a TLS-protected channel (back-channel).
    """
    import base64
    import json

    try:
        parts = id_token.split(".")
        if len(parts) != 3:
            return None
        # Decode payload (part 1)
        payload = parts[1]
        # Add padding
        payload += "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        return {
            "email": claims.get("email") or claims.get("preferred_username") or claims.get("upn"),
            "full_name": claims.get("name"),
            "sub": claims.get("sub"),
            "groups": claims.get("groups", []),
        }
    except Exception:
        logger.debug("Failed to decode id_token claims", exc_info=True)
        return None


async def _authenticate_user(db: Session, user_info: Dict[str, Any]) -> Optional[str]:
    """Authenticate (or create) a user and return a ContextForge JWT.

    Reuses the SSO service's user management if available, falling back
    to direct JWT creation for known users.
    """
    email = str(user_info.get("email", "")).strip().lower()
    if not email:
        return None

    full_name = user_info.get("full_name") or email

    # Try SSO service if available
    try:
        from mcpgateway.services.sso_service import SSOService

        sso_service = SSOService(db)
        sso_user_info = {
            "email": email,
            "full_name": full_name,
            "provider": "entra",
            "groups": user_info.get("groups", []),
            "email_verified": True,
        }
        token = await sso_service.authenticate_or_create_user(sso_user_info)
        if token:
            return token
    except Exception:
        logger.debug("SSO service not available, falling back to direct auth", exc_info=True)

    # Fallback: look up user directly and create JWT
    try:
        from mcpgateway.db import User as DbUser

        user = db.query(DbUser).filter(DbUser.email == email).first()
        if not user:
            logger.warning("MCP OAuth: user %s not found and SSO auto-create not available", sanitize_for_log(email))
            return None

        token_data = {
            "sub": email,
            "email": email,
            "full_name": full_name,
            "auth_provider": "mcp_oauth",
            "user": {
                "email": email,
                "full_name": full_name,
                "is_admin": bool(user.is_admin),
                "auth_provider": "mcp_oauth",
            },
            "token_use": "session",
            "scopes": {
                "server_id": None,
                "permissions": ["*"] if user.is_admin else [],
                "ip_restrictions": [],
                "time_restrictions": {},
            },
        }
        return await create_jwt_token(token_data)
    except Exception:
        logger.exception("Failed to create JWT for MCP OAuth user %s", sanitize_for_log(email))
        return None
