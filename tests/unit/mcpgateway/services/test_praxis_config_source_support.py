"""Shared database setup for Praxis source contract tests."""

from collections.abc import Generator

from cpex.framework import OnError, PluginMode
from cpex.framework.models import Config, PluginConfig
import pytest
from sqlalchemy import Engine, delete, insert
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import (
    A2AAgent,
    EmailTeam,
    EmailUser,
    Gateway,
    PraxisTarget,
    PraxisTargetServer,
    Prompt,
    Resource,
    Server,
    Tool,
    ToolPluginBinding,
    server_a2a_association,
    server_prompt_association,
    server_resource_association,
    server_tool_association,
)
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService, PraxisToolRuntimeOverrides


def _operator_config() -> Config:
    return Config(
        plugins=[
            PluginConfig(
                name="SecurityPlugin",
                kind="plugins.security.SecurityPlugin",
                hooks=["http_auth_check_permission"],
                tags=["security"],
                mode=PluginMode.DISABLED,
                on_error=OnError.IGNORE,
                priority=90,
                config={"policy": "base"},
            )
        ]
    )


@pytest.fixture
def source_factory(test_engine: Engine) -> Generator[sessionmaker[Session], None, None]:
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    with factory() as session:
        session.execute(delete(server_a2a_association))
        session.execute(delete(server_prompt_association))
        session.execute(delete(server_resource_association))
        session.execute(delete(server_tool_association))
        for model in (ToolPluginBinding, PraxisTargetServer, A2AAgent, Prompt, Resource, Tool, Gateway, PraxisTarget, Server, EmailTeam, EmailUser):
            session.query(model).delete()
        session.commit()
    yield factory


def seed_graph(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        user = EmailUser(id="source-user", email="admin@example.test", password_hash="not-a-real-password-hash")
        team = EmailTeam(id="team-alpha", name="Team alpha", slug="praxis-source-team-alpha", created_by=user.email)
        gateway = Gateway(id="gateway-stream", name="Gateway", slug="gateway", url="https://mcp.example.test/mcp", transport="STREAMABLEHTTP", capabilities={})
        unsupported_gateway = Gateway(id="gateway-sse", name="SSE Gateway", slug="sse-gateway", url="https://sse.example.test/sse", transport="SSE", capabilities={})
        server = Server(id="server-team", name="Team server", visibility="team", team_id="team-alpha")
        public_server = Server(id="server-platform", name="Platform server", visibility="public")
        unassigned = Server(id="server-unassigned", name="Unassigned")
        tool = Tool(id="tool-1", original_name="summarize", name="gateway-summarize", custom_name="summarize", custom_name_slug="summarize", url=gateway.url, input_schema={"type": "object"}, gateway_id=gateway.id, visibility="team", team_id="team-alpha")
        disabled_tool = Tool(id="tool-disabled", original_name="disabled", name="gateway-disabled", custom_name="disabled", custom_name_slug="disabled", url=gateway.url, input_schema={}, gateway_id=gateway.id, enabled=False)
        unsupported_tool = Tool(id="tool-sse", original_name="legacy", name="sse-legacy", custom_name="legacy", custom_name_slug="legacy", url=unsupported_gateway.url, input_schema={}, gateway_id=unsupported_gateway.id)
        resource = Resource(id="resource-1", name="guide", uri="docs://guide", gateway_id=gateway.id)
        prompt = Prompt(id="prompt-1", original_name="draft", custom_name="draft", custom_name_slug="draft", name="gateway-draft", template="Draft", argument_schema={}, gateway_id=gateway.id)
        a2a = A2AAgent(id="a2a-1", name="Agent", slug="agent", endpoint_url="https://agent.example.test", capabilities={}, config={})
        session.add_all(
            [
                PraxisTarget(id="target-alpha", name="Target alpha", created_by=user.email),
                PraxisTarget(id="target-beta", name="Target beta", created_by=user.email),
                user,
                team,
                gateway,
                unsupported_gateway,
                server,
                public_server,
                unassigned,
                tool,
                disabled_tool,
                unsupported_tool,
                resource,
                prompt,
                a2a,
            ]
        )
        session.flush()
        session.add_all(
            [
                PraxisTargetServer(target_id="target-alpha", server_id=server.id, assigned_by=user.email),
                PraxisTargetServer(target_id="target-alpha", server_id=public_server.id, assigned_by=user.email),
                ToolPluginBinding(team_id=team.id, tool_name="summarize", plugin_id="SecurityPlugin", mode="enforce_ignore_error", priority=10, config={"policy": "bound"}, created_by=user.email, updated_by=user.email),
            ]
        )
        session.execute(insert(server_tool_association), [{"server_id": server.id, "tool_id": item.id} for item in (tool, disabled_tool, unsupported_tool)])
        session.execute(insert(server_resource_association), {"server_id": server.id, "resource_id": resource.id})
        session.execute(insert(server_prompt_association), {"server_id": server.id, "prompt_id": prompt.id})
        session.execute(insert(server_a2a_association), {"server_id": server.id, "a2a_agent_id": a2a.id})
        session.commit()


def source_service(factory: sessionmaker[Session], overrides: tuple[PraxisToolRuntimeOverrides, ...] = ()) -> PraxisConfigSourceService:
    return PraxisConfigSourceService(factory, _operator_config(), overrides)
