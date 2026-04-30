# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/tool_plugin_binding_service.py
Copyright 2026
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
    For duplicate plugin_ids, an exact ``tool_name`` binding always takes
    precedence over a ``"*"`` wildcard binding, regardless of insertion or
    update order (specificity-wins semantics).

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
        .all()
    )
    # Specificity-wins: wildcard ("*") is the fallback; an exact tool_name
    # binding always overrides the wildcard for the same plugin_id, regardless
    # of insertion/update order.
    wildcard: dict[str, ToolPluginBinding] = {}
    specific: dict[str, ToolPluginBinding] = {}
    for binding in rows:
        if binding.tool_name == "*":
            wildcard[binding.plugin_id] = binding
        else:
            specific[binding.plugin_id] = binding
    # Merge: start with wildcards, let specific bindings overwrite
    return list({**wildcard, **specific}.values())


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
            binding_reference_id=binding.binding_reference_id,
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

        **Stale tool pruning**: when a policy carries a ``binding_reference_id``,
        any existing binding that shares the same ``binding_reference_id`` and
        ``plugin_id`` but whose ``tool_name`` is *not* in the incoming
        ``tool_names`` list is deleted.  This keeps the stored state in sync
        when an external system sends a full replacement list of
        tools on an update event.

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

        # Track which (binding_reference_id, plugin_id) pairs appear in this
        # request and which tool_names are authoritative for each pair so we
        # can prune stale rows after the upsert loop.
        # Structure: {(binding_reference_id, plugin_id_value): set_of_incoming_tool_names}
        ref_plugin_tool_names: dict = {}

        for team_id, team_policies in request.teams.items():
            for policy in team_policies.policies:
                # Build the authoritative tool-name set for stale pruning.
                if policy.binding_reference_id:
                    key = (policy.binding_reference_id, policy.plugin_id)
                    ref_plugin_tool_names.setdefault(key, set()).update(policy.tool_names)

                for tool_name in policy.tool_names:
                    existing = existing_map.get((team_id, tool_name, policy.plugin_id))

                    if existing:
                        # Warn if binding_reference_id ownership is changing — this means two
                        # different external references are claiming the same (team, tool, plugin)
                        # triple.  The new reference_id wins (last-caller-wins), but the old
                        # caller's DELETE by reference will now be a no-op.
                        if existing.binding_reference_id and policy.binding_reference_id and existing.binding_reference_id != policy.binding_reference_id:
                            logger.warning(
                                "binding_reference_id ownership transfer: team=%s tool=%s plugin=%s old_ref=%s new_ref=%s — DELETE by old_ref will now be a no-op",
                                team_id,
                                tool_name,
                                policy.plugin_id,
                                existing.binding_reference_id,
                                policy.binding_reference_id,
                            )
                        # Upsert — update mutable fields only
                        existing.mode = policy.mode.value
                        existing.priority = policy.priority
                        existing.config = policy.config
                        existing.binding_reference_id = policy.binding_reference_id
                        existing.updated_at = now
                        existing.updated_by = caller_email
                        results.append(self._to_response(existing))
                        logger.debug(
                            "Updated tool plugin binding id=%s team=%s tool=%s plugin=%s",
                            existing.id,
                            team_id,
                            tool_name,
                            policy.plugin_id,
                        )
                    else:
                        new_binding = ToolPluginBinding(
                            id=uuid.uuid4().hex,
                            team_id=team_id,
                            tool_name=tool_name,
                            plugin_id=policy.plugin_id,
                            mode=policy.mode.value,
                            priority=policy.priority,
                            config=policy.config,
                            binding_reference_id=policy.binding_reference_id,
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
                            policy.plugin_id,
                        )

        # Prune stale tool bindings for any (binding_reference_id, plugin_id)
        # pair present in this request — rows whose tool_name is no longer in
        # the authoritative incoming list are deleted.
        for (ref_id, plugin_id_val), incoming_tools in ref_plugin_tool_names.items():
            stale_rows = (
                db.query(ToolPluginBinding)
                .filter(
                    ToolPluginBinding.binding_reference_id == ref_id,
                    ToolPluginBinding.plugin_id == plugin_id_val,
                    ToolPluginBinding.tool_name.notin_(incoming_tools),
                )
                .all()
            )
            for stale in stale_rows:
                logger.debug(
                    "Pruning stale tool binding id=%s ref=%s tool=%s plugin=%s",
                    stale.id,
                    ref_id,
                    stale.tool_name,
                    plugin_id_val,
                )
                db.delete(stale)

        db.flush()  # single flush for all inserts/updates/deletes
        return results

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_bindings(
        self,
        db: Session,
        team_id: Optional[str] = None,
        binding_reference_id: Optional[str] = None,
    ) -> List[ToolPluginBindingResponse]:
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

        Returns:
            List[ToolPluginBindingResponse]: Matching bindings.
        """
        query = db.query(ToolPluginBinding)
        if binding_reference_id:
            if team_id:
                logger.warning(
                    "Both team_id=%r and binding_reference_id=%r supplied to list_bindings; team_id will be ignored. Omit team_id when filtering by binding_reference_id.",
                    team_id,
                    binding_reference_id,
                )
            query = query.filter(ToolPluginBinding.binding_reference_id == binding_reference_id)
        elif team_id:
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

    def delete_bindings_by_reference(
        self,
        db: Session,
        binding_reference_id: str,
    ) -> List[ToolPluginBindingResponse]:
        """Delete all bindings tagged with a given external reference ID.

        Intended for use by external systems that need to
        remove all bindings associated with one of their own reference objects
        without knowing the internal ContextForge UUIDs.

        Args:
            db: SQLAlchemy session.
            binding_reference_id: The external reference ID to match.

        Returns:
            List[ToolPluginBindingResponse]: All deleted binding records.
                Returns an empty list (not an error) if no bindings matched.
        """
        rows = db.query(ToolPluginBinding).filter(ToolPluginBinding.binding_reference_id == binding_reference_id).all()
        responses = [self._to_response(r) for r in rows]
        for row in rows:
            logger.debug("Deleted tool plugin binding id=%s ref=%s", row.id, binding_reference_id)
            db.delete(row)
        db.flush()
        return responses
