#!/usr/bin/env bats
# Tests for scripts/git/resolve-secrets-baseline-conflict.sh, the git merge
# driver that regenerates .secrets.baseline during merges/rebases.
#
# Every test runs against a throwaway repo (mktemp -d); see
# test_helper/helpers.bash. Observable behavior (exit status, stderr messages,
# merged baseline content) is asserted, not driver internals.

load test_helper/helpers

setup() {
    setup_standard_repo
}

teardown() {
    teardown_repo
}

# --- Scope detection ---------------------------------------------------------

@test "scope: rebase-merge state dir scans the orig-head changeset" {
    printf 'y = 2\n' > clean_change.py
    commit_all "clean change"
    write_fake_secret secret.py
    commit_all "add secret"
    mkdir -p .git/rebase-merge
    git rev-parse HEAD~2 > .git/rebase-merge/onto
    git rev-parse HEAD > .git/rebase-merge/orig-head

    run_driver
    [ "$status" -eq 1 ]
    [[ "$output" == *"unaudited/live finding(s)"* ]]
}

@test "scope: rebase-merge state dir ignores out-of-scope worktree changes" {
    printf 'y = 2\n' > clean_change.py
    commit_all "clean change"
    mkdir -p .git/rebase-merge
    git rev-parse HEAD~1 > .git/rebase-merge/onto
    git rev-parse HEAD > .git/rebase-merge/orig-head
    # Uncommitted secret in a tracked file: outside the commit-to-commit scope.
    write_fake_secret app.py

    run_driver
    [ "$status" -eq 0 ]
    [[ "$output" == *"regenerated as merge result"* ]]
    run jq -e '.results | has("app.py") | not' "$DRIVER_OUT"
    [ "$status" -eq 0 ]
}

@test "scope: rebase-apply state dir is detected" {
    write_fake_secret secret.py
    commit_all "add secret"
    mkdir -p .git/rebase-apply
    git rev-parse HEAD~1 > .git/rebase-apply/onto
    git rev-parse HEAD > .git/rebase-apply/orig-head

    run_driver
    [ "$status" -eq 1 ]
    [[ "$output" == *"unaudited/live finding(s)"* ]]
}

@test "scope: MERGE_HEAD branch wins over the GIT_DIFF_TARGET fallback" {
    git rev-parse HEAD > .git/MERGE_HEAD
    # A bogus GIT_DIFF_TARGET would make the fallback's `git diff` fail; a
    # clean run proves the MERGE_HEAD branch was taken instead.
    GIT_DIFF_TARGET=bogus-ref-that-does-not-exist run_driver
    [ "$status" -eq 0 ]
    [[ "$output" == *"regenerated as merge result"* ]]
}

@test "scope: MERGE_HEAD scenario scans worktree changes against merge-base" {
    git rev-parse HEAD > .git/MERGE_HEAD
    # Uncommitted secret in a tracked file: inside the merge-base..worktree diff.
    write_fake_secret app.py

    GIT_DIFF_TARGET=bogus-ref-that-does-not-exist run_driver
    [ "$status" -eq 1 ]
    [[ "$output" == *"unaudited/live finding(s)"* ]]
}

@test "scope: fallback diffs the worktree against GIT_DIFF_TARGET" {
    write_fake_secret app.py

    GIT_DIFF_TARGET=main run_driver
    [ "$status" -eq 1 ]
    [[ "$output" == *"unaudited/live finding(s)"* ]]
}

@test "scope: explicit DETECT_SECRETS_PATH overrides the fallback diff" {
    printf 'z = 3\n' > clean.py
    commit_all "add clean file"
    write_fake_secret app.py

    DETECT_SECRETS_PATH=clean.py GIT_DIFF_TARGET=main run_driver
    [ "$status" -eq 0 ]
    [[ "$output" == *"regenerated as merge result"* ]]
    run jq -e '.results | has("app.py") | not' "$DRIVER_OUT"
    [ "$status" -eq 0 ]
}

@test "scope: fallback prefers a local master branch over the whole-tree scan" {
    # No main/develop/origin refs, but a local master exists: the scope must
    # be the commit diff against master, NOT a whole-tree scan. The tracked
    # modification is inside both scopes; the untracked scratch file is only
    # visible to a whole-tree scan — so the finding count (2 = app.py only,
    # not 4) and the absent warning pin the scope precisely.
    teardown_repo
    REPO=$(mktemp -d)
    git init -q -b master "$REPO"
    cd "$REPO" || return 1
    git config user.email "bats@example.invalid"
    git config user.name "bats"
    printf 'x = 1\n' > app.py
    write_seed_baseline
    commit_all "initial"
    write_fake_secret app.py
    write_fake_secret scratch.py

    run_driver
    [ "$status" -eq 1 ]
    [[ "$output" != *"scanning the whole tree"* ]]
    [[ "$output" == *"2 unaudited/live finding(s)"* ]]
}

@test "scope: fallback uses origin/HEAD when no local main/master/develop exists" {
    # Only a feature branch locally, but the remote's default is recorded:
    # refs/remotes/origin/HEAD -> origin/master must be the diff base. Same
    # tracked-vs-untracked trick to pin the scope to the commit diff.
    teardown_repo
    REPO=$(mktemp -d)
    git init -q -b feature "$REPO"
    cd "$REPO" || return 1
    git config user.email "bats@example.invalid"
    git config user.name "bats"
    printf 'x = 1\n' > app.py
    write_seed_baseline
    commit_all "initial"
    git update-ref refs/remotes/origin/master HEAD
    git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/master
    write_fake_secret app.py
    write_fake_secret scratch.py

    run_driver
    [ "$status" -eq 1 ]
    [[ "$output" != *"scanning the whole tree"* ]]
    [[ "$output" == *"2 unaudited/live finding(s)"* ]]
}

@test "scope: fallback with neither main nor origin/main warns and scans the whole tree" {
    # Checkouts with only a PR ref (e.g. CI) have no usable diff base; the
    # fallback chain must degrade to a whole-tree scan instead of dying on
    # `fatal: ambiguous argument`.
    teardown_repo
    REPO=$(mktemp -d)
    git init -q -b feature "$REPO"
    cd "$REPO" || return 1
    git config user.email "bats@example.invalid"
    git config user.name "bats"
    printf 'x = 1\n' > app.py
    write_seed_baseline
    commit_all "initial"

    run_driver
    [ "$status" -eq 0 ]
    [[ "$output" == *"no main/master/develop branch or origin HEAD ref; scanning the whole tree"* ]]
    [[ "$output" == *"regenerated as merge result"* ]]
}

# --- Exit gate ---------------------------------------------------------------

@test "gate: unaudited finding in scope fails the run" {
    write_fake_secret app.py

    GIT_DIFF_TARGET=main run_driver
    [ "$status" -eq 1 ]
    [[ "$output" == *"unaudited/live finding(s) in regenerated baseline"* ]]
    [[ "$output" == *"detect-secrets-audit"* ]]
}

@test "gate: unreadable audit stats fail with a clear message" {
    local stub="$REPO/uv-stub"
    cat > "$stub" <<'EOF'
#!/usr/bin/env bash
for arg in "$@"; do
    if [ "$arg" = "audit" ]; then
        echo "this-is-not-json"
        exit 0
    fi
done
exec uv "$@"
EOF
    chmod +x "$stub"

    UV_BIN="$stub" GIT_DIFF_TARGET=main run_driver
    [ "$status" -eq 1 ]
    [[ "$output" == *"could not read audit stats"* ]]
}

# --- jq merge semantics --------------------------------------------------------

@test "merge: baseline entries for untracked files are pruned by exact membership" {
    # Guards the INDEX exact-membership fix: a tracked config.py.bak must not
    # keep a stale config.py entry alive (the old substring inside() would).
    git rm -q app.py
    printf 'backup\n' > config.py.bak
    commit_all "replace app.py with config.py.bak"
    jq '.results = {"config.py": [{"hashed_secret": "0123456789abcdef0123456789abcdef01234567", "is_secret": false, "is_verified": false, "line_number": 1, "type": "Secret Keyword", "verified_result": null}]}' .secrets.baseline > .secrets.baseline.new  # pragma: allowlist secret
    mv .secrets.baseline.new .secrets.baseline
    commit_all "baseline with stale config.py entry"

    DETECT_SECRETS_PATH=config.py.bak GIT_DIFF_TARGET=main run_driver
    [ "$status" -eq 0 ]
    run jq -e '.results | has("config.py") | not' "$DRIVER_OUT"
    [ "$status" -eq 0 ]
}

# --- %B verdict preservation ---------------------------------------------------

@test "verdicts: %B entry audited real is lost when its file is gone" {
    local b_file="$REPO/b.json"
    jq -n '{version:"1.5.0",plugins_used:[],results:{"gone.py":[{hashed_secret:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",is_secret:true,is_verified:false,line_number:3,type:"Secret Keyword",verified_result:null}]},generated_at:"2025-01-01T00:00:00Z",word_list:{file:null,hash:null},exclude:{files:null,lines:null}}' > "$b_file"  # pragma: allowlist secret

    DETECT_SECRETS_PATH=app.py GIT_DIFF_TARGET=main run_driver - "$b_file"
    [ "$status" -eq 1 ]
    [[ "$output" == *"audited as real would be lost"* ]]
    [[ "$output" == *"gone.py: line 3"* ]]
}

@test "verdicts: %B audited-real verdict is lost when the worktree baseline audited false" {
    jq '.results = {"app.py": [{"hashed_secret": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "is_secret": false, "is_verified": false, "line_number": 1, "type": "Secret Keyword", "verified_result": null}]}' .secrets.baseline > .secrets.baseline.new  # pragma: allowlist secret
    mv .secrets.baseline.new .secrets.baseline
    commit_all "baseline audits app.py finding as false positive"
    local b_file="$REPO/b.json"
    jq -n '{version:"1.5.0",plugins_used:[],results:{"app.py":[{hashed_secret:"cccccccccccccccccccccccccccccccccccccccc",is_secret:true,is_verified:false,line_number:7,type:"Secret Keyword",verified_result:null}]},generated_at:"2025-01-01T00:00:00Z",word_list:{file:null,hash:null},exclude:{files:null,lines:null}}' > "$b_file"  # pragma: allowlist secret

    DETECT_SECRETS_PATH=app.py GIT_DIFF_TARGET=main run_driver - "$b_file"
    [ "$status" -eq 1 ]
    [[ "$output" == *"audited as real would be lost"* ]]
    [[ "$output" == *"app.py: line 7"* ]]
}

@test "verdicts: dash %B skips the preservation check" {
    GIT_DIFF_TARGET=main run_driver - -
    [ "$status" -eq 0 ]
    [[ "$output" == *"no usable %B provided"* ]]
    [[ "$output" == *"regenerated as merge result"* ]]
}

@test "verdicts: unparseable %B skips the preservation check with a warning" {
    local b_file="$REPO/b.json"
    printf 'this is not json\n' > "$b_file"

    GIT_DIFF_TARGET=main run_driver - "$b_file"
    [ "$status" -eq 0 ]
    [[ "$output" == *"could not parse %B"* ]]
    [[ "$output" == *"regenerated as merge result"* ]]
}

# --- Prerequisites -------------------------------------------------------------

@test "prereqs: missing jq aborts with an actionable message" {
    local stubbin="$REPO/stubbin"
    mkdir -p "$stubbin"
    ln -s "$(command -v bash)" "$stubbin/bash"

    run env PATH="$stubbin" "$DRIVER_SCRIPT" - whatever - x
    [ "$status" -eq 1 ]
    [[ "$output" == *"jq not found"* ]]
    [[ "$output" == *"install jq"* ]]
}
