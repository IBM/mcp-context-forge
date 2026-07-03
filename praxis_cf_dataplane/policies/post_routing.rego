# Post-Routing Authorization Policy
#
# Evaluates authorization AFTER routing decision is made.
# Checks if user has access to the gateway or upstream server.
#
# Input Metadata (from cf_tools_router and cf_control_plane_data):
# - input.route: Routing decision ("gateway" or "upstream")
# - input.gateway_id: Gateway ID (if route=gateway)
# - input.upstream_url: Upstream server URL (if route=upstream)
# - input.user_email: User's email address
# - input.teams: Array of team memberships
# - input.is_admin: Admin flag
# - input.user_allowed_gateways: Array of gateway IDs user can access
# - input.user_allowed_upstreams: Array of upstream URLs user can access
#
# Output:
# - allow: boolean (true if authorized, false otherwise)
# - reason: string (explanation if denied)

package contextforge.post_routing

import future.keywords.if
import future.keywords.in

# Default deny
default allow := false

# Allow if user is admin (bypass all checks)
allow if {
    input.is_admin == true
}

# Allow gateway route if user has access to gateway
allow if {
    input.route == "gateway"
    has_gateway_access
}

# Allow upstream route if user has access to upstream server
allow if {
    input.route == "upstream"
    has_upstream_access
}

# Helper: Check if user has access to gateway
has_gateway_access if {
    # Admin bypass
    input.is_admin == true
}

has_gateway_access if {
    # For tools/list and initialize/ping, gateway access is implicitly granted
    # if user passed pre-routing authorization
    not input.gateway_id
}

has_gateway_access if {
    # Check if user has access to specific gateway
    input.gateway_id in input.user_allowed_gateways
}

# Helper: Check if user has access to upstream server
has_upstream_access if {
    # Admin bypass
    input.is_admin == true
}

has_upstream_access if {
    # Check if user has access to specific upstream server
    input.upstream_url in input.user_allowed_upstreams
}

# Denial reasons (for debugging)
reason := "User is not authenticated" if {
    not allow
    input.user_email == ""
}

reason := "User does not have access to gateway" if {
    not allow
    input.route == "gateway"
    input.gateway_id
    not has_gateway_access
}

reason := "User does not have access to upstream server" if {
    not allow
    input.route == "upstream"
    not has_upstream_access
}

reason := "Invalid routing decision" if {
    not allow
    not input.route in ["gateway", "upstream"]
}

reason := "Missing gateway_id for gateway route" if {
    not allow
    input.route == "gateway"
    input.gateway_id == ""
}

reason := "Missing upstream_url for upstream route" if {
    not allow
    input.route == "upstream"
    input.upstream_url == ""
}
