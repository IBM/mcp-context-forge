#!/usr/bin/env bats
# Tests for scripts/testing-web-ui-port.sh, which resolves the host port that
# `make testing-up` advertises for the ContextForge web UI.
#
# The precedence cases compare the script against Compose's own resolved
# configuration for the four WEB_UI_PORT placements (unset, exported,
# env-file only, both). The fixture cases pin the canonical-YAML parser used
# on compose backends without `config --format json` (podman-compose,
# docker-compose v1), and the stub cases pin the backend dispatch.
#
# This suite is self-contained: the helpers in test_helper/helpers.bash are
# git-fixture utilities for the secrets merge driver and do not apply here.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/scripts/testing-web-ui-port.sh"
    TMP_DIR="$(mktemp -d)"
    ENV_FILE="${TMP_DIR}/compose.env"
    # Required by compose interpolation; unrelated to the port under test.
    printf 'DEFAULT_USER_PASSWORD=test\nPLATFORM_ADMIN_PASSWORD=test\nJWT_SECRET_KEY=test-only-jwt-secret\nAUTH_ENCRYPTION_SECRET=test-only-encryption-secret\n' > "${ENV_FILE}"  # pragma: allowlist secret
}

teardown() {
    rm -rf "${TMP_DIR}"
}

have_docker_compose() {
    command -v docker >/dev/null 2>&1 && command -v jq >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

# Compose's own resolved port: the independent reference for each case.
# Extra arguments are env controls, e.g. `-u WEB_UI_PORT` or `WEB_UI_PORT=3200`.
compose_resolved_port() {
    env "$@" docker compose --env-file "${ENV_FILE}" \
        --profile testing --profile inspector --profile sso \
        config --format json | jq -r '.services.web_ui.ports[0].published'
}

# Run the resolver against Docker Compose with the same profiles the Makefile
# passes. Extra arguments are env controls as above.
run_resolver() {
    run env "$@" \
        COMPOSE_CMD="docker compose" \
        COMPOSE_PROFILES="--profile testing --profile inspector --profile sso" \
        COMPOSE_ENV_FILE="${ENV_FILE}" \
        "${SCRIPT}"
}

# Run the resolver against a stub Compose. $1 selects the stub flavour
# (`json` answers `config --format json`; `yaml` only knows canonical YAML).
run_resolver_with_stub() {
    local kind="$1"
    local stub="${TMP_DIR}/fake-compose-${kind}"
    cat > "${stub}" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" > "${FAKE_COMPOSE_ARGS_FILE}"
is_config=0
want_help=0
want_json=0
prev=""
for arg in "$@"; do
    case "${arg}" in
        config) is_config=1 ;;
        --help) want_help=1 ;;
        --format) prev="format" ;;
        json) if [ "${prev}" = "format" ]; then want_json=1; fi ;;
    esac
done
[ "${is_config}" -eq 1 ] || { echo "stub: unsupported command" >&2; exit 1; }
if [ "${want_help}" -eq 1 ]; then
    if [ "${FAKE_COMPOSE_KIND}" = "json" ]; then
        echo "  --format string   Format the output. Values: [yaml | json]"
    else
        echo "  --services        Print the service names"
    fi
    exit 0
fi
if [ "${FAKE_COMPOSE_KIND}" = "json" ]; then
    [ "${want_json}" -eq 1 ] || { echo "stub: expected --format json" >&2; exit 1; }
else
    [ "${want_json}" -eq 0 ] || { echo "stub: unexpected --format json" >&2; exit 1; }
fi
cat "${FAKE_COMPOSE_CONFIG_FILE}"
STUB
    chmod +x "${stub}"
    shift
    run env "$@" \
        COMPOSE_CMD="${stub}" \
        COMPOSE_PROFILES="--profile testing --profile inspector --profile sso" \
        FAKE_COMPOSE_KIND="${kind}" \
        FAKE_COMPOSE_ARGS_FILE="${TMP_DIR}/args-${kind}" \
        FAKE_COMPOSE_CONFIG_FILE="${TMP_DIR}/config-${kind}.out" \
        "${SCRIPT}"
}

fixture_v2_long() {
    cat <<'YAML'
services:
  gateway:
    image: example/gateway
  web_ui:
    image: example/web-ui
    ports:
      - mode: ingress
        target: 3100
        published: "3100"
        protocol: tcp
  web_ui_redis:
    image: redis
YAML
}

fixture_podman_short() {
    cat <<'YAML'
services:
  web_ui:
    image: example/web-ui
    networks:
    - mcpnet
    ports:
    - 3100:3100
    profiles:
    - testing
    - ui
  web_ui_redis:
    image: redis
YAML
}

fixture_v1_long() {
    cat <<'YAML'
services:
  web_ui:
    image: example/web-ui
    ports:
    - mode: ingress
      protocol: tcp
      published: 3200
      target: 3200
    restart: unless-stopped
  web_ui_redis:
    image: redis
YAML
}

@test "defaults to 3001 when WEB_UI_PORT is unset everywhere" {
    have_docker_compose || skip "docker compose v2 and jq required"
    run_resolver -u WEB_UI_PORT
    [ "$status" -eq 0 ]
    [ "$output" = "3001" ]
    [ "$output" = "$(compose_resolved_port -u WEB_UI_PORT)" ]
}

@test "honours an exported WEB_UI_PORT" {
    have_docker_compose || skip "docker compose v2 and jq required"
    run_resolver WEB_UI_PORT=3200
    [ "$status" -eq 0 ]
    [ "$output" = "3200" ]
    [ "$output" = "$(compose_resolved_port WEB_UI_PORT=3200)" ]
}

@test "honours WEB_UI_PORT set only in the compose env file" {
    have_docker_compose || skip "docker compose v2 and jq required"
    printf 'WEB_UI_PORT=3100\n' >> "${ENV_FILE}"
    run_resolver -u WEB_UI_PORT
    [ "$status" -eq 0 ]
    [ "$output" = "3100" ]
    [ "$output" = "$(compose_resolved_port -u WEB_UI_PORT)" ]
}

@test "exported WEB_UI_PORT wins over the compose env file" {
    have_docker_compose || skip "docker compose v2 and jq required"
    printf 'WEB_UI_PORT=3100\n' >> "${ENV_FILE}"
    run_resolver WEB_UI_PORT=3200
    [ "$status" -eq 0 ]
    [ "$output" = "3200" ]
    [ "$output" = "$(compose_resolved_port WEB_UI_PORT=3200)" ]
}

@test "JSON mode reads the published port of the first web_ui port mapping" {
    run "${SCRIPT}" --from-config-json \
        <<< '{"services":{"web_ui":{"ports":[{"published":"3100","target":3100}]}}}'
    [ "$status" -eq 0 ]
    [ "$output" = "3100" ]
}

@test "YAML mode reads Docker Compose v2 long syntax" {
    run "${SCRIPT}" --from-config-yaml <<< "$(fixture_v2_long)"
    [ "$status" -eq 0 ]
    [ "$output" = "3100" ]
}

@test "YAML mode reads podman-compose short syntax" {
    run "${SCRIPT}" --from-config-yaml <<< "$(fixture_podman_short)"
    [ "$status" -eq 0 ]
    [ "$output" = "3100" ]
}

@test "YAML mode reads docker-compose v1 long syntax" {
    run "${SCRIPT}" --from-config-yaml <<< "$(fixture_v1_long)"
    [ "$status" -eq 0 ]
    [ "$output" = "3200" ]
}

@test "fails without a fallback when web_ui publishes no port" {
    run "${SCRIPT}" --from-config-yaml <<'YAML'
services:
  web_ui:
    image: example/web-ui
  web_ui_redis:
    image: redis
YAML
    [ "$status" -eq 1 ]
    [[ "$output" == *"Could not resolve"* ]]
    [[ "$output" != *"http://localhost"* ]]
}

@test "dispatches to the YAML parser on backends without config --format json" {
    fixture_podman_short > "${TMP_DIR}/config-yaml.out"
    run_resolver_with_stub yaml COMPOSE_ENV_FILE="${ENV_FILE}"
    [ "$status" -eq 0 ]
    [ "$output" = "3100" ]
    grep -q -- '--profile testing' "${TMP_DIR}/args-yaml"
    grep -q -- '--profile inspector' "${TMP_DIR}/args-yaml"
    grep -q -- '--profile sso' "${TMP_DIR}/args-yaml"
    grep -q -- "--env-file ${ENV_FILE}" "${TMP_DIR}/args-yaml"
}

@test "dispatches to the JSON parser when config supports --format json" {
    printf '%s' '{"services":{"web_ui":{"ports":[{"published":"3100","target":3100}]}}}' \
        > "${TMP_DIR}/config-json.out"
    run_resolver_with_stub json -u COMPOSE_ENV_FILE
    [ "$status" -eq 0 ]
    [ "$output" = "3100" ]
    ! grep -q -- '--env-file' "${TMP_DIR}/args-json"
}
