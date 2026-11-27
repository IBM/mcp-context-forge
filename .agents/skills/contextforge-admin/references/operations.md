# Common operations

The paths below use the versioned API in ContextForge 1.1.1 and 1.1.2. Run `describe METHOD 'PATH'` for the request schema. Replace brace-delimited IDs and URL-encode email addresses used in path segments. Follow pagination when looking up an object.

| Task | Method and path | Check after the change |
| --- | --- | --- |
| List or create accounts | `GET` or `POST /v1/auth/email/admin/users` | Account email, active status, and admin flag |
| Inspect or update an account | `GET` or `PATCH /v1/auth/email/admin/users/{user_email}` | Requested account fields |
| List or create teams | `GET` or `POST /v1/teams/` | Team ID and visibility |
| Inspect or update a team | `GET` or `PUT /v1/teams/{team_id}` | Same team ID and intended fields |
| List or add members | `GET` or `POST /v1/teams/{team_id}/members` | Member, membership role, and resulting permissions |
| Edit or remove a member | `PUT` or `DELETE /v1/teams/{team_id}/members/{user_email}` | Membership and remaining role assignments |
| List or create roles | `GET` or `POST /v1/rbac/roles` | Role scope and permission set |
| List or assign roles to a user | `GET` or `POST /v1/rbac/users/{user_email}/roles` | Role ID, scope, and scope ID |
| Read effective permissions | `GET /v1/rbac/permissions/user/{user_email}` | Effective permissions in the relevant scope |
| List or register upstream MCP servers | `GET` or `POST /v1/mcp-servers` | URL, transport, enabled state, and team visibility |
| Inspect or update an upstream | `GET` or `PUT /v1/mcp-servers/{gateway_id}` | Same upstream ID and intended settings |
| Refresh upstream tools | `POST /v1/mcp-servers/{gateway_id}/tools/refresh?include_resources=false&include_prompts=false` | Added and removed tools and existing virtual server links |
| List tools and their sources | `GET /v1/tools` | Tool ID and upstream ID (`gatewayId`, also `mcpServerId` in 1.1.2) |
| List or create virtual MCP servers | `GET` or `POST /v1/virtual-servers` | Owner team, visibility, auth settings, and selected tools |
| Inspect or update a virtual MCP server | `GET` or `PUT /v1/virtual-servers/{server_id}` | Exact `associatedToolIds` set |
| Read a virtual server's tools | `GET /v1/virtual-servers/{server_id}/tools` | Selected tools visible to the caller |

## Accounts and access

Add people to shared teams. Personal teams belong to their account owners and reject membership changes. For an existing account, a membership request can use `{"email":"member@example.com","role":"member"}`. Membership can create a default RBAC assignment. Check existing roles before granting another one.

A separate team-scoped role assignment uses `{"role_id":"ROLE_ID","scope":"team","scope_id":"TEAM_ID"}`. To revoke a role assignment, check the live schema for `DELETE /v1/rbac/users/{user_email}/roles/{role_id}` and supply its exact scope. Inviting someone can send email, so use the direct membership endpoint for existing users when the task is only to grant access.

## Upstreams and tool selection

Use the upstream's existing MCP URL, transport, and authentication. Preserve OAuth credentials separately from config snapshots because read responses may mask them. A refresh may remove stale tools and affect existing associations. Inspect the current inventory and links before refreshing.

Select tools by ID and source. Creation uses a wrapped `server` object. Check its team, visibility, and authentication settings before exposing an endpoint.

Updating `associatedTools` replaces the entire selection. Save the old ID list and include every tool that should remain. For example, save `{"associatedTools":["TOOL_ID_A","TOOL_ID_B"]}` in `selection.json` and use the real server and tool IDs.

```sh
python scripts/cf_api.py --base-url https://gateway.example.com request PUT /v1/virtual-servers/SERVER_ID --body-file selection.json --write
python scripts/cf_api.py --base-url https://gateway.example.com request GET /v1/virtual-servers/SERVER_ID
```

Compare the read-back IDs with the intended set. Restore the old list if the change needs to be undone. When verifying access, use the target user's own connection to the virtual endpoint and list its tools.
