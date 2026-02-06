# Example OPA policy for APEX CDM MessageView
#
# This policy demonstrates how to write Rego rules that evaluate
# the JSON structure produced by MessageView.to_dict()
#
# Deploy to OPA:
#   opa run --server example_policy.rego
#
# Test:
#   curl -X POST http://localhost:8181/v1/data/apex/allow \
#     -H "Content-Type: application/json" \
#     -d '{"input": {"kind": "tool_call", "name": "read_file", "uri": "tool://_/read_file"}}'

package apex

import future.keywords.in

default allow = false

# =============================================================================
# Allow Rules
# =============================================================================

# Allow text content (no tool calls)
allow {
    input.kind == "text"
}

# Allow thinking content
allow {
    input.kind == "thinking"
}

# Allow safe read-only tools
allow {
    input.kind == "tool_call"
    startswith(input.name, "read_")
}

allow {
    input.kind == "tool_call"
    startswith(input.name, "search_")
}

allow {
    input.kind == "tool_call"
    startswith(input.name, "list_")
}

# Allow tools for admin users
allow {
    input.kind == "tool_call"
    "admin" in input.context.principal.roles
}

# Allow resources from safe paths
allow {
    input.kind == "resource"
    startswith(input.uri, "file:///workspace/")
}

allow {
    input.kind == "resource_ref"
    startswith(input.uri, "file:///workspace/")
}

# =============================================================================
# Deny Rules (with reasons)
# =============================================================================

# Deny dangerous tools
deny[msg] {
    input.kind == "tool_call"
    dangerous_tools[input.name]
    msg := sprintf("Tool '%s' is not allowed", [input.name])
}

dangerous_tools := {
    "execute_shell",
    "eval",
    "exec",
    "run_command",
    "delete_file",
    "rm",
}

# Deny shell execution in production
deny[msg] {
    input.kind == "tool_call"
    input.name == "execute_shell"
    input.context.environment == "production"
    msg := "Shell execution is blocked in production environment"
}

# Deny access to sensitive files
deny[msg] {
    input.kind in ["resource", "resource_ref"]
    sensitive_path(input.uri)
    msg := sprintf("Access to sensitive path '%s' is denied", [input.uri])
}

sensitive_path(uri) {
    contains(uri, "/.env")
}

sensitive_path(uri) {
    contains(uri, "/secrets/")
}

sensitive_path(uri) {
    contains(uri, "/credentials")
}

sensitive_path(uri) {
    startswith(uri, "file:///etc/")
}

# Deny large content without admin role
deny[msg] {
    input.size_bytes > 1048576  # 1MB
    not "admin" in input.context.principal.roles
    msg := sprintf("Content size %d bytes exceeds limit for non-admin users", [input.size_bytes])
}

# =============================================================================
# Full Message Evaluation (when evaluate_per_view=false)
# =============================================================================

# For message-level evaluation, check all views
message_allow {
    not message_deny[_]
    some i
    input.views[i]
    view_allow(input.views[i])
}

view_allow(view) {
    view.kind == "text"
}

view_allow(view) {
    view.kind == "tool_call"
    startswith(view.name, "read_")
}

message_deny[msg] {
    some i
    view := input.views[i]
    view.kind == "tool_call"
    dangerous_tools[view.name]
    msg := sprintf("Message contains dangerous tool: %s", [view.name])
}

# =============================================================================
# Audit Logging
# =============================================================================

# Log all tool calls for audit
audit[entry] {
    input.kind == "tool_call"
    entry := {
        "type": "tool_call",
        "name": input.name,
        "uri": input.uri,
        "principal": input.context.principal.id,
        "environment": input.context.environment,
    }
}
