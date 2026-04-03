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

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import ToolPluginBinding, utc_now
from mcpgateway.schemas import ToolPluginBindingRequest, ToolPluginBindingResponse

logger = logging.getLogger(__name__)


class ToolPluginBindingNotFoundError(Exception):
    """Raised when a binding with the given ID does not exist."""


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

        for team_id, team_policies in request.teams.items():
            for policy in team_policies.policies:
                for tool_name in policy.tool_names:
                    existing = (
                        db.query(ToolPluginBinding)
                        .filter(
                            ToolPluginBinding.team_id == team_id,
                            ToolPluginBinding.tool_name == tool_name,
                            ToolPluginBinding.plugin_id == policy.plugin_id.value,
                        )
                        .first()
                    )

                    if existing:
                        # Upsert — update mutable fields only
                        existing.mode = policy.mode.value
                        existing.priority = policy.priority
                        existing.config = policy.config
                        existing.updated_at = now
                        existing.updated_by = caller_email
                        db.flush()
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
                        db.flush()
                        results.append(self._to_response(new_binding))
                        logger.debug(
                            "Created tool plugin binding id=%s team=%s tool=%s plugin=%s",
                            new_binding.id,
                            team_id,
                            tool_name,
                            policy.plugin_id.value,
                        )

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
        db.flush()
        logger.debug("Deleted tool plugin binding id=%s", binding_id)
        return response
