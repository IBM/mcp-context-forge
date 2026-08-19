# -*- coding: utf-8 -*-
"""Tests for governed external SQL discovery and execution."""

# Standard
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

# Third-Party
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.pool import QueuePool
from starlette.requests import Request

# First-Party
from mcpgateway.cache.registry_cache import registry_cache
from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache
from mcpgateway.cache.tool_result_cache import tool_result_cache
from mcpgateway.config import settings
from mcpgateway.db import SQLRelation
from mcpgateway.db import SQLTable as DbSQLTable
from mcpgateway.db import Tool as DbTool
from mcpgateway.routers import sql_data
from mcpgateway.schemas import APISQLTableBindingCreate, SQLDataSourceCreate, SQLDataSourceUpdate, SQLRelationUpdate, SQLTableUpdate
from mcpgateway.services import sql_data_service as sql_data_service_module
from mcpgateway.services.sql_data_service import SQLDataError, SQLDataForbiddenError, SQLDataService


class _FakeEngine:
    """Minimal disposable engine used to verify cache ownership."""

    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        """Record one engine disposal."""
        self.dispose_calls += 1


@pytest.fixture(autouse=True)
def clear_sql_engine_cache():
    """Keep process-local SQL engines isolated between tests."""
    SQLDataService.clear_engine_cache()
    yield
    SQLDataService.clear_engine_cache()


def _create_external_database(path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                author_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                FOREIGN KEY(author_id) REFERENCES authors(id)
            );
            CREATE VIEW book_titles AS SELECT id, title FROM books;
            INSERT INTO authors(id, name) VALUES (1, 'Ada');
            INSERT INTO books(id, author_id, title) VALUES (10, 1, 'Notes');
            """)
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def external_source(test_db, tmp_path, monkeypatch):
    database_path = tmp_path / "external.db"
    _create_external_database(database_path)
    monkeypatch.setattr(settings, "mcpgateway_sql_api_enabled", True)
    monkeypatch.setattr(settings, "mcpgateway_sqlite_allowed_roots", [str(tmp_path)])
    source = SQLDataService.create_source(
        test_db,
        SQLDataSourceCreate(name=f"Library {uuid.uuid4().hex}", connection_url=f"sqlite+pysqlite:///{database_path}"),
        "owner@example.com",
    )
    tables = SQLDataService.discover(test_db, source.id)
    return source, {table.table_name: table for table in tables}, database_path


def test_sqlite_discovery_records_keys_views_and_foreign_keys(test_db, external_source):
    source, tables, _path = external_source

    assert source.reachable is True
    assert tables["authors"].primary_key == ["id"]
    assert ["name"] in tables["authors"].unique_keys
    assert tables["book_titles"].object_type == "view"
    relation = test_db.execute(select(SQLRelation).where(SQLRelation.source_table_id == tables["books"].id)).scalar_one()
    assert relation.local_columns == ["author_id"]
    assert relation.remote_columns == ["id"]
    assert relation.enabled is False


@pytest.mark.asyncio
async def test_async_catalog_mutations_await_result_cache_barrier(test_db, external_source, monkeypatch):
    source, tables, _path = external_source
    table_ids = {table.id for table in tables.values()}
    admin_user = {"email": "admin@example.com", "is_admin": True}
    owner_user = {"email": "owner@example.com", "is_admin": False}
    for table in tables.values():
        table.owner_email = "owner@example.com"
    test_db.commit()
    request = Request({"type": "http", "method": "PATCH", "path": "/sql/catalog", "headers": []})
    request.state.token_teams = ["catalog-team"]
    catalog_barrier = AsyncMock()
    relation_barrier = AsyncMock()
    monkeypatch.setattr(SQLDataService, "invalidate_catalog_caches_async", catalog_barrier)
    monkeypatch.setattr(SQLDataService, "invalidate_result_cache_tables_async", relation_barrier)

    updated_source = await sql_data.update_source.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
        source_id=source.id,
        data=SQLDataSourceUpdate(description="updated through route"),
        db=test_db,
        user=admin_user,
    )
    assert updated_source.description == "updated through route"
    catalog_barrier.assert_awaited_once()
    assert set(catalog_barrier.await_args.args[0]) == table_ids
    assert catalog_barrier.await_args.args[1] == ()

    catalog_barrier.reset_mock()
    discovered = await sql_data.discover_source.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
        source_id=source.id,
        db=test_db,
        user=admin_user,
    )
    catalog_barrier.assert_awaited_once_with(tuple(table.id for table in discovered), ())

    catalog_barrier.reset_mock()
    updated_table = await sql_data.update_table.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
        table_id=tables["authors"].id,
        data=SQLTableUpdate(exposed=True, allow_query=True),
        request=request,
        db=test_db,
        user=owner_user,
    )
    catalog_barrier.assert_awaited_once()
    assert catalog_barrier.await_args.args[0] == (updated_table.id,)
    assert {reference[0] for reference in catalog_barrier.await_args.args[1]} == {
        tool.id for tool in test_db.execute(select(DbTool).where(DbTool.sql_table_id == updated_table.id)).scalars()
    }

    relation = test_db.execute(select(SQLRelation).where(SQLRelation.source_table_id == tables["books"].id)).scalar_one()
    catalog_barrier.reset_mock()
    relation_barrier.reset_mock()
    updated_relation = await sql_data.update_relation.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
        relation_id=relation.id,
        data=SQLRelationUpdate(enabled=True),
        request=request,
        db=test_db,
        user=owner_user,
    )
    assert updated_relation.enabled is True
    relation_barrier.assert_awaited_once_with((relation.source_table_id, relation.target_table_id))
    catalog_barrier.assert_not_awaited()

    catalog_barrier.reset_mock()
    await sql_data.delete_source.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
        source_id=source.id,
        db=test_db,
        user=admin_user,
    )
    catalog_barrier.assert_awaited_once()
    assert set(catalog_barrier.await_args.args[0]) == table_ids
    assert catalog_barrier.await_args.args[1]


@pytest.mark.asyncio
async def test_generated_tool_cache_barrier_awaits_all_cache_tiers(monkeypatch):
    registry_invalidate = AsyncMock()
    lookup_invalidate = AsyncMock()
    result_invalidate = AsyncMock()
    monkeypatch.setattr(registry_cache, "invalidate_tools", registry_invalidate)
    monkeypatch.setattr(tool_lookup_cache, "invalidate", lookup_invalidate)
    monkeypatch.setattr(tool_result_cache, "invalidate_tool", result_invalidate)

    await SQLDataService.invalidate_tool_caches_async(
        (
            ("tool-1", "sql.one.query", None),
            ("tool-2", "sql.two.query", "gateway-1"),
        )
    )

    registry_invalidate.assert_awaited_once_with()
    assert lookup_invalidate.await_count == 2
    lookup_invalidate.assert_any_await("sql.one.query", gateway_id=None)
    lookup_invalidate.assert_any_await("sql.two.query", gateway_id="gateway-1")
    assert result_invalidate.await_count == 2
    result_invalidate.assert_any_await("tool-1")
    result_invalidate.assert_any_await("tool-2")


def test_query_include_and_write_operations_share_policy(test_db, external_source):
    _source, tables, _path = external_source
    for name in ("authors", "books"):
        SQLDataService.update_table(
            test_db,
            tables[name].id,
            SQLTableUpdate(exposed=True, allow_query=True, allow_insert=True, allow_update=True, allow_delete=True),
            "owner@example.com",
        )
    relation = test_db.execute(select(SQLRelation).where(SQLRelation.source_table_id == tables["books"].id)).scalar_one()
    relation.enabled = True
    test_db.commit()

    queried = SQLDataService.execute(test_db, tables["books"].id, "query", {"key": {"id": 10}, "include": [relation.name]})
    assert queried["items"][0]["title"] == "Notes"
    assert queried["items"][0][relation.name][0]["name"] == "Ada"

    inserted = SQLDataService.execute(test_db, tables["authors"].id, "insert", {"values": {"id": 2, "name": "Grace"}})
    assert inserted["affected"] == 1
    updated = SQLDataService.execute(test_db, tables["authors"].id, "update", {"key": {"id": 2}, "values": {"name": "Grace Hopper"}})
    assert updated["affected"] == 1
    deleted = SQLDataService.execute(test_db, tables["authors"].id, "delete", {"key": {"id": 2}})
    assert deleted["affected"] == 1


def test_generated_sql_tool_schema_uses_reflected_types(test_db, external_source):
    _source, tables, _path = external_source
    updated_table = SQLDataService.update_table(
        test_db,
        tables["authors"].id,
        SQLTableUpdate(exposed=True, allow_query=True, allow_insert=True),
        "owner@example.com",
    )
    assert updated_table.id == tables["authors"].id
    query_tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["authors"].id, DbTool.source_operation == "query")).scalar_one()
    insert_tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["authors"].id, DbTool.source_operation == "insert")).scalar_one()

    assert query_tool.input_schema["properties"]["filter"]["properties"]["id"]["type"] == "integer"
    assert query_tool.input_schema["properties"]["filter"]["properties"]["name"]["type"] == "string"
    assert insert_tool.input_schema["properties"]["values"]["required"] == ["name"]


def test_sync_tools_opts_only_read_only_queries_into_result_cache(test_db, external_source):
    _source, tables, _path = external_source
    SQLDataService.update_table(
        test_db,
        tables["authors"].id,
        SQLTableUpdate(exposed=True, allow_query=True, allow_insert=True, allow_update=True, allow_delete=True),
        "owner@example.com",
    )
    tools = {
        tool.source_operation: tool
        for tool in test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["authors"].id)).scalars()
    }

    assert tools["query"].annotations["readOnlyHint"] is True
    assert tools["query"].annotations["x-contextforge-result-cache"] == {"enabled": True}
    for operation in ("insert", "update", "delete"):
        assert tools[operation].annotations["readOnlyHint"] is False
        assert "x-contextforge-result-cache" not in tools[operation].annotations

    # Synchronization must also repair annotations on already-existing tools.
    tools["query"].annotations = {}
    tools["insert"].annotations = {"readOnlyHint": True, "x-contextforge-result-cache": {"enabled": True}}
    test_db.commit()
    SQLDataService.sync_tools(test_db, tables["authors"].id)
    test_db.refresh(tools["query"])
    test_db.refresh(tools["insert"])

    assert tools["query"].annotations == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "x-contextforge-result-cache": {"enabled": True},
    }
    assert tools["insert"].annotations == {"readOnlyHint": False, "destructiveHint": False}


def test_views_are_read_only_and_keys_must_match(test_db, external_source):
    _source, tables, _path = external_source
    with pytest.raises(SQLDataForbiddenError, match="Views are always read-only"):
        SQLDataService.update_table(test_db, tables["book_titles"].id, SQLTableUpdate(exposed=True, allow_insert=True), "owner@example.com")

    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_query=True, allow_update=True), "owner@example.com")
    with pytest.raises(SQLDataError, match="exactly match"):
        SQLDataService.execute(test_db, tables["authors"].id, "update", {"key": {"name": "Ada", "id": 1}, "values": {"name": "Changed"}})


def test_query_limit_is_positive_and_capped(test_db, external_source):
    _source, tables, _path = external_source
    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_query=True), "owner@example.com")

    with pytest.raises(SQLDataError, match="limit must be at least 1"):
        SQLDataService.execute(test_db, tables["authors"].id, "query", {"limit": 0})

    response = SQLDataService.execute(test_db, tables["authors"].id, "query", {"limit": settings.mcpgateway_sql_max_limit + 1})
    assert response["limit"] == settings.mcpgateway_sql_max_limit


def test_generated_sql_tool_is_hidden_outside_token_scope(test_db, external_source):
    _source, tables, _path = external_source
    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_query=True), "owner@example.com")
    statement = select(DbTool).where(DbTool.sql_table_id == tables["authors"].id, DbTool.source_operation == "query")
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/data/library/main/authors", "headers": []})
    request.state.token_teams = []

    hidden = test_db.execute(sql_data._scoped_tools(request, {"email": "other@example.com"}, statement, test_db)).scalar_one_or_none()  # pylint: disable=protected-access
    owner_hidden = test_db.execute(sql_data._scoped_tools(request, {"email": "owner@example.com"}, statement, test_db)).scalar_one_or_none()  # pylint: disable=protected-access

    owner_request = Request({"type": "http", "method": "GET", "path": "/api/v1/data/library/main/authors", "headers": []})
    owner_request.state.token_teams = ["catalog-team"]
    visible = test_db.execute(sql_data._scoped_tools(owner_request, {"email": "owner@example.com"}, statement, test_db)).scalar_one_or_none()  # pylint: disable=protected-access

    assert hidden is None
    assert owner_hidden is None
    assert visible is not None


@pytest.mark.asyncio
async def test_catalog_lists_require_both_relation_ends_and_binding_tool_visible(test_db, external_source):
    _source, tables, _path = external_source
    SQLDataService.update_table(
        test_db,
        tables["books"].id,
        SQLTableUpdate(exposed=True, allow_query=True, visibility="public"),
        "owner@example.com",
    )
    tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["books"].id, DbTool.source_operation == "query")).scalar_one()
    tool.visibility = "private"
    tool.owner_email = "other@example.com"
    target = test_db.get(DbSQLTable, tables["authors"].id)
    target.visibility = "private"
    target.owner_email = "other@example.com"
    test_db.commit()

    request = Request({"type": "http", "method": "GET", "path": "/sql/catalog", "headers": []})
    request.state.token_teams = []
    user = {"email": "owner@example.com", "is_admin": False}

    relations = await sql_data.list_relations.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
        request=request,
        db=test_db,
        user=user,
    )
    bindings = await sql_data.list_bindings.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
        request=request,
        db=test_db,
        user=user,
    )

    assert relations == []
    assert bindings == []


@pytest.mark.asyncio
async def test_manage_scope_denies_team_member_and_admin_access_to_another_owner_private_table(test_db, external_source):
    _source, tables, _path = external_source
    table = tables["authors"]
    table.visibility = "private"
    table.team_id = "team-a"
    table.owner_email = "owner@example.com"
    test_db.commit()

    team_request = Request({"type": "http", "method": "PATCH", "path": f"/sql/tables/{table.id}", "headers": []})
    team_request.state.token_teams = ["team-a"]
    with pytest.raises(HTTPException) as team_error:
        await sql_data.update_table.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
            table_id=table.id,
            data=SQLTableUpdate(exposed=True),
            request=team_request,
            db=test_db,
            user={"email": "member@example.com", "is_admin": False},
        )
    assert team_error.value.status_code == 404

    admin_request = Request({"type": "http", "method": "PATCH", "path": f"/sql/tables/{table.id}", "headers": []})
    admin_request.state.token_teams = None
    with pytest.raises(HTTPException) as admin_error:
        await sql_data.update_table.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
            table_id=table.id,
            data=SQLTableUpdate(exposed=True),
            request=admin_request,
            db=test_db,
            user={"email": "admin@example.com", "is_admin": True},
        )
    assert admin_error.value.status_code == 404


@pytest.mark.asyncio
async def test_create_binding_preserves_admin_identity_for_private_tool_scope(test_db, external_source):
    _source, tables, _path = external_source
    table = tables["authors"]
    table.visibility = "public"
    own_tool = DbTool(
        original_name="admin-private-tool",
        custom_name="admin-private-tool",
        custom_name_slug="admin-private-tool",
        display_name="Admin Private Tool",
        url="https://example.com/admin-private",
        description="owned by the requesting admin",
        integration_type="REST",
        request_type="GET",
        input_schema={"type": "object", "properties": {}},
        annotations={},
        owner_email="admin@example.com",
        visibility="private",
    )
    other_tool = DbTool(
        original_name="other-private-tool",
        custom_name="other-private-tool",
        custom_name_slug="other-private-tool",
        display_name="Other Private Tool",
        url="https://example.com/other-private",
        description="owned by another user",
        integration_type="REST",
        request_type="GET",
        input_schema={"type": "object", "properties": {}},
        annotations={},
        owner_email="other@example.com",
        visibility="private",
    )
    test_db.add_all((own_tool, other_tool))
    test_db.commit()
    request = Request({"type": "http", "method": "POST", "path": "/sql/bindings", "headers": []})
    request.state.token_teams = None
    admin = {"email": "admin@example.com", "is_admin": True}

    binding = await sql_data.create_binding.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
        data=APISQLTableBindingCreate(tool_id=own_tool.id, sql_table_id=table.id),
        request=request,
        db=test_db,
        user=admin,
    )
    assert binding.tool_id == own_tool.id

    with pytest.raises(HTTPException) as hidden_error:
        await sql_data.create_binding.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
            data=APISQLTableBindingCreate(tool_id=other_tool.id, sql_table_id=table.id),
            request=request,
            db=test_db,
            user=admin,
        )
    assert hidden_error.value.status_code == 404


@pytest.mark.asyncio
async def test_public_to_private_table_update_evicts_cached_tool_payload_and_bumps_version(test_db, external_source, monkeypatch):
    _source, tables, _path = external_source
    table = SQLDataService.update_table(
        test_db,
        tables["authors"].id,
        SQLTableUpdate(exposed=True, allow_query=True, visibility="public"),
        "owner@example.com",
    )
    tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == table.id, DbTool.source_operation == "query")).scalar_one()
    original_version = tool.version

    monkeypatch.setattr(tool_lookup_cache, "_enabled", True)
    monkeypatch.setattr(tool_lookup_cache, "_l2_enabled", False)
    tool_lookup_cache.invalidate_all_local()
    await tool_lookup_cache.set(tool.name, {"status": "ok", "tool": {"id": tool.id, "visibility": "public"}}, ttl=60)
    assert await tool_lookup_cache.get(tool.name) is not None

    request = Request({"type": "http", "method": "PATCH", "path": f"/sql/tables/{table.id}", "headers": []})
    request.state.token_teams = ["catalog-team"]
    await sql_data.update_table.__wrapped__(  # type: ignore[attr-defined]  # pylint: disable=no-member
        table_id=table.id,
        data=SQLTableUpdate(visibility="private"),
        request=request,
        db=test_db,
        user={"email": "owner@example.com", "is_admin": False},
    )

    test_db.refresh(tool)
    assert tool.visibility == "private"
    assert tool.version > original_version
    assert await tool_lookup_cache.get(tool.name) is None


def test_source_disable_discovery_and_delete_invalidate_and_version_generated_tools(test_db, external_source, monkeypatch):
    source, tables, _path = external_source
    SQLDataService.update_table(
        test_db,
        tables["authors"].id,
        SQLTableUpdate(exposed=True, allow_query=True),
        "owner@example.com",
    )
    tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["authors"].id, DbTool.source_operation == "query")).scalar_one()
    invalidator = MagicMock()
    monkeypatch.setattr(SQLDataService, "invalidate_tool_caches", invalidator)

    prior_version = tool.version
    SQLDataService.update_source(test_db, source.id, SQLDataSourceUpdate(enabled=False))
    test_db.refresh(tool)
    assert tool.enabled is False
    assert tool.deprecated is True
    assert tool.version > prior_version
    invalidator.assert_called()

    prior_version = tool.version
    SQLDataService.update_source(test_db, source.id, SQLDataSourceUpdate(enabled=True))
    SQLDataService.discover(test_db, source.id)
    test_db.refresh(tool)
    assert tool.enabled is True
    assert tool.version > prior_version

    prior_version = tool.version
    SQLDataService.delete_source(test_db, source.id)
    test_db.refresh(tool)
    assert tool.sql_table_id is None
    assert tool.enabled is False
    assert tool.version > prior_version
    assert invalidator.call_count >= 4


def test_rediscovery_marks_missing_table_and_tools_stale(test_db, external_source):
    source, tables, database_path = external_source
    SQLDataService.update_table(test_db, tables["books"].id, SQLTableUpdate(exposed=True, allow_query=True), "owner@example.com")
    tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["books"].id, DbTool.source_operation == "query")).scalar_one()

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DROP VIEW book_titles")
        connection.execute("DROP TABLE books")
        connection.commit()
    finally:
        connection.close()
    SQLDataService.discover(test_db, source.id)

    stale = test_db.get(DbSQLTable, tables["books"].id)
    test_db.refresh(tool)
    assert stale.stale is True
    assert stale.exposed is False
    assert tool.enabled is False
    assert tool.deprecated is True


def test_rediscovery_refreshes_generated_tool_schema(test_db, external_source):
    source, tables, database_path = external_source
    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_query=True), "owner@example.com")
    tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["authors"].id, DbTool.source_operation == "query")).scalar_one()

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("ALTER TABLE authors ADD COLUMN biography TEXT")
        connection.commit()
    finally:
        connection.close()

    SQLDataService.discover(test_db, source.id)
    test_db.refresh(tool)

    assert "biography" in tool.input_schema["properties"]["filter"]["properties"]


def test_sqlite_path_is_fail_closed(tmp_path, monkeypatch):
    database_path = tmp_path / "external.db"
    database_path.touch()
    monkeypatch.setattr(settings, "mcpgateway_sqlite_allowed_roots", [])

    with pytest.raises(SQLDataError, match="outside configured allowed roots"):
        SQLDataService.validate_connection_url(f"sqlite+pysqlite:///{database_path}")


def test_network_sources_require_tls(monkeypatch):
    monkeypatch.setattr(settings, "ssrf_protection_enabled", False)

    with pytest.raises(SQLDataError, match="must use TLS"):
        SQLDataService.validate_connection_url("postgresql+psycopg://user:pass@db.example/app?sslmode=disable")
    with pytest.raises(SQLDataError, match="must name a database"):
        SQLDataService.validate_connection_url("mysql+pymysql://user:pass@db.example")


def test_network_engines_enforce_tls(monkeypatch):
    monkeypatch.setattr(settings, "ssrf_protection_enabled", False)
    captured = []

    def fake_create_engine(url, **kwargs):
        captured.append((url, kwargs))
        return object()

    monkeypatch.setattr("mcpgateway.services.sql_data_service.create_engine", fake_create_engine)

    postgresql = type("Source", (), {"connection_url": "postgresql+psycopg://user:pass@db.example/app"})()
    mysql = type("Source", (), {"connection_url": "mysql+pymysql://user:pass@db.example/app"})()
    SQLDataService._engine(postgresql)  # pylint: disable=protected-access
    SQLDataService._engine(mysql)  # pylint: disable=protected-access

    assert captured[0][1]["connect_args"]["sslmode"] == "require"
    assert captured[1][1]["connect_args"]["ssl"]["check_hostname"] is True
    assert captured[1][1]["connect_args"]["ssl"]["verify_mode"] != 0
    assert all(issubclass(kwargs["poolclass"], QueuePool) for _url, kwargs in captured)
    assert all(kwargs["pool_size"] == settings.mcpgateway_sql_pool_size for _url, kwargs in captured)
    assert all(kwargs["max_overflow"] == settings.mcpgateway_sql_pool_max_overflow for _url, kwargs in captured)


def test_engine_cache_reuses_matching_source_across_remaining_deadlines(monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_sql_engine_cache_enabled", True)
    monkeypatch.setattr(settings, "mcpgateway_sql_engine_cache_max_entries", 4)
    created: list[_FakeEngine] = []
    creation_timeouts: list[float | None] = []

    def fake_engine(_cls, _source, timeout=None):
        engine = _FakeEngine()
        created.append(engine)
        creation_timeouts.append(timeout)
        return engine

    monkeypatch.setattr(SQLDataService, "_engine", classmethod(fake_engine))
    source = SimpleNamespace(id="source-1", dialect="sqlite+pysqlite", connection_url="sqlite+pysqlite:///:memory:")

    with SQLDataService._engine_lease(source, timeout=10) as first:  # pylint: disable=protected-access
        pass
    with SQLDataService._engine_lease(source, timeout=9.75) as reused:  # pylint: disable=protected-access
        pass
    with SQLDataService._engine_lease(source, timeout=2.25) as short_deadline:  # pylint: disable=protected-access
        pass

    assert reused is first
    assert short_deadline is first
    assert len(created) == 1
    assert creation_timeouts == [float(settings.mcpgateway_sql_timeout)]
    assert SQLDataService.engine_cache_size() == 1
    assert all(engine.dispose_calls == 0 for engine in created)

    SQLDataService.clear_engine_cache()
    assert all(engine.dispose_calls == 1 for engine in created)


def test_execute_reuses_engine_and_applies_each_statement_timeout(test_db, external_source, monkeypatch):
    """Connection pooling is stable while SQL deadlines remain invocation-specific."""
    _source, tables, _database_path = external_source
    SQLDataService.update_table(
        test_db,
        tables["authors"].id,
        SQLTableUpdate(exposed=True, allow_query=True),
        "owner@example.com",
    )
    observed_timeouts: list[float] = []
    apply_statement_timeout = SQLDataService._apply_statement_timeout  # pylint: disable=protected-access

    def capture_statement_timeout(connection, dialect, timeout):
        observed_timeouts.append(timeout)
        apply_statement_timeout(connection, dialect, timeout)

    monkeypatch.setattr(SQLDataService, "_apply_statement_timeout", staticmethod(capture_statement_timeout))
    initial_cache_size = SQLDataService.engine_cache_size()

    SQLDataService.execute(test_db, tables["authors"].id, "query", {}, timeout=4.75)
    SQLDataService.execute(test_db, tables["authors"].id, "query", {}, timeout=2.25)

    assert initial_cache_size == 1
    assert SQLDataService.engine_cache_size() == 1
    assert len(observed_timeouts) == 6
    assert all(0 < timeout <= 4.75 for timeout in observed_timeouts[:3])
    assert all(0 < timeout <= 2.25 for timeout in observed_timeouts[3:])
    assert sql_data_service_module._SQL_EXECUTION_DEADLINE.get() is None  # pylint: disable=protected-access


def test_execute_deadline_bounds_pool_checkout(test_db, external_source, monkeypatch):
    source, tables, _path = external_source
    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_query=True), "owner@example.com")
    monkeypatch.setattr(settings, "mcpgateway_sql_pool_size", 1)
    monkeypatch.setattr(settings, "mcpgateway_sql_pool_max_overflow", 0)
    monkeypatch.setattr(settings, "mcpgateway_sql_pool_checkout_timeout", 5.0)
    SQLDataService.clear_engine_cache()

    with SQLDataService._engine_lease(source) as engine:  # pylint: disable=protected-access
        held_connection = engine.connect()
        started = time.monotonic()
        try:
            with pytest.raises(SQLDataError, match="timed out"):
                SQLDataService.execute(test_db, tables["authors"].id, "query", {}, timeout=0.05)
        finally:
            held_connection.close()

    assert time.monotonic() - started < 0.5


def test_reflection_consumes_the_same_absolute_query_deadline(test_db, external_source, monkeypatch):
    _source, tables, _path = external_source
    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_query=True), "owner@example.com")
    real_table = sql_data_service_module.Table
    observed_timeouts: list[float] = []

    def delayed_reflection(*args, **kwargs):
        reflected = real_table(*args, **kwargs)
        if kwargs.get("autoload_with") is not None:
            time.sleep(0.03)
        return reflected

    monkeypatch.setattr(sql_data_service_module, "Table", delayed_reflection)
    monkeypatch.setattr(SQLDataService, "_apply_statement_timeout", staticmethod(lambda _connection, _dialect, timeout: observed_timeouts.append(timeout)))

    SQLDataService.execute(test_db, tables["authors"].id, "query", {}, timeout=0.2)

    assert len(observed_timeouts) == 3
    assert observed_timeouts[1] < observed_timeouts[0] - 0.02
    assert observed_timeouts[2] <= observed_timeouts[1]


def test_engine_cache_lru_defers_disposal_until_active_lease_releases(monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_sql_engine_cache_enabled", True)
    monkeypatch.setattr(settings, "mcpgateway_sql_engine_cache_max_entries", 1)
    created: list[_FakeEngine] = []

    def fake_engine(_cls, _source, timeout=None):
        engine = _FakeEngine()
        created.append(engine)
        return engine

    monkeypatch.setattr(SQLDataService, "_engine", classmethod(fake_engine))
    first_source = SimpleNamespace(id="source-1", dialect="sqlite+pysqlite", connection_url="sqlite+pysqlite:///:memory:")
    second_source = SimpleNamespace(id="source-2", dialect="sqlite+pysqlite", connection_url="sqlite+pysqlite:///:memory:")

    with SQLDataService._engine_lease(first_source, timeout=10) as first:  # pylint: disable=protected-access
        with SQLDataService._engine_lease(second_source, timeout=10) as second:  # pylint: disable=protected-access
            assert first is created[0]
            assert second is created[1]
            assert created[0].dispose_calls == 0
            assert SQLDataService.engine_cache_size() == 1
        assert created[0].dispose_calls == 0

    assert created[0].dispose_calls == 1
    assert created[1].dispose_calls == 0


def test_engine_cache_disabled_uses_short_lived_engine(monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_sql_engine_cache_enabled", False)
    engine = _FakeEngine()
    monkeypatch.setattr(SQLDataService, "_engine", classmethod(lambda _cls, _source, timeout=None: engine))
    source = SimpleNamespace(id="source-1", dialect="sqlite+pysqlite", connection_url="sqlite+pysqlite:///:memory:")

    with SQLDataService._engine_lease(source, timeout=10) as leased:  # pylint: disable=protected-access
        assert leased is engine
        assert engine.dispose_calls == 0

    assert engine.dispose_calls == 1
    assert SQLDataService.engine_cache_size() == 0


def test_invalidation_during_engine_creation_does_not_repopulate_cache(monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_sql_engine_cache_enabled", True)
    engine = _FakeEngine()
    source = SimpleNamespace(id="source-race", dialect="sqlite+pysqlite", connection_url="sqlite+pysqlite:///:memory:")

    def fake_engine(_cls, current_source, timeout=None):
        SQLDataService.invalidate_engine_cache(current_source.id)
        return engine

    monkeypatch.setattr(SQLDataService, "_engine", classmethod(fake_engine))

    with SQLDataService._engine_lease(source, timeout=10) as leased:  # pylint: disable=protected-access
        assert leased is engine
        assert SQLDataService.engine_cache_size() == 0
        assert engine.dispose_calls == 0

    assert engine.dispose_calls == 1


def test_mysql_discovery_is_limited_to_url_database():
    class Inspector:
        def get_schema_names(self):
            raise AssertionError("MySQL discovery must not enumerate sibling databases")

    assert SQLDataService._schema_names(Inspector(), "mysql+pymysql", "tenant_a") == ["tenant_a"]  # pylint: disable=protected-access


def test_source_url_rotation_invalidates_catalog_and_tools(test_db, external_source, tmp_path):
    source, tables, _database_path = external_source
    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_query=True), "owner@example.com")
    tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["authors"].id, DbTool.source_operation == "query")).scalar_one()
    replacement = tmp_path / "replacement.db"
    _create_external_database(replacement)

    SQLDataService.update_source(test_db, source.id, SQLDataSourceUpdate(connection_url=f"sqlite+pysqlite:///{replacement}"))
    test_db.refresh(tool)
    table = test_db.get(DbSQLTable, tables["authors"].id)

    assert table.stale is True
    assert table.exposed is False
    assert tool.enabled is False
    assert tool.deprecated is True
    with pytest.raises(SQLDataForbiddenError, match="not enabled"):
        SQLDataService.execute(test_db, table.id, "query", {})


def test_source_update_and_delete_invalidate_cached_engines(test_db, external_source):
    source, _tables, _database_path = external_source
    assert SQLDataService.engine_cache_size() == 1

    SQLDataService.update_source(test_db, source.id, SQLDataSourceUpdate(description="updated"))
    assert SQLDataService.engine_cache_size() == 0

    SQLDataService.discover(test_db, source.id)
    assert SQLDataService.engine_cache_size() == 1

    SQLDataService.delete_source(test_db, source.id)
    assert SQLDataService.engine_cache_size() == 0


def test_failed_discovery_preserves_last_known_good_catalog_and_tools(test_db, external_source, monkeypatch):
    source, tables, _database_path = external_source
    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_query=True), "owner@example.com")
    tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["authors"].id, DbTool.source_operation == "query")).scalar_one()

    monkeypatch.setattr(SQLDataService, "_engine", classmethod(lambda cls, source, timeout=None: (_ for _ in ()).throw(RuntimeError("offline"))))
    SQLDataService.invalidate_engine_cache(source.id)
    with pytest.raises(SQLDataError, match="discovery failed"):
        SQLDataService.discover(test_db, source.id)

    test_db.refresh(source)
    test_db.refresh(tool)
    table = test_db.get(DbSQLTable, tables["authors"].id)
    assert source.reachable is True
    assert source.last_error
    assert table.stale is False
    assert table.exposed is True
    assert tool.enabled is True
    assert tool.reachable is True


def test_oversized_write_response_rolls_back(test_db, external_source, monkeypatch):
    _source, tables, database_path = external_source
    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_insert=True), "owner@example.com")
    monkeypatch.setattr(settings, "mcpgateway_sql_max_response_bytes", 1)

    with pytest.raises(SQLDataError, match="response exceeds"):
        SQLDataService.execute(test_db, tables["authors"].id, "insert", {"values": {"id": 2, "name": "Grace"}})

    connection = sqlite3.connect(database_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM authors WHERE id = 2").fetchone()[0]
    finally:
        connection.close()
    assert count == 0
