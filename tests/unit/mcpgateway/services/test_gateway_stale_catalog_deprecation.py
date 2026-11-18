# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_stale_catalog_deprecation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for issue #7014: stale catalog reconciliation must deprecate
tools, resources, and prompts instead of hard-deleting them, and may only
delete entries after GATEWAY_STALE_CATALOG_RETENTION_DAYS.
"""

# Standard
from datetime import timedelta
from types import SimpleNamespace

# Third-Party
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import PromptMetric
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import ResourceMetric
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric
from mcpgateway.db import server_prompt_association, server_resource_association, server_tool_association, utc_now
from mcpgateway.services.gateway_service import GatewayCatalogSyncResult, GatewayService, MCP_SYNC_CREATED_VIA_VALUES


def _engine():
    """Create an in-memory SQLite engine with the full schema."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture()
def db_session():
    """Yield a transactional SQLite session and dispose the engine afterwards."""
    engine = _engine()
    Session = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _gateway(session, gateway_id: str = "gw-1") -> DbGateway:
    """Insert a minimal gateway used as the catalog parent."""
    gateway = DbGateway(
        id=gateway_id,
        name="Test Gateway",
        slug="test-gateway",
        url="https://example.com/mcp",
        transport="SSE",
        capabilities={},
    )
    session.add(gateway)
    session.flush()
    return gateway


def _tool(session, gateway: DbGateway, *, name: str = "alpha", tool_id: str = "tool-alpha", created_via: str = "health_check", enabled: bool = True) -> DbTool:
    """Insert a gateway tool with the given identity."""
    tool = DbTool(
        id=tool_id,
        original_name=name,
        custom_name=name,
        custom_name_slug=name,
        name=f"test-gateway-{name}",
        description="alpha tool",
        original_description="alpha tool",
        input_schema={"type": "object", "properties": {}},
        gateway_id=gateway.id,
        created_via=created_via,
        enabled=enabled,
        deprecated=False,
        tags=[],
    )
    session.add(tool)
    session.flush()
    if tool not in gateway.tools:
        gateway.tools.append(tool)
    return tool


def _resource(session, gateway: DbGateway, *, uri: str = "res://alpha", resource_id: str = "res-alpha", created_via: str = "health_check") -> DbResource:
    """Insert a gateway resource with the given URI."""
    resource = DbResource(
        id=resource_id,
        uri=uri,
        name="alpha",
        original_name="alpha",
        gateway_id=gateway.id,
        created_via=created_via,
        enabled=True,
        deprecated=False,
        tags=[],
    )
    session.add(resource)
    session.flush()
    if resource not in gateway.resources:
        gateway.resources.append(resource)
    return resource


def _prompt(session, gateway: DbGateway, *, name: str = "alpha", prompt_id: str = "prompt-alpha", created_via: str = "health_check") -> DbPrompt:
    """Insert a gateway prompt with the given identity."""
    prompt = DbPrompt(
        id=prompt_id,
        original_name=name,
        custom_name=name,
        custom_name_slug=name,
        name=name,
        template="Hello",
        argument_schema={},
        gateway_id=gateway.id,
        created_via=created_via,
        enabled=True,
        deprecated=False,
        tags=[],
    )
    session.add(prompt)
    session.flush()
    if prompt not in gateway.prompts:
        gateway.prompts.append(prompt)
    return prompt


def _empty_sync(**overrides) -> GatewayCatalogSyncResult:
    """Return a catalog sync result, empty unless overrides are provided."""
    defaults = {
        "new_tool_names": [],
        "new_resource_uris": [],
        "new_prompt_names": [],
        "tools_to_add": [],
        "resources_to_add": [],
        "prompts_to_add": [],
    }
    defaults.update(overrides)
    return GatewayCatalogSyncResult(**defaults)


def _reconcile(session, gateway, catalog_sync, *, skip_stale_cleanup: bool = False):
    """Run catalog reconciliation with the MCP-sync created_via safelist."""
    return GatewayService()._reconcile_gateway_catalog(
        session,
        gateway=gateway,
        catalog_sync=catalog_sync,
        log_context="unit test",
        stale_created_via_values=MCP_SYNC_CREATED_VIA_VALUES,
        skip_stale_cleanup=skip_stale_cleanup,
    )


def test_stale_tool_is_deprecated_not_deleted_and_keeps_membership_metrics_and_disabled_state(db_session):
    """A missing upstream tool stays in place with associations, metrics, and enabled=False."""
    gateway = _gateway(db_session)
    tool = _tool(db_session, gateway, enabled=False)
    server = DbServer(id="server-1", name="virtual", tags=[])
    db_session.add(server)
    db_session.flush()
    tool.servers.append(server)
    db_session.add(ToolMetric(tool_id=tool.id, response_time=0.25, is_success=True))
    db_session.flush()
    original_id = tool.id

    result = _reconcile(db_session, gateway, _empty_sync(new_resource_uris=None, new_prompt_names=None))
    db_session.commit()

    persisted = db_session.get(DbTool, original_id)
    assert persisted is not None
    assert persisted.id == original_id
    assert persisted.deprecated is True
    assert persisted.deprecated_at is not None
    assert persisted.enabled is False
    assert result.tools_deprecated == 1
    assert result.tools_removed == 0
    assert db_session.execute(select(func.count()).select_from(ToolMetric).where(ToolMetric.tool_id == original_id)).scalar() == 1
    assert db_session.execute(select(func.count()).select_from(server_tool_association).where(server_tool_association.c.tool_id == original_id)).scalar() == 1


def test_stale_resource_and_prompt_are_deprecated_not_deleted(db_session):
    """Resources and prompts follow the same deprecate-instead-of-delete path."""
    gateway = _gateway(db_session)
    resource = _resource(db_session, gateway)
    prompt = _prompt(db_session, gateway)
    server = DbServer(id="server-1", name="virtual", tags=[])
    db_session.add(server)
    db_session.flush()
    resource.servers.append(server)
    prompt.servers.append(server)
    db_session.add(ResourceMetric(resource_id=resource.id, response_time=0.1, is_success=True))
    db_session.add(PromptMetric(prompt_id=prompt.id, response_time=0.1, is_success=True))
    db_session.flush()
    resource_id, prompt_id = resource.id, prompt.id

    result = _reconcile(db_session, gateway, _empty_sync(new_tool_names=["unused"]))
    db_session.commit()

    assert db_session.get(DbResource, resource_id) is not None
    assert db_session.get(DbPrompt, prompt_id) is not None
    assert db_session.get(DbResource, resource_id).deprecated is True
    assert db_session.get(DbPrompt, prompt_id).deprecated is True
    assert result.resources_deprecated == 1
    assert result.prompts_deprecated == 1
    assert result.resources_removed == 0
    assert result.prompts_removed == 0
    assert db_session.execute(select(func.count()).select_from(server_resource_association).where(server_resource_association.c.resource_id == resource_id)).scalar() == 1
    assert db_session.execute(select(func.count()).select_from(server_prompt_association).where(server_prompt_association.c.prompt_id == prompt_id)).scalar() == 1
    assert db_session.execute(select(func.count()).select_from(ResourceMetric).where(ResourceMetric.resource_id == resource_id)).scalar() == 1
    assert db_session.execute(select(func.count()).select_from(PromptMetric).where(PromptMetric.prompt_id == prompt_id)).scalar() == 1


def test_reappearance_clears_deprecated_and_keeps_the_same_id(db_session):
    """When a stale tool returns, the same row is reused and deprecation is cleared."""
    gateway = _gateway(db_session)
    tool = _tool(db_session, gateway, enabled=False)
    server = DbServer(id="server-1", name="virtual", tags=[])
    db_session.add(server)
    db_session.flush()
    tool.servers.append(server)
    db_session.add(ToolMetric(tool_id=tool.id, response_time=0.25, is_success=True))
    db_session.flush()
    original_id = tool.id

    _reconcile(db_session, gateway, _empty_sync(new_resource_uris=None, new_prompt_names=None))
    db_session.commit()
    assert db_session.get(DbTool, original_id).deprecated is True

    upstream = SimpleNamespace(
        name="alpha",
        description="alpha tool",
        request_type="SSE",
        headers=None,
        input_schema={"type": "object", "properties": {}},
        output_schema=None,
        jsonpath_filter="",
        extension_metadata=None,
        visibility=None,
        title=None,
    )
    service = GatewayService()
    added = service._update_or_create_tools(db_session, [upstream], gateway, created_via="health_check")
    result = _reconcile(
        db_session,
        gateway,
        _empty_sync(new_tool_names=["alpha"], new_resource_uris=None, new_prompt_names=None, tools_to_add=added),
    )
    db_session.commit()

    persisted = db_session.get(DbTool, original_id)
    assert added == []
    assert persisted is not None
    assert persisted.deprecated is False
    assert persisted.deprecated_at is None
    assert persisted.enabled is False
    assert result.tools_deprecated == 0
    assert result.tools_removed == 0
    assert result.tools_added == 0
    assert db_session.execute(select(func.count()).select_from(DbTool).where(DbTool.gateway_id == gateway.id)).scalar() == 1
    assert db_session.execute(select(func.count()).select_from(server_tool_association).where(server_tool_association.c.tool_id == original_id)).scalar() == 1
    assert db_session.execute(select(func.count()).select_from(ToolMetric).where(ToolMetric.tool_id == original_id)).scalar() == 1


def test_resource_and_prompt_reappearance_clears_deprecated(db_session):
    """Resources and prompts keep their id and lose deprecation on reappearance."""
    gateway = _gateway(db_session)
    resource = _resource(db_session, gateway)
    prompt = _prompt(db_session, gateway)
    resource_id, prompt_id = resource.id, prompt.id
    _reconcile(db_session, gateway, _empty_sync())
    db_session.commit()

    service = GatewayService()
    upstream_resource = SimpleNamespace(uri="res://alpha", name="alpha", description=None, mime_type=None, uri_template=None, extension_metadata=None, visibility=None, title=None)
    upstream_prompt = SimpleNamespace(name="alpha", description=None, template="Hello", arguments=[], visibility=None, title=None)
    added_resources = service._update_or_create_resources(db_session, [upstream_resource], gateway, created_via="health_check")
    added_prompts = service._update_or_create_prompts(db_session, [upstream_prompt], gateway, created_via="health_check")
    _reconcile(
        db_session,
        gateway,
        _empty_sync(new_tool_names=[], new_resource_uris=["res://alpha"], new_prompt_names=["alpha"], resources_to_add=added_resources, prompts_to_add=added_prompts),
    )
    db_session.commit()

    assert added_resources == []
    assert added_prompts == []
    assert db_session.get(DbResource, resource_id).deprecated is False
    assert db_session.get(DbResource, resource_id).deprecated_at is None
    assert db_session.get(DbPrompt, prompt_id).deprecated is False
    assert db_session.get(DbPrompt, prompt_id).deprecated_at is None


def test_cleanup_deletes_only_after_retention_period(db_session, monkeypatch):
    """A previously deprecated tool is deleted only after the configured retention period."""
    monkeypatch.setattr(settings, "gateway_stale_catalog_retention_days", 30)
    gateway = _gateway(db_session)
    tool = _tool(db_session, gateway)
    server = DbServer(id="server-1", name="virtual", tags=[])
    db_session.add(server)
    db_session.flush()
    tool.servers.append(server)
    db_session.add(ToolMetric(tool_id=tool.id, response_time=0.25, is_success=True))
    tool.deprecated = True
    tool.deprecated_at = utc_now() - timedelta(days=31)
    db_session.flush()
    original_id = tool.id

    result = _reconcile(db_session, gateway, _empty_sync(new_resource_uris=None, new_prompt_names=None))
    db_session.commit()

    assert result.tools_removed == 1
    assert result.tools_deprecated == 0
    assert db_session.get(DbTool, original_id) is None
    assert db_session.execute(select(func.count()).select_from(ToolMetric).where(ToolMetric.tool_id == original_id)).scalar() == 0
    assert db_session.execute(select(func.count()).select_from(server_tool_association).where(server_tool_association.c.tool_id == original_id)).scalar() == 0


def test_cleanup_disabled_when_retention_is_zero(db_session, monkeypatch):
    """Retention 0 never hard-deletes, even when deprecated_at is old."""
    monkeypatch.setattr(settings, "gateway_stale_catalog_retention_days", 0)
    gateway = _gateway(db_session)
    tool = _tool(db_session, gateway)
    tool.deprecated = True
    tool.deprecated_at = utc_now() - timedelta(days=365)
    db_session.flush()
    original_id = tool.id

    result = _reconcile(db_session, gateway, _empty_sync(new_resource_uris=None, new_prompt_names=None))
    db_session.commit()

    assert result.tools_removed == 0
    assert db_session.get(DbTool, original_id) is not None
    assert db_session.get(DbTool, original_id).deprecated is True


def test_single_partial_list_does_not_delete_immediately(db_session, monkeypatch):
    """A partial catalog deprecates the missing item and cannot wipe state on the first pass."""
    monkeypatch.setattr(settings, "gateway_stale_catalog_retention_days", 30)
    gateway = _gateway(db_session)
    kept = _tool(db_session, gateway, name="kept", tool_id="tool-kept")
    missing = _tool(db_session, gateway, name="missing", tool_id="tool-missing")

    result = _reconcile(db_session, gateway, _empty_sync(new_tool_names=["kept"], new_resource_uris=None, new_prompt_names=None))
    db_session.commit()

    assert result.tools_deprecated == 1
    assert result.tools_removed == 0
    assert db_session.get(DbTool, kept.id).deprecated is False
    assert db_session.get(DbTool, missing.id).deprecated is True
    assert db_session.get(DbTool, missing.id).deprecated_at is not None


def test_skip_stale_cleanup_leaves_state_untouched(db_session):
    """skip_stale_cleanup must neither deprecate nor delete."""
    gateway = _gateway(db_session)
    tool = _tool(db_session, gateway)
    original_id = tool.id

    result = _reconcile(db_session, gateway, _empty_sync(new_resource_uris=None, new_prompt_names=None), skip_stale_cleanup=True)
    db_session.commit()

    persisted = db_session.get(DbTool, original_id)
    assert persisted.deprecated is False
    assert persisted.deprecated_at is None
    assert result.tools_deprecated == 0
    assert result.tools_removed == 0


def test_user_created_rows_are_not_deprecated(db_session):
    """Only MCP-synced created_via values are eligible for stale catalog handling."""
    gateway = _gateway(db_session)
    user_tool = _tool(db_session, gateway, name="user", tool_id="tool-user", created_via="ui")
    mcp_tool = _tool(db_session, gateway, name="mcp", tool_id="tool-mcp", created_via="notification_service")

    result = _reconcile(db_session, gateway, _empty_sync(new_resource_uris=None, new_prompt_names=None))
    db_session.commit()

    assert db_session.get(DbTool, user_tool.id).deprecated is False
    assert db_session.get(DbTool, mcp_tool.id).deprecated is True
    assert result.tools_deprecated == 1
    assert result.tools_removed == 0


def test_second_refresh_does_not_reset_deprecated_at(db_session):
    """A later stale refresh must not restart the retention timer."""
    gateway = _gateway(db_session)
    tool = _tool(db_session, gateway)
    _reconcile(db_session, gateway, _empty_sync(new_resource_uris=None, new_prompt_names=None))
    db_session.commit()
    first_seen = db_session.get(DbTool, tool.id).deprecated_at

    result = _reconcile(db_session, gateway, _empty_sync(new_resource_uris=None, new_prompt_names=None))
    db_session.commit()

    assert db_session.get(DbTool, tool.id).deprecated_at == first_seen
    assert result.tools_deprecated == 0
