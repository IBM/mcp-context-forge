#!/usr/bin/env bats
# Tests for the ibmcloud-deploy Makefile preflight (CLI availability check and
# registry pull-secret verification).
#
# Each test drives `make ibmcloud-deploy` from a throw-away clone of the
# repository with a controlled PATH so that:
#   - the real repo's git config and working tree are never touched
#   - no real IBM Cloud account is contacted regardless of the developer's
#     local authentication state
#   - a real ibmcloud binary installed on the developer's PATH cannot be
#     discovered by any test case, including the missing-CLI case

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
    printf 'IBMCLOUD_REGISTRY_SECRET=my-regcred\n' >> .env.ce  # pragma: allowlist secret
    printf 'IBMCLOUD_ICR_API_KEY=fake-icr-key\n' >> .env.ce  # pragma: allowlist secret
}

# Run `make ibmcloud-deploy` from the clone with the isolated PATH that contains
# only the controlled ibmcloud stub plus the real system tools required by the
# Makefile recipe (make, bash, sh, grep, cut).  No other directory is on PATH,
# so a real ibmcloud binary installed anywhere on the developer's system cannot
# be found.
_run_make() {
    run env \
        PATH="${SAFE_PATH}" \
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

    # TMP_BIN holds the ibmcloud stub (and nothing else).
    TMP_BIN="$(mktemp -d)"

    # SAFE_TOOLS holds symlinks to the real system utilities that the Makefile
    # recipe actually needs.  Only these exact tools are reachable; ibmcloud is
    # never present here — it lives only in TMP_BIN so each test controls it.
    SAFE_TOOLS="$(mktemp -d)"
    for tool in make bash sh grep cut; do
        real_path="$(command -v "$tool" 2>/dev/null || true)"
        if [ -n "$real_path" ]; then
            ln -sf "$real_path" "${SAFE_TOOLS}/${tool}"
        fi
    done

    # SAFE_PATH: stub bin (ibmcloud stub) first, then only the allowlisted tools.
    # The developer's PATH is never included.
    SAFE_PATH="${TMP_BIN}:${SAFE_TOOLS}"

    # Minimal .env files so the Makefile's early guards pass.
    _write_env_files

    # Default stub: ibmcloud is present and every invocation succeeds.
    # Individual tests override this stub as needed.
    cat > "${TMP_BIN}/ibmcloud" <<'STUB'
#!/usr/bin/env bash
# Default stub: succeeds for any invocation.
exit 0
STUB
    chmod +x "${TMP_BIN}/ibmcloud"
}

teardown() {
    cd "${ORIG_DIR}" || true
    rm -rf "${CLONE_PARENT}" "${TMP_BIN}" "${SAFE_TOOLS}"
}

# ── test cases ─────────────────────────────────────────────────────────────────

@test "preflight fails with actionable message when ibmcloud CLI is not on PATH" {
    # Remove the stub from TMP_BIN.  SAFE_PATH does not include any other
    # directory that could contain a real ibmcloud binary.
    rm "${TMP_BIN}/ibmcloud"

    _run_make

    [ "$status" -ne 0 ]
    [[ "$output" == *"ibmcloud CLI not found"* ]]
    [[ "$output" == *"ibmcloud-cli-install"* ]]
    # Must not have proceeded to any cloud write operation.
    [[ "$output" != *"secret create"* ]]
    [[ "$output" != *"secret update"* ]]
    [[ "$output" != *"application create"* ]]
    [[ "$output" != *"application update"* ]]
}

@test "preflight fails with creation hint when registry secret is absent" {
    # Stub: `ce secret get` exits non-zero with the CE CLI's own absence message.
    cat > "${TMP_BIN}/ibmcloud" <<'STUB'
#!/usr/bin/env bash
if [[ "$*" == *"secret get"* ]]; then
    echo "Secret my-regcred not found" >&2
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
    # Must not have proceeded to any cloud write operation.
    [[ "$output" != *"secret update"* ]]
    [[ "$output" != *"application create"* ]]
    [[ "$output" != *"application update"* ]]
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
    # Must not have proceeded to any cloud write operation.
    [[ "$output" != *"secret update"* ]]
    [[ "$output" != *"application create"* ]]
    [[ "$output" != *"application update"* ]]
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
    # Must not have proceeded to any cloud write operation.
    [[ "$output" != *"secret update"* ]]
    [[ "$output" != *"application create"* ]]
    [[ "$output" != *"application update"* ]]
}

@test "preflight passes and deploy continues when registry secret exists" {
    # Default stub exits 0 for all invocations; record every call to a log file
    # so we can assert that the expected cloud operations were reached.
    CALL_LOG="$(mktemp)"
    cat > "${TMP_BIN}/ibmcloud" <<STUB
#!/usr/bin/env bash
echo "\$*" >> "${CALL_LOG}"
exit 0
STUB
    chmod +x "${TMP_BIN}/ibmcloud"

    _run_make

    # Preflight must have succeeded.
    [ "$status" -eq 0 ]

    # No preflight error messages.
    [[ "$output" != *"does not exist"* ]]
    [[ "$output" != *"ibmcloud CLI not found"* ]]
    [[ "$output" != *"Could not verify"* ]]

    # The expected cloud operations must have been reached after the preflight.
    grep -qF "secret get --name my-regcred" "${CALL_LOG}"
    # The env-secret step (create or update) must have run.
    grep -qE "secret (create|update) --name testapp-env" "${CALL_LOG}"
    # The application step (create or update) must have run.
    grep -qE "application (create|update) --name testapp" "${CALL_LOG}"

    rm -f "${CALL_LOG}"
}
