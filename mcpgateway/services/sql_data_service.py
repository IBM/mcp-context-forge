# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/sql_data_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Governed external SQL discovery and shared REST/MCP execution.
"""

# Standard
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import ssl
from time import monotonic
from typing import Any, Iterable, Optional

# Third-Party
import orjson
from sqlalchemy import create_engine, delete, inspect, MetaData, select, Table, update
from sqlalchemy.engine import Connection, Engine, make_url, URL
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import APISQLTableBinding, SQLDataSource, SQLRelation
from mcpgateway.db import SQLTable as DbSQLTable
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import SQLDataSourceCreate, SQLDataSourceUpdate, SQLTableUpdate
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.display_name import generate_display_name

SUPPORTED_SQL_DIALECTS = {"postgresql+psycopg", "mysql+pymysql", "sqlite+pysqlite"}


class SQLDataError(ValueError):
    """Base error for governed external SQL operations."""


class SQLDataNotFoundError(SQLDataError):
    """Raised when a source, table, relation, or binding is absent."""


class SQLDataForbiddenError(SQLDataError):
    """Raised when a table policy does not allow an operation."""


def _json_value(value: Any) -> Any:
    """Convert common SQL values into deterministic JSON-compatible values."""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


class SQLDataService:
    """Manage SQL catalog metadata and execute allowlisted Core statements."""

    @staticmethod
    def validate_connection_url(connection_url: str) -> URL:
        """Validate driver, SSRF policy, and configured SQLite roots."""
        try:
            url = make_url(connection_url)
        except Exception as exc:
            raise SQLDataError("Invalid SQLAlchemy connection URL") from exc
        dialect = f"{url.get_backend_name()}+{url.get_driver_name()}"
        if dialect not in SUPPORTED_SQL_DIALECTS:
            raise SQLDataError("Unsupported SQL driver")
        if dialect == "sqlite+pysqlite":
            if url.query:
                raise SQLDataError("SQLite URI/query options are not permitted")
            if url.database == ":memory:":
                return url
            if not url.database:
                raise SQLDataError("SQLite data source must name a database file")
            database_path = Path(url.database).resolve()
            allowed_roots = [Path(root).resolve() for root in settings.mcpgateway_sqlite_allowed_roots]
            if not allowed_roots or not any(database_path.is_relative_to(root) for root in allowed_roots):
                raise SQLDataError("SQLite database path is outside configured allowed roots")
            if not database_path.is_file():
                raise SQLDataError("SQLite database file does not exist")
        else:
            if not url.host:
                raise SQLDataError("Network SQL data source requires a hostname")
            if dialect == "mysql+pymysql" and not url.database:
                raise SQLDataError("MySQL data source must name a database")
            if dialect == "postgresql+psycopg":
                sslmode = str(url.query.get("sslmode", "require")).lower()
                if sslmode in {"disable", "allow", "prefer"}:
                    raise SQLDataError("PostgreSQL data source must use TLS")
            if dialect == "mysql+pymysql" and any(key.startswith("ssl_") for key in url.query):
                raise SQLDataError("MySQL TLS options must be configured by the gateway")
            if getattr(settings, "ssrf_protection_enabled", True):
                try:
                    SecurityValidator._validate_ssrf(url.host, "SQL data source host")  # pylint: disable=protected-access
                except ValueError as exc:
                    raise SQLDataError(str(exc)) from exc
        return url

    @staticmethod
    def mask_connection_url(url: URL) -> str:
        """Render a credential-free address suitable for API responses and logs."""
        if url.get_backend_name() == "sqlite":
            return "sqlite+pysqlite:///…/" + (Path(url.database).name if url.database and url.database != ":memory:" else ":memory:")
        return url.render_as_string(hide_password=True)

    @classmethod
    def _engine(cls, source: SQLDataSource, timeout: Optional[float] = None) -> Engine:
        """Create a short-lived engine with dialect-specific connection timeouts."""
        url = cls.validate_connection_url(source.connection_url)
        timeout_seconds = float(timeout if timeout is not None else settings.mcpgateway_sql_timeout)
        connect_args: dict[str, Any] = {}
        if url.get_backend_name() == "postgresql":
            connect_args["connect_timeout"] = max(1, int(timeout_seconds))
            connect_args["sslmode"] = str(url.query.get("sslmode", "require"))
        elif url.get_backend_name() == "mysql":
            connect_args["connect_timeout"] = max(1, int(timeout_seconds))
            connect_args["ssl"] = {"check_hostname": True, "verify_mode": ssl.CERT_REQUIRED}
        elif url.get_backend_name() == "sqlite":
            connect_args.update({"timeout": timeout_seconds, "check_same_thread": False})
        return create_engine(url, poolclass=NullPool, pool_pre_ping=True, connect_args=connect_args)

    @staticmethod
    def _apply_statement_timeout(connection: Connection, dialect: str, timeout: float) -> None:
        """Apply a driver-level statement timeout without accepting user SQL."""
        timeout_ms = max(1, int(timeout * 1000))
        if dialect == "postgresql":
            connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")
        elif dialect == "mysql":
            connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {timeout_ms}")
            connection.exec_driver_sql(f"SET SESSION innodb_lock_wait_timeout = {max(1, int(timeout))}")
        elif dialect == "sqlite+pysqlite":
            deadline = monotonic() + timeout
            connection.connection.driver_connection.set_progress_handler(lambda: 1 if monotonic() >= deadline else 0, 1000)

    @classmethod
    def create_source(cls, db: Session, data: SQLDataSourceCreate, user_email: Optional[str]) -> SQLDataSource:
        """Persist a validated encrypted source configuration."""
        url = cls.validate_connection_url(data.connection_url)
        source = SQLDataSource(
            name=data.name,
            slug=slugify(data.name),
            description=data.description,
            dialect=f"{url.get_backend_name()}+{url.get_driver_name()}",
            connection_url=data.connection_url,
            masked_url=cls.mask_connection_url(url),
            enabled=data.enabled,
            created_by=user_email,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        return source

    @classmethod
    def update_source(cls, db: Session, source_id: str, data: SQLDataSourceUpdate) -> SQLDataSource:
        """Update a source and invalidate connectivity state when credentials change."""
        source = db.get(SQLDataSource, source_id)
        if source is None:
            raise SQLDataNotFoundError("SQL data source not found")
        values = data.model_dump(exclude_unset=True)
        if "connection_url" in values:
            url = cls.validate_connection_url(values["connection_url"])
            source.connection_url = values.pop("connection_url")
            source.dialect = f"{url.get_backend_name()}+{url.get_driver_name()}"
            source.masked_url = cls.mask_connection_url(url)
            source.reachable = False
            for table in db.execute(select(DbSQLTable).where(DbSQLTable.source_id == source.id)).scalars():
                table.stale = True
                table.exposed = False
                db.execute(update(DbTool).where(DbTool.sql_table_id == table.id).values(enabled=False, deprecated=True, reachable=False))
        for field, value in values.items():
            setattr(source, field, value)
        if data.name:
            source.slug = slugify(data.name)
        source.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(source)
        return source

    @classmethod
    def test_source(cls, db: Session, source_id: str) -> dict[str, Any]:
        """Test connectivity without leaking connection details."""
        source = db.get(SQLDataSource, source_id)
        if source is None:
            raise SQLDataNotFoundError("SQL data source not found")
        engine = cls._engine(source)
        started = datetime.now(timezone.utc)
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            source.reachable = True
            source.last_error = None
        except Exception as exc:
            source.reachable = False
            source.last_error = SecurityValidator.sanitize_display_text(str(exc), "SQL connection error")[:1000]
        finally:
            engine.dispose()
        source.last_tested_at = datetime.now(timezone.utc)
        db.commit()
        return {"reachable": source.reachable, "latency_ms": (datetime.now(timezone.utc) - started).total_seconds() * 1000, "error": source.last_error}

    @staticmethod
    def _schema_names(inspector, dialect: str, database: Optional[str] = None) -> list[str]:
        """Return discoverable schemas within the configured database only."""
        if dialect == "sqlite+pysqlite":
            return ["main"]
        if dialect == "mysql+pymysql":
            return [database] if database else []
        schemas = inspector.get_schema_names()
        excluded = {"information_schema", "pg_catalog", "mysql", "performance_schema", "sys"}
        return sorted(schema for schema in schemas if schema not in excluded)

    @staticmethod
    def _safe_inspector_call(callable_obj, default):
        """Return a fallback when optional reflection metadata is unavailable."""
        try:
            return callable_obj()
        except (NotImplementedError, AttributeError):
            return default

    @classmethod
    def discover(cls, db: Session, source_id: str) -> list[DbSQLTable]:
        """Reflect tables/views, upsert hashes, preserve stale records, and discover FKs."""
        source = db.get(SQLDataSource, source_id)
        if source is None:
            raise SQLDataNotFoundError("SQL data source not found")
        if not source.enabled:
            raise SQLDataForbiddenError("SQL data source is disabled")
        engine: Optional[Engine] = None
        seen: set[tuple[str, str]] = set()
        foreign_keys: list[tuple[str, str, dict[str, Any]]] = []
        discovered_records: list[DbSQLTable] = []
        # Snapshot the active catalog before reflecting, so candidate validation
        # compares against what was there before this discovery started.
        existing_before = list(db.execute(select(DbSQLTable).where(DbSQLTable.source_id == source.id)).scalars())
        try:
            engine = cls._engine(source)
            inspector = inspect(engine)
            source_url = cls.validate_connection_url(source.connection_url)
            for schema_name in cls._schema_names(inspector, source.dialect, source_url.database):
                table_names = sorted(inspector.get_table_names(schema=schema_name))
                view_names = sorted(inspector.get_view_names(schema=schema_name))
                for object_type, names in (("table", table_names), ("view", view_names)):
                    for table_name in names:
                        columns = [
                            {
                                "name": column["name"],
                                "type": str(column["type"]),
                                "nullable": bool(column.get("nullable", True)),
                                "default": str(column["default"]) if column.get("default") is not None else None,
                            }
                            for column in inspector.get_columns(table_name, schema=schema_name)
                        ]
                        pk = list((inspector.get_pk_constraint(table_name, schema=schema_name) or {}).get("constrained_columns") or [])
                        unique_rows = cls._safe_inspector_call(lambda table=table_name, schema=schema_name: inspector.get_unique_constraints(table, schema=schema), [])
                        unique_keys = [list(item.get("column_names") or []) for item in unique_rows if item.get("column_names")]
                        signature = {"object_type": object_type, "columns": columns, "primary_key": pk, "unique_keys": unique_keys}
                        schema_hash = hashlib.sha256(json.dumps(signature, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                        normalized_schema = "" if source.dialect == "sqlite+pysqlite" else schema_name
                        record = db.execute(
                            select(DbSQLTable).where(
                                DbSQLTable.source_id == source.id,
                                DbSQLTable.schema_name == normalized_schema,
                                DbSQLTable.table_name == table_name,
                            )
                        ).scalar_one_or_none()
                        if record is None:
                            record = DbSQLTable(
                                source_id=source.id,
                                schema_name=normalized_schema,
                                schema_slug=slugify(normalized_schema or "default"),
                                table_name=table_name,
                                table_slug=slugify(table_name),
                                object_type=object_type,
                                columns=columns,
                                primary_key=pk,
                                unique_keys=unique_keys,
                                schema_hash=schema_hash,
                            )
                            db.add(record)
                            db.flush()
                        else:
                            record.object_type = object_type
                            record.columns = columns
                            record.primary_key = pk
                            record.unique_keys = unique_keys
                            record.schema_hash = schema_hash
                            record.stale = False
                            if object_type == "view":
                                record.allow_insert = record.allow_update = record.allow_delete = False
                        seen.add((normalized_schema, table_name))
                        discovered_records.append(record)
                        if object_type == "table":
                            for foreign_key in cls._safe_inspector_call(lambda table=table_name, schema=schema_name: inspector.get_foreign_keys(table, schema=schema), []):
                                foreign_keys.append((normalized_schema, table_name, foreign_key))

            disappearing = [record for record in existing_before if (record.schema_name, record.table_name) not in seen]
            # Validate the candidate catalog before replacing the active one. If the
            # candidate is empty or would drop every pre-existing table, the
            # connection is likely pointing at the wrong/empty database — refuse to
            # replace so the last-known-good catalog and its tools stay intact.
            if existing_before:
                if not discovered_records:
                    raise SQLDataError(f"discovery would replace {len(existing_before)} table(s) with an empty catalog")
                if len(disappearing) == len(existing_before):
                    raise SQLDataError("discovery would drop every existing table; refusing to replace the active catalog")
            existing_records = list(db.execute(select(DbSQLTable).where(DbSQLTable.source_id == source.id)).scalars())
            for record in existing_records:
                if (record.schema_name, record.table_name) not in seen:
                    record.stale = True
                    record.exposed = False
                    db.execute(update(DbTool).where(DbTool.sql_table_id == record.id).values(enabled=False, deprecated=True, reachable=False))

            record_map = {(record.schema_name, record.table_name): record for record in existing_records + discovered_records}
            db.execute(update(SQLRelation).where(SQLRelation.source_table_id.in_([record.id for record in record_map.values()])).values(stale=True))
            for schema_name, table_name, foreign_key in foreign_keys:
                source_table = record_map.get((schema_name, table_name))
                remote_schema = foreign_key.get("referred_schema")
                if source.dialect == "sqlite+pysqlite":
                    remote_schema = ""
                elif remote_schema is None:
                    remote_schema = schema_name
                target_table = record_map.get((remote_schema, foreign_key.get("referred_table")))
                if source_table is None or target_table is None:
                    continue
                local_columns = list(foreign_key.get("constrained_columns") or [])
                remote_columns = list(foreign_key.get("referred_columns") or [])
                if not local_columns or len(local_columns) != len(remote_columns):
                    continue
                relation_name = slugify(foreign_key.get("name") or f"{source_table.table_name}_{'_'.join(local_columns)}_{target_table.table_name}")
                relation = db.execute(select(SQLRelation).where(SQLRelation.source_table_id == source_table.id, SQLRelation.name == relation_name)).scalar_one_or_none()
                if relation is None:
                    relation = SQLRelation(
                        source_table_id=source_table.id,
                        target_table_id=target_table.id,
                        name=relation_name,
                        local_columns=local_columns,
                        remote_columns=remote_columns,
                    )
                    db.add(relation)
                else:
                    relation.target_table_id = target_table.id
                    relation.local_columns = local_columns
                    relation.remote_columns = remote_columns
                    relation.stale = False
            for record in discovered_records:
                if record.exposed:
                    cls.sync_tools(db, record.id, commit=False)
            source.reachable = True
            source.last_error = None
            source.last_discovered_at = datetime.now(timezone.utc)
            db.commit()
            return list(db.execute(select(DbSQLTable).where(DbSQLTable.source_id == source.id).order_by(DbSQLTable.schema_name, DbSQLTable.table_name)).scalars())
        except SQLDataError as exc:
            # Candidate validation rejected the replacement (empty catalog / all
            # tables disappearing), or connection validation failed before
            # reflection. Roll back so the active catalog is untouched, record the
            # failure for observability, and surface the specific reason.
            db.rollback()
            source = db.get(SQLDataSource, source_id)
            if source is not None:
                source.last_error = SecurityValidator.sanitize_display_text(str(exc), "SQL discovery error")[:1000]
                source.last_discovered_at = datetime.now(timezone.utc)
                db.commit()
            raise exc
        except Exception as exc:
            # A failed discovery is a transient connectivity problem, not a catalog
            # change. Preserve the last-known-good state: leave reachable, stale,
            # and generated tools untouched so a temporary outage does not disable
            # the whole SQL tool set. Only record the failure for observability.
            db.rollback()
            source = db.get(SQLDataSource, source_id)
            if source is not None:
                source.last_error = SecurityValidator.sanitize_display_text(str(exc), "SQL discovery error")[:1000]
                source.last_discovered_at = datetime.now(timezone.utc)
                db.commit()
            raise SQLDataError("SQL discovery failed") from exc
        finally:
            if engine is not None:
                engine.dispose()

    @staticmethod
    def _column_schema(column: dict[str, Any]) -> dict[str, Any]:
        """Map reflected SQL type names to a conservative JSON Schema shape."""
        sql_type = str(column.get("type") or "").upper()
        if any(fragment in sql_type for fragment in ("INT", "SERIAL")):
            schema: dict[str, Any] = {"type": "integer"}
        elif any(fragment in sql_type for fragment in ("NUMERIC", "DECIMAL", "REAL", "FLOAT", "DOUBLE")):
            schema = {"type": "number"}
        elif "BOOL" in sql_type:
            schema = {"type": "boolean"}
        elif "TIMESTAMP" in sql_type or "DATETIME" in sql_type:
            schema = {"type": "string", "format": "date-time"}
        elif sql_type == "DATE" or sql_type.startswith("DATE("):
            schema = {"type": "string", "format": "date"}
        elif sql_type == "TIME" or sql_type.startswith("TIME("):
            schema = {"type": "string", "format": "time"}
        elif "JSON" in sql_type:
            schema = {}
        elif any(fragment in sql_type for fragment in ("BINARY", "BLOB", "BYTEA")):
            schema = {"type": "string", "contentEncoding": "base64"}
        else:
            schema = {"type": "string"}
        schema["x-sql-type"] = str(column.get("type") or "unknown")
        if column.get("nullable"):
            schema["x-nullable"] = True
        if column.get("default") is not None:
            schema["x-sql-default"] = str(column["default"])
        return schema

    @staticmethod
    def _tool_schema(operation: str, table: DbSQLTable) -> dict[str, Any]:
        """Build a bounded JSON Schema for one reflected table operation."""
        properties: dict[str, Any] = {column["name"]: SQLDataService._column_schema(column) for column in table.columns}
        if operation == "query":
            return {
                "type": "object",
                "properties": {
                    "key": {"type": "object", "properties": properties},
                    "filter": {"type": "object", "properties": properties, "additionalProperties": False},
                    "fields": {"type": "array", "items": {"type": "string"}},
                    "sort": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "minimum": 1, "maximum": settings.mcpgateway_sql_max_limit},
                    "offset": {"type": "integer", "minimum": 0},
                    "include": {"type": "array", "items": {"type": "string"}, "maxItems": settings.mcpgateway_sql_max_includes},
                },
                "additionalProperties": False,
            }
        if operation == "insert":
            required_values = [column["name"] for column in table.columns if not column.get("nullable", True) and column.get("default") is None and column["name"] not in table.primary_key]
            values_schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
            if required_values:
                values_schema["required"] = required_values
            return {"type": "object", "properties": {"values": values_schema}, "required": ["values"], "additionalProperties": False}
        schema = {
            "type": "object",
            "properties": {"key": {"type": "object", "properties": properties, "additionalProperties": False}},
            "required": ["key"],
            "additionalProperties": False,
        }
        if operation == "update":
            schema["properties"]["values"] = {"type": "object", "properties": properties, "additionalProperties": False}
            schema["required"].append("values")
        return schema

    @classmethod
    def sync_tools(cls, db: Session, table_id: str, *, commit: bool = True) -> list[DbTool]:
        """Create/update stable SQL tools and disable operations no longer exposed."""
        table = db.get(DbSQLTable, table_id)
        if table is None:
            raise SQLDataNotFoundError("SQL table not found")
        source = db.get(SQLDataSource, table.source_id)
        if source is None:
            raise SQLDataNotFoundError("SQL data source not found")
        key_available = bool(table.primary_key or table.unique_keys)
        desired = {
            "query": table.exposed and table.allow_query and not table.stale,
            "insert": table.exposed and table.allow_insert and table.object_type == "table" and not table.stale,
            "update": table.exposed and table.allow_update and table.object_type == "table" and key_available and not table.stale,
            "delete": table.exposed and table.allow_delete and table.object_type == "table" and key_available and not table.stale,
        }
        result: list[DbTool] = []
        for operation, enabled in desired.items():
            name = f"sql.{source.slug}.{table.schema_slug}.{table.table_slug}.{operation}"
            tool = db.execute(select(DbTool).where(DbTool.sql_table_id == table.id, DbTool.source_operation == operation)).scalar_one_or_none()
            if tool is None and enabled:
                tool = DbTool(
                    original_name=name,
                    custom_name=name,
                    custom_name_slug=slugify(name),
                    display_name=generate_display_name(name),
                    url=f"/api/v1/data/{source.slug}/{table.schema_slug}/{table.table_slug}",
                    original_description=f"Governed SQL {operation} on {source.name}.{table.table_name}",
                    description=f"Governed SQL {operation} on {source.name}.{table.table_name}",
                    integration_type="SQL",
                    request_type="POST",
                    input_schema=cls._tool_schema(operation, table),
                    output_schema={"type": "object"},
                    annotations={"readOnlyHint": operation == "query", "destructiveHint": operation == "delete"},
                    created_by="system",
                    created_via="sql-discovery",
                    federation_source=source.name,
                    team_id=table.team_id,
                    owner_email=table.owner_email,
                    visibility=table.visibility,
                    sql_table_id=table.id,
                    source_operation=operation,
                )
                db.add(tool)
                db.flush()
            if tool is not None:
                tool.input_schema = cls._tool_schema(operation, table)
                tool.url = f"/api/v1/data/{source.slug}/{table.schema_slug}/{table.table_slug}"
                tool.enabled = enabled
                tool.deprecated = not enabled
                tool.reachable = enabled and source.reachable
                tool.team_id = table.team_id
                tool.owner_email = table.owner_email
                tool.visibility = table.visibility
                binding = db.execute(select(APISQLTableBinding).where(APISQLTableBinding.tool_id == tool.id, APISQLTableBinding.sql_table_id == table.id)).scalar_one_or_none()
                if binding is None:
                    db.add(
                        APISQLTableBinding(
                            tool_id=tool.id,
                            sql_table_id=table.id,
                            access_mode="read" if operation == "query" else "write",
                            binding_type="auto",
                            created_by="system",
                        )
                    )
                result.append(tool)
        if commit:
            db.commit()
        return result

    @classmethod
    def update_table(cls, db: Session, table_id: str, data: SQLTableUpdate, user_email: Optional[str]) -> DbSQLTable:
        """Apply team/exposure policy and synchronize generated tools."""
        table = db.get(DbSQLTable, table_id)
        if table is None:
            raise SQLDataNotFoundError("SQL table not found")
        values = data.model_dump(exclude_unset=True)
        if table.object_type == "view" and any(values.get(name) for name in ("allow_insert", "allow_update", "allow_delete")):
            raise SQLDataForbiddenError("Views are always read-only")
        if any(values.get(name) for name in ("allow_update", "allow_delete")) and not (table.primary_key or table.unique_keys):
            raise SQLDataForbiddenError("Update/delete requires a primary key or explicit unique key")
        for field, value in values.items():
            setattr(table, field, value)
        if user_email and not table.owner_email:
            table.owner_email = user_email
        table.updated_at = datetime.now(timezone.utc)
        db.flush()
        cls.sync_tools(db, table.id)
        db.refresh(table)
        return table

    @staticmethod
    def _validate_columns(table: Table, values: Iterable[str]) -> list[str]:
        """Reject identifiers that were not present in the reflected table."""
        columns = list(values)
        unknown = sorted(set(columns) - set(table.c.keys()))
        if unknown:
            raise SQLDataError(f"Unknown column(s): {', '.join(unknown)}")
        return columns

    @classmethod
    def _key_clause(cls, reflected: Table, catalog: DbSQLTable, key: Any):
        """Build predicates from one complete primary or explicit unique key."""
        if not isinstance(key, dict) or not key:
            raise SQLDataError("key must be a non-empty JSON object")
        cls._validate_columns(reflected, key)
        allowed_keys = [list(catalog.primary_key), *[list(item) for item in catalog.unique_keys]]
        if sorted(key) not in [sorted(candidate) for candidate in allowed_keys if candidate]:
            raise SQLDataError("key must exactly match the primary key or an explicit unique key")
        return [reflected.c[name] == key[name] for name in key]

    @classmethod
    def execute(cls, db: Session, table_id: str, operation: str, arguments: dict[str, Any], timeout: Optional[float] = None) -> dict[str, Any]:
        """Execute one allowlisted Core operation in a single transaction."""
        catalog = db.get(DbSQLTable, table_id)
        if catalog is None:
            raise SQLDataNotFoundError("SQL table not found")
        source = db.get(SQLDataSource, catalog.source_id)
        if source is None:
            raise SQLDataNotFoundError("SQL data source not found")
        allowed = {
            "query": catalog.allow_query,
            "insert": catalog.allow_insert and catalog.object_type == "table",
            "update": catalog.allow_update and catalog.object_type == "table",
            "delete": catalog.allow_delete and catalog.object_type == "table",
        }
        if not settings.mcpgateway_sql_api_enabled or not source.enabled or not catalog.exposed or catalog.stale or not allowed.get(operation, False):
            raise SQLDataForbiddenError("SQL operation is not enabled")

        effective_timeout = float(timeout if timeout is not None else settings.mcpgateway_sql_timeout)
        if not 0 < effective_timeout <= 600:
            raise SQLDataError("SQL timeout must be greater than zero and no more than 600 seconds")
        engine = cls._engine(source, timeout=effective_timeout)
        try:
            reflected = Table(catalog.table_name, MetaData(), schema=catalog.schema_name or None, autoload_with=engine)
            with engine.begin() as connection:
                cls._apply_statement_timeout(connection, source.dialect, effective_timeout)
                if operation == "query":
                    fields = arguments.get("fields") or list(reflected.c.keys())
                    cls._validate_columns(reflected, fields)
                    statement = select(*[reflected.c[name] for name in fields])
                    key = arguments.get("key")
                    if key:
                        statement = statement.where(*cls._key_clause(reflected, catalog, key))
                    filters = arguments.get("filter") or {}
                    if not isinstance(filters, dict):
                        raise SQLDataError("filter must be a JSON object")
                    cls._validate_columns(reflected, filters)
                    if filters:
                        statement = statement.where(*[reflected.c[name] == value for name, value in filters.items()])
                    sort = arguments.get("sort") or []
                    if isinstance(sort, str):
                        sort = [item for item in sort.split(",") if item]
                    for item in sort:
                        name = item[1:] if item.startswith("-") else item
                        cls._validate_columns(reflected, [name])
                        statement = statement.order_by(reflected.c[name].desc() if item.startswith("-") else reflected.c[name].asc())
                    raw_limit = arguments.get("limit")
                    requested_limit = settings.mcpgateway_sql_default_limit if raw_limit is None else int(raw_limit)
                    if requested_limit < 1:
                        raise SQLDataError("limit must be at least 1")
                    limit = min(requested_limit, settings.mcpgateway_sql_max_limit)
                    offset = max(int(arguments.get("offset") or 0), 0)
                    rows = [dict(row._mapping) for row in connection.execute(statement.limit(limit).offset(offset))]  # pylint: disable=protected-access
                    cls._expand_relations(db, connection, rows, catalog, arguments.get("include") or [])
                    response: dict[str, Any] = {"items": _json_value(rows), "count": len(rows), "limit": limit, "offset": offset}
                elif operation == "insert":
                    values = arguments.get("values")
                    if not isinstance(values, dict) or not values:
                        raise SQLDataError("values must be a non-empty JSON object")
                    cls._validate_columns(reflected, values)
                    result = connection.execute(reflected.insert().values(**values))
                    response = {"affected": result.rowcount, "inserted_primary_key": _json_value(list(result.inserted_primary_key))}
                elif operation == "update":
                    values = arguments.get("values")
                    if not isinstance(values, dict) or not values:
                        raise SQLDataError("values must be a non-empty JSON object")
                    cls._validate_columns(reflected, values)
                    result = connection.execute(reflected.update().where(*cls._key_clause(reflected, catalog, arguments.get("key"))).values(**values))
                    response = {"affected": result.rowcount}
                elif operation == "delete":
                    result = connection.execute(reflected.delete().where(*cls._key_clause(reflected, catalog, arguments.get("key"))))
                    response = {"affected": result.rowcount}
                else:
                    raise SQLDataError("Unsupported SQL operation")
                serialized = orjson.dumps(response, default=str)
                if len(serialized) > settings.mcpgateway_sql_max_response_bytes:
                    raise SQLDataError("SQL response exceeds the configured size limit")
            return response
        finally:
            engine.dispose()

    @classmethod
    def _expand_relations(cls, db: Session, connection: Connection, rows: list[dict[str, Any]], catalog: DbSQLTable, includes: Any) -> None:
        """Expand explicitly enabled, visible one-hop relations only."""
        if isinstance(includes, str):
            includes = [item for item in includes.split(",") if item]
        if not isinstance(includes, list) or len(includes) > settings.mcpgateway_sql_max_includes:
            raise SQLDataError("include exceeds the configured relation limit")
        for relation_name in includes:
            relation = db.execute(
                select(SQLRelation).where(
                    SQLRelation.source_table_id == catalog.id,
                    SQLRelation.name == relation_name,
                    SQLRelation.enabled.is_(True),
                    SQLRelation.stale.is_(False),
                )
            ).scalar_one_or_none()
            if relation is None:
                raise SQLDataForbiddenError(f"Relation '{relation_name}' is not enabled")
            target = db.get(DbSQLTable, relation.target_table_id)
            if (
                target is None
                or target.source_id != catalog.source_id
                or not target.exposed
                or not target.allow_query
                or target.stale
                or target.visibility != catalog.visibility
                or target.team_id != catalog.team_id
                or (catalog.visibility == "private" and target.owner_email != catalog.owner_email)
            ):
                raise SQLDataForbiddenError("Related table is not visible in the caller's scope")
            if not relation.local_columns or len(relation.local_columns) != len(relation.remote_columns):
                raise SQLDataForbiddenError("Relation column mapping is invalid")
            target_table = Table(target.table_name, MetaData(), schema=target.schema_name or None, autoload_with=connection)
            for row in rows:
                predicates = [target_table.c[remote] == row.get(local) for local, remote in zip(relation.local_columns, relation.remote_columns)]
                related = connection.execute(select(target_table).where(*predicates).limit(settings.mcpgateway_sql_default_limit)).mappings().all()
                row[relation.name] = [dict(item) for item in related]

    @staticmethod
    def create_binding(db: Session, tool_id: str, table_id: str, access_mode: str, created_by: Optional[str]) -> APISQLTableBinding:
        """Create a manual catalog binding; it does not alter execution policy."""
        if db.get(DbTool, tool_id) is None or db.get(DbSQLTable, table_id) is None:
            raise SQLDataNotFoundError("Tool or SQL table not found")
        binding = APISQLTableBinding(tool_id=tool_id, sql_table_id=table_id, access_mode=access_mode, binding_type="manual", created_by=created_by)
        db.add(binding)
        db.commit()
        db.refresh(binding)
        return binding

    @staticmethod
    def delete_source(db: Session, source_id: str) -> None:
        """Delete a source and generated catalog records."""
        source = db.get(SQLDataSource, source_id)
        if source is None:
            raise SQLDataNotFoundError("SQL data source not found")
        table_ids = list(db.execute(select(DbSQLTable.id).where(DbSQLTable.source_id == source_id)).scalars())
        if table_ids:
            db.execute(update(DbTool).where(DbTool.sql_table_id.in_(table_ids)).values(sql_table_id=None, enabled=False, deprecated=True, reachable=False))
            db.execute(delete(APISQLTableBinding).where(APISQLTableBinding.sql_table_id.in_(table_ids)))
        db.delete(source)
        db.commit()
