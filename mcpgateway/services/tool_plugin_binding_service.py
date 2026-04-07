# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/tool_plugin_binding_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

Tool Plugin Binding Service.
Handles upsert, retrieval, and deletion of per-tool per-tenant plugin policy bindings.
"""

# Standard
import logging
from typing import List, Optional
import uuid

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import ToolPluginBinding, utc_now
from mcpgateway.schemas import ToolPluginBindingRequest, ToolPluginBindingResponse

logger = logging.getLogger(__name__)


class ToolPluginBindingNotFoundError(Exception):
    """Raised when a binding with the given ID does not exist."""


def get_bindings_for_tool(
    db: Session,
    team_id: str,
    tool_name: str,
) -> List[ToolPluginBinding]:
    """Return deduplicated plugin bindings for a (team_id, tool_name) pair.

    Includes wildcard ``"*"`` bindings alongside exact-match bindings.
    For duplicate plugin_ids, the most recently updated binding wins
    (last-write-wins) so a specific tool_name entry overrides a ``"*"`` entry
    when both exist for the same plugin.

    Args:
        db: SQLAlchemy session.
        team_id: Team whose bindings to query.
        tool_name: Exact tool name, or ``"*"`` to fetch only wildcard rows.

    Returns:
        List of ORM ``ToolPluginBinding`` instances, one per unique plugin_id.
    """
    rows = (
        db.query(ToolPluginBinding)
        .filter(
            ToolPluginBinding.team_id == team_id,
            ToolPluginBinding.tool_name.in_([tool_name, "*"]),
        )
        .order_by(ToolPluginBinding.updated_at.asc())
        .all()
    )
    # Last-write-wins: iterate ascending updated_at so exact matches (later)
    # overwrite wildcard matches (earlier) for the same plugin_id.
    seen: dict[str, ToolPluginBinding] = {}
    for binding in rows:
        seen[binding.plugin_id] = binding
    return list(seen.values())


class ToolPluginBindingService:
    """Service for managing tool plugin bindings.

    All write operations follow an upsert pattern keyed on
    (team_id, tool_name, plugin_id) — a re-POST for an existing triple
    updates the existing row without changing its ``id`` or ``created_*`` fields.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_response(binding: ToolPluginBinding) -> ToolPluginBindingResponse:
        """Convert an ORM row to a response schema.

        Args:
            binding: ORM instance to convert.

        Returns:
            ToolPluginBindingResponse: Pydantic response model.
        """
        return ToolPluginBindingResponse(
            id=binding.id,
            team_id=binding.team_id,
            tool_name=binding.tool_name,
            plugin_id=binding.plugin_id,
            mode=binding.mode,
            priority=binding.priority,
            config=binding.config,
            created_at=binding.created_at,
            created_by=binding.created_by,
            updated_at=binding.updated_at,
            updated_by=binding.updated_by,
        )

    # ------------------------------------------------------------------
    # Write — upsert
    # ------------------------------------------------------------------

    def upsert_bindings(
        self,
        db: Session,
        request: ToolPluginBindingRequest,
        caller_email: str,
    ) -> List[ToolPluginBindingResponse]:
        """Create or update plugin bindings from a POST request payload.

        Iterates over every (team_id, policy) combination in the request.
        For each (team_id, tool_name, plugin_id) triple:
        - If a row already exists → update mode/priority/config/updated_by/updated_at.
        - If no row exists → insert a new row.

        **Config replacement policy**: ``config`` is always fully replaced on
        update — it is NOT merged with the stored value.  To preserve existing
        keys the caller must include them in the new request payload.

        Args:
            db: SQLAlchemy session.
            request: Validated request payload.
            caller_email: Email of the authenticated user making the request.
                Must be a non-empty string — sourced from the auth middleware.

        Returns:
            List[ToolPluginBindingResponse]: All created/updated bindings, flattened.
        """
        results: List[ToolPluginBindingResponse] = []
        now = utc_now()

        # Prefetch all existing bindings for the requested teams in a single query
        # rather than issuing one SELECT per (team_id, tool_name, plugin_id) triple.
        team_ids = list(request.teams.keys())
        existing_rows = db.query(ToolPluginBinding).filter(ToolPluginBinding.team_id.in_(team_ids)).all()
        existing_map: dict = {(b.team_id, b.tool_name, b.plugin_id): b for b in existing_rows}

        for team_id, team_policies in request.teams.items():
            for policy in team_policies.policies:
                for tool_name in policy.tool_names:
                    existing = existing_map.get((team_id, tool_name, policy.plugin_id.value))

                    if existing:
                        # Upsert — update mutable fields only
                        existing.mode = policy.mode.value
                        existing.priority = policy.priority
                        existing.config = policy.config
                        existing.updated_at = now
                        existing.updated_by = caller_email
                        results.append(self._to_response(existing))
                        logger.debug(
                            "Updated tool plugin binding id=%s team=%s tool=%s plugin=%s",
                            existing.id,
                            team_id,
                            tool_name,
                            policy.plugin_id.value,
                        )
                    else:
                        new_binding = ToolPluginBinding(
                            id=uuid.uuid4().hex,
                            team_id=team_id,
                            tool_name=tool_name,
                            plugin_id=policy.plugin_id.value,
                            mode=policy.mode.value,
                            priority=policy.priority,
                            config=policy.config,
                            created_at=now,
                            created_by=caller_email,
                            updated_at=now,
                            updated_by=caller_email,
                        )
                        db.add(new_binding)
                        results.append(self._to_response(new_binding))
                        logger.debug(
                            "Created tool plugin binding id=%s team=%s tool=%s plugin=%s",
                            new_binding.id,
                            team_id,
                            tool_name,
                            policy.plugin_id.value,
                        )

        db.flush()  # single flush for all inserts/updates
        return results

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_bindings(
        self,
        db: Session,
        team_id: Optional[str] = None,
    ) -> List[ToolPluginBindingResponse]:
        """Return all bindings, optionally filtered by team.

        Args:
            db: SQLAlchemy session.
            team_id: If provided, return only bindings for this team.

        Returns:
            List[ToolPluginBindingResponse]: Matching bindings.
        """
        query = db.query(ToolPluginBinding)
        if team_id:
            query = query.filter(ToolPluginBinding.team_id == team_id)
        bindings = query.order_by(ToolPluginBinding.team_id, ToolPluginBinding.priority).all()
        return [self._to_response(b) for b in bindings]

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_binding(self, db: Session, binding_id: str) -> ToolPluginBindingResponse:
        """Delete a binding by its primary key and return its details.

        The response is captured before the row is removed so the caller
        receives the full record that was deleted.

        Args:
            db: SQLAlchemy session.
            binding_id: UUID of the binding to delete.

        Returns:
            ToolPluginBindingResponse: Details of the deleted binding.

        Raises:
            ToolPluginBindingNotFoundError: If no binding with the given ID exists.
        """
        binding = db.query(ToolPluginBinding).filter(ToolPluginBinding.id == binding_id).first()
        if not binding:
            raise ToolPluginBindingNotFoundError(f"Tool plugin binding '{binding_id}' not found")
        response = self._to_response(binding)
        db.delete(binding)
        db.flush()  # flush so the DELETE is sent before the caller's commit
        logger.debug("Deleted tool plugin binding id=%s", binding_id)
        return response
