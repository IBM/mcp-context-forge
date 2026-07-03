# Pre-Routing Authorization Policy
#
# Evaluates authorization BEFORE routing decision is made.
# Checks if user has access to virtual server and if tool is exposed.
#
# Input Metadata (from cf_control_plane_data and McpFilter):
# - input.method: MCP method (e.g., "tools/call", "tools/list")
# - input.name: Tool name (for tools/call)
# - input.user_email: User's email address
# - input.teams: Array of team memberships
# - input.is_admin: Admin flag
# - input.virtual_server_tools: Array of exposed tool names
# - input.virtual_server_access_policy: Object with allowed_teams, allowed_users, require_admin
#
# Output:
# - allow: boolean (true if authorized, false otherwise)
# - reason: string (explanation if denied)

package contextforge.pre_routing

import future.keywords.if
import future.keywords.in

# Default deny
default allow := false

# Allow if user is admin (bypass all checks)
allow if {
    input.is_admin == true
}

# Allow tools/call if tool is exposed and user has access
allow if {
    input.method == "tools/call"
    input.name in input.virtual_server_tools
    has_virtual_server_access
}

# Allow tools/list if user has access to virtual server
allow if {
    input.method == "tools/list"
    has_virtual_server_access
}

# Allow initialize and ping for all authenticated users
allow if {
    input.method in ["initialize", "ping"]
    input.user_email != ""
}

# Allow resources/* and prompts/* if user has access to virtual server
allow if {
    startswith(input.method, "resources/")
    has_virtual_server_access
}

allow if {
    startswith(input.method, "prompts/")
    has_virtual_server_access
}

# Helper: Check if user has access to virtual server
has_virtual_server_access if {
    # Admin bypass
    input.is_admin == true
}

has_virtual_server_access if {
    # Check if admin is required
    not input.virtual_server_access_policy.require_admin
    
    # Check team membership
    some team in input.teams
    team in input.virtual_server_access_policy.allowed_teams
}

has_virtual_server_access if {
    # Check if admin is required
    not input.virtual_server_access_policy.require_admin
    
    # Check specific user allowlist
    input.user_email in input.virtual_server_access_policy.allowed_users
}

# Denial reasons (for debugging)
reason := "User is not authenticated" if {
    not allow
    input.user_email == ""
}

reason := "Tool not exposed on virtual server" if {
    not allow
    input.method == "tools/call"
    not input.name in input.virtual_server_tools
}

reason := "User does not have access to virtual server" if {
    not allow
    input.user_email != ""
    not has_virtual_server_access
}

reason := "Admin access required" if {
    not allow
    input.virtual_server_access_policy.require_admin == true
    input.is_admin != true
}

reason := "Method not allowed" if {
    not allow
    not input.method in ["tools/call", "tools/list", "initialize", "ping"]
    not startswith(input.method, "resources/")
    not startswith(input.method, "prompts/")
}
