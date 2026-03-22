# Authorize Tools in a Virtual Server Using RBAC

This guide walks through configuring RBAC so that specific users can list and execute
tools exposed through a virtual server, while others are restricted to read-only access
or blocked entirely. The scenario used throughout is an analytics team with data-query
tools — such as `run-query` and `db-migrate` — on a production virtual server.
Developers on the team need to both list and execute tools. Viewers should be able to
browse available tools but not execute them. A sensitive `db-migrate` tool should be
restricted by controlling who holds the `tools.execute` permission.

---

## Prerequisites

!!! info "Prerequisites"

    - A running ContextForge instance with `AUTH_REQUIRED=true`
    - At least one team created ([Team Management](../manage/teams.md))
    - At least one user with team membership
    - A virtual server with registered gateway(s) and tools
    - For setup from scratch, see [Deployment](../deployment/index.md) and [Security Configuration](../manage/securing.md)

---

## How the Two-Layer Model Applies to Tools

ContextForge enforces a two-layer security model on every tool operation.
Layer 1 — token scoping — uses the `teams` claim in the caller's JWT to determine
which tools the user can *see*, based on each tool's `visibility` setting and
`team_id`. Layer 2 — RBAC — checks the user's role permissions (`tools.read`,
`tools.execute`) to determine which *actions* are allowed on the tools that passed
Layer 1. Both layers must pass for a tool call to succeed; a user who can see a tool
but lacks the `tools.execute` permission will receive a 403 Forbidden response.
Conversely, a user with the correct role but a token scoped to the wrong team will
not see the tool at all.

```
Request --> Token Scoping (Can see this tool?) --> RBAC Check (Can execute?) --> Tool runs
```

In the analytics scenario, this means a developer's JWT must contain the analytics
team UUID in its `teams` claim (Layer 1) *and* the developer must hold a role that
includes `tools.execute` (Layer 2). A viewer on the same team passes Layer 1 but is
stopped at Layer 2 when attempting execution.

For the full reference on roles, permissions, and token scoping semantics, see
[RBAC Configuration](../manage/rbac.md).

---

## Step 1: Set Tool Visibility

Tools inherit their visibility from how they are registered, defaulting to `private`.
A private tool is visible only to its owner and platform administrators with bypass
tokens. For team members to see a tool, set its visibility to `team` — this restricts discovery to users whose JWT
contains the matching team UUID. To make a tool visible to all authenticated users
regardless of team membership, set visibility to `public`.

For the analytics scenario, set the data-query tools to `team` visibility so that
only analytics team members can discover them.

=== "API / CLI"

    ```bash
    curl -X PUT "$GATEWAY_URL/tools/$TOOL_ID" \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"visibility": "team"}'
    ```

=== "Admin UI"

    1. Navigate to **Admin > Tools**
    2. Select the tool to configure
    3. Change **Visibility** to **Team**
    4. Click **Save**

!!! tip

    Setting visibility to `public` makes the tool visible to all authenticated users across all teams. Use `team` to restrict visibility to members of the owning team only. For the analytics scenario, `team` is the appropriate choice — it ensures only analytics team members can discover the data-query tools.

---

## Step 2: Assign an RBAC Role

The three built-in roles most relevant to tool access are:

| Role | `tools.read` | `tools.execute` | Use case |
|------|:---:|:---:|------|
| `viewer` | Yes | No | Browse tools without executing |
| `developer` | Yes | Yes | List and execute tools |
| `team_admin` | Yes | Yes | Full team management plus tool access |

Assign the `developer` role to users who need to execute tools, and the `viewer`
role to users who should only browse. Roles are scoped to a specific team, so the
same user can hold different roles on different teams — for example, `developer` on
the analytics team but `viewer` on the infrastructure team.

=== "API / CLI"

    ```bash
    curl -X POST "$GATEWAY_URL/rbac/users/analyst@example.com/roles" \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"role_id": "developer", "scope": "team", "scope_id": "<analytics-team-uuid>"}'
    ```

=== "Admin UI"

    1. Navigate to **Admin > Users**
    2. Select the user
    3. Under **Roles**, click **Add Role**
    4. Select **developer** and choose the analytics team as scope
    5. Click **Save**

!!! note "Custom Roles"

    For fine-grained control — for example, a role with `tools.read` but not `tools.execute` for specific teams — create custom roles via bootstrap configuration. This is useful when you need granularity beyond the built-in roles, such as allowing a contractor to see tool definitions without being able to invoke them. See [Bootstrap Custom Roles](../manage/rbac.md#bootstrap-custom-roles).

---

## Step 3: Generate a Scoped Token

API tokens must include the team in the `teams` JWT claim so that Layer 1 (token
scoping) grants visibility to team-scoped resources. Without the correct team UUID
in the token, the user will only see public tools — regardless of their RBAC role.
Session tokens created through the Admin UI login flow resolve team memberships
automatically from the database, so this step applies primarily to programmatic API
access and CI/CD integrations.

=== "API / CLI"

    ```bash
    python3 -m mcpgateway.utils.create_jwt_token \
      --data '{"sub":"analyst@example.com","is_admin":false,"teams":["<analytics-team-uuid>"],"token_use":"api"}' \
      --exp 60 \
      --secret "$JWT_SECRET_KEY"
    ```

    Then export the token for use in subsequent requests:

    ```bash
    export TOKEN="<output-from-above>"
    ```

=== "Admin UI"

    1. Navigate to **Admin > Tokens**
    2. Click **Create Token**
    3. Select the **analytics** team under team scope
    4. Set an appropriate expiration
    5. Copy the generated token

!!! warning

    Tokens created without selecting a team default to public-only access (`teams: []`). They will not see team-scoped tools even if the user has the correct RBAC role. Always verify the `teams` claim is populated before distributing a token.

---

## Step 4: Verify Access

Run the following checks to confirm that the two-layer model is enforcing access as
expected. These four scenarios cover the primary access patterns: successful listing,
successful execution, permission denial, and team isolation.

### Developer lists tools

A developer's token scoped to the analytics team should return team-scoped tools:

```bash
curl -s "$GATEWAY_URL/tools" \
  -H "Authorization: Bearer $DEVELOPER_TOKEN" | jq '.[].name'
```

Expected result: the response includes the analytics team's tools such as `run-query`.

### Developer executes a tool

The developer should be able to invoke a tool successfully. Tool invocation uses
JSON-RPC 2.0 via the `/rpc` endpoint:

```bash
curl -X POST "$GATEWAY_URL/rpc" \
  -H "Authorization: Bearer $DEVELOPER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "run-query", "arguments": {"sql": "SELECT count(*) FROM events"}}}'
```

Expected result: a JSON-RPC response with the tool's output in the `result` field.

### Viewer attempts execution

A viewer has `tools.read` but not `tools.execute`, so the same call should be rejected:

```bash
curl -X POST "$GATEWAY_URL/rpc" \
  -H "Authorization: Bearer $VIEWER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "run-query", "arguments": {"sql": "SELECT count(*) FROM events"}}}'
# Expected: JSON-RPC error with code -32603 (403 Forbidden)
```

Expected result: a JSON-RPC error response. The viewer can list tools but cannot invoke them.

### User from another team

A token scoped to a different team should not see team-scoped analytics tools at all:

```bash
curl -s "$GATEWAY_URL/tools" \
  -H "Authorization: Bearer $OTHER_TEAM_TOKEN" | jq '.[].name'
```

Expected result: the analytics team's tools are absent from the response. Only
tools with `public` visibility appear. This confirms that Layer 1 (token scoping)
is filtering correctly based on the `teams` claim.

!!! tip

    To inspect the claims in any JWT token, decode it locally:

    ```bash
    echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq .
    ```

    Verify that `teams` contains the expected team UUID and that `sub` matches the intended user.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Tool not visible (empty list or 404) | Token missing `teams` claim or wrong team UUID | Decode JWT and verify `teams` includes the tool's `team_id` |
| 403 on tool execution | User has `viewer` role (no `tools.execute`) | Assign `developer` or `team_admin` role for the team |
| Admin token seeing only public tools | Token has `teams: []` (explicit empty list) | Use `teams: null` with `is_admin: true` for admin bypass |
| Tool visible but execution returns 500 | Upstream gateway unreachable | Check gateway health: `GET /gateways/{id}` |

For more details, see [Troubleshooting](../manage/rbac.md#troubleshooting) in the
RBAC reference.

!!! note "Debugging tip"

    When diagnosing access issues, work through the layers in order. First confirm
    the tool appears in the response to `GET /tools` (Layer 1 — token scoping). If
    the tool is missing, the problem is visibility or token claims. If the tool is
    listed but execution fails with 403, the problem is RBAC permissions (Layer 2).
    If execution fails with 500, the issue is likely upstream gateway connectivity
    rather than authorization.

---

## Related Documentation

- [RBAC Configuration](../manage/rbac.md) — Full reference for roles, permissions, and token scoping
- [Team Management](../manage/teams.md) — Creating teams and SSO group mapping
- [Security Configuration](../manage/securing.md) — Authentication setup and token lifecycle
- [Multi-Tenancy Architecture](../architecture/multitenancy.md) — Visibility model and resource scoping
