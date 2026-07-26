#!/usr/bin/env bats
# End-to-end tests: a REAL `git rebase` invoking the installed
# .secrets.baseline merge driver (scripts/git/resolve-secrets-baseline-conflict.sh),
# plus the Makefile wrapper's variable pass-through. The standalone-driver
# suite (resolve_secrets_baseline_conflict.bats) cannot cover these paths:
# with the ort merge strategy git invokes the driver for a conflicting pick
# BEFORE the pick's added files are checked out (and before the index is
# updated), which is exactly the gap these tests pin down.
#
# Every test runs against a throwaway repo (mktemp -d); see
# test_helper/helpers.bash.

load test_helper/helpers

# Same pinned spec the driver and the Makefile use.
DETECT_SECRETS_TEST_SPEC='git+https://github.com/ibm/detect-secrets.git@076672a9a01abdfc7ecee2e7d14f08cdccb73976'

setup() {
    setup_standard_repo
}

teardown() {
    teardown_repo
}

# install_driver: configure the merge driver in the throwaway repo the way
# `make configure-secrets-merge-driver` does: driver copied out of the
# worktree, git config pointing at the copy, and the .gitattributes binding
# (committed so every pick in the history carries it).
install_driver() {
    mkdir -p .git/git-drivers
    cp "$DRIVER_SCRIPT" .git/git-drivers/resolve-secrets-baseline-conflict.sh
    chmod +x .git/git-drivers/resolve-secrets-baseline-conflict.sh
    git config merge.secrets-baseline.name "Regenerate .secrets.baseline via detect-secrets-scan"
    git config merge.secrets-baseline.driver "$REPO/.git/git-drivers/resolve-secrets-baseline-conflict.sh %O %A %B %P"
    printf '%s\n' '.secrets.baseline merge=secrets-baseline' > .gitattributes
    git add .gitattributes
    git commit -qm "configure secrets-baseline merge driver"
}

# rescan_baseline [path...]: refresh .secrets.baseline with the pinned
# detect-secrets, limited to the given paths.
rescan_baseline() {
    uv tool run --from "$DETECT_SECRETS_TEST_SPEC" detect-secrets scan \
        --update .secrets.baseline --use-all-plugins "$@" >/dev/null
}

# set_baseline_verdict <true|false>: mark every baseline entry with the given
# is_secret verdict (what `make detect-secrets-audit` would record).
set_baseline_verdict() {
    jq ".results |= with_entries(.value |= map(. + {is_secret: $1}))" \
        .secrets.baseline > .secrets.baseline.new
    mv .secrets.baseline.new .secrets.baseline
}

# setup_rebase_conflict <verdict>: build the two-sided history that makes a
# rebase pick both ADD secret.py and conflict on .secrets.baseline:
#   main:    initial commit -> driver binding -> baseline touched by main
#   feature: branched before main's touch; adds secret.py plus a baseline
#            whose entries carry the given is_secret verdict
setup_rebase_conflict() {
    install_driver

    git checkout -qb feature
    write_fake_secret secret.py
    rescan_baseline secret.py
    set_baseline_verdict "$1"
    commit_all "add secret.py with audited baseline"

    git checkout -q main
    printf 'y = 2\n' > other.py
    rescan_baseline other.py
    commit_all "main touches baseline"

    git checkout -q feature
}

# --- Gap 1: pick adds a file AND touches .secrets.baseline -------------------

@test "rebase: pick adding a file with an audited-false secret auto-resolves the baseline conflict" {
    # The ordinary pattern: a file with an already-audited (false positive)
    # secret is added in one commit together with its baseline entry. The
    # driver must regenerate a baseline that keeps the pick's entry and
    # verdicts, letting the rebase complete without manual resolution.
    setup_rebase_conflict false

    run git rebase main
    [ "$status" -eq 0 ]
    [[ "$output" != *"audited as real would be lost"* ]]
    [ -f secret.py ]
    run jq -e '.results["secret.py"] | length > 0 and all(.[]; .is_secret == false)' .secrets.baseline
    [ "$status" -eq 0 ]
}

@test "rebase: pick adding a file with an audited-real verdict stops at the audit gate, not on a spurious lost-verdict report" {
    # The reviewer's repro. Before the fix the driver could not see the
    # pick's new file at scan time, so the merged output lacked its entries
    # and the %B fail-closed check reported the audited-real verdict as lost
    # — a spurious reason, since the verdict is recoverable. After the fix
    # the verdict survives into the merged output, and the rebase stops only
    # because the audit gate (correctly, fail-closed) refuses a baseline
    # containing audited-real findings.
    setup_rebase_conflict true

    run git rebase main
    [ "$status" -ne 0 ]
    [[ "$output" != *"audited as real would be lost"* ]]
    [[ "$output" == *"unaudited/live finding(s) in regenerated baseline"* ]]

    # Aborting the stopped rebase restores a clean tree — no strays from
    # files the driver materialized for its scan.
    run git rebase --abort
    [ "$status" -eq 0 ]
    run git status --porcelain
    [ -z "$output" ]
    [ -f secret.py ]
}

# --- Gap 2: Makefile wrapper pass-through --------------------------------------

@test "make detect-secrets-scan forwards no GIT_DIFF_TARGET/DETECT_SECRETS_PATH overrides by default" {
    run env -u GIT_DIFF_TARGET -u DETECT_SECRETS_PATH make -n -C "$REPO_ROOT" detect-secrets-scan
    [ "$status" -eq 0 ]
    local exec_line
    exec_line=$(printf '%s\n' "$output" | grep 'resolve-secrets-baseline-conflict.sh -')
    [ -n "$exec_line" ]
    [[ "$exec_line" != *'GIT_DIFF_TARGET='* ]]
    [[ "$exec_line" != *'DETECT_SECRETS_PATH='* ]]
}

@test "make detect-secrets-scan forwards an explicitly-set GIT_DIFF_TARGET" {
    run env -u GIT_DIFF_TARGET -u DETECT_SECRETS_PATH make -n -C "$REPO_ROOT" detect-secrets-scan GIT_DIFF_TARGET=xyz
    [ "$status" -eq 0 ]
    local exec_line
    exec_line=$(printf '%s\n' "$output" | grep 'resolve-secrets-baseline-conflict.sh -')
    [ -n "$exec_line" ]
    [[ "$exec_line" == *'GIT_DIFF_TARGET="xyz"'* ]]
}
