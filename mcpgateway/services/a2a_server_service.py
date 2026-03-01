# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A2A Server Service — makes virtual servers act as A2A agents.

When a virtual server has A2A interfaces configured (``ServerInterface`` rows
with ``protocol='a2a'``), this service generates an ``AgentCard`` from the
server's metadata and associated A2A agents, and proxies A2A requests
(``SendMessage``, ``GetTask``, ``CancelTask``, etc.) to the appropriate
downstream agent.

The service does **not** duplicate RBAC or visibility checks — those are
handled by the router layer and the downstream ``A2AAgentService``.
"""

# Standard
import logging
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

# Third-Party
from sqlalchemy.orm import Session, selectinload

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Server as DbServer
from mcpgateway.db import ServerInterface as DbServerInterface
from mcpgateway.db import ServerTaskMapping
from mcpgateway.services.a2a_errors import A2AAgentError, A2AAgentNotFoundError

logger = logging.getLogger(__name__)


class A2AServerNotFoundError(A2AAgentNotFoundError):
    """Raised when a server does not exist or has no A2A interfaces."""


class A2AServerService:
    """Service for exposing virtual servers as A2A agents.

    Generates agent cards, routes requests to associated agents,
    and manages server-level task mappings.
    """

    def __init__(self, a2a_service: Any = None) -> None:
        self._a2a_service = a2a_service

    @property
    def a2a_service(self) -> Any:
        """Lazily resolve the A2A agent service."""
        if self._a2a_service is None:
            # First-Party
            from mcpgateway.services.a2a_service import A2AAgentService  # pylint: disable=import-outside-toplevel

            self._a2a_service = A2AAgentService()
        return self._a2a_service

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_server_with_a2a(self, db: Session, server_id: str) -> DbServer:
        """Load a server with its A2A interfaces and agents eagerly loaded.

        Raises:
            A2AServerNotFoundError: If the server doesn't exist or has no A2A interfaces.
        """
        server = (
            db.query(DbServer)
            .options(selectinload(DbServer.a2a_agents), selectinload(DbServer.interfaces))
            .filter(DbServer.id == server_id)
            .first()
        )
        if server is None:
            raise A2AServerNotFoundError(f"Server '{server_id}' not found")

        a2a_interfaces = [i for i in (server.interfaces or []) if i.protocol == "a2a" and i.enabled]
        if not a2a_interfaces:
            raise A2AServerNotFoundError(f"Server '{server_id}' has no enabled A2A interfaces")

        return server

    def _get_a2a_interface(self, server: DbServer) -> DbServerInterface:
        """Return the first enabled A2A interface for the server."""
        for iface in (server.interfaces or []):
            if iface.protocol == "a2a" and iface.enabled:
                return iface
        raise A2AServerNotFoundError(f"Server '{server.id}' has no enabled A2A interfaces")

    def _resolve_tenant(
        self,
        server: DbServer,
        a2a_interface: DbServerInterface,
        agent: Optional[DbA2AAgent] = None,
        caller_tenant: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve effective tenant using precedence rules.

        Precedence (highest wins):
        1. Caller-supplied tenant (only if allow_caller_tenant_override is True)
        2. Per-agent tenant override
        3. Interface-level tenant
        4. None (no tenant)
        """
        config = a2a_interface.config or {}

        # Caller override (gated).
        if caller_tenant and config.get("allow_caller_tenant_override", False):
            allowed = config.get("allowed_tenants")
            if allowed is None or caller_tenant in allowed:
                return caller_tenant
            logger.warning(
                "Caller tenant '%s' not in allowed_tenants for server '%s'",
                caller_tenant,
                server.id,
            )

        # Per-agent override.
        if agent and getattr(agent, "tenant", None):
            return agent.tenant

        # Interface default.
        return a2a_interface.tenant

    def _pick_agent(self, server: DbServer, skill_id: Optional[str] = None) -> DbA2AAgent:
        """Select which associated agent should handle a request.

        Currently uses the first active agent. Future: skill-based routing.

        Raises:
            A2AAgentError: If the server has no associated active agents.
        """
        active_agents = [a for a in (server.a2a_agents or []) if getattr(a, "enabled", True)]
        if not active_agents:
            raise A2AAgentError(f"Server '{server.id}' has no active associated A2A agents")

        if skill_id:
            for agent in active_agents:
                caps = getattr(agent, "capabilities", {}) or {}
                skills = caps.get("skills", [])
                if any(s.get("id") == skill_id for s in skills if isinstance(s, dict)):
                    return agent

        return active_agents[0]

    # ------------------------------------------------------------------
    # Agent Card Generation
    # ------------------------------------------------------------------

    def get_agent_card(
        self,
        db: Session,
        server_id: str,
        base_url: str = "",
    ) -> Dict[str, Any]:
        """Generate an AgentCard for this server's A2A interface.

        Aggregates capabilities and skills from all associated A2A agents
        into a single card. Server-level overrides take precedence.

        Args:
            db: Database session.
            server_id: Server ID.
            base_url: Base URL for constructing interface URLs.

        Returns:
            Agent card dict conforming to A2A v1.0 AgentCard schema.
        """
        server = self._get_server_with_a2a(db, server_id)
        a2a_iface = self._get_a2a_interface(server)
        config = a2a_iface.config or {}

        # Aggregate skills from all associated agents.
        skills: List[Dict[str, Any]] = []
        seen_skill_ids: set = set()
        all_caps: Dict[str, Any] = {}

        for agent in (server.a2a_agents or []):
            if not getattr(agent, "enabled", True):
                continue
            agent_caps = getattr(agent, "capabilities", {}) or {}
            # Merge capabilities (OR for additive, AND for restrictive).
            for key, value in agent_caps.items():
                if key == "skills":
                    for skill in (value or []):
                        sid = skill.get("id", "")
                        if sid and sid not in seen_skill_ids:
                            seen_skill_ids.add(sid)
                            skills.append(skill)
                elif key == "streaming":
                    # AND: only True if all agents support it.
                    all_caps[key] = all_caps.get(key, True) and bool(value)
                elif key == "pushNotifications":
                    # OR: True if any agent supports it.
                    all_caps[key] = all_caps.get(key, False) or bool(value)
                else:
                    all_caps.setdefault(key, value)

        # Build supported_interfaces.
        interface_url = f"{base_url}/servers/{server_id}/a2a" if base_url else f"/servers/{server_id}/a2a"
        supported_interfaces = [
            {
                "url": interface_url,
                "protocolBinding": a2a_iface.binding,
                "protocolVersion": a2a_iface.version,
                **({"tenant": a2a_iface.tenant} if a2a_iface.tenant else {}),
            }
        ]

        # Base agent card.
        card: Dict[str, Any] = {
            "name": server.name,
            "description": server.description or "",
            "supportedInterfaces": supported_interfaces,
            "capabilities": {**all_caps, "skills": skills} if skills else all_caps,
        }

        if server.icon:
            card["iconUrl"] = server.icon

        # Apply overrides from interface config.
        agent_card_override = config.get("agent_card_override")
        if isinstance(agent_card_override, dict):
            for key, value in agent_card_override.items():
                if value is not None:
                    card[key] = value

        return card

    # ------------------------------------------------------------------
    # A2A Protocol Operations
    # ------------------------------------------------------------------

    async def send_message(
        self,
        db: Session,
        server_id: str,
        message_params: Dict[str, Any],
        user_id: str,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Route a SendMessage request to an associated agent.

        Creates a server-level task mapping so callers use server task IDs
        rather than agent task IDs.
        """
        server = self._get_server_with_a2a(db, server_id)
        agent = self._pick_agent(server)

        result = await self.a2a_service.send_message(
            db=db,
            agent_name=agent.name,
            message_params=message_params,
            user_id=user_id,
            user_email=user_email,
            token_teams=token_teams,
        )

        # Create task mapping if the result contains a task ID.
        agent_task_id = None
        if isinstance(result, dict):
            task = result.get("result", {})
            if isinstance(task, dict):
                agent_task_id = task.get("id") or task.get("taskId")

        if agent_task_id:
            server_task_id = uuid.uuid4().hex
            mapping = ServerTaskMapping(
                server_id=server_id,
                server_task_id=server_task_id,
                agent_name=agent.name,
                agent_task_id=str(agent_task_id),
                status="active",
            )
            db.add(mapping)
            db.commit()

            # Replace agent task ID with server task ID in result.
            if isinstance(result.get("result"), dict):
                result["result"]["id"] = server_task_id

        return result

    async def stream_message(
        self,
        db: Session,
        server_id: str,
        message_params: Dict[str, Any],
        user_id: str,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> AsyncIterator[str]:
        """Route a streaming SendMessage request to an associated agent."""
        server = self._get_server_with_a2a(db, server_id)
        agent = self._pick_agent(server)

        return await self.a2a_service.stream_message(
            db=db,
            agent_name=agent.name,
            message_params=message_params,
            user_id=user_id,
            user_email=user_email,
            token_teams=token_teams,
        )

    async def get_task(
        self,
        db: Session,
        server_id: str,
        task_id: str,
        user_id: str,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Retrieve a task by server-level task ID, resolving via mapping."""
        mapping = (
            db.query(ServerTaskMapping)
            .filter(ServerTaskMapping.server_id == server_id, ServerTaskMapping.server_task_id == task_id)
            .first()
        )
        if mapping is None:
            raise A2AAgentNotFoundError(f"Task '{task_id}' not found on server '{server_id}'")

        result = await self.a2a_service.get_task(
            db=db,
            agent_name=mapping.agent_name,
            task_id=mapping.agent_task_id,
            user_id=user_id,
            user_email=user_email,
            token_teams=token_teams,
        )

        # Replace agent task ID with server task ID in response.
        if isinstance(result, dict) and isinstance(result.get("result"), dict):
            result["result"]["id"] = task_id

        return result

    async def cancel_task(
        self,
        db: Session,
        server_id: str,
        task_id: str,
        user_id: str,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Cancel a task by server-level task ID."""
        mapping = (
            db.query(ServerTaskMapping)
            .filter(ServerTaskMapping.server_id == server_id, ServerTaskMapping.server_task_id == task_id)
            .first()
        )
        if mapping is None:
            raise A2AAgentNotFoundError(f"Task '{task_id}' not found on server '{server_id}'")

        result = await self.a2a_service.cancel_task(
            db=db,
            agent_name=mapping.agent_name,
            task_id=mapping.agent_task_id,
            user_id=user_id,
            user_email=user_email,
            token_teams=token_teams,
        )

        if isinstance(result, dict) and isinstance(result.get("result"), dict):
            result["result"]["id"] = task_id

        return result

    async def list_tasks(
        self,
        db: Session,
        server_id: str,
        params: Dict[str, Any],
        user_id: str,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """List tasks across all agents associated with this server."""
        server = self._get_server_with_a2a(db, server_id)

        # Aggregate tasks from all active agents.
        all_tasks: List[Dict[str, Any]] = []
        for agent in (server.a2a_agents or []):
            if not getattr(agent, "enabled", True):
                continue
            try:
                result = await self.a2a_service.list_tasks(
                    db=db,
                    agent_name=agent.name,
                    params=params,
                    user_id=user_id,
                    user_email=user_email,
                    token_teams=token_teams,
                )
                if isinstance(result, dict):
                    tasks = result.get("result", {})
                    if isinstance(tasks, list):
                        all_tasks.extend(tasks)
                    elif isinstance(tasks, dict) and "tasks" in tasks:
                        all_tasks.extend(tasks["tasks"])
            except A2AAgentError:
                logger.debug("Failed to list tasks from agent '%s' on server '%s'", agent.name, server_id)

        return {"result": all_tasks}

    async def invoke_agent(
        self,
        db: Session,
        server_id: str,
        parameters: Dict[str, Any],
        interaction_type: str = "query",
        user_id: str = "",
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generic invoke that routes to an associated agent."""
        server = self._get_server_with_a2a(db, server_id)
        agent = self._pick_agent(server)

        return await self.a2a_service.invoke_agent(
            db=db,
            agent_name=agent.name,
            parameters=parameters,
            interaction_type=interaction_type,
            user_id=user_id,
            user_email=user_email,
            token_teams=token_teams,
        )

    # ------------------------------------------------------------------
    # Server A2A interface queries
    # ------------------------------------------------------------------

    def has_a2a_interface(self, db: Session, server_id: str) -> bool:
        """Check whether a server has any enabled A2A interfaces."""
        count = (
            db.query(DbServerInterface)
            .filter(
                DbServerInterface.server_id == server_id,
                DbServerInterface.protocol == "a2a",
                DbServerInterface.enabled.is_(True),
            )
            .count()
        )
        return count > 0

    def list_a2a_servers(self, db: Session) -> List[Dict[str, Any]]:
        """List all servers that have at least one enabled A2A interface.

        Returns a minimal list of server IDs and names for discovery.
        """
        servers = (
            db.query(DbServer)
            .join(DbServerInterface, DbServer.id == DbServerInterface.server_id)
            .filter(DbServerInterface.protocol == "a2a", DbServerInterface.enabled.is_(True), DbServer.enabled.is_(True))
            .options(selectinload(DbServer.interfaces))
            .distinct()
            .all()
        )
        return [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description or "",
                "a2a_interfaces": [
                    {
                        "binding": i.binding,
                        "version": i.version,
                        "tenant": i.tenant,
                    }
                    for i in (s.interfaces or [])
                    if i.protocol == "a2a" and i.enabled
                ],
            }
            for s in servers
        ]
