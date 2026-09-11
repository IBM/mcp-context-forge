#!/usr/bin/env bats
# Tests for the ibmcloud-deploy preflight checks in the Makefile.
#
# The suite drives `make ibmcloud-deploy` with a stub `ibmcloud` binary injected
# at the front of PATH.  All IBMCLOUD_* variables are passed directly as Make
# overrides so no real .env.ce is needed.  A minimal .env is created in a
# temporary directory; MAKEFLAGS is cleared to avoid interference from a parent
# make invocation.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    TMP_DIR="$(mktemp -d)"

    # ── Stub bin directory ───────────────────────────────────────────────────
    mkdir -p "${TMP_DIR}/bin"

    # Default stub: succeeds for every sub-command (simulates a fully working CLI
    # where the registry secret already exists).  Individual tests override this.
    cat > "${TMP_DIR}/bin/ibmcloud" <<'STUB'
#!/usr/bin/env bash
# Stub ibmcloud: default — succeed silently.
exit 0
STUB
    chmod +x "${TMP_DIR}/bin/ibmcloud"

    # ── Minimal .env ─────────────────────────────────────────────────────────
    printf 'HOST=0.0.0.0\nPORT=4444\n' > "${TMP_DIR}/.env"

    # ── Common Make variable overrides ────────────────────────────────────────
    # These bypass .env.ce loading in the Makefile and provide predictable values.
    MAKE_VARS=(
        "IBMCLOUD_CODE_ENGINE_APP=test-app"
        "IBMCLOUD_REGISTRY_SECRET=test-regcred"
        "IBMCLOUD_IMAGE_NAME=us.icr.io/ns/img:latest"
        "IBMCLOUD_IMG_PROD=local/img"
        "IBMCLOUD_REGION=us-south"
        "IBMCLOUD_PROJECT=test-proj"
        "IBMCLOUD_RESOURCE_GROUP=default"
        "IBMCLOUD_CPU=1"
        "IBMCLOUD_MEMORY=4G"
        "IBMCLOUD_API_KEY=dummy-key"
    )
}

teardown() {
    rm -rf "${TMP_DIR}"
}

# Run make ibmcloud-deploy with the stub on PATH and the temp .env in place.
# Extra Make variable overrides can be appended after the fixed set.
run_deploy() {
    run env \
        -u MAKEFLAGS \
        PATH="${TMP_DIR}/bin:${PATH}" \
        make --no-print-directory -C "${REPO_ROOT}" ibmcloud-deploy \
            "${MAKE_VARS[@]}" \
            "$@"
}

# ── 1. Missing ibmcloud CLI (exit 127) ───────────────────────────────────────

@test "missing ibmcloud CLI is reported correctly, not as a missing registry secret" {
    # Remove the stub so the CLI is not on PATH at all.
    rm "${TMP_DIR}/bin/ibmcloud"

    # Make needs a real .env in the repo root; use the temp one via override.
    # We cannot override the `test -f .env` path from Make, so create a minimal
    # .env in the repo root if one doesn't exist yet (restore it on teardown).
    local env_existed=false
    if [ -f "${REPO_ROOT}/.env" ]; then env_existed=true; fi
    if ! $env_existed; then printf 'HOST=0.0.0.0\n' > "${REPO_ROOT}/.env"; fi

    run_deploy
    status_copy=$status

    if ! $env_existed; then rm -f "${REPO_ROOT}/.env"; fi

    [ "$status_copy" -eq 1 ] || [ "$status_copy" -eq 2 ]
    [[ "$output" == *"ibmcloud CLI not found"* ]]
    [[ "$output" != *"does not exist"* ]]
    [[ "$output" != *"Create it first"* ]]
}

# ── 2. Registry secret missing (CLI present, secret not found) ───────────────

@test "missing registry secret exits with creation guidance" {
    # Stub: `ce secret get` for the registry secret → exit 1 with "not found" message.
    # All other sub-commands succeed.
    cat > "${TMP_DIR}/bin/ibmcloud" <<'STUB'
#!/usr/bin/env bash
if [[ "$*" == *"ce secret get"*"test-regcred"* ]]; then
    echo "[FAILED] Getting secret 'test-regcred': secret not found" >&2
    exit 1
fi
exit 0
STUB
    chmod +x "${TMP_DIR}/bin/ibmcloud"

    local env_existed=false
    if [ -f "${REPO_ROOT}/.env" ]; then env_existed=true; fi
    if ! $env_existed; then printf 'HOST=0.0.0.0\n' > "${REPO_ROOT}/.env"; fi

    run_deploy
    status_copy=$status

    if ! $env_existed; then rm -f "${REPO_ROOT}/.env"; fi

    [ "$status_copy" -ne 0 ]
    [[ "$output" == *"does not exist"* ]]
    [[ "$output" == *"Create it first"* ]]
    [[ "$output" != *"ibmcloud CLI not found"* ]]
    [[ "$output" != *"Check your IBM Cloud login"* ]]
}

# ── 3. Generic CLI failure (auth/plugin/network error) ───────────────────────

@test "generic CLI failure surfaces diagnostic, not creation guidance" {
    # Stub: `ce secret get` exits non-zero with an auth-style error (no "not found").
    cat > "${TMP_DIR}/bin/ibmcloud" <<'STUB'
#!/usr/bin/env bash
if [[ "$*" == *"ce secret get"*"test-regcred"* ]]; then
    echo "FAILED Token is expired or invalid. Please re-login." >&2
    exit 1
fi
exit 0
STUB
    chmod +x "${TMP_DIR}/bin/ibmcloud"

    local env_existed=false
    if [ -f "${REPO_ROOT}/.env" ]; then env_existed=true; fi
    if ! $env_existed; then printf 'HOST=0.0.0.0\n' > "${REPO_ROOT}/.env"; fi

    run_deploy
    status_copy=$status

    if ! $env_existed; then rm -f "${REPO_ROOT}/.env"; fi

    [ "$status_copy" -ne 0 ]
    [[ "$output" == *"Could not verify registry pull secret"* ]]
    [[ "$output" == *"Diagnostic:"* ]]
    [[ "$output" == *"Check your IBM Cloud login"* ]]
    [[ "$output" != *"Create it first"* ]]
    [[ "$output" != *"does not exist"* ]]
}

# ── 4. Happy path (secret exists, new app created) ───────────────────────────

@test "happy path creates new app when secret exists" {
    # Default stub succeeds for every command; record calls for assertion.
    cat > "${TMP_DIR}/bin/ibmcloud" <<STUB
#!/usr/bin/env bash
echo "STUB_CALL: \$*" >> "${TMP_DIR}/calls.log"
exit 0
STUB
    chmod +x "${TMP_DIR}/bin/ibmcloud"

    local env_existed=false
    if [ -f "${REPO_ROOT}/.env" ]; then env_existed=true; fi
    if ! $env_existed; then printf 'HOST=0.0.0.0\n' > "${REPO_ROOT}/.env"; fi

    run_deploy
    status_copy=$status

    if ! $env_existed; then rm -f "${REPO_ROOT}/.env"; fi

    [ "$status_copy" -eq 0 ]
    [[ "$output" != *"❌"* ]]
    # The stub log should contain both a secret-get probe and an application call.
    grep -q "ce secret get" "${TMP_DIR}/calls.log"
    grep -q "ce application" "${TMP_DIR}/calls.log"
}
