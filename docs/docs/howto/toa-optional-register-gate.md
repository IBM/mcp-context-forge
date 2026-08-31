# Optional TOA verify before register / promote

How to add an optional offline Tool Outcome Attestation (`toa/0.1`) check before
registering or promoting an MCP server in ContextForge.

## Context

ContextForge already registers MCP servers, runs health checks, and applies
governance. That answers reachability and catalog state. It does not prove that
a tool recently delivered a real result under an outside probe.

[TOA](https://github.com/Carmel-Labs-Inc/toa) is an Apache-2.0 signed JSON
evidence format for MCP tool delivery (reach, invoke, functional, shape, and
related layers). It is not a wire protocol. It is not meant to run on every live
`tools/call`.

## When to use this

Optional, off by default. Use it in CI or change control before:

- Registering a new MCP server via Admin UI / API
- Promoting a catalog entry into production
- Enabling a virtual server that exposes new tools

Any party can emit if they sign the schema. AgentStatus is one optional emitter.
No AgentStatus account is required to verify.

## Example GitHub Actions step

```yaml
      # After your existing register / health / policy checks.
      - name: Verify tool delivery attestation
        if: hashFiles('toa.json') != ''
        run: |
          pip install "git+https://github.com/Carmel-Labs-Inc/toa.git@345f24607919b5bdf143719b9ea062543cdfe88e#subdirectory=python"
          toa-verify toa.json --require-layer functional=pass
```

Pin the emitter public key with the flags documented in the toa repo when you
need a specific signer.

## Full copy-paste workflow

```yaml
# .github/workflows/contextforge-toa.yml
name: Optional TOA before MCP register
on:
  workflow_dispatch:
  pull_request:
    paths:
      - "mcp-catalog.yml"
      - "toa.json"

jobs:
  toa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Your catalog lint / register dry-run steps go here.

      - name: Verify tool delivery attestation
        if: hashFiles('toa.json') != ''
        run: |
          pip install "git+https://github.com/Carmel-Labs-Inc/toa.git@345f24607919b5bdf143719b9ea062543cdfe88e#subdirectory=python"
          toa-verify toa.json --require-layer functional=pass
```

## Out of scope

- Replacing ContextForge health checks, RBAC, or plugins
- Signing every production `tools/call`
- Requiring a vendor account to verify

## See also

- [MCP Server Catalog](../manage/catalog.md)
- [RBAC for Tool Authorization](rbac-tool-authorization.md)

Raw workflow file: [toa-after-register.yml](toa-after-register.yml).
