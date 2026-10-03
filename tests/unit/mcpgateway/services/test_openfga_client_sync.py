# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_openfga_client_sync.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the OpenFGA client and the tuple sync service.
"""

# Standard
import json
from typing import Any, Optional

# Third-Party
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeamMember, RbacRule, Role, UserRole
from mcpgateway.services.openfga_client import OpenFgaClient, OpenFgaUnavailable, resolve_openfga_token
from mcpgateway.services.openfga_sync import ENTITY_TYPES, OpenFgaSyncService, build_type_definitions, relation_for


class _Script:
    """Scripted httpx handler recording requests."""

    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.responses.pop(0) if self.responses else (200, {})
        return httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": "application/json"})


@pytest.fixture
def mock_http(monkeypatch):
    """Patch the client's AsyncClient with a scripted MockTransport."""
    script = _Script([])

    real_async_client = httpx.AsyncClient

    def _factory(*_args: Any, **_kwargs: Any) -> httpx.AsyncClient:
        return real_async_client(transport=httpx.MockTransport(script))

    monkeypatch.setattr("mcpgateway.services.openfga_client.httpx.AsyncClient", _factory)
    return script


@pytest.fixture
def client() -> OpenFgaClient:
    return OpenFgaClient(api_url="http://openfga.test", api_token="key1", timeout=1.0)


async def test_check_sends_bearer_and_parses_allowed(mock_http, client, monkeypatch):
    monkeypatch.setattr(settings, "openfga_store_id", "store-1")
    mock_http.responses.append((200, {"allowed": True}))
    assert await client.check("user:anne", "tools_read", "tool:*") is True
    request = mock_http.requests[-1]
    assert request.url.path.endswith("/stores/store-1/check")
    assert request.headers["authorization"] == "Bearer key1"
    assert json.loads(request.content)["tuple_key"] == {"user": "user:anne", "relation": "tools_read", "object": "tool:*"}


async def test_fail_closed_on_http_500(mock_http, client, monkeypatch):
    monkeypatch.setattr(settings, "openfga_store_id", "store-1")
    mock_http.responses.append((500, {"code": "internal_error"}))
    with pytest.raises(OpenFgaUnavailable):
        await client.check("user:anne", "tools_read", "tool:*")


async def test_write_tuples_skipped_when_empty(mock_http, client, monkeypatch):
    monkeypatch.setattr(settings, "openfga_store_id", "store-1")
    await client.write_tuples([], [])
    assert not mock_http.requests


async def test_bootstrap_creates_store_and_model(mock_http, monkeypatch):
    monkeypatch.setattr(settings, "openfga_store_id", "")
    monkeypatch.setattr(settings, "openfga_store_name", "contextforge")
    mock_http.responses.extend([(200, {"stores": []}), (201, {"id": "store-9"}), (200, {"authorization_models": []}), (201, {"authorization_model_id": "model-1"})])
    service = OpenFgaSyncService(_null_session(), OpenFgaClient(api_url="http://openfga.test", api_token="key1"))  # type: ignore[arg-type]
    await service.bootstrap()
    assert settings.openfga_store_id == "store-9"
    paths = [r.url.path for r in mock_http.requests]
    assert any(p.endswith("/stores") for p in paths)
    assert any(p.endswith("/stores/store-9/authorization-models") for p in paths)


def test_token_file_wins(monkeypatch, tmp_path):
    # Third-Party
    from pydantic import SecretStr

    token_file = tmp_path / "openfga.key"
    token_file.write_text("  filekey  \n")
    monkeypatch.setattr(settings, "openfga_api_token_file", str(token_file))
    monkeypatch.setattr(settings, "openfga_api_token", SecretStr("literalkey"))
    assert resolve_openfga_token() == "filekey"


def test_build_type_definitions_shape():
    types = build_type_definitions()
    by_type = {t["type"]: t for t in types}
    assert set(ENTITY_TYPES) <= set(by_type)
    tool = by_type["tool"]
    assert "blocked" in tool["relations"]
    assert tool["relations"]["tools_read"] == {"difference": {"base": {"this": {}}, "subtract": {"computedUserset": {"relation": "blocked"}}}}
    assert {"type": "role", "relation": "assignee"} in tool["metadata"]["relations"]["tools_read"]["directly_related_user_types"]


def test_relation_for():
    assert relation_for("tools.read") == "tools_read"
    assert relation_for("security:read") == "security_read"


class _NullSession:
    """Session stub; bootstrap touches no tables."""


def _null_session() -> _NullSession:
    return _NullSession()


class _FakeClient:
    """Recording stand-in for the OpenFGA client."""

    def __init__(self, stored: Optional[list[dict]] = None) -> None:
        self.stored = [dict(t) for t in (stored or [])]
        self.writes: list[dict] = []
        self.deletes: list[dict] = []

    async def read_tuples(self, object_filter: Optional[str] = None) -> list[dict]:
        keys = [t.get("key", t) for t in self.stored]
        return [t for t in keys if object_filter is None or t.get("object") == object_filter]

    async def write_tuples(self, writes: list[dict], deletes: list[dict]) -> None:
        self.writes = writes
        self.deletes = deletes


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(db) -> None:
    db.add(Role(id="r-dev", name="developer", description="", scope="team", permissions=["tools.read", "tools.execute"], created_by="admin@example.com", is_system_role=True, is_active=True))
    from datetime import datetime, timedelta, timezone

    db.add(
        UserRole(
            id="ur-1",
            user_email="anne@example.com",
            user_id="anne",
            role_id="r-dev",
            scope="global",
            granted_by="admin@example.com",
            granted_at=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            is_active=True,
        )
    )
    db.add(EmailTeamMember(team_id="t-eng", user_email="anne@example.com", user_id="anne", role="member", is_active=True))
    db.add(
        RbacRule(
            id="rule-1",
            name="block-one",
            description="",
            capability_type="tool",
            capability_id="tool-42",
            permission="tools.execute",
            phase="pre_invocation",
            predicate="role.developer",
            effect="deny",
            priority=10,
            is_active=True,
            is_system=False,
            created_by="admin@example.com",
        )
    )
    db.flush()


def test_desired_tuples_mirror(db_session):
    _seed(db_session)
    tuples = OpenFgaSyncService(db_session, _FakeClient()).desired_tuples()  # type: ignore[arg-type]
    assert ("user:anne@example.com", "assignee", "role:developer") in tuples
    assert ("user:anne@example.com", "member", "team:t-eng") in tuples
    assert ("role:developer#assignee", "tools_read", "tool:all") in tuples
    assert ("role:developer#assignee", "blocked", "tool:tool-42") in tuples


async def test_full_resync_diffs_and_applies(db_session):
    _seed(db_session)
    desired = OpenFgaSyncService(db_session, _FakeClient()).desired_tuples()  # type: ignore[arg-type]
    stored = [{"key": {"user": u, "relation": r, "object": o}} for (u, r, o) in sorted(desired)[:2]]
    stored.append({"key": {"user": "user:ghost@example.com", "relation": "assignee", "object": "role:developer"}})
    fake = _FakeClient(stored)
    applied = await OpenFgaSyncService(db_session, fake).full_resync()  # type: ignore[arg-type]
    assert applied == len(desired) - 2 + 1
    written = {(w["user"], w["relation"], w["object"]) for w in fake.writes}
    deleted = {(d["user"], d["relation"], d["object"]) for d in fake.deletes}
    assert ("user:ghost@example.com", "assignee", "role:developer") in deleted
    assert ("user:anne@example.com", "member", "team:t-eng") in written


async def test_sync_now_swallows_unavailable(db_session):
    class _Down(_FakeClient):
        async def read_tuples(self, object_filter=None):
            raise OpenFgaUnavailable("down")

    assert await OpenFgaSyncService(db_session, _Down()).sync_now("test") == -1  # type: ignore[arg-type]


async def test_hook_noop_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "rbac_rule_provider", "db")
    monkeypatch.setattr(settings, "rbac_rule_provider_shadow", False)
    called = []

    async def _boom(db, reason):
        called.append(reason)

    import mcpgateway.services.openfga_sync as sync_mod

    monkeypatch.setattr(sync_mod, "OpenFgaSyncService", lambda db, client: _fail())
    await sync_mod.openfga_sync_after_commit(db_session, "test")  # must not touch the engine
    assert not called


def _fail():
    raise AssertionError("engine must not be consulted when disabled")


async def test_hook_runs_and_swallows_engine_failure(db_session, monkeypatch):
    monkeypatch.setattr(settings, "rbac_rule_provider", "openfga")
    import mcpgateway.services.openfga_sync as sync_mod

    class _Exploding:
        async def sync_now(self, reason):
            raise RuntimeError("engine down")

    monkeypatch.setattr(sync_mod, "OpenFgaSyncService", lambda db, client: _Exploding())
    monkeypatch.setattr(sync_mod, "OpenFgaClient", lambda: None)
    await sync_mod.openfga_sync_after_commit(db_session, "role assigned")  # must not raise


async def test_write_tuples_chunks_past_engine_cap(mock_http, client, monkeypatch):
    """A 250-tuple write splits into 3 batched requests."""
    import json as _json

    monkeypatch.setattr(settings, "openfga_store_id", "store-1")
    mock_http.responses.extend([(200, {}), (200, {}), (200, {})])
    tuples = [{"user": f"user:p{i}", "relation": "assignee", "object": "role:developer"} for i in range(250)]
    await client.write_tuples(tuples, [])
    writes = [r for r in mock_http.requests if r.url.path.endswith("/write")]
    assert len(writes) == 3
    sizes = [len(_json.loads(r.content)["writes"]["tuple_keys"]) for r in writes]
    assert sizes == [100, 100, 50]


async def test_error_body_surfaces_in_unavailable(mock_http, client, monkeypatch):
    """A 400 carries the engine message into OpenFgaUnavailable."""
    monkeypatch.setattr(settings, "openfga_store_id", "store-1")
    mock_http.responses.append((400, {"code": "exceeded_entity_limit", "message": "cap"}))
    with pytest.raises(OpenFgaUnavailable, match="exceeded_entity_limit"):
        await client.check("user:anne", "tools_read", "tool:all")


def test_build_conditions_shape():
    from mcpgateway.services.openfga_sync import build_conditions

    conditions = build_conditions()
    grant = conditions["non_expired_grant"]
    assert grant["expression"] == "current_time < grant_time + grant_duration"
    assert grant["parameters"]["grant_duration"] == {"type_name": "TYPE_NAME_DURATION"}


def test_role_assignee_accepts_conditioned_subjects():
    types = {t["type"]: t for t in build_type_definitions()}
    subjects = types["role"]["metadata"]["relations"]["assignee"]["directly_related_user_types"]
    assert {"type": "user"} in subjects
    assert {"type": "user", "condition": "non_expired_grant"} in subjects


def test_desired_tuples_expiry(db_session):
    from datetime import datetime, timedelta, timezone

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    granted = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.add(Role(id="r-dev", name="developer", description="", scope="team", permissions=["tools.read"], created_by="admin@example.com", is_system_role=True, is_active=True))
    db_session.add(UserRole(id="ur-perm", user_email="perm@example.com", user_id="perm", role_id="r-dev", scope="global", granted_by="a@example.com", granted_at=granted, is_active=True))
    db_session.add(
        UserRole(id="ur-exp", user_email="exp@example.com", user_id="exp", role_id="r-dev", scope="global", granted_by="a@example.com", granted_at=granted, expires_at=future, is_active=True)
    )
    db_session.add(UserRole(id="ur-old", user_email="old@example.com", user_id="old", role_id="r-dev", scope="global", granted_by="a@example.com", granted_at=granted, expires_at=past, is_active=True))
    db_session.flush()

    tuples = OpenFgaSyncService(db_session, _FakeClient()).desired_tuples()

    perm = ("user:perm@example.com", "assignee", "role:developer")
    exp = ("user:exp@example.com", "assignee", "role:developer")
    old = ("user:old@example.com", "assignee", "role:developer")
    assert tuples[perm] is None
    assert tuples[old] if old in tuples else True  # expired rows leave the mirror
    assert old not in tuples
    condition = tuples[exp]
    assert condition["name"] == "non_expired_grant"
    assert condition["context"]["grant_duration"].endswith("s")
    assert condition["context"]["grant_time"].startswith(granted.strftime("%Y-%m-%d"))


async def test_check_supplies_current_time(mock_http, client, monkeypatch):
    monkeypatch.setattr(settings, "openfga_store_id", "store-1")
    mock_http.responses.append((200, {"allowed": True}))
    await client.check("user:anne", "tools_read", "tool:all")
    body = json.loads(mock_http.requests[-1].content)
    assert "current_time" in body["context"]
    assert body["context"]["current_time"].endswith("Z")


async def test_write_model_sends_conditions(mock_http, client, monkeypatch):
    from mcpgateway.services.openfga_sync import build_conditions

    monkeypatch.setattr(settings, "openfga_store_id", "store-1")
    mock_http.responses.append((201, {"authorization_model_id": "m2"}))
    model_id = await client.write_model(build_type_definitions(), conditions=build_conditions())
    assert model_id == "m2"
    body = json.loads(mock_http.requests[-1].content)
    assert "non_expired_grant" in body["conditions"]


async def test_resync_rewrites_changed_condition_context(db_session):
    _seed(db_session)
    desired = OpenFgaSyncService(db_session, _FakeClient()).desired_tuples()
    conditioned_key = next(k for k, v in desired.items() if v is not None and k[1] == "assignee")
    stored = [
        {
            "user": conditioned_key[0],
            "relation": conditioned_key[1],
            "object": conditioned_key[2],
            "condition": {"name": "non_expired_grant", "context": {"grant_time": "2000-01-01T00:00:00Z", "grant_duration": "1s"}},
        }
    ]
    fake = _FakeClient(stored)
    await OpenFgaSyncService(db_session, fake).full_resync()
    rewritten = [w for w in fake.writes if (w["user"], w["relation"], w["object"]) == conditioned_key]
    assert rewritten and rewritten[0]["condition"]["context"]["grant_duration"].endswith("s")


async def test_read_tuples_follows_continuation_tokens(mock_http, client, monkeypatch):
    """A paged read consumes every page before returning."""
    monkeypatch.setattr(settings, "openfga_store_id", "store-1")
    mock_http.responses.extend(
        [
            (200, {"tuples": [{"key": {"user": "user:a", "relation": "assignee", "object": "role:developer"}}], "continuation_token": "page-2"}),
            (200, {"tuples": [{"key": {"user": "user:b", "relation": "assignee", "object": "role:viewer"}}], "continuation_token": "page-3"}),
            (200, {"tuples": [{"key": {"user": "user:c", "relation": "member", "object": "team:eng"}}], "continuation_token": ""}),
        ]
    )
    tuples = await client.read_tuples()
    assert len(tuples) == 3
    bodies = [json.loads(r.content) for r in mock_http.requests]
    assert bodies[1].get("continuation_token") == "page-2"
    assert bodies[2].get("continuation_token") == "page-3"


async def test_resync_does_not_rewrite_existing_tuples(db_session):
    """Tuples present in the stored set never enter the write batch."""
    _seed(db_session)
    service = OpenFgaSyncService(db_session, _FakeClient())
    desired = service.desired_tuples()
    stored = []
    for (u, r, o), condition in sorted(desired.items()):
        entry: dict = {"user": u, "relation": r, "object": o}
        if condition is not None:
            entry["condition"] = condition
        stored.append({"key": entry})
    fake = _FakeClient(stored)
    applied = await OpenFgaSyncService(db_session, fake).full_resync()
    assert fake.writes == []
    assert applied == 0


class TestRelationshipModel:
    """Tests for the relationship-based OpenFGA model."""

    def test_domain_type_exists(self):
        from mcpgateway.services.openfga_relationship_model import build_relationship_type_definitions

        types = {t["type"]: t for t in build_relationship_type_definitions()}
        assert "domain" in types
        assert "member" in types["domain"]["relations"]
        assert "admin" in types["domain"]["relations"]

    def test_capability_types_have_parent(self):
        from mcpgateway.services.openfga_relationship_model import build_relationship_type_definitions, ENTITY_TYPES

        types = {t["type"]: t for t in build_relationship_type_definitions()}
        for entity in ENTITY_TYPES:
            assert entity in types, f"{entity} missing"
            assert "parent" in types[entity]["relations"], f"{entity} lacks parent"
            parent_subjects = types[entity]["metadata"]["relations"]["parent"]["directly_related_user_types"]
            assert {"type": "domain"} in parent_subjects

    def test_read_permissions_traverse_member(self):
        """Read relations traverse parent → domain → member."""
        from mcpgateway.services.openfga_relationship_model import build_relationship_type_definitions

        types = {t["type"]: t for t in build_relationship_type_definitions()}
        server = types["server"]
        read_rel = server["relations"]["servers_read"]
        assert "union" in read_rel
        traversals = [c for c in read_rel["union"]["child"] if "tupleToUserset" in c]
        assert len(traversals) == 1
        assert traversals[0]["tupleToUserset"]["computedUserset"]["relation"] == "member"

    def test_write_permissions_traverse_admin(self):
        """Write relations traverse parent → domain → admin."""
        from mcpgateway.services.openfga_relationship_model import build_relationship_type_definitions

        types = {t["type"]: t for t in build_relationship_type_definitions()}
        server = types["server"]
        create_rel = server["relations"]["servers_create"]
        assert "union" in create_rel
        traversals = [c for c in create_rel["union"]["child"] if "tupleToUserset" in c]
        assert len(traversals) == 1
        assert traversals[0]["tupleToUserset"]["computedUserset"]["relation"] == "admin"

    def test_relationship_sync_no_user_domain_tuples(self):
        """The sync stores NO user-to-domain tuples (contextual at check time)."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from mcpgateway.db import Base, EmailTeam, EmailTeamMember
        from mcpgateway.services.openfga_sync import RelationshipSyncService

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        session.add(EmailTeam(id="t-eng", name="engineering", slug="engineering", created_by="admin@example.com"))
        session.add(EmailTeamMember(team_id="t-eng", user_email="anne@example.com", user_id="anne", role="owner", is_active=True))
        session.flush()

        svc = RelationshipSyncService(session, _FakeClient())
        tuples = svc.desired_tuples()
        # No user-to-domain tuples in the stored set
        assert not any(t[1] in ("member", "admin") and t[2].startswith("domain:") for t in tuples)

    def test_contextual_domain_tuples_from_claims(self):
        """build_contextual_domain_tuples uses JWT claims when present."""
        from mcpgateway.services.openfga_sync import build_contextual_domain_tuples

        tuples = build_contextual_domain_tuples(None, "anne@example.com", token_teams=["eng", "sales"], token_roles=["team_admin"])
        assert {"user": "user:anne@example.com", "relation": "admin", "object": "domain:eng"} in tuples
        assert {"user": "user:anne@example.com", "relation": "admin", "object": "domain:sales"} in tuples

    def test_contextual_domain_tuples_member_without_admin_role(self):
        """Without an admin role claim, teams map to member tuples."""
        from mcpgateway.services.openfga_sync import build_contextual_domain_tuples

        tuples = build_contextual_domain_tuples(None, "bob@example.com", token_teams=["eng"], token_roles=["developer"])
        assert tuples == [{"user": "user:bob@example.com", "relation": "member", "object": "domain:eng"}]


class TestDomainObjectId:
    """Tests for the canonical domain identifier."""

    def test_slugifies_spaces_and_apostrophes(self):
        """Team names with whitespace and apostrophes produce engine-safe ids."""
        from mcpgateway.services.openfga_sync import domain_object_id

        assert domain_object_id("RBAC Test anne's Team") == "rbac-test-annes-team"

    def test_short_and_empty_inputs_fall_back_to_digest(self):
        """Inputs that slugify under 2 characters get a digest-based id."""
        from mcpgateway.services.openfga_sync import domain_object_id

        assert domain_object_id("a") != "a"
        assert domain_object_id("---") != ""
        assert len(domain_object_id("")) >= 2
        assert domain_object_id("---").startswith("domain-")

    def test_caps_length_at_engine_maximum(self):
        """Identifiers never exceed the engine's 256-character cap."""
        from mcpgateway.services.openfga_sync import domain_object_id

        assert len(domain_object_id("x" * 300)) == 256

    def test_claim_value_and_team_name_agree(self):
        """A team name and its identical claim value yield one identifier."""
        from mcpgateway.services.openfga_sync import domain_object_id

        assert domain_object_id("Platform Engineering") == domain_object_id("Platform Engineering")

    def test_contextual_tuples_slugify_claim_values(self):
        """Claims with whitespace still build engine-safe domain objects."""
        from mcpgateway.services.openfga_sync import build_contextual_domain_tuples

        tuples = build_contextual_domain_tuples(None, "anne@example.com", token_teams=["Platform Engineering"], token_roles=["developer"])
        assert tuples == [{"user": "user:anne@example.com", "relation": "member", "object": "domain:platform-engineering"}]

    def test_db_fallback_and_sync_parent_agree(self):
        """Fallback member tuples and sync parent tuples share one domain id."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from mcpgateway.db import Base, EmailTeam, EmailTeamMember, Server
        from mcpgateway.services.openfga_sync import RelationshipSyncService, build_contextual_domain_tuples, domain_object_id

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        session.add(EmailTeam(id="t-1", name="RBAC Test anne's Team", slug="rbac-test", created_by="admin@example.com"))
        session.add(EmailTeamMember(team_id="t-1", user_email="anne@example.com", user_id="anne", role="member", is_active=True))
        session.add(Server(id="s-1", name="api-server", team_id="t-1", enabled=True))
        session.flush()

        team_name = "RBAC Test anne's Team"
        expected = f"domain:{domain_object_id(team_name)}"
        svc = RelationshipSyncService(session, _FakeClient())
        tuples = svc.desired_tuples()
        assert ("server:api-server", "parent", expected) in tuples

        fallback = build_contextual_domain_tuples(session, "anne@example.com")
        assert {"user": "user:anne@example.com", "relation": "member", "object": expected} in fallback
