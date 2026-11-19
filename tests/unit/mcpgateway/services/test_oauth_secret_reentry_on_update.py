# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oauth_secret_reentry_on_update.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

An update that keeps a masked OAuth secret must not move that secret to a new
token endpoint. The form submits the mask on every edit, so the service has to
compare the submitted endpoints with the stored ones and refuse the update.

Both update paths are covered: MCP servers (``GatewayService.update_gateway``)
and A2A agents (``A2AAgentService.update_agent``). The refused update must leave
the row untouched, and the gateway must raise ``OAuthSecretReentryRequired`` so
its endpoint returns 400, not a generic 500.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.common.oauth import OAuthSecretReentryRequired
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent  # noqa: F401  (import keeps model registration side effects)
from mcpgateway.schemas import A2AAgentUpdate, GatewayUpdate
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentService
from mcpgateway.services.gateway_service import GatewayService

MASK = settings.masked_auth_value
OLD_TOKEN = "https://old.example.com/token"
NEW_TOKEN = "https://new.example.com/token"
STORED_SECRET = "stored-client-secret"  # pragma: allowlist secret


class TestGatewayUpdate:
    """``update_gateway`` refuses a moved endpoint that keeps the masked secret."""

    @staticmethod
    def _gateway(oauth_config):
        """A persisted MCP gateway row for the update service.

        Args:
            oauth_config: Stored OAuth configuration.

        Returns:
            MagicMock: Gateway row stub.
        """
        gateway = MagicMock()
        gateway.id = "gw-oauth"
        gateway.name = "Gateway"
        gateway.url = "https://upstream.example.com"
        gateway.enabled = True
        gateway.gateway_mode = "cache"
        gateway.transport = "SSE"
        gateway.auth_type = "oauth"
        gateway.auth_value = None
        gateway.auth_query_params = None
        gateway.oauth_config = oauth_config
        gateway.ca_certificate = None
        gateway.ca_certificate_sig = None
        gateway.signing_algorithm = None
        gateway.client_cert = None
        gateway.client_key = None
        gateway.tools = []
        gateway.resources = []
        gateway.prompts = []
        gateway.email_team = None
        gateway.version = 1
        gateway.team = None
        gateway.team_id = None
        gateway.created_by = "admin@example.com"
        gateway.modified_by = "admin@example.com"
        return gateway

    @staticmethod
    def _service(monkeypatch, gateway):
        """A service whose lookups, caches, and upstream calls are stubs.

        Args:
            monkeypatch: pytest monkeypatch fixture.
            gateway: Gateway row returned by ``get_for_update``.

        Returns:
            GatewayService: Configured service instance.
        """
        monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", MagicMock(side_effect=[gateway, None]))
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", AsyncMock)
        monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: MagicMock(invalidate_gateway=AsyncMock()))
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", MagicMock(invalidate_tags=AsyncMock()))
        service = GatewayService()
        service._initialize_gateway = AsyncMock(return_value=({}, [], [], [], [], None))
        service._notify_gateway_updated = AsyncMock()
        return service

    @pytest.mark.asyncio
    async def test_masked_secret_with_a_changed_token_url_is_refused(self, monkeypatch):
        gateway = self._gateway({"grant_type": "client_credentials", "client_id": "svc", "token_url": OLD_TOKEN, "client_secret": STORED_SECRET})
        service = self._service(monkeypatch, gateway)
        db = MagicMock()

        update = GatewayUpdate(oauth_config={"grant_type": "client_credentials", "client_id": "svc", "token_url": NEW_TOKEN, "client_secret": MASK})

        with pytest.raises(OAuthSecretReentryRequired, match="Send the OAuth client secret again"):
            await service.update_gateway(db, "gw-oauth", update)

        db.rollback.assert_called_once()
        db.commit.assert_not_called()
        assert gateway.oauth_config["client_secret"] == STORED_SECRET
        assert gateway.oauth_config["token_url"] == OLD_TOKEN

    @pytest.mark.asyncio
    async def test_masked_discovery_secret_with_a_changed_discovery_url_is_refused(self, monkeypatch):
        gateway = self._gateway(
            {
                "grant_type": "token-exchange",
                "token_url": OLD_TOKEN,
                "target_audience": "https://upstream.example.com",
                "discovery": {"grant_type": "client_credentials", "token_url": OLD_TOKEN, "client_secret": STORED_SECRET},
            }
        )
        service = self._service(monkeypatch, gateway)
        db = MagicMock()

        update = GatewayUpdate(
            oauth_config={
                "grant_type": "token-exchange",
                "token_url": OLD_TOKEN,
                "target_audience": "https://upstream.example.com",
                "discovery": {"grant_type": "client_credentials", "token_url": NEW_TOKEN, "client_secret": MASK},
            }
        )

        with pytest.raises(OAuthSecretReentryRequired, match="Send the OAuth client secret again"):
            await service.update_gateway(db, "gw-oauth", update)

        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_masked_secret_with_an_unchanged_token_url_keeps_the_stored_secret(self, monkeypatch):
        gateway = self._gateway({"grant_type": "client_credentials", "client_id": "svc", "token_url": OLD_TOKEN, "client_secret": STORED_SECRET})
        service = self._service(monkeypatch, gateway)
        db = MagicMock()

        update = GatewayUpdate(oauth_config={"grant_type": "client_credentials", "client_id": "svc", "token_url": OLD_TOKEN, "client_secret": MASK})

        await service.update_gateway(db, "gw-oauth", update)

        db.rollback.assert_not_called()
        assert gateway.oauth_config["client_secret"] == STORED_SECRET

    @pytest.mark.asyncio
    async def test_new_secret_with_a_changed_token_url_is_accepted(self, monkeypatch):
        gateway = self._gateway({"grant_type": "client_credentials", "client_id": "svc", "token_url": OLD_TOKEN, "client_secret": STORED_SECRET})
        service = self._service(monkeypatch, gateway)
        db = MagicMock()

        update = GatewayUpdate(oauth_config={"grant_type": "client_credentials", "client_id": "svc", "token_url": NEW_TOKEN, "client_secret": "new-secret"})  # pragma: allowlist secret

        await service.update_gateway(db, "gw-oauth", update)

        db.rollback.assert_not_called()
        assert gateway.oauth_config["token_url"] == NEW_TOKEN


class TestA2AAgentUpdate:
    """``update_agent`` applies the same rule to the actor and discovery clients."""

    @staticmethod
    def _agent(oauth_config):
        """An A2A agent row for the update service.

        Args:
            oauth_config: Stored OAuth configuration.

        Returns:
            SimpleNamespace: Agent row stub.
        """
        return SimpleNamespace(
            id="a1",
            name="ag",
            slug="ag",
            endpoint_url="https://agent.example.com",
            auth_type="oauth",
            auth_value=None,
            auth_query_params=None,
            enabled=True,
            version=1,
            visibility="public",
            team_id=None,
            owner_email=None,
            passthrough_headers=None,
            oauth_config=oauth_config,
        )

    @staticmethod
    def _service(monkeypatch, agent):
        """A service whose lookups and caches are stubs.

        Args:
            monkeypatch: pytest monkeypatch fixture.
            agent: Agent row returned by ``get_for_update``.

        Returns:
            A2AAgentService: Configured service instance.
        """
        monkeypatch.setattr("mcpgateway.services.a2a_service.get_for_update", MagicMock(side_effect=[agent, None]))
        service = A2AAgentService()
        service.convert_agent_to_read = MagicMock(return_value=MagicMock())
        dummy_cache = SimpleNamespace(invalidate_agents=AsyncMock())
        monkeypatch.setattr("mcpgateway.services.a2a_service._get_registry_cache", lambda: dummy_cache)
        monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
        return service

    @pytest.mark.asyncio
    async def test_masked_actor_secret_with_a_changed_actor_url_is_refused(self, monkeypatch):
        stored = {
            "grant_type": "token-exchange",
            "token_url": OLD_TOKEN,
            "actor_token_source": "client_credentials",
            "actor": {"client_id": "cf", "token_url": OLD_TOKEN, "client_secret": STORED_SECRET},
        }
        agent = self._agent(stored)
        service = self._service(monkeypatch, agent)
        db = MagicMock()

        update = A2AAgentUpdate.model_construct(
            oauth_config={
                "grant_type": "token-exchange",
                "token_url": OLD_TOKEN,
                "actor_token_source": "client_credentials",
                "actor": {"client_id": "cf", "token_url": NEW_TOKEN, "client_secret": MASK},
            }
        )

        with pytest.raises(A2AAgentError, match="Send the OAuth client secret again"):
            await service.update_agent(db, "a1", update)

        db.rollback.assert_called_once()
        db.commit.assert_not_called()
        assert agent.oauth_config["actor"]["client_secret"] == STORED_SECRET
        assert agent.oauth_config["actor"]["token_url"] == OLD_TOKEN

    @pytest.mark.asyncio
    async def test_masked_discovery_secret_with_a_changed_discovery_url_is_refused(self, monkeypatch):
        stored = {"grant_type": "token-exchange", "token_url": OLD_TOKEN, "discovery": {"grant_type": "client_credentials", "token_url": OLD_TOKEN, "client_secret": STORED_SECRET}}
        agent = self._agent(stored)
        service = self._service(monkeypatch, agent)
        db = MagicMock()

        update = A2AAgentUpdate.model_construct(
            oauth_config={"grant_type": "token-exchange", "token_url": OLD_TOKEN, "discovery": {"grant_type": "client_credentials", "token_url": NEW_TOKEN, "client_secret": MASK}}
        )

        with pytest.raises(A2AAgentError, match="Send the OAuth client secret again"):
            await service.update_agent(db, "a1", update)

        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_masked_secret_with_an_unchanged_token_url_keeps_the_stored_secret(self, monkeypatch):
        stored = {"grant_type": "client_credentials", "client_id": "svc", "token_url": OLD_TOKEN, "client_secret": STORED_SECRET}
        agent = self._agent(stored)
        service = self._service(monkeypatch, agent)
        db = MagicMock()

        update = A2AAgentUpdate.model_construct(oauth_config={"grant_type": "client_credentials", "client_id": "svc", "token_url": OLD_TOKEN, "client_secret": MASK})

        with patch("mcpgateway.services.tool_service.tool_service") as tool_service:
            tool_service.update_tool_from_a2a_agent = AsyncMock(return_value=None)
            await service.update_agent(db, "a1", update)

        db.rollback.assert_not_called()
        assert agent.oauth_config["client_secret"] == STORED_SECRET

    @pytest.mark.asyncio
    async def test_new_secret_with_a_changed_token_url_is_accepted(self, monkeypatch):
        stored = {"grant_type": "client_credentials", "client_id": "svc", "token_url": OLD_TOKEN, "client_secret": STORED_SECRET}
        agent = self._agent(stored)
        service = self._service(monkeypatch, agent)
        db = MagicMock()

        update = A2AAgentUpdate.model_construct(
            oauth_config={"grant_type": "client_credentials", "client_id": "svc", "token_url": NEW_TOKEN, "client_secret": "new-secret"}
        )  # pragma: allowlist secret

        with patch("mcpgateway.services.tool_service.tool_service") as tool_service:
            tool_service.update_tool_from_a2a_agent = AsyncMock(return_value=None)
            await service.update_agent(db, "a1", update)

        db.rollback.assert_not_called()
        assert agent.oauth_config["token_url"] == NEW_TOKEN
