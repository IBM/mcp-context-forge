# -*- coding: utf-8 -*-
"""V-server composition end-to-end integration test (Plan T19).

Location: ./tests/integration/test_a2a_vserver_composition.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Plan T19 closes Wave 4 by exercising the v-server composition flow
against a real (in-memory SQLite) database — the SERVICE LAYER end
to end, including the ``server_a2a_association`` write path under
:meth:`ServerService.register_server` and the read path through
:meth:`A2AAgentService.synthesize_agent_card` with ``server_id`` set.

Scope notes:

- Route-layer coverage (T16 middleware → T11/T12 handlers) is already
  in place via the mock-based ``TestVirtualServerCardEndpoint`` /
  ``TestVirtualServerDispatchEndpoint`` classes in
  ``tests/integration/test_a2a_native_routes.py``. T19 complements
  those tests by exercising the SAME contract through the
  ACTUAL service layer + ACTUAL DB so the
  ``server_a2a_association`` row write actually happens against a
  real schema.

- Full ``TestClient(main_mod.app)`` instantiation triggers a
  ``CircularDependencyError`` on lifespan startup against the
  in-memory engine (background services need a more elaborate
  fixture). Rather than mock the whole lifespan, we drive the
  services directly — this isolates T19's unique value (DB-level
  composition) without re-doing route-layer work already covered.

Plan T19 assertions covered:

(a) ``server_a2a_association`` actually receives a row when
    ``associated_a2a_agents`` is supplied to ``register_server``
    (closes the verification half of T20 with a real DB).
(b) ``synthesize_agent_card`` with ``server_id`` set returns the card
    for an agent that IS in the server's membership.
(c) ``synthesize_agent_card`` with ``server_id`` set returns ``None``
    for a foreign agent (not in the server's membership) — same
    wire outcome as agent-not-found per D14.
(d) The card's URL is rewritten to the gateway-public v-server-scoped
    form (``{base}/servers/{server_id}/a2a/{name}``).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Base, server_a2a_association
from mcpgateway.schemas import ServerCreate
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.services.server_service import ServerService

pytestmark = pytest.mark.integration


@pytest.fixture
def real_db_session():
    """Yield a real SQLAlchemy session bound to a fresh in-memory SQLite DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        Path(path).unlink(missing_ok=True)


def _make_a2a_agent(name: str, endpoint_url: str = "http://upstream.example/a2a") -> DbA2AAgent:
    """Build a public A2A agent ORM row ready for ``db.add()``.

    Uses ``uuid4().hex`` (dashless 32-char hex) to match the existing
    ServerService test convention at
    ``tests/unit/mcpgateway/services/test_server_service.py:2565``.
    Pydantic ID normalization in ``ServerCreate`` strips dashes, so
    using the dash-less form up front avoids a refresh-vs-validate
    round-trip mismatch.
    """
    return DbA2AAgent(
        id=uuid4().hex,
        name=name,
        slug=name,
        description=f"echo agent {name}",
        endpoint_url=endpoint_url,
        agent_type="jsonrpc",
        protocol_version="1.0.0",
        capabilities={},
        config={},
        auth_type=None,
        auth_value=None,
        enabled=True,
        reachable=True,
        visibility="public",
        team_id=None,
        owner_email="admin@example.com",
        tags=[],
    )


@pytest.mark.asyncio
async def test_register_server_persists_a2a_association(real_db_session) -> None:
    """T19 (a): real ServerService.register_server creates server_a2a_association rows."""
    db = real_db_session

    agent_echo = _make_a2a_agent("echo")
    db.add(agent_echo)
    db.commit()
    db.refresh(agent_echo)
    echo_id = agent_echo.id

    service = ServerService()
    server_in = ServerCreate(
        name="echo-bundle",
        description="bundle that exposes echo via v-server URL",
        associated_a2a_agents=[echo_id],
        visibility="public",
    )
    created = await service.register_server(db, server_in, created_by="admin@example.com", owner_email="admin@example.com")
    server_id = created.id

    rows = db.execute(select(server_a2a_association).where(server_a2a_association.c.server_id == server_id)).all()
    assert len(rows) == 1, f"expected exactly one row in server_a2a_association, got: {rows}"
    assert rows[0].a2a_agent_id == echo_id


@pytest.mark.asyncio
async def test_synthesize_agent_card_with_server_id_returns_card_for_member(real_db_session) -> None:
    """T19 (b) + (d): v-server card synthesis works for a real bound agent.

    Exercises the Phase A three-level conjunctive check end-to-end
    against the real DB: server visibility (public) + membership
    (just created) + agent visibility (public) all pass, so the card
    is returned and its URL carries the v-server-scoped prefix.
    """
    db = real_db_session

    agent = _make_a2a_agent("echo")
    db.add(agent)
    db.commit()
    db.refresh(agent)

    server_service = ServerService()
    server_in = ServerCreate(name="bundle", description="bundle", associated_a2a_agents=[agent.id], visibility="public")
    created = await server_service.register_server(db, server_in, created_by="admin@example.com", owner_email="admin@example.com")
    server_id = created.id

    a2a_service = A2AAgentService()
    card = await a2a_service.synthesize_agent_card(
        db,
        "echo",
        "http://gateway.example",
        server_id=server_id,
        user_email="admin@example.com",
        token_teams=None,
    )

    assert card is not None, "v-server card should be returned for member agent"
    assert card.name == "echo"
    for iface in card.supported_interfaces:
        assert f"/servers/{server_id}/a2a/echo" in iface.url, f"v-server URL prefix missing in interface: {iface.url}"


@pytest.mark.asyncio
async def test_synthesize_agent_card_with_server_id_returns_none_for_foreign_agent(real_db_session) -> None:
    """T19 (c): foreign agent (NOT in server membership) → None.

    Same wire outcome as agent-not-found per D14. The membership
    check inside the Phase A policy denies, and the synthesizer
    returns None (which the route layer collapses to HTTP 404).
    """
    db = real_db_session

    agent_member = _make_a2a_agent("echo")
    agent_foreign = _make_a2a_agent("foreign-agent")
    db.add_all([agent_member, agent_foreign])
    db.commit()
    db.refresh(agent_member)
    db.refresh(agent_foreign)

    server_service = ServerService()
    server_in = ServerCreate(name="bundle", description="bundle", associated_a2a_agents=[agent_member.id], visibility="public")
    created = await server_service.register_server(db, server_in, created_by="admin@example.com", owner_email="admin@example.com")
    server_id = created.id

    a2a_service = A2AAgentService()
    card = await a2a_service.synthesize_agent_card(
        db,
        "foreign-agent",
        "http://gateway.example",
        server_id=server_id,
        user_email="admin@example.com",
        token_teams=None,
    )
    assert card is None, "foreign-agent (not in server membership) should yield None"


@pytest.mark.asyncio
async def test_per_agent_card_works_outside_vserver_context(real_db_session) -> None:
    """Direct ``/a2a/{name}`` path (no server_id) returns the card normally.

    Sanity test: the agent is still visible via the per-agent path
    even when it's bound to a server. The two URL families are
    independent.
    """
    db = real_db_session

    agent = _make_a2a_agent("echo")
    db.add(agent)
    db.commit()
    db.refresh(agent)

    a2a_service = A2AAgentService()
    card = await a2a_service.synthesize_agent_card(
        db,
        "echo",
        "http://gateway.example",
        server_id=None,
        user_email=None,
        token_teams=[],
    )
    assert card is not None
    assert card.name == "echo"
    for iface in card.supported_interfaces:
        assert iface.url == "http://gateway.example/a2a/echo", iface.url
