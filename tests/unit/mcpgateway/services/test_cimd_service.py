# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_cimd_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the Client ID Metadata Document (CIMD) service and its public endpoint.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.services.cimd_service import CimdService

ISSUER = "https://as.example.com"


def _settings(**overrides):
    values = {
        "cimd_enabled": True,
        "cimd_client_name": "ContextForge",
        "well_known_enabled": True,
        "well_known_cache_max_age": 3600,
        "app_domain": "https://gw.example.com/",
        "app_root_path": "",
        "dcr_allowed_issuers": [],
        "cimd_client_metadata_url": None,
        "cimd_token_endpoint_auth_method": "none",
        "cimd_document_cache_seconds": 3600,
        "jwt_algorithm": "RS256",
        "jwt_public_key_path": "",
        "jwt_private_key_path": "",
        "jwt_previous_public_key_path": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _service(settings, metadata=None, error=None):
    dcr = MagicMock()
    dcr.discover_as_metadata = AsyncMock(return_value=metadata, side_effect=error)
    with patch("mcpgateway.services.cimd_service.get_settings", return_value=settings):
        return CimdService(dcr)


class TestBuildDocument:
    """The published document is derived only from server-side configuration."""

    def test_document_fields(self):
        service = _service(_settings(app_root_path="/forge"))

        doc = service.build_document()

        assert doc["client_id"] == "https://gw.example.com/forge/oauth/client-metadata.json"
        assert doc["redirect_uris"] == ["https://gw.example.com/forge/oauth/callback"]
        assert doc["token_endpoint_auth_method"] == "none"
        assert doc["client_name"] == "ContextForge"
        assert "client_secret" not in doc

    def test_client_id_equals_document_client_id(self):
        service = _service(_settings())

        assert service.build_document()["client_id"] == service.client_id

    def test_client_id_override(self):
        override_url = "https://public.proxy.com/oauth/client-metadata.json"
        service = _service(_settings(cimd_client_metadata_url=override_url))

        assert service.client_id == override_url
        assert service.redirect_uri == "https://public.proxy.com/oauth/callback"
        assert service.jwks_uri == "https://public.proxy.com/oauth/client-metadata/jwks.json"

        doc = service.build_document()
        assert doc["client_id"] == override_url
        assert doc["redirect_uris"] == ["https://public.proxy.com/oauth/callback"]

    def test_private_key_jwt_includes_jwks_uri(self):
        service = _service(_settings(cimd_token_endpoint_auth_method="private_key_jwt"))
        doc = service.build_document()
        assert doc["token_endpoint_auth_method"] == "private_key_jwt"
        assert doc["jwks_uri"] == "https://gw.example.com/oauth/client-metadata/jwks.json"


class TestIsApplicable:
    """CIMD applies only when every precondition holds and the AS advertises support."""

    @pytest.mark.asyncio
    async def test_supported(self):
        service = _service(_settings(), {"client_id_metadata_document_supported": True})

        assert await service.is_applicable(ISSUER, service.redirect_uri) is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("metadata", [{}, {"client_id_metadata_document_supported": False}, {"client_id_metadata_document_supported": "true"}])
    async def test_unsupported_metadata(self, metadata):
        service = _service(_settings(), metadata)

        assert await service.is_applicable(ISSUER, service.redirect_uri) is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "overrides",
        [{"cimd_enabled": False}, {"app_domain": "http://gw.example.com"}, {"dcr_allowed_issuers": ["https://other.example.com"]}],
    )
    async def test_preconditions_skip_discovery(self, overrides):
        service = _service(_settings(**overrides), {"client_id_metadata_document_supported": True})

        assert await service.is_applicable(ISSUER, service.redirect_uri) is False
        service._dcr_service.discover_as_metadata.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_redirect_uri_mismatch(self, caplog):
        service = _service(_settings(), {"client_id_metadata_document_supported": True})

        with caplog.at_level("INFO", logger="mcpgateway.services.cimd_service"):
            assert await service.is_applicable(ISSUER, "https://evil.example.net/oauth/callback") is False

        assert "effective redirect_uri" in caplog.text

    @pytest.mark.asyncio
    async def test_allowlisted_issuer(self):
        service = _service(_settings(dcr_allowed_issuers=[f"{ISSUER}/"]), {"client_id_metadata_document_supported": True})

        assert await service.is_applicable(ISSUER, service.redirect_uri) is True

    @pytest.mark.asyncio
    async def test_discovery_failure_falls_back(self):
        service = _service(_settings(), error=RuntimeError("boom"))

        assert await service.is_applicable(ISSUER, service.redirect_uri) is False


class TestClientMetadataEndpoint:
    """GET /oauth/client-metadata.json is public and gated by configuration."""

    @pytest.mark.asyncio
    async def test_serves_document(self):
        # First-Party
        from mcpgateway.routers import well_known

        cfg = _settings()
        with patch.object(well_known, "settings", cfg), patch("mcpgateway.services.cimd_service.get_settings", return_value=cfg):
            response = await well_known.get_oauth_client_metadata()

        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=3600"
        assert b"https://gw.example.com/oauth/client-metadata.json" in response.body

    @pytest.mark.asyncio
    async def test_disabled_returns_404(self):
        # First-Party
        from mcpgateway.routers import well_known

        with patch.object(well_known, "settings", _settings(cimd_enabled=False)):
            with pytest.raises(HTTPException) as exc_info:
                await well_known.get_oauth_client_metadata()

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_jwks_serves_unauthenticated(self, app):
        # Third-Party
        from fastapi.testclient import TestClient

        cfg = _settings()
        with patch("mcpgateway.routers.well_known.settings", cfg):
            response = TestClient(app).get("/oauth/client-metadata/jwks.json")
            assert response.status_code == 200
            assert "keys" in response.json()

    def test_route_requires_no_authentication(self, app):
        # Third-Party
        from fastapi.testclient import TestClient

        response = TestClient(app).get("/oauth/client-metadata.json")

        assert response.status_code == 200
        assert response.json()["token_endpoint_auth_method"] == "none"
