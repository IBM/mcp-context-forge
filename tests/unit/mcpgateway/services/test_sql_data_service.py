# -*- coding: utf-8 -*-
"""Tests for governed external SQL discovery and execution."""

# Standard
import sqlite3
import uuid

# Third-Party
import pytest
from sqlalchemy import select
from starlette.requests import Request

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import SQLRelation
from mcpgateway.db import SQLTable as DbSQLTable
from mcpgateway.db import Tool as DbTool
from mcpgateway.routers import sql_data
from mcpgateway.schemas import SQLDataSourceCreate, SQLDataSourceUpdate, SQLTableUpdate
from mcpgateway.services.sql_data_service import SQLDataError, SQLDataForbiddenError, SQLDataService


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

    hidden = test_db.execute(sql_data._scoped_tools(request, {"email": "other@example.com"}, statement)).scalar_one_or_none()  # pylint: disable=protected-access
    visible = test_db.execute(sql_data._scoped_tools(request, {"email": "owner@example.com"}, statement)).scalar_one_or_none()  # pylint: disable=protected-access

    assert hidden is None
    assert visible is not None


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


def test_failed_discovery_disables_existing_tools(test_db, external_source, monkeypatch):
    source, tables, _database_path = external_source
    SQLDataService.update_table(test_db, tables["authors"].id, SQLTableUpdate(exposed=True, allow_query=True), "owner@example.com")
    tool = test_db.execute(select(DbTool).where(DbTool.sql_table_id == tables["authors"].id, DbTool.source_operation == "query")).scalar_one()

    monkeypatch.setattr(SQLDataService, "_engine", classmethod(lambda cls, source, timeout=None: (_ for _ in ()).throw(RuntimeError("offline"))))
    with pytest.raises(SQLDataError, match="discovery failed"):
        SQLDataService.discover(test_db, source.id)

    test_db.refresh(source)
    test_db.refresh(tool)
    table = test_db.get(DbSQLTable, tables["authors"].id)
    assert source.reachable is False
    assert table.stale is True
    assert table.exposed is True
    assert tool.enabled is False
    assert tool.reachable is False
    with pytest.raises(SQLDataForbiddenError, match="not enabled"):
        SQLDataService.execute(test_db, table.id, "query", {})



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
