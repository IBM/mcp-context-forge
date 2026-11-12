#!/usr/bin/env bats
# Tests for scripts/git/post-rewrite-secrets-refresh.sh, the post-rewrite hook
# that refreshes .secrets.baseline after a rebase and amends the refresh into
# HEAD.
#
# The hook is invoked directly as `post-rewrite rebase|amend` from the top
# level of a throwaway repo (mktemp -d); see test_helper/helpers.bash. A stale
# baseline is simulated by committing an audited entry with a wrong
# line_number: the scan corrects the line number and keeps the verdict, so the
# refresh produces a substantive change with zero unaudited findings.

load test_helper/helpers

setup() {
    setup_standard_repo
}

teardown() {
    teardown_repo
}

# make_stale_baseline_repo: feature branch whose HEAD commit adds secret.py
# with an audited-false baseline entry recorded at the wrong line number.
make_stale_baseline_repo() {
    git checkout -qb feature
    write_fake_secret secret.py
    rescan_baseline secret.py
    set_baseline_verdict false
    jq '.results |= with_entries(.value |= map(.line_number = 99))' \
        .secrets.baseline > .secrets.baseline.new
    mv .secrets.baseline.new .secrets.baseline
    commit_all "add secret.py with stale baseline"
}

# run_hook <amend|rebase>: run the hook the way git does (no stdin lines).
run_hook() {
    run env GIT_DIFF_TARGET=main "$HOOK_SCRIPT" "$1" < /dev/null
}

head_line_number() {
    git show HEAD:.secrets.baseline | jq -r '.results["secret.py"][0].line_number'
}

@test "rebase: refreshed baseline is amended into HEAD" {
    make_stale_baseline_repo
    local old_head old_count old_msg
    old_head=$(git rev-parse HEAD)
    old_count=$(git rev-list --count HEAD)
    old_msg=$(git log -1 --format=%B)
    [ "$(head_line_number)" = "99" ]

    run_hook rebase

    [ "$status" -eq 0 ]
    [[ "$output" == *"refreshed and amended into HEAD"* ]]
    [ "$(git rev-parse HEAD)" != "$old_head" ]
    [ "$(git rev-list --count HEAD)" = "$old_count" ]
    [ "$(git log -1 --format=%B)" = "$old_msg" ]
    [ "$(head_line_number)" = "1" ]
    run jq -e '.results["secret.py"] | all(.[]; .is_secret == false)' .secrets.baseline
    [ "$status" -eq 0 ]
    run git status --porcelain
    [ -z "$output" ]
}

@test "rebase: unrelated staged changes stay out of the amended commit" {
    make_stale_baseline_repo
    printf 'z = 3\n' > unrelated.py
    git add unrelated.py

    run_hook rebase

    [ "$status" -eq 0 ]
    run git show --name-only --format= HEAD
    [[ "$output" == *".secrets.baseline"* ]]
    [[ "$output" != *"unrelated.py"* ]]
    run git diff --cached --name-only
    [ "$output" = "unrelated.py" ]
}

@test "amend: hook does nothing" {
    make_stale_baseline_repo
    local old_head
    old_head=$(git rev-parse HEAD)

    run_hook amend

    [ "$status" -eq 0 ]
    [ "$(git rev-parse HEAD)" = "$old_head" ]
    [ "$(head_line_number)" = "99" ]
    run git status --porcelain
    [ -z "$output" ]
}

@test "rebase: second run with an up-to-date baseline leaves HEAD alone" {
    make_stale_baseline_repo
    run_hook rebase
    [ "$status" -eq 0 ]
    local head_after_first
    head_after_first=$(git rev-parse HEAD)

    run_hook rebase

    [ "$status" -eq 0 ]
    [[ "$output" == *"already up to date"* ]]
    [ "$(git rev-parse HEAD)" = "$head_after_first" ]
    run git status --porcelain
    [ -z "$output" ]
}

@test "rebase: failed amend warns, exits 0, and leaves the refresh staged" {
    make_stale_baseline_repo
    local old_head
    old_head=$(git rev-parse HEAD)
    printf '#!/bin/sh\nexit 1\n' > .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit

    run_hook rebase

    [ "$status" -eq 0 ]
    [[ "$output" == *"could not amend HEAD"* ]]
    [[ "$output" != *"amended into HEAD"* ]]
    [ "$(git rev-parse HEAD)" = "$old_head" ]
    run git diff --cached --name-only
    [ "$output" = ".secrets.baseline" ]
}

@test "rebase: unaudited findings warn and leave HEAD alone" {
    git checkout -qb feature
    write_fake_secret secret.py
    rescan_baseline secret.py
    commit_all "add secret.py with unaudited baseline entry"
    local old_head
    old_head=$(git rev-parse HEAD)

    run_hook rebase

    [ "$status" -eq 0 ]
    [[ "$output" == *"review .secrets.baseline manually"* ]]
    [ "$(git rev-parse HEAD)" = "$old_head" ]
}

@test "rebase: chained post-rewrite hook runs after the amend with the same args and stdin" {
    make_stale_baseline_repo
    cat > .git/hooks/post-rewrite.chain <<'EOF'
#!/bin/sh
printf '%s\n' "$*" > "$CHAIN_OUT"
cat >> "$CHAIN_OUT"
EOF
    chmod +x .git/hooks/post-rewrite.chain
    export CHAIN_OUT="$BATS_TEST_TMPDIR/chain.out"

    run env GIT_DIFF_TARGET=main "$HOOK_SCRIPT" rebase <<< "oldsha newsha"

    [ "$status" -eq 0 ]
    [ "$(head_line_number)" = "1" ]
    [ "$(sed -n 1p "$CHAIN_OUT")" = "rebase" ]
    [ "$(sed -n 2p "$CHAIN_OUT")" = "oldsha newsha" ]
}
