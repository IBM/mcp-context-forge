# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/sql_data.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Admin SQL catalog APIs and the governed public data endpoint.
"""

# Standard
from typing import Any, Optional

# Third-Party
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
import orjson
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

# First-Party
from mcpgateway.auth_context import get_scoped_resource_access_context, get_user_email
from mcpgateway.config import settings
from mcpgateway.db import APISQLTableBinding, EmailTeam, get_db, SQLDataSource, SQLRelation
from mcpgateway.db import SQLTable as DbSQLTable
from mcpgateway.db import Tool as DbTool
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import (
    APISQLTableBindingCreate,
    APISQLTableBindingRead,
    APISQLTableBindingReadDetail,
    SQLDataSourceCreate,
    SQLDataSourceRead,
    SQLDataSourceUpdate,
    SQLRelationRead,
    SQLRelationUpdate,
    SQLTableRead,
    SQLTableUpdate,
)
from mcpgateway.services.base_service import BaseService
from mcpgateway.services.sql_data_service import SQLDataError, SQLDataForbiddenError, SQLDataNotFoundError, SQLDataService
from mcpgateway.services.tool_service import tool_service, ToolNotFoundError

admin_router = APIRouter(prefix="/sql", tags=["SQL Data Catalog"])
data_router = APIRouter(prefix="/api/v1/data", tags=["SQL Data API"])


def _require_sql_enabled() -> None:
    """Hide SQL catalog and data routes while the feature is disabled."""
    if not settings.mcpgateway_sql_api_enabled:
        raise HTTPException(status_code=404, detail="SQL data API is disabled")


def _require_platform_admin(user: Any) -> None:
    """Restrict encrypted source configuration to platform administrators."""
    if not isinstance(user, dict) or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Platform administrator access required")


def _scoped_model(request: Request, user: Any, statement, model: Any, db: Session):
    """Apply the canonical Layer-1 visibility contract to one ORM model."""
    user_email, token_teams = get_scoped_resource_access_context(request, user)
    return BaseService._apply_visibility_scope(  # pylint: disable=protected-access
        statement,
        model,
        user_email,
        token_teams,
        token_teams or [],
        db,
    )


def _scoped_tables(request: Request, user: Any, statement, db: Session, model: Any = DbSQLTable):
    """Apply canonical token visibility semantics to SQL catalog reads."""
    return _scoped_model(request, user, statement, model, db)


def _scoped_tools(request: Request, user: Any, statement, db: Session, model: Any = DbTool):
    """Apply the same token visibility boundary before resolving a generated SQL tool."""
    return _scoped_model(request, user, statement, model, db)


def _ensure_table_manage_scope(request: Request, user: Any, db: Session, table_id: str, *, detail: str = "SQL table not found") -> DbSQLTable:
    """Resolve a mutation target through canonical Layer-1 visibility."""
    statement = _scoped_tables(request, user, select(DbSQLTable).where(DbSQLTable.id == table_id), db)
    table = db.execute(statement).scalar_one_or_none()
    if table is None:
        raise HTTPException(status_code=404, detail=detail)
    return table


def _translate_sql_error(exc: SQLDataError) -> HTTPException:
    """Map governed SQL service errors without exposing driver details."""
    if isinstance(exc, SQLDataNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, SQLDataForbiddenError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@admin_router.get("/sources", response_model=list[SQLDataSourceRead])
@require_permission("admin.sql_sources", allow_admin_bypass=False)
async def list_sources(db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """List credential-free SQL data source metadata."""
    _require_sql_enabled()
    _require_platform_admin(user)
    return list(db.execute(select(SQLDataSource).order_by(SQLDataSource.name)).scalars())


@admin_router.post("/sources", response_model=SQLDataSourceRead, status_code=201)
@require_permission("admin.sql_sources", allow_admin_bypass=False)
async def create_source(data: SQLDataSourceCreate, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Create an encrypted SQL data source."""
    _require_sql_enabled()
    _require_platform_admin(user)
    try:
        return SQLDataService.create_source(db, data, get_user_email(user))
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="SQL data source name already exists") from exc
    except SQLDataError as exc:
        raise _translate_sql_error(exc) from exc


@admin_router.put("/sources/{source_id}", response_model=SQLDataSourceRead)
@require_permission("admin.sql_sources", allow_admin_bypass=False)
async def update_source(source_id: str, data: SQLDataSourceUpdate, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Update connection configuration without returning credentials."""
    _require_sql_enabled()
    _require_platform_admin(user)
    try:
        table_ids = tuple(db.execute(select(DbSQLTable.id).where(DbSQLTable.source_id == source_id)).scalars())
        tool_references = SQLDataService.tool_cache_references(db, table_ids)
        source = SQLDataService.update_source(
            db,
            source_id,
            data,
            defer_result_cache_invalidation=True,
            defer_tool_cache_invalidation=True,
        )
        tool_references = tuple({*tool_references, *SQLDataService.tool_cache_references(db, table_ids)})
        await SQLDataService.invalidate_catalog_caches_async(table_ids, tool_references)
        return source
    except SQLDataError as exc:
        raise _translate_sql_error(exc) from exc


@admin_router.delete("/sources/{source_id}", status_code=204)
@require_permission("admin.sql_sources", allow_admin_bypass=False)
async def delete_source(source_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Delete a source while preserving detached tool history."""
    _require_sql_enabled()
    _require_platform_admin(user)
    try:
        table_ids = tuple(db.execute(select(DbSQLTable.id).where(DbSQLTable.source_id == source_id)).scalars())
        tool_references = SQLDataService.tool_cache_references(db, table_ids)
        SQLDataService.delete_source(
            db,
            source_id,
            defer_result_cache_invalidation=True,
            defer_tool_cache_invalidation=True,
        )
        await SQLDataService.invalidate_catalog_caches_async(table_ids, tool_references)
    except SQLDataError as exc:
        raise _translate_sql_error(exc) from exc


@admin_router.post("/sources/{source_id}/test")
@require_permission("admin.sql_sources", allow_admin_bypass=False)
async def test_source(source_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Test an external database connection."""
    _require_sql_enabled()
    _require_platform_admin(user)
    try:
        return SQLDataService.test_source(db, source_id)
    except SQLDataError as exc:
        raise _translate_sql_error(exc) from exc


@admin_router.post("/sources/{source_id}/discover", response_model=list[SQLTableRead])
@require_permission("admin.sql_sources", allow_admin_bypass=False)
async def discover_source(source_id: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Reflect a source and preserve stale catalog records."""
    _require_sql_enabled()
    _require_platform_admin(user)
    try:
        prior_table_ids = tuple(db.execute(select(DbSQLTable.id).where(DbSQLTable.source_id == source_id)).scalars())
        tool_references = SQLDataService.tool_cache_references(db, prior_table_ids)
        tables = SQLDataService.discover(
            db,
            source_id,
            defer_result_cache_invalidation=True,
            defer_tool_cache_invalidation=True,
        )
        table_ids = tuple(table.id for table in tables)
        tool_references = tuple({*tool_references, *SQLDataService.tool_cache_references(db, table_ids)})
        await SQLDataService.invalidate_catalog_caches_async(table_ids, tool_references)
        return tables
    except SQLDataError as exc:
        raise _translate_sql_error(exc) from exc


@admin_router.get("/tables", response_model=list[SQLTableRead])
@require_permission("sql.tables.read", allow_admin_bypass=False)
async def list_tables(request: Request, source_id: Optional[str] = None, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """List SQL tables visible through canonical token scoping."""
    _require_sql_enabled()
    statement = select(DbSQLTable).order_by(DbSQLTable.schema_name, DbSQLTable.table_name)
    if source_id:
        statement = statement.where(DbSQLTable.source_id == source_id)
    statement = _scoped_tables(request, user, statement, db)
    return list(db.execute(statement).scalars())


@admin_router.patch("/tables/{table_id}", response_model=SQLTableRead)
@require_permission("sql.tables.manage", allow_admin_bypass=False)
async def update_table(table_id: str, data: SQLTableUpdate, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Assign and expose a table operation-by-operation."""
    _require_sql_enabled()
    table = _ensure_table_manage_scope(request, user, db, table_id)
    _scoped_user_email, token_teams = get_scoped_resource_access_context(request, user)
    is_platform_admin = bool(isinstance(user, dict) and user.get("is_admin"))
    if "team_id" in data.model_fields_set and not is_platform_admin and data.team_id != table.team_id:
        raise HTTPException(status_code=403, detail="Only a platform administrator can reassign a SQL table")
    if data.team_id and token_teams is not None and data.team_id not in token_teams:
        raise HTTPException(status_code=403, detail="Cannot assign SQL table outside token scope")
    effective_team_id = data.team_id if "team_id" in data.model_fields_set else table.team_id
    effective_visibility = data.visibility if "visibility" in data.model_fields_set else table.visibility
    if effective_team_id:
        team = db.get(EmailTeam, effective_team_id)
        if team is None or not team.is_active:
            raise HTTPException(status_code=422, detail="Assigned team does not exist or is inactive")
    if effective_visibility == "team" and not effective_team_id:
        raise HTTPException(status_code=422, detail="Team-visible SQL tables require an assigned team")
    if data.visibility == "public" and not settings.allow_public_visibility:
        raise HTTPException(status_code=403, detail="Public visibility is disabled")
    try:
        tool_references = SQLDataService.tool_cache_references(db, (table_id,))
        table = SQLDataService.update_table(
            db,
            table_id,
            data,
            get_user_email(user),
            defer_result_cache_invalidation=True,
            defer_tool_cache_invalidation=True,
        )
        tool_references = tuple({*tool_references, *SQLDataService.tool_cache_references(db, (table.id,))})
        await SQLDataService.invalidate_catalog_caches_async((table.id,), tool_references)
        return table
    except SQLDataError as exc:
        raise _translate_sql_error(exc) from exc


@admin_router.get("/relations", response_model=list[SQLRelationRead])
@require_permission("sql.tables.read", allow_admin_bypass=False)
async def list_relations(request: Request, table_id: Optional[str] = None, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """List relations whose source and target tables are both visible."""
    _require_sql_enabled()
    source_alias = aliased(DbSQLTable, name="relation_source")
    target_alias = aliased(DbSQLTable, name="relation_target")
    statement = (
        select(SQLRelation)
        .join(source_alias, source_alias.id == SQLRelation.source_table_id)
        .join(target_alias, target_alias.id == SQLRelation.target_table_id)
        .order_by(SQLRelation.name)
    )
    statement = _scoped_tables(request, user, statement, db, source_alias)
    statement = _scoped_tables(request, user, statement, db, target_alias)
    if table_id:
        statement = statement.where(SQLRelation.source_table_id == table_id)
    return list(db.execute(statement).scalars())


@admin_router.patch("/relations/{relation_id}", response_model=SQLRelationRead)
@require_permission("sql.tables.manage", allow_admin_bypass=False)
async def update_relation(  # pylint: disable=unused-argument
    relation_id: str, data: SQLRelationUpdate, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)
):
    """Enable an explicitly managed one-hop include."""
    _require_sql_enabled()
    relation = db.get(SQLRelation, relation_id)
    if relation is None:
        raise HTTPException(status_code=404, detail="SQL relation not found")
    _ensure_table_manage_scope(request, user, db, relation.source_table_id, detail="SQL relation not found")
    _ensure_table_manage_scope(request, user, db, relation.target_table_id, detail="SQL relation not found")
    relation.enabled = data.enabled
    db.commit()
    await SQLDataService.invalidate_result_cache_tables_async((relation.source_table_id, relation.target_table_id))
    db.refresh(relation)
    return relation


@admin_router.get("/bindings", response_model=list[APISQLTableBindingReadDetail])
@require_permission("sql.tables.read", allow_admin_bypass=False)
async def list_bindings(
    request: Request,
    tool_id: Optional[str] = None,
    sql_table_id: Optional[str] = None,
    source_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """List API/table bindings with joined Tool and SQLTable context for visible tables."""
    _require_sql_enabled()
    tool_alias = aliased(DbTool, name="btool")
    table_alias = aliased(DbSQLTable, name="btable")
    source_alias = aliased(SQLDataSource, name="bsource")
    statement = (
        select(APISQLTableBinding, tool_alias, table_alias, source_alias)
        .join(tool_alias, tool_alias.id == APISQLTableBinding.tool_id)
        .join(table_alias, table_alias.id == APISQLTableBinding.sql_table_id)
        .join(source_alias, source_alias.id == table_alias.source_id)
    )
    statement = _scoped_tables(request, user, statement, db, table_alias)
    statement = _scoped_tools(request, user, statement, db, tool_alias)
    if tool_id:
        statement = statement.where(APISQLTableBinding.tool_id == tool_id)
    if sql_table_id:
        statement = statement.where(APISQLTableBinding.sql_table_id == sql_table_id)
    if source_id:
        statement = statement.where(source_alias.id == source_id)
    rows = db.execute(statement).mappings().all()
    return [
        APISQLTableBindingReadDetail(
            id=row[APISQLTableBinding].id,
            tool_id=row[APISQLTableBinding].tool_id,
            sql_table_id=row[APISQLTableBinding].sql_table_id,
            access_mode=row[APISQLTableBinding].access_mode,
            binding_type=row[APISQLTableBinding].binding_type,
            created_by=row[APISQLTableBinding].created_by,
            created_at=row[APISQLTableBinding].created_at,
            tool_name=row[tool_alias].display_name or row[tool_alias].original_name,
            tool_display_name=row[tool_alias].display_name,
            tool_integration_type=row[tool_alias].integration_type,
            tool_enabled=row[tool_alias].enabled,
            table_schema=row[table_alias].schema_name,
            table_name=row[table_alias].table_name,
            object_type=row[table_alias].object_type,
            table_exposed=row[table_alias].exposed,
            source_id=row[source_alias].id,
            source_name=row[source_alias].name,
        )
        for row in rows
    ]


@admin_router.post("/bindings", response_model=APISQLTableBindingRead, status_code=201)
@require_permission("sql.tables.manage", allow_admin_bypass=False)
async def create_binding(data: APISQLTableBindingCreate, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Create a manual impact binding without granting database access."""
    _require_sql_enabled()
    _ensure_table_manage_scope(request, user, db, data.sql_table_id)
    scoped_user_email, token_teams = get_scoped_resource_access_context(request, user)
    is_admin_bypass = bool(isinstance(user, dict) and user.get("is_admin") and token_teams is None)
    try:
        await tool_service.get_tool(
            db,
            data.tool_id,
            requesting_user_email=scoped_user_email,
            requesting_user_is_admin=is_admin_bypass,
            token_teams=token_teams,
        )
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Tool not found") from exc
    try:
        return SQLDataService.create_binding(db, data.tool_id, data.sql_table_id, data.access_mode, get_user_email(user))
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Binding already exists") from exc
    except SQLDataError as exc:
        raise _translate_sql_error(exc) from exc


@admin_router.delete("/bindings/{binding_id}", status_code=204)
@require_permission("sql.tables.manage", allow_admin_bypass=False)
async def delete_binding(binding_id: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):  # pylint: disable=unused-argument
    """Delete a manual binding; generated auto bindings are immutable."""
    _require_sql_enabled()
    binding = db.get(APISQLTableBinding, binding_id)
    if binding is None or binding.binding_type != "manual":
        raise HTTPException(status_code=404, detail="Manual binding not found")
    _ensure_table_manage_scope(request, user, db, binding.sql_table_id, detail="Manual binding not found")
    db.execute(delete(APISQLTableBinding).where(APISQLTableBinding.id == binding_id))
    db.commit()


def _parse_json_parameter(value: Optional[str], name: str) -> Any:
    """Decode a URL JSON parameter and return a stable validation error."""
    if value is None:
        return None
    try:
        return orjson.loads(value)
    except orjson.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be URL-encoded JSON") from exc


async def _invoke_data_tool(request: Request, db: Session, user: Any, source_slug: str, schema_slug: str, table_slug: str, operation: str, arguments: dict[str, Any]):
    """Resolve a scoped generated tool and invoke it through ToolService."""
    _require_sql_enabled()
    statement = (
        select(DbTool)
        .join(DbSQLTable, DbSQLTable.id == DbTool.sql_table_id)
        .join(SQLDataSource, SQLDataSource.id == DbSQLTable.source_id)
        .where(
            SQLDataSource.slug == source_slug,
            DbSQLTable.schema_slug == schema_slug,
            DbSQLTable.table_slug == table_slug,
            DbTool.source_operation == operation,
            DbTool.integration_type == "SQL",
            DbTool.enabled.is_(True),
        )
    )
    statement = _scoped_tools(request, user, statement, db)
    statement = _scoped_tables(request, user, statement, db)
    tool = db.execute(statement).scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=404, detail="SQL data endpoint not found")
    scoped_user_email, token_teams = get_scoped_resource_access_context(request, user)
    result = await tool_service.invoke_tool(
        db,
        tool.name,
        arguments,
        request_headers=dict(request.headers),
        app_user_email=get_user_email(user),
        user_email=scoped_user_email,
        token_teams=token_teams,
    )
    if result.is_error:
        message = result.content[0].text if result.content and hasattr(result.content[0], "text") else "SQL operation failed"
        raise HTTPException(status_code=422, detail=message)
    text = result.content[0].text if result.content and hasattr(result.content[0], "text") else "{}"
    try:
        return orjson.loads(text)
    except orjson.JSONDecodeError:
        return {"result": text}


@data_router.get("/{source_slug}/{schema_slug}/{table_slug}")
@require_permission("tools.execute", allow_admin_bypass=False)
async def query_data(
    source_slug: str,
    schema_slug: str,
    table_slug: str,
    request: Request,
    key: Optional[str] = None,
    filter_: Optional[str] = Query(None, alias="filter"),
    fields: Optional[str] = None,
    sort: Optional[str] = None,
    limit: Optional[int] = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    include: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
):
    """Query an exposed table with bounded equality filters and one-hop includes."""
    arguments = {
        "key": _parse_json_parameter(key, "key"),
        "filter": _parse_json_parameter(filter_, "filter"),
        "fields": fields.split(",") if fields else None,
        "sort": sort.split(",") if sort else None,
        "limit": limit,
        "offset": offset,
        "include": include.split(",") if include else None,
    }
    return await _invoke_data_tool(request, db, user, source_slug, schema_slug, table_slug, "query", {key: value for key, value in arguments.items() if value is not None})


@data_router.post("/{source_slug}/{schema_slug}/{table_slug}")
@require_permission("tools.execute", allow_admin_bypass=False)
async def insert_data(
    source_slug: str, schema_slug: str, table_slug: str, request: Request, values: dict[str, Any] = Body(..., embed=True), db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)
):
    """Insert exactly one row."""
    return await _invoke_data_tool(request, db, user, source_slug, schema_slug, table_slug, "insert", {"values": values})


@data_router.patch("/{source_slug}/{schema_slug}/{table_slug}")
@require_permission("tools.execute", allow_admin_bypass=False)
async def update_data(
    source_slug: str, schema_slug: str, table_slug: str, request: Request, key: str, values: dict[str, Any] = Body(..., embed=True), db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)
):
    """Update one row selected by a complete primary/unique key."""
    return await _invoke_data_tool(request, db, user, source_slug, schema_slug, table_slug, "update", {"key": _parse_json_parameter(key, "key"), "values": values})


@data_router.delete("/{source_slug}/{schema_slug}/{table_slug}")
@require_permission("tools.execute", allow_admin_bypass=False)
async def delete_data(source_slug: str, schema_slug: str, table_slug: str, request: Request, key: str, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions)):
    """Delete one row selected by a complete primary/unique key."""
    return await _invoke_data_tool(request, db, user, source_slug, schema_slug, table_slug, "delete", {"key": _parse_json_parameter(key, "key")})
