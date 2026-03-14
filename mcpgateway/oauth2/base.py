# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/oauth2/base.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Canonical OAuth2/OIDC helper functions for protocol operations.
"""

# Standard
from typing import Any, Dict, List, Optional, cast
from urllib.parse import urlencode

# Third-Party
import jwt

# First-Party
from mcpgateway.oauth2.exceptions import (
    OAuth2DiscoveryError,
    OAuth2TokenExchangeError,
    OAuth2TokenRefreshError,
    OAuth2TokenValidationError,
)
from mcpgateway.oauth2.models import (
    OAuth2ValidationConfig,
    RefreshTokenRequest,
    TokenExchangeRequest,
    TokenValidationResult,
)
from mcpgateway.services.http_client_service import get_http_client


def normalize_scopes(scopes: str | List[str] | None) -> List[str]:
    """Normalize OAuth scope input to a stable list."""
    if scopes is None:
        return []
    if isinstance(scopes, str):
        return [s for s in scopes.split(" ") if s]
    return [s for s in scopes if s]


def scopes_to_string(scopes: str | List[str] | None) -> str:
    """Convert scopes to RFC-compatible space-delimited string."""
    return " ".join(normalize_scopes(scopes))


def apply_scope_modifications(base_scopes: str | List[str] | None, add: Optional[List[str]] = None, remove: Optional[List[str]] = None) -> List[str]:
    """Apply additive/removal scope updates in canonical order."""
    current = set(normalize_scopes(base_scopes))
    if add:
        current.update(normalize_scopes(add))
    if remove:
        for scope in normalize_scopes(remove):
            current.discard(scope)
    return sorted(current)


def extract_claims(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract canonical claims from a token payload."""
    raw_scope = payload.get("scope")
    if raw_scope is None:
        raw_scope = payload.get("scp")
    scopes = normalize_scopes(cast(str | List[str] | None, raw_scope))
    roles = payload.get("roles") or payload.get("groups") or []
    if isinstance(roles, str):
        roles = [roles]
    return {
        "sub": payload.get("sub"),
        "iss": payload.get("iss"),
        "aud": payload.get("aud"),
        "azp": payload.get("azp"),
        "email": payload.get("email"),
        "client_id": payload.get("client_id"),
        "scope": scopes,
        "roles": roles,
        "claims": payload,
    }


class OAuth2BaseLibrary:
    """Reusable OAuth2/OIDC protocol helper methods."""

    async def discover_authorization_server_metadata(self, issuer: str, timeout_seconds: float = 30.0) -> Dict[str, Any]:
        """RFC 8414 authorization server metadata discovery."""
        normalized_issuer = issuer.rstrip("/")
        url = f"{normalized_issuer}/.well-known/oauth-authorization-server"
        client = await get_http_client()
        response = await client.get(url, timeout=timeout_seconds)
        if response.status_code != 200:
            raise OAuth2DiscoveryError(f"Authorization server metadata discovery failed for issuer {normalized_issuer} with status {response.status_code}")
        metadata = response.json()
        metadata_issuer = (metadata.get("issuer") or "").rstrip("/")
        if metadata_issuer != normalized_issuer:
            raise OAuth2DiscoveryError(f"Authorization server issuer mismatch: expected {normalized_issuer}, got {metadata.get('issuer')}")
        return metadata

    async def discover_oidc_metadata(self, issuer: str, timeout_seconds: float = 30.0) -> Dict[str, Any]:
        """OIDC discovery document retrieval."""
        normalized_issuer = issuer.rstrip("/")
        url = f"{normalized_issuer}/.well-known/openid-configuration"
        client = await get_http_client()
        response = await client.get(url, timeout=timeout_seconds)
        if response.status_code != 200:
            raise OAuth2DiscoveryError(f"OIDC metadata discovery failed for issuer {normalized_issuer} with status {response.status_code}")
        metadata = response.json()
        metadata_issuer = (metadata.get("issuer") or "").rstrip("/")
        if metadata_issuer != normalized_issuer:
            raise OAuth2DiscoveryError(f"OIDC issuer mismatch: expected {normalized_issuer}, got {metadata.get('issuer')}")
        return metadata

    async def discover_protected_resource_metadata(self, resource_base_url: str, timeout_seconds: float = 30.0) -> Dict[str, Any]:
        """RFC 9728 protected resource metadata discovery."""
        normalized = resource_base_url.rstrip("/")
        url = f"{normalized}/.well-known/oauth-protected-resource"
        client = await get_http_client()
        response = await client.get(url, timeout=timeout_seconds)
        if response.status_code != 200:
            raise OAuth2DiscoveryError(f"Protected resource metadata discovery failed for resource {normalized} with status {response.status_code}")
        return response.json()

    async def validate_token(self, token: str, config: OAuth2ValidationConfig) -> TokenValidationResult:
        """Validate token via JWKS JWT validation or introspection fallback."""
        if config.jwks_uri:
            claims = self._validate_jwt_with_jwks(token, config)
            return TokenValidationResult(active=True, claims=claims, source="jwt", scopes=normalize_scopes(cast(str | List[str] | None, claims.get("scope"))))

        if config.introspection_endpoint:
            return await self._validate_token_with_introspection(token, config)

        raise OAuth2TokenValidationError("No token validation mechanism configured. Provide jwks_uri or introspection_endpoint.")

    def _validate_jwt_with_jwks(self, token: str, config: OAuth2ValidationConfig) -> Dict[str, Any]:
        """Validate JWT access token using RFC 8414/OIDC jwks_uri."""
        try:
            jwk_client = jwt.PyJWKClient(config.jwks_uri or "")
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            options: Dict[str, Any] = {"verify_exp": config.require_exp}
            decode_kwargs: Dict[str, Any] = {"key": signing_key.key, "algorithms": list(config.algorithms), "options": options, "leeway": config.leeway_seconds}
            if config.audience:
                decode_kwargs["audience"] = config.audience
            if config.issuer:
                decode_kwargs["issuer"] = config.issuer
            return cast(Dict[str, Any], jwt.decode(token, **decode_kwargs))
        except Exception as exc:
            raise OAuth2TokenValidationError(f"JWT validation failed: {exc}") from exc

    async def _validate_token_with_introspection(self, token: str, config: OAuth2ValidationConfig) -> TokenValidationResult:
        """Validate token using RFC 7662 introspection endpoint."""
        if not config.introspection_endpoint:
            raise OAuth2TokenValidationError("Missing introspection endpoint for token introspection.")
        data = {"token": token}
        auth = None
        if config.client_id and config.client_secret:
            # Third-Party
            import httpx  # pylint: disable=import-outside-toplevel

            auth = httpx.BasicAuth(config.client_id, config.client_secret)
        client = await get_http_client()
        response = await client.post(config.introspection_endpoint, data=data, auth=auth)
        if response.status_code != 200:
            raise OAuth2TokenValidationError(f"Token introspection failed with status {response.status_code}")
        payload = response.json()
        if not payload.get("active", False):
            return TokenValidationResult(active=False, claims=payload, source="introspection", scopes=normalize_scopes(cast(str | List[str] | None, payload.get("scope"))))
        return TokenValidationResult(active=True, claims=payload, source="introspection", scopes=normalize_scopes(cast(str | List[str] | None, payload.get("scope"))))

    async def exchange_token(self, request: TokenExchangeRequest) -> Dict[str, Any]:
        """RFC 8693 token exchange helper."""
        if not request.subject_token:
            raise OAuth2TokenExchangeError("subject_token is required for token exchange.")
        data: List[tuple[str, str]] = [
            ("grant_type", "urn:ietf:params:oauth:grant-type:token-exchange"),
            ("subject_token", request.subject_token),
            ("subject_token_type", request.subject_token_type),
            ("client_id", request.client_id),
        ]
        if request.client_secret:
            data.append(("client_secret", request.client_secret))
        if request.requested_token_type:
            data.append(("requested_token_type", request.requested_token_type))
        if request.actor_token:
            data.append(("actor_token", request.actor_token))
        if request.actor_token_type:
            data.append(("actor_token_type", request.actor_token_type))
        if request.scope:
            data.append(("scope", scopes_to_string(request.scope)))
        for aud in request.audience or []:
            data.append(("audience", aud))
        for res in request.resource or []:
            data.append(("resource", res))

        client = await get_http_client()
        response = await client.post(request.token_endpoint, data=data, timeout=request.timeout_seconds)
        if response.status_code != 200:
            raise OAuth2TokenExchangeError(f"Token exchange failed with status {response.status_code}: {response.text}")
        body = response.json()
        if "access_token" not in body:
            raise OAuth2TokenExchangeError(f"Token exchange response missing access_token: {body}")
        return body

    async def refresh_token(self, request: RefreshTokenRequest) -> Dict[str, Any]:
        """RFC 6749 refresh token grant helper."""
        if not request.refresh_token:
            raise OAuth2TokenRefreshError("refresh_token is required for refresh flow.")
        data: List[tuple[str, str]] = [
            ("grant_type", "refresh_token"),
            ("refresh_token", request.refresh_token),
            ("client_id", request.client_id),
        ]
        if request.client_secret:
            data.append(("client_secret", request.client_secret))
        if request.scope:
            data.append(("scope", scopes_to_string(request.scope)))
        for res in request.resource or []:
            data.append(("resource", res))
        client = await get_http_client()
        response = await client.post(request.token_endpoint, data=data, timeout=request.timeout_seconds)
        if response.status_code != 200:
            raise OAuth2TokenRefreshError(f"Refresh token flow failed with status {response.status_code}: {response.text}")
        body = response.json()
        if "access_token" not in body:
            raise OAuth2TokenRefreshError(f"Refresh response missing access_token: {body}")
        return body

    def build_authorization_url(
        self,
        authorization_endpoint: str,
        client_id: str,
        redirect_uri: str,
        response_type: str = "code",
        scope: Optional[List[str]] = None,
        state: Optional[str] = None,
        code_challenge: Optional[str] = None,
        code_challenge_method: Optional[str] = None,
        resource: Optional[List[str]] = None,
    ) -> str:
        """Build authorization URL including RFC 8707 resource indicators."""
        params: List[tuple[str, str]] = [("response_type", response_type), ("client_id", client_id), ("redirect_uri", redirect_uri)]
        if scope:
            params.append(("scope", scopes_to_string(scope)))
        if state:
            params.append(("state", state))
        if code_challenge:
            params.append(("code_challenge", code_challenge))
        if code_challenge_method:
            params.append(("code_challenge_method", code_challenge_method))
        for res in resource or []:
            params.append(("resource", res))
        return f"{authorization_endpoint}?{urlencode(params, doseq=True)}"
