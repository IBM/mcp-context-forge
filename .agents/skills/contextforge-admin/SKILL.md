---
name: contextforge-admin
description: Operate a ContextForge gateway through its management API. Use for accounts, team membership, role assignments, upstream MCP servers, tool discovery, and virtual MCP tool selection.
---

# ContextForge administration

Use this skill from a harness that can run Python 3.10+ and reach the gateway. Supply the intended gateway URL on every run. Set `CONTEXTFORGE_TOKEN` to a bearer token with the rights for the task, or set `CONTEXTFORGE_EMAIL` and `CONTEXTFORGE_PASSWORD` to sign in with a ContextForge account. Inject credentials through the harness secret store.

Run from the skill directory.

```sh
python scripts/cf_api.py --base-url https://gateway.example.com request GET /v1/teams/
python scripts/cf_api.py --base-url https://gateway.example.com describe PUT '/v1/virtual-servers/{server_id}'
```

Read [operations.md](references/operations.md) for the relevant endpoint and the state to check afterward. The examples were verified with ContextForge 1.1.1 and 1.1.2. Use the target gateway's OpenAPI description to check request fields on other versions.

## Change a configuration

1. Read the object and its current associations. Resolve the target by ID before writing.
2. For an authorized change, put just the intended fields in a local JSON file. Pass it with `--body-file` and add `--write`. Keep secret-bearing files out of shared workspaces and repositories.
3. Read the result back and check the affected associations. If the response timed out, read the current state before trying again.

Use the account affected by a permission change to verify MCP access. Gateway permissions control access to tools. The upstream service still controls access to its data.
