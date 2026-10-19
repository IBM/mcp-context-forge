# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_instructions_resolver.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the choice of ``instructions`` text for a virtual server.
"""

# Standard
from types import SimpleNamespace
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.common.models import DEFAULT_SERVER_INSTRUCTIONS
from mcpgateway.db import A2AAgent, Base, Gateway, Prompt, Resource, Server, Tool
from mcpgateway.services.server_service import ServerService

UPSTREAM_TEXT = "Call the clock tools in UTC."


@pytest.fixture
def session_factory():
    """Isolated in-memory database shared by every session of one test."""
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def seed(session_factory):
    """Build catalog rows and return a function that resolves instructions for a virtual server."""
    db: Session = session_factory()

    def gateway(name: str, text: Optional[str] = None) -> Gateway:
        row = Gateway(name=name, slug=name, url=f"https://{name}.example.com/mcp", capabilities={}, upstream_instructions=text)
        db.add(row)
        db.flush()
        return row

    def tool(name: str, owner: Optional[Gateway] = None) -> Tool:
        row = Tool(original_name=name, custom_name=name, custom_name_slug=name, input_schema={"type": "object"}, gateway_id=owner.id if owner else None)
        db.add(row)
        db.flush()
        return row

    def resource(uri: str, owner: Optional[Gateway] = None) -> Resource:
        row = Resource(uri=uri, name=uri, gateway_id=owner.id if owner else None)
        db.add(row)
        db.flush()
        return row

    def prompt(name: str, owner: Optional[Gateway] = None) -> Prompt:
        row = Prompt(original_name=name, custom_name=name, custom_name_slug=name, template="hi", argument_schema={}, gateway_id=owner.id if owner else None)
        db.add(row)
        db.flush()
        return row

    def server(*items: Any, agent: bool = False, instructions: Optional[str] = None) -> str:
        row = Server(name="virtual", instructions=instructions)
        for item in items:
            if isinstance(item, Tool):
                row.tools.append(item)
            elif isinstance(item, Resource):
                row.resources.append(item)
            else:
                row.prompts.append(item)
        if agent:
            row.a2a_agents.append(A2AAgent(name="agent", slug="agent", endpoint_url="http://example.com"))
        db.add(row)
        db.commit()
        return row.id

    def resolve(server_id: str, user_email: Optional[str] = None, token_teams: Optional[List[str]] = ()) -> Optional[str]:
        with patch("mcpgateway.services.server_service.SessionLocal", session_factory):
            return ServerService._resolve_instructions_sync(server_id, user_email=user_email, token_teams=token_teams)  # pylint: disable=protected-access

    yield type("Seed", (), {"gateway": staticmethod(gateway), "tool": staticmethod(tool), "resource": staticmethod(resource), "prompt": staticmethod(prompt), "server": staticmethod(server), "resolve": staticmethod(resolve)})
    db.close()


def test_all_items_from_one_upstream_send_its_text(seed):
    """Tools, resources and prompts from one upstream server: its text."""
    up = seed.gateway("clock", UPSTREAM_TEXT)
    sid = seed.server(seed.tool("now", up), seed.resource("clock://tz", up), seed.prompt("greet", up))
    assert seed.resolve(sid) == UPSTREAM_TEXT


def test_subset_of_tools_from_one_upstream_sends_its_text(seed):
    """A strict subset of one upstream server's tools, with no resources or prompts: its text."""
    up = seed.gateway("clock", UPSTREAM_TEXT)
    seed.tool("unused", up)
    sid = seed.server(seed.tool("now", up))
    assert seed.resolve(sid) == UPSTREAM_TEXT


def test_two_upstreams_send_default_text(seed):
    """Items from two upstream servers: the default text."""
    sid = seed.server(seed.tool("a", seed.gateway("one", "one text")), seed.tool("b", seed.gateway("two", "two text")))
    assert seed.resolve(sid) == DEFAULT_SERVER_INSTRUCTIONS


def test_local_plus_federated_send_default_text(seed):
    """A local tool next to a federated tool: the default text."""
    up = seed.gateway("clock", UPSTREAM_TEXT)
    sid = seed.server(seed.tool("local"), seed.tool("remote", up))
    assert seed.resolve(sid) == DEFAULT_SERVER_INSTRUCTIONS


def test_only_local_items_send_default_text(seed):
    """Only local items: the default text."""
    assert seed.resolve(seed.server(seed.tool("local"))) == DEFAULT_SERVER_INSTRUCTIONS


def test_empty_server_sends_default_text(seed):
    """A server with no items: the default text."""
    assert seed.resolve(seed.server()) == DEFAULT_SERVER_INSTRUCTIONS


def test_a2a_agent_sends_default_text(seed):
    """A single-upstream server with an A2A agent: the default text."""
    up = seed.gateway("clock", UPSTREAM_TEXT)
    sid = seed.server(seed.tool("now", up), agent=True)
    assert seed.resolve(sid) == DEFAULT_SERVER_INSTRUCTIONS


def test_upstream_without_text_sends_default(seed):
    """A single-upstream server whose upstream has no text sends the default text, not None."""
    sid = seed.server(seed.tool("now", seed.gateway("clock")))
    assert seed.resolve(sid) == DEFAULT_SERVER_INSTRUCTIONS


def test_upstream_with_empty_text_sends_default(seed):
    """A single-upstream server whose upstream stored an empty string sends the default text."""
    sid = seed.server(seed.tool("now", seed.gateway("clock", "")))
    assert seed.resolve(sid) == DEFAULT_SERVER_INSTRUCTIONS


@pytest.mark.asyncio
async def test_lookup_failure_sends_default_text():
    """A database failure never fails the handshake."""
    with patch.object(ServerService, "_resolve_instructions_sync", side_effect=RuntimeError("db down")):
        assert await ServerService().resolve_instructions("any") == DEFAULT_SERVER_INSTRUCTIONS


def test_operator_override_beats_the_upstream_text(seed):
    """An operator override wins over the text of the single upstream server."""
    up = seed.gateway("clock", UPSTREAM_TEXT)
    sid = seed.server(seed.tool("now", up), instructions="Operator text")
    assert seed.resolve(sid) == "Operator text"


def test_operator_override_applies_to_a_server_without_a_single_upstream(seed):
    """An operator override replaces the default text on an empty server."""
    assert seed.resolve(seed.server(instructions="Operator text")) == "Operator text"


def test_empty_override_sends_no_instructions(seed):
    """An empty-string override suppresses the upstream text."""
    up = seed.gateway("clock", UPSTREAM_TEXT)
    sid = seed.server(seed.tool("now", up), instructions="")
    assert seed.resolve(sid) is None


def test_unset_override_falls_back_to_the_upstream_text(seed):
    """A NULL override leaves the single-upstream rule in charge."""
    up = seed.gateway("clock", UPSTREAM_TEXT)
    sid = seed.server(seed.tool("now", up), instructions=None)
    assert seed.resolve(sid) == UPSTREAM_TEXT


# ---------------------------------------------------------------------------
# Visibility deny-path tests (CWE-639 / CWE-200)
# ---------------------------------------------------------------------------


@pytest.fixture
def vis_seed(session_factory):
    """Fixture that seeds servers with varying visibility for deny-path tests."""
    db: Session = session_factory()
    up = Gateway(name="up", slug="up", url="https://up.example.com/mcp", capabilities={}, upstream_instructions=UPSTREAM_TEXT)
    db.add(up)
    db.flush()

    def _server(visibility: str = "public", owner_email: Optional[str] = None, team_id: Optional[str] = None) -> str:
        name = f"t{len(db.query(Tool).all())}"
        t = Tool(original_name=name, custom_name=name, custom_name_slug=name, input_schema={"type": "object"}, gateway_id=up.id)
        db.add(t)
        db.flush()
        row = Server(name="vs", visibility=visibility, owner_email=owner_email, team_id=team_id)
        row.tools.append(t)
        db.add(row)
        db.commit()
        return row.id

    def _resolve(server_id: str, user_email: Optional[str] = None, token_teams: Optional[List[str]] = ()) -> Optional[str]:
        with patch("mcpgateway.services.server_service.SessionLocal", session_factory):
            return ServerService._resolve_instructions_sync(server_id, user_email=user_email, token_teams=token_teams)  # pylint: disable=protected-access

    yield type("VisSeed", (), {"server": staticmethod(_server), "resolve": staticmethod(_resolve)})
    db.close()


def test_public_server_visible_to_public_only_token(vis_seed):
    """A public server is visible to a public-only token (token_teams=[])."""
    sid = vis_seed.server(visibility="public")
    assert vis_seed.resolve(sid, user_email=None, token_teams=[]) == UPSTREAM_TEXT


def test_private_server_not_visible_to_public_only_token(vis_seed):
    """A private server is not visible to a public-only token; returns default text."""
    sid = vis_seed.server(visibility="private", owner_email="alice@example.com")
    assert vis_seed.resolve(sid, user_email=None, token_teams=[]) == DEFAULT_SERVER_INSTRUCTIONS


def test_private_server_visible_to_owner(vis_seed):
    """A private server is visible to its owner under a team-scoped token."""
    sid = vis_seed.server(visibility="private", owner_email="alice@example.com")
    assert vis_seed.resolve(sid, user_email="alice@example.com", token_teams=["team-1"]) == UPSTREAM_TEXT


def test_private_server_not_visible_to_wrong_user(vis_seed):
    """A private server is not visible to a different authenticated user."""
    sid = vis_seed.server(visibility="private", owner_email="alice@example.com")
    assert vis_seed.resolve(sid, user_email="bob@example.com", token_teams=[]) == DEFAULT_SERVER_INSTRUCTIONS


def test_team_server_visible_to_team_member(vis_seed):
    """A team server is visible to a caller whose token includes the server's team."""
    sid = vis_seed.server(visibility="team", team_id="team-1")
    assert vis_seed.resolve(sid, user_email="alice@example.com", token_teams=["team-1"]) == UPSTREAM_TEXT


def test_team_server_not_visible_to_wrong_team(vis_seed):
    """A team server is not visible to a caller from a different team."""
    sid = vis_seed.server(visibility="team", team_id="team-1")
    assert vis_seed.resolve(sid, user_email="alice@example.com", token_teams=["team-2"]) == DEFAULT_SERVER_INSTRUCTIONS


def test_admin_bypass_does_not_see_another_users_private_server(vis_seed):
    """Admin bypass (token_teams=None) never reads another user's private server."""
    sid = vis_seed.server(visibility="private", owner_email="alice@example.com")
    assert vis_seed.resolve(sid, user_email="admin@example.com", token_teams=None) == DEFAULT_SERVER_INSTRUCTIONS


def test_admin_bypass_sees_own_private_server(vis_seed):
    """Admin bypass reads the admin's own private server."""
    sid = vis_seed.server(visibility="private", owner_email="admin@example.com")
    assert vis_seed.resolve(sid, user_email="admin@example.com", token_teams=None) == UPSTREAM_TEXT


def test_admin_bypass_sees_team_server(vis_seed):
    """Admin bypass reads a team server of any team."""
    sid = vis_seed.server(visibility="team", team_id="team-1")
    assert vis_seed.resolve(sid, user_email="admin@example.com", token_teams=None) == UPSTREAM_TEXT


def test_missing_scope_is_public_only(vis_seed):
    """A caller that passes no scope gets the public-only rule, never admin bypass."""
    private_sid = vis_seed.server(visibility="private", owner_email="alice@example.com")
    team_sid = vis_seed.server(visibility="team", team_id="team-1")
    assert vis_seed.resolve(private_sid, user_email="alice@example.com") == DEFAULT_SERVER_INSTRUCTIONS
    assert vis_seed.resolve(team_sid, user_email="alice@example.com") == DEFAULT_SERVER_INSTRUCTIONS


def test_public_only_token_does_not_see_own_private_server(vis_seed):
    """A public-only token sees public servers only, even for the owner."""
    sid = vis_seed.server(visibility="private", owner_email="alice@example.com")
    assert vis_seed.resolve(sid, user_email="alice@example.com", token_teams=[]) == DEFAULT_SERVER_INSTRUCTIONS


def test_unknown_server_sends_default_text(vis_seed):
    """An unknown server id never raises and sends the default text."""
    assert vis_seed.resolve("missing", user_email="alice@example.com", token_teams=["team-1"]) == DEFAULT_SERVER_INSTRUCTIONS


def test_no_auth_context_sees_only_public(vis_seed):
    """token_teams=[] with no user_email (public-only token, no owner match) sees only public servers."""
    sid = vis_seed.server(visibility="private", owner_email="alice@example.com")
    assert vis_seed.resolve(sid, user_email=None, token_teams=[]) == DEFAULT_SERVER_INSTRUCTIONS


# ---------------------------------------------------------------------------
# /rpc initialize deny-path tests (CWE-639 / CWE-200)
# ---------------------------------------------------------------------------


class _RpcRequest:
    """Request double that carries a verified JWT payload."""

    def __init__(self, teams: Optional[List[str]], is_admin: bool = False) -> None:
        self.headers = {}
        self.query_params = {}
        self.state = SimpleNamespace(_jwt_verified_payload=("token", {"teams": teams, "is_admin": is_admin}))


async def _rpc_initialize_instructions(vis_seed, session_factory, server_id: str, user_email: str, teams: Optional[List[str]], is_admin: bool = False) -> Optional[str]:
    """Run the ``/rpc`` initialize path against the in-memory catalog and return the instructions text."""
    # First-Party
    from mcpgateway import main as main_mod  # pylint: disable=import-outside-toplevel

    request = _RpcRequest(teams, is_admin)
    with (
        patch("mcpgateway.services.server_service.SessionLocal", session_factory),
        patch.object(main_mod.session_registry, "_get_oauth_experimental_config", return_value=None),
        patch.object(main_mod.server_service, "get_server", AsyncMock(return_value=SimpleNamespace(id=server_id))),
    ):
        result = await main_mod._execute_rpc_initialize(  # pylint: disable=protected-access
            request,
            MagicMock(),
            {"email": user_email, "is_admin": is_admin},
            params={"protocolVersion": "2025-06-18"},
            server_id=server_id,
            mcp_session_id=None,
        )
    return result.get("instructions")


@pytest.mark.asyncio
async def test_rpc_initialize_wrong_team_token_gets_default_text(vis_seed, session_factory):
    """A team-scoped token for another team never reads the server's upstream text."""
    sid = vis_seed.server(visibility="team", team_id="team-1")
    assert await _rpc_initialize_instructions(vis_seed, session_factory, sid, "bob@example.com", ["team-2"]) == DEFAULT_SERVER_INSTRUCTIONS


@pytest.mark.asyncio
async def test_rpc_initialize_other_users_private_server_gets_default_text(vis_seed, session_factory):
    """A user never reads another user's private server text."""
    sid = vis_seed.server(visibility="private", owner_email="alice@example.com")
    assert await _rpc_initialize_instructions(vis_seed, session_factory, sid, "bob@example.com", ["team-2"]) == DEFAULT_SERVER_INSTRUCTIONS


@pytest.mark.asyncio
async def test_rpc_initialize_public_only_token_gets_default_text(vis_seed, session_factory):
    """A public-only token never reads a team server's text."""
    sid = vis_seed.server(visibility="team", team_id="team-1")
    assert await _rpc_initialize_instructions(vis_seed, session_factory, sid, "alice@example.com", []) == DEFAULT_SERVER_INSTRUCTIONS


@pytest.mark.asyncio
async def test_rpc_initialize_admin_bypass_does_not_read_other_users_private_server(vis_seed, session_factory):
    """An admin with an unrestricted token never reads another user's private server text."""
    sid = vis_seed.server(visibility="private", owner_email="alice@example.com")
    assert await _rpc_initialize_instructions(vis_seed, session_factory, sid, "admin@example.com", None, is_admin=True) == DEFAULT_SERVER_INSTRUCTIONS


@pytest.mark.asyncio
async def test_rpc_initialize_team_member_reads_team_server_text(vis_seed, session_factory):
    """A token for the server's team reads the upstream text."""
    sid = vis_seed.server(visibility="team", team_id="team-1")
    assert await _rpc_initialize_instructions(vis_seed, session_factory, sid, "alice@example.com", ["team-1"]) == UPSTREAM_TEXT
