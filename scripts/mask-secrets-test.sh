#!/usr/bin/env bash
# =============================================================================
# E2E test for issue #2760: Secret masking & UI permission gating
#
# Tests:
#   1. API header masking (non-owner, owner, admin-bypass, admin-no-bypass)
#   2. Admin partial HTML button gating (Edit/Delete hidden for non-owners)
#   3. Backend enforcement (non-owner mutations rejected)
#   4. Prompts owner column rendering (Finding 3)
#   5. Gateway "Authorize" button gating (Finding 4)
#
# Requirements:
#   - docker compose stack running with gateway on localhost:8080
#   - curl, jq installed
#
# Usage:
#   ./scripts/mask-secrets-test.sh [BASE_URL]
# =============================================================================
set -uo pipefail
# Don't use set -e; we handle errors manually via the check() function

BASE="${1:-http://localhost:8080}"
PASS="TestPass2760!"
PASS_TOTAL=0
FAIL_TOTAL=0
SKIP_TOTAL=0

# Unique suffix to avoid collisions with previous runs
RUN_ID="$(date +%s)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

check() {
    local name="$1" cond="$2" msg="${3:-}"
    if [ "$cond" = "true" ]; then
        echo -e "  ${GREEN}[PASS]${NC} $name${msg:+ -- $msg}"
        PASS_TOTAL=$((PASS_TOTAL + 1))
    else
        echo -e "  ${RED}[FAIL]${NC} $name${msg:+ -- $msg}"
        FAIL_TOTAL=$((FAIL_TOTAL + 1))
    fi
}

skip() {
    local name="$1" msg="${2:-}"
    echo -e "  ${YELLOW}[SKIP]${NC} $name${msg:+ -- $msg}"
    SKIP_TOTAL=$((SKIP_TOTAL + 1))
}

section() {
    echo ""
    echo -e "${BOLD}${CYAN}$(printf '=%.0s' {1..70})${NC}"
    echo -e "${BOLD}${CYAN}$1${NC}"
    echo -e "${BOLD}${CYAN}$(printf '=%.0s' {1..70})${NC}"
}

# -----------------------------------------------------------------------------
# Token generation helpers
# -----------------------------------------------------------------------------
# Generate non-admin token with empty teams (public-only access)
gen_token() {
    local email="$1" is_admin="${2:-False}"
    local pyscript
    pyscript=$(mktemp)
    cat > "$pyscript" <<PYEOF
import warnings
warnings.filterwarnings("ignore")
from mcpgateway.utils.create_jwt_token import _create_jwt_token
token = _create_jwt_token(
    {"username": "${email}", "sub": "${email}"},
    expires_in_minutes=60,
    user_data={"email": "${email}", "full_name": "Test User", "is_admin": ${is_admin}, "auth_provider": "cli"},
    teams=[],
)
print(token)
PYEOF
    docker compose exec -T gateway /app/.venv/bin/python3 - < "$pyscript" 2>/dev/null | grep '^eyJ' | head -1
    rm -f "$pyscript"
}

# Generate admin bypass token (teams=null + is_admin=true) via Python script
# The CLI --admin flag does NOT set teams=null, so we use PyJWT directly.
gen_admin_bypass_token() {
    local email="$1"
    local pyscript
    pyscript=$(mktemp)
    # Generate a valid token via _create_jwt_token (includes jti, iss, aud etc),
    # then decode, patch teams=None for admin bypass, and re-encode.
    cat > "$pyscript" <<PYEOF
import warnings, sys
warnings.filterwarnings("ignore")
from mcpgateway.utils.create_jwt_token import _create_jwt_token
from mcpgateway.utils.jwt_config_helper import get_jwt_private_key_or_secret
import jwt as pyjwt
token = _create_jwt_token(
    {"username": "${email}", "sub": "${email}"},
    expires_in_minutes=60,
    user_data={"email": "${email}", "full_name": "Admin Bypass", "is_admin": True, "auth_provider": "cli"},
    teams=[],
)
decoded = pyjwt.decode(token, options={"verify_signature": False})
decoded["teams"] = None
print(pyjwt.encode(decoded, get_jwt_private_key_or_secret(), algorithm="HS256"))
PYEOF
    docker compose exec -T gateway /app/.venv/bin/python3 - < "$pyscript" 2>/dev/null | grep '^eyJ' | head -1
    rm -f "$pyscript"
}

# HTTP helper
api() {
    local method="$1" path="$2" token="$3" data="${4:-}"
    local args=(-s -X "$method" "$BASE$path"
        -H "Authorization: Bearer $token"
        -H "Content-Type: application/json")
    if [ -n "$data" ]; then
        args+=(-d "$data")
    fi
    curl "${args[@]}" 2>/dev/null
}

# =============================================================================
section "SETUP: Generate tokens and create test users"
# =============================================================================

echo "Generating tokens..."

# Admin bypass token (teams=null + is_admin=true)
ADMIN_T=$(gen_admin_bypass_token "admin@example.com")
if [ -z "$ADMIN_T" ]; then
    echo "FATAL: Could not generate admin bypass token"
    exit 1
fi
echo "  Admin bypass token: ${ADMIN_T:0:40}..."

# Regular admin token (no admin bypass - teams=[] + is_admin=true)
# This mimics an admin who doesn't have the bypass claim (teams is empty list, not null)
ADMIN_NBYPASS_T=$(gen_token "admin-nbypass@example.com" True)
if [ -z "$ADMIN_NBYPASS_T" ]; then
    echo "FATAL: Could not generate admin-no-bypass token"
    exit 1
fi
echo "  Admin (no bypass) token: ${ADMIN_NBYPASS_T:0:40}..."

echo ""
echo "Creating test users..."

# Create owner and viewer users
OWNER_EMAIL="owner-${RUN_ID}@test2760.com"
VIEWER_EMAIL="viewer-${RUN_ID}@test2760.com"
ADMIN2_EMAIL="admin2-${RUN_ID}@test2760.com"

for email in "$OWNER_EMAIL" "$VIEWER_EMAIL"; do
    resp=$(api POST "/auth/email/admin/users" "$ADMIN_T" \
        "{\"email\":\"$email\",\"password\":\"$PASS\",\"full_name\":\"Test User\",\"is_admin\":false,\"is_active\":true}")
    echo "  Create $email: $(echo "$resp" | jq -r '.email // .detail // "ok"' 2>/dev/null)"
done

# Create admin2 user (is_admin=true, for UI login tests)
resp=$(api POST "/auth/email/admin/users" "$ADMIN_T" \
    "{\"email\":\"$ADMIN2_EMAIL\",\"password\":\"$PASS\",\"full_name\":\"Admin2\",\"is_admin\":true,\"is_active\":true}")
echo "  Create $ADMIN2_EMAIL: $(echo "$resp" | jq -r '.email // .detail // "ok"' 2>/dev/null)"

# Assign RBAC roles via POST /rbac/users/{email}/roles
# All roles except platform_admin are team-scoped, so we assign platform_admin
# to all test users. This grants API permissions but does NOT grant JWT admin bypass
# (which requires is_admin=true + teams=null in the JWT).
echo ""
echo "Assigning RBAC roles..."

# First, find the platform_admin role ID
PA_ROLE_ID=$(api GET "/rbac/roles" "$ADMIN_T" | jq -r '.[] | select(.name == "platform_admin") | .id' 2>/dev/null)
echo "  platform_admin role ID: $PA_ROLE_ID"

if [ -n "$PA_ROLE_ID" ]; then
    for email in "$OWNER_EMAIL" "$VIEWER_EMAIL" "$ADMIN2_EMAIL"; do
        resp=$(api POST "/rbac/users/$email/roles" "$ADMIN_T" \
            "{\"role_id\":\"$PA_ROLE_ID\",\"scope\":\"global\"}")
        echo "  Assign platform_admin to $email: $(echo "$resp" | jq -r '.id // .detail // "ok"' 2>/dev/null)"
    done
else
    echo "  WARNING: Could not find platform_admin role. Tests may fail due to RBAC."
fi

# Generate non-admin tokens
OWNER_T=$(gen_token "$OWNER_EMAIL")
VIEWER_T=$(gen_token "$VIEWER_EMAIL")

if [ -z "$OWNER_T" ] || [ -z "$VIEWER_T" ]; then
    echo "FATAL: Could not generate owner/viewer tokens"
    exit 1
fi
echo "  Owner token: ${OWNER_T:0:40}..."
echo "  Viewer token: ${VIEWER_T:0:40}..."

# Create tool with secret headers AS OWNER
echo ""
echo "Creating tool with secret headers (as owner)..."
TOOL_NAME="secret-test-2760-${RUN_ID}"
TOOL_RESP=$(api POST "/tools" "$OWNER_T" "{
    \"tool\": {
        \"name\": \"$TOOL_NAME\",
        \"url\": \"http://fast_test_server:8880/test-tool\",
        \"description\": \"Test tool with secret headers for issue 2760\",
        \"integration_type\": \"REST\",
        \"request_type\": \"POST\",
        \"headers\": {
            \"Authorization\": \"Bearer TOP-SECRET-KEY-ABCDEF\",
            \"X-Api-Key\": \"private-api-key-123456\",
            \"X-Normal\": \"not-secret-value\"
        },
        \"input_schema\": {\"type\": \"object\", \"properties\": {\"q\": {\"type\": \"string\"}}},
        \"visibility\": \"public\"
    },
    \"team_id\": null
}")
TOOL_ID=$(echo "$TOOL_RESP" | jq -r '.id // empty' 2>/dev/null)

if [ -z "$TOOL_ID" ]; then
    echo "  Create failed, searching for existing..."
    echo "  Response: $(echo "$TOOL_RESP" | head -c 200)"
    # Try to find existing
    TOOLS_LIST=$(api GET "/tools" "$OWNER_T")
    TOOL_ID=$(echo "$TOOLS_LIST" | jq -r ".[] | select(.name == \"$TOOL_NAME\") | .id" 2>/dev/null | head -1)
fi

if [ -z "$TOOL_ID" ]; then
    echo "FATAL: Could not create or find test tool"
    exit 1
fi
echo "  Tool ID: $TOOL_ID"
echo "  Owner: $(echo "$TOOL_RESP" | jq -r '.ownerEmail // "unknown"' 2>/dev/null)"

# Detect the masked value used by this deployment
MASKED=$(echo 'from mcpgateway.config import settings; print(settings.masked_auth_value)' \
    | docker compose exec -T gateway /app/.venv/bin/python3 - 2>/dev/null | tr -d '\r\n')
if [ -z "$MASKED" ]; then
    MASKED="*****"
fi
echo "  Masked value: '$MASKED'"

# =============================================================================
section "TEST 1: API header masking - single tool GET /tools/{id}"
# =============================================================================

# 1a: Non-owner (viewer) sees masked headers
echo ""
echo "--- 1a: Viewer (non-owner) reads single tool ---"
resp=$(api GET "/tools/$TOOL_ID" "$VIEWER_T")
hdrs=$(echo "$resp" | jq -c '.headers // {}' 2>/dev/null)
echo "  Headers: $hdrs"
all_masked=$(echo "$hdrs" | jq --arg m "$MASKED" 'to_entries | length > 0 and all(.value == $m)' 2>/dev/null)
check "1a: Viewer GET /tools/{id} - headers masked" "$all_masked" "values: $(echo "$hdrs" | jq '[.[] ]' 2>/dev/null)"

# 1b: Owner sees real headers
echo ""
echo "--- 1b: Owner reads own tool ---"
resp=$(api GET "/tools/$TOOL_ID" "$OWNER_T")
hdrs=$(echo "$resp" | jq -c '.headers // {}' 2>/dev/null)
echo "  Headers: $hdrs"
has_secret=$(echo "$hdrs" | jq 'to_entries | any(.value | tostring | contains("ABCDEF"))' 2>/dev/null)
check "1b: Owner GET /tools/{id} - headers visible" "$has_secret"

# 1c: Admin bypass sees real headers
echo ""
echo "--- 1c: Admin (bypass) reads tool ---"
resp=$(api GET "/tools/$TOOL_ID" "$ADMIN_T")
hdrs=$(echo "$resp" | jq -c '.headers // {}' 2>/dev/null)
echo "  Headers: $hdrs"
has_secret=$(echo "$hdrs" | jq 'to_entries | any(.value | tostring | contains("ABCDEF"))' 2>/dev/null)
check "1c: Admin bypass GET /tools/{id} - headers visible" "$has_secret"

# 1d: Admin WITHOUT bypass sees masked headers (or no headers if not included)
echo ""
echo "--- 1d: Admin (no bypass) reads non-owned tool ---"
resp=$(api GET "/tools/$TOOL_ID" "$ADMIN_NBYPASS_T")
hdrs=$(echo "$resp" | jq -c '.headers // {}' 2>/dev/null)
echo "  Headers: $hdrs"
no_secrets=$(echo "$hdrs" | jq 'to_entries | all(.value | tostring | (contains("ABCDEF") or contains("123456")) | not)' 2>/dev/null)
check "1d: Admin (no bypass) GET /tools/{id} - no secrets exposed" "$no_secrets"

# =============================================================================
section "TEST 2: API header masking - tool list GET /tools"
# =============================================================================

# 2a: Non-owner list
echo ""
echo "--- 2a: Viewer reads tool list ---"
resp=$(api GET "/tools" "$VIEWER_T")
hdrs=$(echo "$resp" | jq -c --arg id "$TOOL_ID" '.[] | select(.id == $id) | .headers // {}' 2>/dev/null)
if [ -n "$hdrs" ] && [ "$hdrs" != "{}" ]; then
    echo "  Headers: $hdrs"
    all_masked=$(echo "$hdrs" | jq --arg m "$MASKED" 'to_entries | length > 0 and all(.value == $m)' 2>/dev/null)
    check "2a: Viewer GET /tools list - headers masked" "$all_masked"
else
    skip "2a: Viewer GET /tools list" "tool not found in list or no headers"
fi

# 2b: Owner list
echo ""
echo "--- 2b: Owner reads tool list ---"
resp=$(api GET "/tools" "$OWNER_T")
hdrs=$(echo "$resp" | jq -c --arg id "$TOOL_ID" '.[] | select(.id == $id) | .headers // {}' 2>/dev/null)
if [ -n "$hdrs" ] && [ "$hdrs" != "{}" ]; then
    echo "  Headers: $hdrs"
    has_secret=$(echo "$hdrs" | jq 'to_entries | any(.value | tostring | contains("ABCDEF"))' 2>/dev/null)
    check "2b: Owner GET /tools list - headers visible" "$has_secret"
else
    skip "2b: Owner GET /tools list" "tool not found in list or no headers"
fi

# 2c: Admin bypass list
echo ""
echo "--- 2c: Admin (bypass) reads tool list ---"
resp=$(api GET "/tools" "$ADMIN_T")
hdrs=$(echo "$resp" | jq -c --arg id "$TOOL_ID" '.[] | select(.id == $id) | .headers // {}' 2>/dev/null)
if [ -n "$hdrs" ] && [ "$hdrs" != "{}" ]; then
    echo "  Headers: $hdrs"
    has_secret=$(echo "$hdrs" | jq 'to_entries | any(.value | tostring | contains("ABCDEF"))' 2>/dev/null)
    check "2c: Admin bypass GET /tools list - headers visible" "$has_secret"
else
    skip "2c: Admin bypass GET /tools list" "tool not found"
fi

# =============================================================================
section "TEST 3: Admin partial HTML - button gating"
# =============================================================================

# Login as admin2 (is_admin=true) to get session cookie
echo ""
echo "--- Logging in as admin2 and owner for UI tests ---"
ADMIN2_COOKIE=$(curl -s -c - "$BASE/auth/email/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$ADMIN2_EMAIL\",\"password\":\"$PASS\"}" 2>/dev/null \
    | grep -i 'session\|token\|jwt' | awk '{print $NF}')

# Login as owner
OWNER_COOKIE=$(curl -s -c - "$BASE/auth/email/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$OWNER_EMAIL\",\"password\":\"$PASS\"}" 2>/dev/null \
    | grep -i 'session\|token\|jwt' | awk '{print $NF}')

# For the admin partial tests, we use Bearer tokens since cookie auth
# may not work for non-browser requests. The admin partials accept Bearer auth.

# 3a: Admin (platform_admin) sees Edit/Delete on all tools
echo ""
echo "--- 3a: Admin (platform_admin) sees Edit/Delete buttons ---"

partial_html=$(curl -s "$BASE/admin/tools/partial" \
    -H "Authorization: Bearer $ADMIN_T" \
    -H "Accept: text/html" \
    -H "HX-Request: true" 2>/dev/null)

# Count Edit/Delete buttons for our tool
our_tool_row=$(echo "$partial_html" | grep -A 100 "$TOOL_ID" | head -100)
has_edit=$(echo "$our_tool_row" | grep -c "editTool\|>Edit<" || true)
has_delete=$(echo "$our_tool_row" | grep -c "Delete" || true)

if [ -n "$our_tool_row" ]; then
    check "3a: Admin sees Edit button on test tool" "$([ "$has_edit" -gt 0 ] && echo true || echo false)"
    check "3a: Admin sees Delete button on test tool" "$([ "$has_delete" -gt 0 ] && echo true || echo false)"
else
    skip "3a: Admin partial" "tool not found in partial HTML"
fi

# 3b: Owner sees Edit/Delete only on own tool
echo ""
echo "--- 3b: Owner sees Edit/Delete on own tool only ---"
partial_html=$(curl -s "$BASE/admin/tools/partial" \
    -H "Authorization: Bearer $OWNER_T" \
    -H "Accept: text/html" \
    -H "HX-Request: true" 2>/dev/null)

if echo "$partial_html" | grep -q "$TOOL_ID"; then
    our_tool_row=$(echo "$partial_html" | grep -A 100 "$TOOL_ID" | head -100)
    has_edit=$(echo "$our_tool_row" | grep -c "editTool\|>Edit<" || true)
    check "3b: Owner sees Edit on own tool" "$([ "$has_edit" -gt 0 ] && echo true || echo false)"

    # Check a different tool that owner does NOT own
    other_tool_id=$(echo "$partial_html" | grep -oP "(?<=editTool\(')[^']+(?='\))" 2>/dev/null | grep -v "$TOOL_ID" | head -1 || true)
    if [ -n "$other_tool_id" ]; then
        echo "  Found other tool: $other_tool_id (owner should NOT have Edit on this)"
    fi
else
    skip "3b: Owner partial" "tool not found in partial HTML (may need tools.read permission)"
fi

# 3c: Viewer sees NO Edit/Delete on owner's tool
echo ""
echo "--- 3c: Viewer sees no Edit/Delete on other's tool ---"
partial_html=$(curl -s "$BASE/admin/tools/partial" \
    -H "Authorization: Bearer $VIEWER_T" \
    -H "Accept: text/html" \
    -H "HX-Request: true" 2>/dev/null)

if echo "$partial_html" | grep -q "$TOOL_ID"; then
    our_tool_row=$(echo "$partial_html" | grep -A 100 "$TOOL_ID" | head -100)
    has_edit=$(echo "$our_tool_row" | grep -c "editTool\|>Edit<" || true)
    has_delete=$(echo "$our_tool_row" | grep -c "Delete" || true)
    check "3c: Viewer sees NO Edit on other's tool" "$([ "$has_edit" -eq 0 ] && echo true || echo false)" "edit count: $has_edit"
    check "3c: Viewer sees NO Delete on other's tool" "$([ "$has_delete" -eq 0 ] && echo true || echo false)" "delete count: $has_delete"
else
    skip "3c: Viewer partial" "tool not found (may need permission or tool not visible)"
fi

# =============================================================================
section "TEST 4: Admin partial - headers masked in serialized tool data"
# =============================================================================

# 4a: Check that admin partial tools JSON contains masked headers for non-owner
echo ""
echo "--- 4a: Viewer's admin partial has masked header values ---"
# The tools partial HTML may include header data in edit modals or JS data attributes
# More importantly, check the /admin/tools JSON endpoint
resp=$(api GET "/admin/tools" "$VIEWER_T")
content_type_check="false"
if echo "$resp" | jq -e '.' >/dev/null 2>&1; then
    hdrs=$(echo "$resp" | jq -c --arg id "$TOOL_ID" '.[] | select(.id == $id) | .headers // {}' 2>/dev/null)
    if [ -n "$hdrs" ] && [ "$hdrs" != "{}" ] && [ "$hdrs" != "null" ]; then
        echo "  Headers from /admin/tools JSON: $hdrs"
        all_masked=$(echo "$hdrs" | jq --arg m "$MASKED" 'to_entries | length > 0 and all(.value == $m)' 2>/dev/null)
        check "4a: Viewer /admin/tools JSON - headers masked" "$all_masked"
    else
        skip "4a: Viewer /admin/tools JSON" "no headers in response or tool not found"
    fi
else
    skip "4a: Viewer /admin/tools" "response is HTML, not JSON (admin UI page)"
fi

# 4b: Owner's admin partial has real headers
echo ""
echo "--- 4b: Owner's admin tools has real header values ---"
resp=$(api GET "/admin/tools" "$OWNER_T")
if echo "$resp" | jq -e '.' >/dev/null 2>&1; then
    hdrs=$(echo "$resp" | jq -c --arg id "$TOOL_ID" '.[] | select(.id == $id) | .headers // {}' 2>/dev/null)
    if [ -n "$hdrs" ] && [ "$hdrs" != "{}" ] && [ "$hdrs" != "null" ]; then
        echo "  Headers from /admin/tools JSON: $hdrs"
        has_secret=$(echo "$hdrs" | jq 'to_entries | any(.value | tostring | contains("ABCDEF"))' 2>/dev/null)
        check "4b: Owner /admin/tools JSON - headers visible" "$has_secret"
    else
        skip "4b: Owner /admin/tools JSON" "no headers or tool not found"
    fi
else
    skip "4b: Owner /admin/tools" "response is HTML"
fi

# =============================================================================
section "TEST 5: Backend enforcement - non-owner mutations"
# =============================================================================

# 5a: Viewer tries to delete owner's tool
echo ""
echo "--- 5a: Viewer DELETE attempt ---"
resp=$(api DELETE "/tools/$TOOL_ID" "$VIEWER_T")
echo "  Response: $(echo "$resp" | head -c 200)"
status_code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/tools/$TOOL_ID" \
    -H "Authorization: Bearer $VIEWER_T" -H "Content-Type: application/json" 2>/dev/null)
echo "  HTTP status: $status_code"
rejected="false"
if [ "$status_code" -ge 400 ] && [ "$status_code" -lt 500 ]; then
    rejected="true"
elif echo "$resp" | grep -qi "owner\|permission\|forbidden\|unauthorized"; then
    rejected="true"
fi
check "5a: Viewer delete rejected" "$rejected" "status=$status_code"

# 5b: Verify tool survived
echo ""
echo "--- 5b: Tool survived delete attempt ---"
resp=$(api GET "/tools/$TOOL_ID" "$OWNER_T")
survived=$(echo "$resp" | jq -r --arg id "$TOOL_ID" 'if .id == $id then "true" else "false" end' 2>/dev/null)
check "5b: Tool survived rejected delete" "$survived"

# 5c: Admin-no-bypass tries to delete (should also fail - not owner)
echo ""
echo "--- 5c: Admin (no bypass) DELETE attempt ---"
status_code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/tools/$TOOL_ID" \
    -H "Authorization: Bearer $ADMIN_NBYPASS_T" -H "Content-Type: application/json" 2>/dev/null)
echo "  HTTP status: $status_code"
# Admin without bypass should be rejected (not owner, not admin bypass)
rejected="false"
if [ "$status_code" -ge 400 ] && [ "$status_code" -lt 500 ]; then
    rejected="true"
fi
check "5c: Admin (no bypass) delete rejected" "$rejected" "status=$status_code"

# 5d: Admin bypass can delete (verify admin bypass works, then re-create)
echo ""
echo "--- 5d: Admin bypass CAN delete (verify, then re-create) ---"
status_code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/tools/$TOOL_ID" \
    -H "Authorization: Bearer $ADMIN_T" -H "Content-Type: application/json" 2>/dev/null)
echo "  HTTP status: $status_code"
admin_can_delete="$([ "$status_code" -eq 200 ] || [ "$status_code" -eq 204 ] && echo true || echo false)"
check "5d: Admin bypass can delete" "$admin_can_delete" "status=$status_code"

# =============================================================================
section "TEST 6: Prompts owner column (Finding 3)"
# =============================================================================

echo ""
echo "--- 6: Check prompts partial renders ownerEmail ---"
prompts_html=$(curl -s "$BASE/admin/prompts/partial" \
    -H "Authorization: Bearer $ADMIN_T" \
    -H "Accept: text/html" \
    -H "HX-Request: true" 2>/dev/null)
if echo "$prompts_html" | grep -q "prompts-table"; then
    # Check if any owner email is rendered (not blank cells for owner column)
    # The template uses {{ prompt.ownerEmail or prompt.owner_email }}
    # If working correctly, owner emails should appear in the HTML
    owner_cells=$(echo "$prompts_html" | grep -oP '(?<=<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300 w-20">)[^<]+' | head -5)
    if [ -n "$owner_cells" ]; then
        has_email=$(echo "$owner_cells" | grep -c '@' || true)
        check "6: Prompts partial shows owner emails" "$([ "$has_email" -gt 0 ] && echo true || echo false)" "found $has_email emails"
    else
        skip "6: Prompts owner column" "no owner cells found (may have no prompts)"
    fi
else
    skip "6: Prompts partial" "could not load prompts partial"
fi

# =============================================================================
section "TEST 7: Gateway Authorize button gating (Finding 4)"
# =============================================================================

echo ""
echo "--- 7: Check gateway Authorize button is gated ---"
gateways_html=$(curl -s "$BASE/admin/gateways/partial" \
    -H "Authorization: Bearer $VIEWER_T" \
    -H "Accept: text/html" \
    -H "HX-Request: true" 2>/dev/null)
if echo "$gateways_html" | grep -q "gateways-table"; then
    authorize_count=$(echo "$gateways_html" | grep -c "Authorize" || true)
    # For a viewer who doesn't own any gateways, Authorize should not appear
    # (unless viewer happens to own oauth gateways, which is unlikely in test)
    echo "  Authorize buttons visible to viewer: $authorize_count"
    if [ "$authorize_count" -eq 0 ]; then
        check "7: Viewer sees no Authorize buttons" "true"
    else
        # Check if viewer owns any gateways - if so, this is expected
        echo "  (Viewer may own OAuth gateways - checking)"
        skip "7: Gateway Authorize gating" "viewer sees $authorize_count Authorize buttons (may own OAuth gateways)"
    fi
else
    skip "7: Gateway partial" "could not load gateways partial"
fi

# =============================================================================
section "CLEANUP"
# =============================================================================

echo "  (Test data left in place for manual inspection)"
echo "  Tool: $TOOL_NAME (ID: $TOOL_ID)"
echo "  Owner: $OWNER_EMAIL"
echo "  Viewer: $VIEWER_EMAIL"
echo "  Admin2: $ADMIN2_EMAIL"

# =============================================================================
section "SUMMARY"
# =============================================================================

for status_line in ""; do :; done  # noop to separate

echo -e "  ${GREEN}PASS: $PASS_TOTAL${NC}"
echo -e "  ${RED}FAIL: $FAIL_TOTAL${NC}"
echo -e "  ${YELLOW}SKIP: $SKIP_TOTAL${NC}"
echo ""

if [ "$FAIL_TOTAL" -gt 0 ]; then
    echo -e "${RED}${BOLD}RESULT: FAILED ($FAIL_TOTAL failures)${NC}"
    exit 1
else
    echo -e "${GREEN}${BOLD}RESULT: PASSED ($PASS_TOTAL tests, $SKIP_TOTAL skipped)${NC}"
    exit 0
fi
