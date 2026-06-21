# -*- coding: utf-8 -*-
"""Admin form POST → ``server_a2a_association`` persistence (Plan T22).

Location: ./tests/integration/test_admin_server_a2a_flow.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Closes the integration-test acceptance criterion of Amendment D (T21B)
in the A2A native passthrough plan:

    Automated: simulates form POST with ``associatedA2aAgents=[a1, a2]``
    and asserts the resulting server row has both IDs in
    ``server_a2a_association``.

This test exercises the FULL admin flow that landed in T21B:

1. JS bundle (T21B-a/-b/-c/-export) collects checked A2A agents into
   FormData under the camelCase key ``associatedA2aAgents``.
2. ``admin_add_server`` / ``admin_edit_server`` extract that list via
   ``form.getlist("associatedA2aAgents")`` and pass the comma-joined
   value into :class:`ServerCreate` / :class:`ServerUpdate` as
   ``associated_a2a_agents`` (T21B-admin-py).
3. :meth:`ServerService.register_server` /
   :meth:`ServerService.update_server` round-trip the IDs through the
   ``server_a2a_association`` table (Phase A CallerContext authz).

T19 (:mod:`test_a2a_vserver_composition`) already covered the
service-layer half (3) directly. T22 here adds the route-layer half
(1)+(2) so a regression in either the form-parsing OR the
ServerCreate/ServerUpdate wiring would surface.

Scope notes:

- Real in-memory SQLite via the same ``real_db_session`` pattern used
  by ``test_a2a_vserver_composition.py``. The Wave 3+4 ``TestClient``
  lifespan limitation continues to apply here — we call
  ``admin_add_server`` / ``admin_edit_server`` directly (bypassing
  only the HTTP transport layer) so the route handler's form-extraction
  + ServerCreate/ServerUpdate construction + service-layer call
  ALL execute against the real DB.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mcpgateway.admin import admin_add_server, admin_edit_server
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Base, server_a2a_association

pytestmark = pytest.mark.integration


class FakeForm(dict):
    """Mirror of the FakeForm in tests/unit/mcpgateway/test_admin.py.

    Replicated here (rather than imported from a unit-test module) so the
    integration test does not depend on unit-test helpers, which keeps
    the integration suite runnable in isolation.
    """

    def getlist(self, key):
        """Return the value for ``key`` as a list (matches Starlette FormData)."""
        value = self.get(key, [])
        if isinstance(value, list):
            return value
        return [value] if value else []


@pytest.fixture
def real_db_session():
    """Yield a real SQLAlchemy session bound to a fresh in-memory SQLite DB.

    Mirrors the fixture in test_a2a_vserver_composition.py — identical
    setup so the two integration tests share the same DB shape and
    behaviour. ``StaticPool`` keeps the same connection across calls so
    the schema created on one cursor is visible to the next.
    """
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

    Matches ``_make_a2a_agent`` in test_a2a_vserver_composition.py so
    both integration tests use identical agent shape.
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


def _mock_request_with_form(form_data: dict) -> MagicMock:
    """Build a Starlette ``Request``-shaped mock returning ``form_data``.

    The admin route handlers read ``request.form()``, ``request.state``,
    and ``request.scope``; all are wired here to defaults that keep the
    handler off the unauth/no-team paths.
    """
    request = MagicMock(spec=Request)
    request.scope = {"root_path": ""}
    request.form = AsyncMock(return_value=FakeForm(form_data))
    request.state = MagicMock(token_teams=None, bearer_token=None)
    request.headers = MagicMock()
    request.headers.get = MagicMock(return_value=None)
    return request


def _bypass_team_and_metadata(monkeypatch, user_email: str = "admin@example.com") -> None:
    """Patch out the team-verification + metadata-capture + RBAC side calls.

    Same monkeypatches that the existing unit tests use in
    test_admin.py::TestAdminServerEndpoints + the ``allow_permission``
    fixture pattern. The integration test only cares about the
    A2A-association write path, not team verification or the
    middleware-level permission check (which is exercised separately
    by tests/unit/mcpgateway/services/test_a2a_access_policy.py).
    """
    team_service = MagicMock()
    team_service.verify_team_for_user = AsyncMock(return_value=None)
    team_service.get_user_teams = AsyncMock(return_value=[SimpleNamespace(id="t1")])
    monkeypatch.setattr("mcpgateway.admin.TeamManagementService", lambda db: team_service)
    monkeypatch.setattr(
        "mcpgateway.admin.MetadataCapture.extract_creation_metadata",
        lambda *_args, **_kwargs: {
            "created_by": user_email,
            "created_from_ip": None,
            "created_via": "ui",
            "created_user_agent": None,
            "import_batch_id": None,
            "federation_source": None,
        },
    )
    monkeypatch.setattr(
        "mcpgateway.admin.MetadataCapture.extract_modification_metadata",
        lambda *_args, **_kwargs: {
            "modified_by": user_email,
            "modified_from_ip": None,
            "modified_via": "ui",
            "modified_user_agent": None,
        },
    )
    mock_perm_service = MagicMock()
    mock_perm_service.check_permission = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: mock_perm_service)
    monkeypatch.setattr("mcpgateway.admin.PermissionService", lambda db: mock_perm_service)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_admin_add_server_form_persists_associatedA2aAgents(real_db_session, monkeypatch) -> None:
    """T22 (a): admin_add_server with ``associatedA2aAgents`` writes server_a2a_association.

    Pre-creates two A2A agents directly in the DB (skipping the agent
    creation route, which is out of scope), then submits a server form
    with both agent IDs and verifies the join table has both rows.
    """
    db = real_db_session
    _bypass_team_and_metadata(monkeypatch)

    agent_one = _make_a2a_agent("echo-one")
    agent_two = _make_a2a_agent("echo-two")
    db.add_all([agent_one, agent_two])
    db.commit()
    db.refresh(agent_one)
    db.refresh(agent_two)

    form_data = {
        "name": "bundle-server",
        "description": "server bundling two A2A agents",
        "visibility": "public",
        "associatedA2aAgents": [agent_one.id, agent_two.id],
    }
    request = _mock_request_with_form(form_data)

    result = await admin_add_server(request, db, user={"email": "admin@example.com", "db": db})

    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    rows = db.execute(select(server_a2a_association)).all()
    assert len(rows) == 2, f"expected exactly two server_a2a_association rows, got: {rows}"
    bound_agent_ids = {row.a2a_agent_id for row in rows}
    assert bound_agent_ids == {agent_one.id, agent_two.id}


@pytest.mark.asyncio
async def test_admin_add_server_form_with_no_a2a_agents(real_db_session, monkeypatch) -> None:
    """T22 (b): admin_add_server without ``associatedA2aAgents`` writes ZERO join rows.

    Guard against a regression where ``form.getlist("associatedA2aAgents")``
    returning an empty list would still cause a stray write. T21B-admin-py
    handles this via ``associated_a2a_agents=... if associated_a2a_agents_list
    else None`` — this test pins that contract.
    """
    db = real_db_session
    _bypass_team_and_metadata(monkeypatch)

    form_data = {
        "name": "empty-server",
        "description": "server with no A2A agents bound",
        "visibility": "public",
    }
    request = _mock_request_with_form(form_data)

    result = await admin_add_server(request, db, user={"email": "admin@example.com", "db": db})

    assert isinstance(result, JSONResponse)
    assert result.status_code == 200

    rows = db.execute(select(server_a2a_association)).all()
    assert rows == [], f"expected no server_a2a_association rows, got: {rows}"


@pytest.mark.asyncio
async def test_admin_edit_server_form_updates_associatedA2aAgents(real_db_session, monkeypatch) -> None:
    """T22 (c): admin_edit_server with ``associatedA2aAgents`` replaces server's bindings.

    Round-trip the full lifecycle: create a server with one A2A agent
    bound, then PUT-like edit it to bind a different pair. Verifies
    the edit handler's form extraction + ServerUpdate wiring + the
    service layer's clear-AFTER-check (Metis H4) all compose correctly
    when the bound set changes.
    """
    db = real_db_session
    _bypass_team_and_metadata(monkeypatch)

    agent_initial = _make_a2a_agent("echo-initial")
    agent_new_a = _make_a2a_agent("echo-new-a")
    agent_new_b = _make_a2a_agent("echo-new-b")
    db.add_all([agent_initial, agent_new_a, agent_new_b])
    db.commit()
    db.refresh(agent_initial)
    db.refresh(agent_new_a)
    db.refresh(agent_new_b)

    create_form = {
        "name": "edit-target-server",
        "description": "server to edit",
        "visibility": "public",
        "associatedA2aAgents": [agent_initial.id],
    }
    create_request = _mock_request_with_form(create_form)
    create_result = await admin_add_server(create_request, db, user={"email": "admin@example.com", "db": db})
    assert isinstance(create_result, JSONResponse)
    assert create_result.status_code == 200

    initial_rows = db.execute(select(server_a2a_association)).all()
    assert len(initial_rows) == 1
    assert initial_rows[0].a2a_agent_id == agent_initial.id
    server_id = initial_rows[0].server_id

    edit_form = {
        "name": "edit-target-server",
        "description": "server with updated A2A bindings",
        "visibility": "public",
        "associatedA2aAgents": [agent_new_a.id, agent_new_b.id],
    }
    edit_request = _mock_request_with_form(edit_form)

    edit_result = await admin_edit_server(server_id, edit_request, db, user={"email": "admin@example.com", "db": db})
    assert isinstance(edit_result, JSONResponse)
    assert edit_result.status_code == 200

    final_rows = db.execute(select(server_a2a_association)).all()
    assert len(final_rows) == 2, f"expected exactly two server_a2a_association rows after edit, got: {final_rows}"
    final_agent_ids = {row.a2a_agent_id for row in final_rows}
    assert final_agent_ids == {agent_new_a.id, agent_new_b.id}
    assert agent_initial.id not in final_agent_ids, "initial agent should be cleared on edit"
