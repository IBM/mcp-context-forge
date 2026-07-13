# Gateway-Side Plugin Metrics Rollout (5 remaining cpex-* plugins) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once `IBM/cpex-plugins#129` ships metrics emission for `secrets_detection`, `encoded_exfil_detection`, `url_reputation`, `rate_limiter`, `retry_with_backoff`, wire the gateway to actually consume it: extend the S4 sanitizer allowlist, flip each plugin's `mode:` in `plugins/config.yaml`, bump the version floor in `pyproject.toml`, and extend e2e coverage. Closes `IBM/mcp-context-forge#5554`. Companion plugin-side plan: `IBM/cpex-plugins` `docs/superpowers/plans/2026-07-13-otel-plugin-metrics-rollout.md` (other repo).

**Architecture:** `mcpgateway/plugins/utils.py`'s `record_plugin_metrics()` / `_sanitize_plugin_metrics()` (landed in `#5470`) is already **generic per plugin namespace** — it does not need new code paths per plugin. What it needs is **data**: two allowlists (`_SAFE_STRING_FIELD_NAMES`, `_SAFE_NUMERIC_FIELD_NAMES`) currently contain only `pii_filter`'s fields. The code even carries an explicit forward-reference comment (verified, `mcpgateway/plugins/utils.py:88-91` and `99-103`): *"New plugins that add a string/numeric-valued metadata field must extend this set explicitly — see #5554 and cpex-plugins#129"*. This plan is that extension, plus the config/version bookkeeping issue #5554 also asks for.

**Scope is SMALLER than it looks — G0 plumbing is already complete (verified).** `docs/docs/manage/observability/internal-observability.md` states: *"all 17 gateway-side `invoke_hook()` call sites pass trace context in (`extensions=`) and consume `result.metadata` out."* So the gateway **already builds and passes trace context to every plugin and already calls `record_plugin_metrics()` after every hook** — there is **no new plumbing/call-site work** for the 5 new plugins. The gateway side is purely: (1) extend two allowlist sets, (2) flip `mode:` + bump `version:` in `config.yaml`, (3) bump `pyproject.toml` floors, (4) docs + tests. Corollary: because the gateway already passes `extensions=` to every call site, a plugin whose Python wrapper does not yet accept `extensions` will **TypeError the moment its `mode:` is flipped off `disabled`** — hence the strict sequencing below (plugin release first, then mode flip).

**Tech Stack:** Python (FastAPI gateway), pytest, `make pre-commit`.

**Source specs:** `docs/docs/manage/observability/internal-observability.md` (pii_filter's documented contract — mirror its shape per new plugin). Prior work: PR `#5470` (G0+G1 pipeline + pii_filter consumption).

## Global Constraints

- **Branching:** New feature branch off `main` — already created: `feature/gateway-5554-plugin-metrics-rollout`, based on freshly-reset `main` (includes merged `#5470`, `#5543`). `main` stays read-only.
- **Commits:** DCO sign-off required (`git commit -s`). No `Co-Authored-By` trailer.
- **Sequencing dependency:** Do NOT flip a plugin's `mode:` from `disabled` in `plugins/config.yaml` until the corresponding `cpex-plugins` release that emits its metrics has actually been published and the version floor bumped — flipping mode first would enable a plugin whose metadata the sanitizer doesn't yet allowlist, silently dropping everything (not a functional break, but pointless dead code path until both sides land).
- **S4 discipline:** Every new allowlist entry must be a low-cardinality counter/enum name, never anything that could carry content (matches the existing banner comment's reasoning in `utils.py:83-104`). Cross-check each addition against the plugin-side contract doc in `cpex-plugins` before adding.
- **Blocker rule:** True blocker → STOP and notify, don't improvise around it.
- **CI gate:** `make pre-commit` / full test suite green before a task is done.

---

## File Structure

- Modify `mcpgateway/plugins/utils.py` — extend `_SAFE_STRING_FIELD_NAMES` and `_SAFE_NUMERIC_FIELD_NAMES` (lines 92, 104) with the 5 plugins' fields; keep the existing per-entry rationale comment style.
- Modify `plugins/config.yaml` — flip `mode: "disabled"` → appropriate mode (likely `"sequential"`, matching `pii_filter`'s pattern of "the only mode that makes sense since downstream code needs the result before continuing") for each of the 5 plugin blocks (lines ~281, ~365, ~394, ~766, ~789 per current file), AND set/bump each plugin's `version:` pin field once the corresponding release ships.
- Modify `pyproject.toml` `[project.optional-dependencies].plugins` (lines 278-283) — tighten each `cpex-*` floor to `>=<new-release>`, same pattern PR `#5470` used for `cpex-pii-filter>=0.3.6`. **Flag (origin now known):** `cpex-retry-with-backoff` is pinned `>=0.3.1,<0.3.2` — an upper bound below the plugin repo's current 0.3.5. `git log -S` confirms this cap was introduced in PR `#5332` as a **deliberate CI-compat pin** ("fix(ci): pin retry-with-backoff to 0.3.1"), not a runtime incompatibility. So widening it is safe *in principle*, but the reason it was pinned was CI breakage at newer versions — re-run the gateway's plugin CI against the new metrics-emitting release before dropping the `<` bound, don't just widen blindly.
- Modify `docs/docs/manage/observability/internal-observability.md` — add a contract-table row per new plugin (mirror the `pii_filter` row: fields, types, example).
- Modify `tests/unit/mcpgateway/plugins/test_plugins_utils.py` — add allowlist coverage: each new field accepted, still-unlisted fields still rejected, still no double-write for renamed legacy fields.
- Modify `tests/integration/plugins/test_plugin_metrics_consumer_integration.py` — end-to-end per new plugin: `result.metadata["<plugin>"]` in → span/metric out.
- Modify/extend `tests/e2e/test_otel_plugin_metadata_e2e.py` — add at least one new plugin (e.g. `secrets_detection`, since it's Rust-core like `pii_filter` and thus lowest-risk parity) to the real HTTP → `/observability` assertion.

---

## Phase 0 — Setup

### Task 0: Confirm branch state

- [ ] **Step 1:** Confirm `feature/gateway-5554-plugin-metrics-rollout` is on latest `main` (already done: hard-reset to `origin/main` at `02d2ae2cf` — includes `#5470` — then branched).

---

## Phase 1 — Sanitizer allowlist extension

### Task 1: Add the 5 plugins' fields to `_SAFE_STRING_FIELD_NAMES` / `_SAFE_NUMERIC_FIELD_NAMES`

> **The allowlists are FLAT, keyed on field name — NOT namespaced per plugin.** Verified: `mcpgateway/plugins/utils.py:92,104` are `frozenset`s of bare field names, and `_sanitize_plugin_metrics()` checks a field against them regardless of which plugin namespace it came from. Consequences that change this task:
> - `total_detections` and `total_masked` are **already allowlisted** (pii_filter). `secrets_detection` and `encoded_exfil_detection` reuse `total_detections` → **adding it again is a no-op; the union is what matters, not the per-plugin count.**
> - `detection_types` (string) is already allowlisted; the new *string* fields are only `secret_types`, `encoding_types`, `reputation_categories`, `backend`.
> - Field names are shared across plugins by design. Do NOT add any per-plugin-scoped guard (there is no per-namespace allowlist mechanism and adding one is out of scope) — just extend the two flat sets with the union of genuinely-new names.

The per-plugin field mapping (must match whatever the plugin repo actually ships — verify against the final `cpex-plugins#129` PR, since exact field names are that PR's call):

| Plugin namespace key | String fields | Numeric fields |
|---|---|---|
| `secrets_detection` | `secret_types` | `total_detections` (already listed), `total_masked` (already listed), `total_blocked` |
| `encoded_exfil_detection` | `encoding_types` | `total_detections` (already listed) |
| `url_reputation` | `reputation_categories` | `total_checked`, `total_blocked` |
| `rate_limiter` | `backend` | `allowed`, `throttled` |
| `retry_with_backoff` | (none) | `retry_count`, `retry_delay_ms` (per-attempt — plugin-side decision: no cumulative `total_backoff_ms` accumulator; emit the already-computed per-attempt delay) |

**Genuinely-new union to add** (`total_detections`/`total_masked`/`detection_types`/`stage` are ALREADY allowlisted from pii_filter — do not re-add):
- `_SAFE_STRING_FIELD_NAMES` += `{"secret_types", "encoding_types", "reputation_categories", "backend"}`
- `_SAFE_NUMERIC_FIELD_NAMES` += `{"total_blocked", "total_checked", "allowed", "throttled", "retry_count", "retry_delay_ms"}`

- [ ] **Step 1:** Once the plugin-side PR is merged and its exact field names confirmed, extend `_SAFE_STRING_FIELD_NAMES` / `_SAFE_NUMERIC_FIELD_NAMES` in `mcpgateway/plugins/utils.py` with the union above, preserving the existing rationale-comment block above each set (extend the comment's "New plugins..." pointer to note these are now wired, not still-pending).
- [ ] **Step 2:** Unit tests: for each new field name, one accepted-value test + one still-rejected-if-field-unknown test (use a fabricated bogus field name to prove the allowlist, not the charset, is doing the gating).

---

## Phase 2 — Config + dependency pins (per plugin, once its release ships)

**RESOLVED (supersedes each task's "flip mode" step below):** Task 2's implementer found that `mode: "disabled"` means the plugin is never instantiated — hooks never run at all. Flipping to `sequential` would newly enable each plugin's actual detection/blocking/throttling behavior for every default deployment (e.g. secrets_detection's `block_on_detection: true`), not just enable metrics. This directly conflicts with the repo's own established convention: `pii_filter` (the pilot) deliberately stays `disabled` by default for exactly this reason (documented in `plugins/config.yaml`'s pii_filter block: "masking a tool response by default would be a silent behavior change for existing deployments"). Human decision: **keep `mode: "disabled"` for all 5 plugins** — bump version pins + add contract-doc rows only. The metrics pipeline is wired and ready; an operator opts a plugin in later by flipping its own mode, same as pii_filter. Do NOT flip mode in Tasks 2-6.

### Task 2: `secrets_detection`

- [ ] Bump `pyproject.toml` `cpex-secrets-detection` floor to the metrics-emitting release.
- [ ] Flip `plugins/config.yaml` `mode:` for the `SecretsDetectionPlugin` block from `disabled` to `sequential` (confirm this doesn't change existing deployments' behavior beyond adding metrics — re-read the plugin's `block_on_detection`/masking config to confirm mode flip doesn't also newly enable masking/blocking that was previously inert under `disabled`).
- [ ] Update `internal-observability.md` contract table.

### Task 3: `encoded_exfil_detection`

- [ ] Same steps. Note current config has commented-out `# mode: "sequential"` alongside active `mode: "disabled"` — clean up the stale commented line when flipping.

### Task 4: `url_reputation`

- [ ] Same steps.

### Task 5: `rate_limiter`

- [ ] Same steps.

### Task 6: `retry_with_backoff`

- [ ] Same steps, PLUS the `<0.3.2` cap: origin confirmed as a CI-compat pin from PR `#5332` (see File Structure). Re-run the gateway's plugin CI against the new metrics-emitting release, then widen the floor to `>=<new-release>` and drop the `<0.3.2` upper bound only if CI is green. If CI still breaks at the newer version, that CI failure is a real blocker — STOP and notify, do not force the pin.

---

## Phase 3 — E2E + docs

### Task 7: Extend e2e coverage

- [ ] Add `secrets_detection` (Rust-core, same shape as `pii_filter`) to `tests/e2e/test_otel_plugin_metadata_e2e.py` as the first parity check.
- [ ] Add integration tests in `tests/integration/plugins/test_plugin_metrics_consumer_integration.py` for the remaining 4.

### Task 8: Wrap-up

- [ ] Full `make pre-commit` + test suite green.
- [ ] Do NOT open a PR or merge — stop here; PR creation is a separate, explicit user request.
