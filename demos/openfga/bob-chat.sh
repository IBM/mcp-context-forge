#!/usr/bin/env bash
# Location: ./demos/openfga/bob-chat.sh
#
# Open one tmux window with 4 panes, one Bob chat per demo user.
#
# The script talks to the running ContextForge gateway, mints a fresh API
# key per user (alice, becky, carol, david), writes one bobshell mcp.json
# per user, and starts one bobshell container per pane. The containers run
# attached to the tmux panes: close a pane (or detach with Ctrl-b d and
# later kill the session) and its container stops.
#
# Requirements:
#   - The demo stack is up (see docker-compose.demo-openfga.yml).
#   - tmux, docker, jq, curl.
#   - BOBSHELL_API_KEY in the environment: the Bob inference key from the
#     Bob web portal. It is passed to every container as BOB_API_KEY.
#
# Environment:
#   GATEWAY_URL           Gateway base URL as seen from a container
#                         (default http://host.docker.internal:8080;
#                          on Linux set http://172.17.0.1:8080 or similar).
#   HOST_GATEWAY_URL      Gateway base URL as seen from this host
#                         (default http://localhost:8080). Key minting
#                         uses this URL.
#   DEMO_USER_PASSWORD    Demo account password
#                         (default Demo!Passw0rd#2026, matches the seeder).
#   SESSION               tmux session name (default bob-demo).
#
# Each run mints 1 new key per user named bobshell-demo-<timestamp>. Revoke
# old demo keys from the Admin UI token catalog when they pile up.

set -euo pipefail

SESSION="${SESSION:-bob-demo}"
USERS=(alice becky carol david)
HOST_GATEWAY_URL="${HOST_GATEWAY_URL:-http://localhost:8080}"
GATEWAY_URL="${GATEWAY_URL:-http://host.docker.internal:8080}"
DEMO_USER_PASSWORD="${DEMO_USER_PASSWORD:-Demo!Passw0rd#2026}"  # pragma: allowlist secret
SERVER_NAME="fast-time-demo"
TEAM_NAME="OpenFGA Demo Team"
BOBSHELL_IMAGE="${BOBSHELL_IMAGE:-ghcr.io/ibm/cfex-bobshell:latest}"

die() { echo "bob-chat: $*" >&2; exit 1; }

command -v tmux >/dev/null || die "tmux is required"
command -v jq >/dev/null || die "jq is required"
command -v curl >/dev/null || die "curl is required"
[ -n "${BOBSHELL_API_KEY:-}" ] || die "set BOBSHELL_API_KEY (Bob inference key) first"

# Colima shares only the home directory with containers, and Docker
# Desktop shares /var/folders unreliably for single files. Anchor the
# workspace under the home directory so every Docker backend mounts it.
WORKDIR="$(mktemp -d "${HOME}/.cache/bob-demo.XXXXXX")"
echo "bob-chat: workspace ${WORKDIR}"

api() { # api METHOD PATH [JSON] [TOKEN] -> body
    local method="$1"
    local path="$2"
    local data="${3-}"
    local token="${4-}"
    local args=(-sS -X "$method" "${HOST_GATEWAY_URL}${path}" -H 'Content-Type: application/json')
    [ -n "$token" ] && args+=(-H "Authorization: Bearer ${token}")
    [ -n "$data" ] && args+=(-d "$data")
    curl "${args[@]}"
}

login() {
    local email="$1" password="$2"
    api POST /auth/email/login "{\"email\":\"${email}\",\"password\":\"${password}\"}" | jq -r '.access_token // empty'
}

# Resolve the virtual server id with the admin account.
ADMIN_EMAIL="${PLATFORM_ADMIN_EMAIL:-admin@example.com}"
PLATFORM_ADMIN_PASSWORD="${PLATFORM_ADMIN_PASSWORD:-$(grep -E '^PLATFORM_ADMIN_PASSWORD=' "$(dirname "$0")/../../.env" 2>/dev/null | cut -d= -f2-)}"  # pragma: allowlist secret
[ -n "${PLATFORM_ADMIN_PASSWORD:-}" ] || die "set PLATFORM_ADMIN_PASSWORD or keep the repo .env present"
ADMIN_TOKEN="$(login "${ADMIN_EMAIL}" "${PLATFORM_ADMIN_PASSWORD}")"
[ -n "${ADMIN_TOKEN}" ] || die "admin login failed"

SERVER_ID="$(api GET /servers "" "${ADMIN_TOKEN}" | jq -r ".[] | select(.name == \"${SERVER_NAME}\") | .id")"
[ -n "${SERVER_ID}" ] || die "virtual server ${SERVER_NAME} not found; run the demo-seed service first"
TEAM_ID="$(api GET /teams/ "" "${ADMIN_TOKEN}" | jq -r "(if type == \"array\" then . else .teams end)[] | select(.name == \"${TEAM_NAME}\") | .id")"
[ -n "${TEAM_ID}" ] || die "team ${TEAM_NAME} not found; run the demo-seed service first"
echo "bob-chat: virtual server ${SERVER_NAME} = ${SERVER_ID}; team ${TEAM_NAME} = ${TEAM_ID}"

STAMP="$(date +%H%M%S)"

for user in "${USERS[@]}"; do
    USER_TOKEN="$(login "${user}@demo.example.com" "${DEMO_USER_PASSWORD}")"
    [ -n "${USER_TOKEN}" ] || die "login failed for ${user}@demo.example.com (run demo-seed, check DEMO_USER_PASSWORD)"
    KEY="$(api POST /tokens "{\"name\":\"bobshell-demo-${STAMP}\",\"expires_in_days\":1,\"team_id\":\"${TEAM_ID}\",\"scope\":{\"permissions\":[\"tools.read\",\"tools.execute\"]}}" "${USER_TOKEN}" | jq -r '.access_token // empty')"
    [ -n "${KEY}" ] || die "key mint failed for ${user}"
    mkdir -p "${WORKDIR}/${user}"
    # Entry schema for bob 2.0.5: the session layer requires type+url.
    # The httpURL shape (used by the bobshell example's sample config) is
    # accepted by "bob mcp list" but never reaches the session hub.
    jq -n --arg url "${GATEWAY_URL}/servers/${SERVER_ID}/mcp/" --arg key "${KEY}" \
        '{mcpServers: {fast_time: {type: "http", url: $url, headers: {Authorization: ("Bearer " + $key)}, disabled: false}}}' \
        > "${WORKDIR}/${user}/mcp.json"
    echo "bob-chat: ${user} key bobshell-demo-${STAMP} -> ${WORKDIR}/${user}/mcp.json"
done

# Stop any chats left over from an earlier run: closing a tmux pane does
# not reliably stop its docker run under every backend.
for user in "${USERS[@]}"; do
    docker rm -f "bob-${user}" >/dev/null 2>&1 || true
done
tmux kill-session -t "${SESSION}" 2>/dev/null || true
bob_cmd() { # bob_cmd USER -> the container command line for one chat
    echo "docker run --rm -it --name bob-$1 --add-host=host.docker.internal:host-gateway -e BOB_API_KEY='${BOBSHELL_API_KEY}' -v '${WORKDIR}/$1:/etc/bob:ro' ${BOBSHELL_IMAGE}"
}

# Each pane runs its container as the pane process: no shell, no
# send-keys race, and closing the pane stops the container.
tmux new-session -d -s "${SESSION}" -n "bob-chat" "$(bob_cmd "${USERS[0]}")"
tmux select-pane -t "${SESSION}:0.0" -T "${USERS[0]}"
for i in 1 2 3; do
    tmux split-window -t "${SESSION}" -d "$(bob_cmd "${USERS[$i]}")"
    tmux select-layout -t "${SESSION}" tiled
    echo "bob-chat: pane ${i} -> bob-${USERS[$i]}"
done
for i in 0 1 2 3; do
    tmux select-pane -t "${SESSION}:0.${i}" -T "${USERS[$i]}"
done
# Show the pane titles as a labeled top border on every pane.
tmux set-option -t "${SESSION}" pane-border-status top
tmux set-option -t "${SESSION}" pane-border-format " #{pane_index} · #{pane_title} "
echo "bob-chat: pane 0 -> bob-${USERS[0]}"

if [ -t 0 ] && [ -t 1 ]; then
    echo "bob-chat: session '${SESSION}' ready with 4 chats. Attaching (detach: Ctrl-b d)."
    tmux attach-session -t "${SESSION}"
else
    echo "bob-chat: session '${SESSION}' ready with 4 chats (non-interactive: attach with 'tmux attach -t ${SESSION}')."
fi
