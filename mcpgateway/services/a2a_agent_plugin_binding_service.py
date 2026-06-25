# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/a2a_agent_plugin_binding_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

A2A Agent Plugin Binding Service.
Handles upsert, retrieval, and deletion of per-agent per-tenant plugin policy bindings.
"""

# Standard
import logging
from typing import Dict, List, Optional
import uuid

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgentPluginBinding, utc_now
from mcpgateway.schemas import A2AAgentPluginBindingResponse

logger = logging.getLogger(__name__)


class A2AAgentPluginBindingNotFoundError(Exception):
    """Raised when a binding with the given ID does not exist."""


class A2AAgentPluginBindingForbiddenError(Exception):
    """Raised when the caller is not authorized to modify a binding from another team."""


def get_bindings_for_agent(
    db: Session,
    team_id: str,
    agent_name: str,
) -> List[A2AAgentPluginBinding]:
    """Return deduplicated plugin bindings for a (team_id, agent_name) pair.

    Includes wildcard ``"*"`` bindings alongside exact-match bindings.
    For duplicate plugin_ids, an exact ``agent_name`` binding always takes
    precedence over a ``"*"`` wildcard binding, regardless of insertion or
    update order (specificity-wins semantics).

    Args:
        db: SQLAlchemy session.
        team_id: Team whose bindings to query.
        agent_name: Exact agent name, or ``"*"`` to fetch only wildcard rows.

    Returns:
        List of ORM ``A2AAgentPluginBinding`` instances, one per unique plugin_id.
    """
    rows = (
        db.query(A2AAgentPluginBinding)
        .filter(
            A2AAgentPluginBinding.team_id == team_id,
            A2AAgentPluginBinding.agent_name.in_([agent_name, "*"]),
        )
        .all()
    )
    wildcard: Dict[str, A2AAgentPluginBinding] = {}
    specific: Dict[str, A2AAgentPluginBinding] = {}
    for binding in rows:
        if binding.agent_name == "*":
            wildcard[binding.plugin_id] = binding
        else:
            specific[binding.plugin_id] = binding
    return list({**wildcard, **specific}.values())


class A2AAgentPluginBindingService:
    """Service for managing A2A agent plugin bindings.

    All write operations follow an upsert pattern keyed on
    (team_id, agent_name, plugin_id) — a re-POST for an existing triple
    updates the existing row without changing its ``id`` or ``created_*`` fields.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_response(binding: A2AAgentPluginBinding) -> A2AAgentPluginBindingResponse:
        """Convert an ORM row to a response schema.

        Args:
            binding: ORM instance to convert.

        Returns:
            A2AAgentPluginBindingResponse: Pydantic response model.
        """
        return A2AAgentPluginBindingResponse(
            id=binding.id,
            team_id=binding.team_id,
            agent_name=binding.agent_name,
            plugin_id=binding.plugin_id,
            mode=binding.mode,
            priority=binding.priority,
            config=binding.config,
            on_error=binding.on_error,
            binding_reference_id=binding.binding_reference_id,
            created_at=binding.created_at,
            created_by=binding.created_by,
            updated_at=binding.updated_at,
            updated_by=binding.updated_by,
        )

    # ------------------------------------------------------------------
    # Write — upsert
    # ------------------------------------------------------------------

    def upsert_binding(
        self,
        db: Session,
        team_id: str,
        agent_name: str,
        plugin_id: str,
        mode: str,
        priority: int,
        config: dict,
        on_error: Optional[str],
        caller_email: str,
        binding_reference_id: Optional[str] = None,
    ) -> A2AAgentPluginBindingResponse:
        """Create or update a plugin binding for an A2A agent.

        Operates on a single (team_id, agent_name, plugin_id) triple:
        - If a row already exists the mutable fields are updated in place.
        - If no row exists a new row is inserted.

        Args:
            db: SQLAlchemy session.
            team_id: Team owning the binding.
            agent_name: Agent name the policy applies to; ``"*"`` means all team agents.
            plugin_id: Plugin identifier.
            mode: Execution mode string (e.g. ``"enforce"``, ``"permissive"``, etc.).
            priority: Execution order — lower numbers run first.
            config: Plugin-specific configuration (fully replaced on update).
            on_error: Error handling policy (``"fail"``, ``"ignore"``, ``"disable"``, or ``None``).
            caller_email: Email of the authenticated user.
            binding_reference_id: Optional external reference ID.

        Returns:
            A2AAgentPluginBindingResponse: The created or updated binding.
        """
        now = utc_now()
        existing = (
            db.query(A2AAgentPluginBinding)
            .filter(
                A2AAgentPluginBinding.team_id == team_id,
                A2AAgentPluginBinding.agent_name == agent_name,
                A2AAgentPluginBinding.plugin_id == plugin_id,
            )
            .first()
        )

        if existing:
            # Warn if binding_reference_id ownership is changing
            if existing.binding_reference_id and binding_reference_id and existing.binding_reference_id != binding_reference_id:
                logger.warning(
                    "binding_reference_id ownership transfer: team=%s agent=%s plugin=%s old_ref=%s new_ref=%s",
                    team_id,
                    agent_name,
                    plugin_id,
                    existing.binding_reference_id,
                    binding_reference_id,
                )
            existing.mode = mode
            existing.priority = priority
            existing.config = config
            existing.on_error = on_error
            existing.binding_reference_id = binding_reference_id
            existing.updated_at = now
            existing.updated_by = caller_email
            logger.debug(
                "Updated A2A agent plugin binding id=%s team=%s agent=%s plugin=%s",
                existing.id,
                team_id,
                agent_name,
                plugin_id,
            )
        else:
            existing = A2AAgentPluginBinding(
                id=uuid.uuid4().hex,
                team_id=team_id,
                agent_name=agent_name,
                plugin_id=plugin_id,
                mode=mode,
                priority=priority,
                config=config,
                on_error=on_error,
                binding_reference_id=binding_reference_id,
                created_at=now,
                created_by=caller_email,
                updated_at=now,
                updated_by=caller_email,
            )
            db.add(existing)
            logger.debug(
                "Created A2A agent plugin binding id=%s team=%s agent=%s plugin=%s",
                existing.id,
                team_id,
                agent_name,
                plugin_id,
            )

        db.flush()
        return self._to_response(existing)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_bindings(
        self,
        db: Session,
        team_id: Optional[str] = None,
        binding_reference_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        allowed_teams: Optional[set[str]] = None,
    ) -> tuple[List[A2AAgentPluginBindingResponse], int]:
        """Return all bindings, optionally filtered by team or binding_reference_id.

        When ``binding_reference_id`` is provided it takes precedence and
        ``team_id`` is ignored — a reference ID is globally unique so scoping
        by team is redundant and would produce confusing results.

        Args:
            db: SQLAlchemy session.
            team_id: If provided (and ``binding_reference_id`` is not), return
                only bindings for this team.
            binding_reference_id: If provided, return only bindings with this
                reference ID (``team_id`` is ignored).
            limit: Maximum number of results to return (None = no limit).
            offset: Number of results to skip.
            allowed_teams: When non-None, only bindings whose ``team_id`` is in
                this set are returned. Pass ``None`` for admin callers (unrestricted).
                This enforces multi-tenant isolation at the data layer.

        Returns:
            Tuple of (List[A2AAgentPluginBindingResponse], total_count).
        """
        query = db.query(A2AAgentPluginBinding)

        # Filter by allowed_teams first (multi-tenant isolation)
        if allowed_teams is not None:
            query = query.filter(A2AAgentPluginBinding.team_id.in_(allowed_teams))

        if binding_reference_id:
            query = query.filter(A2AAgentPluginBinding.binding_reference_id == binding_reference_id)
        elif team_id:
            query = query.filter(A2AAgentPluginBinding.team_id == team_id)
        total = query.count()
        # TODO: For tables with >10K bindings, consider:  # pylint: disable=fixme
        # 1. Caching total count with Redis + TTL
        # 2. Approximate count from pg_stats
        # 3. Cursor-based pagination (no total count needed)
        query = query.order_by(A2AAgentPluginBinding.team_id, A2AAgentPluginBinding.priority)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        bindings = query.all()
        return [self._to_response(b) for b in bindings], total

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_binding(
        self,
        db: Session,
        binding_id: str,
        allowed_teams: Optional[set[str]] = None,
    ) -> A2AAgentPluginBindingResponse:
        """Delete a binding by its primary key and return its details.

        The response is captured before the row is removed so the caller
        receives the full record that was deleted.

        Args:
            db: SQLAlchemy session.
            binding_id: UUID of the binding to delete.
            allowed_teams: When non-None, the binding's ``team_id`` must be in
                this set or ``A2AAgentPluginBindingForbiddenError`` is raised.
                Pass ``None`` for admin callers (unrestricted).

        Returns:
            A2AAgentPluginBindingResponse: Details of the deleted binding.

        Raises:
            A2AAgentPluginBindingNotFoundError: If no binding with the given ID exists.
            A2AAgentPluginBindingForbiddenError: If ``allowed_teams`` is set and the
                binding belongs to a team the caller is not a member of.
        """
        binding = db.query(A2AAgentPluginBinding).filter(A2AAgentPluginBinding.id == binding_id).first()
        if not binding:
            raise A2AAgentPluginBindingNotFoundError(f"A2A agent plugin binding '{binding_id}' not found")
        if allowed_teams is not None and binding.team_id not in allowed_teams:
            raise A2AAgentPluginBindingForbiddenError(f"Not authorized to delete binding '{binding_id}' for team '{binding.team_id}'")
        response = self._to_response(binding)
        db.delete(binding)
        db.flush()
        logger.debug("Deleted A2A agent plugin binding id=%s", binding_id)
        return response

    def delete_bindings_by_reference(
        self,
        db: Session,
        binding_reference_id: str,
        allowed_teams: Optional[set[str]] = None,
    ) -> List[A2AAgentPluginBindingResponse]:
        """Delete all bindings tagged with a given external reference ID.

        Intended for use by external systems that need to
        remove all bindings associated with one of their own reference objects
        without knowing the internal ContextForge UUIDs.

        Args:
            db: SQLAlchemy session.
            binding_reference_id: The external reference ID to match.
            allowed_teams: When non-None, only bindings whose ``team_id`` is in
                this set are deleted.  Bindings for other teams are silently
                skipped.
                Pass ``None`` for admin callers (unrestricted).

        Returns:
            List[A2AAgentPluginBindingResponse]: All deleted binding records.
                Returns an empty list (not an error) if no bindings matched.
        """
        query = db.query(A2AAgentPluginBinding).filter(A2AAgentPluginBinding.binding_reference_id == binding_reference_id)
        if allowed_teams is not None:
            query = query.filter(A2AAgentPluginBinding.team_id.in_(allowed_teams))
        rows = query.all()
        responses = [self._to_response(r) for r in rows]
        for row in rows:
            logger.debug("Deleted A2A agent plugin binding id=%s ref=%s", row.id, binding_reference_id)
            db.delete(row)
        db.flush()
        return responses
