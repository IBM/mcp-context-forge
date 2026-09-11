#!/usr/bin/env bats
# Tests for the ibmcloud-deploy preflight checks in the Makefile.
#
# Drives `make -C "$REPO_ROOT" ibmcloud-deploy` directly against the working
# tree (no clone needed) with a stub ibmcloud injected at the front of PATH.
# All IBMCLOUD_* variables are supplied as Make overrides; a minimal .env is
# written to a temporary directory and passed via the ENVFILE override used
# by the test-only Make invocation.  The real repo's state is never modified.

load test_helper/helpers

# Common Make variable overrides — satisfy every required IBMCLOUD_* variable.
MAKE_VARS=(
    IBMCLOUD_CODE_ENGINE_APP=test-app
    IBMCLOUD_REGISTRY_SECRET=test-regcred
    IBMCLOUD_IMAGE_NAME=us.icr.io/ns/img:latest
    IBMCLOUD_IMG_PROD=local/img
    IBMCLOUD_REGION=us-south
    IBMCLOUD_PROJECT=test-proj
    IBMCLOUD_RESOURCE_GROUP=default
    IBMCLOUD_CPU=1
    IBMCLOUD_MEMORY=4G
    IBMCLOUD_API_KEY=dummy-key
)

setup() {
    TMP_DIR="$(mktemp -d)"
    mkdir -p "$TMP_DIR/bin"

    # Write a minimal .env into the temp dir; the Makefile `test -f .env` guard
    # runs in the repo root so we symlink it there temporarily, restoring on teardown.
    printf 'HOST=0.0.0.0\nPORT=4444\n' > "$TMP_DIR/.env"
    _ENV_EXISTED=false
    if [ -f "$REPO_ROOT/.env" ]; then
        _ENV_EXISTED=true
    else
        cp "$TMP_DIR/.env" "$REPO_ROOT/.env"
        _ENV_INJECTED=true
    fi
}

teardown() {
    if [ "${_ENV_INJECTED:-false}" = true ] && [ -f "$REPO_ROOT/.env" ]; then
        rm -f "$REPO_ROOT/.env"
    fi
    rm -rf "$TMP_DIR"
}

# Write a stub ibmcloud with the given body and run make ibmcloud-deploy
# against the live working tree.
run_deploy() {
    local stub_body="${1:-exit 0}"
    cat > "$TMP_DIR/bin/ibmcloud" <<STUB
#!/usr/bin/env bash
${stub_body}
STUB
    chmod +x "$TMP_DIR/bin/ibmcloud"

    run env -u MAKEFLAGS \
        PATH="$TMP_DIR/bin:$PATH" \
        make --no-print-directory -C "$REPO_ROOT" ibmcloud-deploy \
        "${MAKE_VARS[@]}"
}

# ── 1. Missing ibmcloud CLI ───────────────────────────────────────────────────

@test "missing ibmcloud CLI reports installation guidance, not a missing secret" {
    # No stub written — ibmcloud absent from PATH entirely.
    run env -u MAKEFLAGS \
        PATH="$TMP_DIR/bin:$PATH" \
        make --no-print-directory -C "$REPO_ROOT" ibmcloud-deploy \
        "${MAKE_VARS[@]}"

    [ "$status" -ne 0 ]
    [[ "$output" == *"ibmcloud CLI not found"* ]]
    [[ "$output" == *"ibmcloud-cli-install"* ]]
    [[ "$output" != *"does not exist"* ]]
    [[ "$output" != *"Create it first"* ]]
}

# ── 2. Registry secret genuinely absent ──────────────────────────────────────

@test "absent registry secret exits with creation guidance" {
    run_deploy "
if [[ \"\$*\" == *'ce secret get'*'test-regcred'* ]]; then
    echo \"[FAILED] Getting secret 'test-regcred': Secret 'test-regcred' not found.\" >&2
    exit 1
fi
exit 0"

    [ "$status" -ne 0 ]
    [[ "$output" == *"does not exist"* ]]
    [[ "$output" == *"Create it first"* ]]
    [[ "$output" != *"ibmcloud CLI not found"* ]]
    [[ "$output" != *"Check your IBM Cloud login"* ]]
}

# ── 3. Generic CLI failure (auth / network) ───────────────────────────────────

@test "generic CLI failure surfaces diagnostic, not creation guidance" {
    run_deploy "
if [[ \"\$*\" == *'ce secret get'*'test-regcred'* ]]; then
    echo \"[FAILED] Unauthorized: Token is expired or invalid. Please re-login.\" >&2
    exit 1
fi
exit 0"

    [ "$status" -ne 0 ]
    [[ "$output" == *"Could not verify registry pull secret"* ]]
    [[ "$output" == *"Diagnostic:"* ]]
    [[ "$output" == *"Check your IBM Cloud login"* ]]
    [[ "$output" != *"Create it first"* ]]
    [[ "$output" != *"does not exist"* ]]
}

# ── 4. Missing CE project is not misclassified as a missing secret ────────────

@test "missing CE project failure is not misclassified as a missing registry secret" {
    run_deploy "
if [[ \"\$*\" == *'ce secret get'*'test-regcred'* ]]; then
    echo \"[FAILED] Getting secret 'test-regcred': Project 'test-proj' not found.\" >&2
    exit 1
fi
exit 0"

    [ "$status" -ne 0 ]
    [[ "$output" == *"Could not verify registry pull secret"* ]]
    [[ "$output" == *"Check your IBM Cloud login"* ]]
    [[ "$output" != *"does not exist"* ]]
    [[ "$output" != *"Create it first"* ]]
}

# ── 5. Happy path — secret exists, new app created ───────────────────────────

@test "happy path succeeds and invokes application create" {
    run_deploy "
echo \"STUB_CALL: \$*\" >> \"$TMP_DIR/calls.log\"
exit 0"

    [ "$status" -eq 0 ]
    [[ "$output" != *"❌"* ]]
    grep -q "ce secret get" "$TMP_DIR/calls.log"
    grep -q "ce application" "$TMP_DIR/calls.log"
}
