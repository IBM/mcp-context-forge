# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_audit_team_stamping_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise audit stamping through HTTP against an isolated gateway and its database.
Set MCP_CLI_BASE_URL and LIVE_GATEWAY_DB_URL to the same test gateway.
SQLite and PostgreSQL databases support the identity and RBAC fixtures.
"""

# Standard
from datetime import datetime, timezone
import os
import uuid

# Third-Party
import httpx
import pytest
from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import AuditTrail, EmailTeam, EmailTeamMember, EmailUser, Prompt, Resource, Role, Server, TokenRevocation, Tool, UserRole
from tests.helpers.auth import make_auth_headers, make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

LIVE_DB_URL = os.getenv("LIVE_GATEWAY_DB_URL", "")
pytestmark = [pytest.mark.e2e, skip_no_gateway, pytest.mark.skipif(not LIVE_DB_URL, reason="Set LIVE_GATEWAY_DB_URL to an isolated test database")]


@pytest.fixture
def audit_context():
    """Create unique identities, teams, and permissions in the gateway test database."""
    engine = create_engine(LIVE_DB_URL)
    session_factory = sessionmaker(bind=engine)
    suffix = uuid.uuid4().hex
    actor = f"audit-live-{suffix}@example.com"
    denied = f"audit-denied-{suffix}@example.com"
    team_ids = [uuid.uuid4().hex, uuid.uuid4().hex]
    personal_team_id = uuid.uuid4().hex
    all_team_ids = [*team_ids, personal_team_id]
    role_id = str(uuid.uuid4())
    resource_ids = []
    with session_factory() as db:
        db.add_all([EmailUser(email=actor, full_name="Audit Live Actor"), EmailUser(email=denied, full_name="Audit Denied Actor")])
        db.flush()
        db.add_all([EmailTeam(id=team_id, name=f"audit-{team_id}", slug=f"audit-{team_id}", created_by=ADMIN_EMAIL) for team_id in team_ids])
        db.add(EmailTeam(id=personal_team_id, name=f"audit-personal-{suffix}", slug=f"audit-personal-{suffix}", created_by=actor, is_personal=True))
        db.add(
            Role(
                id=role_id,
                name=f"audit-live-{suffix}",
                scope="global",
                permissions=["servers.create", "servers.read", "servers.update", "servers.delete", "audit:read", "admin.import"],
                created_by=ADMIN_EMAIL,
            )
        )
        db.flush()
        db.add_all([EmailTeamMember(team_id=team_id, user_email=actor, role="owner") for team_id in all_team_ids])
        db.add(UserRole(user_email=actor, role_id=role_id, scope="global", granted_by=ADMIN_EMAIL))
        db.commit()
    try:
        yield {"actor": actor, "denied": denied, "teams": team_ids, "personal_team_id": personal_team_id, "resource_ids": resource_ids, "session_factory": session_factory}
    finally:
        with session_factory() as db:
            db.query(Server).filter(Server.owner_email == actor).delete(synchronize_session=False)
            db.query(Tool).filter(or_(Tool.owner_email == actor, Tool.team_id.in_(all_team_ids), Tool.id.in_(resource_ids))).delete(synchronize_session=False)
            for model in (Resource, Prompt):
                db.query(model).filter(or_(model.owner_email == actor, model.team_id.in_(all_team_ids))).delete(synchronize_session=False)
            db.query(AuditTrail).filter(or_(AuditTrail.user_id == actor, AuditTrail.team_id.in_(all_team_ids), AuditTrail.resource_id.in_(resource_ids))).delete(synchronize_session=False)
            db.query(TokenRevocation).filter(TokenRevocation.revoked_by == actor).delete(synchronize_session=False)
            db.query(UserRole).filter(UserRole.role_id == role_id).delete(synchronize_session=False)
            db.query(EmailTeamMember).filter(EmailTeamMember.team_id.in_(all_team_ids)).delete(synchronize_session=False)
            db.query(Role).filter(Role.id == role_id).delete(synchronize_session=False)
            db.query(EmailTeam).filter(EmailTeam.id.in_(all_team_ids)).delete(synchronize_session=False)
            db.query(EmailUser).filter(EmailUser.email.in_([actor, denied])).delete(synchronize_session=False)
            db.commit()
        engine.dispose()


def _headers(email: str, teams: list[str] | None, *, session: bool = False) -> dict[str, str]:
    """Mint a test token for the requested team scope and optional session refresh.

    Args:
        email: Test actor email.
        teams: Token team scope.
        session: Whether to issue a refreshable session token.

    Returns:
        Bearer authorization headers.
    """
    extra_payload = {"token_use": "session", "jti": str(uuid.uuid4())} if session else None
    token = make_test_jwt(email, teams=teams, secret=JWT_SECRET, include_user_data=True, extra_payload=extra_payload)
    return make_auth_headers(token)


def test_server_lifecycle_audits_and_actor_token_isolation(audit_context):
    """HTTP server writes persist resource teams and isolate one actor across token scopes."""
    actor = audit_context["actor"]
    team_a, team_b = audit_context["teams"]
    headers = _headers(actor, [team_a, team_b])
    server_ids = {}
    audit_ids = {}
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
        for index, team_id in enumerate((team_a, team_b)):
            response = client.post("/servers", headers=headers, json={"server": {"name": f"audit-live-{team_id}-{index}"}, "team_id": team_id, "visibility": "team"})
            assert response.status_code == 201, response.text
            server_ids[team_id] = response.json()["id"]
            audit_context["resource_ids"].append(server_ids[team_id])
            with audit_context["session_factory"]() as db:
                row = db.execute(select(AuditTrail).where(AuditTrail.action == "create_server", AuditTrail.resource_id == server_ids[team_id])).scalar_one()
                assert row.team_id == team_id
                assert row.context["details"]["team_id"] == team_id
                audit_ids[team_id] = f"audit:{row.id}"

        for teams in ([team_a], [team_b], []):
            response = client.get("/api/logs/activity", headers=_headers(actor, teams), params={"limit": 100})
            assert response.status_code == 200, response.text
            visible_ids = {item["id"] for item in response.json()["items"]}
            assert visible_ids.intersection(audit_ids.values()) == {audit_ids[team_id] for team_id in teams}

        response = client.get("/api/logs/activity")
        assert response.status_code == 401, response.text
        response = client.get("/api/logs/activity", headers=_headers(audit_context["denied"], []))
        assert response.status_code == 403, response.text

        server_id = server_ids[team_a]
        response = client.put(f"/servers/{server_id}", headers=headers, json={"team_id": team_b})
        assert response.status_code == 200, response.text
        for activate in (False, True):
            response = client.post(f"/servers/{server_id}/state", headers=headers, params={"activate": str(activate).lower()})
            assert response.status_code == 200, response.text
        response = client.delete(f"/servers/{server_id}", headers=headers)
        assert response.status_code == 200, response.text

    with audit_context["session_factory"]() as db:
        rows = db.execute(select(AuditTrail).where(AuditTrail.resource_id == server_id)).scalars().all()
        mutation_teams = {
            "create_server": team_a,
            "update_server": team_b,
            "deactivate_server": team_b,
            "activate_server": team_b,
            "delete_server": team_b,
        }
        assert {row.action: row.team_id for row in rows if row.action != "view_server"} == mutation_teams
        view_rows = [row for row in rows if row.action == "view_server"]
        assert view_rows
        assert all(row.team_id == team_b for row in view_rows)
        assert db.get(Server, server_id) is None


def test_session_refresh_audit_keeps_platform_null_team(audit_context):
    """HTTP session refresh retains NULL audit scope and actor visibility for a public-only token."""
    actor = audit_context["actor"]
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
        response = client.post("/auth/refresh", headers=_headers(actor, audit_context["teams"], session=True))
        assert response.status_code == 200, response.text
        with audit_context["session_factory"]() as db:
            row = db.execute(select(AuditTrail).where(AuditTrail.action == "session_refresh", AuditTrail.user_id == actor)).scalar_one()
            assert row.team_id is None
            audit_id = f"audit:{row.id}"
        response = client.get("/api/logs/activity", headers=_headers(actor, []), params={"limit": 100})
        assert response.status_code == 200, response.text
        assert audit_id in {item["id"] for item in response.json()["items"]}


def _import_entity(entity_type: str, name: str) -> dict:
    """Build an HTTP import entity without ownership fields.

    Args:
        entity_type: Import collection name.
        name: Unique resource name.

    Returns:
        Configuration entity for the requested type.
    """
    entity = {"name": name, "description": "Imported resource"}
    if entity_type == "tools":
        entity.update(url="http://example.com/tool", integration_type="REST", jsonpath_filter="")
    elif entity_type == "resources":
        entity.update(uri=f"resource://audit/{name}", content="hello", mime_type="text/plain")
    elif entity_type == "prompts":
        entity.update(template="Hello", arguments=[])
    return entity


@pytest.mark.parametrize("entity_type", ["tools", "resources", "prompts", "servers"])
def test_http_import_audits_trusted_personal_team(audit_context, entity_type):
    """HTTP imports stamp the importer's personal team and exclude the bulk summary from other token scopes."""
    actor = audit_context["actor"]
    personal_team_id = audit_context["personal_team_id"]
    wrong_team_id = audit_context["teams"][1]
    entities_data = [
        {
            **_import_entity(entity_type, f"auditimport{uuid.uuid4().hex}"),
            "team_id": wrong_team_id,
            "owner_email": audit_context["denied"],
            "visibility": "public",
        }
        for _ in range(2)
    ]
    payload = {"import_data": {"version": "2025-03-26", "exported_at": datetime.now(timezone.utc).isoformat(), "entities": {entity_type: entities_data}}}
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
        response = client.post("/import", headers=_headers(actor, [personal_team_id]), json=payload)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "completed", result
        assert result["progress"]["created"] == 2, result
        assert result["progress"]["failed"] == 0, result

        with audit_context["session_factory"]() as db:
            model = {"tools": Tool, "resources": Resource, "prompts": Prompt, "servers": Server}[entity_type]
            resources = db.execute(select(model).where(model.name.in_([entity["name"] for entity in entities_data]))).scalars().all()
            assert len(resources) == 2
            assert all(resource.team_id == personal_team_id and resource.owner_email == actor and resource.visibility == "team" for resource in resources)
            action = "create_server" if entity_type == "servers" else f"bulk_create_{entity_type}"
            rows = db.execute(select(AuditTrail).where(AuditTrail.action == action, AuditTrail.user_id == actor)).scalars().all()
            assert len(rows) == (2 if entity_type == "servers" else 1)
            assert all(row.team_id == personal_team_id for row in rows)
            if entity_type == "tools":
                assert rows[0].context["details"]["count"] == 2
                assert rows[0].context["details"]["import_batch_id"]
            elif entity_type != "servers":
                assert rows[0].new_values[f"{entity_type}_created"] == 2
            audit_ids = {f"audit:{row.id}" for row in rows}

        for teams, expected_visible in (([personal_team_id], True), ([wrong_team_id], False), ([], False)):
            response = client.get("/api/logs/activity", headers=_headers(actor, teams), params={"limit": 100})
            assert response.status_code == 200, response.text
            visible_ids = {item["id"] for item in response.json()["items"]}
            assert audit_ids.intersection(visible_ids) == (audit_ids if expected_visible else set())


@pytest.mark.parametrize("entity_type", ["tools", "resources", "prompts"])
@pytest.mark.parametrize("owns_resource", [True, False])
def test_http_import_updates_keep_existing_scope_and_deny_foreign_ownership(audit_context, entity_type, owns_resource):
    """HTTP imports preserve existing teams and reject updates without resource ownership."""
    actor = audit_context["actor"]
    team_id = audit_context["teams"][1]
    owner = actor if owns_resource else audit_context["denied"]
    name = f"auditupdate{uuid.uuid4().hex}"
    model = {"tools": Tool, "resources": Resource, "prompts": Prompt}[entity_type]
    values = {"name": name, "description": "Before import", "owner_email": owner, "team_id": team_id, "visibility": "public", "created_by": owner, "created_via": "api"}
    if entity_type == "tools":
        values.update(original_name=name, url="http://example.com/tool", integration_type="REST", input_schema={"type": "object"})
    elif entity_type == "resources":
        values.update(uri=f"resource://audit/{name}", mime_type="text/plain")
    else:
        values.update(original_name=name, template="Hello", argument_schema={"type": "object", "properties": {}})
    with audit_context["session_factory"]() as db:
        resource = model(**values)
        db.add(resource)
        db.commit()
        resource_id = resource.id
    payload = {"import_data": {"version": "2025-03-26", "exported_at": datetime.now(timezone.utc).isoformat(), "entities": {entity_type: [_import_entity(entity_type, name)]}}}

    with httpx.Client(base_url=BASE_URL, timeout=20.0) as client:
        response = client.post("/import", headers=_headers(actor, [audit_context["personal_team_id"]]), json=payload)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["progress"]["updated"] == int(owns_resource), result
        assert result["progress"]["failed"] == int(not owns_resource), result
        with audit_context["session_factory"]() as db:
            resource = db.get(model, resource_id)
            assert (resource.team_id, resource.owner_email) == (team_id, owner)
            assert resource.description == ("Imported resource" if owns_resource else "Before import")
            rows = db.execute(select(AuditTrail).where(AuditTrail.user_id == actor, AuditTrail.action == f"bulk_update_{entity_type}")).scalars().all()
            assert len(rows) == int(owns_resource)
            if owns_resource:
                assert rows[0].team_id == team_id
                audit_id = f"audit:{rows[0].id}"
        if owns_resource:
            for teams, expected_visible in (([team_id], True), ([audit_context["personal_team_id"]], False), ([], False)):
                response = client.get("/api/logs/activity", headers=_headers(actor, teams), params={"limit": 100})
                assert response.status_code == 200, response.text
                assert (audit_id in {item["id"] for item in response.json()["items"]}) is expected_visible
        response = client.post("/import", json=payload)
        assert response.status_code == 401, response.text
        response = client.post("/import", headers=_headers(audit_context["denied"], []), json=payload)
        assert response.status_code == 403, response.text
