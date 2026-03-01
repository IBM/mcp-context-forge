# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for A2A Server Service (mcpgateway/services/a2a_server_service.py)."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_errors import A2AAgentError, A2AAgentNotFoundError
from mcpgateway.services.a2a_server_service import A2AServerNotFoundError, A2AServerService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_interface(protocol="a2a", binding="jsonrpc", version="1.0", tenant=None, enabled=True, config=None):
    """Create a mock ServerInterface."""
    iface = MagicMock()
    iface.protocol = protocol
    iface.binding = binding
    iface.version = version
    iface.tenant = tenant
    iface.enabled = enabled
    iface.config = config or {}
    return iface


def _make_agent(name="agent-1", enabled=True, capabilities=None, tenant=None):
    """Create a mock A2AAgent."""
    agent = MagicMock()
    agent.name = name
    agent.enabled = enabled
    agent.capabilities = capabilities or {}
    agent.tenant = tenant
    return agent


def _make_server(server_id="srv-1", name="Test Server", interfaces=None, agents=None, description="A test server", icon=None):
    """Create a mock Server."""
    server = MagicMock()
    server.id = server_id
    server.name = name
    server.description = description
    server.icon = icon
    server.interfaces = interfaces or []
    server.a2a_agents = agents or []
    server.enabled = True
    return server


@pytest.fixture
def mock_a2a_service():
    """Create a mock A2AAgentService."""
    svc = MagicMock()
    svc.send_message = AsyncMock(return_value={"result": {"id": "task-abc", "state": "SUBMITTED"}})
    svc.stream_message = AsyncMock(return_value=iter(["data: test\n\n"]))
    svc.get_task = AsyncMock(return_value={"result": {"id": "task-abc", "state": "WORKING"}})
    svc.cancel_task = AsyncMock(return_value={"result": {"id": "task-abc", "state": "CANCELED"}})
    svc.list_tasks = AsyncMock(return_value={"result": [{"id": "task-1"}, {"id": "task-2"}]})
    svc.invoke_agent = AsyncMock(return_value={"result": {"status": "ok"}})
    return svc


@pytest.fixture
def service(mock_a2a_service):
    """Create an A2AServerService with a mocked A2A service."""
    return A2AServerService(a2a_service=mock_a2a_service)


@pytest.fixture
def db():
    """Create a mock database session."""
    mock_db = MagicMock()
    return mock_db


# ---------------------------------------------------------------------------
# A2AServerNotFoundError
# ---------------------------------------------------------------------------
class TestA2AServerNotFoundError:
    def test_inherits_from_not_found(self):
        assert issubclass(A2AServerNotFoundError, A2AAgentNotFoundError)

    def test_message(self):
        err = A2AServerNotFoundError("Server 'x' not found")
        assert "Server 'x'" in str(err)


# ---------------------------------------------------------------------------
# _get_server_with_a2a
# ---------------------------------------------------------------------------
class TestGetServerWithA2A:
    def test_raises_when_server_not_found(self, service, db):
        db.query.return_value.options.return_value.filter.return_value.first.return_value = None
        with pytest.raises(A2AServerNotFoundError, match="not found"):
            service._get_server_with_a2a(db, "nonexistent")

    def test_raises_when_no_a2a_interfaces(self, service, db):
        server = _make_server(interfaces=[_make_interface(protocol="mcp", binding="sse")])
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server
        with pytest.raises(A2AServerNotFoundError, match="no enabled A2A"):
            service._get_server_with_a2a(db, "srv-1")

    def test_raises_when_a2a_interface_disabled(self, service, db):
        server = _make_server(interfaces=[_make_interface(enabled=False)])
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server
        with pytest.raises(A2AServerNotFoundError, match="no enabled A2A"):
            service._get_server_with_a2a(db, "srv-1")

    def test_succeeds_with_a2a_interface(self, service, db):
        server = _make_server(interfaces=[_make_interface()])
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server
        result = service._get_server_with_a2a(db, "srv-1")
        assert result is server


# ---------------------------------------------------------------------------
# _pick_agent
# ---------------------------------------------------------------------------
class TestPickAgent:
    def test_raises_when_no_agents(self, service):
        server = _make_server(agents=[])
        with pytest.raises(A2AAgentError, match="no active"):
            service._pick_agent(server)

    def test_raises_when_all_disabled(self, service):
        server = _make_server(agents=[_make_agent(enabled=False)])
        with pytest.raises(A2AAgentError, match="no active"):
            service._pick_agent(server)

    def test_returns_first_active(self, service):
        a1 = _make_agent(name="first")
        a2 = _make_agent(name="second")
        server = _make_server(agents=[a1, a2])
        assert service._pick_agent(server) is a1

    def test_skips_disabled_agents(self, service):
        a1 = _make_agent(name="disabled", enabled=False)
        a2 = _make_agent(name="active")
        server = _make_server(agents=[a1, a2])
        assert service._pick_agent(server) is a2

    def test_skill_based_selection(self, service):
        a1 = _make_agent(name="general")
        a2 = _make_agent(name="specialist", capabilities={"skills": [{"id": "translate"}]})
        server = _make_server(agents=[a1, a2])
        assert service._pick_agent(server, skill_id="translate") is a2

    def test_falls_back_when_skill_not_found(self, service):
        a1 = _make_agent(name="general")
        server = _make_server(agents=[a1])
        assert service._pick_agent(server, skill_id="nonexistent") is a1


# ---------------------------------------------------------------------------
# _resolve_tenant
# ---------------------------------------------------------------------------
class TestResolveTenant:
    def test_interface_tenant_default(self, service):
        server = _make_server()
        iface = _make_interface(tenant="default-tenant")
        assert service._resolve_tenant(server, iface) == "default-tenant"

    def test_agent_tenant_overrides_interface(self, service):
        server = _make_server()
        iface = _make_interface(tenant="interface-tenant")
        agent = _make_agent(tenant="agent-tenant")
        assert service._resolve_tenant(server, iface, agent=agent) == "agent-tenant"

    def test_caller_tenant_rejected_by_default(self, service):
        server = _make_server()
        iface = _make_interface(tenant="default-tenant")
        result = service._resolve_tenant(server, iface, caller_tenant="caller-tenant")
        assert result == "default-tenant"

    def test_caller_tenant_accepted_when_enabled(self, service):
        server = _make_server()
        iface = _make_interface(config={"allow_caller_tenant_override": True})
        result = service._resolve_tenant(server, iface, caller_tenant="caller-tenant")
        assert result == "caller-tenant"

    def test_caller_tenant_validated_against_allowlist(self, service):
        server = _make_server()
        iface = _make_interface(config={"allow_caller_tenant_override": True, "allowed_tenants": ["allowed-1"]})
        # Allowed tenant passes.
        assert service._resolve_tenant(server, iface, caller_tenant="allowed-1") == "allowed-1"
        # Disallowed tenant falls through to interface default.
        assert service._resolve_tenant(server, iface, caller_tenant="forbidden") is None

    def test_none_when_no_tenant_set(self, service):
        server = _make_server()
        iface = _make_interface(tenant=None)
        assert service._resolve_tenant(server, iface) is None


# ---------------------------------------------------------------------------
# Agent Card Generation
# ---------------------------------------------------------------------------
class TestGetAgentCard:
    def test_basic_card_generation(self, service, db):
        agent = _make_agent(capabilities={"streaming": True, "skills": [{"id": "echo", "name": "Echo"}]})
        server = _make_server(
            name="My Server",
            description="Test desc",
            icon="https://icon.png",
            interfaces=[_make_interface(binding="jsonrpc", version="1.0")],
            agents=[agent],
        )
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        card = service.get_agent_card(db, "srv-1", base_url="https://gw.example.com")
        assert card["name"] == "My Server"
        assert card["description"] == "Test desc"
        assert card["iconUrl"] == "https://icon.png"
        assert len(card["supportedInterfaces"]) == 1
        assert card["supportedInterfaces"][0]["url"] == "https://gw.example.com/servers/srv-1/a2a"
        assert card["supportedInterfaces"][0]["protocolBinding"] == "jsonrpc"
        assert card["capabilities"]["streaming"] is True
        assert len(card["capabilities"]["skills"]) == 1

    def test_card_with_override(self, service, db):
        server = _make_server(
            interfaces=[_make_interface(config={"agent_card_override": {"name": "Custom Name", "description": "Custom desc"}})],
            agents=[_make_agent()],
        )
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        card = service.get_agent_card(db, "srv-1")
        assert card["name"] == "Custom Name"
        assert card["description"] == "Custom desc"

    def test_card_aggregates_skills_from_multiple_agents(self, service, db):
        a1 = _make_agent(name="a1", capabilities={"skills": [{"id": "s1"}, {"id": "s2"}]})
        a2 = _make_agent(name="a2", capabilities={"skills": [{"id": "s2"}, {"id": "s3"}]})
        server = _make_server(interfaces=[_make_interface()], agents=[a1, a2])
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        card = service.get_agent_card(db, "srv-1")
        skill_ids = [s["id"] for s in card["capabilities"]["skills"]]
        assert "s1" in skill_ids
        assert "s2" in skill_ids
        assert "s3" in skill_ids
        # s2 should only appear once (deduplication).
        assert skill_ids.count("s2") == 1

    def test_card_includes_tenant_when_set(self, service, db):
        server = _make_server(
            interfaces=[_make_interface(tenant="acme-corp")],
            agents=[_make_agent()],
        )
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        card = service.get_agent_card(db, "srv-1")
        assert card["supportedInterfaces"][0]["tenant"] == "acme-corp"

    def test_card_omits_tenant_when_none(self, service, db):
        server = _make_server(
            interfaces=[_make_interface(tenant=None)],
            agents=[_make_agent()],
        )
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        card = service.get_agent_card(db, "srv-1")
        assert "tenant" not in card["supportedInterfaces"][0]

    def test_card_skips_disabled_agents(self, service, db):
        a1 = _make_agent(name="active", capabilities={"skills": [{"id": "s1"}]})
        a2 = _make_agent(name="disabled", enabled=False, capabilities={"skills": [{"id": "s2"}]})
        server = _make_server(interfaces=[_make_interface()], agents=[a1, a2])
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        card = service.get_agent_card(db, "srv-1")
        skill_ids = [s["id"] for s in card["capabilities"]["skills"]]
        assert "s1" in skill_ids
        assert "s2" not in skill_ids


# ---------------------------------------------------------------------------
# Send Message
# ---------------------------------------------------------------------------
class TestSendMessage:
    @pytest.mark.asyncio
    async def test_routes_to_first_agent(self, service, mock_a2a_service, db):
        agent = _make_agent(name="my-agent")
        server = _make_server(interfaces=[_make_interface()], agents=[agent])
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        result = await service.send_message(db, "srv-1", {"message": {"role": "user"}}, "user-1")
        mock_a2a_service.send_message.assert_called_once()
        call_kwargs = mock_a2a_service.send_message.call_args.kwargs
        assert call_kwargs["agent_name"] == "my-agent"

    @pytest.mark.asyncio
    async def test_creates_task_mapping(self, service, mock_a2a_service, db):
        agent = _make_agent(name="my-agent")
        server = _make_server(interfaces=[_make_interface()], agents=[agent])
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        result = await service.send_message(db, "srv-1", {}, "user-1")
        # The task mapping should have been created and committed.
        db.add.assert_called_once()
        db.commit.assert_called_once()
        mapping = db.add.call_args[0][0]
        assert mapping.server_id == "srv-1"
        assert mapping.agent_name == "my-agent"
        assert mapping.agent_task_id == "task-abc"


# ---------------------------------------------------------------------------
# Get Task
# ---------------------------------------------------------------------------
class TestGetTask:
    @pytest.mark.asyncio
    async def test_resolves_via_mapping(self, service, mock_a2a_service, db):
        mapping = MagicMock()
        mapping.agent_name = "my-agent"
        mapping.agent_task_id = "agent-task-xyz"
        db.query.return_value.filter.return_value.first.return_value = mapping

        result = await service.get_task(db, "srv-1", "server-task-123", "user-1")
        mock_a2a_service.get_task.assert_called_once()
        call_kwargs = mock_a2a_service.get_task.call_args.kwargs
        assert call_kwargs["agent_name"] == "my-agent"
        assert call_kwargs["task_id"] == "agent-task-xyz"
        # Response should use the server task ID, not the agent's.
        assert result["result"]["id"] == "server-task-123"

    @pytest.mark.asyncio
    async def test_raises_when_mapping_not_found(self, service, db):
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(A2AAgentNotFoundError, match="not found"):
            await service.get_task(db, "srv-1", "missing-task", "user-1")


# ---------------------------------------------------------------------------
# Cancel Task
# ---------------------------------------------------------------------------
class TestCancelTask:
    @pytest.mark.asyncio
    async def test_cancels_via_mapping(self, service, mock_a2a_service, db):
        mapping = MagicMock()
        mapping.agent_name = "my-agent"
        mapping.agent_task_id = "agent-task-xyz"
        db.query.return_value.filter.return_value.first.return_value = mapping

        result = await service.cancel_task(db, "srv-1", "server-task-123", "user-1")
        mock_a2a_service.cancel_task.assert_called_once()
        assert result["result"]["id"] == "server-task-123"

    @pytest.mark.asyncio
    async def test_raises_when_mapping_not_found(self, service, db):
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(A2AAgentNotFoundError, match="not found"):
            await service.cancel_task(db, "srv-1", "missing-task", "user-1")


# ---------------------------------------------------------------------------
# List Tasks
# ---------------------------------------------------------------------------
class TestListTasks:
    @pytest.mark.asyncio
    async def test_aggregates_from_all_agents(self, service, mock_a2a_service, db):
        a1 = _make_agent(name="agent-1")
        a2 = _make_agent(name="agent-2")
        server = _make_server(interfaces=[_make_interface()], agents=[a1, a2])
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        result = await service.list_tasks(db, "srv-1", {}, "user-1")
        assert mock_a2a_service.list_tasks.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_disabled_agents(self, service, mock_a2a_service, db):
        a1 = _make_agent(name="active")
        a2 = _make_agent(name="disabled", enabled=False)
        server = _make_server(interfaces=[_make_interface()], agents=[a1, a2])
        db.query.return_value.options.return_value.filter.return_value.first.return_value = server

        await service.list_tasks(db, "srv-1", {}, "user-1")
        assert mock_a2a_service.list_tasks.call_count == 1


# ---------------------------------------------------------------------------
# has_a2a_interface & list_a2a_servers
# ---------------------------------------------------------------------------
class TestDiscovery:
    def test_has_a2a_interface_true(self, service, db):
        db.query.return_value.filter.return_value.count.return_value = 1
        assert service.has_a2a_interface(db, "srv-1") is True

    def test_has_a2a_interface_false(self, service, db):
        db.query.return_value.filter.return_value.count.return_value = 0
        assert service.has_a2a_interface(db, "srv-1") is False

    def test_list_a2a_servers(self, service, db):
        iface = _make_interface(binding="jsonrpc", version="1.0", tenant="acme")
        server = _make_server(name="Server A", interfaces=[iface])
        db.query.return_value.join.return_value.filter.return_value.options.return_value.distinct.return_value.all.return_value = [server]

        result = service.list_a2a_servers(db)
        assert len(result) == 1
        assert result[0]["name"] == "Server A"
        assert result[0]["a2a_interfaces"][0]["binding"] == "jsonrpc"
        assert result[0]["a2a_interfaces"][0]["tenant"] == "acme"
