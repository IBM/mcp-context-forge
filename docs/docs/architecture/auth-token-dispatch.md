# Token Dispatch Rule

This page pins the rule the verifier uses to route a bearer token when JWT
trust mode (epic #5885) exists. Trust mode lets a signed JWT alone prove
identity, roles, and teams. No local user record is read on the request path.

The dispatch rule has four parts: the eligibility rule, the ingress
dispatch at the authentication choke point, the 401 rule for marked
tokens when trust mode is OFF, and the default-funnel rule for all other
tokens.

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

## Ingress dispatch

`get_current_user()` in `mcpgateway/auth.py` is the authentication choke
point for every bearer token. When trust mode is ON it first calls
`_try_external_verification()`, which reads the token's `iss` claim
UNVERIFIED (`verify_signature: False`) solely to choose the verification
path — no other claim from this peek is ever trusted — then delegates to
the external verification chain (`_maybe_verify_external` ->
`verify_external_idp_token` -> `build_trusted_external_identity` in
`mcpgateway/utils/verify_credentials.py`):

- **Issuer is a configured trust root and verification succeeds** -> the
  claims-derived identity payload (`token_use="trusted"`) becomes the
  principal.
- **Issuer is a configured trust root but verification fails
  definitively** (bad signature, wrong audience, expiry, missing
  revocation claim) -> `401`, fail-closed. The internal JWT funnel is
  NEVER consulted for that token.
- **Issuer is not a configured trust root** (or is the internal issuer,
  or the token is not a JWT at all) -> `None`; the caller falls through
  to the internal verifier exactly as before.

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
| Trust | Gateway-signed trust token (`token_use=="trusted"`) | Trust-semantics: claims-derived identity, revocation retained, no local user read (#5900) |
| Trust | External IdP token (trusted issuer) | Trust-semantics via the issuer branch: JWKS-verified at ingress, claims-derived identity (#5903) |

The executable form of this table is
`tests/unit/mcpgateway/test_token_dispatch_matrix.py`. Every row passes:
the matrix drives `get_current_user()` itself (only the JWKS fetch is
mocked, not the dispatch), including the cross-mode deny rows.

## Result semantics at ingress

The black-box matrix in
`tests/live_gateway/test_trust_mode_external_ingress_e2e.py` (5/5
live-green against a gateway started with `JWT_TRUST_MODE=jwt-trust`)
pins the observable results:

| Result | Meaning |
|--------|---------|
| `200` | External authentication succeeded, the group mapping resolved team + role, RBAC granted, and the team-visible agent was invoked. |
| `401` | Untrusted issuer (fall-through to the internal verifier, which rejects the externally-signed token) OR a trust-root token that failed verification definitively (bad signature, wrong audience, expiry, missing revocation claim). |
| `403` | Authenticated, but no group mapping/role resolved — RBAC Layer-2 deny (deny without disclosing agent existence). |
| `404` | Authenticated and authorized, but the named agent does not exist — the agent lookup terminates at 404. |

`tests/live_gateway/test_trust_mode_entra_barrier.py` is pinned to the
same semantics: its scenario seeds no SSO provider, so the Entra issuer
is not a configured trust root and the token falls through to the
internal verifier, which rejects it with `401` — the by-design
untrusted-issuer fall-through, not the pre-fix wiring failure where the
external JWKS path was unreachable even for a seeded trust root. The
seeded-trust-root denial paths (`403` unmapped, `404` nonexistent agent)
are proven by the ingress matrix above.
