# Rectified Findings — Issue #4510

## Verdict

**Valid**, confirmed against current `main`. Not partial — the reported symptom and root
cause are both accurate. What needs correcting is the *scope* implied by the linked
triage comment, not the bug report itself.

## Confirmed on source

| Claim | Evidence |
|---|---|
| Docs promise `IBM_VERIFY_GROUP_MAPPING` / `IBM_VERIFY_USER_MAPPING` | `docs/docs/manage/sso-ibm-tutorial.md:149,152`, `docs/docs/manage/teams.md:44` |
| No matching `Settings` field exists | `mcpgateway/config.py:485-488` — only `sso_ibm_verify_enabled/client_id/client_secret/issuer`. No `ibm_verify_group_mapping`, no `ibm_verify_user_mapping` anywhere in the file. |
| IBM Verify's `team_mapping` is hardcoded empty | `mcpgateway/utils/sso_bootstrap.py:154-174` — `"team_mapping": {}` unconditionally, no env read |
| Okta does the equivalent correctly | `sso_bootstrap.py:178-190` parses `settings.okta_group_mapping` JSON into `okta_team_mapping` before building the provider dict |
| `team_mapping` is consumed at login time | `sso_service.py:597-731` (`_apply_team_mapping`), called from the OAuth callback at `:2147`/`:2199` |
| `IBM_VERIFY_USER_MAPPING` has zero implementation, for any provider | No `user_mapping`/attribute-rename concept exists in `sso_service.py`. `apply_attribute_mapping` (`plugins/utils.py:624`) is unrelated — used for observability span attributes, never wired into SSO. |

## Correction to the triage comment's dependency graph

`@jonpspri`'s comment states #4510 is "Blocked by: #6396 #6237." Tracing the actual code
paths, that overstates the real dependency:

- **#6396 is not a blocker.** It's about *bearer-token* API auth — presenting an
  already-issued external-IdP access token as `Authorization: Bearer` on `/rpc`, `/mcp`,
  REST. `_apply_team_mapping` runs in the **OAuth authorization-code login/callback
  flow** (`sso_service.py:2147`/`:2199`), a separate path that already works for every
  other provider today.
- **#6237 only matters if implemented the wrong way.** Its bug is that `provider_metadata`
  dict keys get pinned to a stale empty default forever. `team_mapping` is a *separate*
  top-level field with its own merge rule (`sso_bootstrap.py:423-425`) that already lets a
  non-empty env value fill an empty DB value. Following the Okta pattern (top-level
  `team_mapping`, not nested `provider_metadata`) sidesteps #6237 entirely.
- **#6425 is the real, unlisted prerequisite.** IBM's own account-iam emits dict-shaped
  claims (`{"roles": {"SERVICE": ["ServiceOwner"]}}`). `_extract_groups_and_roles`
  (`sso_service.py:1694`) only handles `str`/`list` and returns `[]` for dicts. Without
  this fix, `IBM_VERIFY_GROUP_MAPPING` "works" only for synthetic list-shaped claims and
  silently no-ops against IBM's actual token shape.

## Rectified scope for #4510

1. Add `ibm_verify_group_mapping: Optional[str]` to `config.py` (mirror `okta_group_mapping`).
2. Parse it in `sso_bootstrap.py`'s IBM Verify block into `team_mapping`, mirroring the
   Okta block exactly.
3. Fix `_extract_groups_and_roles` to handle dict-of-buckets claims (shared code, also
   closes #6425) — without this, step 1-2 is cosmetic for IBM's real claim shape.
4. `IBM_VERIFY_USER_MAPPING` is a distinct, unscoped feature with no existing pattern to
   copy — out of scope for the minimal fix; correct the docs instead of building an
   unrequested subsystem.
5. Drop the "blocked by #6396" framing when scoping implementation work — false
   dependency.
