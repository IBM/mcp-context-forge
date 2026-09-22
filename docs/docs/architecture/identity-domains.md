# Identifier Domains

ContextForge issues and accepts more than one token type. Each token type
puts a different value in the `sub` claim. This page maps each token type
to the layer that resolves the value and to the canonical user ID.

## Token-type mapping

| Token type | `sub` content | Resolution layer | Canonical user_id (phase 1) |
|---|---|---|---|
| Session token (`token_use="session"`) | UUID (`EmailUser.id`) | `_get_email_by_id_sync` and `get_user_email_from_token` in `mcpgateway/auth.py`, plus `resolve_jwt_user_email_from_payload` in `mcpgateway/auth_context.py` | e-mail |
| API token | UUID; signed metadata carries the e-mail | `resolve_jwt_user_email_from_payload` in `mcpgateway/auth_context.py` | e-mail |
| Legacy token (no `token_use`) | e-mail | none (direct) | e-mail |
| Future trust token | opaque | trusted-claims module (not built yet, epic #5885) | to be defined by Stack B |

## Accessors

`get_user_email()` is the e-mail-attribute accessor. `get_user_id()` is the
identity accessor. Phase 1 populates both with the same value.

The old assumption "the e-mail is the identity" (see the comment in
`mcpgateway/middleware/auth_middleware.py`) is abolished by later stories.
