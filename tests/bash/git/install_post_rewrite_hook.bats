#!/usr/bin/env bats
# Tests for the install-post-rewrite-detect-secrets-hook Makefile target,
# exercised against a throwaway clone of this repository (mktemp -d) so the
# real repo's git config and hooks are never touched. The working-tree
# Makefile and hook script are copied over the clone's committed versions so
# uncommitted changes are what gets tested.

load test_helper/helpers

setup() {
    ORIG_DIR=$PWD
    CLONE_PARENT=$(mktemp -d)
    git clone -q "$REPO_ROOT" "$CLONE_PARENT/repo"
    cp "$REPO_ROOT/Makefile" "$CLONE_PARENT/repo/Makefile"
    cp "$HOOK_SCRIPT" "$CLONE_PARENT/repo/scripts/git/post-rewrite-secrets-refresh.sh"
    cd "$CLONE_PARENT/repo" || return 1
    export GIT_CONFIG_GLOBAL=/dev/null
    git config user.email "bats@example.invalid"
    git config user.name "bats"
    COMMON_DIR=$(cd "$(git rev-parse --git-common-dir)" && pwd)
    HOOKS_DIR="$COMMON_DIR/hooks"
    NAME=contextforge-secrets-refresh
}

teardown() {
    cd "$ORIG_DIR" || return 1
    if [ -n "${CLONE_PARENT:-}" ] && [ -d "$CLONE_PARENT" ]; then
        rm -rf "$CLONE_PARENT"
    fi
}

install_hook() {
    run make --no-print-directory install-post-rewrite-detect-secrets-hook "$@"
}

git_supports_config_hooks() {
    local v maj min
    v=$(git version | sed -n 's/^git version \([0-9]*\)\.\([0-9]*\).*/\1 \2/p')
    maj=${v% *}
    min=${v#* }
    [ "$maj" -gt 2 ] || { [ "$maj" -eq 2 ] && [ "$min" -ge 54 ]; }
}

write_foreign_hook() {
    printf '#!/bin/sh\necho foreign >> "$FOREIGN_OUT"\n' > "$HOOKS_DIR/post-rewrite"
    chmod +x "$HOOKS_DIR/post-rewrite"
}

# fake_old_git <version-line>: put a git shim first on PATH that reports the
# given `git version` output and delegates everything else to the real git.
fake_old_git() {
    local fakebin="$BATS_TEST_TMPDIR/fakebin" real_git
    real_git=$(command -v git)
    mkdir -p "$fakebin"
    {
        printf '#!/bin/sh\n'
        printf 'if [ "$1" = "version" ]; then echo "%s"; exit 0; fi\n' "$1"
        printf 'exec "%s" "$@"\n' "$real_git"
    } > "$fakebin/git"
    chmod +x "$fakebin/git"
    PATH="$fakebin:$PATH"
}

@test "config mode: registers a config hook and leaves the hooks dir alone" {
    git_supports_config_hooks || skip "needs Git >= 2.54"

    install_hook POST_REWRITE_HOOK_MODE=config

    [ "$status" -eq 0 ]
    [ -x "$COMMON_DIR/git-drivers/post-rewrite-secrets-refresh.sh" ]
    [ ! -e "$HOOKS_DIR/post-rewrite" ]
    [ "$(git config --local --get-all "hook.$NAME.event")" = "post-rewrite" ]
    run git hook list post-rewrite
    [[ "$output" == *"$NAME"* ]]
}

@test "auto mode picks the config hook on a Git that supports it" {
    git_supports_config_hooks || skip "needs Git >= 2.54"

    install_hook

    [ "$status" -eq 0 ]
    [[ "$output" == *"Installed config hook"* ]]
    [ ! -e "$HOOKS_DIR/post-rewrite" ]
}

@test "file mode: installs the legacy hook file and no config hook" {
    install_hook POST_REWRITE_HOOK_MODE=file

    [ "$status" -eq 0 ]
    [ -x "$HOOKS_DIR/post-rewrite" ]
    run git config --local --get-all "hook.$NAME.event"
    [ "$status" -ne 0 ]
}

@test "config mode is idempotent: one event entry, no duplicate hook" {
    git_supports_config_hooks || skip "needs Git >= 2.54"

    install_hook POST_REWRITE_HOOK_MODE=config
    install_hook POST_REWRITE_HOOK_MODE=config

    [ "$status" -eq 0 ]
    [ "$(git config --local --get-all "hook.$NAME.event" | wc -l)" -eq 1 ]
    [ "$(git hook list post-rewrite | grep -c "$NAME")" -eq 1 ]
}

@test "migration: legacy hook file is removed when installing the config hook" {
    git_supports_config_hooks || skip "needs Git >= 2.54"
    install_hook POST_REWRITE_HOOK_MODE=file
    [ -f "$HOOKS_DIR/post-rewrite" ]

    install_hook POST_REWRITE_HOOK_MODE=config

    [ "$status" -eq 0 ]
    [[ "$output" == *"Removed legacy post-rewrite hook file"* ]]
    [ ! -e "$HOOKS_DIR/post-rewrite" ]
    [ ! -e "$HOOKS_DIR/post-rewrite.chain" ]
    [ "$(git config --local --get-all "hook.$NAME.event")" = "post-rewrite" ]
}

@test "migration: a chained foreign hook is moved back to post-rewrite and still runs" {
    git_supports_config_hooks || skip "needs Git >= 2.54"
    write_foreign_hook
    install_hook POST_REWRITE_HOOK_MODE=file
    [ -f "$HOOKS_DIR/post-rewrite.chain" ]

    install_hook POST_REWRITE_HOOK_MODE=config

    [ "$status" -eq 0 ]
    [ ! -e "$HOOKS_DIR/post-rewrite.chain" ]
    grep -q 'foreign' "$HOOKS_DIR/post-rewrite"
    run grep -q 'contextforge: post-rewrite-secrets-refresh' "$HOOKS_DIR/post-rewrite"
    [ "$status" -ne 0 ]

    export FOREIGN_OUT="$BATS_TEST_TMPDIR/foreign.out"
    run git hook run post-rewrite -- amend < /dev/null
    [ "$status" -eq 0 ]
    [ "$(cat "$FOREIGN_OUT")" = "foreign" ]
}

@test "config mode: a foreign hook with no legacy install is left in place" {
    git_supports_config_hooks || skip "needs Git >= 2.54"
    write_foreign_hook
    local before
    before=$(cat "$HOOKS_DIR/post-rewrite")

    install_hook POST_REWRITE_HOOK_MODE=config

    [ "$status" -eq 0 ]
    [ "$(cat "$HOOKS_DIR/post-rewrite")" = "$before" ]
    [ ! -e "$HOOKS_DIR/post-rewrite.chain" ]
}

@test "config hook receives the rewrite arguments and stdin from git" {
    git_supports_config_hooks || skip "needs Git >= 2.54"
    install_hook POST_REWRITE_HOOK_MODE=config
    # Replace the installed copy with a recorder to check that the registered
    # command string is invoked with git's arguments and stdin.
    printf '#!/bin/sh\nprintf "%%s\\n" "$*" > "$REC_OUT"\ncat >> "$REC_OUT"\n' \
        > "$COMMON_DIR/git-drivers/post-rewrite-secrets-refresh.sh"
    export REC_OUT="$BATS_TEST_TMPDIR/rec.out"

    local old_head
    old_head=$(git rev-parse HEAD)

    run git commit --amend --allow-empty --no-verify -qm "amended"

    [ "$status" -eq 0 ]
    [ "$(sed -n 1p "$REC_OUT")" = "amend" ]
    [ "$(sed -n 2p "$REC_OUT")" = "$old_head $(git rev-parse HEAD)" ]
}

@test "config mode is refused on a Git older than 2.54" {
    fake_old_git "git version 2.43.0"

    install_hook POST_REWRITE_HOOK_MODE=config

    [ "$status" -ne 0 ]
    [[ "$output" == *"need Git >= 2.54"* ]]
    [ ! -e "$HOOKS_DIR/post-rewrite" ]
}

@test "auto mode falls back to the hook file on a Git older than 2.54" {
    fake_old_git "git version 2.43.0 (Apple Git-146)"

    install_hook

    [ "$status" -eq 0 ]
    [ -x "$HOOKS_DIR/post-rewrite" ]
    run git config --local --get-all "hook.$NAME.event"
    [ "$status" -ne 0 ]
}

@test "an invalid POST_REWRITE_HOOK_MODE is rejected" {
    install_hook POST_REWRITE_HOOK_MODE=bogus

    [ "$status" -ne 0 ]
    [[ "$output" == *"must be auto, config, or file"* ]]
}
