# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/token_scoping.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Token Scoping Middleware.
This middleware enforces token scoping restrictions at the API level,
including server_id restrictions, IP restrictions, permission checks,
and time-based restrictions.
"""

# Standard
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import auto, Enum
from functools import lru_cache
import ipaddress
import re
from typing import Any, List, Optional, Pattern, Tuple

# Third-Party
from fastapi import HTTPException, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import normalize_token_teams, resolve_session_teams, validate_token_team_membership
from mcpgateway.auth_context import get_jwt_user_email_from_payload, resolve_jwt_user_email_from_payload
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent, Gateway, Permissions, Prompt, Resource, Server, Tool
from mcpgateway.middleware.rbac import _ACCESS_DENIED_MSG, _ALL_PERMISSIONS_SCOPE, token_scope_grants
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.paths import replace_api_path_alias
from mcpgateway.utils.verify_credentials import (
    ConfigurableHTTPBearer,
    get_request_auth_token,
    verify_jwt_token_cached,
)

# Security scheme
bearer_scheme = ConfigurableHTTPBearer(auto_error=False)

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# ============================================================================
# Precompiled regex patterns (compiled once at module load for performance)
# ============================================================================

# Server path extraction patterns
_SERVER_PATH_PATTERNS: List[Pattern[str]] = [
    re.compile(r"^/servers/([^/]+)(?:$|/)"),
    re.compile(r"^/sse/([^/?]+)(?:$|\?)"),
    re.compile(r"^/ws/([^/?]+)(?:$|\?)"),
]

_A2A_AGENT_ID = r"(?:[a-f0-9]{32}|[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12})"

# Resource ID extraction patterns (IDs are UUID hex strings)
_RESOURCE_PATTERNS: List[Tuple[Pattern[str], str]] = [
    (re.compile(r"/servers/?([a-f0-9\-]+)"), "server"),
    (re.compile(r"/tools/?([a-f0-9\-]+)"), "tool"),
    (re.compile(r"/resources/?([a-f0-9\-]+)"), "resource"),
    (re.compile(r"/prompts/?([a-f0-9\-]+)"), "prompt"),
    (re.compile(r"/gateways/?([a-f0-9\-]+)"), "gateway"),
    (re.compile(rf"/a2a/({_A2A_AGENT_ID})(?:/|$)"), "a2a_agent"),
]


class ResourceOwnershipResult(Enum):
    """Outcome from a token-scoped resource ownership lookup."""

    ALLOWED = auto()
    NOT_FOUND = auto()
    DENIED = auto()


@dataclass(frozen=True)
class _ResourceOwnershipSpec:
    """Per-resource-type inputs to the token-scoped ownership check.

    Attributes:
        model: ORM model holding the resource rows.
        label: Lowercase name used in log messages.
        title: Sentence-initial name used in log messages.
        missing_result: Result returned when the resource row does not exist.
        private_visibilities: Visibility values treated as owner-only.
    """

    model: Any
    label: str
    title: str
    missing_result: ResourceOwnershipResult
    private_visibilities: Tuple[str, ...] = ("private", "user")


_RESOURCE_OWNERSHIP_SPECS = {
    "server": _ResourceOwnershipSpec(Server, "server", "Server", ResourceOwnershipResult.NOT_FOUND, private_visibilities=("private",)),
    "tool": _ResourceOwnershipSpec(Tool, "tool", "Tool", ResourceOwnershipResult.DENIED),
    "resource": _ResourceOwnershipSpec(Resource, "resource", "Resource", ResourceOwnershipResult.DENIED),
    "prompt": _ResourceOwnershipSpec(Prompt, "prompt", "Prompt", ResourceOwnershipResult.DENIED),
    "gateway": _ResourceOwnershipSpec(Gateway, "gateway", "Gateway", ResourceOwnershipResult.NOT_FOUND),
    "a2a_agent": _ResourceOwnershipSpec(A2AAgent, "A2A agent", "A2A agent", ResourceOwnershipResult.NOT_FOUND),
}


# A2A routes that change an agent. Read, invoke, test and task routes enforce visibility in the
# service and return 404 for a hidden agent, so the middleware must not answer 403 before them.
_A2A_MUTATION_PATTERN = re.compile(rf"^/(?:admin/)?a2a/{_A2A_AGENT_ID}(?:/(?:state|toggle|edit|delete))?/?$")
_A2A_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_TARGETED_MISSING_DELETE_PATTERN = re.compile(r"^/(?:servers|gateways)/(?:[a-f0-9]{32}|[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12})/?$")

# Permission map with precompiled patterns
# Maps (HTTP method, path pattern) to required permission
_PERMISSION_PATTERNS: List[Tuple[str, Pattern[str], str]] = [
    # Plugin discovery permissions
    ("GET", re.compile(r"^/plugins(?:$|/)"), Permissions.PLUGINS_READ),
    # Tools permissions
    ("GET", re.compile(r"^/tools(?:$|/)"), Permissions.TOOLS_READ),
    ("POST", re.compile(r"^/tools/?$"), Permissions.TOOLS_CREATE),  # Only exact /tools or /tools/
    ("POST", re.compile(r"^/tools/preview(?:$|/)"), Permissions.TOOLS_PREVIEW),  # Must precede the /tools/[^/]+/ catch-all below (#5629)
    # Tool plugin bindings use tools.manage_plugins (see tool_plugin_bindings router),
    # not tools.update / tools.delete from the catch-alls below (#6701).
    ("POST", re.compile(r"^/tools/plugin_bindings(?:$|/)"), Permissions.TOOLS_MANAGE_PLUGINS),
    ("DELETE", re.compile(r"^/tools/plugin_bindings(?:$|/)"), Permissions.TOOLS_MANAGE_PLUGINS),
    ("POST", re.compile(r"^/tools/[^/]+/"), Permissions.TOOLS_UPDATE),  # POST to sub-resources (state, toggle)
    ("PUT", re.compile(r"^/tools/[^/]+(?:$|/)"), Permissions.TOOLS_UPDATE),
    ("DELETE", re.compile(r"^/tools/[^/]+(?:$|/)"), Permissions.TOOLS_DELETE),
    ("GET", re.compile(r"^/servers/[^/]+/tools(?:$|/)"), Permissions.TOOLS_READ),
    ("POST", re.compile(r"^/servers/[^/]+/tools/[^/]+/call(?:$|/)"), Permissions.TOOLS_EXECUTE),
    # Completion endpoint (protocol_router) is guarded by @require_permission("tools.read") (#6760).
    ("POST", re.compile(r"^/protocol/completion/complete(?:$|/)"), Permissions.TOOLS_READ),
    # JSON-RPC endpoint — multiplexes tools/call, resources/list, initialize, etc.
    # Fine-grained per-method RBAC is enforced downstream by _ensure_rpc_permission();
    # the middleware only gates transport-level access via servers.use.
    ("POST", re.compile(r"^/rpc(?:$|/)"), Permissions.SERVERS_USE),
    # SSE transport — like /rpc and /mcp, this is a transport-level endpoint;
    # the handler's own @require_permission enforces fine-grained RBAC.
    ("GET", re.compile(r"^/sse(?:$|/)"), Permissions.SERVERS_USE),
    # Streamable HTTP MCP transport (POST=send, GET=SSE stream, DELETE=session termination)
    ("POST", re.compile(r"^/mcp(?:$|/)"), Permissions.SERVERS_USE),
    ("GET", re.compile(r"^/mcp(?:$|/)"), Permissions.SERVERS_USE),
    ("DELETE", re.compile(r"^/mcp(?:$|/)"), Permissions.SERVERS_USE),
    # Resources permissions
    ("GET", re.compile(r"^/resources(?:$|/)"), Permissions.RESOURCES_READ),
    ("POST", re.compile(r"^/resources/?$"), Permissions.RESOURCES_CREATE),  # Only exact /resources or /resources/
    ("POST", re.compile(r"^/resources/subscribe(?:$|/)"), Permissions.RESOURCES_READ),  # SSE subscription
    ("POST", re.compile(r"^/resources/[^/]+/"), Permissions.RESOURCES_UPDATE),  # POST to sub-resources (state, toggle)
    ("PUT", re.compile(r"^/resources/[^/]+(?:$|/)"), Permissions.RESOURCES_UPDATE),
    ("DELETE", re.compile(r"^/resources/[^/]+(?:$|/)"), Permissions.RESOURCES_DELETE),
    ("GET", re.compile(r"^/servers/[^/]+/resources(?:$|/)"), Permissions.RESOURCES_READ),
    # Prompts permissions
    ("GET", re.compile(r"^/prompts(?:$|/)"), Permissions.PROMPTS_READ),
    ("POST", re.compile(r"^/prompts/?$"), Permissions.PROMPTS_CREATE),  # Only exact /prompts or /prompts/
    ("POST", re.compile(r"^/prompts/[^/]+/"), Permissions.PROMPTS_UPDATE),  # POST to sub-resources (state, toggle)
    ("POST", re.compile(r"^/prompts/[^/]+$"), Permissions.PROMPTS_READ),  # MCP spec prompt retrieval (POST /prompts/{id})
    ("PUT", re.compile(r"^/prompts/[^/]+(?:$|/)"), Permissions.PROMPTS_UPDATE),
    ("DELETE", re.compile(r"^/prompts/[^/]+(?:$|/)"), Permissions.PROMPTS_DELETE),
    # Server management permissions
    ("GET", re.compile(r"^/servers/[^/]+/sse(?:$|/)"), Permissions.SERVERS_USE),  # Server SSE access endpoint
    ("GET", re.compile(r"^/servers(?:$|/)"), Permissions.SERVERS_READ),
    ("POST", re.compile(r"^/servers/?$"), Permissions.SERVERS_CREATE),  # Only exact /servers or /servers/
    # Handshake probe against the virtual server's own MCP endpoint — read-only, symmetric
    # with GATEWAYS_READ on the gateway test-handshake endpoint. Must precede the generic
    # state|toggle sub-resource rule below.
    ("POST", re.compile(r"^/servers/[^/]+/test-handshake(?:$|/)"), Permissions.SERVERS_READ),
    ("POST", re.compile(r"^/servers/[^/]+/(?:state|toggle)(?:$|/)"), Permissions.SERVERS_UPDATE),  # Server management sub-resources
    ("POST", re.compile(r"^/servers/[^/]+/oauth/approve/?$"), Permissions.SERVERS_UPDATE),
    ("POST", re.compile(r"^/servers/[^/]+/message(?:$|/)"), Permissions.SERVERS_USE),  # Server message access endpoint
    ("POST", re.compile(r"^/servers/[^/]+/mcp(?:$|/)"), Permissions.SERVERS_USE),  # Server MCP access endpoint
    ("PUT", re.compile(r"^/servers/[^/]+(?:$|/)"), Permissions.SERVERS_UPDATE),
    ("DELETE", re.compile(r"^/servers/[^/]+(?:$|/)"), Permissions.SERVERS_DELETE),
    # Gateway permissions
    # Connectivity test and handshake probe exposed through the /v1/mcp-servers product alias.
    # They must precede the generic POST sub-resource rule below.
    ("POST", re.compile(r"^/gateways/test(?:$|/)"), Permissions.GATEWAYS_READ),
    ("POST", re.compile(r"^/gateways/test-handshake(?:$|/)"), Permissions.GATEWAYS_READ),
    ("GET", re.compile(r"^/gateways(?:$|/)"), Permissions.GATEWAYS_READ),
    ("POST", re.compile(r"^/gateways/?$"), Permissions.GATEWAYS_CREATE),  # Only exact /gateways or /gateways/
    ("POST", re.compile(r"^/gateways/[^/]+/"), Permissions.GATEWAYS_UPDATE),  # POST to sub-resources (state, toggle, refresh)
    ("PUT", re.compile(r"^/gateways/[^/]+(?:$|/)"), Permissions.GATEWAYS_UPDATE),
    ("DELETE", re.compile(r"^/gateways/[^/]+(?:$|/)"), Permissions.GATEWAYS_DELETE),
    # Vault OAuth authorize — initiates Authorization Code flow via virtual server ID.
    # Router is registered only when OAUTH_TOKEN_BACKEND=vault (see main.py); this
    # pattern is harmless when the router is absent (no matching route exists).
    # The handler enforces gateway-level access via _enforce_gateway_access, so this
    # entry adds defence-in-depth only: it ensures a server-scoped API token whose
    # permissions list does not include gateways.read is rejected at the middleware
    # layer rather than reaching the handler and failing there.
    ("GET", re.compile(r"^/vault/authorize/[^/]+(?:$|/)"), Permissions.GATEWAYS_READ),
    # OAuth per-caller token status (oauth_router, prefix="/oauth") - single-gateway
    # and batch variants. The handler enforces gateway-level access via
    # _enforce_gateway_access, so this entry adds defence-in-depth only: it ensures a
    # server-scoped API token whose permissions list does not include gateways.read is
    # rejected at the middleware layer rather than reaching the handler and failing there.
    ("GET", re.compile(r"^/oauth/status(?:$|/)"), Permissions.GATEWAYS_READ),
    # OAuth per-caller access token retrieval (GET /oauth/token/{gateway_id}); returns a
    # live bearer token, so it requires gateways.token_read.
    ("GET", re.compile(r"^/oauth/token(?:$|/)"), Permissions.GATEWAYS_TOKEN_READ),
    # OAuth DCR registered-client management (oauth_router, prefix="/oauth").
    # Registered clients are global rows with no team column, so these map to
    # admin-category permissions; the handlers additionally require an
    # un-narrowed admin token (see _require_unnarrowed_admin).
    ("GET", re.compile(r"^/oauth/registered-clients(?:$|/)"), Permissions.ADMIN_OAUTH_CLIENTS_READ),
    ("DELETE", re.compile(r"^/oauth/registered-clients/[^/]+(?:$|/)"), Permissions.ADMIN_OAUTH_CLIENTS_DELETE),
    # MCP registry catalog (v1 prefix stripped by middleware before matching)
    ("GET", re.compile(r"^/catalog(?:$|/)"), Permissions.SERVERS_READ),
    ("POST", re.compile(r"^/catalog/[^/]+/register(?:$|/)"), Permissions.SERVERS_CREATE),
    # Observability metrics summaries (v1 prefix stripped by middleware before matching)
    ("GET", re.compile(r"^/observability/metrics/(?:timeseries|percentiles)(?:$|/)"), Permissions.METRICS_READ),
    # Recent activity feed (unversioned /api prefix; not subject to /v1 stripping)
    ("GET", re.compile(r"^/api/logs/activity(?:$|/)"), Permissions.AUDIT_READ),
    # Metrics permissions
    ("GET", re.compile(r"^/metrics(?:$|/)"), Permissions.ADMIN_METRICS),
    ("POST", re.compile(r"^/metrics/reset(?:$|/)"), Permissions.ADMIN_METRICS),
    # Invitee-facing team invitation routes
    ("GET", re.compile(r"^/users/me/invitations/?$"), Permissions.TEAMS_JOIN),
    ("POST", re.compile(r"^/teams/invitations/[^/]+/(?:accept|decline)/?$"), Permissions.TEAMS_JOIN),
    # Token permissions
    ("GET", re.compile(r"^/tokens(?:$|/)"), Permissions.TOKENS_READ),
    ("POST", re.compile(r"^/tokens/?$"), Permissions.TOKENS_CREATE),  # Only exact /tokens or /tokens/
    ("POST", re.compile(r"^/tokens/teams/[^/]+(?:$|/)"), Permissions.TOKENS_CREATE),
    ("PUT", re.compile(r"^/tokens/[^/]+(?:$|/)"), Permissions.TOKENS_UPDATE),
    ("DELETE", re.compile(r"^/tokens/[^/]+(?:$|/)"), Permissions.TOKENS_REVOKE),
    # Compliance reporting
    ("GET", re.compile(r"^/compliance(?:$|/)"), Permissions.ADMIN_COMPLIANCE),
    ("POST", re.compile(r"^/compliance(?:$|/)"), Permissions.ADMIN_COMPLIANCE),
    # A2A agent API permissions (a2a_router, prefix="/a2a" — see main.py).
    # Order matters: the first method+path match wins. The stored extended card needs
    # a2a.update, so it precedes the general GET /a2a rule. The concrete /a2a/invoke
    # collection route is listed before the {agent_name}-scoped POST routes.
    ("GET", re.compile(r"^/a2a/[^/]+/stored-card/extended/?$"), Permissions.A2A_UPDATE),
    ("GET", re.compile(r"^/a2a(?:$|/)"), Permissions.A2A_READ),
    ("POST", re.compile(r"^/a2a/[^/]+/tasks/[^/]+/cancel/?$"), Permissions.A2A_INVOKE),
    ("POST", re.compile(r"^/a2a/[^/]+/tasks/[^/]+/pushNotificationConfigs/?$"), Permissions.A2A_UPDATE),
    ("DELETE", re.compile(r"^/a2a/[^/]+/tasks/[^/]+/pushNotificationConfigs/[^/]+/?$"), Permissions.A2A_UPDATE),
    ("POST", re.compile(r"^/a2a/[^/]+/tasks/[^/]+/messages/?$"), Permissions.A2A_INVOKE),
    ("POST", re.compile(r"^/a2a/?$"), Permissions.A2A_CREATE),
    # Card fetch makes the gateway issue an outbound request to a caller-chosen URL,
    # so it needs a2a.create rather than a2a.read.
    ("POST", re.compile(r"^/a2a/fetch-card/?$"), Permissions.A2A_CREATE),
    ("POST", re.compile(r"^/a2a/[^/]+/card/?$"), Permissions.A2A_UPDATE),
    ("POST", re.compile(r"^/a2a/invoke/?$"), Permissions.A2A_INVOKE),
    ("POST", re.compile(r"^/a2a/[^/]+/invoke(?:$|/)"), Permissions.A2A_INVOKE),
    ("POST", re.compile(r"^/a2a/[^/]+/jsonrpc(?:$|/)"), Permissions.A2A_INVOKE),
    ("POST", re.compile(r"^/a2a/[^/]+/test(?:$|/)"), Permissions.A2A_INVOKE),
    ("POST", re.compile(r"^/a2a/[^/]+/(?:state|toggle)(?:$|/)"), Permissions.A2A_UPDATE),
    ("PUT", re.compile(r"^/a2a/[^/]+(?:$|/)"), Permissions.A2A_UPDATE),
    ("DELETE", re.compile(r"^/a2a/[^/]+(?:$|/)"), Permissions.A2A_DELETE),
    # Export/import routes on export_import_router. The handlers require
    # admin.export / admin.import (the import routes are global_only); without
    # these entries the default-deny below rejects correctly scoped tokens.
    ("GET", re.compile(r"^/export(?:$|/)"), Permissions.ADMIN_EXPORT),
    ("POST", re.compile(r"^/export/selective(?:$|/)"), Permissions.ADMIN_EXPORT),
    ("POST", re.compile(r"^/import(?:$|/)"), Permissions.ADMIN_IMPORT),
    ("GET", re.compile(r"^/import/status(?:$|/)"), Permissions.ADMIN_IMPORT),
    ("POST", re.compile(r"^/import/cleanup(?:$|/)"), Permissions.ADMIN_IMPORT),
    # A2A agent plugin bindings live under /a2a-agents/... (hyphen), which does not
    # match ^/a2a(?:$|/) above. Decorators on a2a_agent_plugin_bindings require
    # tools.read / tools.manage_plugins — same contract as tool plugin bindings (#6701).
    ("GET", re.compile(r"^/a2a-agents/plugin-bindings(?:$|/)"), Permissions.TOOLS_READ),
    ("POST", re.compile(r"^/a2a-agents/plugin-bindings(?:$|/)"), Permissions.TOOLS_MANAGE_PLUGINS),
    ("DELETE", re.compile(r"^/a2a-agents/plugin-bindings(?:$|/)"), Permissions.TOOLS_MANAGE_PLUGINS),
]

# Admin route permission map (granular by route group).
# IMPORTANT: Unmatched /admin/* paths are denied by default (fail-secure).
_ADMIN_PERMISSION_PATTERNS: List[Tuple[str, Pattern[str], str]] = [
    # Dashboard/overview surfaces
    ("GET", re.compile(r"^/admin/?$"), Permissions.ADMIN_DASHBOARD),
    ("GET", re.compile(r"^/admin/search(?:$|/)"), Permissions.ADMIN_DASHBOARD),
    ("GET", re.compile(r"^/admin/overview(?:$|/)"), Permissions.ADMIN_OVERVIEW),
    # User management
    ("GET", re.compile(r"^/admin/users(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
    ("POST", re.compile(r"^/admin/users(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
    ("DELETE", re.compile(r"^/admin/users(?:$|/)"), Permissions.ADMIN_USER_MANAGEMENT),
    # Team management
    ("POST", re.compile(r"^/admin/teams/?$"), Permissions.TEAMS_CREATE),
    ("DELETE", re.compile(r"^/admin/teams/[^/]+/join-request/[^/]+(?:$|/)"), Permissions.TEAMS_JOIN),
    ("DELETE", re.compile(r"^/admin/teams/[^/]+(?:$|/)"), Permissions.TEAMS_DELETE),
    ("GET", re.compile(r"^/admin/teams/[^/]+/edit(?:$|/)"), Permissions.TEAMS_UPDATE),
    ("POST", re.compile(r"^/admin/teams/[^/]+/update(?:$|/)"), Permissions.TEAMS_UPDATE),
    ("GET", re.compile(r"^/admin/teams/[^/]+/(?:members/add|members/partial|non-members/partial|join-requests)(?:$|/)"), Permissions.TEAMS_MANAGE_MEMBERS),
    ("POST", re.compile(r"^/admin/teams/[^/]+/(?:add-member|update-member-role|remove-member|join-requests/[^/]+/(?:approve|reject))(?:$|/)"), Permissions.TEAMS_MANAGE_MEMBERS),
    ("POST", re.compile(r"^/admin/teams/[^/]+/(?:leave|join-request(?:/[^/]+)?)(?:$|/)"), Permissions.TEAMS_JOIN),
    ("GET", re.compile(r"^/admin/teams(?:$|/)"), Permissions.TEAMS_READ),
    # Tool management
    ("POST", re.compile(r"^/admin/tools/?$"), Permissions.TOOLS_CREATE),
    ("POST", re.compile(r"^/admin/tools/import(?:$|/)"), Permissions.TOOLS_CREATE),
    ("POST", re.compile(r"^/admin/tools/[^/]+/delete(?:$|/)"), Permissions.TOOLS_DELETE),
    ("POST", re.compile(r"^/admin/tools/[^/]+/(?:edit|state)(?:$|/)"), Permissions.TOOLS_UPDATE),
    ("GET", re.compile(r"^/admin/tools(?:$|/)"), Permissions.TOOLS_READ),
    # Resource management
    ("POST", re.compile(r"^/admin/resources/?$"), Permissions.RESOURCES_CREATE),
    ("POST", re.compile(r"^/admin/resources/[^/]+/delete(?:$|/)"), Permissions.RESOURCES_DELETE),
    ("POST", re.compile(r"^/admin/resources/[^/]+/(?:edit|state)(?:$|/)"), Permissions.RESOURCES_UPDATE),
    ("GET", re.compile(r"^/admin/resources(?:$|/)"), Permissions.RESOURCES_READ),
    # Prompt management
    ("POST", re.compile(r"^/admin/prompts/?$"), Permissions.PROMPTS_CREATE),
    ("POST", re.compile(r"^/admin/prompts/[^/]+/delete(?:$|/)"), Permissions.PROMPTS_DELETE),
    ("POST", re.compile(r"^/admin/prompts/[^/]+/(?:edit|state)(?:$|/)"), Permissions.PROMPTS_UPDATE),
    ("GET", re.compile(r"^/admin/prompts(?:$|/)"), Permissions.PROMPTS_READ),
    # Gateway management
    ("POST", re.compile(r"^/admin/gateways/test(?:$|/)"), Permissions.GATEWAYS_READ),
    ("POST", re.compile(r"^/admin/gateways/?$"), Permissions.GATEWAYS_CREATE),
    ("POST", re.compile(r"^/admin/gateways/[^/]+/delete(?:$|/)"), Permissions.GATEWAYS_DELETE),
    ("POST", re.compile(r"^/admin/gateways/[^/]+/(?:edit|state)(?:$|/)"), Permissions.GATEWAYS_UPDATE),
    ("POST", re.compile(r"^/admin/gateways/[^/]+/transfer-ownership(?:$|/)"), Permissions.GATEWAYS_UPDATE),
    ("GET", re.compile(r"^/admin/gateways(?:$|/)"), Permissions.GATEWAYS_READ),
    # Server management
    ("POST", re.compile(r"^/admin/servers/?$"), Permissions.SERVERS_CREATE),
    ("POST", re.compile(r"^/admin/servers/[^/]+/delete(?:$|/)"), Permissions.SERVERS_DELETE),
    ("POST", re.compile(r"^/admin/servers/[^/]+/(?:edit|state)(?:$|/)"), Permissions.SERVERS_UPDATE),
    ("POST", re.compile(r"^/admin/servers/[^/]+/oauth/approve/?$"), Permissions.SERVERS_UPDATE),
    ("GET", re.compile(r"^/admin/servers(?:$|/)"), Permissions.SERVERS_READ),
    # Token/tag read surfaces
    ("GET", re.compile(r"^/admin/tokens(?:$|/)"), Permissions.TOKENS_READ),
    ("GET", re.compile(r"^/admin/tags(?:$|/)"), Permissions.TAGS_READ),
    # A2A management
    ("POST", re.compile(r"^/admin/a2a/?$"), Permissions.A2A_CREATE),
    ("POST", re.compile(r"^/admin/a2a/[^/]+/delete(?:$|/)"), Permissions.A2A_DELETE),
    ("POST", re.compile(r"^/admin/a2a/[^/]+/(?:edit|state)(?:$|/)"), Permissions.A2A_UPDATE),
    ("POST", re.compile(r"^/admin/a2a/[^/]+/test(?:$|/)"), Permissions.A2A_INVOKE),
    ("GET", re.compile(r"^/admin/a2a(?:$|/)"), Permissions.A2A_READ),
    # Section partials
    ("GET", re.compile(r"^/admin/sections/resources(?:$|/)"), Permissions.RESOURCES_READ),
    ("GET", re.compile(r"^/admin/sections/prompts(?:$|/)"), Permissions.PROMPTS_READ),
    ("GET", re.compile(r"^/admin/sections/servers(?:$|/)"), Permissions.SERVERS_READ),
    ("GET", re.compile(r"^/admin/sections/gateways(?:$|/)"), Permissions.GATEWAYS_READ),
    # Specialized admin domains
    ("GET", re.compile(r"^/admin/events(?:$|/)"), Permissions.ADMIN_EVENTS),
    ("GET", re.compile(r"^/admin/grpc(?:$|/)"), Permissions.ADMIN_GRPC),
    ("POST", re.compile(r"^/admin/grpc(?:$|/)"), Permissions.ADMIN_GRPC),
    ("PUT", re.compile(r"^/admin/grpc(?:$|/)"), Permissions.ADMIN_GRPC),
    ("GET", re.compile(r"^/admin/plugins(?:$|/)"), Permissions.ADMIN_PLUGINS),
    ("POST", re.compile(r"^/admin/plugins(?:$|/)"), Permissions.ADMIN_PLUGINS),
    ("PUT", re.compile(r"^/admin/plugins(?:$|/)"), Permissions.ADMIN_PLUGINS),
    ("DELETE", re.compile(r"^/admin/plugins(?:$|/)"), Permissions.ADMIN_PLUGINS),
    # System configuration/admin operations
    (
        "GET",
        re.compile(r"^/admin/(?:config|cache|mcp-pool|roots|metrics|logs|export|import|mcp-registry|system|support-bundle|maintenance|observability|performance|llm)(?:$|/)"),
        Permissions.ADMIN_SYSTEM_CONFIG,
    ),
    (
        "POST",
        re.compile(r"^/admin/(?:config|cache|mcp-pool|roots|metrics|logs|export|import|mcp-registry|system|support-bundle|maintenance|observability|performance|llm)(?:$|/)"),
        Permissions.ADMIN_SYSTEM_CONFIG,
    ),
    (
        "PUT",
        re.compile(r"^/admin/(?:config|cache|mcp-pool|roots|metrics|logs|export|import|mcp-registry|system|support-bundle|maintenance|observability|performance|llm)(?:$|/)"),
        Permissions.ADMIN_SYSTEM_CONFIG,
    ),
    (
        "DELETE",
        re.compile(r"^/admin/(?:config|cache|mcp-pool|roots|metrics|logs|export|import|mcp-registry|system|support-bundle|maintenance|observability|performance|llm)(?:$|/)"),
        Permissions.ADMIN_SYSTEM_CONFIG,
    ),
]


def _strip_v1_prefix(path: str) -> str:
    """Strip a leading /v1 version segment from a normalized path.

    Args:
        path: Normalized path string (must start with /).

    Returns:
        Path with the /v1 prefix removed, or the original path if not present.

    Examples:
        >>> _strip_v1_prefix("/v1/tools")
        '/tools'
        >>> _strip_v1_prefix("/v1")
        '/'
        >>> _strip_v1_prefix("/tools")
        '/tools'
    """
    if path.startswith("/v1/"):
        return path[3:]
    if path == "/v1":
        return "/"
    return path


def _normalize_llm_api_prefix(prefix: Optional[str]) -> str:
    """Normalize llm_api_prefix to a canonical path prefix.

    Args:
        prefix: Raw LLM API prefix setting value.

    Returns:
        str: Normalized path prefix, or empty string when prefix is empty or "/".
    """
    if not prefix:
        return ""
    normalized = "/" + str(prefix).strip().strip("/")
    if normalized == "/":
        return ""
    # Strip the /v1 API version prefix to align with _normalize_path_for_matching.
    normalized = _strip_v1_prefix(normalized)
    if normalized == "/":
        return ""
    return normalized


def _normalize_scope_path(scope_path: str, root_path: str) -> str:
    """Strip ``root_path`` from ``scope_path`` when the incoming path includes it.

    Args:
        scope_path: Request path observed by middleware.
        root_path: Application root path prefix, if configured.

    Returns:
        Path value normalized for permission and scope pattern matching.
    """
    if root_path and len(root_path) > 1:
        root_path = root_path.rstrip("/")
    if root_path and len(root_path) > 1 and scope_path.startswith(root_path):
        rest = scope_path[len(root_path) :]
        # root_path="/app" must not strip from "/application/..."
        if rest == "" or rest.startswith("/"):
            return rest or "/"
    return scope_path


@lru_cache(maxsize=16)
def _get_llm_permission_patterns(prefix: str) -> Tuple[Tuple[str, Pattern[str], str], ...]:
    """Build precompiled permission patterns for LLM proxy endpoints.

    Args:
        prefix: LLM API prefix used to mount proxy routes.

    Returns:
        Tuple[Tuple[str, Pattern[str], str], ...]: Method/path regex to required permission mappings.
    """
    normalized_prefix = _normalize_llm_api_prefix(prefix)
    escaped_prefix = re.escape(normalized_prefix)
    return (
        # LLM proxy routes are exact endpoints (optionally with a trailing slash),
        # unlike many REST resources that intentionally include sub-resources.
        ("POST", re.compile(rf"^{escaped_prefix}/chat/completions/?$"), Permissions.LLM_INVOKE),
        ("GET", re.compile(rf"^{escaped_prefix}/models/?$"), Permissions.LLM_READ),
    )


class TokenScopingMiddleware:
    """Middleware to enforce token scoping restrictions.

    Examples:
        >>> middleware = TokenScopingMiddleware()
        >>> isinstance(middleware, TokenScopingMiddleware)
        True
    """

    def __init__(self):
        """Initialize token scoping middleware.

        Examples:
            >>> middleware = TokenScopingMiddleware()
            >>> hasattr(middleware, '_extract_token_scopes')
            True
        """

    def _normalize_teams(self, teams) -> list:
        """Normalize teams from token payload to list of team IDs.

        Handles various team formats:
        - None -> []
        - List of strings -> as-is
        - List of dicts with 'id' key -> extract IDs

        Args:
            teams: Raw teams value from JWT payload

        Returns:
            List of team ID strings
        """
        if not teams:
            return []
        normalized = []
        for team in teams:
            if isinstance(team, dict):
                team_id = team.get("id")
                if team_id:
                    normalized.append(team_id)
            elif isinstance(team, str):
                normalized.append(team)
        return normalized

    def _normalize_path_for_matching(self, request_path: str) -> str:
        """Normalize a path for team scoping and permission matching.

        **IMPORTANT:** This method strips the `/v1` API version prefix to ensure
        scope patterns work consistently across both versioned and legacy routes.

        Examples:
            - `/v1/tools` → `/tools`
            - `/tools` → `/tools`
            - `/v1/admin/users` → `/admin/users`
            - `/v1` → `/`

        This means:
            - A pattern `^/tools` matches BOTH `/tools` AND `/v1/tools`
            - A pattern `^/v1/tools` is normalized to `^/tools` and matches both
            - **Write patterns WITHOUT the `/v1` prefix for consistency**

        Args:
            request_path: Raw request path from HTTP request.

        Returns:
            Normalized path with `/v1` prefix removed (if present).

        See Also:
            - docs/docs/manage/rbac.md - Token scope pattern documentation
            - tests/unit/mcpgateway/middleware/test_token_scoping_normalization.py
        """
        normalized = _normalize_scope_path(request_path or "/", settings.app_root_path or "")
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        normalized = replace_api_path_alias(normalized)
        # Strip the /v1 API version prefix so all patterns match unversioned paths.
        # This ensures scope patterns work identically for /tools and /v1/tools.
        return _strip_v1_prefix(normalized)

    def _get_normalized_request_path(self, request: Request) -> str:
        """Resolve request path with APP_ROOT_PATH-aware normalization.

        Args:
            request: Request object containing scope and URL data.

        Returns:
            Normalized request path suitable for permission checks.
        """
        scope = getattr(request, "scope", {}) or {}
        if not isinstance(scope, dict):
            scope = {}
        scope_path = request.url.path or scope.get("path") or "/"
        root_path = scope.get("root_path") or settings.app_root_path or ""
        normalized = _normalize_scope_path(scope_path, root_path)
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return replace_api_path_alias(normalized)

    async def _extract_token_scopes(self, request: Request) -> Optional[dict]:
        """Extract token scopes from JWT in request.

        Args:
            request: FastAPI request object

        Returns:
            Dict containing token scopes or None if no valid token
        """
        token = get_request_auth_token(request)
        if not token:
            return None

        try:
            # Use the centralized verify_jwt_token_cached function for consistent JWT validation
            payload = await verify_jwt_token_cached(token, request)
            return payload
        except HTTPException:
            # Token validation failed (expired, invalid, etc.)
            return None
        except Exception:
            # Any other error in token validation
            return None

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request.

        ``ProxyHeadersMiddleware`` resolves ``request.client`` from
        X-Forwarded-For only when the direct peer is listed in
        ``FORWARDED_ALLOW_IPS``; otherwise it is the socket peer.

        Args:
            request: FastAPI request object

        Returns:
            str: Client IP address
        """
        return request.client.host if request.client else "unknown"

    def _check_ip_restrictions(self, client_ip: str, ip_restrictions: list) -> bool:
        """Check if client IP is allowed by restrictions.

        Args:
            client_ip: Client's IP address
            ip_restrictions: List of allowed IP addresses/CIDR ranges

        Returns:
            bool: True if IP is allowed, False otherwise

        Examples:
            Allow specific IP:
            >>> m = TokenScopingMiddleware()
            >>> m._check_ip_restrictions('192.168.1.10', ['192.168.1.10'])
            True

            Allow CIDR range:
            >>> m._check_ip_restrictions('10.0.0.5', ['10.0.0.0/24'])
            True

            Deny when not in list:
            >>> m._check_ip_restrictions('10.0.1.5', ['10.0.0.0/24'])
            False

            Empty restrictions allow all:
            >>> m._check_ip_restrictions('203.0.113.1', [])
            True
        """
        if not ip_restrictions:
            return True  # No restrictions

        try:
            client_ip_obj = ipaddress.ip_address(client_ip)

            for restriction in ip_restrictions:
                try:
                    # Check if it's a CIDR range
                    if "/" in restriction:
                        network = ipaddress.ip_network(restriction, strict=False)
                        if client_ip_obj in network:
                            return True
                    else:
                        # Single IP address
                        if client_ip_obj == ipaddress.ip_address(restriction):
                            return True
                except (ValueError, ipaddress.AddressValueError):
                    continue

        except (ValueError, ipaddress.AddressValueError):
            return False

        return False

    def _check_time_restrictions(self, time_restrictions: dict) -> bool:
        """Check if current time is allowed by restrictions.

        Args:
            time_restrictions: Dict containing time-based restrictions

        Returns:
            bool: True if current time is allowed, False otherwise

        Examples:
            No restrictions allow access:
            >>> m = TokenScopingMiddleware()
            >>> m._check_time_restrictions({})
            True

            Weekdays only: result depends on current weekday (always bool):
            >>> isinstance(m._check_time_restrictions({'weekdays_only': True}), bool)
            True

            Business hours only: result depends on current hour (always bool):
            >>> isinstance(m._check_time_restrictions({'business_hours_only': True}), bool)
            True
        """
        if not time_restrictions:
            return True  # No restrictions

        now = datetime.now(tz=timezone.utc)

        # Check business hours restriction
        if time_restrictions.get("business_hours_only"):
            # Assume business hours are 9 AM to 5 PM UTC
            # This could be made configurable
            if not 9 <= now.hour < 17:
                return False

        # Check day of week restrictions
        weekdays_only = time_restrictions.get("weekdays_only")
        if weekdays_only and now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        return True

    @staticmethod
    def _parse_positive_limit(value: object) -> Optional[int]:
        """Parse usage-limit values as positive integers.

        Args:
            value: Candidate limit value from token scope configuration.

        Returns:
            Parsed positive integer limit, or ``None`` when invalid/non-positive.
        """
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _check_usage_limits(self, jti: Optional[str], usage_limits: dict) -> Tuple[bool, Optional[str]]:
        """Check token usage limits against recorded usage logs.

        Args:
            jti: Token JTI identifier.
            usage_limits: Usage limits from token scope.

        Returns:
            Tuple[bool, Optional[str]]: (allowed, denial_reason)
        """
        if not isinstance(usage_limits, dict) or not usage_limits or not jti:
            return True, None

        requests_per_hour = self._parse_positive_limit(usage_limits.get("requests_per_hour"))
        requests_per_day = self._parse_positive_limit(usage_limits.get("requests_per_day"))

        if not requests_per_hour and not requests_per_day:
            return True, None

        # First-Party
        from mcpgateway.db import get_db, TokenUsageLog  # pylint: disable=import-outside-toplevel

        db = next(get_db())
        try:
            now = datetime.now(timezone.utc)

            if requests_per_hour:
                hour_window_start = now - timedelta(hours=1)
                hourly_count = db.execute(
                    # Pylint false-positive: SQLAlchemy func namespace is callable at runtime.
                    # pylint: disable=not-callable
                    select(func.count(TokenUsageLog.id)).where(and_(TokenUsageLog.token_jti == jti, TokenUsageLog.timestamp >= hour_window_start))
                ).scalar()
                if int(hourly_count or 0) >= requests_per_hour:
                    return False, "Hourly request limit exceeded"

            if requests_per_day:
                day_window_start = now - timedelta(days=1)
                daily_count = db.execute(
                    # Pylint false-positive: SQLAlchemy func namespace is callable at runtime.
                    # pylint: disable=not-callable
                    select(func.count(TokenUsageLog.id)).where(and_(TokenUsageLog.token_jti == jti, TokenUsageLog.timestamp >= day_window_start))
                ).scalar()
                if int(daily_count or 0) >= requests_per_day:
                    return False, "Daily request limit exceeded"
        except Exception as exc:
            logger.warning("Failed to evaluate token usage limits for jti %s: %s", jti, exc)
            return True, None
        finally:
            try:
                db.rollback()
            finally:
                db.close()

        return True, None

    def _check_server_restriction(self, request_path: str, server_id: Optional[str]) -> bool:
        """Check if request path matches server restriction.

        Args:
            request_path: The request path/URL
            server_id: Required server ID (None means no restriction)

        Returns:
            bool: True if request is allowed, False otherwise

        Examples:
            Match server paths:
            >>> m = TokenScopingMiddleware()
            >>> m._check_server_restriction('/servers/abc/tools', 'abc')
            True
            >>> m._check_server_restriction('/sse/xyz', 'xyz')
            True
            >>> m._check_server_restriction('/ws/xyz?x=1', 'xyz')
            True

            Mismatch denies:
            >>> m._check_server_restriction('/servers/def', 'abc')
            False

            General endpoints allowed:
            >>> m._check_server_restriction('/health', 'abc')
            True
            >>> m._check_server_restriction('/', 'abc')
            True
        """
        request_path = self._normalize_path_for_matching(request_path)

        if not server_id:
            return True  # No server restriction

        # Extract server ID from path patterns (uses precompiled regex)
        # /servers/{server_id}/...
        # /sse/{server_id}
        # /ws/{server_id}
        for pattern in _SERVER_PATH_PATTERNS:
            match = pattern.search(request_path)
            if match:
                path_server_id = match.group(1)
                return path_server_id == server_id

        # If no server ID found in path, allow general endpoints
        general_endpoints = ["/health", "/metrics", "/openapi.json", "/docs", "/redoc", "/rpc", "/mcp", "/sse"]

        # Check exact root path separately
        if request_path == "/":
            return True

        for endpoint in general_endpoints:
            if request_path.startswith(endpoint):
                return True

        # Default deny for unmatched paths with server restrictions
        return False

    def _check_permission_restrictions(self, request_path: str, request_method: str, permissions: list) -> bool:
        """Check if request is allowed by permission restrictions.

        Args:
            request_path: The request path/URL
            request_method: HTTP method (GET, POST, etc.)
            permissions: List of allowed permissions

        Returns:
            bool: True if request is allowed, False otherwise

        Examples:
            Wildcard allows all:
            >>> m = TokenScopingMiddleware()
            >>> m._check_permission_restrictions('/tools', 'GET', ['*'])
            True

            Requires specific permission:
            >>> m._check_permission_restrictions('/tools', 'POST', ['tools.create'])
            True
            >>> m._check_permission_restrictions('/tools/xyz', 'PUT', ['tools.update'])
            True
            >>> m._check_permission_restrictions('/resources', 'GET', ['resources.read'])
            True
            >>> m._check_permission_restrictions('/servers/s1/tools/abc/call', 'POST', ['tools.execute'])
            True

            Category wildcard covers every action in that category:
            >>> m._check_permission_restrictions('/tools', 'POST', ['tools.*'])
            True

            Missing permission denies:
            >>> m._check_permission_restrictions('/tools', 'POST', ['tools.read'])
            False
            >>> m._check_permission_restrictions('/tools', 'POST', ['resources.*'])
            False
        """
        request_path = self._normalize_path_for_matching(request_path)

        if not permissions or _ALL_PERMISSIONS_SCOPE in permissions:
            return True  # No restrictions or full access

        # Unified search (/v1/search, normalized to /search) is authenticated-only
        # at this layer: it spans many entity types, each guarded by its own
        # @require_permission, and per-entity denials are suppressed downstream by
        # _safe_entity_search. Requiring a single permission here would wrongly 403
        # a validly-scoped token (e.g. tools.read-only), so let it through and rely
        # on the handler's per-entity RBAC + token/team scoping to filter results.
        if request_path == "/search" or request_path.startswith("/search/"):
            return True

        # The caller's own profile and deployment feature flags need no scoped permission;
        # any authenticated token may read them.
        if request_method == "GET" and request_path in ("/auth/email/me", "/auth/email/me/"):
            return True

        # Handle admin routes with granular route-group mapping.
        # Unmapped /admin/* paths are denied by default (fail-secure).
        if request_path.startswith("/admin"):
            for method, path_pattern, required_permission in _ADMIN_PERMISSION_PATTERNS:
                if request_method == method and path_pattern.match(request_path):
                    return token_scope_grants(permissions, required_permission)
            return False

        # Check each permission mapping (uses precompiled regex patterns).
        # token_scope_grants() owns the servers.use transport compensation for tokens
        # carrying MCP method permissions, so this layer and the RBAC decorators agree.
        for method, path_pattern, required_permission in _PERMISSION_PATTERNS:
            if request_method == method and path_pattern.match(request_path):
                return token_scope_grants(permissions, required_permission)

        # LLM proxy permissions (respect configured llm_api_prefix).
        for method, path_pattern, required_permission in _get_llm_permission_patterns(settings.llm_api_prefix):
            if request_method == method and path_pattern.match(request_path):
                return token_scope_grants(permissions, required_permission)

        # Default deny for unmatched paths (requires explicit permission mapping)
        return False

    @staticmethod
    def _get_user_email_from_payload(payload: dict) -> str | None:
        """Extract the email identity from a signed JWT payload."""
        return get_jwt_user_email_from_payload(payload)

    @staticmethod
    async def _resolve_user_email_from_payload(payload: dict) -> str | None:
        """Resolve the email identity from a signed JWT payload, including UUID-sub fallback."""
        # First-Party
        from mcpgateway.auth import _get_email_by_id_sync  # pylint: disable=import-outside-toplevel

        async def resolve_uuid_subject(user_id: str) -> str | None:
            """Resolve a UUID subject to the owning user's email."""
            return await asyncio.to_thread(_get_email_by_id_sync, user_id)

        return await resolve_jwt_user_email_from_payload(payload, uuid_email_resolver=resolve_uuid_subject)

    def _check_team_membership(self, payload: dict, db=None) -> bool:
        """
        Check if user still belongs to teams in the token.

        For public-only tokens (no teams), always returns True.
        For team-scoped tokens, validates membership with caching.

        Uses in-memory cache (per gateway instance, 60s TTL) to avoid repeated
        email_team_members queries for the same user+teams combination.
        Note: Sync path uses in-memory only for performance; Redis is not
        consulted to avoid async overhead in the hot path.

        Args:
            payload: Decoded JWT payload containing teams
            db: Optional database session. If provided, caller manages lifecycle.
                If None, creates and manages its own session.

        Returns:
            bool: True if team membership is valid, False otherwise
        """
        teams = payload.get("teams", [])
        user_email = self._get_user_email_from_payload(payload)

        # PUBLIC-ONLY TOKEN: No team validation needed
        if not teams or len(teams) == 0:
            logger.debug(f"Public-only token for user {SecurityValidator.sanitize_log_message(user_email)} - no team validation required")
            return True

        # TEAM-SCOPED TOKEN: Validate membership
        if not user_email:
            logger.warning("Token missing user email")
            return False

        # Extract team IDs from token (handles both dict and string formats)
        team_ids = [team["id"] if isinstance(team, dict) else team for team in teams]
        valid = validate_token_team_membership(user_email, team_ids, db=db)
        if not valid:
            logger.warning(f"Token invalid: User {SecurityValidator.sanitize_log_message(user_email)} no longer member of teams")
        return valid

    @staticmethod
    def _is_a2a_mutation(request_path: str, method: str) -> bool:
        """Return whether a request changes an A2A agent.

        Args:
            request_path: Normalized request path.
            method: HTTP method of the request.

        Returns:
            bool: True for update, state, toggle and delete routes of one agent.
        """
        return method.upper() in _A2A_MUTATION_METHODS and bool(_A2A_MUTATION_PATTERN.fullmatch(request_path))

    def _is_targeted_missing_resource_delete(self, request_path: str, method: str) -> bool:
        """Return whether request is an exact server or gateway DELETE path."""
        normalized_path = self._normalize_path_for_matching(request_path)
        return method == "DELETE" and bool(_TARGETED_MISSING_DELETE_PATTERN.fullmatch(normalized_path))

    @staticmethod
    def _normalize_token_team_ids(token_teams: List[Any]) -> List[str]:
        """Extract team IDs from token teams, accepting both dict and string formats.

        Args:
            token_teams: Teams from the token (dicts with an ``id`` key or plain team IDs).

        Returns:
            List[str]: The team IDs.
        """
        return [team["id"] if isinstance(team, dict) else team for team in token_teams]

    @staticmethod
    def _extract_resource_target(request_path: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract the resource type and ID addressed by a request path.

        IDs are UUID hex strings (32 chars) or UUIDs with dashes (36 chars).

        Args:
            request_path: Normalized request path.

        Returns:
            Tuple[Optional[str], Optional[str]]: ``(resource_type, resource_id)``, or ``(None, None)`` when the path addresses no resource.
        """
        for pattern, resource_type in _RESOURCE_PATTERNS:
            match = pattern.search(request_path)
            if match:
                resource_id = match.group(1)
                logger.debug(f"Extracted {resource_type} ID: {SecurityValidator.sanitize_log_message(resource_id)} from path: {SecurityValidator.sanitize_log_message(request_path)}")
                return resource_type, resource_id
        return None, None

    @staticmethod
    def _load_resource_row(db: Session, spec: _ResourceOwnershipSpec, resource_id: str, preloaded_gateway: Optional[Gateway] = None) -> Optional[Any]:
        """Load the resource row addressed by a request path.

        Args:
            db: Database session.
            spec: Ownership spec of the resource type.
            resource_id: ID of the resource.
            preloaded_gateway: Optional already-fetched ``Gateway`` row, reused when its ``id`` matches ``resource_id``.

        Returns:
            The resource row, or ``None`` when it does not exist.
        """
        if spec.model is Gateway and preloaded_gateway is not None and getattr(preloaded_gateway, "id", None) == resource_id:
            return preloaded_gateway
        return db.execute(select(spec.model).where(spec.model.id == resource_id)).scalar_one_or_none()

    @staticmethod
    def _team_visibility_result(spec: _ResourceOwnershipSpec, resource: Any, resource_id: str, token_team_ids: List[str]) -> ResourceOwnershipResult:
        """Check a team-visible resource against the token's teams.

        Args:
            spec: Ownership spec of the resource type.
            resource: The resource row.
            resource_id: ID of the resource.
            token_team_ids: Team IDs from the token.

        Returns:
            ResourceOwnershipResult: ``ALLOWED`` when the resource's team is one of the token's teams, else ``DENIED``.
        """
        safe_id = SecurityValidator.sanitize_log_message(resource_id)
        resource_team_id = getattr(resource, "team_id", None)
        if resource_team_id and resource_team_id in token_team_ids:
            logger.debug(f"Access granted: Team {spec.label} {safe_id} belongs to token's team {SecurityValidator.sanitize_log_message(str(resource_team_id))}")
            return ResourceOwnershipResult.ALLOWED

        logger.warning(
            f"Access denied: {spec.title} {safe_id} is team-scoped to '{SecurityValidator.sanitize_log_message(str(resource_team_id))}', "
            f"token is scoped to teams {SecurityValidator.sanitize_log_message(str(token_team_ids))}"
        )
        return ResourceOwnershipResult.DENIED

    @staticmethod
    def _private_visibility_result(spec: _ResourceOwnershipSpec, resource: Any, resource_id: str, visibility: str, user_email: Optional[str]) -> ResourceOwnershipResult:
        """Check a private resource against the requesting user (owner-only access).

        Args:
            spec: Ownership spec of the resource type.
            resource: The resource row.
            resource_id: ID of the resource.
            visibility: Visibility of the resource.
            user_email: Email of the requesting user.

        Returns:
            ResourceOwnershipResult: ``ALLOWED`` when the requester owns the resource, else ``DENIED``.
        """
        safe_id = SecurityValidator.sanitize_log_message(resource_id)
        owner = getattr(resource, "owner_email", None)
        if owner and owner == user_email:
            logger.debug(f"Access granted: Private {spec.label} {safe_id} owned by {SecurityValidator.sanitize_log_message(user_email)}")
            return ResourceOwnershipResult.ALLOWED

        logger.warning(
            f"Access denied: {spec.title} {safe_id} is {SecurityValidator.sanitize_log_message(visibility)}, "
            f"owner is '{SecurityValidator.sanitize_log_message(str(owner))}', requester is '{SecurityValidator.sanitize_log_message(user_email)}'"
        )
        return ResourceOwnershipResult.DENIED

    def _resource_visibility_result(
        self, spec: _ResourceOwnershipSpec, resource: Any, resource_id: str, token_team_ids: List[str], is_public_token: bool, user_email: Optional[str]
    ) -> ResourceOwnershipResult:
        """Apply the Three-Tier Resource Visibility (Public/Team/Private) rules to a resource row.

        Args:
            spec: Ownership spec of the resource type.
            resource: The resource row.
            resource_id: ID of the resource.
            token_team_ids: Team IDs from the token.
            is_public_token: Whether the token is public-only (no teams).
            user_email: Email of the requesting user.

        Returns:
            ResourceOwnershipResult: ``ALLOWED`` or ``DENIED``; unknown visibility is denied.
        """
        safe_id = SecurityValidator.sanitize_log_message(resource_id)
        visibility = getattr(resource, "visibility", "team")

        if visibility == "public":
            logger.debug(f"Access granted: {spec.title} {safe_id} is PUBLIC")
            return ResourceOwnershipResult.ALLOWED

        # Public-only tokens reach public resources only; owners needing their own resources use a personal team-scoped token.
        if is_public_token:
            logger.warning(f"Access denied: Public-only token cannot access {SecurityValidator.sanitize_log_message(visibility)} {spec.label} {safe_id}")
            return ResourceOwnershipResult.DENIED

        if visibility == "team":
            return self._team_visibility_result(spec, resource, resource_id, token_team_ids)

        if visibility in spec.private_visibilities:
            return self._private_visibility_result(spec, resource, resource_id, visibility, user_email)

        logger.warning(f"Access denied: {spec.title} {safe_id} has unknown visibility: {SecurityValidator.sanitize_log_message(visibility)}")
        return ResourceOwnershipResult.DENIED

    def _check_resource_team_ownership(
        self,
        request_path: str,
        token_teams: List[Any],
        db: Optional[Session] = None,
        _user_email: Optional[str] = None,
        preloaded_gateway: Optional[Gateway] = None,
        method: Optional[str] = None,
    ) -> ResourceOwnershipResult:
        """
        Check if the requested resource is accessible by the token.

        Implements Three-Tier Resource Visibility (Public/Team/Private):
        - PUBLIC: Accessible by all tokens (public-only and team-scoped)
        - TEAM: Accessible only by tokens scoped to that specific team
        - PRIVATE: Accessible only by the owner

        Token Access Rules:
        - Public-only tokens (empty token_teams): Can access public resources only
        - Team-scoped tokens: Can access their team's resources + public resources

        Handles URLs like:
        - /servers/{id}/mcp
        - /servers/{id}/sse
        - /servers/{id}
        - /tools/{id}/execute
        - /tools/{id}
        - /resources/{id}
        - /prompts/{id}
        - /a2a/{id}

        Args:
            request_path: The request path/URL
            token_teams: List of team IDs from the token (empty list = public-only token)
            db: Optional database session. If provided, caller manages lifecycle.
                If None, creates and manages its own session.
            _user_email: Email of the requesting user, used for private-resource ownership.
            preloaded_gateway: Optional already-fetched ``Gateway`` row. When the
                path resolves to a gateway resource and this row's ``id`` matches
                the path's resource id, it is reused instead of issuing another
                ``SELECT`` - lets a caller that already loaded the gateway (e.g. a
                batch endpoint that bulk-fetched many gateways) avoid a redundant
                per-id re-fetch here.
            method: HTTP method of the request. A2A agent paths are checked only for mutation
                routes. When omitted, every A2A agent path is checked.

        Returns:
            ResourceOwnershipResult: Allowed, missing, or denied ownership result.
        """
        request_path = self._normalize_path_for_matching(request_path)
        token_team_ids = self._normalize_token_team_ids(token_teams)
        is_public_token = not token_team_ids

        if is_public_token:
            logger.debug("Processing request with PUBLIC-ONLY token")
        else:
            logger.debug(f"Processing request with TEAM-SCOPED token (teams: {SecurityValidator.sanitize_log_message(str(token_teams))})")

        resource_type, resource_id = self._extract_resource_target(request_path)

        # If no resource ID in path, allow (general endpoints like /health, /tokens, /metrics)
        if not resource_id or not resource_type:
            logger.debug(f"No resource ID found in path {request_path}, allowing access")
            return ResourceOwnershipResult.ALLOWED

        if resource_type == "a2a_agent" and method is not None and not self._is_a2a_mutation(request_path, method):
            return ResourceOwnershipResult.ALLOWED

        spec = _RESOURCE_OWNERSHIP_SPECS.get(resource_type)
        if spec is None:
            logger.warning(f"Unknown resource type '{SecurityValidator.sanitize_log_message(str(resource_type))}' for path: {SecurityValidator.sanitize_log_message(request_path)}")
            return ResourceOwnershipResult.DENIED

        # Imported lazily so the session factory stays patchable at ``mcpgateway.db.get_db``.
        # First-Party
        from mcpgateway.db import get_db  # pylint: disable=import-outside-toplevel

        # Track if we own the session (and thus must clean it up)
        owns_session = db is None
        session = next(get_db()) if db is None else db

        try:
            resource = self._load_resource_row(session, spec, resource_id, preloaded_gateway)
            if not resource:
                logger.warning(f"{spec.title} {SecurityValidator.sanitize_log_message(resource_id)} not found in database")
                return spec.missing_result
            return self._resource_visibility_result(spec, resource, resource_id, token_team_ids, is_public_token, _user_email)
        except Exception as e:
            logger.error(f"Error checking resource team ownership for {request_path}: {e}", exc_info=True)
            # Fail securely - deny access on error
            return ResourceOwnershipResult.DENIED
        finally:
            # Only commit/close if we created the session
            if owns_session:
                try:
                    session.commit()  # Commit read-only transaction to avoid implicit rollback
                finally:
                    session.close()

    async def __call__(self, request: Request, call_next):
        """Middleware function to check token scoping including team-level validation.

        Args:
            request: FastAPI request object
            call_next: Next middleware/handler in chain

        Returns:
            Response from next handler or HTTPException

        Raises:
            HTTPException: If token scoping restrictions are violated
        """
        try:
            # Skip if already scoped (prevents double-scoping for /mcp requests)
            # MCPPathRewriteMiddleware runs scoping via dispatch, then routes through
            # middleware stack which hits BaseHTTPMiddleware's scoping again.
            # Use request.state flag which persists across middleware invocations.
            if getattr(request.state, "_token_scoping_done", False):
                return await call_next(request)

            # Mark as scoped before doing any work
            request.state._token_scoping_done = True

            normalized_path = self._get_normalized_request_path(request)

            # Skip scoping for certain paths (truly public endpoints only)
            skip_paths = [
                "/health",
                "/openapi.json",
                "/docs",
                "/redoc",
                "/auth/email/login",
                "/auth/email/register",
                "/.well-known/",
            ]

            # Check exact root path separately
            if normalized_path == "/":
                return await call_next(request)

            # Trusted Python affinity dispatch already carries a
            # normalized auth context and is re-authorized by the internal MCP
            # dispatcher. Re-applying token-scoping path checks here would reject
            # the private /_internal/mcp/rpc hop for scoped tokens.
            if self._is_trusted_internal_mcp_runtime_request(request, normalized_path):
                return await call_next(request)

            if any(normalized_path.startswith(path) for path in skip_paths):
                return await call_next(request)

            # Skip server-specific well-known endpoints (RFC 9728)
            if re.match(r"^/servers/[^/]+/\.well-known/", normalized_path):
                return await call_next(request)

            # Extract full token payload (not just scopes)
            payload = await self._extract_token_scopes(request)

            # If no payload, continue (regular auth will handle this)
            if not payload:
                return await call_next(request)

            # Resolve teams based on token_use claim
            token_use = payload.get("token_use")
            if token_use == "session":  # nosec B105 - Not a password; token_use is a JWT claim type
                user_email = await self._resolve_user_email_from_payload(payload)
                # Session token: resolve teams from DB/cache directly
                # Cannot rely on request.state.token_teams — AuthContextMiddleware
                # is gated by security_logging_enabled (defaults to False)
                user_info = {}  # is_admin resolved from DB inside _resolve_teams_from_db
                token_teams = await resolve_session_teams(payload, user_email, user_info)
            else:
                # API and legacy tokens carry signed email metadata or legacy
                # email subjects, so keep this path free of DB lookups.
                user_email = self._get_user_email_from_payload(payload)
                # API token or legacy: use embedded teams with normalize_token_teams
                token_teams = normalize_token_teams(payload)

            # Check if admin bypass is active (token_teams is None means admin with explicit null teams)
            is_admin_bypass = token_teams is None

            # Admin with explicit null teams bypasses team validation entirely
            if is_admin_bypass:
                logger.debug(f"Admin bypass: skipping team validation for {SecurityValidator.sanitize_log_message(user_email)}")
                # Skip to other checks (server_id, IP, etc.)
            elif token_teams:
                # First-Party
                from mcpgateway.db import get_db  # pylint: disable=import-outside-toplevel

                db = next(get_db())
                try:
                    # Check team membership — only for API/legacy tokens whose teams
                    # come from JWT claims and may be stale.  Session tokens skip this
                    # because resolve_session_teams() already resolved membership from
                    # the DB; re-checking the raw JWT claim here would conflict with
                    # the intersection semantics (stale JWT teams would cause a 403
                    # even though the user has valid DB teams).
                    # NOTE: session-token membership staleness is bounded by the
                    # auth_cache TTL (see _resolve_teams_from_db).
                    if token_use != "session" and not self._check_team_membership(payload, db=db):  # nosec B105 - Not a password; token_use is a JWT claim type
                        logger.warning("Token rejected: User no longer member of associated team(s)")
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is invalid: User is no longer a member of the associated team")

                    # Check resource team ownership with shared session
                    ownership_result = self._check_resource_team_ownership(normalized_path, token_teams, db=db, _user_email=user_email, method=request.method)
                    if ownership_result is ResourceOwnershipResult.NOT_FOUND and self._is_targeted_missing_resource_delete(request.url.path, request.method):
                        logger.info("Scoped DELETE target not found: %s", SecurityValidator.sanitize_log_message(normalized_path))
                        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
                    if ownership_result is not ResourceOwnershipResult.ALLOWED:
                        logger.warning(f"Access denied: Resource does not belong to token's teams {SecurityValidator.sanitize_log_message(str(token_teams))}")
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)
                finally:
                    # Ensure session cleanup even if checks raise exceptions
                    try:
                        db.commit()
                    finally:
                        db.close()
            else:
                # Public-only token (or session token with empty intersection):
                # skip _check_team_membership for session tokens — the empty
                # intersection already means no team-scoped access.
                # Membership staleness bounded by auth_cache TTL.
                if token_use != "session" and not self._check_team_membership(payload):  # nosec B105 - Not a password; token_use is a JWT claim type
                    logger.warning("Token rejected: User no longer member of associated team(s)")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is invalid: User is no longer a member of the associated team")

                ownership_result = self._check_resource_team_ownership(normalized_path, token_teams, _user_email=user_email, method=request.method)
                if ownership_result is ResourceOwnershipResult.NOT_FOUND and self._is_targeted_missing_resource_delete(request.url.path, request.method):
                    logger.info("Scoped DELETE target not found: %s", SecurityValidator.sanitize_log_message(normalized_path))
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
                if ownership_result is not ResourceOwnershipResult.ALLOWED:
                    logger.warning(f"Access denied: Resource does not belong to token's teams {SecurityValidator.sanitize_log_message(str(token_teams))}")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)

            # Extract scopes from payload
            scopes = payload.get("scopes", {})

            # Check server ID restriction
            server_id = scopes.get("server_id")
            if not self._check_server_restriction(normalized_path, server_id):
                logger.warning(f"Token not authorized for this server. Required: {SecurityValidator.sanitize_log_message(str(server_id))}")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)

            # Check IP restrictions
            ip_restrictions = scopes.get("ip_restrictions", [])
            if ip_restrictions:
                client_ip = self._get_client_ip(request)
                if not self._check_ip_restrictions(client_ip, ip_restrictions):
                    logger.warning(f"Request from IP {client_ip} not allowed by token restrictions")
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)

            # Check time restrictions
            time_restrictions = scopes.get("time_restrictions", {})
            if not self._check_time_restrictions(time_restrictions):
                logger.warning("Request not allowed at this time by token restrictions")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Request not allowed at this time by token restrictions")

            # Check permission restrictions
            permissions = scopes.get("permissions", [])
            if not self._check_permission_restrictions(normalized_path, request.method, permissions):
                logger.warning("Insufficient permissions for this operation")
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_ACCESS_DENIED_MSG)

            # Check optional token usage limits.
            usage_limits = scopes.get("usage_limits", {})
            usage_allowed, usage_reason = self._check_usage_limits(payload.get("jti"), usage_limits)
            if not usage_allowed:
                logger.warning("Token usage limit exceeded for jti %s: %s", payload.get("jti"), usage_reason)
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=usage_reason or "Token usage limit exceeded")

            # All scoping checks passed, continue
            return await call_next(request)

        except HTTPException as exc:
            # Return clean JSON response instead of traceback
            return ORJSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )

    def _is_trusted_internal_mcp_runtime_request(self, request: Request, normalized_path: str) -> bool:
        """Return whether the request is a trusted Python affinity RPC hop.

        Delegate to the shared gate in ``auth_context`` to keep middleware and
        internal dispatch on the same trust boundary.

        Args:
            request: Incoming HTTP request.
            normalized_path: Canonicalized request path used for route matching.

        Returns:
            ``True`` when the request is a trusted Python affinity RPC hop.
        """
        # First-Party
        from mcpgateway.auth_context import is_trusted_internal_mcp_request  # pylint: disable=import-outside-toplevel

        return is_trusted_internal_mcp_request(request, path=normalized_path)


# Create middleware instance
token_scoping_middleware = TokenScopingMiddleware()
