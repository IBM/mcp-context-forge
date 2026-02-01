# Unified Policy Decision Point (PDP)

A single plugin that orchestrates access-control decisions across multiple policy engines. Hooks into `tool_pre_invoke` and `resource_pre_fetch` — every tool call and resource read is checked before it reaches the backend.

---

## How It Works

```
Gateway request
      │
      ▼
┌─────────────────┐
│  UnifiedPDP     │   ← plugin class (unified_pdp.py)
│  Plugin         │
└────────┬────────┘
         │  builds Subject, Resource, Context from hook payload
         ▼
┌─────────────────┐
│  PolicyDecision │   ← orchestrator (pdp.py)
│  Point          │
└────────┬────────┘
         │  fans out to enabled engines
         ▼
┌──────────────────────────────────────────┐
│  Native RBAC │ MAC │ OPA │ Cedar        │
└──────────────────────────────────────────┘
         │  decisions combined via combination_mode
         ▼
┌─────────────────┐
│  ALLOW / DENY   │   ← cached, returned to gateway
└─────────────────┘
```

1. The gateway calls `tool_pre_invoke` or `resource_pre_fetch` on the plugin.
2. The plugin extracts a `Subject` (from the authenticated user), a `Resource` (from the payload), and a `Context` (request metadata).
3. `PolicyDecisionPoint.check_access()` fans the request out to all enabled engines.
4. Engine decisions are merged according to the configured `combination_mode`.
5. The result is cached (if enabled) and returned — ALLOW passes through, DENY blocks with a `PluginViolation`.

---

## Engines

| Engine | Requires sidecar | Notes |
|--------|-----------------|-------|
| **Native RBAC** | No | Pure Python, role-based rules in JSON |
| **MAC** | No | Bell-LaPadula mandatory access control |
| **OPA** | Yes | Rego policies via OPA server |
| **Cedar** | Yes | Amazon Cedar policies via cedar-agent |

### Starting sidecars

**OPA:**
```bash
docker run -p 8181:8181 openpolicyagent/opa:latest run --server
```

**Cedar:** See PR #1499 for cedar-agent deployment instructions.

---

## Quick Start

### 1. Enable the plugin

In `plugins/config.yaml`, change `mode` from `disabled` to `enforce`:

```yaml
- name: "UnifiedPDPPlugin"
  kind: "plugins.unified_pdp.unified_pdp.UnifiedPDPPlugin"
  mode: "enforce"
  priority: 10
  config:
    engines:
      - name: native
        enabled: true
        priority: 1
        settings:
          rules_file: "plugins/unified_pdp/default_rules.json"
    combination_mode: "all_must_allow"
    default_decision: "deny"
    cache:
      enabled: true
      ttl_seconds: 60
      max_entries: 10000
```

### 2. Restart the gateway

The plugin is now active. All tool invocations and resource fetches will be checked.

### 3. Write your own rules

Edit `default_rules.json` or point `rules_file` at your own file. Example — allow only the `finance` team to invoke `billing-api`:

```json
[
  {
    "id": "finance.billing-api",
    "roles": ["finance"],
    "actions": ["tools.invoke.billing-api"],
    "resource_types": ["tool"],
    "resource_ids": ["billing-api"],
    "reason": "Only finance team may invoke billing-api"
  }
]
```

### 4. Add MAC if you need classification levels

Enable MAC alongside Native RBAC and set clearance/classification levels on your subjects and resources:

```yaml
engines:
  - name: native
    enabled: true
    priority: 1
    settings:
      rules_file: "plugins/unified_pdp/default_rules.json"
  - name: mac
    enabled: true
    priority: 2
    settings:
      relaxed_star: false   # strict Bell-LaPadula
```

With `combination_mode: "all_must_allow"`, a request must pass both Native RBAC *and* MAC to be allowed.

---

## Data Models

### Subject — the entity requesting access

Populated automatically from the gateway's authenticated user context.

| Field | Type | Description |
|-------|------|-------------|
| `email` | `str` | User identifier. Falls back to `"anonymous@internal"` if no user. |
| `roles` | `list[str]` | Role list from the auth token |
| `team_id` | `str \| None` | Team identifier |
| `mfa_verified` | `bool` | Whether MFA was completed this session |
| `clearance_level` | `int \| None` | MAC clearance level (required for MAC engine) |
| `attributes` | `dict` | Arbitrary extra attributes |

### Resource — the thing being accessed

Populated automatically from the hook payload.

| Field | Type | Description |
|-------|------|-------------|
| `type` | `str` | `"tool"` or `"resource"` (set by the hook) |
| `id` | `str` | Tool name or resource URI |
| `server` | `str \| None` | MCP server that owns this resource |
| `classification_level` | `int \| None` | MAC classification level (required for MAC engine) |
| `annotations` | `dict` | Arbitrary metadata |

### Context — ambient request info

| Field | Type | Description |
|-------|------|-------------|
| `ip` | `str \| None` | Client IP address |
| `timestamp` | `datetime` | Request time (auto-set to now) |
| `user_agent` | `str \| None` | Client user agent |
| `session_id` | `str \| None` | Session identifier |
| `extra` | `dict` | Arbitrary extra context |

### Action strings

Actions follow a dotted hierarchy so policies can match broadly or narrowly:

| Hook | Action format | Example |
|------|--------------|---------|
| `tool_pre_invoke` | `tools.invoke.<tool_name>` | `tools.invoke.billing-api` |
| `resource_pre_fetch` | `resources.fetch` | `resources.fetch` |

Use wildcards in rules to match broadly: `tools.invoke.*` matches any tool invocation.

---

## Configuration Reference

### Engines

Each engine entry:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | One of: `native`, `mac`, `opa`, `cedar` |
| `enabled` | `bool` | Toggle without removing the block |
| `priority` | `int` | Lower = evaluated first (matters for `first_match` mode) |
| `settings` | `dict` | Engine-specific config (see below) |

#### Native RBAC settings

| Field | Description |
|-------|-------------|
| `rules_file` | Path to a JSON rules file |
| `rules` | Inline rules array (alternative to `rules_file`) |

Each rule in the JSON file:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique rule identifier |
| `roles` | `list[str]` | Roles this rule applies to. `"*"` = all roles |
| `actions` | `list[str]` | Actions this rule matches. Supports `*` wildcards |
| `resource_types` | `list[str]` | Resource types (`tool`, `resource`, etc.). `"*"` = all |
| `resource_ids` | `list[str]` | Specific resource IDs. `"*"` = all |
| `conditions` | `dict` | Optional conditions (e.g. `{"subject.mfa_verified": false}`) |
| `reason` | `str` | Human-readable explanation shown on deny |

#### MAC settings

| Field | Default | Description |
|-------|---------|-------------|
| `relaxed_star` | `false` | `false` = strict BLP (write only at same clearance level). `true` = allow write at same or lower level |

Bell-LaPadula rules enforced:
- **Read:** Subject clearance must be ≥ resource classification (simple security property)
- **Write (strict):** Subject clearance must equal resource classification (star property)
- **Write (relaxed):** Subject clearance must be ≥ resource classification

#### OPA settings

| Field | Default | Description |
|-------|---------|-------------|
| `opa_url` | `http://localhost:8181` | OPA server base URL |
| `policy_path` | `mcpgateway` | Decision path prefix |
| `timeout_ms` | `5000` | Per-request timeout |
| `max_retries` | `3` | Retry count on connection failure |

#### Cedar settings

| Field | Default | Description |
|-------|---------|-------------|
| `cedar_url` | `http://localhost:8700` | Cedar agent base URL |
| `timeout_ms` | `5000` | Per-request timeout |
| `max_retries` | `3` | Retry count on connection failure |

### Combination Modes

Controls how multiple engine decisions are merged into a single ALLOW/DENY:

| Mode | Behaviour | Use case |
|------|-----------|----------|
| `all_must_allow` | Every enabled engine must ALLOW. One DENY blocks. | Defence in depth — RBAC *and* MAC must both pass |
| `any_allow` | At least one engine must ALLOW. | Engines are alternatives — RBAC *or* MAC |
| `first_match` | Engines sorted by priority (ascending). First non-error decision wins. | Layered fallback — try OPA first, fall back to native |

### Cache

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Toggle decision caching |
| `ttl_seconds` | `60` | Cache entry lifetime in seconds |
| `max_entries` | `10000` | Max cached decisions before LRU eviction |

Cache key is built from: subject email + action + resource type + resource ID. Changing any of these invalidates the cache entry.

### Performance

| Field | Default | Description |
|-------|---------|-------------|
| `timeout_ms` | `1000` | Per-engine evaluation timeout |
| `parallel_evaluation` | `true` | Run engines concurrently via asyncio |

---

## Default Rules

`default_rules.json` ships with these starter rules:

| Rule ID | Who | Can do what |
|---------|-----|-------------|
| `default.admin-full-access` | `admin`, `platform_admin` | Everything |
| `default.developer-read-tools` | `developer` | List, get, describe tools |
| `default.developer-invoke-tools` | `developer` | Invoke any tool |
| `default.developer-read-resources` | `developer` | Fetch and list resources |
| `default.viewer-read-only` | `viewer` | List tools, list/fetch resources |
| `deny:no-mfa-destructive` | Everyone | Blocks delete/update operations when MFA is not verified |

**Tighten these rules before going to production.**

---

## Related Issues

| Issue | Scope |
|-------|-------|
| **#2223** | This plugin (unified PDP) |
| #2224 | Compliance reporting |
| #2225 | Audit trail |
| #2226 | Admin UI |
| #2227 | REST API endpoints |
| #2238 | GitOps integration |
