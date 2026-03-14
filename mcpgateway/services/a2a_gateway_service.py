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
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import get_for_update
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.services_auth import decode_auth

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

    def _check_agent_access(
        self,
        agent: DbA2AAgent,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> bool:
        """Check if user has access to agent based on visibility rules.

        Mirrors the access check in A2AAgentService._check_agent_access.

        Args:
            agent: The A2A agent to check access for.
            user_email: User's email for owner matching.
            token_teams: Teams from JWT. None = admin bypass, [] = public-only.

        Returns:
            True if access is allowed.
        """
        if agent.visibility == "public":
            return True

        if token_teams is None and user_email is None:
            return True

        if not user_email:
            return False

        is_public_only_token = token_teams is not None and len(token_teams) == 0
        if is_public_only_token:
            return False

        if agent.visibility == "team" and agent.team_id:
            if token_teams is not None:
                return agent.team_id in token_teams
            return False

        if agent.visibility == "private":
            if token_teams is not None and len(token_teams) > 0:
                return agent.owner_email == user_email
            return False

        return False

    def resolve_agent(
        self,
        db: Session,
        slug: str,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> Tuple[DbA2AAgent, Dict[str, str]]:
        """Resolve an A2A agent by slug with visibility checking and auth preparation.

        Follows the same lock-read-release pattern as a2a_service.invoke_agent:
        1. Lookup agent by slug
        2. Lock the row for read consistency
        3. Check visibility/team access
        4. Verify agent is enabled
        5. Decrypt auth credentials
        6. Release DB connection before HTTP calls

        Args:
            db: SQLAlchemy database session.
            slug: The agent slug to resolve.
            user_email: Email of the requesting user.
            token_teams: Teams from the JWT token.

        Returns:
            Tuple of (agent, auth_headers dict).

        Raises:
            A2AGatewayAgentNotFoundError: If agent not found or user lacks access.
            A2AGatewayAgentDisabledError: If agent is disabled.
        """
        agent_id = db.execute(select(DbA2AAgent.id).where(DbA2AAgent.slug == slug)).scalar_one_or_none()
        if not agent_id:
            raise A2AGatewayAgentNotFoundError(f"A2A agent not found: {slug}")

        agent = get_for_update(db, DbA2AAgent, agent_id)
        if not agent:
            raise A2AGatewayAgentNotFoundError(f"A2A agent not found: {slug}")

        # Return 404 (not 403) to avoid leaking existence of private agents
        if not self._check_agent_access(agent, user_email, token_teams):
            raise A2AGatewayAgentNotFoundError(f"A2A agent not found: {slug}")

        if not agent.enabled:
            raise A2AGatewayAgentDisabledError(f"A2A agent '{slug}' is disabled")

        # Decrypt auth credentials
        auth_headers = self._prepare_auth_headers(agent)

        # Extract endpoint URL (may include query param auth)
        endpoint_url = agent.endpoint_url
        if agent.auth_type == "query_param" and agent.auth_query_params:
            from mcpgateway.utils.url_auth import apply_query_param_auth

            auth_query_params_decrypted: Dict[str, str] = {}
            for param_key, encrypted_value in agent.auth_query_params.items():
                if encrypted_value:
                    try:
                        decrypted = decode_auth(encrypted_value)
                        auth_query_params_decrypted[param_key] = decrypted.get(param_key, "")
                    except Exception:
                        logger.debug(f"Failed to decrypt query param '{param_key}' for A2A gateway")
            if auth_query_params_decrypted:
                endpoint_url = apply_query_param_auth(endpoint_url, auth_query_params_decrypted)

        # Store endpoint URL on agent object for later use (avoids re-reading from DB)
        agent._gateway_endpoint_url = endpoint_url  # type: ignore[attr-defined]

        # Detach agent from session so attributes remain accessible after close
        db.expunge(agent)

        # Release DB connection before making HTTP calls
        db.commit()
        db.close()

        return agent, auth_headers

    def _prepare_auth_headers(self, agent: DbA2AAgent) -> Dict[str, str]:
        """Decrypt and prepare auth headers for downstream agent requests.

        Args:
            agent: The A2A agent with auth configuration.

        Returns:
            Dict of HTTP headers for authentication.
        """
        auth_headers: Dict[str, str] = {}
        if agent.auth_type in ("basic", "bearer", "authheaders") and agent.auth_value:
            if isinstance(agent.auth_value, str):
                try:
                    auth_headers = decode_auth(agent.auth_value)
                except Exception as e:
                    raise A2AGatewayError(f"Failed to decrypt authentication for agent '{agent.slug}': {e}")
            elif isinstance(agent.auth_value, dict):
                auth_headers = {str(k): str(v) for k, v in agent.auth_value.items()}
        return auth_headers

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
        gateway_url = f"{base_url}/a2a/v1/{agent.slug}"

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

