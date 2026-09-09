# Token Dispatch Rule

This page pins the rule the verifier uses to route a bearer token when JWT
trust mode (epic #5885) exists. Trust mode lets a signed JWT alone prove
identity, roles, and teams. No local user record is read on the request path.

The dispatch rule has three parts: the eligibility rule, the 401 rule for
marked tokens when trust mode is OFF, and the default-funnel rule for all
other tokens.

## Eligibility rule (disjunctive)

A token is trust-eligible when trust mode is ON AND one of these two trust
roots applies:

- **(a) Gateway-signed token.** `token_use == "trusted"` AND the required
  mapped claim set (`sub`, `teams`, `roles` per #5899) AND a configured
  revocation claim (default `jti`). The marker is an explicit positive
  signal. It is not a claim-shape heuristic, so no future mint path can
  become trust-eligible by accident.
- **(b) External IdP token.** The issuer is a configured trust root
  (`trusted_for_api_auth` + `api_audience` on `SSOProvider` in
  `mcpgateway/db.py`) AND the required mapped claims AND a configured
  revocation claim. External IdP tokens cannot carry the ContextForge
  `token_use` marker, so the issuer is the trust root for this branch.

## Marked tokens get HTTP 401 when trust mode is OFF

A token that carries `token_use == "trusted"` gets HTTP 401 when trust mode
is OFF. Such a token never enters the default funnel. Two default-funnel
behaviors make this necessary:

- The UUID heuristic (`resolve_uuid_subject` in `mcpgateway/auth.py`) could
  silently re-attribute a UUID-shaped `sub` to a different local user.
- `normalize_token_teams` in `mcpgateway/auth_context.py` would honor the
  embedded `teams` claim under default semantics, without the trust-mode
  claim mapping and revocation rules.

## All other tokens use the default funnel

Every token that is not trust-eligible routes through the default funnel,
even when trust mode is ON. Default mode behavior does not change:

- Session tokens (`token_use == "session"`) carry no `teams` or `is_admin`
  claims (`create_access_token` in `mcpgateway/routers/email_auth.py`).
  Teams come from server-side resolution.
- API tokens (`token_use == "api"`) embed `user_data.is_admin` and `teams`
  (`_generate_token` in `mcpgateway/services/token_catalog_service.py`).
  The embedded teams are honored.
- External IdP tokens follow the current provisioning behavior through
  `verify_external_idp_token` in `mcpgateway/utils/verify_credentials.py`.

## Mode x token combinations

| Mode | Token type | Expected result |
|------|-----------|-----------------|
| Default | Session token | Default-semantics (server-side team resolution) |
| Default | API token | Default-semantics (embedded teams honored) |
| Trust | Default session token | Default-semantics (not trust-eligible; no `token_use=="trusted"` marker, issuer not a trust root) |
| Trust | Default API token | Default-semantics (same reason) |
| Trust | Gateway-signed trust token (`token_use=="trusted"`) | Trust-semantics (post-#5900); 401 before #5900 lands |
| Trust | External IdP token (trusted issuer) | Trust-semantics via issuer branch (post-#5900); provisioning behavior pre-#5900 |

The executable form of this table is
`tests/unit/mcpgateway/test_token_dispatch_matrix.py`. Rows whose
expectation holds today pass. Rows that need un-landed behavior carry
`pytest.mark.xfail(strict=True, ...)` with a pointer to the story that
flips them.

## Operative fact

No `token_use` value other than `session` or `api` exists in `mcpgateway/`
today. The `trusted` marker is introduced by #5904.
