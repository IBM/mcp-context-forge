#!/usr/bin/env bash
set -euo pipefail

# Validate fresh installs + release-to-current upgrades for SQLite and PostgreSQL.

BASE_IMAGE="${BASE_IMAGE:-ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2}"
TARGET_IMAGE="${TARGET_IMAGE:-mcpgateway/mcpgateway:latest}"
ARTIFACT_DIR="${ARTIFACT_DIR:-artifacts/upgrade-validation}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-240}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_ID="${RUN_ID:-$(date +%s)-$RANDOM}"
NAME_PREFIX="upgrade-val-${RUN_ID}"

mkdir -p "${ARTIFACT_DIR}"

declare -a TRACKED_CONTAINERS=()
declare -a TRACKED_NETWORKS=()
declare -a TRACKED_PATHS=()

log() {
    echo "[upgrade-validation] $*"
}

fail() {
    echo "[upgrade-validation] ERROR: $*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

register_container() {
    TRACKED_CONTAINERS+=("$1")
}

register_network() {
    TRACKED_NETWORKS+=("$1")
}

register_path() {
    TRACKED_PATHS+=("$1")
}

collect_container_log() {
    local container="$1"
    local out_file="${ARTIFACT_DIR}/${container}.log"

    if docker container inspect "${container}" >/dev/null 2>&1; then
        docker logs "${container}" >"${out_file}" 2>&1 || true
    fi
}

cleanup() {
    local item

    for item in ${TRACKED_CONTAINERS[@]+"${TRACKED_CONTAINERS[@]}"}; do
        collect_container_log "${item}"
    done

    for item in ${TRACKED_CONTAINERS[@]+"${TRACKED_CONTAINERS[@]}"}; do
        docker rm -f "${item}" >/dev/null 2>&1 || true
    done

    for item in ${TRACKED_NETWORKS[@]+"${TRACKED_NETWORKS[@]}"}; do
        docker network rm "${item}" >/dev/null 2>&1 || true
    done

    for item in ${TRACKED_PATHS[@]+"${TRACKED_PATHS[@]}"}; do
        rm -rf "${item}" || true
    done
}

trap cleanup EXIT

wait_for_health() {
    local url="$1"
    local container="$2"
    local timeout="${3:-${HEALTH_TIMEOUT_SECONDS}}"
    local i
    local running_state
    local status_summary

    for i in $(seq 1 "${timeout}"); do
        if docker container inspect "${container}" >/dev/null 2>&1; then
            running_state="$(docker inspect -f '{{.State.Running}}' "${container}")"
            if [[ "${running_state}" != "true" ]]; then
                status_summary="$(docker inspect -f '{{.State.Status}} (exit={{.State.ExitCode}})' "${container}")"
                collect_container_log "${container}"
                fail "Container ${container} exited before becoming healthy: ${status_summary}"
            fi
        fi

        if curl -fsS "${url}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    collect_container_log "${container}"
    fail "Health check timed out for ${container} (${url})"
}

wait_for_postgres_ready() {
    local pg_container="$1"
    local timeout="${2:-120}"
    local i

    for i in $(seq 1 "${timeout}"); do
        if docker exec "${pg_container}" pg_isready -U postgres -d mcp >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    collect_container_log "${pg_container}"
    fail "PostgreSQL readiness timed out for ${pg_container}"
}

next_port() {
    local base="$1"
    echo $((base + (RANDOM % 1000)))
}

get_expected_head() {
    # Parses the local checkout to determine the single alembic head revision.
    # In CI the checkout matches the built target image; when run locally ensure
    # the working tree matches the image you are validating.
    python3 - "${PROJECT_ROOT}" <<'PY'
import ast
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
versions_dir = root / "mcpgateway" / "alembic" / "versions"

if not versions_dir.is_dir():
    raise SystemExit("Alembic versions directory not found")

revisions = set()
referenced = set()

for path in versions_dir.glob("*.py"):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        continue

    revision = None
    down_revision = None

    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
            if name == "revision":
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    revision = value.value
                else:
                    try:
                        parsed = ast.literal_eval(value)
                    except Exception:
                        parsed = None
                    if isinstance(parsed, str):
                        revision = parsed
            elif name == "down_revision":
                try:
                    down_revision = ast.literal_eval(value)
                except Exception:
                    down_revision = None
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "revision":
                    try:
                        parsed = ast.literal_eval(node.value)
                    except Exception:
                        parsed = None
                    if isinstance(parsed, str):
                        revision = parsed
                elif target.id == "down_revision":
                    try:
                        down_revision = ast.literal_eval(node.value)
                    except Exception:
                        down_revision = None

    if revision is None:
        continue

    revisions.add(revision)

    if down_revision is None:
        continue
    if isinstance(down_revision, str):
        referenced.add(down_revision)
    elif isinstance(down_revision, (tuple, list)):
        for item in down_revision:
            if isinstance(item, str):
                referenced.add(item)

heads = sorted(revisions - referenced)
if len(heads) != 1:
    raise SystemExit(f"Expected exactly one alembic head, found {len(heads)}: {heads}")

print(heads[0])
PY
}

sqlite_versions() {
    local db_file="$1"

    python3 - "${db_file}" <<'PY'
import sqlite3
import sys

db_file = sys.argv[1]
conn = sqlite3.connect(db_file)
rows = conn.execute("SELECT version_num FROM alembic_version ORDER BY version_num").fetchall()
conn.close()
print(",".join(row[0] for row in rows))
PY
}

sqlite_marker_count() {
    local db_file="$1"

    python3 - "${db_file}" <<'PY'
import sqlite3
import sys

db_file = sys.argv[1]
conn = sqlite3.connect(db_file)
rows = conn.execute("SELECT count(*) FROM upgrade_test_marker").fetchone()
conn.close()
print(rows[0])
PY
}

seed_sqlite_marker() {
    local db_file="$1"

    python3 - "${db_file}" <<'PY'
import sqlite3
import sys

db_file = sys.argv[1]
conn = sqlite3.connect(db_file)
conn.execute("CREATE TABLE IF NOT EXISTS upgrade_test_marker (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
conn.execute("INSERT INTO upgrade_test_marker(note) VALUES ('from-base-image')")
conn.commit()
conn.close()
PY
}

psql_query() {
    local pg_container="$1"
    local sql="$2"
    docker exec "${pg_container}" psql -U postgres -d mcp -Atq -c "${sql}"
}

assert_equals() {
    local actual="$1"
    local expected="$2"
    local description="$3"

    if [[ "${actual}" != "${expected}" ]]; then
        fail "${description}: expected '${expected}', got '${actual}'"
    fi
}

assert_int_ge() {
    local actual="$1"
    local min_value="$2"
    local description="$3"

    if (( actual < min_value )); then
        fail "${description}: expected >= ${min_value}, got ${actual}"
    fi
}

run_sqlite_fresh() {
    local expected_head="$1"
    local port="$2"
    local container="${NAME_PREFIX}-sqlite-fresh"
    local db_dir
    local db_file
    local versions

    log "Running SQLite fresh install check"
    db_dir="$(mktemp -d)"
    register_path "${db_dir}"
    db_file="${db_dir}/mcp-upgrade-test.db"

    docker run -d \
        --name "${container}" \
        -p "${port}:4444" \
        -e "DATABASE_URL=sqlite:////app/data/mcp-upgrade-test.db" \
        -e "AUTH_REQUIRED=false" \
        -e "CACHE_TYPE=memory" \
        -e "HOST=0.0.0.0" \
        -e "PORT=4444" \
        -e "MCPGATEWAY_UI_ENABLED=false" \
        -e "MCPGATEWAY_ADMIN_API_ENABLED=true" \
        -e "LOG_LEVEL=INFO" \
        -v "${db_dir}:/app/data" \
        "${TARGET_IMAGE}" >/dev/null
    register_container "${container}"

    wait_for_health "http://127.0.0.1:${port}/health" "${container}"
    versions="$(sqlite_versions "${db_file}")"
    assert_equals "${versions}" "${expected_head}" "SQLite fresh alembic_version"

    docker stop "${container}" >/dev/null
}

run_sqlite_upgrade() {
    local expected_head="$1"
    local port="$2"
    local old_container="${NAME_PREFIX}-sqlite-old"
    local new_container="${NAME_PREFIX}-sqlite-upgrade"
    local db_dir
    local db_file
    local versions
    local markers

    log "Running SQLite upgrade check (${BASE_IMAGE} -> ${TARGET_IMAGE})"
    db_dir="$(mktemp -d)"
    register_path "${db_dir}"
    db_file="${db_dir}/mcp-upgrade-test.db"

    docker run -d \
        --name "${old_container}" \
        -p "${port}:4444" \
        -e "DATABASE_URL=sqlite:////app/data/mcp-upgrade-test.db" \
        -e "AUTH_REQUIRED=false" \
        -e "CACHE_TYPE=memory" \
        -e "HOST=0.0.0.0" \
        -e "PORT=4444" \
        -e "MCPGATEWAY_UI_ENABLED=false" \
        -e "MCPGATEWAY_ADMIN_API_ENABLED=true" \
        -e "LOG_LEVEL=INFO" \
        -v "${db_dir}:/app/data" \
        "${BASE_IMAGE}" >/dev/null
    register_container "${old_container}"

    wait_for_health "http://127.0.0.1:${port}/health" "${old_container}"
    seed_sqlite_marker "${db_file}"

    docker stop "${old_container}" >/dev/null

    docker run -d \
        --name "${new_container}" \
        -p "${port}:4444" \
        -e "DATABASE_URL=sqlite:////app/data/mcp-upgrade-test.db" \
        -e "AUTH_REQUIRED=false" \
        -e "CACHE_TYPE=memory" \
        -e "HOST=0.0.0.0" \
        -e "PORT=4444" \
        -e "MCPGATEWAY_UI_ENABLED=false" \
        -e "MCPGATEWAY_ADMIN_API_ENABLED=true" \
        -e "LOG_LEVEL=INFO" \
        -v "${db_dir}:/app/data" \
        "${TARGET_IMAGE}" >/dev/null
    register_container "${new_container}"

    wait_for_health "http://127.0.0.1:${port}/health" "${new_container}"

    versions="$(sqlite_versions "${db_file}")"
    markers="$(sqlite_marker_count "${db_file}")"

    assert_equals "${versions}" "${expected_head}" "SQLite upgrade alembic_version"
    assert_int_ge "${markers}" 1 "SQLite upgrade marker row count"

    docker stop "${new_container}" >/dev/null
}

run_postgres_fresh() {
    local expected_head="$1"
    local port="$2"
    local network="${NAME_PREFIX}-pg-fresh-net"
    local pg_container="${NAME_PREFIX}-pg-fresh-db"
    local gateway_container="${NAME_PREFIX}-pg-fresh-gateway"
    local db_url
    local versions

    log "Running PostgreSQL fresh install check"

    docker network create "${network}" >/dev/null
    register_network "${network}"

    docker run -d \
        --name "${pg_container}" \
        --network "${network}" \
        -e "POSTGRES_USER=postgres" \
        -e "POSTGRES_PASSWORD=upgrade-test-password" \
        -e "POSTGRES_DB=mcp" \
        postgres:18 >/dev/null
    register_container "${pg_container}"

    wait_for_postgres_ready "${pg_container}"

    db_url="postgresql+psycopg://postgres:upgrade-test-password@${pg_container}:5432/mcp"
    docker run -d \
        --name "${gateway_container}" \
        --network "${network}" \
        -p "${port}:4444" \
        -e "DATABASE_URL=${db_url}" \
        -e "AUTH_REQUIRED=false" \
        -e "CACHE_TYPE=memory" \
        -e "HOST=0.0.0.0" \
        -e "PORT=4444" \
        -e "MCPGATEWAY_UI_ENABLED=false" \
        -e "MCPGATEWAY_ADMIN_API_ENABLED=true" \
        -e "LOG_LEVEL=INFO" \
        "${TARGET_IMAGE}" >/dev/null
    register_container "${gateway_container}"

    wait_for_health "http://127.0.0.1:${port}/health" "${gateway_container}"
    versions="$(psql_query "${pg_container}" "SELECT version_num FROM alembic_version ORDER BY version_num")"
    assert_equals "${versions}" "${expected_head}" "PostgreSQL fresh alembic_version"

    docker stop "${gateway_container}" >/dev/null
    docker stop "${pg_container}" >/dev/null
}

run_postgres_upgrade() {
    local expected_head="$1"
    local port="$2"
    local network="${NAME_PREFIX}-pg-upgrade-net"
    local pg_container="${NAME_PREFIX}-pg-upgrade-db"
    local old_container="${NAME_PREFIX}-pg-upgrade-old"
    local new_container="${NAME_PREFIX}-pg-upgrade-new"
    local db_url
    local versions
    local markers

    log "Running PostgreSQL upgrade check (${BASE_IMAGE} -> ${TARGET_IMAGE})"

    docker network create "${network}" >/dev/null
    register_network "${network}"

    docker run -d \
        --name "${pg_container}" \
        --network "${network}" \
        -e "POSTGRES_USER=postgres" \
        -e "POSTGRES_PASSWORD=upgrade-test-password" \
        -e "POSTGRES_DB=mcp" \
        postgres:18 >/dev/null
    register_container "${pg_container}"

    wait_for_postgres_ready "${pg_container}"

    db_url="postgresql+psycopg://postgres:upgrade-test-password@${pg_container}:5432/mcp"
    docker run -d \
        --name "${old_container}" \
        --network "${network}" \
        -p "${port}:4444" \
        -e "DATABASE_URL=${db_url}" \
        -e "AUTH_REQUIRED=false" \
        -e "CACHE_TYPE=memory" \
        -e "HOST=0.0.0.0" \
        -e "PORT=4444" \
        -e "MCPGATEWAY_UI_ENABLED=false" \
        -e "MCPGATEWAY_ADMIN_API_ENABLED=true" \
        -e "LOG_LEVEL=INFO" \
        "${BASE_IMAGE}" >/dev/null
    register_container "${old_container}"

    wait_for_health "http://127.0.0.1:${port}/health" "${old_container}"

    psql_query "${pg_container}" "CREATE TABLE IF NOT EXISTS upgrade_test_marker (id SERIAL PRIMARY KEY, note TEXT NOT NULL);" >/dev/null
    psql_query "${pg_container}" "INSERT INTO upgrade_test_marker(note) VALUES ('from-base-image');" >/dev/null

    docker stop "${old_container}" >/dev/null

    docker run -d \
        --name "${new_container}" \
        --network "${network}" \
        -p "${port}:4444" \
        -e "DATABASE_URL=${db_url}" \
        -e "AUTH_REQUIRED=false" \
        -e "CACHE_TYPE=memory" \
        -e "HOST=0.0.0.0" \
        -e "PORT=4444" \
        -e "MCPGATEWAY_UI_ENABLED=false" \
        -e "MCPGATEWAY_ADMIN_API_ENABLED=true" \
        -e "LOG_LEVEL=INFO" \
        "${TARGET_IMAGE}" >/dev/null
    register_container "${new_container}"

    wait_for_health "http://127.0.0.1:${port}/health" "${new_container}"

    versions="$(psql_query "${pg_container}" "SELECT version_num FROM alembic_version ORDER BY version_num")"
    markers="$(psql_query "${pg_container}" "SELECT count(*) FROM upgrade_test_marker")"

    assert_equals "${versions}" "${expected_head}" "PostgreSQL upgrade alembic_version"
    assert_int_ge "${markers}" 1 "PostgreSQL upgrade marker row count"

    docker stop "${new_container}" >/dev/null
    docker stop "${pg_container}" >/dev/null
}

main() {
    local expected_head

    require_cmd docker
    require_cmd python3
    require_cmd curl

    log "Base image: ${BASE_IMAGE}"
    log "Target image: ${TARGET_IMAGE}"

    docker pull "${BASE_IMAGE}" >/dev/null
    docker image inspect "${TARGET_IMAGE}" >/dev/null 2>&1 || fail "Target image not found locally: ${TARGET_IMAGE}"

    expected_head="$(get_expected_head)"
    log "Expected alembic head: ${expected_head}"

    # Each test gets its own non-overlapping port range (base + 0..999)
    run_sqlite_fresh    "${expected_head}" "$(next_port 22000)"
    run_sqlite_upgrade  "${expected_head}" "$(next_port 23000)"
    run_postgres_fresh  "${expected_head}" "$(next_port 24000)"
    run_postgres_upgrade "${expected_head}" "$(next_port 25000)"

    log "All upgrade validation checks passed"
}

main "$@"
