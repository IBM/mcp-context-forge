# -*- coding: utf-8 -*-
"""Centralized A2A access-decision policy module (Plan T16 Phase A).

Location: ./mcpgateway/services/a2a_access_policy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Single source of truth for visibility decisions about A2A agents under
both the per-agent and the virtual-server-scoped URL families. Lives
beside :mod:`mcpgateway.services.permission_service` (the RBAC service)
so the **DECISIONS** are co-located even though the primitives they
compose live in domain services today.

**Migration intent** (per user direction): when the platform adopts a
rules-engine (OPA, Casbin, custom DSL), the bodies of these functions
become policy-lookup calls; the **callers and call sites do not change**.
That is the contract that makes this module worth maintaining.

The three decisions exposed here:

- :func:`can_view_a2a_agent_directly` — single-level: agent's own
  Layer-1 visibility (used by ``/a2a/{name}``).
- :func:`can_view_a2a_agent_in_server_context` — three-level
  conjunctive: server visibility AND agent visibility AND agent-in-
  server membership (used by ``/servers/{id}/a2a/{name}``). The plan
  amendment explicitly forbids substituting any one of these for
  another — server membership does NOT bypass agent visibility, and
  vice versa.
- :func:`can_associate_a2a_agent_with_server` — CRUD authorization:
  the caller must be able to see BOTH the server they are mutating
  AND the agent they are adding (used by ``ServerService.create_server``
  and ``ServerService.update_server`` in Wave 5 T20).

Primitives composed:

- ``_check_server_access`` from
  :mod:`mcpgateway.services.a2a_server_service` — server visibility
  primitive (sync, no DB).
- ``A2AAgentService._check_agent_access`` — agent visibility primitive
  (async, may touch DB for team membership).
- ``A2AAgentService.check_server_a2a_membership`` — binding lookup
  (async, single SELECT against ``server_a2a_association``).

Type-only import of :class:`A2AAgentService` avoids a circular import at
module-load time (the service module imports this policy module).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy.orm import Session

from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Server as DbServer
from mcpgateway.services.a2a_server_service import _check_server_access

if TYPE_CHECKING:  # pragma: no cover - import-time-only
    from mcpgateway.services.a2a_service import A2AAgentService


async def can_view_a2a_agent_directly(
    db: Session,
    *,
    agent: DbA2AAgent,
    user_email: Optional[str],
    token_teams: Optional[List[str]],
    a2a_service: "A2AAgentService",
) -> bool:
    """Decide whether the caller can view ``agent`` via ``/a2a/{name}``.

    Single-level: only the agent's own Layer-1 visibility scope is
    consulted. No server or membership context applies on the direct
    per-agent path.

    Args:
        db: Database session.
        agent: The A2A agent ORM row (must expose ``visibility``,
            ``owner_email``, ``team_id``).
        user_email: Caller email; ``None`` for anonymous (combined with
            ``token_teams=None`` triggers admin-bypass).
        token_teams: Caller team scope per
            ``_check_agent_access`` semantics: ``None`` is unrestricted,
            ``[]`` is public-only, ``[ids...]`` is team-scoped.
        a2a_service: The :class:`A2AAgentService` instance — we delegate
            to its existing primitive. A future rules-engine migration
            will drop this parameter once the primitive moves here.

    Returns:
        ``True`` when the caller can see the agent, ``False`` otherwise.
    """
    return await a2a_service._check_agent_access(db, agent, user_email, token_teams)  # pylint: disable=protected-access


async def can_view_a2a_agent_in_server_context(
    db: Session,
    *,
    agent: DbA2AAgent,
    server: DbServer,
    user_email: Optional[str],
    token_teams: Optional[List[str]],
    a2a_service: "A2AAgentService",
) -> bool:
    """Decide whether the caller can view ``agent`` via ``/servers/{id}/a2a/{name}``.

    Three-level conjunctive: ALL must pass. None of these checks
    substitute for any other — server membership does NOT bypass agent
    visibility, agent visibility does NOT bypass server visibility, and
    public visibility on either side does NOT bypass the binding check.

    Check ordering (cheapest first, expensive last):

    1. **Server visibility** — caller can see the virtual server itself.
       Sync, no DB query.
    2. **Agent-in-server membership** — the binding has been explicitly
       configured on this server via ``server_a2a_association``.
       Single SELECT against the join table.
    3. **Agent visibility** — caller can see the agent itself (its
       Layer-1 scope still applies in v-server context). Async, may
       query team membership.

    This ordering also reduces timing side-channels: the expensive
    team-membership query in step 3 is short-circuited by the cheaper
    checks above, so denials at the first two layers are
    indistinguishable in latency from each other.

    Args:
        db: Database session.
        agent: The A2A agent ORM row.
        server: The virtual-server ORM row.
        user_email: Caller email.
        token_teams: Caller team scope.
        a2a_service: The :class:`A2AAgentService` instance (delegation
            shim — see :func:`can_view_a2a_agent_directly`).

    Returns:
        ``True`` iff all three checks pass, ``False`` otherwise.
    """
    if not _check_server_access(server, user_email, token_teams):
        return False
    if not await a2a_service.check_server_a2a_membership(db, server.id, agent.id):
        return False
    if not await a2a_service._check_agent_access(db, agent, user_email, token_teams):  # pylint: disable=protected-access
        return False
    return True


async def can_associate_a2a_agent_with_server(
    db: Session,
    *,
    agent: DbA2AAgent,
    server: DbServer,
    user_email: Optional[str],
    token_teams: Optional[List[str]],
    a2a_service: "A2AAgentService",
) -> bool:
    """Decide whether the caller can add ``agent`` to ``server`` membership.

    CRUD authorization (Wave 5 T20). Requires:

    1. Caller can see the server they are mutating (otherwise they
       would not even know the server exists).
    2. Caller can see the agent they are adding (otherwise they could
       expose an agent they have no business surfacing).

    Combined: an admin who can see both proceeds; a team member who
    can see the server but not the agent is denied; and so on. The
    decision is symmetric in the same sense as
    :func:`can_view_a2a_agent_in_server_context`: BOTH sides must
    permit the action.

    Args:
        db: Database session.
        agent: The A2A agent ORM row being added.
        server: The virtual-server ORM row being mutated.
        user_email: Caller email.
        token_teams: Caller team scope.
        a2a_service: The :class:`A2AAgentService` instance.

    Returns:
        ``True`` iff the caller can both view the server and view the
        agent, ``False`` otherwise.
    """
    if not _check_server_access(server, user_email, token_teams):
        return False
    if not await a2a_service._check_agent_access(db, agent, user_email, token_teams):  # pylint: disable=protected-access
        return False
    return True
