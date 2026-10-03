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
        return [t for t in self.stored if object_filter is None or t.get("object") == object_filter]

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
    db.add(UserRole(id="ur-1", user_email="anne@example.com", user_id="anne", role_id="r-dev", scope="global", granted_by="admin@example.com", is_active=True))
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
    stored = [{"user": u, "relation": r, "object": o} for (u, r, o) in sorted(desired)[:2]]
    stored.append({"user": "user:ghost@example.com", "relation": "assignee", "object": "role:developer"})
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
