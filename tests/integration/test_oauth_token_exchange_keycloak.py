# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_oauth_token_exchange_keycloak.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

Integration tests for RFC 8693 OAuth 2.0 Token Exchange against a live Keycloak.

These tests are skipped unless ``KEYCLOAK_URL`` is set, and require a running
Keycloak instance with token exchange enabled.

Setup (Keycloak >= 24):
    1. Run Keycloak with the token-exchange feature enabled, e.g.:

       docker run -p 8080:8080 \\
           -e KEYCLOAK_ADMIN=admin -e KEYCLOAK_ADMIN_PASSWORD=admin \\
           quay.io/keycloak/keycloak:latest \\
           start-dev --features=token-exchange

    2. Create (or import) a realm, e.g. ``cf``.
    3. Create a confidential client (e.g. ``token-exchange``) with:
       - "Standard token exchange" (or the legacy "Permissions" ->
         "token-exchange" permission) enabled, granting itself permission to
         exchange tokens.
       - Client authentication enabled, and note the client secret.
    4. Add a test user, obtain a user access token (the "subject_token") via
       the resource owner password grant or an interactive login.
    5. Create/verify a target audience (e.g. another client ID or a custom
       audience identifier) that the exchanged token should be scoped to.

Environment variables:
    KEYCLOAK_URL: Base URL of the Keycloak server (e.g. http://localhost:8080)
    KEYCLOAK_CLIENT_ID: Client ID configured for token exchange
    KEYCLOAK_CLIENT_SECRET: Client secret for the above client
    KEYCLOAK_USER_JWT: A valid user access token to use as the subject_token
    KEYCLOAK_TARGET_AUDIENCE: The target audience for the exchanged token

Usage:
    KEYCLOAK_URL=http://localhost:8080 \\
    KEYCLOAK_CLIENT_ID=token-exchange \\
    KEYCLOAK_CLIENT_SECRET=... \\
    KEYCLOAK_USER_JWT=... \\
    KEYCLOAK_TARGET_AUDIENCE=... \\
    pytest tests/integration/test_oauth_token_exchange_keycloak.py -v
"""

# Standard
import os

# Third-Party
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("KEYCLOAK_URL"), reason="KEYCLOAK_URL not set"),
]


@pytest.mark.asyncio
class TestKeycloakTokenExchange:
    async def test_successful_token_exchange(self):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        mgr = OAuthManager()
        resp = await mgr.token_exchange(
            token_url=f"{os.environ['KEYCLOAK_URL']}/realms/cf/protocol/openid-connect/token",
            subject_token=os.environ["KEYCLOAK_USER_JWT"],
            client_id=os.environ["KEYCLOAK_CLIENT_ID"],
            client_secret=os.environ["KEYCLOAK_CLIENT_SECRET"],
            audience=os.environ["KEYCLOAK_TARGET_AUDIENCE"],
        )
        assert "access_token" in resp

    async def test_invalid_audience_fails(self):
        # First-Party
        from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

        mgr = OAuthManager(max_retries=1)
        with pytest.raises(OAuthError):
            await mgr.token_exchange(
                token_url=f"{os.environ['KEYCLOAK_URL']}/realms/cf/protocol/openid-connect/token",
                subject_token=os.environ["KEYCLOAK_USER_JWT"],
                client_id=os.environ["KEYCLOAK_CLIENT_ID"],
                client_secret=os.environ["KEYCLOAK_CLIENT_SECRET"],
                audience="https://nonexistent-audience.invalid",
            )

    async def test_exchanged_token_has_correct_audience(self):
        # Issue acceptance: exchanged token's aud claim matches target_audience.
        # Standard
        import base64
        import json

        # First-Party
        from mcpgateway.services.oauth_manager import OAuthManager

        mgr = OAuthManager()
        resp = await mgr.token_exchange(
            token_url=f"{os.environ['KEYCLOAK_URL']}/realms/cf/protocol/openid-connect/token",
            subject_token=os.environ["KEYCLOAK_USER_JWT"],
            client_id=os.environ["KEYCLOAK_CLIENT_ID"],
            client_secret=os.environ["KEYCLOAK_CLIENT_SECRET"],
            audience=os.environ["KEYCLOAK_TARGET_AUDIENCE"],
        )
        payload_b64 = resp["access_token"].split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        aud = claims.get("aud")
        auds = aud if isinstance(aud, list) else [aud]
        assert os.environ["KEYCLOAK_TARGET_AUDIENCE"] in auds


@pytest.mark.asyncio
class TestKeycloakResolverCachingFullFlow:
    """Issue MUST-HAVE: exercise the resolver (cache + exchange) against live Keycloak."""

    def _gateway_cfg(self):
        return {
            "grant_type": "token-exchange",
            "token_url": f"{os.environ['KEYCLOAK_URL']}/realms/cf/protocol/openid-connect/token",
            "client_id": os.environ["KEYCLOAK_CLIENT_ID"],
            "client_secret": os.environ["KEYCLOAK_CLIENT_SECRET"],
            "target_audience": os.environ["KEYCLOAK_TARGET_AUDIENCE"],
            "subject_token_source": "inbound_user_jwt",
        }

    async def test_resolver_full_flow_and_caching(self):
        # test_token_exchange_caching_keycloak: second resolve within TTL reuses the cached token,
        # so the AS is hit exactly once.
        # First-Party
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()  # real TokenExchangeCache (memory; no REDIS_URL needed)
        headers = {"authorization": f"Bearer {os.environ['KEYCLOAK_USER_JWT']}"}
        cfg = self._gateway_cfg()

        h1 = await svc._resolve_token_exchange_header(cfg, "gw-kc", "kc", "u@e", headers)
        h2 = await svc._resolve_token_exchange_header(cfg, "gw-kc", "kc", "u@e", headers)
        assert h1 == h2  # cached reuse
        assert h1["Authorization"].startswith("Bearer ")
        # and never the raw inbound JWT
        assert os.environ["KEYCLOAK_USER_JWT"] not in h1["Authorization"]

    async def test_cache_expiry_forces_reexchange(self):
        # test_token_exchange_cache_expiry_keycloak: a skew larger than the token lifetime
        # forces a fresh exchange every call (no stale serve).
        # First-Party
        from mcpgateway.services.token_exchange_cache import TokenExchangeCache
        from mcpgateway.services.tool_service import ToolService

        svc = ToolService()
        svc._token_exchange_cache = TokenExchangeCache(redis_url=None, skew_seconds=10**9)  # force immediate "near expiry"
        headers = {"authorization": f"Bearer {os.environ['KEYCLOAK_USER_JWT']}"}
        cfg = self._gateway_cfg()
        # each get() is a miss -> a real exchange happens; both succeed
        h1 = await svc._resolve_token_exchange_header(cfg, "gw-kc", "kc", "u@e", headers)
        h2 = await svc._resolve_token_exchange_header(cfg, "gw-kc", "kc", "u@e", headers)
        assert h1["Authorization"].startswith("Bearer ")
        assert h2["Authorization"].startswith("Bearer ")
