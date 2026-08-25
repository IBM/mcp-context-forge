# Catalog Ownership Fallback Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent user deletion from assigning gateways and linked resources to a missing or inactive configured platform administrator, and document the catalog visibility and ownership-transfer behavior.

**Architecture:** Keep ownership validation in `EmailAuthService.delete_user()`, immediately before the platform-admin fallback is accepted. Reuse the existing `EmailUser` query pattern and active-user predicate; do not add a database foreign key or a new helper. Add deny-path coverage to the existing deletion service tests and extend the existing catalog guide with the changed defaults and transfer endpoint.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest, Markdown.

**Spec:** Review findings #1 and #3 valid portions from the catalog-registration security review.

## Global Constraints

- Platform-admin fallback must require an existing active `EmailUser` row.
- The deleted user must never be selected as the fallback owner.
- Existing alternate active team-member transfer remains first priority.
- Missing or inactive fallback must preserve the existing orphan `ValueError` path.
- No migration or schema change is needed; `owner_email` remains an application-level identity field.
- Do not modify unrelated review suggestions or PR metadata that is not represented in repository files.

---

### Task 1: Add failing deletion regression coverage

**Files:**
- Modify: `tests/unit/mcpgateway/services/test_email_auth_basic.py:3058-3144`

**Interfaces:**
- Consumes: `EmailAuthService.delete_user()` and the existing `mock_db.execute.side_effect` fixture pattern.
- Produces: A regression test proving a configured platform admin without an active database row cannot receive ownership.

- [ ] **Step 1: Update the existing valid-fallback test setup**

Add the active admin lookup result to `test_delete_user_transfers_gateway_to_platform_admin_fallback` so the test describes the new contract:

```python
mock_admin_result = MagicMock()
mock_admin_result.scalar_one_or_none.return_value = MagicMock(email="admin@x.com", is_active=True)
mock_db.execute.side_effect = [mock_user_result, mock_no_teams, mock_gateways, mock_admin_result, MagicMock(), MagicMock()]
```

- [ ] **Step 2: Add the missing/inactive fallback deny-path test**

Add a test after the existing orphan test. It must configure a non-empty `platform_admin_email`, return `None` for the active-admin lookup, invoke `delete_user()`, and assert `ValueError` contains `orphaned` and `mock_db.rollback` was called. The `is_active == True` query predicate makes both missing and inactive rows resolve to `None`.

- [ ] **Step 3: Run the focused tests and verify the new test fails**

Run:

```bash
pytest -q tests/unit/mcpgateway/services/test_email_auth_basic.py -k 'platform_admin_fallback or gateway_would_be_orphaned'
```

Expected: the new deny-path test fails because the current implementation accepts any non-empty configured email without querying `EmailUser`.

### Task 2: Validate the platform-admin fallback

**Files:**
- Modify: `mcpgateway/services/email_auth_service.py:2130-2137`

**Interfaces:**
- Consumes: Existing `EmailUser`, `select`, `self.db`, and the existing orphan `ValueError` path.
- Produces: Fallback ownership only when the configured email identifies an active user other than the deleted user.

- [ ] **Step 1: Add the active-user lookup**

Replace the string-only fallback with:

```python
admin_email = (settings.platform_admin_email or "").strip()
if admin_email and admin_email != email:
    admin_user = self.db.execute(
        select(EmailUser).where(
            EmailUser.email == admin_email,
            EmailUser.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if admin_user:
        new_owner_email = admin_user.email
```

Leave the following existing `if not new_owner_email: raise ValueError(...)` unchanged.

- [ ] **Step 2: Run the focused tests and verify they pass**

Run:

```bash
pytest -q tests/unit/mcpgateway/services/test_email_auth_basic.py -k 'platform_admin_fallback or gateway_would_be_orphaned'
```

Expected: all selected tests pass.

### Task 3: Document catalog visibility and transfer behavior

**Files:**
- Modify: `docs/docs/manage/catalog.md:254-271`

**Interfaces:**
- Consumes: Existing catalog registration API documentation and current endpoint contract.
- Produces: User-facing documentation for private-by-default registration, team scoping, and admin ownership transfer.

- [ ] **Step 1: Document visibility defaults and scope rules**

Add a subsection after the registration example stating:

- Registrations default to `private` when `visibility` is omitted.
- `visibility: team` requires `team_id` and active membership.
- Public team-scoped registration is controlled by `ALLOW_PUBLIC_VISIBILITY`.
- Existing catalog gateway rows are not rewritten automatically.

Include a JSON request example showing `visibility` and `team_id`.

- [ ] **Step 2: Document gateway ownership transfer**

Add the `POST /admin/gateways/{gateway_id}/transfer-ownership` endpoint, required admin permission, target-user validation, optional `target_team_id`, and the 404/400/403 failure cases. Include a minimal curl example.

### Task 4: Verify and stage the change

**Files:**
- Review: `mcpgateway/services/email_auth_service.py`
- Review: `tests/unit/mcpgateway/services/test_email_auth_basic.py`
- Review: `docs/docs/manage/catalog.md`

- [ ] **Step 1: Run focused regression tests**

Run:

```bash
pytest -q tests/unit/mcpgateway/services/test_email_auth_basic.py -k 'platform_admin_fallback or gateway_would_be_orphaned'
```

- [ ] **Step 2: Run targeted lint checks**

Run:

```bash
ruff check mcpgateway/services/email_auth_service.py tests/unit/mcpgateway/services/test_email_auth_basic.py
```

- [ ] **Step 3: Review the diff and stage only intended files**

Run:

```bash
git diff --check
git diff -- mcpgateway/services/email_auth_service.py tests/unit/mcpgateway/services/test_email_auth_basic.py docs/docs/manage/catalog.md
git add docs/superpowers/plans/2026-08-25-catalog-ownership-fallback.md mcpgateway/services/email_auth_service.py tests/unit/mcpgateway/services/test_email_auth_basic.py docs/docs/manage/catalog.md
```

- [ ] **Step 4: Verify staged status**

Run:

```bash
git status --short
```

Expected staged files: exactly the plan, source, test, and catalog documentation files listed above.
