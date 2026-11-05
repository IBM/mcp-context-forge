# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_catalog.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Stable reverse-proxy catalog, internal gateway registration, and reachability tests.
"""

from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from threading import Event, Lock
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from mcpgateway.db import Base
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.reverse_proxy_catalog import (
    AuthenticatedRegistrationContext,
    ReverseProxyCatalogConflictError,
    ReverseProxyCatalogService,
    ReverseProxyGatewayRegistration,
    ReverseProxyGatewayScope,
    stable_proxy_id,
)
from mcpgateway.services.reverse_proxy_protocol import RegistrationServer
from mcpgateway.services.reverse_proxy_relay import ReverseProxyRelay
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, LocalSessionId, ReverseProxyEviction, ReverseProxySessionManager, StableGatewayId
from mcpgateway.services.server_service import ServerError, ServerService


@pytest.fixture
def catalog_service(test_db, monkeypatch):
    test_db.query(DbServer).delete()
    test_db.query(DbGateway).delete()
    test_db.commit()
    gateway_service = GatewayService()
    server_service = ServerService()
    gateway_service._notify_gateway_added = AsyncMock()
    server_service._notify_server_added = AsyncMock()
    server_service._audit_trail = MagicMock(log_action=MagicMock())
    server_service._structured_logger = MagicMock(log=MagicMock())
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_registry_cache", lambda: SimpleNamespace(invalidate_gateways=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_tool_lookup_cache", lambda: SimpleNamespace(invalidate_gateway=AsyncMock()))
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.audit_trail", MagicMock(log_action=MagicMock()))
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.structured_logger", MagicMock(log=MagicMock()))
    service = ReverseProxyCatalogService(gateway_service=gateway_service, server_service=server_service)
    yield service
    test_db.query(DbServer).delete()
    test_db.query(DbGateway).delete()
    test_db.commit()


@pytest.mark.asyncio
async def test_team_registration_inherits_scope_on_gateway_and_virtual_server(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email=" Owner@Example.com ", team_id="TEAM-42")
    registration = RegistrationServer(name="team-proxy", description="Team server")

    # When
    result = await catalog_service.register(test_db, context, registration)

    # Then
    gateway, server = test_db.get(DbGateway, result.stable_id), test_db.get(DbServer, result.stable_id)
    assert gateway is not None and server is not None
    assert (gateway.owner_email, gateway.team_id, gateway.visibility) == ("owner@example.com", "team-42", "team")
    assert (server.owner_email, server.team_id, server.visibility) == ("owner@example.com", "team-42", "team")
    assert server.tools == [] and server.resources == [] and server.prompts == []
    assert server.created_via == "reverse_proxy"


@pytest.mark.asyncio
async def test_registration_without_trusted_team_falls_back_to_public(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)

    # When
    result = await catalog_service.register(test_db, context, RegistrationServer(name="public-proxy"))

    # Then
    gateway, server = test_db.get(DbGateway, result.stable_id), test_db.get(DbServer, result.stable_id)
    assert gateway is not None and server is not None
    assert (gateway.team_id, gateway.visibility) == (None, "public")
    assert (server.team_id, server.visibility) == (None, "public")


@pytest.mark.asyncio
async def test_same_owner_scope_and_name_reconnect_is_idempotent(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    registration = RegistrationServer(name="reconnect-proxy")

    # When
    first = await catalog_service.register(test_db, context, registration)
    second = await catalog_service.register(test_db, context, registration)

    # Then
    assert first.stable_id == second.stable_id
    assert test_db.query(DbGateway).filter(DbGateway.id == first.stable_id).count() == 1
    assert test_db.query(DbServer).filter(DbServer.id == first.stable_id).count() == 1


@pytest.mark.asyncio
async def test_omitted_description_reconnect_preserves_catalog_descriptions_and_server_version(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    first = await catalog_service.register(test_db, context, RegistrationServer(name="described-proxy", description="Persisted description"))
    persisted_server = test_db.get(DbServer, first.stable_id)
    assert persisted_server is not None
    original_version = persisted_server.version

    # When
    await catalog_service.register(test_db, context, RegistrationServer(name="described-proxy"))
    await catalog_service.register(test_db, context, RegistrationServer(name="described-proxy"))

    # Then
    test_db.expire_all()
    gateway, server = test_db.get(DbGateway, first.stable_id), test_db.get(DbServer, first.stable_id)
    assert gateway is not None and server is not None
    assert gateway.description == server.description == "Persisted description"
    assert server.version == original_version


@pytest.mark.asyncio
async def test_explicit_null_description_reconnect_clears_once(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    first = await catalog_service.register(test_db, context, RegistrationServer(name="clear-description-proxy", description="Clear me"))
    original = test_db.get(DbServer, first.stable_id)
    assert original is not None
    original_version = original.version

    # When / Then
    await catalog_service.register(test_db, context, RegistrationServer(name="clear-description-proxy", description=None))
    test_db.expire_all()
    gateway, server = test_db.get(DbGateway, first.stable_id), test_db.get(DbServer, first.stable_id)
    assert gateway is not None and server is not None and gateway.description is server.description is None
    assert server.version == original_version + 1

    await catalog_service.register(test_db, context, RegistrationServer(name="clear-description-proxy", description=None))
    test_db.expire_all()
    gateway, server = test_db.get(DbGateway, first.stable_id), test_db.get(DbServer, first.stable_id)
    assert gateway is not None and server is not None and gateway.description is server.description is None
    assert server.version == original_version + 1


@pytest.mark.asyncio
async def test_reconnect_description_update_preserves_discovered_associations(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    registration = RegistrationServer(name="discovered-proxy", description="Before discovery")
    first = await catalog_service.register(test_db, context, registration)
    tool = DbTool(
        original_name="discovered-tool",
        name="discovered-tool",
        custom_name="discovered-tool",
        custom_name_slug="discovered-tool",
        url="reverse-proxy://tool/discovered-tool",
        input_schema={},
        gateway_id=first.gateway.id,
        owner_email=context.canonical_owner_email,
        visibility="public",
    )
    server = test_db.get(DbServer, first.server.id)
    assert server is not None
    server.tools.append(tool)
    test_db.commit()

    # When
    second = await catalog_service.register(test_db, context, RegistrationServer(name=registration.name, description="After discovery"))

    # Then
    test_db.expire_all()
    persisted = test_db.get(DbServer, second.server.id)
    assert persisted is not None
    assert persisted.description == "After discovery"
    assert [associated.id for associated in persisted.tools] == [tool.id]
    assert all("db" not in call.kwargs for call in catalog_service._server_service._audit_trail.log_action.call_args_list)


@pytest.mark.asyncio
async def test_server_creation_failure_rolls_back_gateway(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    registration = RegistrationServer(name="atomic-proxy")
    catalog_id = stable_proxy_id(context, registration)
    catalog_service._server_service.register_server = AsyncMock(side_effect=ServerError("server persistence failed"))

    # When / Then
    with pytest.raises(ServerError, match="server persistence failed"):
        await catalog_service.register(test_db, context, registration)
    assert test_db.get(DbGateway, catalog_id) is None
    catalog_service._gateway_service._notify_gateway_added.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_registration_commits_catalog_pair_once(catalog_service, test_db):
    # Given
    commits = 0

    def count_commit(_session):
        nonlocal commits
        commits += 1

    event.listen(test_db, "after_commit", count_commit)

    # When
    try:
        await catalog_service.register(
            test_db,
            AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None),
            RegistrationServer(name="single-transaction-proxy"),
        )
    finally:
        event.remove(test_db, "after_commit", count_commit)

    # Then
    assert commits == 1
    assert all("db" not in call.kwargs for call in catalog_service._server_service._audit_trail.log_action.call_args_list)


def test_concurrent_first_registration_is_database_serialized(catalog_service, tmp_path):
    # Given
    engine = create_engine(
        f"sqlite:///{tmp_path / 'catalog-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    registration = RegistrationServer(name="concurrent-proxy")
    first_entered = Event()
    release_first = Event()
    second_entered = Event()
    entry_lock = Lock()
    entry_count = 0
    original = catalog_service.register_reverse_proxy_gateway

    async def observe_gateway_stage(*args, **kwargs):
        nonlocal entry_count
        with entry_lock:
            entry_count += 1
            current_entry = entry_count
        if current_entry == 1:
            first_entered.set()
            release_first.wait(timeout=5)
        else:
            second_entered.set()
        return await original(*args, **kwargs)
    catalog_service.register_reverse_proxy_gateway = observe_gateway_stage

    def register_once():
        with session_factory() as db:
            return anyio.run(catalog_service.register, db, context, registration)

    # When
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(register_once)
            assert first_entered.wait(timeout=5)
            second = executor.submit(register_once)

            # Then
            assert not second_entered.wait(timeout=0.25)
            release_first.set()
            first_result = first.result(timeout=5)
            second_result = second.result(timeout=5)
        with session_factory() as verification_db:
            assert first_result.stable_id == second_result.stable_id
            assert verification_db.query(DbGateway).count() == 1
            assert verification_db.query(DbServer).count() == 1
    finally:
        release_first.set()
        engine.dispose()


@pytest.mark.asyncio
async def test_other_owner_stable_id_collision_fails_closed(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    registration = RegistrationServer(name="collision-proxy")
    stable_id = stable_proxy_id(context, registration)
    test_db.add(DbGateway(id=stable_id, name="collision-proxy", slug="collision-proxy", url=f"reverse-proxy://catalog/{stable_id}", transport="PROXIED", capabilities={}, owner_email="other@example.com", visibility="public", created_via="reverse_proxy"))
    test_db.commit()

    # When / Then
    with pytest.raises(ReverseProxyCatalogConflictError):
        await catalog_service.register(test_db, context, registration)


@pytest.mark.asyncio
async def test_stable_server_identity_conflict_rolls_back_registration_lock(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    registration = RegistrationServer(name="identity-conflict")
    catalog_id = stable_proxy_id(context, registration)
    test_db.add(
        DbServer(
            id=catalog_id,
            name=registration.name,
            owner_email="other@example.com",
            visibility="public",
            created_via="reverse_proxy",
        )
    )
    test_db.commit()

    # When / Then
    with pytest.raises(ReverseProxyCatalogConflictError, match="stable ID belongs to different virtual server state"):
        await catalog_service.register(test_db, context, registration)
    assert not test_db.in_transaction()


@pytest.mark.asyncio
async def test_non_reverse_proxy_name_or_origin_conflict_fails_closed(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    test_db.add(DbGateway(name="occupied", slug="occupied", url="https://example.com/mcp", transport="STREAMABLEHTTP", capabilities={}, owner_email="owner@example.com", visibility="public", created_via="api"))
    test_db.commit()

    # When / Then
    with pytest.raises(ReverseProxyCatalogConflictError):
        await catalog_service.register(test_db, context, RegistrationServer(name="occupied"))


@pytest.mark.asyncio
async def test_non_reverse_proxy_server_conflict_is_rejected_before_gateway_creation(catalog_service, test_db):
    # Given
    context = AuthenticatedRegistrationContext(owner_email="owner@example.com", team_id=None)
    registration = RegistrationServer(name="occupied-server")
    catalog_id = stable_proxy_id(context, registration)
    test_db.add(DbServer(name="occupied-server", owner_email="other@example.com", visibility="public", created_via="api"))
    test_db.commit()

    # When / Then
    with pytest.raises(ReverseProxyCatalogConflictError):
        await catalog_service.register(test_db, context, registration)
    assert not test_db.in_transaction()
    assert test_db.get(DbGateway, catalog_id) is None


@pytest.mark.asyncio
async def test_internal_reverse_proxy_registration_persists_without_network_initialization(test_db, monkeypatch):
    # Given
    gateway_service = GatewayService()
    gateway_service._initialize_gateway_with_timeout = AsyncMock()
    gateway_service._notify_gateway_added = AsyncMock()
    service = ReverseProxyCatalogService(gateway_service=gateway_service)
    registry_cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    tool_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_registry_cache", lambda: registry_cache)
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_tool_lookup_cache", lambda: tool_cache)
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.audit_trail", MagicMock(log_action=MagicMock()))
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.structured_logger", MagicMock(log=MagicMock()))
    registration = ReverseProxyGatewayRegistration(
        stable_id="831ca569cfa55f89bf5a80720d32ef25",  # pragma: allowlist secret
        name="proxied-alpha",
        description="Local alpha server",
        owner_email="owner@example.com",
        scope=ReverseProxyGatewayScope(team_id=None, visibility="public"),
    )

    # When
    result = await service.register_reverse_proxy_gateway(test_db, registration)

    # Then
    persisted = test_db.get(DbGateway, registration.stable_id)
    assert result.id == registration.stable_id
    assert persisted is not None
    assert persisted.transport == "PROXIED"
    assert persisted.url == f"reverse-proxy://catalog/{registration.stable_id}"
    assert persisted.created_via == "reverse_proxy"
    assert persisted.enabled is True
    assert persisted.reachable is True
    assert persisted.owner_email == "owner@example.com"
    assert persisted.visibility == "public"
    gateway_service._initialize_gateway_with_timeout.assert_not_awaited()
    gateway_service._notify_gateway_added.assert_awaited_once()
    registry_cache.invalidate_gateways.assert_awaited_once()
    tool_cache.invalidate_gateway.assert_awaited_once_with(registration.stable_id)


@pytest.mark.asyncio
async def test_internal_reverse_proxy_registration_reconciles_matching_gateway(test_db, monkeypatch):
    # Given
    gateway_service = GatewayService()
    gateway_service._notify_gateway_added = AsyncMock()
    service = ReverseProxyCatalogService(gateway_service=gateway_service)
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_registry_cache", lambda: SimpleNamespace(invalidate_gateways=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_tool_lookup_cache", lambda: SimpleNamespace(invalidate_gateway=AsyncMock()))
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
    registration = ReverseProxyGatewayRegistration(
        stable_id="23bffbef515258d184d3421c95215c72",  # pragma: allowlist secret
        name="proxied-reconnect",
        description=None,
        owner_email="owner@example.com",
        scope=ReverseProxyGatewayScope(team_id=None, visibility="public"),
    )

    # When
    first = await service.register_reverse_proxy_gateway(test_db, registration)
    second = await service.register_reverse_proxy_gateway(test_db, registration)

    # Then
    assert first.id == second.id
    assert test_db.query(DbGateway).filter(DbGateway.id == registration.stable_id).count() == 1
    gateway_service._notify_gateway_added.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_reverse_proxy_gateway_unreachable_requires_internal_authority(test_db, monkeypatch):
    """Only transport-plus-server-provenance rows are updated; catalog rows remain present."""
    seen_at = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
    internal = DbGateway(id="internal-proxied", name="internal", slug="internal", url="reverse-proxy://catalog/internal", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    forged = DbGateway(id="forged-proxied", name="forged", slug="forged", url="reverse-proxy://catalog/forged", transport="PROXIED", created_via="api", reachable=True, capabilities={})
    test_db.add_all([internal, forged])
    test_db.commit()
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.fresh_db_session", lambda: nullcontext(test_db))

    manager = ReverseProxySessionManager()
    evictions = tuple(ReverseProxyEviction(StableGatewayId(gateway_id), ConnectionId("old")) for gateway_id in (internal.id, forged.id))
    await ReverseProxyCatalogService().mark_reverse_proxy_gateways_unreachable(manager, evictions, seen_at=seen_at)

    assert test_db.get(DbGateway, internal.id) is internal
    assert internal.reachable is False
    assert internal.last_seen is not None
    assert internal.last_seen.replace(tzinfo=timezone.utc) == seen_at
    assert forged.reachable is True


@pytest.mark.asyncio
async def test_unreachable_commit_invalidates_gateway_registry_cache(test_db, monkeypatch):
    """A successful reachability commit invalidates cached gateway reads."""
    gateway = DbGateway(id="cached-proxied", name="cached", slug="cached", url="reverse-proxy://catalog/cached", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    test_db.add(gateway)
    test_db.commit()
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.fresh_db_session", lambda: nullcontext(test_db))
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_registry_cache", lambda: cache)

    manager = ReverseProxySessionManager()
    eviction = ReverseProxyEviction(StableGatewayId(gateway.id), ConnectionId("old"))
    await ReverseProxyCatalogService().mark_reverse_proxy_gateways_unreachable(manager, (eviction,), seen_at=datetime.now(tz=timezone.utc))

    cache.invalidate_gateways.assert_awaited_once()


@pytest.mark.asyncio
async def test_unreachable_batch_continues_after_persistence_failure_and_invalidates_once(monkeypatch):
    # Given
    gateways = [
        SimpleNamespace(transport="PROXIED", created_via="reverse_proxy", reachable=True, last_seen=None)
        for _ in range(3)
    ]
    failure = RuntimeError("second persistence failed")
    sessions = []
    for index, gateway in enumerate(gateways):
        session = MagicMock()
        session.get.return_value = gateway
        if index == 1:
            session.commit.side_effect = failure
        sessions.append(session)
    session_contexts = iter(nullcontext(session) for session in sessions)
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.fresh_db_session", lambda: next(session_contexts))
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_registry_cache", lambda: cache)
    evictions = tuple(ReverseProxyEviction(StableGatewayId(f"proxied-{index}"), ConnectionId("old")) for index in range(3))

    # When
    with pytest.raises(RuntimeError) as captured:
        await ReverseProxyCatalogService().mark_reverse_proxy_gateways_unreachable(
            ReverseProxySessionManager(),
            evictions,
            seen_at=datetime(2026, 8, 13, 12, tzinfo=timezone.utc),
        )

    # Then
    assert captured.value is failure
    assert [session.commit.call_count for session in sessions] == [1, 1, 1]
    assert gateways[0].reachable is False
    assert gateways[2].reachable is False
    cache.invalidate_gateways.assert_awaited_once()


@pytest.mark.asyncio
async def test_unreachable_persistence_skips_live_replacement(test_db, monkeypatch):
    """An old generation cannot overwrite reachability after a replacement promotion."""
    gateway = DbGateway(id="replacement-proxied", name="replacement", slug="replacement", url="reverse-proxy://catalog/replacement", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    test_db.add(gateway)
    test_db.commit()
    manager = ReverseProxySessionManager()
    replacement = await manager.connect(MagicMock(), LocalSessionId("replacement"))
    stable_id = StableGatewayId(gateway.id)
    await manager.promote_stable_id(stable_id, replacement.connection_id)
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.fresh_db_session", lambda: nullcontext(test_db))
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_registry_cache", lambda: cache)

    await ReverseProxyCatalogService().mark_reverse_proxy_gateways_unreachable(
        manager,
        (ReverseProxyEviction(stable_id, ConnectionId("old-generation")),),
        seen_at=datetime.now(tz=timezone.utc),
    )

    assert gateway.reachable is True
    cache.invalidate_gateways.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreachable_persistence_requires_distributed_owner_absence(test_db, monkeypatch):
    """A denied distributed authority guard prevents an old worker from persisting unreachable."""
    gateway = DbGateway(id="distributed-replacement", name="replacement", slug="distributed-replacement", url="reverse-proxy://catalog/distributed-replacement", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    test_db.add(gateway)
    test_db.commit()
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.fresh_db_session", lambda: nullcontext(test_db))
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_registry_cache", lambda: cache)
    guard_calls: list[ReverseProxyEviction] = []

    @asynccontextmanager
    async def denying_guard(eviction: ReverseProxyEviction) -> AsyncIterator[bool]:
        guard_calls.append(eviction)
        yield False

    eviction = ReverseProxyEviction(StableGatewayId(gateway.id), ConnectionId("old-generation"))

    await ReverseProxyCatalogService().mark_reverse_proxy_gateways_unreachable(
        ReverseProxySessionManager(),
        (eviction,),
        seen_at=datetime.now(tz=timezone.utc),
        authority_guard=denying_guard,
    )

    assert guard_calls == [eviction]
    assert gateway.reachable is True
    cache.invalidate_gateways.assert_not_awaited()


def _lease_fake_redis() -> MagicMock:
    """Deterministic Redis subset with SET NX and fenced-eval semantics for registration leases."""
    store: dict[str, bytes] = {}
    redis = MagicMock(name="lease-redis")
    redis.store = store

    async def set_value(key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        del ex
        if nx and key in store:
            return None
        store[key] = value.encode()
        return True

    async def get_value(key: str) -> bytes | None:
        return store.get(key)

    async def eval_script(script: str, numkeys: int, *args: str | int) -> int:
        del script
        keys = tuple(str(arg) for arg in args[:numkeys])
        argv = tuple(str(arg) for arg in args[numkeys:])
        current = store.get(keys[0])
        if current is None or current.decode() != argv[0]:
            return 0
        if numkeys == 2:
            store[keys[1]] = argv[1].encode()
            return 1
        store.pop(keys[0])
        return 1

    redis.set = AsyncMock(side_effect=set_value)
    redis.get = AsyncMock(side_effect=get_value)
    redis.eval = AsyncMock(side_effect=eval_script)
    return redis


@pytest.mark.asyncio
async def test_unreachable_write_is_serialized_against_replacement_registration_lease(test_db, monkeypatch):
    """An old worker cannot commit unreachable while a replacement holds only its registration lease.

    Forces the exact TOCTOU interleaving from the distributed lifecycle: the
    replacement's owner promotion and reachable commit are armed to land at the
    old worker's commit point, so the lease guard must deny the write first.
    """
    gateway = DbGateway(id="lease-race-proxied", name="lease-race", slug="lease-race", url="reverse-proxy://catalog/lease-race", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    test_db.add(gateway)
    test_db.commit()
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.fresh_db_session", lambda: nullcontext(test_db))
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_registry_cache", lambda: cache)

    redis = _lease_fake_redis()
    manager = ReverseProxySessionManager()
    stable_id = StableGatewayId(gateway.id)
    old_worker = ReverseProxyRelay(manager, redis=redis, worker_id=lambda: "worker-old", owner_ttl_seconds=300)
    replacement = ReverseProxyRelay(manager, redis=redis, worker_id=lambda: "worker-new", owner_ttl_seconds=300)
    replacement_connection = ConnectionId("replacement-connection")
    assert await replacement.claim_registration(stable_id, replacement_connection)

    promoted = False
    original_commit = test_db.commit

    def commit_after_replacement_promotion() -> None:
        nonlocal promoted
        if not promoted:
            promoted = True
            redis.store[old_worker.owner_key(stable_id)] = replacement.owner_value(replacement_connection).encode()
            gateway.reachable = True
        original_commit()

    monkeypatch.setattr(test_db, "commit", commit_after_replacement_promotion)

    await ReverseProxyCatalogService().mark_reverse_proxy_gateways_unreachable(
        manager,
        (ReverseProxyEviction(stable_id, ConnectionId("old-generation")),),
        seen_at=datetime.now(tz=timezone.utc),
        authority_guard=old_worker.unreachable_write_guard,
    )

    # The write was denied at lease acquisition: no commit ever ran, so the
    # armed replacement promotion never had to fire and reachability survives.
    assert promoted is False
    assert gateway.reachable is True
    cache.invalidate_gateways.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreachable_write_proceeds_once_failed_replacement_releases_lease(test_db, monkeypatch):
    """Once a failed replacement releases its lease without promoting, the eviction write persists unreachable."""
    gateway = DbGateway(id="lease-released-proxied", name="lease-released", slug="lease-released", url="reverse-proxy://catalog/lease-released", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    test_db.add(gateway)
    test_db.commit()
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog.fresh_db_session", lambda: nullcontext(test_db))
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.reverse_proxy_catalog._get_registry_cache", lambda: cache)

    redis = _lease_fake_redis()
    manager = ReverseProxySessionManager()
    stable_id = StableGatewayId(gateway.id)
    old_worker = ReverseProxyRelay(manager, redis=redis, worker_id=lambda: "worker-old", owner_ttl_seconds=300)
    replacement = ReverseProxyRelay(manager, redis=redis, worker_id=lambda: "worker-new", owner_ttl_seconds=300)
    replacement_connection = ConnectionId("replacement-connection")
    assert await replacement.claim_registration(stable_id, replacement_connection)
    assert await replacement.release_registration(stable_id, replacement_connection)

    await ReverseProxyCatalogService().mark_reverse_proxy_gateways_unreachable(
        manager,
        (ReverseProxyEviction(stable_id, ConnectionId("old-generation")),),
        seen_at=datetime.now(tz=timezone.utc),
        authority_guard=old_worker.unreachable_write_guard,
    )

    assert gateway.reachable is False
    assert old_worker.registration_key(stable_id) not in redis.store
    cache.invalidate_gateways.assert_awaited_once()
