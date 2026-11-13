# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_sigv4_signing_paths.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Signing-path tests for gateways that use auth_type "sigv4".

Each upstream path must hand the MCP client a factory that attaches the SigV4 signer.
A SigV4 gateway without usable credentials must fail closed before any connection opens.
"""

# Standard
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.completion_service import CompletionInternalError, CompletionService
from mcpgateway.services.prompt_service import PromptError, PromptService
from mcpgateway.services.resource_service import ResourceError, ResourceService
from mcpgateway.services.tool_service import ToolInvocationError, ToolService
from mcpgateway.transports import streamablehttp_transport as transport_module
from mcpgateway.utils.sigv4 import encrypt_sigv4_secret, SigV4Auth

SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
CONFIG = {"access_key_id": "AKIAIOSFODNN7EXAMPLE", "secret_access_key": SECRET, "region": "us-east-1", "service": "execute-api"}  # pragma: allowlist secret


def _stored_config() -> dict:
    """Return a persisted sigv4_config with an encrypted secret."""
    return {**CONFIG, "secret_access_key": encrypt_sigv4_secret("secret_access_key", SECRET)}


def _sigv4_gateway(**overrides) -> SimpleNamespace:
    """Return a SigV4 gateway stand-in with valid stored credentials."""
    fields = {
        "id": "gw-sigv4",
        "name": "aws-gateway",
        "slug": "aws-gateway",
        "url": "https://api.example.com/mcp",
        "transport": "streamable_http",
        "auth_type": "sigv4",
        "auth_value": None,
        "auth_query_params": None,
        "sigv4_config": _stored_config(),
        "oauth_config": None,
        "ca_certificate": None,
        "ca_certificate_sig": None,
        "passthrough_headers": None,
        "gateway_mode": "direct_proxy",
        "visibility": "public",
        "team_id": None,
        "owner_email": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def _signer_of(factory) -> SigV4Auth:
    """Build one client from ``factory`` and return the auth object it carries."""
    assert factory is not None, "the path passed no client factory, so nothing would sign"
    client = factory()
    try:
        assert isinstance(client.auth, SigV4Auth), "the client built by the factory does not sign"
        return client.auth
    finally:
        await client.aclose()


def _capturing_proxy_client(captured: dict, session=None):
    """Return an ``mcp_proxy_client`` stand-in that records its keyword arguments."""
    yielded = session if session is not None else SimpleNamespace(session=AsyncMock())

    @asynccontextmanager
    async def _proxy_client(**kwargs):
        captured.update(kwargs)
        yield yielded

    return _proxy_client


class TestPromptSigning:
    """PromptService signs gateway-backed prompt fetches."""

    @staticmethod
    def _prompt(gateway) -> SimpleNamespace:
        return SimpleNamespace(name="gw-prompt", original_name="gw-prompt", description="d", gateway=gateway, gateway_id=getattr(gateway, "id", None))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transport", ["streamable_http", "sse"])
    async def test_prompt_fetch_signs_with_the_gateway_credentials(self, transport):
        captured: dict = {}
        remote = SimpleNamespace(messages=[], description="remote")

        with (
            patch("mcpgateway.services.prompt_service._downstream_session_id_from_request", return_value=None),
            patch("mcpgateway.services.prompt_service.mcp_proxy_client", _capturing_proxy_client(captured)),
            patch("mcpgateway.services.prompt_service._get_prompt_with_meta", new_callable=AsyncMock, return_value=remote),
        ):
            await PromptService()._fetch_gateway_prompt_result(self._prompt(_sigv4_gateway(transport=transport)), {})

        signer = await _signer_of(captured["httpx_client_factory"])
        assert signer.signer.credentials.secret_access_key == SECRET

    @pytest.mark.asyncio
    async def test_prompt_fetch_signs_on_the_pooled_session_path(self):
        fake_registry = MagicMock()
        fake_registry.acquire = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=SimpleNamespace(session=MagicMock())), __aexit__=AsyncMock(return_value=False)))

        with (
            patch("mcpgateway.services.prompt_service._downstream_session_id_from_request", return_value="downstream-1"),
            patch("mcpgateway.services.prompt_service.get_upstream_session_registry", return_value=fake_registry),
            patch("mcpgateway.services.prompt_service._get_prompt_with_meta", new_callable=AsyncMock, return_value=SimpleNamespace(messages=[], description="r")),
        ):
            await PromptService()._fetch_gateway_prompt_result(self._prompt(_sigv4_gateway()), {})

        signer = await _signer_of(fake_registry.acquire.call_args.kwargs["httpx_client_factory"])
        assert signer.signer.credentials.access_key_id == CONFIG["access_key_id"]

    @pytest.mark.asyncio
    async def test_other_auth_types_get_no_signing_factory(self):
        captured: dict = {}

        with (
            patch("mcpgateway.services.prompt_service._downstream_session_id_from_request", return_value=None),
            patch("mcpgateway.services.prompt_service.mcp_proxy_client", _capturing_proxy_client(captured)),
            patch("mcpgateway.services.prompt_service._get_prompt_with_meta", new_callable=AsyncMock, return_value=SimpleNamespace(messages=[], description="r")),
        ):
            await PromptService()._fetch_gateway_prompt_result(self._prompt(_sigv4_gateway(auth_type="bearer", sigv4_config=None)), {})

        assert captured["httpx_client_factory"] is None

    @pytest.mark.asyncio
    async def test_missing_credentials_fail_closed_before_connecting(self):
        proxy = MagicMock()

        with patch("mcpgateway.services.prompt_service.mcp_proxy_client", proxy):
            with pytest.raises(PromptError, match="SigV4 credentials"):
                await PromptService()._fetch_gateway_prompt_result(self._prompt(_sigv4_gateway(sigv4_config=None)), {})

        proxy.assert_not_called()


class TestCompletionSigning:
    """CompletionService signs gateway completion calls."""

    @pytest.mark.asyncio
    async def test_fallback_session_signs_with_the_gateway_credentials(self):
        captured: dict = {}
        pinned = MagicMock()
        pinned.client_kwargs.return_value = {}

        with (
            patch("mcpgateway.services.completion_service._downstream_session_id_from_request", return_value=None),
            patch("mcpgateway.services.completion_service.resolve_pinned_target", AsyncMock(return_value=pinned)),
            patch("mcpgateway.services.completion_service.mcp_proxy_client", _capturing_proxy_client(captured)),
        ):
            async with CompletionService()._acquire_upstream_session(_sigv4_gateway()):
                pass

        signer = await _signer_of(captured["httpx_client_factory"])
        assert signer.signer.credentials.secret_access_key == SECRET
        pinned.client_kwargs.assert_called()

    @pytest.mark.asyncio
    async def test_pooled_session_signs_with_the_gateway_credentials(self):
        acquired: dict = {}

        @asynccontextmanager
        async def _acquire(**kwargs):
            acquired.update(kwargs)
            yield SimpleNamespace(session=MagicMock())

        registry = SimpleNamespace(acquire=_acquire)

        with (
            patch("mcpgateway.services.completion_service._downstream_session_id_from_request", return_value="downstream-1"),
            patch("mcpgateway.services.completion_service.get_upstream_session_registry", return_value=registry),
        ):
            async with CompletionService()._acquire_upstream_session(_sigv4_gateway()):
                pass

        signer = await _signer_of(acquired["httpx_client_factory"])
        assert signer.signer.credentials.access_key_id == CONFIG["access_key_id"]

    @pytest.mark.asyncio
    async def test_missing_credentials_fail_closed_before_connecting(self):
        proxy = MagicMock()

        with patch("mcpgateway.services.completion_service.mcp_proxy_client", proxy):
            with pytest.raises(CompletionInternalError, match="SigV4 credentials"):
                async with CompletionService()._acquire_upstream_session(_sigv4_gateway(sigv4_config=None)):
                    pass

        proxy.assert_not_called()


class TestResourceSigning:
    """ResourceService signs gateway resource reads."""

    @staticmethod
    def _resource() -> MagicMock:
        resource = MagicMock()
        resource.id = "res-1"
        resource.name = "Test Resource"
        resource.gateway_id = "gw-sigv4"
        return resource

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transport", ["sse", "streamablehttp"])
    async def test_invoke_resource_signs_with_the_gateway_credentials(self, monkeypatch, transport):
        monkeypatch.setenv("PLUGINS_ENABLED", "false")
        captured: dict = {}
        session = AsyncMock()
        session.session = session
        session.read_resource.return_value = SimpleNamespace(contents=[SimpleNamespace(uri="test://r", text="x", mimeType="text/plain")])

        with (
            patch("mcpgateway.services.resource_service.mcp_proxy_client", _capturing_proxy_client(captured, session)),
            patch("mcpgateway.services.resource_service._downstream_session_id_from_request", return_value=None),
            patch("mcpgateway.services.resource_service.create_span"),
            patch("mcpgateway.services.resource_service.is_input_capture_enabled", return_value=False),
            patch("mcpgateway.services.resource_service.is_output_capture_enabled", return_value=False),
        ):
            await ResourceService().invoke_resource(MagicMock(), "res-1", "test://r", resource_obj=self._resource(), gateway_obj=_sigv4_gateway(transport=transport))

        signer = await _signer_of(captured["httpx_client_factory"])
        assert signer.signer.credentials.secret_access_key == SECRET

    @pytest.mark.asyncio
    async def test_invoke_resource_fails_closed_without_credentials(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_ENABLED", "false")
        proxy = MagicMock()

        with patch("mcpgateway.services.resource_service.mcp_proxy_client", proxy):
            with pytest.raises(ResourceError, match="SigV4 credentials"):
                await ResourceService().invoke_resource(MagicMock(), "res-1", "test://r", resource_obj=self._resource(), gateway_obj=_sigv4_gateway(sigv4_config=None))

        proxy.assert_not_called()


class TestToolDirectProxySigning:
    """ToolService.invoke_tool_direct signs direct-proxy tool calls."""

    @staticmethod
    def _fresh_session(gateway):
        @contextmanager
        def _session():
            db = MagicMock()
            gateway_result = MagicMock()
            gateway_result.scalar_one_or_none.return_value = gateway
            tool_result = MagicMock()
            tool_result.scalar_one_or_none.return_value = None
            db.execute.side_effect = [gateway_result, tool_result]
            yield db

        return _session

    async def _invoke(self, gateway, proxy_client):
        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._fresh_session(gateway)),
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=True),
            patch("mcpgateway.services.tool_service.resolve_pinned_target", AsyncMock(return_value=MagicMock(client_kwargs=MagicMock(return_value={})))),
            patch("mcpgateway.services.tool_service.mcp_proxy_client", proxy_client),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.mcpgateway_direct_proxy_timeout = 30
            mock_settings.gateway_tool_name_separator = "-"
            return await ToolService().invoke_tool_direct(gateway_id=gateway.id, name="remote_tool", arguments={}, user_email="user@example.com", token_teams=["team-1"])

    @pytest.mark.asyncio
    async def test_direct_proxy_call_signs_with_the_gateway_credentials(self):
        captured: dict = {}
        session = SimpleNamespace(session=AsyncMock())
        session.session.call_tool = AsyncMock(return_value=MagicMock())

        await self._invoke(_sigv4_gateway(), _capturing_proxy_client(captured, session))

        signer = await _signer_of(captured["httpx_client_factory"])
        assert signer.signer.credentials.secret_access_key == SECRET

    @pytest.mark.asyncio
    async def test_direct_proxy_fails_closed_without_credentials(self):
        proxy = MagicMock()

        with pytest.raises(ToolInvocationError, match="SigV4"):
            await self._invoke(_sigv4_gateway(sigv4_config=None), proxy)

        proxy.assert_not_called()

    @pytest.mark.asyncio
    async def test_direct_proxy_does_not_sign_other_auth_types(self):
        captured: dict = {}
        session = SimpleNamespace(session=AsyncMock())
        session.session.call_tool = AsyncMock(return_value=MagicMock())

        await self._invoke(_sigv4_gateway(auth_type="bearer", auth_value={"Authorization": "Bearer t"}, sigv4_config=None), _capturing_proxy_client(captured, session))

        client = captured["httpx_client_factory"]()
        try:
            assert not isinstance(client.auth, SigV4Auth)
        finally:
            await client.aclose()


class TestTransportDirectProxySigning:
    """The streamable HTTP transport signs direct-proxy catalog calls."""

    @pytest.mark.asyncio
    async def test_sigv4_gateway_gets_a_signing_factory(self):
        signer = await _signer_of(transport_module._gateway_sigv4_factory(_sigv4_gateway()))

        assert signer.signer.credentials.access_key_id == CONFIG["access_key_id"]

    @pytest.mark.parametrize("auth_type", [None, "bearer", "basic", "authheaders"])
    def test_other_auth_types_get_no_factory(self, auth_type):
        assert transport_module._gateway_sigv4_factory(_sigv4_gateway(auth_type=auth_type, sigv4_config=None)) is None

    def test_sigv4_gateway_without_credentials_fails_closed(self):
        # First-Party
        from mcpgateway.utils.sigv4 import SigV4ConfigError  # pylint: disable=import-outside-toplevel

        with pytest.raises(SigV4ConfigError):
            transport_module._gateway_sigv4_factory(_sigv4_gateway(sigv4_config=None))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "proxy_fn, client_method, args",
        [
            ("_proxy_list_tools_to_gateway", "list_tools", ({}, {}, None)),
            ("_proxy_list_resources_to_gateway", "list_resources", ({}, {}, None)),
        ],
    )
    async def test_catalog_proxy_signs_with_the_gateway_credentials(self, proxy_fn, client_method, args):
        captured: dict = {}
        client = AsyncMock()
        getattr(client, client_method).return_value = SimpleNamespace(tools=[], resources=[], next_cursor=None, nextCursor=None)

        with (
            patch.object(transport_module, "mcp_proxy_client", _capturing_proxy_client(captured, client)),
            patch.object(transport_module, "build_gateway_auth_headers", return_value={}),
        ):
            await getattr(transport_module, proxy_fn)(_sigv4_gateway(), *args)

        signer = await _signer_of(captured["httpx_client_factory"])
        assert signer.signer.credentials.secret_access_key == SECRET


def test_sigv4_gateway_model_has_the_storage_column():
    """The ORM exposes the column the signing paths read."""
    assert "sigv4_config" in DbGateway.__table__.columns
