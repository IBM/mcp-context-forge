# Microsoft Entra ID E2E Testing

End-to-end testing guide for Microsoft Entra ID (Azure AD) SSO integration with ContextForge.

This guide walks you through setting up Azure resources and running fully automated E2E tests that validate group-based role assignment for `platform_administrator`.

---

## Overview

The E2E tests in `tests/e2e/test_entra_id_integration.py` are **fully self-contained**:

- **Create** test users and groups in Azure AD before tests
- **Execute** SSO role mapping tests against real Azure infrastructure
- **Delete** all created resources after tests complete

This ensures repeatable, isolated test runs without manual cleanup.

---

## Prerequisites

### Azure Subscription

You need access to an Azure tenant where you can:

- Create App Registrations
- Grant admin consent for API permissions
- Create users and groups (or have a service principal that can)

### Local Development Environment

```bash
# Clone and set up the project
git clone <repository-url>
cd hoax-id
make venv install-dev
```

---

## Step 1: Create an Azure App Registration

### 1.1 Navigate to Azure Portal

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Microsoft Entra ID** > **App registrations**
3. Click **+ New registration**

### 1.2 Register the Application

| Field | Value |
|-------|-------|
| Name | `ContextForge-E2E-Tests` |
| Supported account types | Single tenant (this organization only) |
| Redirect URI | Leave blank (not needed for E2E tests) |

Click **Register**.

### 1.3 Note the Application Details

After registration, note these values from the **Overview** page:

```bash
# You'll need these later
AZURE_CLIENT_ID=<Application (client) ID>
AZURE_TENANT_ID=<Directory (tenant) ID>
```

---

## Step 2: Create a Client Secret

1. In your App Registration, go to **Certificates & secrets**
2. Click **+ New client secret**
3. Add a description: `E2E Test Secret`
4. Choose expiration: `12 months` (or as appropriate)
5. Click **Add**

**Important:** Copy the secret value immediately - it won't be shown again!

```bash
AZURE_CLIENT_SECRET=<secret-value>
```

---

## Step 3: Configure API Permissions

The service principal needs permissions to create/delete users and groups.

### 3.1 Add Required Permissions

1. Go to **API permissions**
2. Click **+ Add a permission**
3. Select **Microsoft Graph**
4. Choose **Application permissions** (not Delegated)
5. Add these permissions:

| Permission | Purpose |
|------------|---------|
| `User.ReadWrite.All` | Create and delete test users |
| `Group.ReadWrite.All` | Create and delete test groups, manage membership |
| `GroupMember.ReadWrite.All` | Add/remove users from groups |

### 3.2 Grant Admin Consent

1. Click **Grant admin consent for [Your Organization]**
2. Confirm by clicking **Yes**

You should see green checkmarks next to all permissions indicating consent is granted.

---

## Step 4: Enable Public Client Flows (Optional)

If you want to test ROPC (Resource Owner Password Credentials) token acquisition:

1. Go to **Authentication**
2. Scroll to **Advanced settings**
3. Set **Allow public client flows** to **Yes**
4. Click **Save**

> **Note:** ROPC is considered less secure and may be disabled by your organization's security policies. The E2E tests will skip ROPC tests gracefully if this is not enabled.

---

## Step 5: Determine Your Test Domain

Test users need a User Principal Name (UPN) in your tenant's domain.

### Find Your Domain

1. Go to **Microsoft Entra ID** > **Overview**
2. Look for **Primary domain** (e.g., `yourcompany.onmicrosoft.com`)

Or check **Custom domain names** for verified domains.

```bash
TEST_ENTRA_DOMAIN=yourcompany.onmicrosoft.com
```

---

## Step 6: Choose a Test User Password

The password must meet Azure AD complexity requirements:

- Minimum 8 characters
- At least 3 of: uppercase, lowercase, number, special character
- Cannot contain the user's name

```bash
# Example: Strong password for test users
TEST_ENTRA_USER_PASSWORD='ContextForge2024!Test'
```

---

## Step 7: Configure Environment Variables

Create a `.env.test` file or export variables directly:

```bash
# Azure Service Principal (for Graph API access)
export AZURE_CLIENT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
export AZURE_CLIENT_SECRET="your-client-secret-value"
export AZURE_TENANT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Test Configuration
export TEST_ENTRA_USER_PASSWORD="ContextForge2024!Test"
export TEST_ENTRA_DOMAIN="yourcompany.onmicrosoft.com"
```

### Environment Variable Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_CLIENT_ID` | Yes | App Registration's Application (client) ID |
| `AZURE_CLIENT_SECRET` | Yes | Client secret value |
| `AZURE_TENANT_ID` | Yes | Azure AD tenant ID |
| `TEST_ENTRA_USER_PASSWORD` | Yes | Password for dynamically created test users |
| `TEST_ENTRA_DOMAIN` | Yes | Domain for test user UPNs (e.g., `company.onmicrosoft.com`) |

---

## Step 8: Run the E2E Tests

### Run All Entra ID Tests

```bash
# Source your environment variables
source .env.test

# Run the tests
uv run pytest tests/e2e/test_entra_id_integration.py -v
```

### Run Specific Test Classes

```bash
# Test role mapping only
uv run pytest tests/e2e/test_entra_id_integration.py::TestEntraIDRoleMapping -v

# Test HTTP endpoints
uv run pytest tests/e2e/test_entra_id_integration.py::TestEntraIDEndToEndHTTP -v

# Test admin role retention behavior
uv run pytest tests/e2e/test_entra_id_integration.py::TestEntraIDAdminRoleRetention -v

# Test multiple admin groups
uv run pytest tests/e2e/test_entra_id_integration.py::TestEntraIDMultipleAdminGroups -v

# Test token validation
uv run pytest tests/e2e/test_entra_id_integration.py::TestEntraIDTokenValidation -v
```

### Run with Debug Output

```bash
uv run pytest tests/e2e/test_entra_id_integration.py -v -s --log-cli-level=INFO
```

---

## Test Structure

The test suite includes these test classes:

| Class | Tests | Description |
|-------|:-----:|-------------|
| `TestEntraIDRoleMapping` | 4 | Core tests for admin role assignment based on groups |
| `TestEntraIDEndToEndHTTP` | 2 | True E2E with real ROPC tokens and HTTP endpoints |
| `TestEntraIDAdminRoleRetention` | 2 | Verifies admin role retention behavior (by design) |
| `TestEntraIDMultipleAdminGroups` | 2 | Tests multiple admin group configurations |
| `TestEntraIDTokenValidation` | 4 | Tests token validation and error handling |
| `TestEntraIDSyncDisabled` | 1 | Tests behavior when role sync is disabled |

---

## Test Scenarios - Detailed Reference

### Complete Test List

| # | Test Name | Expected Behavior |
|---|-----------|-------------------|
| **TestEntraIDRoleMapping** |||
| 1 | `test_admin_user_gets_admin_role` | New user in Entra admin group → `is_admin=True` |
| 2 | `test_regular_user_does_not_get_admin_role` | New user NOT in admin group → `is_admin=False` |
| 3 | `test_user_gains_admin_when_added_to_group` | Existing non-admin user logs in with admin group → promoted to `is_admin=True` |
| 4 | `test_admin_group_matching_is_case_insensitive` | Group ID `ABC123` matches config `abc123` → `is_admin=True` |
| **TestEntraIDEndToEndHTTP** |||
| 5 | `test_sso_callback_with_real_token_creates_admin_user` | Real ROPC token from Entra ID + admin group → user created with `is_admin=True` |
| 6 | `test_sso_providers_endpoint_lists_enabled_providers` | GET `/auth/sso/providers` returns 200 or 404 (valid response) |
| **TestEntraIDAdminRoleRetention** |||
| 7 | `test_admin_retains_role_when_removed_from_group` | Existing admin logs in WITHOUT admin group → `is_admin=True` **retained** (by design) |
| 8 | `test_admin_retains_role_when_no_groups_in_token` | Existing admin logs in with empty groups → `is_admin=True` **retained** (by design) |
| **TestEntraIDMultipleAdminGroups** |||
| 9 | `test_user_in_secondary_admin_group_gets_admin` | User in 2nd configured admin group → `is_admin=True` |
| 10 | `test_user_in_both_admin_groups_gets_admin` | User in both admin groups → `is_admin=True` |
| **TestEntraIDTokenValidation** |||
| 11 | `test_expired_token_claims_detected` | Expired JWT → `jwt.ExpiredSignatureError` raised |
| 12 | `test_invalid_audience_detected` | Wrong `aud` claim → `jwt.InvalidAudienceError` raised |
| 13 | `test_invalid_issuer_detected` | Wrong `iss` claim → `jwt.InvalidIssuerError` raised |
| 14 | `test_real_token_has_valid_claims` | Real Entra token contains `sub`, `iss`, `aud`, `exp`, `iat` claims |
| **TestEntraIDSyncDisabled** |||
| 15 | `test_admin_retains_role_when_sync_disabled` | `sso_entra_sync_roles_on_login=False` → existing admin status preserved |

### Behavior Summary by Scenario

| Scenario | User State | Group Membership | Expected `is_admin` |
|----------|------------|------------------|:-------------------:|
| New user | Does not exist | In admin group | `True` |
| New user | Does not exist | Not in admin group | `False` |
| Existing user | `is_admin=False` | Gains admin group | `True` (promoted) |
| Existing user | `is_admin=True` | Loses admin group | `True` (retained)* |
| Existing user | `is_admin=True` | Empty groups claim | `True` (retained)* |
| Existing user | `is_admin=True` | Still in admin group | `True` (unchanged) |

!!! warning "Admin Role Retention Behavior"
    \*By design, the SSOService only **upgrades** admin status via SSO, never downgrades.
    This preserves manual admin grants made via Admin UI/API.
    To revoke admin access, administrators must use the Admin UI/API directly.

    See [Issue #2331](https://github.com/IBM/mcp-context-forge/issues/2331) for security
    considerations and proposed improvements to this behavior.

### What Each Test Validates

| Category | Test Coverage |
|----------|---------------|
| Admin promotion via SSO group membership | Tests 1, 3, 5 |
| Non-admin users don't get admin | Test 2 |
| Case-insensitive group ID matching | Test 4 |
| Real ROPC token acquisition | Tests 5, 14 |
| HTTP endpoint integration | Tests 5, 6 |
| Admin retention (no demotion) | Tests 7, 8, 15 |
| Multiple admin groups | Tests 9, 10 |
| Token validation errors | Tests 11, 12, 13 |

---

## What Gets Created in Azure

During test execution, the following resources are created and then deleted:

### Groups

| Resource | Purpose |
|----------|---------|
| `ContextForge-TestAdmins-{uuid}` | Primary admin group for testing |
| `ContextForge-TestAdmins2-{uuid}` | Secondary admin group (for multiple admin groups tests) |
| `ContextForge-TestUsers-{uuid}` | Regular (non-admin) group |

### Users

| Resource | Purpose |
|----------|---------|
| `cftest-admin-{uuid}@{domain}` | Test user in primary admin group |
| `cftest-regular-{uuid}@{domain}` | Test user in regular group (not admin) |

All resources are automatically cleaned up after tests complete (even on test failure).

### Resource Lifecycle

```
Test Start
    │
    ├── Create ContextForge-TestAdmins-{uuid}
    ├── Create ContextForge-TestAdmins2-{uuid}
    ├── Create ContextForge-TestUsers-{uuid}
    │       │
    │       ├── Wait for Azure AD replication
    │       │
    ├── Create cftest-admin-{uuid} → Add to TestAdmins
    ├── Create cftest-regular-{uuid} → Add to TestUsers
    │       │
    │       ├── Wait for membership replication
    │       │
    ├── Run all 15 tests
    │       │
    │       ├── Tests use real Azure group IDs
    │       ├── Tests acquire real ROPC tokens (if enabled)
    │       │
Test End (success or failure)
    │
    ├── Delete cftest-admin-{uuid}
    ├── Delete cftest-regular-{uuid}
    ├── Delete ContextForge-TestAdmins-{uuid}
    ├── Delete ContextForge-TestAdmins2-{uuid}
    └── Delete ContextForge-TestUsers-{uuid}
```

---

## Troubleshooting

### Tests Skip with "Azure credentials not configured"

Ensure all required environment variables are set:

```bash
echo $AZURE_CLIENT_ID
echo $AZURE_CLIENT_SECRET
echo $AZURE_TENANT_ID
echo $TEST_ENTRA_USER_PASSWORD
echo $TEST_ENTRA_DOMAIN
```

### "Insufficient privileges" Error

The service principal lacks required permissions. Verify:

1. Correct permissions are added (Application, not Delegated)
2. Admin consent is granted
3. The secret hasn't expired

### "Invalid client secret" Error

- Check the secret hasn't expired
- Verify you copied the **Value**, not the **Secret ID**
- Create a new secret if needed

### User Creation Fails with Password Policy Error

Your password doesn't meet Azure AD requirements:

```bash
# Good password examples
TEST_ENTRA_USER_PASSWORD='ContextForge2024!Test'
TEST_ENTRA_USER_PASSWORD='E2e-Testing-Password-123'
```

### ROPC Tests Skip

If ROPC tests are skipped, your tenant may have ROPC disabled. This is common in enterprise environments for security reasons. The other tests will still run.

---

## CI/CD Integration

### GitHub Actions Example

Add these secrets to your repository:

- `AZURE_CLIENT_ID`
- `AZURE_CLIENT_SECRET`
- `AZURE_TENANT_ID`
- `TEST_ENTRA_USER_PASSWORD`
- `TEST_ENTRA_DOMAIN`

```yaml
# .github/workflows/test.yml
jobs:
  entra-e2e:
    runs-on: ubuntu-latest
    # Only run if secrets are configured
    if: ${{ vars.AZURE_CLIENT_ID != '' }}
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install uv
          uv sync

      - name: Run Entra ID E2E Tests
        env:
          AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
          AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
          AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
          TEST_ENTRA_USER_PASSWORD: ${{ secrets.TEST_ENTRA_USER_PASSWORD }}
          TEST_ENTRA_DOMAIN: ${{ secrets.TEST_ENTRA_DOMAIN }}
        run: |
          uv run pytest tests/e2e/test_entra_id_integration.py -v
```

---

## Security Considerations

### Principle of Least Privilege

The service principal has broad permissions (`User.ReadWrite.All`, `Group.ReadWrite.All`). Consider:

- Using a dedicated test tenant
- Limiting the service principal's scope via Conditional Access
- Rotating secrets regularly

### Test Isolation

Each test run creates uniquely-named resources with UUIDs, so multiple concurrent test runs won't conflict.

### Cleanup Guarantee

The test fixtures use `pytest` finalizers that run even on test failure, ensuring resources are always cleaned up.

---

## Summary

| Step | Action |
|------|--------|
| 1 | Create Azure App Registration |
| 2 | Create client secret |
| 3 | Add API permissions (User.ReadWrite.All, Group.ReadWrite.All) |
| 4 | Grant admin consent |
| 5 | (Optional) Enable public client flows for ROPC |
| 6 | Configure environment variables |
| 7 | Run tests with `uv run pytest tests/e2e/test_entra_id_integration.py -v` |

---

## Related Documentation

- [Microsoft Graph API - Users](https://learn.microsoft.com/en-us/graph/api/resources/user)
- [Microsoft Graph API - Groups](https://learn.microsoft.com/en-us/graph/api/resources/group)
- [Azure AD App Registration](https://learn.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
- [ContextForge SSO Configuration](../configuration/sso.md)
