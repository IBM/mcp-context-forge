# Shared helpers for the bats suite covering the .secrets.baseline merge
# driver (scripts/git/resolve-secrets-baseline-conflict.sh) and the
# configure-secrets-merge-driver Makefile target.
#
# All helpers operate on throwaway repositories created under mktemp dirs;
# nothing touches the real repo's hooks, config, or worktree.

HELPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HELPER_DIR/../../../.." && pwd)"
DRIVER_SCRIPT="$REPO_ROOT/scripts/git/resolve-secrets-baseline-conflict.sh"
HOOK_SCRIPT="$REPO_ROOT/scripts/git/post-rewrite-secrets-refresh.sh"

# Same pinned spec the driver, the hook, and the Makefile use.
DETECT_SECRETS_TEST_SPEC='git+https://github.com/ibm/detect-secrets.git@076672a9a01abdfc7ecee2e7d14f08cdccb73976'

# A value detect-secrets flags under --use-all-plugins (Secret Keyword +
# Base64 High Entropy String). Verified against the pinned DETECT_SECRETS_SPEC.
FAKE_AWS_KEY='AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY"'  # pragma: allowlist secret

# init_repo: create a throwaway repo in a fresh mktemp dir and cd into it.
# Sets REPO to the new repo path.
init_repo() {
    REPO=$(mktemp -d)
    git init -q -b main "$REPO"
    cd "$REPO" || return 1
    git config user.email "bats@example.invalid"
    git config user.name "bats"
}

# write_seed_baseline: minimal baseline accepted by `detect-secrets scan
# --update` at the pinned spec (word_list must be an object, not a list).
write_seed_baseline() {
    cat > .secrets.baseline <<'EOF'
{"version":"1.5.0","plugins_used":[],"results":{},"generated_at":"2025-01-01T00:00:00Z","word_list":{"file":null,"hash":null},"exclude":{"files":null,"lines":null}}
EOF
}

# commit_all <msg>: stage everything and commit.
commit_all() {
    git add -A
    git commit -qm "$1"
}

# write_fake_secret <file>: overwrite <file> with content detect-secrets flags.
write_fake_secret() {
    printf '%s\n' "$FAKE_AWS_KEY" > "$1"
}

# run_driver [O] [B] [P]: invoke the driver the way git / the Makefile wrapper
# would. %A is a fresh temp copy of the worktree baseline; its path is left in
# DRIVER_OUT for post-run jq assertions. Env overrides (GIT_DIFF_TARGET,
# DETECT_SECRETS_PATH, UV_BIN, ...) are set by the caller, e.g.
#   GIT_DIFF_TARGET=main run_driver
run_driver() {
    local o=${1:--} b=${2:--} p=${3:-.secrets.baseline}
    DRIVER_OUT=$(mktemp)
    cp .secrets.baseline "$DRIVER_OUT"
    run "$DRIVER_SCRIPT" "$o" "$DRIVER_OUT" "$b" "$p"
}

# setup_standard_repo: clean app.py + seed baseline committed on main.
setup_standard_repo() {
    ORIG_DIR=$PWD
    init_repo
    printf 'x = 1\n' > app.py
    write_seed_baseline
    commit_all "initial"
}

# teardown_repo: leave the temp repo and delete it.
teardown_repo() {
    cd "$ORIG_DIR" || return 1
    if [ -n "${REPO:-}" ] && [ -d "$REPO" ]; then
        rm -rf "$REPO"
    fi
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
