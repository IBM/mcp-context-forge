# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/dataplane_publisher/models.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Data models and visibility indexing structures for dataplane publishing.
"""

# Standard
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict


class BackendItems(TypedDict):
    """Database identifiers associated with one server backend."""

    tools: list[str]
    resources: list[str]
    prompts: list[str]


BackendItemsByServer = dict[str, dict[str, BackendItems]]


@dataclass(frozen=True)
class UserScope:
    """User identity and memberships used to select visible routing data."""

    id: str
    email: str
    is_admin: bool
    team_ids: frozenset[str]


@dataclass
class VisibilityIndex:
    """Index detached rows by public, team, and private-owner visibility."""

    rows_by_id: dict[str, Any] = field(default_factory=dict)
    public_ids: set[str] = field(default_factory=set)
    ids_by_team: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    private_ids_by_owner: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @classmethod
    def build(cls, rows: Sequence[Any]) -> "VisibilityIndex":
        """Index selected-column rows without retaining a database session.

        Args:
            rows: Detached rows with identity and visibility fields.

        Returns:
            Resource lookup and visibility partitions.
        """
        index = cls()
        for row in rows:
            index.rows_by_id[row.id] = row
            if row.visibility == "public":
                index.public_ids.add(row.id)
            elif row.visibility == "team" and row.team_id is not None:
                index.ids_by_team[row.team_id].add(row.id)
            elif row.visibility == "private" and row.owner_email is not None:
                index.private_ids_by_owner[row.owner_email].add(row.id)
        return index

    def visible_ids(self, user: UserScope) -> set[str]:
        """Select visible IDs without scanning resource rows again.

        Args:
            user: User identity and memberships.

        Returns:
            IDs visible to the user.
        """
        if user.is_admin:
            return set(self.rows_by_id)
        visible = self.public_ids.copy()
        for team_id in user.team_ids:
            visible.update(self.ids_by_team.get(team_id, ()))
        visible.update(self.private_ids_by_owner.get(user.email, ()))
        return visible


@dataclass
class ControlPlaneData:
    """Resource indexes and associations shared by all active users."""

    users: tuple[UserScope, ...] = ()
    servers: VisibilityIndex = field(default_factory=VisibilityIndex)
    gateways: VisibilityIndex = field(default_factory=VisibilityIndex)
    tools: VisibilityIndex = field(default_factory=VisibilityIndex)
    prompts: VisibilityIndex = field(default_factory=VisibilityIndex)
    resources: VisibilityIndex = field(default_factory=VisibilityIndex)
    backend_items: BackendItemsByServer = field(default_factory=dict)
