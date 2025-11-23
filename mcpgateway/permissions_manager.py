# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/permissions_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhav Kandukuri

Permissions Manager.
Defines the default system roles and their permissions.
"""

# First-Party
from mcpgateway.db import Permissions

DEFAULT_ROLES = [
    {
        "name": "platform_admin",
        "description": "Platform administrator with all permissions",
        "scope": "global",
        "permissions": [Permissions.ALL_PERMISSIONS],
        "is_system_role": True,
    },
    {
        "name": "team_owner",
        "description": "Team owner with full team management permissions",
        "scope": "team",
        "permissions": [
            # Team Management
            Permissions.TEAMS_READ,
            Permissions.TEAMS_UPDATE,
            Permissions.TEAMS_DELETE,
            Permissions.TEAMS_JOIN,
            Permissions.TEAMS_MANAGE_MEMBERS,
            # Gateways
            Permissions.GATEWAYS_CREATE,
            Permissions.GATEWAYS_READ,
            Permissions.GATEWAYS_UPDATE,
            Permissions.GATEWAYS_DELETE,
            # Servers
            Permissions.SERVERS_CREATE,
            Permissions.SERVERS_READ,
            Permissions.SERVERS_UPDATE,
            Permissions.SERVERS_DELETE,
            Permissions.SERVERS_MANAGE,
            # Tools
            Permissions.TOOLS_CREATE,
            Permissions.TOOLS_READ,
            Permissions.TOOLS_UPDATE,
            Permissions.TOOLS_DELETE,
            Permissions.TOOLS_EXECUTE,
            # Resources
            Permissions.RESOURCES_CREATE,
            Permissions.RESOURCES_READ,
            Permissions.RESOURCES_UPDATE,
            Permissions.RESOURCES_DELETE,
            Permissions.RESOURCES_SHARE,
            # Prompts
            Permissions.PROMPTS_CREATE,
            Permissions.PROMPTS_READ,
            Permissions.PROMPTS_UPDATE,
            Permissions.PROMPTS_DELETE,
            Permissions.PROMPTS_EXECUTE,
            # Agents
            Permissions.AGENTS_CREATE,
            Permissions.AGENTS_READ,
            Permissions.AGENTS_UPDATE,
            Permissions.AGENTS_DELETE,
            Permissions.AGENTS_EXECUTE,
            # Tokens
            Permissions.TOKENS_CREATE,
            Permissions.TOKENS_READ,
            Permissions.TOKENS_REVOKE,
            Permissions.TOKENS_SCOPE,
        ],
        "is_system_role": True,
    },
    {
        "name": "team_admin",
        "description": "Team administrator with management permissions",
        "scope": "team",
        "permissions": [
            # Team Management (No Delete)
            Permissions.TEAMS_READ,
            Permissions.TEAMS_UPDATE,
            Permissions.TEAMS_JOIN,
            Permissions.TEAMS_MANAGE_MEMBERS,
            # Gateways
            Permissions.GATEWAYS_CREATE,
            Permissions.GATEWAYS_READ,
            Permissions.GATEWAYS_UPDATE,
            Permissions.GATEWAYS_DELETE,
            # Servers
            Permissions.SERVERS_CREATE,
            Permissions.SERVERS_READ,
            Permissions.SERVERS_UPDATE,
            Permissions.SERVERS_DELETE,
            Permissions.SERVERS_MANAGE,
            # Tools
            Permissions.TOOLS_CREATE,
            Permissions.TOOLS_READ,
            Permissions.TOOLS_UPDATE,
            Permissions.TOOLS_DELETE,
            Permissions.TOOLS_EXECUTE,
            # Resources
            Permissions.RESOURCES_CREATE,
            Permissions.RESOURCES_READ,
            Permissions.RESOURCES_UPDATE,
            Permissions.RESOURCES_DELETE,
            Permissions.RESOURCES_SHARE,
            # Prompts
            Permissions.PROMPTS_CREATE,
            Permissions.PROMPTS_READ,
            Permissions.PROMPTS_UPDATE,
            Permissions.PROMPTS_DELETE,
            Permissions.PROMPTS_EXECUTE,
            # Agents
            Permissions.AGENTS_CREATE,
            Permissions.AGENTS_READ,
            Permissions.AGENTS_UPDATE,
            Permissions.AGENTS_DELETE,
            Permissions.AGENTS_EXECUTE,
            # Tokens
            Permissions.TOKENS_CREATE,
            Permissions.TOKENS_READ,
            Permissions.TOKENS_REVOKE,
            Permissions.TOKENS_SCOPE,
        ],
        "is_system_role": True,
    },
    {
        "name": "team_member",
        "description": "Developer with tool execution and resource access",
        "scope": "team",
        "permissions": [
            Permissions.TEAMS_JOIN,
            Permissions.TEAMS_READ,
            # Read-only on infrastructure
            Permissions.GATEWAYS_READ,
            Permissions.SERVERS_READ,
            # Execute/Read on capabilities
            Permissions.TOOLS_READ,
            Permissions.TOOLS_EXECUTE,
            Permissions.RESOURCES_READ,
            Permissions.PROMPTS_READ,
            Permissions.PROMPTS_EXECUTE,
            Permissions.AGENTS_READ,
            Permissions.AGENTS_EXECUTE,
            # Token management
            Permissions.TOKENS_CREATE,
            Permissions.TOKENS_READ,
            Permissions.TOKENS_REVOKE,
            Permissions.TOKENS_SCOPE,
        ],
        "is_system_role": True,
    },
    {
        "name": "team_viewer",
        "description": "Read-only access to resources",
        "scope": "team",
        "permissions": [
            Permissions.TEAMS_JOIN,
            Permissions.TEAMS_READ,
            Permissions.GATEWAYS_READ,
            Permissions.SERVERS_READ,
            Permissions.TOOLS_READ,
            Permissions.RESOURCES_READ,
            Permissions.PROMPTS_READ,
            Permissions.AGENTS_READ,
        ],
        "is_system_role": True,
    },
]

PERMISSION_MAPPINGS = {
    # Tools permissions
    ("GET", r"^/tools(?:$|/)"): Permissions.TOOLS_READ,
    ("POST", r"^/tools(?:$|/)"): Permissions.TOOLS_CREATE,
    ("PUT", r"^/tools/[^/]+(?:$|/)"): Permissions.TOOLS_UPDATE,
    ("DELETE", r"^/tools/[^/]+(?:$|/)"): Permissions.TOOLS_DELETE,
    ("GET", r"^/servers/[^/]+/tools(?:$|/)"): Permissions.TOOLS_READ,
    ("POST", r"^/servers/[^/]+/tools/[^/]+/call(?:$|/)"): Permissions.TOOLS_EXECUTE,
    # Resources permissions
    ("GET", r"^/resources(?:$|/)"): Permissions.RESOURCES_READ,
    ("POST", r"^/resources(?:$|/)"): Permissions.RESOURCES_CREATE,
    ("PUT", r"^/resources/[^/]+(?:$|/)"): Permissions.RESOURCES_UPDATE,
    ("DELETE", r"^/resources/[^/]+(?:$|/)"): Permissions.RESOURCES_DELETE,
    ("GET", r"^/servers/[^/]+/resources(?:$|/)"): Permissions.RESOURCES_READ,
    # Prompts permissions
    ("GET", r"^/prompts(?:$|/)"): Permissions.PROMPTS_READ,
    ("POST", r"^/prompts(?:$|/)"): Permissions.PROMPTS_CREATE,
    ("PUT", r"^/prompts/[^/]+(?:$|/)"): Permissions.PROMPTS_UPDATE,
    ("DELETE", r"^/prompts/[^/]+(?:$|/)"): Permissions.PROMPTS_DELETE,
    # Server management permissions
    ("GET", r"^/servers(?:$|/)"): Permissions.SERVERS_READ,
    ("POST", r"^/servers(?:$|/)"): Permissions.SERVERS_CREATE,
    ("PUT", r"^/servers/[^/]+(?:$|/)"): Permissions.SERVERS_UPDATE,
    ("DELETE", r"^/servers/[^/]+(?:$|/)"): Permissions.SERVERS_DELETE,
    # Admin permissions
    ("GET", r"^/admin(?:$|/)"): Permissions.ADMIN_USER_MANAGEMENT,
    ("POST", r"^/admin/[^/]+(?:$|/)"): Permissions.ADMIN_USER_MANAGEMENT,
    ("PUT", r"^/admin/[^/]+(?:$|/)"): Permissions.ADMIN_USER_MANAGEMENT,
    ("DELETE", r"^/admin/[^/]+(?:$|/)"): Permissions.ADMIN_USER_MANAGEMENT,
}
