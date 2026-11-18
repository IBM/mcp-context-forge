#!/usr/bin/env bats
# Tests for the configure-secrets-merge-driver Makefile target, exercised
# against a throwaway clone of this repository (mktemp -d) so the real repo's
# git config and hooks are never touched.

load test_helper/helpers

setup() {
    ORIG_DIR=$PWD
    CLONE_PARENT=$(mktemp -d)
    git clone -q "$REPO_ROOT" "$CLONE_PARENT/repo"
    cd "$CLONE_PARENT/repo" || return 1
}

teardown() {
    cd "$ORIG_DIR" || return 1
    if [ -n "${CLONE_PARENT:-}" ] && [ -d "$CLONE_PARENT" ]; then
        rm -rf "$CLONE_PARENT"
    fi
}

@test "make configure-secrets-merge-driver is idempotent" {
    run make --no-print-directory configure-secrets-merge-driver
    [ "$status" -eq 0 ]
    run make --no-print-directory configure-secrets-merge-driver
    [ "$status" -eq 0 ]

    local common_dir
    common_dir=$(git rev-parse --git-common-dir)
    [ "$(grep -cF '.secrets.baseline merge=secrets-baseline' .gitattributes)" -eq 1 ]
    [ "$(grep -cF '.secrets.baseline merge=secrets-baseline' "$common_dir/info/attributes")" -eq 1 ]
    [ -x "$common_dir/git-drivers/resolve-secrets-baseline-conflict.sh" ]
    [[ "$(git config merge.secrets-baseline.driver)" == *"resolve-secrets-baseline-conflict.sh %O %A %B %P"* ]]
}
