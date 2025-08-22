# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/a2a_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

A2A Agent Service

This module implements A2A (Agent-to-Agent) agent management for the MCP Gateway.
It handles agent registration, listing, retrieval, updates, activation toggling, deletion,
and interactions with A2A-compatible agents.
"""

# Standard
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

# Third-Party
import httpx
from sqlalchemy import case, delete, desc, func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import A2AAgentMetric
from mcpgateway.schemas import A2AAgentCreate, A2AAgentMetrics, A2AAgentRead, A2AAgentUpdate
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class A2AAgentError(Exception):
    """Base class for A2A agent-related errors."""


class A2AAgentNotFoundError(A2AAgentError):
    """Raised when a requested A2A agent is not found."""


class A2AAgentNameConflictError(A2AAgentError):
    """Raised when an A2A agent name conflicts with an existing one."""

    def __init__(self, name: str, is_active: bool = True, agent_id: Optional[str] = None):
        """Initialize an A2AAgentNameConflictError exception.

        Creates an exception that indicates an agent name conflict, with additional
        context about whether the conflicting agent is active and its ID if known.

        Args:
            name: The agent name that caused the conflict.
            is_active: Whether the conflicting agent is currently active.
            agent_id: The ID of the conflicting agent, if known.
        """
        self.name = name
        self.is_active = is_active
        self.agent_id = agent_id
        message = f"A2A Agent already exists with name: {name}"
        if not is_active:
            message += f" (currently inactive, ID: {agent_id})"
        super().__init__(message)


class A2AAgentService:
    """Service for managing A2A agents in the gateway.

    Provides methods to create, list, retrieve, update, toggle status, and delete agent records.
    Also supports interactions with A2A-compatible agents.
    """

    def __init__(self) -> None:
        """Initialize a new A2AAgentService instance."""
        self._initialized = False
        self._event_streams: List[AsyncGenerator[str, None]] = []

    async def initialize(self) -> None:
        """Initialize the A2A agent service."""
        if not self._initialized:
            logger.info("Initializing A2A Agent Service")
            self._initialized = True

    async def shutdown(self) -> None:
        """Shutdown the A2A agent service and cleanup resources."""
        if self._initialized:
            logger.info("Shutting down A2A Agent Service")
            self._initialized = False

    async def register_agent(
        self,
        db: Session,
        agent_data: A2AAgentCreate,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
    ) -> A2AAgentRead:
        """Register a new A2A agent.

        Args:
            db: Database session.
            agent_data: Agent creation data.
            created_by: Username who created this agent.
            created_from_ip: IP address of creator.
            created_via: Creation method.
            created_user_agent: User agent of creation request.
            import_batch_id: UUID of bulk import batch.
            federation_source: Source gateway for federated entities.

        Returns:
            The created agent data.

        Raises:
            A2AAgentNameConflictError: If an agent with the same name already exists.
        """
        # Check for existing agent with same name
        existing_query = select(DbA2AAgent).where(DbA2AAgent.name == agent_data.name)
        existing_agent = db.execute(existing_query).scalar_one_or_none()

        if existing_agent:
            raise A2AAgentNameConflictError(name=agent_data.name, is_active=existing_agent.enabled, agent_id=existing_agent.id)

        # Create new agent
        new_agent = DbA2AAgent(
            name=agent_data.name,
            description=agent_data.description,
            endpoint_url=agent_data.endpoint_url,
            agent_type=agent_data.agent_type,
            protocol_version=agent_data.protocol_version,
            capabilities=agent_data.capabilities,
            config=agent_data.config,
            auth_type=agent_data.auth_type,
            auth_value=agent_data.auth_value,  # This should be encrypted in practice
            tags=agent_data.tags,
            created_by=created_by,
            created_from_ip=created_from_ip,
            created_via=created_via,
            created_user_agent=created_user_agent,
            import_batch_id=import_batch_id,
            federation_source=federation_source,
        )

        db.add(new_agent)
        db.commit()
        db.refresh(new_agent)

        logger.info(f"Registered new A2A agent: {new_agent.name} (ID: {new_agent.id})")
        return self._db_to_schema(new_agent)

    async def list_agents(self, db: Session, cursor: Optional[str] = None, include_inactive: bool = False, tags: Optional[List[str]] = None) -> List[A2AAgentRead]:  # pylint: disable=unused-argument
        """List A2A agents with optional filtering.

        Args:
            db: Database session.
            cursor: Pagination cursor (not implemented yet).
            include_inactive: Whether to include inactive agents.
            tags: List of tags to filter by.

        Returns:
            List of agent data.
        """
        query = select(DbA2AAgent)

        if not include_inactive:
            query = query.where(DbA2AAgent.enabled.is_(True))

        if tags:
            # Filter by tags - agent must have at least one of the specified tags
            tag_conditions = []
            for tag in tags:
                tag_conditions.append(func.json_extract(DbA2AAgent.tags, "$").contains(tag))

            if tag_conditions:
                query = query.where(func.or_(*tag_conditions))

        query = query.order_by(desc(DbA2AAgent.created_at))

        agents = db.execute(query).scalars().all()
        return [self._db_to_schema(agent) for agent in agents]

    async def get_agent(self, db: Session, agent_id: str) -> A2AAgentRead:
        """Retrieve an A2A agent by ID.

        Args:
            db: Database session.
            agent_id: Agent ID.

        Returns:
            Agent data.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
        """
        query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
        agent = db.execute(query).scalar_one_or_none()

        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        return self._db_to_schema(agent)

    async def get_agent_by_name(self, db: Session, agent_name: str) -> A2AAgentRead:
        """Retrieve an A2A agent by name.

        Args:
            db: Database session.
            agent_name: Agent name.

        Returns:
            Agent data.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
        """
        query = select(DbA2AAgent).where(DbA2AAgent.name == agent_name)
        agent = db.execute(query).scalar_one_or_none()

        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with name: {agent_name}")

        return self._db_to_schema(agent)

    async def update_agent(
        self,
        db: Session,
        agent_id: str,
        agent_data: A2AAgentUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
    ) -> A2AAgentRead:
        """Update an existing A2A agent.

        Args:
            db: Database session.
            agent_id: Agent ID.
            agent_data: Agent update data.
            modified_by: Username who modified this agent.
            modified_from_ip: IP address of modifier.
            modified_via: Modification method.
            modified_user_agent: User agent of modification request.

        Returns:
            Updated agent data.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
            A2AAgentNameConflictError: If name conflicts with another agent.
        """
        query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
        agent = db.execute(query).scalar_one_or_none()

        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        # Check for name conflict if name is being updated
        if agent_data.name and agent_data.name != agent.name:
            existing_query = select(DbA2AAgent).where(DbA2AAgent.name == agent_data.name, DbA2AAgent.id != agent_id)
            existing_agent = db.execute(existing_query).scalar_one_or_none()

            if existing_agent:
                raise A2AAgentNameConflictError(name=agent_data.name, is_active=existing_agent.enabled, agent_id=existing_agent.id)

        # Update fields
        update_data = agent_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(agent, field):
                setattr(agent, field, value)

        # Update metadata
        if modified_by:
            agent.modified_by = modified_by
        if modified_from_ip:
            agent.modified_from_ip = modified_from_ip
        if modified_via:
            agent.modified_via = modified_via
        if modified_user_agent:
            agent.modified_user_agent = modified_user_agent

        agent.version += 1

        db.commit()
        db.refresh(agent)

        logger.info(f"Updated A2A agent: {agent.name} (ID: {agent.id})")
        return self._db_to_schema(agent)

    async def toggle_agent_status(self, db: Session, agent_id: str, activate: bool, reachable: Optional[bool] = None) -> A2AAgentRead:
        """Toggle the activation status of an A2A agent.

        Args:
            db: Database session.
            agent_id: Agent ID.
            activate: True to activate, False to deactivate.
            reachable: Optional reachability status.

        Returns:
            Updated agent data.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
        """
        query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
        agent = db.execute(query).scalar_one_or_none()

        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        agent.enabled = activate
        if reachable is not None:
            agent.reachable = reachable

        db.commit()
        db.refresh(agent)

        status = "activated" if activate else "deactivated"
        logger.info(f"A2A agent {status}: {agent.name} (ID: {agent.id})")
        return self._db_to_schema(agent)

    async def delete_agent(self, db: Session, agent_id: str) -> None:
        """Delete an A2A agent.

        Args:
            db: Database session.
            agent_id: Agent ID.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
        """
        query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
        agent = db.execute(query).scalar_one_or_none()

        if not agent:
            raise A2AAgentNotFoundError(f"A2A Agent not found with ID: {agent_id}")

        agent_name = agent.name
        db.delete(agent)
        db.commit()

        logger.info(f"Deleted A2A agent: {agent_name} (ID: {agent_id})")

    async def invoke_agent(self, db: Session, agent_name: str, parameters: Dict[str, Any], interaction_type: str = "query") -> Dict[str, Any]:
        """Invoke an A2A agent.

        Args:
            db: Database session.
            agent_name: Name of the agent to invoke.
            parameters: Parameters for the interaction.
            interaction_type: Type of interaction.

        Returns:
            Agent response.

        Raises:
            A2AAgentNotFoundError: If the agent is not found.
            A2AAgentError: If the agent is disabled or invocation fails.
        """
        agent = await self.get_agent_by_name(db, agent_name)

        if not agent.enabled:
            raise A2AAgentError(f"A2A Agent '{agent_name}' is disabled")

        start_time = datetime.now(timezone.utc)
        success = False
        error_message = None
        response = None

        try:
            # Prepare the request to the A2A agent
            # Format request based on agent type and endpoint
            if agent.agent_type in ["generic", "jsonrpc"] or agent.endpoint_url.endswith("/"):
                # Use JSONRPC format for agents that expect it
                request_data = {"jsonrpc": "2.0", "method": parameters.get("method", "message/send"), "params": parameters.get("params", parameters), "id": 1}
            else:
                # Use custom A2A format
                request_data = {"interaction_type": interaction_type, "parameters": parameters, "protocol_version": agent.protocol_version}

            # Make HTTP request to the agent endpoint
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Content-Type": "application/json"}

                # Add authentication if configured
                if agent.auth_type == "api_key" and agent.auth_value:
                    headers["Authorization"] = f"Bearer {agent.auth_value}"
                elif agent.auth_type == "bearer" and agent.auth_value:
                    headers["Authorization"] = f"Bearer {agent.auth_value}"

                http_response = await client.post(agent.endpoint_url, json=request_data, headers=headers)

                if http_response.status_code == 200:
                    response = http_response.json()
                    success = True
                else:
                    error_message = f"HTTP {http_response.status_code}: {http_response.text}"
                    raise A2AAgentError(error_message)

        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to invoke A2A agent '{agent_name}': {error_message}")
            raise A2AAgentError(f"Failed to invoke A2A agent: {error_message}")

        finally:
            # Record metrics
            end_time = datetime.now(timezone.utc)
            response_time = (end_time - start_time).total_seconds()

            metric = A2AAgentMetric(a2a_agent_id=agent.id, response_time=response_time, is_success=success, error_message=error_message, interaction_type=interaction_type)
            db.add(metric)

            # Update last interaction timestamp
            query = select(DbA2AAgent).where(DbA2AAgent.id == agent.id)
            db_agent = db.execute(query).scalar_one()
            db_agent.last_interaction = end_time

            db.commit()

        return response or {"error": error_message}

    async def aggregate_metrics(self, db: Session) -> Dict[str, Any]:
        """Aggregate metrics for all A2A agents.

        Args:
            db: Database session.

        Returns:
            Aggregated metrics.
        """
        # Get total number of agents
        total_agents = db.execute(select(func.count(DbA2AAgent.id))).scalar()  # pylint: disable=not-callable
        active_agents = db.execute(select(func.count(DbA2AAgent.id)).where(DbA2AAgent.enabled.is_(True))).scalar()  # pylint: disable=not-callable

        # Get overall metrics
        metrics_query = select(
            func.count(A2AAgentMetric.id).label("total_interactions"),  # pylint: disable=not-callable
            func.sum(case((A2AAgentMetric.is_success.is_(True), 1), else_=0)).label("successful_interactions"),
            func.avg(A2AAgentMetric.response_time).label("avg_response_time"),
            func.min(A2AAgentMetric.response_time).label("min_response_time"),
            func.max(A2AAgentMetric.response_time).label("max_response_time"),
        )

        metrics_result = db.execute(metrics_query).first()

        total_interactions = metrics_result.total_interactions or 0
        successful_interactions = metrics_result.successful_interactions or 0
        failed_interactions = total_interactions - successful_interactions

        return {
            "total_agents": total_agents,
            "active_agents": active_agents,
            "total_interactions": total_interactions,
            "successful_interactions": successful_interactions,
            "failed_interactions": failed_interactions,
            "success_rate": (successful_interactions / total_interactions * 100) if total_interactions > 0 else 0.0,
            "avg_response_time": float(metrics_result.avg_response_time or 0.0),
            "min_response_time": float(metrics_result.min_response_time or 0.0),
            "max_response_time": float(metrics_result.max_response_time or 0.0),
        }

    async def reset_metrics(self, db: Session, agent_id: Optional[str] = None) -> None:
        """Reset metrics for agents.

        Args:
            db: Database session.
            agent_id: Optional agent ID to reset metrics for specific agent.
        """
        if agent_id:
            # Reset metrics for specific agent
            delete_query = delete(A2AAgentMetric).where(A2AAgentMetric.a2a_agent_id == agent_id)
        else:
            # Reset all metrics
            delete_query = delete(A2AAgentMetric)

        db.execute(delete_query)
        db.commit()

        logger.info("Reset A2A agent metrics" + (f" for agent {agent_id}" if agent_id else ""))

    def _db_to_schema(self, db_agent: DbA2AAgent) -> A2AAgentRead:
        """Convert database model to schema.

        Args:
            db_agent: Database agent model.

        Returns:
            Agent read schema.
        """
        # Calculate metrics
        total_executions = len(db_agent.metrics)
        successful_executions = sum(1 for m in db_agent.metrics if m.is_success)
        failed_executions = total_executions - successful_executions
        failure_rate = (failed_executions / total_executions) * 100 if total_executions > 0 else 0.0

        min_response_time = None
        max_response_time = None
        avg_response_time = None
        last_execution_time = None

        if db_agent.metrics:
            response_times = [m.response_time for m in db_agent.metrics]
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            avg_response_time = sum(response_times) / len(response_times)
            last_execution_time = max(m.timestamp for m in db_agent.metrics)

        metrics = A2AAgentMetrics(
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            failure_rate=failure_rate,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            avg_response_time=avg_response_time,
            last_execution_time=last_execution_time,
        )

        return A2AAgentRead(
            id=db_agent.id,
            name=db_agent.name,
            slug=db_agent.slug,
            description=db_agent.description,
            endpoint_url=db_agent.endpoint_url,
            agent_type=db_agent.agent_type,
            protocol_version=db_agent.protocol_version,
            capabilities=db_agent.capabilities,
            config=db_agent.config,
            auth_type=db_agent.auth_type,
            enabled=db_agent.enabled,
            reachable=db_agent.reachable,
            created_at=db_agent.created_at,
            updated_at=db_agent.updated_at,
            last_interaction=db_agent.last_interaction,
            tags=db_agent.tags,
            metrics=metrics,
            created_by=db_agent.created_by,
            created_from_ip=db_agent.created_from_ip,
            created_via=db_agent.created_via,
            created_user_agent=db_agent.created_user_agent,
            modified_by=db_agent.modified_by,
            modified_from_ip=db_agent.modified_from_ip,
            modified_via=db_agent.modified_via,
            modified_user_agent=db_agent.modified_user_agent,
            import_batch_id=db_agent.import_batch_id,
            federation_source=db_agent.federation_source,
            version=db_agent.version,
        )
