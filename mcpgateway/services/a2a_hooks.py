# -*- coding: utf-8 -*-
"""Plugin-hook helpers + agent-snapshot dataclass for A2A code paths.

Location: ./mcpgateway/services/a2a_hooks.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Extracted from the inline boilerplate that previously lived in
:meth:`A2AAgentService.invoke_agent` so that every A2A code path can
share the same plugin-hook firing convention without duplicating
~80 lines of GlobalContext + PydanticA2AAgent + invoke_hook setup at
each call site.

Public types:

* :class:`A2AAgentSnapshot` — frozen projection of a
  :class:`mcpgateway.db.A2AAgent` ORM row. Used by every downstream
  consumer (hooks, policy, telemetry) so the agent identity is
  pinned at lookup time and the DB session can be released early.
  Pairs with :class:`mcpgateway.services.caller_context.CallerContext`
  as the agent side of every ``(caller, target)`` policy input
  (Plan Amendment G).
* :class:`A2AHookContext` — bundle of identifiers + plugin manager +
  cpex ``GlobalContext`` + ``context_table`` threaded pre → post.

Three live helpers wrap the existing ``cpex.framework`` hook types:

* :func:`build_a2a_hook_context` — builds the bundle of identifiers,
  the per-tenant plugin manager, the cpex ``GlobalContext``, and an
  initially-empty ``context_table`` that the helpers thread from pre
  to post.
* :func:`fire_a2a_pre_invoke_hook` — fires ``AGENT_PRE_INVOKE``.
* :func:`fire_a2a_post_invoke_hook` — fires ``AGENT_POST_INVOKE``.

Six placeholder helpers document the integration points for the
A2A-specific events that don't exist in ``cpex.framework`` yet
(Amendment F, Phase C deferral). They are intentional no-ops today
that log at DEBUG so the audit trail still reflects WHERE the
firing would happen. The future focused commit per Amendment F's
deferral note swaps the bodies for real firing once the cpex fork
is resolved — see ``docs/docs/architecture/a2a-cpex-hook-proposal.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class A2AAgentSnapshot:
    """Frozen projection of a :class:`mcpgateway.db.A2AAgent` ORM row.

    Built once per request from a session-attached ``DbA2AAgent`` via
    :meth:`from_orm`. Lets every downstream consumer (plugin hooks,
    visibility policy, telemetry) work with the same identity tuple
    WITHOUT needing the DB session, so the connection can be released
    before any HTTP / RPC latency. Pairs with
    :class:`mcpgateway.services.caller_context.CallerContext` as the
    AGENT side of every ``(caller, target)`` policy input — together
    they're the canonical decision input for the three policy
    functions in :mod:`mcpgateway.services.a2a_access_policy`.

    Field set is deliberately bounded: identity, visibility / RBAC
    inputs, plugin-relevant config flags, and the auth-type label.
    Wire-level secrets (``endpoint_url``, ``auth_value``,
    ``auth_query_params``) stay on the ORM row and flow through
    :func:`mcpgateway.services.a2a_protocol.prepare_a2a_invocation`
    separately — those are dispatch concerns, not authorization
    concerns. Per Amendment G's MUST NOT clause, do NOT add wire
    secrets to this snapshot.
    """

    id: str
    name: str
    team_id: Optional[str]
    visibility: str
    enabled: bool
    tags: List[str]
    owner_email: Optional[str]
    oauth_config: Optional[Dict[str, Any]]
    oauth_enabled: bool
    passthrough_headers: Optional[List[str]]
    auth_type: Optional[str]

    @classmethod
    def from_orm(cls, agent: Any) -> "A2AAgentSnapshot":
        """Project a session-attached ``DbA2AAgent`` into a detached snapshot.

        Uses ``getattr`` with sensible defaults so the helper also accepts
        duck-typed stand-ins (``SimpleNamespace``, mocked ORM rows,
        Pydantic projections) without losing type discipline at the call
        site. Tags coerced to a fresh ``list`` so the snapshot owns its
        own copy and an ORM-level ``InstrumentedList`` cannot be mutated
        through it.

        Args:
            agent: A :class:`mcpgateway.db.A2AAgent` ORM row, OR any
                object that exposes the same field names. ``id`` is
                ``str()``-coerced so UUID columns and string keys both
                work; ``oauth_enabled`` is ``bool()``-coerced so the
                snapshot's invariant holds even when the ORM column
                returns a truthy non-bool.

        Returns:
            A frozen :class:`A2AAgentSnapshot` with every field locked
            for the rest of the request lifecycle.
        """
        return cls(
            id=str(agent.id),
            name=agent.name,
            team_id=getattr(agent, "team_id", None),
            visibility=getattr(agent, "visibility", "public"),
            enabled=bool(getattr(agent, "enabled", True)),
            tags=list(getattr(agent, "tags", None) or []),
            owner_email=getattr(agent, "owner_email", None),
            oauth_config=getattr(agent, "oauth_config", None),
            oauth_enabled=bool(getattr(agent, "oauth_enabled", False)),
            passthrough_headers=getattr(agent, "passthrough_headers", None),
            auth_type=getattr(agent, "auth_type", None),
        )


@dataclass(frozen=True)
class A2AHookContext:
    """Bundle of identifiers + plugin manager + ``GlobalContext`` per A2A op.

    Constructed once per A2A operation by :func:`build_a2a_hook_context`
    and passed to whichever hook-firing helper a given code path needs.
    Decouples context construction (which always needs the agent ORM row
    + correlation id + caller identity) from hook firing (which is
    event-type specific).

    The ``context_table`` field is a mutable dict deliberately — the
    pre-hook helper appends into it so the post-hook helper sees any
    state the pre-hook plugin chain threaded through. The frozen
    dataclass guarantees the IDENTIFIER fields don't drift between
    pre and post, while still allowing per-hook state to accumulate.
    """

    agent_id: str
    agent_name: str
    agent_team_id: Optional[str]
    correlation_id: str
    user_email: Optional[str]
    plugin_manager: Optional[Any]
    global_context: Any
    context_table: Dict[str, Any] = field(default_factory=dict)


PluginManagerFactory = Callable[[str], Awaitable[Optional[Any]]]


async def build_a2a_hook_context(
    agent: Any,
    *,
    correlation_id: str,
    user_email: Optional[str],
    plugin_manager_factory: PluginManagerFactory,
    content_type: Optional[str] = None,
) -> A2AHookContext:
    """Build the per-operation A2A hook context bundle.

    Mirrors the setup that previously lived inline in
    :meth:`A2AAgentService.invoke_agent` at lines 3097-3127 (pre-refactor)
    so card / extended-card / streaming dispatch can reuse the same
    plumbing without copy-pasting the boilerplate.

    Args:
        agent: The :class:`mcpgateway.db.A2AAgent` ORM row for the
            target agent. Read via ``getattr`` so a future caller can
            pass a partial / lighter object (e.g. a Pydantic projection)
            without breaking the helper.
        correlation_id: Per-request correlation id from
            ``get_correlation_id()``.
        user_email: Authenticated caller email; ``None`` for anonymous
            (the public card route at T11 is the canonical anonymous
            caller).
        plugin_manager_factory: Async callable
            ``(context_id: str) -> Optional[TenantPluginManager]``.
            Service-internal callers pass
            ``self._get_plugin_manager``; route handlers pass the
            top-level ``mcpgateway.plugins.get_plugin_manager``.
        content_type: Optional content-type header value to attach to
            the agent metadata so plugins can route on it.

    Returns:
        A frozen :class:`A2AHookContext` ready to thread through the
        fire-pre / fire-post helpers.
    """
    # Third-Party
    from cpex.framework import GlobalContext  # pylint: disable=import-outside-toplevel

    # First-Party
    from mcpgateway.plugins.gateway_plugin_manager import make_context_id  # pylint: disable=import-outside-toplevel
    from mcpgateway.schemas import A2A_AGENT_METADATA, PydanticA2AAgent  # pylint: disable=import-outside-toplevel

    agent_id = str(agent.id)
    agent_name = agent.name
    agent_team_id = getattr(agent, "team_id", None)

    agent_context_id = make_context_id(str(agent_team_id), agent_name) if agent_team_id else agent_id
    plugin_manager = await plugin_manager_factory(agent_context_id)

    global_context = GlobalContext(
        request_id=correlation_id or "",
        server_id=agent_context_id if agent_team_id else agent_id,
        tenant_id=agent_team_id if agent_team_id and isinstance(agent_team_id, str) else None,
        user=user_email,
    )

    if plugin_manager:
        try:
            agent_metadata = PydanticA2AAgent(
                id=agent_id,
                name=agent_name,
                team_id=agent_team_id,
                visibility=getattr(agent, "visibility", "public"),
                enabled=getattr(agent, "enabled", True),
                tags=getattr(agent, "tags", None) or [],
                oauth_config=getattr(agent, "oauth_config", None),
                passthrough_headers=getattr(agent, "passthrough_headers", None),
                auth_type=getattr(agent, "auth_type", None),
            )
            if content_type:
                agent_metadata.content_type = content_type
            global_context.metadata[A2A_AGENT_METADATA] = agent_metadata
        except Exception as exc:
            logger.warning("Failed to build A2A agent metadata for plugins: %s", exc)

    return A2AHookContext(
        agent_id=agent_id,
        agent_name=agent_name,
        agent_team_id=agent_team_id,
        correlation_id=correlation_id,
        user_email=user_email,
        plugin_manager=plugin_manager,
        global_context=global_context,
        context_table={},
    )


async def fire_a2a_pre_invoke_hook(
    ctx: A2AHookContext,
    *,
    parameters: Dict[str, Any],
    request_headers: Optional[Dict[str, str]] = None,
) -> Optional[Any]:
    """Fire ``AGENT_PRE_INVOKE`` for an A2A unary invocation.

    The caller decides how to apply ``pre_result.modified_payload`` —
    parameters and headers updates are invocation-specific and stay
    inline at the call site (e.g. invoke_agent overrides ``parameters``
    and patches ``prepared.headers``).

    Args:
        ctx: The hook context built by :func:`build_a2a_hook_context`.
        parameters: The invocation parameters to ship to the plugin
            chain. Passed as both the ``messages`` payload (in
            user-role form) and the ``parameters`` payload field.
        request_headers: Inbound HTTP headers (already filtered for
            credential leakage by the caller). Plugins can mutate via
            ``pre_result.modified_payload.headers``.

    Returns:
        The cpex ``AgentPreInvokeResult`` if a hook ran, else ``None``.

    Raises:
        cpex.framework.PluginViolationError: When the pre-hook denies the
            call (``violations_as_exceptions=True``). Callers turn this
            into an :class:`A2AAgentError` per their own conventions.
    """
    # Third-Party
    from cpex.framework import (  # pylint: disable=import-outside-toplevel
        AgentHookType,
        AgentPreInvokePayload,
        HttpHeaderPayload,
    )

    pm = ctx.plugin_manager
    if not pm or not pm.has_hooks_for(AgentHookType.AGENT_PRE_INVOKE):
        return None

    pre_result, new_context = await pm.invoke_hook(
        AgentHookType.AGENT_PRE_INVOKE,
        payload=AgentPreInvokePayload(
            agent_id=ctx.agent_id,
            messages=[{"role": "user", "content": parameters}] if parameters else [],
            headers=HttpHeaderPayload(root=request_headers or {}),
            parameters=parameters if isinstance(parameters, dict) else {},
        ),
        global_context=ctx.global_context,
        local_contexts=ctx.context_table,
        violations_as_exceptions=True,
    )
    if new_context:
        ctx.context_table.update(new_context)
    return pre_result


async def fire_a2a_post_invoke_hook(
    ctx: A2AHookContext,
    *,
    response: Optional[Any],
    success: bool,
) -> Optional[Any]:
    """Fire ``AGENT_POST_INVOKE`` for an A2A unary invocation.

    Non-blocking — any exception from the plugin chain is logged at
    WARNING and swallowed so a misbehaving observability plugin can
    never fail an otherwise-successful agent invocation.

    Args:
        ctx: The hook context built by :func:`build_a2a_hook_context`.
        response: The agent response object (dict / Task / etc.). Wrapped
            as a single assistant-role message in the payload.
        success: Whether the invocation succeeded. ``messages`` is left
            empty on failure so post-hook plugins do not see partial /
            error responses misframed as assistant output.

    Returns:
        The cpex ``AgentPostInvokeResult`` if a hook ran, else ``None``.
        Callers can inspect ``post_result.retry_delay_ms`` to honor a
        plugin-requested retry.
    """
    # Third-Party
    from cpex.framework import (  # pylint: disable=import-outside-toplevel
        AgentHookType,
        AgentPostInvokePayload,
    )

    pm = ctx.plugin_manager
    if not pm or not pm.has_hooks_for(AgentHookType.AGENT_POST_INVOKE):
        return None

    try:
        post_result, _ = await pm.invoke_hook(
            AgentHookType.AGENT_POST_INVOKE,
            payload=AgentPostInvokePayload(
                agent_id=ctx.agent_id,
                messages=[{"role": "assistant", "content": response}] if response and success else [],
                tool_calls=None,
            ),
            global_context=ctx.global_context,
            local_contexts=ctx.context_table,
            violations_as_exceptions=False,
        )
        return post_result
    except Exception as exc:
        logger.warning("Post-invoke plugin error for A2A agent %s: %s", ctx.agent_id, exc)
        return None


# =============================================================================
# Placeholder hooks for Amendment F (Phase C) — DEFERRED wiring.
#
# These six helpers document the integration points for A2A-specific plugin
# events on code paths that DO NOT reuse invoke_agent (T11 card route,
# T12 GetExtendedAgentCard branch, T5 streaming dispatch). They are
# intentional no-ops today; the future Phase C focused commit per
# Amendment F's deferral note swaps the bodies for real firing once the
# cpex fork is resolved.
#
# Decision fork (see docs/docs/architecture/a2a-cpex-hook-proposal.md):
#   - Path A: extend cpex.framework with new AgentHookType values
#     (AGENT_CARD_PRE/POST, AGENT_EXTENDED_CARD_PRE/POST,
#     AGENT_STREAMING_DISPATCH_PRE/POST) + matching payload classes.
#     Real bodies fire those events directly.
#   - Path B: reuse AGENT_PRE_INVOKE/POST with a `method` discriminator
#     on the payload. Real bodies pass the A2A method name through so
#     plugins can filter on `method in {"GetAgentCard", ...}`.
#
# The placeholder signatures are deliberately MINIMAL — they take only
# the identifiers each event would need at firing time, not a full
# A2AHookContext, because card discovery fires BEFORE the agent ORM is
# resolved at the T11 route. The real bodies will either:
#   (a) build A2AHookContext after the lookup and fire from there, or
#   (b) accept an A2AHookContext parameter for paths where the agent
#       row is already in hand (T12, T5).
# =============================================================================


async def fire_a2a_card_pre_hook(
    plugin_manager: Optional[Any],
    *,
    agent_name: str,
    server_id: Optional[str],
    public_base_url: str,
    caller_email: Optional[str],
) -> None:
    """PLACEHOLDER for ``AGENT_CARD_PRE`` (Amendment F, T-Phase-C-1).

    Fires before the per-agent or v-server-scoped card synthesis at the
    T11 well-known route. Today this is a no-op that logs at DEBUG; the
    future Phase C commit wires it to either cpex ``AGENT_CARD_PRE``
    (Path A) or ``AGENT_PRE_INVOKE`` with ``method="GetAgentCard"``
    (Path B). See ``docs/docs/architecture/a2a-cpex-hook-proposal.md``
    for the wire shape and the decision fork.
    """
    if plugin_manager is None:
        return
    logger.debug(
        "A2A card discovery pre-hook (placeholder): agent=%s server_id=%s base=%s caller=%s",
        agent_name,
        server_id,
        public_base_url,
        caller_email,
    )


async def fire_a2a_card_post_hook(
    plugin_manager: Optional[Any],
    *,
    agent_name: str,
    server_id: Optional[str],
    card_resolved: bool,
) -> None:
    """PLACEHOLDER for ``AGENT_CARD_POST`` (Amendment F, T-Phase-C-1).

    Fires after the card synthesis returns. ``card_resolved`` is False on
    None (visibility miss / agent not found / v-server membership miss)
    so plugins can distinguish a real card discovery from a 404 outcome.
    See ``docs/docs/architecture/a2a-cpex-hook-proposal.md``.
    """
    if plugin_manager is None:
        return
    logger.debug(
        "A2A card discovery post-hook (placeholder): agent=%s server_id=%s resolved=%s",
        agent_name,
        server_id,
        card_resolved,
    )


async def fire_a2a_extended_card_pre_hook(
    ctx: A2AHookContext,
    *,
    server_id: Optional[str],
) -> None:
    """PLACEHOLDER for ``AGENT_EXTENDED_CARD_PRE`` (Amendment F, T-Phase-C-2).

    Fires before the extended card synthesis in the
    ``GetExtendedAgentCard`` / ``agent/getAuthenticatedExtendedCard``
    branch at main.py dispatch_a2a_agent. The agent ORM row is already
    resolved at this point, so the helper takes a full
    :class:`A2AHookContext`. D18 (NEVER forwards upstream) stays enforced
    in main.py — this hook only observes the synthesis, it does not gate
    or modify the upstream forwarding decision.
    """
    if ctx.plugin_manager is None:
        return
    logger.debug(
        "A2A extended card pre-hook (placeholder): agent=%s server_id=%s",
        ctx.agent_name,
        server_id,
    )


async def fire_a2a_extended_card_post_hook(
    ctx: A2AHookContext,
    *,
    server_id: Optional[str],
    capabilities_advertised: bool,
) -> None:
    """PLACEHOLDER for ``AGENT_EXTENDED_CARD_POST`` (Amendment F, T-Phase-C-2).

    Fires after the extended card branch returns. ``capabilities_advertised``
    is False on the ``-32007 AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED``
    path so plugins can distinguish a real extended card from a
    capabilities-deny.
    """
    if ctx.plugin_manager is None:
        return
    logger.debug(
        "A2A extended card post-hook (placeholder): agent=%s server_id=%s advertised=%s",
        ctx.agent_name,
        server_id,
        capabilities_advertised,
    )


async def fire_a2a_streaming_dispatch_pre_hook(
    ctx: A2AHookContext,
    *,
    method: str,
    server_id: Optional[str],
    hop_count: int,
) -> None:
    """PLACEHOLDER for ``AGENT_STREAMING_DISPATCH_PRE`` (Amendment F, T-Phase-C-3).

    Fires before ``dispatch_a2a_jsonrpc_streaming`` returns its async
    generator (i.e. before the upstream SSE connection opens). MUST fire
    exactly once per request, regardless of stream length. Mirrors the
    ``AGENT_PRE_INVOKE`` semantics for unary calls.

    The companion post-hook fires once after the stream closes (either
    normal completion or client disconnect) — see
    :func:`fire_a2a_streaming_dispatch_post_hook`.
    """
    if ctx.plugin_manager is None:
        return
    logger.debug(
        "A2A streaming dispatch pre-hook (placeholder): agent=%s method=%s server_id=%s hop=%d",
        ctx.agent_name,
        method,
        server_id,
        hop_count,
    )


async def fire_a2a_streaming_dispatch_post_hook(
    ctx: A2AHookContext,
    *,
    method: str,
    server_id: Optional[str],
    chunks_sent: int,
    completed_normally: bool,
) -> None:
    """PLACEHOLDER for ``AGENT_STREAMING_DISPATCH_POST`` (Amendment F, T-Phase-C-3).

    Fires once after the stream closes — normal completion OR client
    disconnect. MUST NOT fire from inside the async-generator yield loop
    (Amendment F constraint: plugins see one event per request, not one
    per chunk). ``chunks_sent`` lets plugins record the stream length
    without subscribing to the chunk-level data.
    """
    if ctx.plugin_manager is None:
        return
    logger.debug(
        "A2A streaming dispatch post-hook (placeholder): agent=%s method=%s server_id=%s chunks=%d complete=%s",
        ctx.agent_name,
        method,
        server_id,
        chunks_sent,
        completed_normally,
    )
