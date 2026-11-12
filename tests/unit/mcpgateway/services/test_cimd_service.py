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
        "cimd_private_key_path": "",
        "cimd_previous_public_key_path": "",
        "cimd_key_id": "cimd-1",
        "cimd_previous_key_id": "",
        "cimd_signing_alg": "RS256",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _request(root_path=""):
    return SimpleNamespace(scope={"root_path": root_path})


def _service(settings, metadata=None, error=None, **kwargs):
    dcr = MagicMock()
    dcr.discover_as_metadata = AsyncMock(return_value=metadata, side_effect=error)
    with patch("mcpgateway.services.cimd_service.get_settings", return_value=settings):
        return CimdService(dcr, **kwargs)


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

    @pytest.mark.asyncio
    async def test_discovery_failure_warns_and_records_reason(self, caplog):
        service = _service(_settings(), error=RuntimeError("boom"))

        with caplog.at_level("WARNING", logger="mcpgateway.services.cimd_service"):
            assert await service.is_applicable(ISSUER, service.redirect_uri) is False

        assert service.skip_reason == "discovery_failed"
        assert "discovery raised RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_unadvertised_records_reason_and_metadata(self):
        metadata = {"client_id_metadata_document_supported": False}
        service = _service(_settings(), metadata)

        assert await service.is_applicable(ISSUER, service.redirect_uri) is False
        assert service.skip_reason == "not_advertised"
        assert service.as_metadata is metadata

    @pytest.mark.asyncio
    async def test_supported_keeps_metadata_for_reuse(self):
        metadata = {"client_id_metadata_document_supported": True}
        service = _service(_settings(), metadata)

        assert await service.is_applicable(ISSUER, service.redirect_uri) is True
        assert service.skip_reason is None
        assert service.as_metadata is metadata

    @pytest.mark.asyncio
    async def test_guard_skip_logs_warning(self, caplog):
        service = _service(_settings(), {"client_id_metadata_document_supported": True})

        with caplog.at_level("WARNING", logger="mcpgateway.services.cimd_service"):
            assert await service.is_applicable(ISSUER, "https://evil.example.net/oauth/callback") is False

        assert service.skip_reason == "redirect_uri_mismatch"
        assert "APP_ROOT_PATH" in caplog.text


class TestRequestRootPath:
    """The request-resolved root path drives the published URLs."""

    def test_request_root_path_overrides_setting(self):
        service = _service(_settings(), root_path="/proxy")

        assert service.client_id == "https://gw.example.com/proxy/oauth/client-metadata.json"
        assert service.redirect_uri == "https://gw.example.com/proxy/oauth/callback"

    def test_empty_request_root_path_wins_over_setting(self):
        service = _service(_settings(app_root_path="/forge"), root_path="")

        assert service.redirect_uri == "https://gw.example.com/oauth/callback"

    @pytest.mark.asyncio
    async def test_matches_router_default_redirect_uri_behind_proxy(self):
        # First-Party
        from mcpgateway.routers.oauth_router import _default_redirect_uri
        from mcpgateway.utils.paths import resolve_root_path

        request = _request("/proxy")
        cfg = _settings()
        with patch("mcpgateway.routers.oauth_router.settings", cfg), patch("mcpgateway.utils.paths.settings", cfg):
            redirect = _default_redirect_uri(request)
            service = _service(cfg, {"client_id_metadata_document_supported": True}, root_path=resolve_root_path(request))

        assert redirect == service.redirect_uri
        assert await service.is_applicable(ISSUER, redirect) is True

    def test_owns_client_id_ignores_root_path_difference(self):
        service = _service(_settings(), root_path="/proxy")

        assert service.owns_client_id("https://gw.example.com/forge/oauth/client-metadata.json") is True
        assert service.owns_client_id("https://evil.example.net/oauth/client-metadata.json") is False
        assert service.owns_client_id("https://gw.example.com/other.json") is False
        assert service.owns_client_id(None) is False


class TestClientIdOverridePath:
    """CIMD_CLIENT_METADATA_URL is limited to the served path."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://p.example.com/custom/doc.json",
            "https://p.example.com/client-metadata.json",
            "https://p.example.com/oauth/client-metadata.json?x=1",
            "https://p.example.com/oauth/client-metadata.json#f",
        ],
    )
    def test_rejects_unserved_paths(self, url):
        # First-Party
        from mcpgateway.config import Settings

        with pytest.raises(ValueError, match="oauth/client-metadata.json"):
            Settings.validate_cimd_client_metadata_url(url)

    def test_accepts_prefixed_served_path(self):
        # First-Party
        from mcpgateway.config import Settings

        url = "https://p.example.com/edge/oauth/client-metadata.json"
        assert Settings.validate_cimd_client_metadata_url(url) == url
        service = _service(_settings(cimd_client_metadata_url=url))
        assert service.redirect_uri == "https://p.example.com/edge/oauth/callback"

    def test_blank_is_unset(self):
        # First-Party
        from mcpgateway.config import Settings

        assert Settings.validate_cimd_client_metadata_url("") is None


class TestPrivateKeyJwtConfig:
    """private_key_jwt needs a dedicated key; the HS256 default never reaches CIMD."""

    def test_requires_dedicated_key(self):
        # First-Party
        from mcpgateway.config import Settings

        with pytest.raises(ValueError, match="CIMD_PRIVATE_KEY_PATH"):
            Settings(cimd_token_endpoint_auth_method="private_key_jwt", cimd_private_key_path="", jwt_algorithm="HS256")

    def test_hs256_default_with_dedicated_key_is_valid(self):
        # First-Party
        from mcpgateway.config import Settings

        cfg = Settings(cimd_token_endpoint_auth_method="private_key_jwt", cimd_private_key_path="certs/cimd/private.pem", jwt_algorithm="HS256")
        assert cfg.cimd_signing_alg == "RS256"

    def test_rejects_symmetric_signing_alg(self):
        # First-Party
        from mcpgateway.config import Settings

        with pytest.raises(ValueError):
            Settings(cimd_signing_alg="HS256")


class TestClientMetadataEndpoint:
    """GET /oauth/client-metadata.json is public and gated by configuration."""

    @pytest.mark.asyncio
    async def test_serves_document(self):
        # First-Party
        from mcpgateway.routers import well_known

        cfg = _settings()
        with patch.object(well_known, "settings", cfg), patch("mcpgateway.services.cimd_service.get_settings", return_value=cfg):
            response = await well_known.get_oauth_client_metadata(_request())

        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=3600"
        assert b"https://gw.example.com/oauth/client-metadata.json" in response.body

    @pytest.mark.asyncio
    async def test_serves_document_under_request_root_path(self):
        # First-Party
        from mcpgateway.routers import well_known

        cfg = _settings()
        with patch.object(well_known, "settings", cfg), patch("mcpgateway.services.cimd_service.get_settings", return_value=cfg), patch("mcpgateway.utils.paths.settings", cfg):
            response = await well_known.get_oauth_client_metadata(_request("/proxy"))

        assert b"https://gw.example.com/proxy/oauth/client-metadata.json" in response.body
        assert b"https://gw.example.com/proxy/oauth/callback" in response.body

    @pytest.mark.asyncio
    async def test_disabled_returns_404(self):
        # First-Party
        from mcpgateway.routers import well_known

        with patch.object(well_known, "settings", _settings(cimd_enabled=False)):
            with pytest.raises(HTTPException) as exc_info:
                await well_known.get_oauth_client_metadata(_request())

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

    def test_jwks_publishes_only_dedicated_cimd_key(self, tmp_path):
        # Third-Party
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        # First-Party
        from mcpgateway.routers import well_known

        def _pem(key):
            return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()

        cimd_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwt_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        (tmp_path / "cimd.pem").write_text(_pem(cimd_key))
        (tmp_path / "jwt.pem").write_text(_pem(jwt_key))
        cfg = _settings(cimd_private_key_path=str(tmp_path / "cimd.pem"), jwt_private_key_path=str(tmp_path / "jwt.pem"))

        with patch.object(well_known, "settings", cfg), patch("mcpgateway.services.cimd_service.get_settings", return_value=cfg):
            keys = well_known.get_jwks()["keys"]

        assert [k["kid"] for k in keys] == ["cimd-1"]
        assert (
            keys[0]["n"]
            != well_known.get_jwk_from_public_key(jwt_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(), "x", "RS256")["n"]
        )

    def test_jwks_empty_without_cimd_key(self):
        # First-Party
        from mcpgateway.routers import well_known

        cfg = _settings()
        with patch.object(well_known, "settings", cfg), patch("mcpgateway.services.cimd_service.get_settings", return_value=cfg):
            assert well_known.get_jwks() == {"keys": []}

    def test_route_requires_no_authentication(self, app):
        # Third-Party
        from fastapi.testclient import TestClient

        response = TestClient(app).get("/oauth/client-metadata.json")

        assert response.status_code == 200
        assert response.json()["token_endpoint_auth_method"] == "none"


def _pem_private(key):
    # Third-Party
    from cryptography.hazmat.primitives import serialization

    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def _pem_public(key):
    # Third-Party
    from cryptography.hazmat.primitives import serialization

    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


class TestCimdKeyLoading:
    """The CIMD key loaders read only the dedicated key and reject unsafe configurations."""

    @staticmethod
    def _rsa():
        # Third-Party
        from cryptography.hazmat.primitives.asymmetric import rsa

        return rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def test_relative_key_path_resolves_against_cwd(self, tmp_path, monkeypatch):
        # First-Party
        from mcpgateway.services import cimd_service

        pem = _pem_private(self._rsa())
        (tmp_path / "cimd.pem").write_text(pem)
        monkeypatch.chdir(tmp_path)

        with patch.object(cimd_service, "get_settings", return_value=_settings(cimd_private_key_path="cimd.pem")):
            assert cimd_service.load_cimd_private_key() == pem

    def test_private_key_reloads_after_file_replaced(self, tmp_path):
        # Standard
        import os

        # First-Party
        from mcpgateway.services import cimd_service

        key_file = tmp_path / "cimd.pem"
        first, second = _pem_private(self._rsa()), _pem_private(self._rsa())
        key_file.write_text(first)
        cfg = _settings(cimd_private_key_path=str(key_file))
        with patch.object(cimd_service, "get_settings", return_value=cfg):
            assert cimd_service.load_cimd_private_key() == first
            key_file.write_text(second)
            os.utime(key_file, ns=(1, 1))
            assert cimd_service.load_cimd_private_key() == second

    def test_unreadable_key_file_rejected(self, tmp_path):
        # First-Party
        from mcpgateway.services import cimd_service

        with patch.object(cimd_service, "get_settings", return_value=_settings(cimd_private_key_path=str(tmp_path / "missing.pem"))):
            with pytest.raises(cimd_service.CimdKeyError, match="cannot read key file"):
                cimd_service.load_cimd_private_key()

    def test_invalid_pem_rejected(self, tmp_path):
        # First-Party
        from mcpgateway.services import cimd_service

        (tmp_path / "bad.pem").write_text("not a pem")
        with patch.object(cimd_service, "get_settings", return_value=_settings(cimd_private_key_path=str(tmp_path / "bad.pem"))):
            with pytest.raises(cimd_service.CimdKeyError, match="valid unencrypted PEM private key"):
                cimd_service.load_cimd_private_key()

    def test_unreadable_jwt_key_does_not_block_cimd_key(self, tmp_path):
        # First-Party
        from mcpgateway.services import cimd_service

        pem = _pem_private(self._rsa())
        (tmp_path / "cimd.pem").write_text(pem)
        cfg = _settings(cimd_private_key_path=str(tmp_path / "cimd.pem"), jwt_private_key_path=str(tmp_path / "missing-jwt.pem"))
        with patch.object(cimd_service, "get_settings", return_value=cfg):
            assert cimd_service.load_cimd_private_key() == pem

    def test_key_identical_to_jwt_key_rejected(self, tmp_path):
        # First-Party
        from mcpgateway.services import cimd_service

        pem = _pem_private(self._rsa())
        (tmp_path / "cimd.pem").write_text(pem)
        (tmp_path / "jwt.pem").write_text(pem)
        cfg = _settings(cimd_private_key_path=str(tmp_path / "cimd.pem"), jwt_private_key_path=str(tmp_path / "jwt.pem"))
        with patch.object(cimd_service, "get_settings", return_value=cfg):
            with pytest.raises(cimd_service.CimdKeyError, match="must not reference the gateway JWT signing key"):
                cimd_service.load_cimd_private_key()

    def test_previous_public_key(self, tmp_path):
        # First-Party
        from mcpgateway.services import cimd_service

        prev_pem = _pem_public(self._rsa())
        (tmp_path / "prev.pem").write_text(prev_pem)

        with patch.object(cimd_service, "get_settings", return_value=_settings()):
            assert cimd_service.load_cimd_previous_public_key() is None
        with patch.object(cimd_service, "get_settings", return_value=_settings(cimd_previous_public_key_path=str(tmp_path / "prev.pem"))):
            assert cimd_service.load_cimd_previous_public_key() == prev_pem
        with patch.object(cimd_service, "get_settings", return_value=_settings(cimd_previous_public_key_path=str(tmp_path / "missing.pem"))):
            assert cimd_service.load_cimd_previous_public_key() is None


class TestJwks:
    """JWK conversion and the CIMD JWKS endpoints."""

    def test_jwk_for_ec_key(self):
        # Third-Party
        from cryptography.hazmat.primitives.asymmetric import ec

        # First-Party
        from mcpgateway.routers.well_known import get_jwk_from_public_key

        for curve, name in ((ec.SECP256R1(), "P-256"), (ec.SECP384R1(), "P-384"), (ec.SECP521R1(), "P-521")):
            jwk = get_jwk_from_public_key(_pem_public(ec.generate_private_key(curve)), "k", "ES256")
            assert jwk["kty"] == "EC"
            assert jwk["crv"] == name
            assert jwk["kid"] == "k"

    def test_jwk_for_ed25519_key(self):
        # Third-Party
        from cryptography.hazmat.primitives.asymmetric import ed25519

        # First-Party
        from mcpgateway.routers.well_known import get_jwk_from_public_key

        jwk = get_jwk_from_public_key(_pem_public(ed25519.Ed25519PrivateKey.generate()), "k", "EdDSA")

        assert jwk["kty"] == "OKP"
        assert jwk["crv"] == "Ed25519"

    def test_jwk_for_unsupported_key_type_is_empty(self):
        # Third-Party
        from cryptography.hazmat.primitives.asymmetric import x25519

        # First-Party
        from mcpgateway.routers.well_known import get_jwk_from_public_key

        assert get_jwk_from_public_key(_pem_public(x25519.X25519PrivateKey.generate()), "k", "ES256") == {}

    def test_jwk_for_unparseable_key_is_empty(self):
        # First-Party
        from mcpgateway.routers.well_known import get_jwk_from_public_key

        assert get_jwk_from_public_key("not a pem", "k", "RS256") == {}

    def test_jwks_includes_previous_key(self, tmp_path):
        # Third-Party
        from cryptography.hazmat.primitives.asymmetric import rsa

        # First-Party
        from mcpgateway.routers import well_known

        (tmp_path / "cimd.pem").write_text(_pem_private(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
        (tmp_path / "prev.pem").write_text(_pem_public(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
        cfg = _settings(cimd_private_key_path=str(tmp_path / "cimd.pem"), cimd_previous_public_key_path=str(tmp_path / "prev.pem"))

        with patch.object(well_known, "settings", cfg), patch("mcpgateway.services.cimd_service.get_settings", return_value=cfg):
            keys = well_known.get_jwks()["keys"]

        assert [k["kid"] for k in keys] == ["cimd-1", "cimd-1-previous"]

    def test_jwks_previous_key_uses_configured_kid(self, tmp_path):
        # Third-Party
        from cryptography.hazmat.primitives.asymmetric import rsa

        # First-Party
        from mcpgateway.routers import well_known

        (tmp_path / "cimd.pem").write_text(_pem_private(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
        (tmp_path / "prev.pem").write_text(_pem_public(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
        cfg = _settings(
            cimd_private_key_path=str(tmp_path / "cimd.pem"),
            cimd_previous_public_key_path=str(tmp_path / "prev.pem"),
            cimd_key_id="cimd-2",
            cimd_previous_key_id="cimd-1",
        )

        with patch.object(well_known, "settings", cfg), patch("mcpgateway.services.cimd_service.get_settings", return_value=cfg):
            keys = well_known.get_jwks()["keys"]

        assert [k["kid"] for k in keys] == ["cimd-2", "cimd-1"]

    @pytest.mark.asyncio
    async def test_jwks_endpoint_disabled_returns_404(self):
        # First-Party
        from mcpgateway.routers import well_known

        with patch.object(well_known, "settings", _settings(cimd_enabled=False)):
            with pytest.raises(HTTPException) as exc_info:
                await well_known.get_oauth_client_metadata_jwks()

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_jwks_endpoint_serves_keys_with_cache_header(self):
        # First-Party
        from mcpgateway.routers import well_known

        cfg = _settings()
        with patch.object(well_known, "settings", cfg), patch("mcpgateway.services.cimd_service.get_settings", return_value=cfg):
            response = await well_known.get_oauth_client_metadata_jwks()

        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=3600"
