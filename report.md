# PR #7381 Review Report

**PR:** [feat(oauth): add GET /oauth/token/{gateway_id} access token retrieval endpoint](https://github.com/IBM/mcp-context-forge/pull/7381)
**Author:** jonpspri
**Closes:** [#6966](https://github.com/IBM/mcp-context-forge/issues/6966)
**Size:** 15 files, +973 / -129
**Review date:** 2026-11-04

## Summary

The PR adds `GET /oauth/token/{gateway_id}`. The endpoint returns the caller's own OAuth `access_token` for a gateway. It refreshes the token first when the token expires within a fixed threshold. It never returns the `refresh_token`. A new flag, `OAUTH_TOKEN_RETRIEVAL_ENABLED`, disables the endpoint by default.

The PR also adds:
- `get_user_token_details()` to the token storage service and to both backends (database and Vault).
- A `TokenReauthorizationRequired` exception and an `AccessTokenDetails` dataclass.
- A default-deny route mapping in `token_scoping.py`, which requires `gateways.update`.
- A refactor of the Vault refresh logic into `_refresh_token_details()`.

## Verdict

**Changes requested.** No blocking finding applies. Six functionally-impacting findings need a fix or a documented waiver before merge. The branch needs a rebase on `main`.

## Verification

| Check | Result |
|-------|--------|
| Diff read in full (all 15 files) | Done |
| PR description cross-referenced with issue #6966 | Done |
| Unit tests on the PR branch: `test_oauth_router.py`, `test_vault_token_backend.py`, `test_db_backend.py`, `test_token_scoping.py`, `test_vault_coverage_boost.py` | All pass (about 1,000 tests) |
| CI at review time | DCO passed; CodeQL queued |
| Branch status | Behind `main` |
| Full validation gate (`make ruff interrogate pylint`, `make test`, `make coverage diff-cover`, `make test-e2e`) | Not run by the author; not run in this review |

## Security Assessment

| Area | Observation |
|------|-------------|
| Feature gating | The endpoint is disabled by default. A disabled instance returns 503. |
| Layer 1 (visibility) | `_enforce_gateway_access` runs with the request's token-scoping context. |
| Layer 2 (RBAC) | `@require_permission(Permissions.GATEWAYS_UPDATE)`. |
| Token-scoped API tokens | `token_scoping.py` maps `GET /oauth/token` to `gateways.update`. Unmapped paths stay default-deny. |
| Identity | The token lookup uses the authenticated caller's email. No client-supplied ownership field is used. |
| Credential exposure | The response omits `refresh_token`. It sets `Cache-Control: no-store`. The log line holds the gateway ID and user email, never the token. |
| Deny-path tests | The live-gateway test covers flag off, unauthenticated, viewer, wrong team, and read-only API token. |

## Findings

Format: `severity | location | problem | fix`

### Functionally-impacting

1. **functionally-impacting | PR description vs `mcpgateway/routers/oauth_router.py::get_gateway_oauth_token` | The PR description says a bounded `threshold_seconds` query param (0–3600) exists. The code uses a fixed constant, `OAUTH_TOKEN_REFRESH_THRESHOLD_SECONDS = 600`, and the docstring states this is deliberate. Issue #6966 asks for a "configured threshold". `config.py` and `.env.example` hard-code "10 minutes" in their text. | Correct the description. Either make the threshold a setting, or state in the PR that the fixed value is intentional.**

2. **functionally-impacting | `mcpgateway/services/token_backends/db_backend.py::get_user_token_details` and `vault_backend.py::get_user_token_details` | Both methods catch only `OAuthError` around the refresh call. With `raise_errors=True`, `_refresh_access_token` re-raises non-OAuth errors (network, decryption) from its generic handler. A token that is near expiry but still valid then yields HTTP 503. The existing `get_user_token` path returns the valid token in the same case. | Catch `Exception` in both backends. Return the still-valid token when `_is_token_expired(record, 0)` is false.**

3. **functionally-impacting | `mcpgateway/services/token_backends/vault_backend.py::get_user_token_details` | `data.get("token", {})` raises `AttributeError` when `token` is present but `None`. A header-only Vault record raises `ValueError`, which the router maps to 503 "storage unavailable". `get_user_token` returns `None` for the same record, which maps to 404. | Return `None` when `token` is missing or not a dict, and when `access_token` is missing. This matches `get_user_token`.**

4. **functionally-impacting | `mcpgateway/routers/oauth_router.py`, `except Exception` branch | `logger.error("OAuth token storage retrieval failed")` drops the cause. Operators cannot diagnose a 503 from the log. | Add `exc_info=True`. The message carries no secret.**

5. **functionally-impacting | `tests/unit/mcpgateway/routers/test_oauth_router.py`, `tests/live_gateway/test_oauth_token_retrieval.py` | No test covers the 409 (`TokenReauthorizationRequired`), 502 (`OAuthError`) or 503 (storage failure) mappings. No router-level test covers the Vault `invalid_grant` revoke-and-409 path. | Add one router test per mapped error. Assert that no token string appears in the response detail or the logs.**

6. **functionally-impacting | `CHANGELOG.md`, `docs/docs/manage/oauth.md`, `docs/docs/manage/rbac.md` | The PR adds an endpoint, an environment variable and a permission requirement. The PR description confirms the CHANGELOG is not updated. No documentation covers the endpoint or the `gateways.update` choice. | Add a CHANGELOG entry and a section in `oauth.md`. State that `/oauth/status` needs `gateways.read` while this endpoint needs `gateways.update`.**

### Minor

7. **minor | `mcpgateway/services/token_backends/base.py`, `mcpgateway/services/token_storage_service.py` imports | The `OAuthError` import in `base.py` follows the `mcpgateway.utils` import. `base.py` now depends on `oauth_manager`. The `AccessTokenDetails` import in `token_storage_service.py` follows a `# noqa` block. | Run `make isort`.**

8. **minor | `.secrets.baseline` | The file change is unrelated to the feature. `generated_at` moves backwards (2026-11-04T13:30:40Z to 2026-11-02T10:41:28Z). The `files` regex gains a `Cargo.lock` entry. `main` has `generated_at` 2026-11-04T15:40:06Z and no `Cargo.lock` entry. | After the rebase, take the `main` version. Then run `make detect-secrets-scan`.**

9. **minor | PR template | The reviewability item "linked issue is not labeled `triage`" is unchecked. Issue #6966 carries the labels `COULD` and `work-queue`. The `make lint` and `make test` items are unchecked. | Tick the item that applies. Run the validation gate before merge.**

## Scope check against issue #6966

| Acceptance criterion | Status |
|----------------------|--------|
| The endpoint returns a valid, unexpired `access_token` | Delivered |
| The endpoint refreshes a near-expiry token before it returns the token | Delivered, with a fixed 600-second threshold (see finding 1) |
| `refresh_token` never leaves the gateway | Delivered |
| Disabled by default | Delivered |

## Conclusion

The design is sound and the security controls are in place. Merge requires:
- Resolution of findings 1–6, or a documented waiver for each.
- A rebase on `main`, with `.secrets.baseline` taken from `main`.
- A passing validation gate.

## Local remediation — 2026-11-05

The working tree addresses findings 1–6. Tests remain unexecuted at the user's request.
The existing staged change selects `tokens.create`; middleware, documentation, and regression cases now use that permission.
`git diff --check` passes. Targeted Ruff reports 65 existing test-file findings, confirmed against the index baseline.
Ruff reports no findings in the changed production files or new regression cases.

| Finding | Change |
|---------|--------|
| 1 | Add `OAUTH_TOKEN_REFRESH_THRESHOLD_SECONDS`, default `600`, bounded to `0`–`3600`. The endpoint accepts no threshold query parameter. |
| 2 | Preserve valid tokens after non-OAuth refresh failures in both backends. Expired tokens still propagate the failure. |
| 3 | Return `None` for absent, non-dictionary, and access-token-free Vault token records. |
| 4 | Log traceback locations and the exception type. Exclude original exception messages and chains, which can contain tokens. |
| 5 | Add router error mappings and Vault revoke-and-409 coverage. Add backend fallback, missing-token, configuration, and permission cases. |
| 6 | Document retrieval, configuration, permissions, and errors in the OAuth guide, RBAC guide, and CHANGELOG. |

### Replacement PR description text

The published PR description still needs this correction. No GitHub content changes accompany these local edits.

> Adds `GET /oauth/token/{gateway_id}` to return the caller's own OAuth access token, refreshing it when necessary.
> `OAUTH_TOKEN_RETRIEVAL_ENABLED` defaults to `false`.
> Operators configure `OAUTH_TOKEN_REFRESH_THRESHOLD_SECONDS` from `0` through `3600` seconds; the default is `600`.
> Callers cannot override the threshold through query parameters.
> Retrieval requires `tokens.create` and gateway visibility; OAuth status requires `gateways.read`.
> Responses exclude refresh tokens and use `Cache-Control: no-store`.
