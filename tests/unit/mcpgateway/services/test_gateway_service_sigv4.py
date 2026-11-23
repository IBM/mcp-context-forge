# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_sigv4.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Service-level tests for gateways that use auth_type "sigv4".
"""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import httpx2
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.schemas import GatewayUpdate
from mcpgateway.services import upstream_session_registry as registry_module
from mcpgateway.services.gateway_service import GatewayCredentialError, GatewayService
from mcpgateway.utils.passthrough_headers import compute_passthrough_headers_cached
from mcpgateway.utils.sigv4 import access_key_fingerprint, decrypt_sigv4_secret, encrypt_sigv4_secret, SigV4Auth, with_sigv4_auth
from mcpgateway.utils.ssrf_pinning import resolve_pinned_target

SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
ROTATED_SECRET = "rotatedSecretAccessKeyValue0123456789ABCD"  # pragma: allowlist secret
CONFIG = {"access_key_id": "AKIAIOSFODNN7EXAMPLE", "secret_access_key": SECRET, "region": "us-east-1", "service": "execute-api"}  # pragma: allowlist secret


def _stored(secret: str = SECRET, **extra) -> dict:
    """Return a persisted sigv4_config with an encrypted secret."""
    return {**CONFIG, "secret_access_key": encrypt_sigv4_secret("secret_access_key", secret), **extra}


def _query_result(scalar=None):
    """Return a SQLAlchemy-like result that yields ``scalar``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


class TestInitializeGateway:
    """_initialize_gateway builds the signer from the stored configuration."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transport,method", [("streamablehttp", "connect_to_streamablehttp_server"), ("sse", "connect_to_sse_server")])
    async def test_signer_reaches_the_transport(self, transport, method):
        service = GatewayService()
        connector = AsyncMock(return_value=({}, [], [], [], [], None))
        setattr(service, method, connector)

        await service._initialize_gateway("https://api.example.com/mcp", transport=transport, auth_type="sigv4", sigv4_config=_stored())

        signing_auth = connector.await_args.kwargs["signing_auth"]
        assert isinstance(signing_auth, SigV4Auth)
        assert signing_auth.signer.credentials.secret_access_key == SECRET

    @pytest.mark.asyncio
    async def test_other_auth_types_get_no_signer(self):
        service = GatewayService()
        service.connect_to_streamablehttp_server = AsyncMock(return_value=({}, [], [], [], [], None))

        await service._initialize_gateway("https://api.example.com/mcp", {"Authorization": "Bearer t"}, transport="streamablehttp", auth_type="bearer")

        assert service.connect_to_streamablehttp_server.await_args.kwargs["signing_auth"] is None

    @pytest.mark.asyncio
    async def test_missing_config_fails_closed(self):
        service = GatewayService()
        service.connect_to_streamablehttp_server = AsyncMock()

        with pytest.raises(GatewayCredentialError):
            await service._initialize_gateway("https://api.example.com/mcp", transport="streamablehttp", auth_type="sigv4", sigv4_config=None)

        service.connect_to_streamablehttp_server.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_undecryptable_secret_is_a_credential_error(self):
        service = GatewayService()
        service.connect_to_streamablehttp_server = AsyncMock()
        broken = {**CONFIG, "secret_access_key": "v2:{corrupted-bundle"}  # pragma: allowlist secret

        with pytest.raises(GatewayCredentialError) as excinfo:
            await service._initialize_gateway("https://api.example.com/mcp", transport="streamablehttp", auth_type="sigv4", sigv4_config=broken)

        assert "corrupted-bundle" not in str(excinfo.value)
        service.connect_to_streamablehttp_server.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_upstream_rejection_is_a_credential_error(self, status):
        service = GatewayService()
        response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.example.com/mcp"))
        service.connect_to_streamablehttp_server = AsyncMock(side_effect=httpx2.HTTPStatusError("denied", request=response.request, response=response))

        with pytest.raises(GatewayCredentialError, match="rejected the SigV4 credentials") as excinfo:
            await service._initialize_gateway("https://api.example.com/mcp", transport="streamablehttp", auth_type="sigv4", sigv4_config=_stored())

        assert SECRET not in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_upstream_server_error_stays_a_connection_error(self):
        # First-Party
        from mcpgateway.services.gateway_service import GatewayConnectionError

        service = GatewayService()
        response = httpx2.Response(500, request=httpx2.Request("POST", "https://api.example.com/mcp"))
        service.connect_to_streamablehttp_server = AsyncMock(side_effect=httpx2.HTTPStatusError("boom", request=response.request, response=response))

        with pytest.raises(GatewayConnectionError):
            await service._initialize_gateway("https://api.example.com/mcp", transport="streamablehttp", auth_type="sigv4", sigv4_config=_stored())


class TestConnectorsSignEveryRequest:
    """The client factory handed to the MCP transport carries the signer."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["connect_to_streamablehttp_server", "connect_to_sse_server"])
    async def test_factory_attaches_signer(self, monkeypatch, method):
        captured = {}

        class _Boom(Exception):
            """Stops the connector once the factory has been captured."""

        def _fake_proxy_client(**kwargs):
            captured.update(kwargs)
            raise _Boom()

        monkeypatch.setattr("mcpgateway.services.gateway_service.mcp_proxy_client", _fake_proxy_client)
        monkeypatch.setattr("mcpgateway.services.gateway_service.resolve_pinned_target", AsyncMock(return_value=MagicMock(client_kwargs=lambda **kw: dict(kw))))
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_default_verify", lambda: True)
        signer = SigV4Auth(MagicMock())
        service = GatewayService()

        with pytest.raises(Exception):  # noqa: B017 - connectors wrap the sentinel in a gateway error
            await getattr(service, method)("https://api.example.com/mcp", {}, signing_auth=signer)

        client = captured["httpx_client_factory"](headers={"X-Test": "1"}, timeout=None, auth="caller-auth")  # pragma: allowlist secret
        try:
            assert client.auth is signer
        finally:
            await client.aclose()


class TestRegistryPinning:
    """A signing factory survives the session registry's SSRF pinning wrap."""

    @pytest.mark.asyncio
    async def test_pinned_client_keeps_signer(self):
        # First-Party
        from mcpgateway.services.upstream_session_registry import _wrap_httpx_client_factory
        from mcpgateway.utils.sigv4 import build_sigv4_signer, sigv4_client_factory

        signer = SigV4Auth(build_sigv4_signer(CONFIG))
        pinned = await resolve_pinned_target("https://example.com/mcp", "Gateway URL")

        client = _wrap_httpx_client_factory(pinned, sigv4_client_factory(signer))(None, None, None)
        try:
            assert client.auth is signer
        finally:
            await client.aclose()


class TestUniqueness:
    """Two SigV4 gateways collide only when they share the signing identity."""

    def _existing(self, auth_type, sigv4_config=None, auth_value=None):
        return SimpleNamespace(auth_type=auth_type, sigv4_config=sigv4_config, auth_value=auth_value, oauth_config=None)

    def _check(self, existing, sigv4_config, auth_value=None):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [existing]
        return GatewayService()._check_gateway_uniqueness(db, "https://api.example.com/mcp", auth_value, None, None, "owner@example.com", "private", sigv4_config=sigv4_config)

    def test_same_identity_collides(self):
        existing = self._existing("sigv4", _stored(ROTATED_SECRET))
        assert self._check(existing, dict(CONFIG)) is existing

    @pytest.mark.parametrize("field,value", [("access_key_id", "AKIAOTHEREXAMPLE0000"), ("region", "eu-west-1"), ("service", "bedrock")])  # pragma: allowlist secret
    def test_different_identity_does_not_collide(self, field, value):
        existing = self._existing("sigv4", _stored())
        assert self._check(existing, {**CONFIG, field: value}) is None

    def test_sigv4_never_matches_unauthenticated_gateway(self):
        assert self._check(self._existing(None), dict(CONFIG)) is None

    def test_other_auth_never_matches_sigv4_gateway(self):
        existing = self._existing("sigv4", _stored())
        assert self._check(existing, None, auth_value={"Authorization": "Bearer t"}) is None


class TestPassthroughCannotOverrideSignature:
    """Inbound headers never replace the gateway-held SigV4 credentials."""

    @pytest.mark.parametrize("header", ["X-Upstream-Authorization", "Authorization"])
    def test_inbound_authorization_is_dropped(self, header):
        with patch("mcpgateway.utils.passthrough_headers.settings") as cfg:
            cfg.enable_header_passthrough = True
            cfg.enable_overwrite_base_headers = False
            cfg.max_header_value_length = 4096
            headers = compute_passthrough_headers_cached(
                {header: "Bearer attacker"},
                {"Content-Type": "application/json"},
                ["Authorization"],
                gateway_auth_type="sigv4",
            )

        assert "authorization" not in {k.lower() for k in headers}


class TestReadMasking:
    """GatewayRead built from the ORM row never exposes AWS secrets."""

    def test_convert_gateway_to_read_masks_secrets(self):
        stored = _stored(session_token=encrypt_sigv4_secret("session_token", "SESSIONTOKENVALUE"))
        now = datetime.now(timezone.utc)
        gateway = DbGateway(id="gw1", name="aws-gw", slug="aws-gw", url="https://api.example.com/mcp", auth_type="sigv4", sigv4_config=stored, capabilities={}, tags=[], created_at=now, updated_at=now)

        read = GatewayService().convert_gateway_to_read(gateway)

        dumped = read.model_dump_json()
        assert read.sigv4_config["secret_access_key"] == settings.masked_auth_value
        assert read.sigv4_config["session_token"] == settings.masked_auth_value
        assert read.sigv4_config["access_key_id"] == CONFIG["access_key_id"]
        assert SECRET not in dumped
        assert stored["secret_access_key"] not in dumped
        assert "SESSIONTOKENVALUE" not in dumped


class TestUpdateGateway:
    """update_gateway rotates credentials, evicts pinned sessions and rejects bad input."""

    @pytest.fixture
    def reg(self, monkeypatch):
        """Install a throwaway upstream session registry and restore the singleton afterwards."""
        registry = registry_module.UpstreamSessionRegistry()
        monkeypatch.setattr(registry_module, "_registry", registry)
        registry.evict_gateway = AsyncMock(return_value=0)  # type: ignore[method-assign]
        return registry

    def _gateway(self, **overrides):
        gateway = MagicMock()
        gateway.id = "gw-1"
        gateway.name = "gw"
        gateway.url = "https://api.example.com/mcp"
        gateway.transport = "streamablehttp"
        gateway.auth_type = "sigv4"
        gateway.auth_value = None
        gateway.auth_query_params = None
        gateway.oauth_config = None
        gateway.sigv4_config = _stored()
        gateway.ca_certificate = None
        gateway.ca_certificate_sig = None
        gateway.signing_algorithm = None
        gateway.client_cert = None
        gateway.client_key = None
        gateway.team_id = None
        gateway.visibility = "private"
        gateway.tags = []
        gateway.version = 1
        gateway.enabled = True
        for key, value in overrides.items():
            setattr(gateway, key, value)
        return gateway

    def _service(self):
        service = GatewayService()
        service._initialize_gateway = AsyncMock(return_value=({"prompts": {}, "resources": {}, "tools": {}}, [], [], [], [], None))
        service._notify_gateway_updated = AsyncMock()
        service._active_gateways = set()
        service._classification_service = None
        service._check_gateway_uniqueness = Mock(return_value=None)
        service.normalize_url = lambda u: u
        return service

    def _db(self, gateway):
        db = MagicMock()
        db.execute = Mock(side_effect=[_query_result(gateway), _query_result(None), _query_result(None), _query_result(None)])
        return db

    def _patches(self):
        return (
            patch("mcpgateway.services.gateway_service._get_registry_cache"),
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache"),
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache"),
            patch("mcpgateway.services.gateway_service.GatewayRead.model_validate"),
            patch("mcpgateway.utils.passthrough_headers.invalidate_passthrough_header_caches"),
            patch("mcpgateway.services.gateway_service.audit_trail"),
        )

    async def _update(self, service, db, update):
        registry_cache, lookup_cache, stats_cache, validate, invalidate, audit = self._patches()
        with registry_cache as rc, lookup_cache as lc, stats_cache as sc, validate as mv, invalidate, audit:
            for name in ("invalidate_gateways", "invalidate_tools", "invalidate_resources", "invalidate_prompts"):
                setattr(rc.return_value, name, AsyncMock())
            lc.return_value.invalidate_gateway = AsyncMock()
            sc.invalidate_tags = AsyncMock()
            mv.return_value.masked.return_value = MagicMock()
            return await service.update_gateway(db, "gw-1", update)

    @pytest.mark.asyncio
    async def test_rotation_evicts_sessions_and_reencrypts(self, reg):
        reg.evict_gateway.return_value = 1
        gateway = self._gateway()
        old_ciphertext = gateway.sigv4_config["secret_access_key"]
        service = self._service()

        await self._update(service, self._db(gateway), GatewayUpdate(auth_type="sigv4", sigv4_config={**CONFIG, "secret_access_key": ROTATED_SECRET}))

        reg.evict_gateway.assert_awaited_once_with("gw-1")
        stored_secret = gateway.sigv4_config["secret_access_key"]
        assert stored_secret not in (ROTATED_SECRET, old_ciphertext)
        assert decrypt_sigv4_secret("secret_access_key", stored_secret) == ROTATED_SECRET

    @pytest.mark.asyncio
    async def test_masked_echo_keeps_stored_secret(self, reg):
        gateway = self._gateway()
        old_ciphertext = gateway.sigv4_config["secret_access_key"]
        service = self._service()

        await self._update(service, self._db(gateway), GatewayUpdate(auth_type="sigv4", sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value, "region": "eu-west-1"}))

        assert gateway.sigv4_config["secret_access_key"] == old_ciphertext
        assert gateway.sigv4_config["region"] == "eu-west-1"
        reg.evict_gateway.assert_awaited_once_with("gw-1")

    @pytest.mark.asyncio
    async def test_masked_secret_without_a_stored_secret_is_rejected(self, reg):
        """A masked placeholder cannot create a credential that does not exist."""
        gateway = self._gateway(auth_type="bearer", sigv4_config=None)
        service = self._service()

        with pytest.raises(Exception, match="secret_access_key must be provided"):
            await self._update(service, self._db(gateway), GatewayUpdate(auth_type="sigv4", sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value}))

    @pytest.mark.asyncio
    async def test_switching_away_clears_signing_material(self, reg):
        gateway = self._gateway()
        service = self._service()

        await self._update(service, self._db(gateway), GatewayUpdate(auth_type="bearer", auth_token="new-token"))  # pragma: allowlist secret

        assert gateway.sigv4_config is None
        assert gateway.auth_type == "bearer"
        reg.evict_gateway.assert_awaited_once_with("gw-1")

    @pytest.mark.asyncio
    async def test_unrelated_update_keeps_sessions(self, reg):
        gateway = self._gateway()
        stored_before = dict(gateway.sigv4_config)
        service = self._service()

        await self._update(service, self._db(gateway), GatewayUpdate(description="new description"))

        assert gateway.sigv4_config == stored_before
        reg.evict_gateway.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_config_without_sigv4_auth_is_rejected(self):
        # First-Party
        from mcpgateway.services.gateway_service import GatewayError

        gateway = self._gateway(auth_type="bearer", sigv4_config=None)
        service = self._service()

        with pytest.raises(GatewayError):
            await self._update(service, self._db(gateway), GatewayUpdate.model_construct(sigv4_config=dict(CONFIG), auth_type=None))


class TestSigV4FactoryOverridesCallerAuth:
    """A caller cannot swap the signer out through the factory ``auth`` argument."""

    def test_caller_auth_is_ignored(self):
        received = {}

        def factory(headers=None, timeout=None, auth=None):
            received["auth"] = auth
            return "client"

        signer = SigV4Auth(MagicMock())
        with_sigv4_auth(factory, signer)(None, None, "attacker-auth")

        assert received["auth"] is signer


class TestSigV4AuditAttribution:
    """update_gateway and register_gateway record key fingerprints, never credentials."""

    FINGERPRINT = access_key_fingerprint(CONFIG["access_key_id"])
    OTHER_CONFIG = {**CONFIG, "access_key_id": "AKIAI44QH8DHBEXAMPLE"}  # pragma: allowlist secret
    OTHER_FINGERPRINT = access_key_fingerprint(OTHER_CONFIG["access_key_id"])

    @pytest.fixture
    def helper(self, monkeypatch):
        """Reuse the TestUpdateGateway builders with a captured audit logger."""
        registry = registry_module.UpstreamSessionRegistry()
        monkeypatch.setattr(registry_module, "_registry", registry)
        registry.evict_gateway = AsyncMock(return_value=0)  # type: ignore[method-assign]
        return TestUpdateGateway()

    async def _update(self, helper, gateway, update):
        service = helper._service()
        registry_cache, lookup_cache, stats_cache, validate, invalidate, audit = helper._patches()
        with registry_cache as rc, lookup_cache as lc, stats_cache as sc, validate as mv, invalidate, audit as audit_mock:
            for name in ("invalidate_gateways", "invalidate_tools", "invalidate_resources", "invalidate_prompts"):
                setattr(rc.return_value, name, AsyncMock())
            lc.return_value.invalidate_gateway = AsyncMock()
            sc.invalidate_tags = AsyncMock()
            mv.return_value.masked.return_value = MagicMock()
            await service.update_gateway(helper._db(gateway), "gw-1", update)
        audit_mock.log_action.assert_called_once()
        return audit_mock.log_action.call_args.kwargs

    @staticmethod
    def _assert_no_credential_in(call_kwargs):
        rendered = repr(call_kwargs)
        for forbidden in (SECRET, ROTATED_SECRET, CONFIG["access_key_id"], TestSigV4AuditAttribution.OTHER_CONFIG["access_key_id"], "SESSIONTOKENVALUE"):
            assert forbidden not in rendered

    @pytest.mark.asyncio
    async def test_rotation_records_old_and_new_fingerprint(self, helper):
        gateway = helper._gateway()

        call = await self._update(helper, gateway, GatewayUpdate(auth_type="sigv4", sigv4_config={**self.OTHER_CONFIG, "secret_access_key": ROTATED_SECRET}))

        new_values = call["new_values"]
        assert new_values["sigv4_credential_rotated"] is True
        assert new_values["sigv4_key_fingerprint"] == self.OTHER_FINGERPRINT
        assert new_values["sigv4_previous_key_fingerprint"] == self.FINGERPRINT
        assert call["resource_id"] == "gw-1"
        assert call["resource_name"] == "gw"
        self._assert_no_credential_in(call)

    @pytest.mark.asyncio
    async def test_secret_rotation_with_same_key_id_is_a_rotation(self, helper):
        call = await self._update(helper, helper._gateway(), GatewayUpdate(auth_type="sigv4", sigv4_config={**CONFIG, "secret_access_key": ROTATED_SECRET}))

        assert call["new_values"]["sigv4_credential_rotated"] is True
        assert call["new_values"]["sigv4_previous_key_fingerprint"] == self.FINGERPRINT

    @pytest.mark.asyncio
    async def test_masked_echo_is_not_a_rotation(self, helper):
        call = await self._update(helper, helper._gateway(), GatewayUpdate(auth_type="sigv4", sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value}))

        assert "sigv4_credential_rotated" not in call["new_values"]
        assert "sigv4_key_fingerprint" not in call["new_values"]

    @pytest.mark.asyncio
    async def test_resending_the_same_secret_is_not_a_rotation(self, helper):
        call = await self._update(helper, helper._gateway(), GatewayUpdate(auth_type="sigv4", sigv4_config=dict(CONFIG)))

        assert "sigv4_credential_rotated" not in call["new_values"]

    @pytest.mark.asyncio
    async def test_description_only_update_is_not_a_rotation(self, helper):
        call = await self._update(helper, helper._gateway(), GatewayUpdate(description="new description"))

        assert set(call["new_values"]) == {"name", "url", "version"}

    @pytest.mark.asyncio
    async def test_non_sigv4_gateway_audit_entry_is_unchanged(self, helper):
        gateway = helper._gateway(auth_type="bearer", sigv4_config=None)

        call = await self._update(helper, gateway, GatewayUpdate(description="new description"))

        assert set(call["new_values"]) == {"name", "url", "version"}

    @pytest.mark.asyncio
    async def test_switching_away_from_sigv4_records_the_removal(self, helper):
        call = await self._update(helper, helper._gateway(), GatewayUpdate(auth_type="bearer", auth_token="new-token"))  # pragma: allowlist secret

        new_values = call["new_values"]
        assert new_values["sigv4_credential_removed"] is True
        assert new_values["sigv4_previous_key_fingerprint"] == self.FINGERPRINT
        assert "sigv4_key_fingerprint" not in new_values
        self._assert_no_credential_in(call)

    @pytest.mark.asyncio
    async def test_switching_to_sigv4_records_the_new_fingerprint_only(self, helper):
        gateway = helper._gateway(auth_type="bearer", sigv4_config=None)

        call = await self._update(helper, gateway, GatewayUpdate(auth_type="sigv4", sigv4_config=dict(CONFIG)))

        assert call["new_values"]["sigv4_key_fingerprint"] == self.FINGERPRINT
        assert call["new_values"]["sigv4_credential_rotated"] is True
        assert "sigv4_previous_key_fingerprint" not in call["new_values"]
        self._assert_no_credential_in(call)


class TestSigV4GatewayRegistrationAudit:
    """register_gateway records the key fingerprint and no credential."""

    @staticmethod
    def _db():
        db = MagicMock()
        empty = MagicMock()
        empty.scalar_one_or_none.return_value = None
        empty.scalars.return_value.all.return_value = []
        db.execute = Mock(side_effect=[empty, empty])
        return db

    async def _register(self, gateway_create):
        service = GatewayService()
        service._initialize_gateway = AsyncMock(return_value=({"prompts": {}, "resources": {}, "tools": {}}, [], [], [], [], None))
        service._notify_gateway_added = AsyncMock()
        with (
            patch("mcpgateway.services.gateway_service.audit_trail") as audit,
            patch("mcpgateway.services.gateway_service.structured_logger"),
            patch("mcpgateway.services.gateway_service.GatewayRead.model_validate"),
        ):
            await service.register_gateway(self._db(), gateway_create)
        audit.log_action.assert_called_once()
        return audit.log_action.call_args.kwargs

    @pytest.mark.asyncio
    async def test_registration_records_the_fingerprint(self):
        # First-Party
        from mcpgateway.schemas import GatewayCreate

        call = await self._register(
            GatewayCreate(name="aws-gw", url="https://api.example.com/mcp", transport="STREAMABLEHTTP", auth_type="sigv4", sigv4_config={**CONFIG, "session_token": "SESSIONTOKENVALUE"})
        )

        assert call["action"] == "create_gateway"
        assert call["new_values"]["auth_type"] == "sigv4"
        assert call["new_values"]["sigv4_key_fingerprint"] == access_key_fingerprint(CONFIG["access_key_id"])
        assert call["resource_name"] == "aws-gw"
        assert call["resource_id"]
        assert "db" not in call
        rendered = repr(call)
        for forbidden in (SECRET, CONFIG["access_key_id"], "SESSIONTOKENVALUE"):
            assert forbidden not in rendered

    @pytest.mark.asyncio
    async def test_non_sigv4_registration_audit_entry_is_unchanged(self):
        # First-Party
        from mcpgateway.schemas import GatewayCreate

        call = await self._register(GatewayCreate(name="plain-gw", url="https://example.com/mcp", transport="SSE"))

        assert set(call["new_values"]) == {"name", "url", "visibility", "transport", "tools_count", "resources_count", "prompts_count"}


class TestFailingGatewayCallLeaksNoCredential:
    """A failing SigV4 gateway call logs and raises no secret, signature or session token."""

    SESSION_TOKEN = "SESSIONTOKENVALUE"  # pragma: allowlist secret
    SIGNATURE = "deadbeefsignature0123"  # pragma: allowlist secret

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transport,method", [("streamablehttp", "connect_to_streamablehttp_server"), ("sse", "connect_to_sse_server")])
    async def test_connection_failure_with_a_signed_url(self, caplog, transport, method):
        # First-Party
        from mcpgateway.services.gateway_service import GatewayConnectionError

        service = GatewayService()
        url = f"https://api.example.com/mcp?X-Amz-Signature={self.SIGNATURE}&X-Amz-Security-Token={self.SESSION_TOKEN}&X-Amz-Credential={CONFIG['access_key_id']}"  # pragma: allowlist secret
        setattr(service, method, AsyncMock(side_effect=RuntimeError(f"connection to {url} failed")))

        with caplog.at_level("DEBUG"), pytest.raises(GatewayConnectionError) as raised:
            await service._initialize_gateway(url, transport=transport, auth_type="sigv4", sigv4_config=_stored(session_token=encrypt_sigv4_secret("session_token", self.SESSION_TOKEN)))

        messages = "\n".join(record.getMessage() for record in caplog.records)
        for value in (self.SESSION_TOKEN, self.SIGNATURE, CONFIG["access_key_id"]):
            assert value not in messages
            assert value not in str(raised.value)
        assert SECRET not in caplog.text
        assert SECRET not in str(raised.value)

    @pytest.mark.asyncio
    async def test_upstream_rejection_names_no_credential(self, caplog):
        # First-Party
        from mcpgateway.services.gateway_service import GatewayCredentialError

        service = GatewayService()
        response = httpx2.Response(403, request=httpx2.Request("POST", "https://api.example.com/mcp"))
        service.connect_to_streamablehttp_server = AsyncMock(side_effect=httpx2.HTTPStatusError("403 Forbidden", request=response.request, response=response))

        with caplog.at_level("DEBUG"), pytest.raises(GatewayCredentialError) as raised:
            await service._initialize_gateway("https://api.example.com/mcp", transport="streamablehttp", auth_type="sigv4", sigv4_config=_stored())

        logged = "\n".join(record.getMessage() + "\n" + str(record.__dict__.get("exc_text") or "") for record in caplog.records)
        for value in (SECRET, CONFIG["access_key_id"]):
            assert value not in logged
            assert value not in str(raised.value)

    @pytest.mark.asyncio
    async def test_undecryptable_credentials_name_no_secret(self, caplog):
        # First-Party
        from mcpgateway.services.gateway_service import GatewayCredentialError

        service = GatewayService()
        broken = {**CONFIG, "secret_access_key": "not-encrypted"}  # pragma: allowlist secret

        with caplog.at_level("DEBUG"), pytest.raises(GatewayCredentialError) as raised:
            await service._initialize_gateway("https://api.example.com/mcp", transport="streamablehttp", auth_type="sigv4", sigv4_config=broken)

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "not-encrypted" not in logged
        assert "not-encrypted" not in str(raised.value)
