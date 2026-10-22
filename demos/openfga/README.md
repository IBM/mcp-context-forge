# OpenFGA Policy Engine Demo

Four Bob Shell chats, one per demo user, calling fast-time tools through
ContextForge with Layer-2 RBAC enforced by [OpenFGA](https://openfga.dev).

```
bob-alice ─┐                                                        ┌─ fast-time
bob-becky ─┼─ MCP (Bearer <per-user API key>) ─> gateway ─> OpenFGA ─┤   server
bob-carol ─┤       /servers/<id>/mcp/        :8080   :18080         └─ (upstream)
bob-david ─┘
```

Every chat pane is a [bobshell](https://github.com/IBM/contextforge-examples/tree/main/infra/bobshell)
container. Its MCP config points at the `fast-time-demo` virtual server and
carries a freshly minted, scope-narrowed API key (`tools.read`,
`tools.execute`) for that pane's user. The gateway answers each call through
the OpenFGA engine: permission checks hit the Check API, and membership tuples
are derived at check time from the token's team claim.

## What gets created

| Object | Name | Purpose |
| --- | --- | --- |
| Federation gateway | `fast_time` | Points at the `fast_time_server` upstream |
| Virtual server | `fast-time-demo` | Public server carrying the 8 fast-time tools |
| Team | `OpenFGA Demo Team` | Anchors the role grants and the token team scope |
| Users | `alice@demo.example.com`, `becky@…`, `carol@…` | Non-admin, `developer` role on the demo team |
| David | `david@demo.example.com` | Server administrator: `demo-server-admin` role (servers + policy) and a `contextforge-policy` skill in his chat workspace |
| API keys | `bobshell-demo-<timestamp>` | One per user per launcher run, 1-day expiry |

## Prerequisites

- Docker with compose v2 (Docker Desktop, or colima — see
  [Troubleshooting](#troubleshooting) for colima specifics)
- `openssl`, `jq`, `curl`, `tmux`
- A Bob Shell inference API key from the
  [Bob web portal](https://bob.ibm.com/login) (`BOBSHELL_API_KEY`)
- Ports free: `8080` (nginx), `18080` (OpenFGA), `8888` (fast-time host port)

## Cold start

Run from the repository root, on a branch that carries the OpenFGA rule
provider (the published image does not include it).

### 1. Secrets

```bash
cp .env.example .env && make init-secrets-patch-env
```

Generates `JWT_SECRET_KEY`, `AUTH_ENCRYPTION_SECRET`, and
`PLATFORM_ADMIN_PASSWORD` into `.env`. The seeder and the chat launcher read
the admin password from there.

### 2. Build the gateway image

```bash
make docker-prod
```

### 3. OpenFGA credentials

```bash
export OPENFGA_API_TOKEN=$(openssl rand -hex 32)
export OPENFGA_DB_PASSWORD=$(openssl rand -hex 16)
```

Generate these **once** and keep them. The `openfgapgdata` volume is
initialized with the datastore password, so every later `up -d` must reuse
the same value. A new shell loses the exports — persist them in `.env` or a
password manager.

### 4. Bring up the stack

```bash
docker compose -f docker-compose.yml -f docker-compose.openfga.yml \
   -f demos/openfga/docker-compose.demo-openfga.yml \
   --profile openfga --profile demo up -d
```

This starts the base infrastructure, the OpenFGA engine, the gateway with
`RBAC_RULE_PROVIDER=openfga`, and the one-shot `demo-seed` service. Watch the
seeder finish (it exits 0 with a summary; it is idempotent, so re-running
just fills gaps):

```bash
docker compose -f docker-compose.yml -f docker-compose.openfga.yml \
   -f demos/openfga/docker-compose.demo-openfga.yml \
   --profile openfga --profile demo logs demo-seed
```

### 5. Open the chats

```bash
BOBSHELL_API_KEY=<your Bob inference key> demos/openfga/bob-chat.sh
```

The launcher:

1. Logs in as each demo user and mints a fresh team-scoped API key
2. Writes one bobshell `mcp.json` per user (workspace under `~/.cache/bob-demo.*`)
3. Stops any leftover `bob-*` containers from an earlier run
4. Opens a tmux session (`bob-demo`) with four panes labeled with each
   user's name on the pane's top border; each pane runs its container as
   the pane process, so closing a pane stops that container

Detach from tmux with `Ctrl-b d`; reattach with `tmux attach -t bob-demo`.
Ask a chat something like *"call fast-time-get-system-time for UTC"* to see a
call flow through the policy engine.

## Demoing the policy engine

Two levers, with different latencies:

**Immediate: revoke a user's API key.** Token revocation hits the very next
call. Revoke alice's key and her pane's tool calls fail with 401 while the
other three panes keep working:

```bash
# List alice's tokens (as admin), pick the bobshell-demo-* id, then:
curl -X DELETE http://localhost:8080/tokens/admin/<token-id> \
  -H "Authorization: Bearer $ADMIN_JWT"
```

Rerun `bob-chat.sh` to mint fresh keys and bring her chat back.

**Immediate for policy: forced reconciliation.** Any holder of
`rbac.rules.manage` (david) can converge the engine at once:

```bash
curl -X POST http://localhost:8080/rbac/rules/reconcile \
  -H "Authorization: Bearer $DAVID_KEY"
# -> {"provider":"openfga","applied":N}
```

The response counts tuple writes and deletes applied. Role and rule changes
become enforceable on the very next call instead of waiting for
`OPENFGA_RECONCILE_SECONDS`. The catalog overlay rules under `/rbac/rules`
apply on the `db` provider path; the openfga provider consults them only
when a check falls back to the database.

**David's chat is the policy console.** His workspace carries the
`contextforge-policy` skill: rule CRUD, tool-argument predicates
(`args.message == 'secret'`), forced MCP header parameters on the virtual
server, expiring rules (`expires_at`), and forced reconciliation. The skill
directs him to show the exact rule JSON and get an explicit go-ahead before
sending anything to ContextForge. Note: bob lists only its packaged skills
when asked what skills it has — user skills surface when used. Ask david to
use the contextforge-policy skill, or just describe the policy change; he
invokes it via `use_skill`.

The engine's raw state is inspectable at the OpenFGA API on
`http://localhost:18080` with `Authorization: Bearer $OPENFGA_API_TOKEN` —
see its stores for the mirrored role and parent tuples.

Each launcher run mints new keys (`bobshell-demo-<timestamp>`); revoke old
ones from the Admin UI token catalog when they pile up.

## Teardown

```bash
# Chats and containers
tmux kill-session -t bob-demo 2>/dev/null
docker rm -f bob-alice bob-becky bob-carol bob-david 2>/dev/null

# The stack (add -v to also drop the database and OpenFGA datastore volumes)
docker compose -f docker-compose.yml -f docker-compose.openfga.yml \
   -f demos/openfga/docker-compose.demo-openfga.yml \
   --profile openfga --profile demo down
```

## Troubleshooting

- **colima**: colima shares only the home directory with containers, and
  single-file bind mounts from the macOS temp tree (`/var/folders`, `/tmp`)
  render as directories. The launcher anchors its workspace under
  `~/.cache` and mounts per-user directories, which avoids both.
- **Linux hosts**: `host.docker.internal` needs the `host-gateway` mapping —
  the launcher passes `--add-host=host.docker.internal:host-gateway`, which
  works on Docker Desktop and colima too. If your backend rejects it, set
  `GATEWAY_URL=http://<docker0-IP>:8080`.
- **Leftover chats**: closing a tmux pane does not reliably stop its
  container on every backend; the launcher force-removes `bob-*` containers
  at startup, so just rerun it.
- **`demo-seed` waiting**: it blocks until the gateway is healthy and the
  fast-time tools sync (up to ~60 s). Its log names whichever step it is on.
- **Key mint 400**: the demo users' `developer` role is what authorizes
  `tools.execute` inside a token scope. If minting fails, rerun the seeder —
  it repairs missing users, team, and role grants.
