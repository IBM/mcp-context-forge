#!/usr/bin/env bash
# Print the host port that Compose publishes for the web_ui service of the
# testing stack. The port comes from the resolved Compose configuration, so
# .env files and exported variables take the same precedence as they do for
# `make testing-up`.
#
# Usage:
#   testing-web-ui-port.sh                    Resolve through the Compose CLI.
#   testing-web-ui-port.sh --from-config-json Parse `compose config --format json` from stdin.
#   testing-web-ui-port.sh --from-config-yaml Parse canonical `compose config` YAML from stdin.
#
# Environment:
#   COMPOSE_CMD       Compose invocation to query (default: "docker compose").
#   COMPOSE_PROFILES  Profile flags that enable web_ui
#                     (default: "--profile testing --profile inspector --profile sso").
#   COMPOSE_ENV_FILE  Optional env file passed as --env-file. The Makefile
#                     leaves this unset so Compose applies its default .env.
#
# The script exits non-zero when the port cannot be resolved. Callers must not
# substitute a fallback URL.

set -euo pipefail

SERVICE="web_ui"

port_from_config_json() {
    jq -r --arg svc "${SERVICE}" '.services[$svc].ports[0].published // empty'
}

# Extract the first published host port of the service from canonical
# `compose config` YAML. Emitters differ: Docker Compose v2 prints long syntax
# with a quoted `published:` value, podman-compose prints short syntax
# ("published:target"), and docker-compose v1 prints long syntax unquoted.
port_from_config_yaml() {
    awk -v svc="${SERVICE}" '
        $0 ~ "^  " svc ":" { in_service = 1; ports_indent = -1; next }
        in_service && /^  [^ ]/ { exit }
        in_service && ports_indent < 0 && /^ +ports: *$/ {
            match($0, /[^ ]/)
            ports_indent = RSTART - 1
            next
        }
        in_service && ports_indent >= 0 {
            if ($0 ~ /^ *[A-Za-z_]+:/) {
                match($0, /[^ ]/)
                if (RSTART - 1 <= ports_indent) { ports_indent = -1; next }
            }
            if ($0 ~ /^ *-? *published:/) {
                value = $0
                sub(/.*published: */, "", value)
                gsub(/["'"'"' \t]/, "", value)
                if (value != "") { print value; exit }
                next
            }
            if ($0 ~ /^ *- *["'"'"']?[0-9][0-9.:]*/) {
                value = $0
                sub(/^ *- */, "", value)
                gsub(/["'"'"']/, "", value)
                count = split(value, fields, ":")
                if (count >= 2) { print fields[count - 1]; exit }
            }
        }
    '
}

main() {
    local port
    case "${1:-}" in
        --from-config-json) port=$(port_from_config_json) ;;
        --from-config-yaml) port=$(port_from_config_yaml) ;;
        "")
            local compose_cmd="${COMPOSE_CMD:-docker compose}"
            local profiles="${COMPOSE_PROFILES:---profile testing --profile inspector --profile sso}"
            local env_file=""
            if [ -n "${COMPOSE_ENV_FILE:-}" ]; then
                env_file="--env-file ${COMPOSE_ENV_FILE}"
            fi

            # `config --format json` exists only on Docker Compose v2 and later.
            # podman-compose and docker-compose v1 render canonical YAML instead.
            if ${compose_cmd} config --help 2>&1 | grep -q -- '--format'; then
                if ! command -v jq >/dev/null 2>&1; then
                    echo "❌ jq is required to read the resolved Compose configuration." >&2
                    exit 1
                fi
                # shellcheck disable=SC2086  # compose_cmd, env_file and profiles are word lists by design.
                port=$(${compose_cmd} ${env_file} ${profiles} config --format json | port_from_config_json)
            else
                # shellcheck disable=SC2086  # compose_cmd, env_file and profiles are word lists by design.
                port=$(${compose_cmd} ${env_file} ${profiles} config | port_from_config_yaml)
            fi
            ;;
        *) echo "usage: $0 [--from-config-json|--from-config-yaml]" >&2; exit 2 ;;
    esac

    if [ -z "${port}" ]; then
        echo "❌ Could not resolve the ${SERVICE} host port from the Compose configuration." >&2
        exit 1
    fi
    printf '%s\n' "${port}"
}

main "$@"
