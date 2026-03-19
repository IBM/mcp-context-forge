#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v curl >/dev/null 2>&1; then
  echo "❌ curl is required"
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "❌ jq is required"
  exit 1
fi

if [[ -z "${COMPOSE_CMD:-}" ]]; then
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
  elif command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
    COMPOSE_CMD="podman compose"
  elif command -v podman-compose >/dev/null 2>&1; then
    COMPOSE_CMD="podman-compose"
  else
    echo "❌ Could not detect docker compose / podman compose / podman-compose"
    exit 1
  fi
fi

if [[ ! -f "docker-compose.sso.yml" ]]; then
  echo "❌ Missing docker-compose.sso.yml"
  exit 1
fi

compose() {
  # shellcheck disable=SC2086
  $COMPOSE_CMD -f docker-compose.yml -f docker-compose.sso.yml --profile sso "$@"
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-45}"
  local delay="${4:-2}"

  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "✅ $name is reachable at $url"
      return 0
    fi
    sleep "$delay"
  done

  echo "❌ Timed out waiting for $name at $url"
  return 1
}

decode_jwt_payload() {
  local token="$1"
  python3 - "$token" <<'PY'
import base64
import json
import sys

token = sys.argv[1]
parts = token.split(".")
if len(parts) != 3:
    raise SystemExit(1)
payload = parts[1] + "=" * (-len(parts[1]) % 4)
decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
json.loads(decoded)
print(decoded)
PY
}

request_password_grant() {
  local username="$1"
  curl -fsS -X POST "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=mcp-gateway" \
    --data-urlencode "client_secret=keycloak-dev-secret" \
    --data-urlencode "username=${username}" \
    --data-urlencode "password=changeme" \
    --data-urlencode "scope=openid profile email"
}

assert_user_role() {
  local username="$1"
  local expected_role="$2"

  local token_response
  token_response="$(request_password_grant "$username")"
  local access_token
  access_token="$(echo "$token_response" | jq -r '.access_token // empty')"
  if [[ -z "$access_token" ]]; then
    echo "❌ Keycloak token request failed for $username"
    echo "$token_response"
    return 1
  fi

  local payload
  payload="$(decode_jwt_payload "$access_token")"
  if ! echo "$payload" | jq -e --arg role "$expected_role" '.realm_access.roles // [] | index($role) != null' >/dev/null; then
    echo "❌ Expected role '$expected_role' not found in token for $username"
    echo "$payload" | jq '.realm_access.roles'
    return 1
  fi

  echo "✅ $username has role $expected_role"
}

assert_user_has_no_gateway_roles() {
  local username="$1"

  local token_response
  token_response="$(request_password_grant "$username")"
  local access_token
  access_token="$(echo "$token_response" | jq -r '.access_token // empty')"
  if [[ -z "$access_token" ]]; then
    echo "❌ Keycloak token request failed for $username"
    echo "$token_response"
    return 1
  fi

  local payload
  payload="$(decode_jwt_payload "$access_token")"
  if ! echo "$payload" | jq -e '.realm_access.roles // [] | map(select(startswith("gateway-"))) | length == 0' >/dev/null; then
    echo "❌ Expected no gateway-* role in token for $username"
    echo "$payload" | jq '.realm_access.roles'
    return 1
  fi

  echo "✅ $username has no explicit gateway-* roles"
}

assert_browser_callback_login() {
  local username="$1"
  local password="$2"

  local redirect_uri encoded_redirect login_json auth_url
  local cookie_file keycloak_headers callback_headers login_page form_action callback_url callback_status callback_location

  redirect_uri="http://localhost:8080/auth/sso/callback/keycloak"
  encoded_redirect="$(printf '%s' "$redirect_uri" | jq -sRr @uri)"
  login_json="$(curl -fsS "http://localhost:8080/auth/sso/login/keycloak?redirect_uri=${encoded_redirect}")"
  auth_url="$(echo "$login_json" | jq -r '.authorization_url // empty')"
  if [[ -z "$auth_url" ]]; then
    echo "❌ Could not obtain authorization URL for callback smoke test"
    echo "$login_json" | jq '.'
    return 1
  fi

  cookie_file="$(mktemp)"
  keycloak_headers="$(mktemp)"
  callback_headers="$(mktemp)"

  login_page="$(curl -fsS -c "$cookie_file" "$auth_url")"
  form_action="$(
    echo "$login_page" \
      | tr '\n' ' ' \
      | sed -n 's/.*<form[^>]*id="kc-form-login"[^>]*action="\([^"]*\)".*/\1/p' \
      | head -n1 \
      | sed 's/&amp;/\&/g'
  )"
  if [[ -z "$form_action" ]]; then
    echo "❌ Could not parse Keycloak login form action"
    rm -f "$cookie_file" "$keycloak_headers" "$callback_headers"
    return 1
  fi

  curl -sS -o /dev/null -D "$keycloak_headers" -b "$cookie_file" -c "$cookie_file" -X POST "$form_action" \
    --data-urlencode "username=${username}" \
    --data-urlencode "password=${password}" \
    --data-urlencode "credentialId="

  callback_url="$(awk 'BEGIN{IGNORECASE=1}/^Location:/{print $2}' "$keycloak_headers" | tr -d '\r' | tail -n1)"
  if [[ -z "$callback_url" ]]; then
    echo "❌ Keycloak login did not return a callback redirect"
    cat "$keycloak_headers"
    rm -f "$cookie_file" "$keycloak_headers" "$callback_headers"
    return 1
  fi

  callback_status="$(curl -sS -o /dev/null -D "$callback_headers" -w '%{http_code}' -b "$cookie_file" -c "$cookie_file" "$callback_url")"
  callback_location="$(awk 'BEGIN{IGNORECASE=1}/^Location:/{print $2}' "$callback_headers" | tr -d '\r' | tail -n1)"

  if [[ "$callback_status" != "302" ]]; then
    echo "❌ Gateway callback did not return redirect (status=$callback_status)"
    cat "$callback_headers"
    rm -f "$cookie_file" "$keycloak_headers" "$callback_headers"
    return 1
  fi

  if [[ "$callback_location" != "/admin" && "$callback_location" != "http://localhost:8080/admin" ]]; then
    echo "❌ Gateway callback redirected to unexpected location: $callback_location"
    cat "$callback_headers"
    rm -f "$cookie_file" "$keycloak_headers" "$callback_headers"
    return 1
  fi

  if ! grep -qi '^set-cookie: jwt_token=' "$callback_headers"; then
    echo "❌ Gateway callback did not set jwt_token cookie"
    cat "$callback_headers"
    rm -f "$cookie_file" "$keycloak_headers" "$callback_headers"
    return 1
  fi

  echo "✅ Browser callback flow redirects to /admin and sets auth cookie"

  rm -f "$cookie_file" "$keycloak_headers" "$callback_headers"
}

echo "🔍 Checking compose services..."
compose ps >/dev/null

wait_for_http "Keycloak OIDC discovery" "http://localhost:8180/realms/mcp-gateway/.well-known/openid-configuration"
wait_for_http "Gateway" "http://localhost:8080/health"

echo "🔍 Verifying SSO providers..."
providers_json="$(curl -fsS "http://localhost:8080/auth/sso/providers")"
if ! echo "$providers_json" | jq -e '.[] | select(.id == "keycloak")' >/dev/null; then
  echo "❌ Keycloak provider not found in /auth/sso/providers"
  echo "$providers_json" | jq '.'
  exit 1
fi
echo "✅ Keycloak provider is exposed by gateway"

echo "🔍 Verifying SSO login URL..."
encoded_redirect="$(printf '%s' 'http://localhost:8080/auth/sso/callback/keycloak' | jq -sRr @uri)"
login_json="$(curl -fsS "http://localhost:8080/auth/sso/login/keycloak?redirect_uri=${encoded_redirect}")"
auth_url="$(echo "$login_json" | jq -r '.authorization_url // empty')"
if [[ -z "$auth_url" ]]; then
  echo "❌ Gateway did not return an authorization URL"
  echo "$login_json" | jq '.'
  exit 1
fi
if [[ "$auth_url" != http://localhost:8180/* ]]; then
  echo "❌ Authorization URL should target browser-facing Keycloak (localhost:8180)"
  echo "   Actual: $auth_url"
  exit 1
fi
echo "✅ Authorization URL is browser-accessible"

echo "🔍 Verifying pre-seeded Keycloak users and role claims..."
assert_user_role "admin@example.com" "gateway-admin"
assert_user_role "developer@example.com" "gateway-developer"
assert_user_role "viewer@example.com" "gateway-viewer"
assert_user_has_no_gateway_roles "newuser@example.com"

echo "🔍 Verifying browser callback flow..."
assert_browser_callback_login "admin@example.com" "changeme"

echo ""
echo "✅ SSO smoke checks passed."
echo "   Next manual check:"
echo "   1) Open http://localhost:8080/admin/login"
echo "   2) Click 'Continue with Keycloak'"
echo "   3) Login with: newuser@example.com / changeme (or admin/developer/viewer users)"
