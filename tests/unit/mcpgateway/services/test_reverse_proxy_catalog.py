# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_catalog.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Stable reverse-proxy catalog registration tests.
"""

from concurrent.futures import ThreadPoolExecutor
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
    stable_proxy_id,
)
from mcpgateway.services.reverse_proxy_protocol import RegistrationServer
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
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: SimpleNamespace(invalidate_gateways=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: SimpleNamespace(invalidate_gateway=AsyncMock()))
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.gateway_service.audit_trail", MagicMock(log_action=MagicMock()))
    monkeypatch.setattr("mcpgateway.services.gateway_service.structured_logger", MagicMock(log=MagicMock()))
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
    original = catalog_service._gateway_service.register_reverse_proxy_gateway

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

    catalog_service._gateway_service.register_reverse_proxy_gateway = observe_gateway_stage

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
