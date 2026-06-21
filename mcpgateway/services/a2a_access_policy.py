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
policy engine via ``cpex`` or any other rules-engine substrate, the
bodies of these three functions become policy-lookup calls; the
**callers and call sites do not change** for today's signatures. The
``a2a_service`` delegation-shim parameter is provisional and will drop
when the primitives' return values are pre-fetched at the call site —
see Amendment E in ``.omo/plans/a2a-native-passthrough.md`` for the
honest scope statement. This module is worth maintaining BECAUSE it
isolates the decision points to three named functions.

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

from mcpgateway.db import Server as DbServer
from mcpgateway.services.a2a_hooks import A2AAgentSnapshot
from mcpgateway.services.a2a_server_service import _check_server_access

if TYPE_CHECKING:  # pragma: no cover - import-time-only
    from mcpgateway.services.a2a_service import A2AAgentService


async def can_view_a2a_agent_directly(
    db: Session,
    *,
    agent_snapshot: A2AAgentSnapshot,
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
        agent_snapshot: Frozen :class:`A2AAgentSnapshot` projection of
            the agent ORM row. Plan Amendment G: callers build the
            snapshot once via :meth:`A2AAgentSnapshot.from_orm` and
            thread it through every visibility decision so the DB
            connection can be released early.
        user_email: Caller email; ``None`` for anonymous.
        token_teams: Caller team scope. Semantics per
            ``A2AAgentService._check_agent_access`` (see
            ``a2a_service.py:807``), summarized here because it is
            load-bearing for the rules-engine migration:

            - ``[]`` (empty list) — public-only token. Sees public
              agents only; cannot see team or private agents.
            - ``[id1, id2, ...]`` — team-scoped. Sees public + agents
              whose ``team_id`` is in the list + agents the caller
              owns directly.
            - ``None`` — JWT did NOT carry a ``teams`` claim. Behaviour
              then depends on ``user_email``:

                * ``user_email=None`` AND ``token_teams=None`` →
                  anonymous admin bypass: sees public + team agents
                  only (PR #4341 — NEVER sees private agents).
                * ``user_email=<admin>`` AND ``token_teams=None`` →
                  authenticated admin: sees public + team + OWN
                  private (other users' private remain hidden).
                * ``user_email=<non-admin>`` AND ``token_teams=None``
                  → upstream normalization should prevent this state,
                  but defended: returns False for non-public.

            ``None`` is therefore NOT "unrestricted" in any case; it
            is the JWT-absent path that grants admin-flavoured access
            ONLY when paired with the appropriate ``user_email``.
        a2a_service: The :class:`A2AAgentService` instance — we delegate
            to its existing primitive. The future rules-engine migration
            (Cedar / cedarpy) replaces the function BODY with a policy
            lookup; whether the ``a2a_service`` parameter survives
            depends on whether the primitives also migrate. Treat the
            signature as STABLE for today's callers; expect a follow-up
            refactor when the rules engine lands.

    Returns:
        ``True`` when the caller can see the agent, ``False`` otherwise.
    """
    return await a2a_service._check_agent_access(db, agent_snapshot, user_email, token_teams)  # pylint: disable=protected-access


async def can_view_a2a_agent_in_server_context(
    db: Session,
    *,
    agent_snapshot: A2AAgentSnapshot,
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

    Cheap-first ordering is for PERFORMANCE on the allowed path and to
    minimize DB work on early denials. It does **NOT** make denials
    indistinguishable by latency: a step-1 denial (sync only) is
    faster than a step-2 denial (one SELECT) is faster than a
    step-3 denial (potentially a team-membership SELECT). A timing
    attacker who measures many samples could distinguish the three
    denial layers. The wire response is uniform per D14 (HTTP 404 for
    every denial reason); the timing differences are an accepted
    tradeoff vs. the cost of constant-time evaluation. If the
    deployment threat model needs constant-time, switch to running
    all three checks unconditionally and combining the booleans.

    See :func:`can_view_a2a_agent_directly` for the ``token_teams``
    semantics that load-bear the agent-visibility check (step 3).

    Args:
        db: Database session.
        agent_snapshot: Frozen :class:`A2AAgentSnapshot` for the agent
            being checked (Plan Amendment G).
        server: The virtual-server ORM row.
        user_email: Caller email.
        token_teams: Caller team scope (see
            :func:`can_view_a2a_agent_directly` for the full table).
        a2a_service: The :class:`A2AAgentService` instance (delegation
            shim — see :func:`can_view_a2a_agent_directly`).

    Returns:
        ``True`` iff all three checks pass, ``False`` otherwise.
    """
    if not _check_server_access(server, user_email, token_teams):
        return False
    if not await a2a_service.check_server_a2a_membership(db, server.id, agent_snapshot.id):
        return False
    if not await a2a_service._check_agent_access(db, agent_snapshot, user_email, token_teams):  # pylint: disable=protected-access
        return False
    return True


async def can_associate_a2a_agent_with_server(
    db: Session,
    *,
    agent_snapshot: A2AAgentSnapshot,
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
        agent_snapshot: Frozen :class:`A2AAgentSnapshot` of the agent
            being added (Plan Amendment G).
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
    if not await a2a_service._check_agent_access(db, agent_snapshot, user_email, token_teams):  # pylint: disable=protected-access
        return False
    return True
