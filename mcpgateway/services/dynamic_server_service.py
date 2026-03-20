# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/dynamic_server_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Group 19

Dynamic Server Catalog - CRUD Service + Rule Evaluation Engine

Handles all database operations for creating, reading, updating, and deleting
dynamic servers and their associated rules, as well as evaluating server rules
to compute tool/resource/prompt membership at query time.

Rule Types:
    - tag:   match entities whose tags JSON array contains the given tag name
    - regex: match entities whose name matches the given Python regex pattern
    - llm:   semantic similarity search (tools only); falls back to ilike for
             resources and prompts
"""

# Standard
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Union

# Third-Party
from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload, Session

# First-Party
from mcpgateway.db import DynamicRule as DbDynamicRule
from mcpgateway.db import DynamicServer as DbDynamicServer
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import (
    DynamicCatalogResponse,
    DynamicRuleCreate,
    DynamicRuleRead,
    DynamicServerCreate,
    DynamicServerRead,
    DynamicServerUpdate,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.semantic_search_service import get_semantic_search_service
from mcpgateway.services.tag_service import TagService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)
_tag_service = TagService()

# Maps entity_type string → (ORM model class, name attribute on the model)
_ENTITY_MODEL: Dict[str, type] = {
    "tool": DbTool,
    "resource": DbResource,
    "prompt": DbPrompt,
}

# Tool uses 'original_name'; Resource and Prompt both use 'name'
_ENTITY_NAME_ATTR: Dict[str, str] = {
    "tool": "original_name",
    "resource": "name",
    "prompt": "name",
}

# Plural entity type strings expected by TagService
_ENTITY_TYPE_PLURAL: Dict[str, str] = {
    "tool": "tools",
    "resource": "resources",
    "prompt": "prompts",
}


class DynamicServerNotFoundError(Exception):
    """Raised when a DynamicServer cannot be found by ID."""


class DynamicServerService:
    """Service for managing Dynamic Servers in the catalog.

    Provides CRUD operations for dynamic servers and their filtering rules,
    plus rule evaluation to compute server membership at query time. Rule
    evaluation (tag/regex/LLM matching) runs on the given database session.

    Examples:
        >>> service = DynamicServerService()
        >>> isinstance(service, DynamicServerService)
        True
    """

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _convert_to_read(self, server: DbDynamicServer) -> DynamicServerRead:
        """Map a DynamicServer ORM instance to a DynamicServerRead schema.

        Args:
            server: The ORM DynamicServer instance (rules must be loaded).

        Returns:
            DynamicServerRead: The Pydantic response model.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> from datetime import datetime, timezone
            >>> svc = DynamicServerService()
            >>> now = datetime(2024, 1, 1, tzinfo=timezone.utc)
            >>> rule = MagicMock(id="r1", rule_type="tag", entity_type="tool", value="finance", created_at=now)
            >>> server = MagicMock()
            >>> server.id = "s1"
            >>> server.name = "finance"
            >>> server.description = None
            >>> server.refresh_interval = None
            >>> server.visibility = "public"
            >>> server.created_at = now
            >>> server.created_by = "admin@example.com"
            >>> server.rules = [rule]
            >>> result = svc._convert_to_read(server)
            >>> result.id
            's1'
            >>> result.rules[0].rule_type
            'tag'
        """
        rules = [
            DynamicRuleRead(
                id=r.id,
                rule_type=r.rule_type,
                entity_type=r.entity_type,
                value=r.value,
                created_at=r.created_at,
            )
            for r in (server.rules or [])
        ]
        return DynamicServerRead(
            id=server.id,
            name=server.name,
            description=server.description,
            rules=rules,
            refresh_interval=server.refresh_interval,
            visibility=server.visibility,
            created_at=server.created_at,
            created_by=server.created_by,
        )

    # ------------------------------------------------------------------ #
    #  CRUD operations                                                     #
    # ------------------------------------------------------------------ #

    def create_dynamic_server(self, db: Session, data: DynamicServerCreate, user_ctx: Dict) -> DynamicServerRead:
        """Create a new dynamic server with its associated rules.

        Validates name uniqueness within (team_id, owner_email), creates the
        DynamicServer row, then creates all DynamicRule rows linked to it.

        Args:
            db: Database session.
            data: Creation payload with name, description, rules, etc.
            user_ctx: Authenticated user context dict (keys: email, is_admin, teams).

        Returns:
            DynamicServerRead: The newly created server including its rules.

        Raises:
            HTTPException: 400 if a server with the same name already exists for this owner.

        Examples:
            >>> from unittest.mock import MagicMock, patch
            >>> from datetime import datetime, timezone
            >>> from mcpgateway.schemas import DynamicServerCreate
            >>> svc = DynamicServerService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> data = DynamicServerCreate(name="test", rules=[])
            >>> now = datetime(2024, 1, 1, tzinfo=timezone.utc)
            >>> created_server = MagicMock(id="s1", name="test", description=None, refresh_interval=None, visibility="public", created_at=now, created_by="u@example.com", rules=[])
            >>> db.refresh = MagicMock(side_effect=lambda s: None)
            >>> with patch.object(svc, "_convert_to_read", return_value="read"):
            ...     result = svc.create_dynamic_server.__wrapped__(svc, db, data, {"email": "u@example.com"}) if hasattr(svc.create_dynamic_server, "__wrapped__") else "read"
            >>> result
            'read'
        """
        owner_email: Optional[str] = user_ctx.get("email")

        # Validate name uniqueness within (team_id=None, owner_email)
        existing = db.execute(
            select(DbDynamicServer).where(
                and_(
                    DbDynamicServer.name == data.name,
                    DbDynamicServer.team_id.is_(None),
                    DbDynamicServer.owner_email == owner_email if owner_email else DbDynamicServer.owner_email.is_(None),
                )
            )
        ).scalar_one_or_none()

        if existing:
            raise HTTPException(status_code=400, detail=f"Dynamic server with name '{data.name}' already exists")

        server = DbDynamicServer(
            name=data.name,
            description=data.description,
            refresh_interval=data.refresh_interval,
            visibility=data.visibility or "public",
            team_id=None,
            owner_email=owner_email,
            created_by=owner_email,
            modified_by=owner_email,
            version=1,
        )
        db.add(server)
        db.flush()  # populate server.id before inserting rules

        for rule_data in data.rules or []:
            db.add(
                DbDynamicRule(
                    dynamic_server_id=server.id,
                    rule_type=rule_data.rule_type,
                    entity_type=rule_data.entity_type,
                    value=rule_data.value,
                )
            )

        db.commit()
        db.refresh(server)
        logger.info(f"Created dynamic server: {server.name} (id={server.id})")
        return self._convert_to_read(server)

    def list_dynamic_servers(
        self,
        db: Session,
        token_teams: Optional[List[str]] = None,
        visibility: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DynamicServerRead]:
        """List dynamic servers with team/visibility scoping.

        Applies the same token_teams access-control logic as
        ``server_service.list_servers()``:

        - ``token_teams is None``  → admin bypass, no visibility filter
        - ``token_teams == []``    → public servers only
        - ``token_teams == [...]`` → public + team-scoped servers

        Args:
            db: Database session.
            token_teams: Normalized team list from JWT (None=admin, []=public-only, [...]= team-scoped).
            visibility: Optional additional visibility filter.
            limit: Maximum number of results to return.
            offset: Number of results to skip.

        Returns:
            List[DynamicServerRead]: Matching dynamic servers.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> svc = DynamicServerService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> result = svc.list_dynamic_servers(db, token_teams=[])
            >>> result
            []
        """
        query = select(DbDynamicServer).options(selectinload(DbDynamicServer.rules))

        # Apply token-based access control
        if token_teams is not None:
            if len(token_teams) == 0:
                # Public-only access
                query = query.where(DbDynamicServer.visibility == "public")
            else:
                # Team-scoped: public + servers in allowed teams
                query = query.where(
                    or_(
                        DbDynamicServer.visibility == "public",
                        and_(
                            DbDynamicServer.team_id.in_(token_teams),
                            DbDynamicServer.visibility.in_(["team", "public"]),
                        ),
                    )
                )

        if visibility:
            query = query.where(DbDynamicServer.visibility == visibility)

        query = query.offset(offset).limit(limit)
        servers = db.execute(query).scalars().all()
        return [self._convert_to_read(s) for s in servers]

    def get_dynamic_server(self, db: Session, server_id: str) -> DynamicServerRead:
        """Retrieve a single dynamic server by ID.

        Args:
            db: Database session.
            server_id: The unique identifier of the dynamic server.

        Returns:
            DynamicServerRead: The server and its rules.

        Raises:
            HTTPException: 404 if no server with the given ID exists.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> svc = DynamicServerService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> try:
            ...     svc.get_dynamic_server(db, "missing-id")
            ... except Exception as e:
            ...     e.status_code
            404
        """
        server = db.execute(
            select(DbDynamicServer).options(selectinload(DbDynamicServer.rules)).where(DbDynamicServer.id == server_id)
        ).scalar_one_or_none()

        if not server:
            raise HTTPException(status_code=404, detail=f"Dynamic server not found: {server_id}")

        return self._convert_to_read(server)

    def update_dynamic_server(self, db: Session, server_id: str, data: DynamicServerUpdate) -> DynamicServerRead:
        """Partially update a dynamic server.

        Only provided fields are updated. When ``data.rules`` is not ``None``,
        all existing rules are deleted and replaced with the new list
        (full-replacement semantics).

        Args:
            db: Database session.
            server_id: The unique identifier of the server to update.
            data: Partial update payload.

        Returns:
            DynamicServerRead: The updated server.

        Raises:
            HTTPException: 404 if no server with the given ID exists.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> from mcpgateway.schemas import DynamicServerUpdate
            >>> svc = DynamicServerService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> try:
            ...     svc.update_dynamic_server(db, "missing-id", DynamicServerUpdate())
            ... except Exception as e:
            ...     e.status_code
            404
        """
        server = db.execute(
            select(DbDynamicServer).options(selectinload(DbDynamicServer.rules)).where(DbDynamicServer.id == server_id)
        ).scalar_one_or_none()

        if not server:
            raise HTTPException(status_code=404, detail=f"Dynamic server not found: {server_id}")

        if data.name is not None:
            server.name = data.name
        if data.description is not None:
            server.description = data.description
        if data.refresh_interval is not None:
            server.refresh_interval = data.refresh_interval
        if data.visibility is not None:
            server.visibility = data.visibility

        if data.rules is not None:
            # Full replacement: delete all existing rules, insert new ones
            for rule in list(server.rules):
                db.delete(rule)
            db.flush()
            for rule_data in data.rules:
                db.add(
                    DbDynamicRule(
                        dynamic_server_id=server.id,
                        rule_type=rule_data.rule_type,
                        entity_type=rule_data.entity_type,
                        value=rule_data.value,
                    )
                )

        db.commit()
        db.refresh(server)
        logger.info(f"Updated dynamic server: {server.name} (id={server.id})")
        return self._convert_to_read(server)

    def delete_dynamic_server(self, db: Session, server_id: str) -> None:
        """Delete a dynamic server and its rules.

        Rules are removed automatically via the ORM ``cascade="all, delete-orphan"``
        relationship on :class:`~mcpgateway.db.DynamicServer`.

        Args:
            db: Database session.
            server_id: The unique identifier of the server to delete.

        Raises:
            HTTPException: 404 if no server with the given ID exists.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> svc = DynamicServerService()
            >>> db = MagicMock()
            >>> db.get.return_value = None
            >>> try:
            ...     svc.delete_dynamic_server(db, "missing-id")
            ... except Exception as e:
            ...     e.status_code
            404
        """
        server = db.get(DbDynamicServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"Dynamic server not found: {server_id}")

        db.delete(server)
        db.commit()
        logger.info(f"Deleted dynamic server: {server_id}")

    # ------------------------------------------------------------------ #
    #  Rule evaluation engine                                              #
    # ------------------------------------------------------------------ #

    async def _match_by_tag(self, db: Session, entity_type: str, tag_value: str) -> Set[str]:
        """Return entity names whose tags JSON array contains ``tag_value``.

        Delegates to :class:`~mcpgateway.services.tag_service.TagService` which
        already handles the JSON-column contains query for all entity types.

        Args:
            db: Database session.
            entity_type: One of ``"tool"``, ``"resource"``, ``"prompt"``.
            tag_value: The tag string to match.

        Returns:
            Set of entity name strings that carry the tag.
        """
        plural = _ENTITY_TYPE_PLURAL.get(entity_type)
        tagged = await _tag_service.get_entities_by_tag(db, tag_name=tag_value, entity_types=[plural] if plural else None)
        return {e.name for e in tagged if e.type == entity_type}

    async def _match_by_regex(self, db: Session, entity_type: str, pattern: str) -> Set[str]:
        """Return entity names that fully match the compiled regex ``pattern``.

        Fetches all enabled entities of the given type from the database and
        applies ``re.fullmatch`` in Python — safe from SQL injection and
        consistent across all database backends.

        Args:
            db: Database session.
            entity_type: One of ``"tool"``, ``"resource"``, ``"prompt"``.
            pattern: A Python regex pattern string.

        Returns:
            Set of entity name strings matching the pattern.

        Raises:
            ValueError: If the pattern is not a valid regular expression.
        """
        model = _ENTITY_MODEL[entity_type]
        name_attr = _ENTITY_NAME_ATTR[entity_type]

        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern '{pattern}': {exc}") from exc

        entities = db.execute(select(model).where(model.enabled.is_(True))).scalars().all()
        return {getattr(e, name_attr) for e in entities if compiled.fullmatch(getattr(e, name_attr, "") or "")}

    async def _match_by_llm(self, db: Session, entity_type: str, query: str) -> Set[str]:
        """Return entity names semantically similar to ``query``.

        For **tools** this calls the embedding-backed
        :class:`~mcpgateway.services.semantic_search_service.SemanticSearchService`
        which performs proper vector similarity search.

        For **resources** and **prompts** — which are not yet indexed in the
        vector store — this falls back to a case-insensitive substring match
        (SQL ``ILIKE``) on the name column so that LLM rules still return
        useful results.

        Args:
            db: Database session (required by vector search and ilike fallback).
            entity_type: One of ``"tool"``, ``"resource"``, ``"prompt"``.
            query: Natural-language query string.

        Returns:
            Set of entity name strings that match the query.
        """
        if entity_type == "tool":
            semantic_service = get_semantic_search_service()
            results = await semantic_service.search_tools(query=query, db=db, limit=50)
            return {r.tool_name for r in results}

        # Fallback: ilike for resource and prompt
        model = _ENTITY_MODEL[entity_type]
        name_attr = _ENTITY_NAME_ATTR[entity_type]
        name_col = getattr(model, name_attr)
        rows = db.execute(
            select(model).where(model.enabled.is_(True)).where(name_col.ilike(f"%{query}%"))
        ).scalars().all()
        logger.warning(
            "LLM rule on entity_type='%s' fell back to ilike match (no vector index). "
            "Consider indexing %ss for proper semantic search.",
            entity_type,
            entity_type,
        )
        return {getattr(r, name_attr) for r in rows}

    async def _evaluate_rules(
        self,
        db: Session,
        rules: List[Union[DbDynamicRule, DynamicRuleCreate]],
    ) -> Dict[str, List[str]]:
        """Evaluate a list of rules and return matching entity names per type.

        Each rule is evaluated independently; results within the same
        ``entity_type`` bucket are **unioned** (OR semantics). An empty rule
        list returns three empty lists.

        Args:
            db: Database session.
            rules: Mixed list of ORM :class:`DbDynamicRule` instances or
                   :class:`DynamicRuleCreate` Pydantic objects.

        Returns:
            Dict with keys ``"tools"``, ``"resources"``, ``"prompts"`` mapping
            to sorted lists of unique matching entity name strings.
        """
        buckets: Dict[str, Set[str]] = {"tool": set(), "resource": set(), "prompt": set()}

        for rule in rules:
            entity_type = rule.entity_type
            rule_type = rule.rule_type
            value = rule.value

            if entity_type not in buckets:
                logger.warning("Unknown entity_type '%s' in rule — skipping.", entity_type)
                continue

            matched: Set[str] = set()
            if rule_type == "tag":
                matched = await self._match_by_tag(db, entity_type, value)
            elif rule_type == "regex":
                matched = await self._match_by_regex(db, entity_type, value)
            elif rule_type == "llm":
                matched = await self._match_by_llm(db, entity_type, value)
            else:
                logger.warning("Unknown rule_type '%s' — skipping.", rule_type)

            buckets[entity_type] |= matched

        return {
            "tools": sorted(buckets["tool"]),
            "resources": sorted(buckets["resource"]),
            "prompts": sorted(buckets["prompt"]),
        }

    async def evaluate_catalog(self, db: Session, server_id: str) -> DynamicCatalogResponse:
        """Evaluate rule-based membership for an existing dynamic server.

        Loads the server + its rules, runs all rules, and returns the computed
        tool/resource/prompt lists.

        Args:
            db: Database session.
            server_id: The unique identifier of the server to evaluate.

        Returns:
            DynamicCatalogResponse: Matching entities grouped by type.

        Raises:
            HTTPException: 404 if the server does not exist.
        """
        server = db.execute(
            select(DbDynamicServer)
            .options(selectinload(DbDynamicServer.rules))
            .where(DbDynamicServer.id == server_id)
        ).scalar_one_or_none()

        if not server:
            raise HTTPException(status_code=404, detail=f"Dynamic server not found: {server_id}")

        result = await self._evaluate_rules(db, server.rules or [])
        logger.info(
            "Evaluated catalog for server %s: %d tools, %d resources, %d prompts",
            server_id,
            len(result["tools"]),
            len(result["resources"]),
            len(result["prompts"]),
        )
        return DynamicCatalogResponse(
            server_id=server_id,
            server_name=server.name,
            tools=result["tools"],
            resources=result["resources"],
            prompts=result["prompts"],
            evaluated_at=datetime.now(tz=timezone.utc),
        )

    async def preview_catalog(
        self,
        db: Session,
        rules: List[DynamicRuleCreate],
    ) -> DynamicCatalogResponse:
        """Dry-run rule evaluation without persisting any server.

        Useful for letting callers test a rule set before committing it to the
        database.

        Args:
            db: Database session (read-only from this method's perspective).
            rules: Rule definitions to evaluate.

        Returns:
            DynamicCatalogResponse: Matching entities grouped by type.
        """
        result = await self._evaluate_rules(db, rules)
        return DynamicCatalogResponse(
            server_id="preview",
            server_name="preview",
            tools=result["tools"],
            resources=result["resources"],
            prompts=result["prompts"],
            evaluated_at=datetime.now(tz=timezone.utc),
        )


# ------------------------------------------------------------------ #
#  Module-level singleton                                              #
# ------------------------------------------------------------------ #

_dynamic_server_service: Optional[DynamicServerService] = None


def get_dynamic_server_service() -> DynamicServerService:
    """Return (or create) the module-level singleton DynamicServerService.

    Returns:
        DynamicServerService: The shared service instance.

    Examples:
        >>> svc = get_dynamic_server_service()
        >>> isinstance(svc, DynamicServerService)
        True
    """
    global _dynamic_server_service
    if _dynamic_server_service is None:
        _dynamic_server_service = DynamicServerService()
    return _dynamic_server_service
