# Feature-by-Mode Behavior Matrix

This page pins the behavior of every user-dependent feature under default
mode and under JWT trust mode (epic #5885). Trust mode lets a signed JWT
alone prove identity, roles, and teams; no local user record is read on the
request path. Features that depend on a local user record therefore need an
explicit decision per mode. This matrix is that decision.

Each entry states one of:

- **Works** — the feature behaves as today.
- **Disabled with clear error** — the feature returns the stated HTTP status
  and message.
- **Degraded** — the feature runs with reduced function.
- **N/A** — the feature cannot apply in that mode.

Every entry carries a `file:symbol` citation to the code the decision
governs.

## Matrix

| Surface | Default mode | Trust mode | Citation |
|---------|--------------|------------|----------|
| Password login/register/reset | Works | Disabled (401, "Password authentication disabled in trust mode") | `mcpgateway/routers/email_auth.py` — `login`, `register`, reset-password handlers |
| Invitations | Works | Disabled (403, "Invitations require local user records") | `mcpgateway/services/team_invitation_service.py` — inviter/owner checks in the invitation creation flow |
| Team membership writes | Works (raises `UserNotFoundError` when user absent) | Disabled (403, "Team membership writes require local user records") | `mcpgateway/services/team_management_service.py` — `add_member_to_team` |
| SSO browser login | Works (provisions user + issues session token) | Disabled (401, "SSO browser login disabled in trust mode") | `mcpgateway/services/sso_service.py` — `authenticate_or_create_user` |
| Personal-team auto-creation | Works | N/A (trust mode has no local user to create teams for) | `mcpgateway/services/email_auth_service.py` — `auto_create_personal_teams` check in `create_user` |
| Import ownership | Works (queries `EmailUser` for personal-team lookup) | Degraded (import ownership requires a local user record) | `mcpgateway/services/import_service.py` — `_get_user_context`, `_add_multitenancy_context` |
| Admin UI user CRUD | Works | Disabled (403, "User management disabled in trust mode") | `mcpgateway/admin.py` — admin user CRUD handlers (`admin_create_user`, `admin_update_user`, `admin_delete_user`); `mcpgateway/routers/email_auth.py` — API CRUD endpoints (`create_user`, `update_user`, `delete_user` under `/admin/users`) |
| API-token catalog | Works (requires `EmailUser` row) | DB-backed principals: works. Trust-only principals: disabled with explicit error ("Token minting is disabled for trust-only principals. Create a local user account first.") | `mcpgateway/services/token_catalog_service.py` — `create_token` |
| Session-token refresh | Works (`POST /auth/refresh`, session-only guard) | Disabled (401, "Session refresh disabled in trust mode") | `mcpgateway/routers/auth.py` — `refresh_session` |

## Self-check

- [x] Password login/register/reset — decision recorded.
- [x] Invitations — decision recorded.
- [x] Team membership writes — decision recorded.
- [x] SSO browser login — decision recorded.
- [x] Personal-team auto-creation — decision recorded.
- [x] Import ownership — decision recorded.
- [x] Admin UI user CRUD — decision recorded.
- [x] API-token catalog — decision recorded.
- [x] Session-token refresh — decision recorded.

Every surface has a decision. No entry is undefined. Any entry that becomes
"undefined" blocks #5906 (matrix error-path tests) until a decision is
recorded here.

## Binding

These decisions are binding for WO-B.12 (choke-point implementation) and
WO-B.14 (matrix error-path tests). Any change to a cell requires editing all
three work orders.
