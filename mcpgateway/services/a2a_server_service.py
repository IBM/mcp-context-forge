# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/a2a_server_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Service for exposing virtual servers as A2A agents (virtual server federation).

A virtual server with an enabled ServerInterface whose protocol contains "a2a"
can be resolved and invoked as if it were a standalone A2A agent.  The Rust
sidecar calls /_internal/a2a/agents/{name}/resolve; this service provides the
fallback lookup when no matching DbA2AAgent row exists.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Any, Dict, NamedTuple, Optional, Union
import uuid

# Third-Party
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload, Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Server as DbServer
from mcpgateway.db import server_a2a_association
from mcpgateway.db import ServerInterface as DbServerInterface
from mcpgateway.db import ServerTaskMapping as DbServerTaskMapping
from mcpgateway.services.a2a_protocol import is_v1_a2a_protocol

logger = logging.getLogger(__name__)


class _AggregatedCapabilities(NamedTuple):
    """Capabilities, modes, and skills aggregated across a server's associated agents."""

    streaming: bool
    push_notifications: bool
    skills: list[Dict[str, Any]]
    input_modes: list[str]
    output_modes: list[str]


_A2A_BINDING_PREFIX = "a2a-"
_DEFAULT_PROTOCOL_BINDING = "JSONRPC"


def _derive_protocol_binding(protocol: str) -> str:
    """Map a stored ``ServerInterface.protocol`` value to an A2A ``protocolBinding``.

    ``protocol`` combines the protocol family and its binding, e.g.
    ``a2a-jsonrpc`` or ``a2a-grpc`` (see
    ``uq_server_interfaces_server_protocol_binding``). Falls back to
    ``JSONRPC``, the only binding ContextForge's A2A invocation path
    supports today, when no binding suffix is present.

    Args:
        protocol: The interface's stored ``protocol`` value.

    Returns:
        An uppercase protocol-binding token, e.g. ``JSONRPC`` or ``GRPC``.
    """
    lowered = (protocol or "").lower()
    if lowered.startswith(_A2A_BINDING_PREFIX) and len(lowered) > len(_A2A_BINDING_PREFIX):
        return lowered[len(_A2A_BINDING_PREFIX) :].upper()
    return _DEFAULT_PROTOCOL_BINDING


def _check_server_access(server: Union[DbServer, DbA2AAgent], user_email: Optional[str], token_teams: Optional[list[str]]) -> bool:
    """Apply the standard scoped visibility rules to a virtual server.

    Admin bypass invariant (PR #4341): never reveal another user's private
    servers via an admin-bypass shape. Anonymous bypass (token_teams=None
    AND user_email=None) sees public + team but never private. DB-resolved
    admin sessions ((email, None) shape) fall through to the natural flow
    below, which already grants public + team + own-private and denies
    other users' private. Mirrors a2a_service._check_agent_access.
    """
    if server.visibility == "public":
        return True

    if token_teams is None and user_email is None:
        # Anonymous admin bypass: team allowed, private denied (PR #4341).
        return server.visibility != "private"

    if not user_email:
        return False

    is_public_only_token = token_teams is not None and len(token_teams) == 0
    if is_public_only_token:
        return False

    if server.visibility == "private" and server.owner_email and server.owner_email == user_email:
        return True

    if server.visibility == "team":
        if token_teams is None:
            return True
        return server.team_id in token_teams

    return False


class A2AServerService:
    """Service for exposing virtual servers as A2A agents.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> service = A2AServerService()
        >>> db = MagicMock()
        >>> db.execute.return_value.scalar_one_or_none.return_value = None
        >>> service.resolve_server_agent(db, "missing") is None
        True
        >>> service.get_server_agent_card(db, "missing") is None
        True
    """

    def get_server_agent_card(
        self,
        db: Session,
        server_name: Optional[str] = None,
        *,
        user_email: Optional[str] = None,
        token_teams: Optional[list[str]] = None,
        caller_version: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build an A2A v1 AgentCard for a virtual server.

        Looks up the server by name, or by ID when ``server_id`` is set
        (enabled=True), checks for an enabled
        ServerInterface whose protocol contains 'a2a' (case-insensitive), and
        builds an AgentCard dict from the server and interface metadata.
        Skills are derived from associated A2A agents.

        Args:
            db: Database session.
            server_name: Name of the virtual server. Ignored when ``server_id`` is set.
            user_email: Caller's email for visibility scoping.
            token_teams: Caller's teams for visibility scoping.
            caller_version: A2A version the caller speaks (its ``A2A-Version`` header).
                A pre-1.0 value keeps the legacy card shape.
            server_id: ID of the virtual server to look up instead of ``server_name``.

        Returns:
            AgentCard dict, or None if the server does not exist, is disabled,
            is not visible to the caller, or has no enabled A2A interface.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = A2AServerService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service.get_server_agent_card(db, "no-such-server") is None
            True
            >>> service.get_server_agent_card(db, server_id="no-such-server") is None
            True
        """
        match = DbServer.id == server_id if server_id is not None else DbServer.name == server_name
        server_query = select(DbServer).where(match, DbServer.enabled.is_(True)).options(selectinload(DbServer.a2a_agents))
        server = db.execute(server_query).scalar_one_or_none()
        if not server:
            return None
        if not _check_server_access(server, user_email, token_teams):
            return None

        interface = self._find_a2a_interface(db, server.id)
        if not interface:
            return None

        return self._build_server_card(server, interface, user_email, token_teams, caller_version)

    def _aggregate_agent_capabilities(self, server: DbServer, user_email: Optional[str], token_teams: Optional[list[str]]) -> _AggregatedCapabilities:
        """Aggregate capability flags, modes, and deduplicated skills from enabled associated agents.

        Malformed free-form ``capabilities`` entries (a non-list ``skills`` or
        mode field, a non-string mode, a non-string skill ``id``) are skipped
        so one bad agent cannot break the server card.

        Args:
            server: The virtual server whose associated A2A agents to aggregate.
            user_email: Caller's email for per-agent visibility scoping.
            token_teams: Caller's teams for per-agent visibility scoping.

        Returns:
            An :class:`_AggregatedCapabilities`. ``streaming`` and
            ``push_notifications`` are ``True`` if any enabled associated agent
            declares them. ``skills`` keeps only the first occurrence of each
            skill id, so identical ids from different agents don't collide.
            ``input_modes`` and ``output_modes`` are the union of
            ``defaultInputModes``/``defaultOutputModes`` declared by enabled
            associated agents, in first-seen order, or ``["text"]`` when no
            agent declares any — Server/ServerInterface have no capabilities
            column of their own.
        """
        streaming = False
        push_notifications = False
        skills: list[Dict[str, Any]] = []
        seen_skill_ids: set[str] = set()
        input_modes: list[str] = []
        output_modes: list[str] = []
        for agent in server.a2a_agents:
            if not agent.enabled or not _check_server_access(agent, user_email, token_teams):
                continue
            caps = agent.capabilities if isinstance(agent.capabilities, dict) else {}
            streaming = streaming or bool(caps.get("streaming", False))
            push_notifications = push_notifications or bool(caps.get("pushNotifications", False))
            raw_skills = caps.get("skills")
            for skill in raw_skills if isinstance(raw_skills, list) else []:
                skill_id = skill.get("id") if isinstance(skill, dict) else None
                if skill_id is not None:
                    if not isinstance(skill_id, str):
                        logger.debug("Skipping skill with non-string id on agent %s", agent.id)
                        continue
                    if skill_id in seen_skill_ids:
                        logger.debug("Dropping duplicate skill id %r from agent %s", skill_id, agent.id)
                        continue
                    seen_skill_ids.add(skill_id)
                skills.append(skill)
            for key, modes in (("defaultInputModes", input_modes), ("defaultOutputModes", output_modes)):
                declared = caps.get(key)
                for mode in declared if isinstance(declared, list) else []:
                    if isinstance(mode, str) and mode not in modes:
                        modes.append(mode)
        return _AggregatedCapabilities(streaming, push_notifications, skills, input_modes or ["text"], output_modes or ["text"])

    def _build_server_card(self, server: DbServer, interface: DbServerInterface, user_email: Optional[str], token_teams: Optional[list[str]], caller_version: Optional[str] = None) -> Dict[str, Any]:
        """Dispatch card construction by the interface's declared protocol version.

        Args:
            server: The visibility-checked virtual server row.
            interface: Its enabled A2A ``ServerInterface`` row.
            user_email: Caller's email for per-agent visibility scoping.
            token_teams: Caller's teams for per-agent visibility scoping.
            caller_version: A2A version the caller speaks, when it declared one.
                A pre-1.0 value always gets the legacy shape.

        Returns:
            AgentCard dict, shaped per the interface's declared protocol version.
        """
        capabilities = self._aggregate_agent_capabilities(server, user_email, token_teams)
        if is_v1_a2a_protocol(interface.version) and (not caller_version or is_v1_a2a_protocol(caller_version)):
            return self._build_v1_server_card(server, interface, capabilities)
        return self._build_legacy_server_card(server, interface, capabilities)

    def _build_legacy_server_card(self, server: DbServer, interface: DbServerInterface, capabilities: _AggregatedCapabilities) -> Dict[str, Any]:
        """Build the pre-1.0 AgentCard shape for a v0.3 interface.

        Preserved unchanged (aside from aggregating capabilities and modes
        from associated agents instead of hardcoding them) so existing v0.3
        callers see no shape change.

        Args:
            server: The visibility-checked virtual server row.
            interface: Its enabled A2A ``ServerInterface`` row.
            capabilities: Capabilities, modes, and skills aggregated from associated agents.

        Returns:
            AgentCard dict in the A2A v0.3 shape.
        """
        return {
            "name": server.name,
            "description": server.description or "",
            "url": interface.binding,
            "version": str(server.version),
            "protocolVersion": interface.version or "1.0",
            "defaultInputModes": capabilities.input_modes,
            "defaultOutputModes": capabilities.output_modes,
            "capabilities": {
                "streaming": capabilities.streaming,
                "pushNotifications": capabilities.push_notifications,
                "stateTransitionHistory": False,
            },
            "skills": capabilities.skills,
            "supportsAuthenticatedExtendedCard": True,
        }

    def _build_v1_server_card(self, server: DbServer, interface: DbServerInterface, capabilities: _AggregatedCapabilities) -> Dict[str, Any]:
        """Build the A2A 1.0 AgentCard shape for a v1+ interface.

        Transport is reported through ``supportedInterfaces``, with
        ``protocolBinding`` derived from the interface's ``protocol`` value
        rather than reusing its endpoint for both roles.

        Args:
            server: The visibility-checked virtual server row.
            interface: Its enabled A2A ``ServerInterface`` row.
            capabilities: Capabilities, modes, and skills aggregated from associated agents.

        Returns:
            AgentCard dict in the A2A 1.0 shape.
        """
        iface: Dict[str, Any] = {
            "url": interface.binding,
            "protocolBinding": _derive_protocol_binding(interface.protocol),
            "protocolVersion": interface.version or "1.0",
        }
        if interface.tenant:
            iface["tenant"] = interface.tenant

        return {
            "name": server.name,
            "description": server.description or "",
            "version": str(server.version),
            "supportedInterfaces": [iface],
            "capabilities": {
                "streaming": capabilities.streaming,
                "pushNotifications": capabilities.push_notifications,
                "extendedAgentCard": True,
            },
            "defaultInputModes": capabilities.input_modes,
            "defaultOutputModes": capabilities.output_modes,
            "skills": capabilities.skills,
        }

    def resolve_server_agent(
        self,
        db: Session,
        server_name: str,
        *,
        user_email: Optional[str] = None,
        token_teams: Optional[list[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve a virtual server's A2A agent endpoint for invocation.

        Returns a dict matching the ResolvedAgent format expected by the Rust
        sidecar if the server has an enabled A2A interface. Returns None if the
        server does not exist, is disabled, or has no A2A interface.

        Args:
            db: Database session.
            server_name: Name of the virtual server.
            user_email: Caller's email for visibility scoping.
            token_teams: Caller's teams for visibility scoping.

        Returns:
            ResolvedAgent dict, or None.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = A2AServerService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service.resolve_server_agent(db, "no-such-server") is None
            True
        """
        server_query = select(DbServer).where(DbServer.name == server_name, DbServer.enabled.is_(True))
        server = db.execute(server_query).scalar_one_or_none()
        if not server:
            return None
        if not _check_server_access(server, user_email, token_teams):
            return None

        interface = self._find_a2a_interface(db, server.id)
        if not interface:
            return None

        result: Dict[str, Any] = {
            "agent_id": server.id,
            "name": server.name,
            "endpoint_url": interface.binding,
            "agent_type": "server",
            "protocol_version": interface.version or "1.0",
            "auth_type": None,
        }
        return result

    def select_downstream_agent(self, db: Session, server_id: str) -> Optional[str]:
        """Select a downstream A2A agent for a server to delegate to.

        Uses a simple strategy: pick the first enabled agent associated with
        the server (ordered by agent name for determinism).

        Args:
            db: Database session.
            server_id: ID of the virtual server.

        Returns:
            Agent ID string, or None if no enabled agent is associated.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = A2AServerService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service.select_downstream_agent(db, "srv-id") is None
            True
        """
        query = (
            select(DbA2AAgent)
            .join(server_a2a_association, server_a2a_association.c.a2a_agent_id == DbA2AAgent.id)
            .where(
                server_a2a_association.c.server_id == server_id,
                DbA2AAgent.enabled.is_(True),
            )
            .order_by(DbA2AAgent.name)
            .limit(1)
        )
        agent = db.execute(query).scalar_one_or_none()
        return agent.id if agent else None

    def create_task_mapping(
        self,
        db: Session,
        server_id: str,
        server_task_id: str,
        agent_id: str,
        agent_task_id: str,
    ) -> Dict[str, Any]:
        """Record a server→agent task ID mapping for federation tracking.

        Args:
            db: Database session.
            server_id: ID of the virtual server.
            server_task_id: Task ID assigned at the server level.
            agent_id: ID of the downstream A2A agent.
            agent_task_id: Task ID assigned by the downstream agent.

        Returns:
            Dict representation of the created mapping record.
        """
        mapping = DbServerTaskMapping(
            id=str(uuid.uuid4()),
            server_id=server_id,
            server_task_id=server_task_id,
            agent_id=agent_id,
            agent_task_id=agent_task_id,
            status="active",
        )
        db.add(mapping)
        db.flush()
        return {
            "id": mapping.id,
            "server_id": mapping.server_id,
            "server_task_id": mapping.server_task_id,
            "agent_id": mapping.agent_id,
            "agent_task_id": mapping.agent_task_id,
            "status": mapping.status,
        }

    def resolve_task_mapping(self, db: Session, server_id: str, server_task_id: str) -> Optional[Dict[str, Any]]:
        """Look up the downstream agent task ID for a server task.

        Args:
            db: Database session.
            server_id: ID of the virtual server.
            server_task_id: Task ID assigned at the server level.

        Returns:
            Mapping dict (with agent_id and agent_task_id), or None if not found.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = A2AServerService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service.resolve_task_mapping(db, "srv-id", "task-id") is None
            True
        """
        query = select(DbServerTaskMapping).where(
            DbServerTaskMapping.server_id == server_id,
            DbServerTaskMapping.server_task_id == server_task_id,
        )
        mapping = db.execute(query).scalar_one_or_none()
        if not mapping:
            return None
        return {
            "id": mapping.id,
            "server_id": mapping.server_id,
            "server_task_id": mapping.server_task_id,
            "agent_id": mapping.agent_id,
            "agent_task_id": mapping.agent_task_id,
            "status": mapping.status,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_a2a_interface(self, db: Session, server_id: str) -> Optional[DbServerInterface]:
        """Return the first enabled ServerInterface with an A2A protocol for *server_id*.

        Matches any protocol whose lower-cased value starts with ``a2a``
        (e.g. ``a2a``, ``a2a/v1``, ``a2a-jsonrpc``).  When a server exposes
        multiple A2A interfaces, the first one (by DB insertion order) is
        returned — this avoids ``MultipleResultsFound`` when both v0.3 and
        v1 bindings exist.

        Args:
            db: Database session.
            server_id: Server primary key.

        Returns:
            Matching ServerInterface ORM instance, or None.
        """
        query = (
            select(DbServerInterface)
            .where(
                DbServerInterface.server_id == server_id,
                DbServerInterface.enabled.is_(True),
                func.lower(DbServerInterface.protocol).like("a2a%"),
            )
            .order_by(DbServerInterface.created_at.desc())
            .limit(1)
        )
        return db.execute(query).scalar_one_or_none()
