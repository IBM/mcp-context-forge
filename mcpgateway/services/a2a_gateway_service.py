# -*- coding: utf-8 -*-
# pylint: disable=import-outside-toplevel
"""Location: ./mcpgateway/services/a2a_gateway_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

A2A Gateway Service

Implements the native A2A protocol gateway for ContextForge.
Handles agent resolution, agent card generation, JSON-RPC dispatch,
and transparent proxying of requests to downstream A2A agents.
"""

# Standard
from typing import Any, Dict, List, Optional, Tuple

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import get_for_update
from mcpgateway.services.a2a_service import check_agent_visibility_access, prepare_agent_auth
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Supported JSON-RPC methods for the A2A protocol
A2A_JSONRPC_METHODS = frozenset({
    "message/send",
    "message/stream",
    "tasks/get",
    "tasks/cancel",
    "tasks/resubscribe",
    "tasks/pushNotificationConfig/set",
    "tasks/pushNotificationConfig/get",
    "tasks/pushNotificationConfig/list",
    "tasks/pushNotificationConfig/delete",
    "agent/getAuthenticatedExtendedCard",
})

# Methods that return SSE streaming responses
A2A_STREAMING_METHODS = frozenset({
    "message/stream",
    "tasks/resubscribe",
})

# Standard JSON-RPC 2.0 error codes
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

# A2A-specific error codes
A2A_TASK_NOT_FOUND = -32001
A2A_TASK_NOT_CANCELABLE = -32002
A2A_PUSH_NOT_SUPPORTED = -32003
A2A_UNSUPPORTED_OPERATION = -32004


class A2AGatewayError(Exception):
    """Base exception for A2A gateway errors."""

    pass


class A2AGatewayAgentNotFoundError(A2AGatewayError):
    """Raised when the requested agent is not found or inaccessible."""

    pass


class A2AGatewayAgentDisabledError(A2AGatewayError):
    """Raised when the requested agent is disabled."""

    pass


class A2AGatewayAgentIncompatibleError(A2AGatewayError):
    """Raised when the agent type is not compatible with the A2A protocol gateway.

    The A2A gateway only supports agents that speak JSON-RPC 2.0 (agent_type
    'generic' or 'jsonrpc', or endpoint URLs ending with '/').  Other agent
    types (openai, anthropic, custom) use proprietary request formats and must
    be accessed through MCP tool wrapping instead.
    """

    pass


# Agent types that speak JSON-RPC 2.0 and are compatible with the A2A gateway
A2A_COMPATIBLE_AGENT_TYPES = frozenset({"generic", "jsonrpc"})


def make_jsonrpc_error(code: int, message: str, request_id: Any = None, data: Any = None) -> Dict[str, Any]:
    """Build a JSON-RPC 2.0 error response.

    Args:
        code: JSON-RPC error code.
        message: Human-readable error message.
        request_id: The request ID from the original request (null if parse error).
        data: Optional additional error data.

    Returns:
        JSON-RPC 2.0 error response dict.
    """
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "error": error, "id": request_id}


def make_jsonrpc_response(result: Any, request_id: Any) -> Dict[str, Any]:
    """Build a JSON-RPC 2.0 success response.

    Args:
        result: The result payload.
        request_id: The request ID from the original request.

    Returns:
        JSON-RPC 2.0 success response dict.
    """
    return {"jsonrpc": "2.0", "result": result, "id": request_id}


class A2AGatewayService:
    """Service for the native A2A protocol gateway.

    Handles agent resolution (with visibility/team scoping), agent card generation,
    JSON-RPC request validation, and forwarding requests to downstream A2A agents.
    """

    def resolve_agent(
        self,
        db: Session,
        agent_id: str,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> Tuple[DbA2AAgent, Dict[str, str]]:
        """Resolve an A2A agent by ID with visibility checking and auth preparation.

        Follows the same lock-read-release pattern as a2a_service.invoke_agent:
        1. Lookup agent by ID
        2. Lock the row for read consistency
        3. Check visibility/team access (shared check_agent_visibility_access)
        4. Verify agent is enabled
        5. Decrypt auth credentials (shared prepare_agent_auth)
        6. Release DB connection before HTTP calls

        Args:
            db: SQLAlchemy database session.
            agent_id: The agent's database ID.
            user_email: Email of the requesting user.
            token_teams: Teams from the JWT token.

        Returns:
            Tuple of (agent, auth_headers dict).

        Raises:
            A2AGatewayAgentNotFoundError: If agent not found or user lacks access.
            A2AGatewayAgentDisabledError: If agent is disabled.
            A2AGatewayAgentIncompatibleError: If agent type is not JSON-RPC compatible.
        """
        agent = get_for_update(db, DbA2AAgent, agent_id)
        if not agent:
            raise A2AGatewayAgentNotFoundError(f"A2A agent not found: {agent_id}")

        # Return 404 (not 403) to avoid leaking existence of private agents
        if not check_agent_visibility_access(agent, user_email, token_teams):
            raise A2AGatewayAgentNotFoundError(f"A2A agent not found: {agent_id}")

        if not agent.enabled:
            raise A2AGatewayAgentDisabledError(f"A2A agent '{agent_id}' is disabled")

        # Validate agent type is compatible with A2A JSON-RPC gateway.
        # Only 'generic'/'jsonrpc' agents (or URLs ending with '/') speak JSON-RPC.
        # Other types (openai, anthropic, custom) use proprietary formats and
        # must be accessed through MCP tool wrapping instead.
        if agent.agent_type not in A2A_COMPATIBLE_AGENT_TYPES and not agent.endpoint_url.endswith("/"):
            raise A2AGatewayAgentIncompatibleError(
                f"Agent '{agent.name}' (type: {agent.agent_type}) is not compatible with the A2A protocol gateway. "
                f"Only 'generic' or 'jsonrpc' agent types support JSON-RPC 2.0. "
                f"Use MCP tool wrapping to interact with this agent."
            )

        # Decrypt auth credentials and prepare endpoint URL using shared function
        auth_headers, endpoint_url, _ = prepare_agent_auth(agent, error_class=A2AGatewayError)

        # Store endpoint URL on agent object for later use (avoids re-reading from DB)
        agent._gateway_endpoint_url = endpoint_url  # type: ignore[attr-defined]

        # Detach agent from session so attributes remain accessible after close
        db.expunge(agent)

        # Release DB connection before making HTTP calls
        db.commit()
        db.close()

        return agent, auth_headers

    def generate_agent_card(self, agent: DbA2AAgent, base_url: str) -> Dict[str, Any]:
        """Generate an A2A-spec compliant Agent Card for a registered agent.

        The agent card points clients to the gateway's JSON-RPC endpoint rather than
        the downstream agent, so all requests flow through the gateway pipeline.

        Args:
            agent: The A2A agent to generate a card for.
            base_url: The gateway's base URL (e.g., "https://gateway.example.com").

        Returns:
            Agent card as a dict (JSON-serializable).
        """
        from mcpgateway.config import settings

        route_prefix = settings.a2a_gateway_route_prefix.strip("/")
        gateway_url = f"{base_url}/{route_prefix}/{agent.id}"

        capabilities = agent.capabilities or {}

        card: Dict[str, Any] = {
            "name": agent.name,
            "description": agent.description or "",
            "url": gateway_url,
            "version": str(agent.protocol_version or "1.0"),
            "protocolVersion": str(agent.protocol_version or "1.0"),
            "capabilities": {
                "streaming": capabilities.get("streaming", False),
                "pushNotifications": capabilities.get("pushNotifications", capabilities.get("push_notifications", False)),
                "stateTransitionHistory": capabilities.get("stateTransitionHistory", capabilities.get("state_transition_history", False)),
            },
            "defaultInputModes": capabilities.get("defaultInputModes", capabilities.get("default_input_modes", ["text"])),
            "defaultOutputModes": capabilities.get("defaultOutputModes", capabilities.get("default_output_modes", ["text"])),
            "skills": capabilities.get("skills", []),
        }

        # Add provider info if available
        config = agent.config or {}
        if config.get("provider"):
            card["provider"] = config["provider"]

        # Add tags as skills if no skills defined
        if not card["skills"] and agent.tags:
            card["skills"] = [{"id": tag, "name": tag, "description": f"Skill: {tag}"} for tag in agent.tags]

        return card

    def validate_jsonrpc_request(self, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate a JSON-RPC 2.0 request structure.

        Args:
            body: The parsed JSON request body.

        Returns:
            None if valid, or a JSON-RPC error response dict if invalid.
        """
        if not isinstance(body, dict):
            return make_jsonrpc_error(JSONRPC_INVALID_REQUEST, "Request must be a JSON object")

        if body.get("jsonrpc") != "2.0":
            return make_jsonrpc_error(JSONRPC_INVALID_REQUEST, "Missing or invalid 'jsonrpc' field (must be '2.0')", body.get("id"))

        method = body.get("method")
        if not method or not isinstance(method, str):
            return make_jsonrpc_error(JSONRPC_INVALID_REQUEST, "Missing or invalid 'method' field", body.get("id"))

        if method not in A2A_JSONRPC_METHODS:
            return make_jsonrpc_error(JSONRPC_METHOD_NOT_FOUND, f"Unknown method: {method}", body.get("id"))

        return None

    def is_streaming_method(self, method: str) -> bool:
        """Check if a JSON-RPC method returns a streaming (SSE) response.

        Args:
            method: The JSON-RPC method name.

        Returns:
            True if the method streams SSE events.
        """
        return method in A2A_STREAMING_METHODS

