# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_jwt_claims_extraction.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ioannis Ioannou

Tests for JWT Claims Extraction Plugin.
"""

# Standard
from typing import Any

# Third-Party
import jwt
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
)
from mcpgateway.plugins.framework.hooks.http import (
    HttpAuthResolveUserPayload,
    HttpHeaderPayload,
)
from plugins.jwt_claims_extraction.jwt_claims_extraction import JwtClaimsExtractionPlugin


@pytest.fixture
def plugin() -> JwtClaimsExtractionPlugin:
    """Create plugin instance with default config."""
    config = PluginConfig(
        name="jwt_claims_extraction",
        version="1.0.0",
        kind="plugins.jwt_claims_extraction.jwt_claims_extraction.JwtClaimsExtractionPlugin",
        hooks=["http_auth_resolve_user"],
        mode="permissive",
        priority=10,
        config={"context_key": "jwt_claims"},
    )
    return JwtClaimsExtractionPlugin(config)


@pytest.fixture
def sample_claims() -> dict[str, Any]:
    """Standard JWT claims payload for tests."""
    return {
        "sub": "user123",
        "email": "user@example.com",
        "roles": ["developer", "admin"],
        "permissions": ["tools.read", "tools.invoke"],
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
    }


@pytest.fixture
def sample_jwt_token(sample_claims: dict[str, Any]) -> str:
    """Create a sample JWT token."""
    return jwt.encode(sample_claims, "secret", algorithm="HS256")


def _make_context(request_id: str = "test-123") -> PluginContext:
    """Create a PluginContext with a fresh GlobalContext."""
    return PluginContext(global_context=GlobalContext(request_id=request_id))


class TestJwtClaimsExtractionPlugin:
    """Test JWT claims extraction plugin."""

    @pytest.mark.asyncio
    async def test_extract_claims_from_credentials(self, plugin: JwtClaimsExtractionPlugin, sample_jwt_token: str) -> None:
        """Test extracting claims from Bearer credentials."""
        payload = HttpAuthResolveUserPayload(
            credentials={"scheme": "Bearer", "credentials": sample_jwt_token},
            headers=HttpHeaderPayload(root={}),
        )
        ctx = _make_context("test-creds")

        result = await plugin.http_auth_resolve_user(payload, ctx)

        assert result.continue_processing is True
        claims = ctx.global_context.state["jwt_claims"]
        assert claims["sub"] == "user123"
        assert claims["email"] == "user@example.com"
        assert "developer" in claims["roles"]
        assert "tools.read" in claims["permissions"]
        assert result.metadata["jwt_claims_extracted"] is True
        assert result.metadata["claims_count"] == 6

    @pytest.mark.asyncio
    async def test_extract_claims_from_authorization_header(self, plugin: JwtClaimsExtractionPlugin, sample_jwt_token: str) -> None:
        """Test extracting claims from Authorization header fallback."""
        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=HttpHeaderPayload(root={"Authorization": f"Bearer {sample_jwt_token}"}),
        )
        ctx = _make_context("test-header")

        result = await plugin.http_auth_resolve_user(payload, ctx)

        assert result.continue_processing is True
        assert ctx.global_context.state["jwt_claims"]["sub"] == "user123"

    @pytest.mark.asyncio
    async def test_no_token_present(self, plugin: JwtClaimsExtractionPlugin) -> None:
        """Test behavior when no JWT token is present."""
        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=HttpHeaderPayload(root={}),
        )
        ctx = _make_context("test-empty")

        result = await plugin.http_auth_resolve_user(payload, ctx)

        assert result.continue_processing is True
        assert "jwt_claims" not in ctx.global_context.state

    @pytest.mark.asyncio
    async def test_extract_rfc9396_authorization_details(self, plugin: JwtClaimsExtractionPlugin) -> None:
        """Test extracting RFC 9396 authorization_details."""
        token = jwt.encode(
            {
                "sub": "user123",
                "authorization_details": [
                    {
                        "type": "tool_invocation",
                        "actions": ["invoke"],
                        "locations": ["db-query", "api-call"],
                    }
                ],
            },
            "secret",
            algorithm="HS256",
        )
        payload = HttpAuthResolveUserPayload(
            credentials={"scheme": "Bearer", "credentials": token},
            headers=HttpHeaderPayload(root={}),
        )
        ctx = _make_context("test-rfc9396")

        await plugin.http_auth_resolve_user(payload, ctx)

        claims = ctx.global_context.state["jwt_claims"]
        assert "authorization_details" in claims
        assert claims["authorization_details"][0]["type"] == "tool_invocation"

    @pytest.mark.asyncio
    async def test_malformed_token_error_handling(self, plugin: JwtClaimsExtractionPlugin) -> None:
        """Test error handling with malformed token."""
        payload = HttpAuthResolveUserPayload(
            credentials={"scheme": "Bearer", "credentials": "not-a-valid-jwt"},
            headers=HttpHeaderPayload(root={}),
        )
        ctx = _make_context("test-error")

        result = await plugin.http_auth_resolve_user(payload, ctx)

        assert result.continue_processing is True
        assert result.metadata["jwt_claims_extracted"] is False
        assert "jwt_claims" not in ctx.global_context.state

    @pytest.mark.asyncio
    async def test_ignores_non_bearer_scheme(self, plugin: JwtClaimsExtractionPlugin, sample_jwt_token: str) -> None:
        """Test that non-Bearer scheme credentials are ignored."""
        payload = HttpAuthResolveUserPayload(
            credentials={"scheme": "Basic", "credentials": sample_jwt_token},
            headers=HttpHeaderPayload(root={}),
        )
        ctx = _make_context("test-basic")

        result = await plugin.http_auth_resolve_user(payload, ctx)

        assert result.continue_processing is True
        assert "jwt_claims" not in ctx.global_context.state

    @pytest.mark.asyncio
    async def test_custom_context_key(self, sample_jwt_token: str) -> None:
        """Test using a custom context key via config."""
        config = PluginConfig(
            name="jwt_claims_extraction",
            version="1.0.0",
            kind="plugins.jwt_claims_extraction.jwt_claims_extraction.JwtClaimsExtractionPlugin",
            hooks=["http_auth_resolve_user"],
            mode="permissive",
            priority=10,
            config={"context_key": "custom_claims"},
        )
        custom_plugin = JwtClaimsExtractionPlugin(config)

        payload = HttpAuthResolveUserPayload(
            credentials={"scheme": "Bearer", "credentials": sample_jwt_token},
            headers=HttpHeaderPayload(root={}),
        )
        ctx = _make_context("test-custom-key")

        await custom_plugin.http_auth_resolve_user(payload, ctx)

        assert "custom_claims" in ctx.global_context.state
        assert ctx.global_context.state["custom_claims"]["sub"] == "user123"
