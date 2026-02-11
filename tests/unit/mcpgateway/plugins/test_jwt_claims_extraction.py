# -*- coding: utf-8 -*-
"""Tests for JWT Claims Extraction Plugin.

Location: ./tests/unit/mcpgateway/plugins/test_jwt_claims_extraction.py
"""

# Standard
import pytest

# Third-Party
import jwt

# First-Party
from mcpgateway.plugins.jwt_claims_extraction import JwtClaimsExtractionPlugin
from mcpgateway.plugins.framework.models import PluginConfig, GlobalContext, PluginContext
from mcpgateway.plugins.framework.hooks.http import (
    HttpAuthResolveUserPayload,
    HttpHeaderPayload,
)


class TestJwtClaimsExtractionPlugin:
    """Test JWT claims extraction plugin."""

    @pytest.fixture
    def plugin(self):
        """Create plugin instance."""
        config = PluginConfig(
            name="jwt_claims_extraction",
            version="1.0.0",
            kind="mcpgateway.plugins.jwt_claims_extraction.JwtClaimsExtractionPlugin",
            hooks=["http_auth_resolve_user"],
            mode="permissive",
            priority=10,
        )
        return JwtClaimsExtractionPlugin(config)

    @pytest.fixture
    def sample_jwt_token(self):
        """Create a sample JWT token."""
        payload = {
            "sub": "user123",
            "email": "user@example.com",
            "roles": ["developer", "admin"],
            "permissions": ["tools.read", "tools.invoke"],
            "iss": "mcpgateway",
            "aud": "mcpgateway-api",
        }
        return jwt.encode(payload, "secret", algorithm="HS256")

    @pytest.fixture
    def sample_payload_with_token(self, sample_jwt_token):
        """Create sample auth payload with JWT token."""
        return HttpAuthResolveUserPayload(
            credentials={"credentials": sample_jwt_token},
            headers=HttpHeaderPayload(root={}),
        )

    @pytest.mark.asyncio
    async def test_extract_claims_from_credentials(
        self, plugin, sample_payload_with_token
    ):
        """Test extracting claims from credentials."""
        # Setup global context and plugin context
        global_context = GlobalContext(request_id="test-123")
        plugin_context = PluginContext(global_context=global_context)

        # Call the handler
        result = await plugin.http_auth_resolve_user(
            sample_payload_with_token, plugin_context
        )

        # Verify claims were extracted
        assert hasattr(global_context, "metadata")
        assert "jwt_claims" in global_context.metadata

        claims = global_context.metadata["jwt_claims"]
        assert claims["sub"] == "user123"
        assert claims["email"] == "user@example.com"
        assert "developer" in claims["roles"]
        assert "tools.read" in claims["permissions"]

        # Result should be continue_processing=True (passthrough)
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_extract_claims_from_header(self, plugin, sample_jwt_token):
        """Test extracting claims from Authorization header."""
        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=HttpHeaderPayload(
                root={"Authorization": f"Bearer {sample_jwt_token}"}
            ),
        )

        global_context = GlobalContext(request_id="test-456")
        plugin_context = PluginContext(global_context=global_context)

        result = await plugin.http_auth_resolve_user(payload, plugin_context)

        # Verify claims extracted
        assert "jwt_claims" in global_context.metadata
        assert global_context.metadata["jwt_claims"]["sub"] == "user123"

    @pytest.mark.asyncio
    async def test_no_token_present(self, plugin):
        """Test behavior when no JWT token is present."""
        payload = HttpAuthResolveUserPayload(
            credentials=None,
            headers=HttpHeaderPayload(root={}),
        )

        global_context = GlobalContext(request_id="test-789")
        plugin_context = PluginContext(global_context=global_context)

        result = await plugin.http_auth_resolve_user(payload, plugin_context)

        # Should return continue_processing=True without error
        assert result.continue_processing is True

        # No claims should be stored
        if hasattr(global_context, "metadata"):
            assert "jwt_claims" not in global_context.metadata

    @pytest.mark.asyncio
    async def test_extract_rfc9396_authorization_details(self, plugin):
        """Test extracting RFC 9396 authorization_details."""
        # Create token with RFC 9396 authorization_details
        payload_data = {
            "sub": "user123",
            "authorization_details": [
                {
                    "type": "tool_invocation",
                    "actions": ["invoke"],
                    "locations": ["db-query", "api-call"],
                }
            ],
        }
        token = jwt.encode(payload_data, "secret", algorithm="HS256")

        auth_payload = HttpAuthResolveUserPayload(
            credentials={"credentials": token},
            headers=HttpHeaderPayload(root={}),
        )

        global_context = GlobalContext(request_id="test-rfc9396")
        plugin_context = PluginContext(global_context=global_context)

        result = await plugin.http_auth_resolve_user(auth_payload, plugin_context)

        # Verify RFC 9396 data extracted
        claims = global_context.metadata["jwt_claims"]
        assert "authorization_details" in claims
        assert claims["authorization_details"][0]["type"] == "tool_invocation"

    @pytest.mark.asyncio
    async def test_error_handling(self, plugin):
        """Test error handling with malformed token."""
        payload = HttpAuthResolveUserPayload(
            credentials={"credentials": "not-a-valid-jwt"},
            headers=HttpHeaderPayload(root={}),
        )

        global_context = GlobalContext(request_id="test-error")
        plugin_context = PluginContext(global_context=global_context)

        # Should not raise exception
        result = await plugin.http_auth_resolve_user(payload, plugin_context)

        # Should return continue_processing=True
        assert result.continue_processing is True
