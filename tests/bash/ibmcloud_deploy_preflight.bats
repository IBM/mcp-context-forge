#!/usr/bin/env bats
# Tests for the ibmcloud-deploy Makefile preflight (CLI availability check and
# registry pull-secret verification).
#
# Each test drives `make ibmcloud-deploy` from a throw-away clone with a stubbed
# `ibmcloud` binary on PATH, so:
#   - the real repo's git config and working tree are never touched
#   - no real IBM Cloud account is contacted regardless of the developer's
#     local authentication state

load test_helper/helpers

# ── helpers ────────────────────────────────────────────────────────────────────

# Write a minimal .env and .env.ce so the Makefile's first guards pass.
_write_env_files() {
    printf 'JWT_SECRET_KEY=test\n' > .env
    printf 'IBMCLOUD_REGION=us-south\n'          > .env.ce
    printf 'IBMCLOUD_RESOURCE_GROUP=default\n'  >> .env.ce
    printf 'IBMCLOUD_PROJECT=test-proj\n'        >> .env.ce
    printf 'IBMCLOUD_CODE_ENGINE_APP=testapp\n'  >> .env.ce
    printf 'IBMCLOUD_IMAGE_NAME=us.icr.io/ns/img:1\n' >> .env.ce
    printf 'IBMCLOUD_IMG_PROD=ns/img\n'          >> .env.ce
    printf 'IBMCLOUD_CPU=1\n'                    >> .env.ce
    printf 'IBMCLOUD_MEMORY=4G\n'                >> .env.ce
    printf 'IBMCLOUD_REGISTRY_SECRET=my-regcred\n' >> .env.ce
    printf 'IBMCLOUD_ICR_API_KEY=fake-icr-key\n' >> .env.ce
}

# Run `make ibmcloud-deploy` from the clone with the stub bin dir first on PATH.
# Extra env vars can be passed as KEY=VALUE arguments before calling this.
_run_make() {
    run env \
        PATH="${TMP_BIN}:${PATH}" \
        make --no-print-directory \
            --include-dir="${CLONE_DIR}" \
            -C "${CLONE_DIR}" \
            ibmcloud-deploy
}

# ── setup / teardown ───────────────────────────────────────────────────────────

setup() {
    ORIG_DIR="${PWD}"
    CLONE_PARENT="$(mktemp -d)"
    git clone -q "${REPO_ROOT}" "${CLONE_PARENT}/repo"
    CLONE_DIR="${CLONE_PARENT}/repo"
    cd "${CLONE_DIR}" || return 1

    TMP_BIN="$(mktemp -d)"

    # Minimal .env files so the Makefile's early guards pass.
    _write_env_files

    # Default stub: ibmcloud is present and `ce secret get` succeeds.
    # Individual tests override this stub as needed.
    cat > "${TMP_BIN}/ibmcloud" <<'STUB'
#!/usr/bin/env bash
# Stub: succeeds for any invocation by default.
exit 0
STUB
    chmod +x "${TMP_BIN}/ibmcloud"
}

teardown() {
    cd "${ORIG_DIR}" || true
    rm -rf "${CLONE_PARENT}" "${TMP_BIN}"
}

# ── test cases ─────────────────────────────────────────────────────────────────

@test "preflight fails with actionable message when ibmcloud CLI is not on PATH" {
    # Remove the stub so ibmcloud is genuinely absent.
    rm "${TMP_BIN}/ibmcloud"

    run env PATH="${TMP_BIN}:${PATH}" \
        make --no-print-directory -C "${CLONE_DIR}" ibmcloud-deploy

    [ "$status" -ne 0 ]
    [[ "$output" == *"ibmcloud CLI not found"* ]]
    [[ "$output" == *"ibmcloud-cli-install"* ]]
}

@test "preflight fails with creation hint when registry secret is absent" {
    # Stub: `ce secret get` exits non-zero with the CLI's own absence message.
    cat > "${TMP_BIN}/ibmcloud" <<'STUB'
#!/usr/bin/env bash
if [[ "$*" == *"secret get"* ]]; then
    echo "Secret 'my-regcred' not found" >&2
    exit 1
fi
exit 0
STUB
    chmod +x "${TMP_BIN}/ibmcloud"

    _run_make

    [ "$status" -ne 0 ]
    [[ "$output" == *"does not exist"* ]]
    [[ "$output" == *"ibmcloud ce secret create"* ]]
    [[ "$output" == *"IBMCLOUD_ICR_API_KEY"* ]]
}

@test "preflight fails with diagnostic message on generic CLI failure" {
    # Stub: `ce secret get` exits non-zero with an unrelated error (e.g. wrong project).
    cat > "${TMP_BIN}/ibmcloud" <<'STUB'
#!/usr/bin/env bash
if [[ "$*" == *"secret get"* ]]; then
    echo "Project 'my-ce-proj' not found in region us-south" >&2
    exit 1
fi
exit 0
STUB
    chmod +x "${TMP_BIN}/ibmcloud"

    _run_make

    [ "$status" -ne 0 ]
    [[ "$output" == *"Could not verify registry pull secret"* ]]
    [[ "$output" == *"Check your IBM Cloud login"* ]]
    # Must NOT misclassify a project-not-found error as a missing registry secret.
    [[ "$output" != *"does not exist"* ]]
}

@test "generic CLI failure does not misclassify a missing CE project as missing secret" {
    cat > "${TMP_BIN}/ibmcloud" <<'STUB'
#!/usr/bin/env bash
if [[ "$*" == *"secret get"* ]]; then
    echo "[FAILED] Project 'contextforge-proj' not found" >&2
    exit 1
fi
exit 0
STUB
    chmod +x "${TMP_BIN}/ibmcloud"

    _run_make

    [ "$status" -ne 0 ]
    [[ "$output" == *"Could not verify registry pull secret"* ]]
    [[ "$output" != *"does not exist"* ]]
}

@test "preflight passes and deploy continues when registry secret exists" {
    # Default stub already exits 0 for all invocations; make should proceed past
    # the preflight into the env-secret and app-create/update steps.
    _run_make

    # The preflight should not have printed any error.
    [[ "$output" != *"does not exist"* ]]
    [[ "$output" != *"ibmcloud CLI not found"* ]]
    [[ "$output" != *"Could not verify"* ]]
}
