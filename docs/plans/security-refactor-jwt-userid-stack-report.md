# PR Stack Report — `jwt-trust` (Stack #6729)

**Epics:** #5884 (Canonical User ID) + #5885 (JWT-Trust Authentication Mode)
**Generated:** 2026-09-10 · **Stack tip branch:** `feat/6756-app-only-graph-lookup` (tag `jwt-trust`)
**Suite:** 23,410 passed / 879 skipped / 2 xfailed — green in both `JWT_TRUST_MODE=db` and `jwt-trust`
**Total:** 25 open, ready-for-review PRs; each shows only its own diff; merge bottom-up (`gh stack` restacks automatically).

---

## Stack A — Epic 1: #5884 Canonical User ID (decouple identity from e-mail)

| PR | Issue | Description |
|----|-------|-------------|
| #6726 | #5886 | Add canonical `get_user_id()` helper in `auth_context.py` + `identity-domains.md` token-type mapping doc. Also carries the implementation plan (`docs/plans/security-refactor-jwt-userid.md`). |
| #6728 | #5887 | Every principal/user-dict construction site (6 sites) carries `user_id == email`; fixture helper gains `token_use`/`user_id` kwargs. |
| #6730 | #5888 | Audit and observability identity routed through `get_user_id()` with the `"system"` guard preserved; `AuditTrail`/`ObservabilityTrace` column comments; AGENTS.md two-accessor rule. |
| #6731 | #5889 | RBAC middleware resolves caller identity via `get_user_id()` (13 identity uses replaced, 9 logging uses kept); deny paths untouched. |
| #6732 | #5890 | `resolve_session_teams` keys on canonical user_id; UUID session subjects fall back to the e-mail argument; DB-authority contract unchanged. |
| #6733 | #5891 | Auth caches re-keyed by user_id with `auth_cache_key_version` namespace; mode-flip cold-start proof. |
| #6734 | #5892 | Idempotent migration: nullable `user_id` column on `email_users` + e-mail backfill + non-unique index; ORM column. |
| #6735 | #5893 | SSO subject stored as `user_id` (per-provider claim setting); all 5 writer sites re-keyed through one shared resolver; AST audit test enforces coverage. |
| #6736 | #5894 | Diverged-identity separation suite: 3 token formats × 4 columns + fail-closed row; caught and fixed a real row-loss bug in `_resolve_teams_from_db`. |
| #6737 | #5895 | Epic 1 gate (all commands green) + identity docs sweep; behavior-identity note listing all justified test modifications. |

## Stack B — Epic 2: #5885 JWT-Trust Authentication Mode

| PR | Issue | Description |
|----|-------|-------------|
| #6738 | #5896 | Token-dispatch rule doc (`auth-token-dispatch.md`) + executable 6-row deny matrix (strict-xfail rows point at their flip stories). |
| #6739 | #5897 | Feature-by-mode matrix doc: 9 user-dependent surfaces × default/trust mode, every entry cited and binding on later PRs. |
| #6740 | #5898 | Config surface: `JWT_TRUST_MODE` + 5 claim-mapping settings + overage policy + revocation claim, with startup validators. |
| #6741 | #5976 | `external_group_mappings` table (group → team + optional role), fail-closed resolver, RBAC-scoped admin CRUD; visibility-gate tests as strict-xfail. |
| #6742 | #6272 | Group→role wiring proven: `cf_role` CRUD validation tests; trust-path merge tests (developer via group alone) as strict-xfail. |
| #6744 | #5899 | `trusted_claims.py`: `extract_trusted_principal` + `VirtualPrincipal` contract, dotted-path claim readers, shared overage detection, revocation-claim extractor. |
| #6745 | #5977 | App-only Entra Graph client (client-credentials, never inbound token) + oid-keyed cache; three-policy overage dispatch incl. Redis-error fallback. |
| #6746 | #5900 | Trust branch in `get_current_user`: claims-derived identity, revocation retained, user lookup/is_active skipped; cache key gains mode segment; all branch-(a) xfails flipped green. |
| #6747 | #5901 | `revoked_by` FK relaxed (batch migration); all 6 revocation insert sites store user_id or exact sentinels; idle-revoke now persists-with-ERROR-logging. |
| #6749 | #5902 | Mapped admin claim feeds both admin tracks atomically (server-injected `platform_admin`); verdict-for-verdict parity with DB admins; public-only suppression intact. |
| #6750 | #5903 | External-IdP trust root: claims-derived identity with zero `email_users` reads (SQL-listener proof); final dispatch-matrix xfail flipped. |
| #6751 | #5904 | Trust-token minting (`POST /admin/tokens/trust`, server-derived claims, no act-as); catalog guard for trust-only principals; plugin hook disabled in trust mode. |
| #6753 | #5905 | Acceptance suite: no-DB proof (60 requests, zero user-table SELECTs), config-flip round-trip, UAID forwarding, overage-degraded, cross-gateway re-evaluation; multi-worker live file (runs on a stack). Wall-clock p99 benchmark removed before merge. |
| #6755 | #5906 | Epic 2 gate: executable tests for all disabled-with-clear-error matrix rows (real mode-gated 401/403 guards); docs sweep; both-mode validation green. |
| #6757 | #6756 | Follow-on: app-only (`idtyp="app"`) service-principal group resolution via `/servicePrincipals/{oid}/getMemberObjects` under `graph_lookup`; app-role path preserved under default policy. |

---

**Notes:** #6725 was an early duplicate of #6726 (closed during the fork→upstream transition — not part of the stack). Migrations form one linear head chain: `12d4a0c7789c → bf2998718ea1 → e5f6a7b8c9d0 → f7a8b9c0d1e2`. Live-stack gate items (docker bring-up, `test-mcp-protocol-e2e`, `test-mcp-rbac`) run in the maintainer environment at merge time; the live test files ship with correct skip markers.
