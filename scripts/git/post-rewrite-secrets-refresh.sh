#!/usr/bin/env bash
# contextforge: post-rewrite-secrets-refresh
# post-rewrite git hook: refresh .secrets.baseline after a rebase
#
# Git invokes this as `post-rewrite <amend|rebase>` with "<old> <new>" lines
# on stdin, from the top level of the worktree, after the command finishes.
#
# Why: the .secrets.baseline merge driver resolves each conflict against a
# mid-rebase snapshot (scan scope, ls-files filter, and unchanged entries all
# reflect the tree at that pick), so the rebased baseline can drift from a
# scan of the final tree. Refreshing once, at the end, closes the gap.
#
# Chaining: if <git-common-dir>/hooks/post-rewrite.chain exists, it is run
# after this hook with the same arguments and a copy of stdin. The install
# target (make install-post-rewrite-detect-secrets-hook) moves any pre-existing foreign
# post-rewrite hook there instead of overwriting it; the marker comment on
# line 2 is how the target recognizes this hook as ours on reinstall.
#
# Like the merge driver, this hook is installed (copied into
# <git-common-dir>/hooks/) and must not depend on the tree's Makefile: the
# scan below is a self-contained port of `make detect-secrets-scan`. Keep
# the DETECT_SECRETS_* defaults in sync with the Makefile and with
# scripts/git/resolve-secrets-baseline-conflict.sh.
#
# Install: make install-post-rewrite-detect-secrets-hook  (or make configure-git)

set -euo pipefail

# Preserve stdin for the chained hook (we only need to drain it ourselves).
stdin_copy=$(mktemp)
trap 'rm -f "$stdin_copy"' EXIT
cat > "$stdin_copy"

chain_hook=$(git rev-parse --git-common-dir)/hooks/post-rewrite.chain

# Self-contained port of `make detect-secrets-scan`. Every step is guarded
# with `|| return` because this function is called in an `||` context, where
# bash ignores `set -e` no matter what is set inside.
do_scan() {
    UV_BIN=${UV_BIN:-$(type -p uv 2>/dev/null || echo "$HOME/.local/bin/uv")}
    DETECT_SECRETS_SPEC=${DETECT_SECRETS_SPEC:-git+https://github.com/ibm/detect-secrets.git@076672a9a01abdfc7ecee2e7d14f08cdccb73976}
    DETECT_SECRETS_FILES_EXCLUDE=${DETECT_SECRETS_FILES_EXCLUDE:-'(?x)( package-lock\.json$ |Cargo\.lock$ |uv\.lock$ |go\.sum$ |mcpgateway/sri_hashes\.json$ )|^\.secrets\.baseline$'}
    # Scan scope: files the branch changes relative to its upstream, mirroring
    # the Makefile's `git diff $(GIT_DIFF_TARGET)`. Unlike the merge driver,
    # this hook cannot read the rebase state dir: git removes it before
    # post-rewrite runs, and by then the working tree IS the final tree, so
    # the plain upstream diff the Makefile uses is both available and exact.
    # An explicit GIT_DIFF_TARGET is used as-is; otherwise probe for the
    # repository's root/default branch: local main/master/develop, then the
    # remote's default (origin/HEAD), then origin/main/master/develop. When
    # nothing matches (e.g. CI fetching only the PR ref) leave
    # DETECT_SECRETS_PATH empty: detect-secrets with no path arguments scans
    # the whole tree.
    # --diff-filter=d excludes deleted files.
    # Word-splitting of $DETECT_SECRETS_PATH is intentional (mirrors the Makefile).
    if [ -z "${GIT_DIFF_TARGET:-}" ]; then
        GIT_DIFF_TARGET=
        for b in main master develop; do
            if git rev-parse --verify -q "$b" >/dev/null 2>&1; then
                GIT_DIFF_TARGET=$b
                break
            fi
        done
        if [ -z "$GIT_DIFF_TARGET" ]; then
            origin_head=$(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null) || origin_head=
            if [ -n "$origin_head" ] && git rev-parse --verify -q "$origin_head" >/dev/null 2>&1; then
                GIT_DIFF_TARGET=$origin_head
            fi
        fi
        if [ -z "$GIT_DIFF_TARGET" ]; then
            for b in origin/main origin/master origin/develop; do
                if git rev-parse --verify -q "$b" >/dev/null 2>&1; then
                    GIT_DIFF_TARGET=$b
                    break
                fi
            done
        fi
        if [ -z "$GIT_DIFF_TARGET" ]; then
            echo "⚠️  no main/master/develop branch or origin HEAD ref; scanning the whole tree" >&2
        fi
    fi
    if [ -n "${GIT_DIFF_TARGET:-}" ]; then
        DETECT_SECRETS_PATH=${DETECT_SECRETS_PATH:-$(git diff "$GIT_DIFF_TARGET" --name-only --diff-filter=d)} || return
    else
        DETECT_SECRETS_PATH=${DETECT_SECRETS_PATH:-}
    fi

    cp .secrets.baseline "$tmpfile" || return
    # shellcheck disable=SC2086
    "$UV_BIN" tool run --from "$DETECT_SECRETS_SPEC" detect-secrets scan \
        --update "$tmpfile" \
        --use-all-plugins \
        --exclude-files "$DETECT_SECRETS_FILES_EXCLUDE" \
        $DETECT_SECRETS_PATH || return

    # Merge: keep worktree-baseline entries for files git no longer tracks,
    # take freshly scanned results for everything else. INDEX(.) builds an
    # exact-membership set of tracked filenames (the old inside() used
    # substring semantics); see the driver for the line-by-line walkthrough.
    jq --arg exclude "$DETECT_SECRETS_FILES_EXCLUDE" -s '
        (.[2] | INDEX(.)) as $gitfileset |
        {
        exclude: { files: $exclude, lines: null },
        generated_at: .[1].generated_at,
        plugins_used: .[1].plugins_used,
        results: (
            (.[0].results | to_entries | [ .[]|select($gitfileset[.key]) ] | from_entries)
            + .[1].results),
        version: .[1].version,
        word_list: .[1].word_list
        }' \
        .secrets.baseline "$tmpfile" \
        <(git ls-files | jq -R -s 'split("\n")[:-1]') \
        > "$outfile" || return
    cp "$outfile" .secrets.baseline || return

    echo "📊 detect-secrets findings report:" >&2
    "$UV_BIN" tool run --from "$DETECT_SECRETS_SPEC" detect-secrets audit --report .secrets.baseline || return
    count=$("$UV_BIN" tool run --from "$DETECT_SECRETS_SPEC" detect-secrets audit --report --json .secrets.baseline \
        | jq -r '.stats | .live + .unaudited + .audited_real') || count=""
    case "$count" in
        ''|*[!0-9]*)
            echo "⚠️  could not read audit stats from refreshed baseline (got '${count}')" >&2
            return 1
            ;;
    esac
    [ "$count" -eq 0 ]
}

refresh_secrets_baseline() {
    # Only rebase can leave the baseline stale; amend is covered by the
    # pre-commit detect-secrets hook.
    [ "${1:-}" = "rebase" ] || return 0

    [ -f .secrets.baseline ] || return 0

    if ! command -v jq >/dev/null 2>&1; then
        echo "⚠️  jq not found; install jq (e.g. 'brew install jq' or 'apt-get install jq') — skipping .secrets.baseline refresh" >&2
        return 0
    fi

    echo "🔄 post-rebase: refreshing .secrets.baseline..." >&2

    local tmpfile outfile
    tmpfile=$(mktemp) || return 0
    outfile=$(mktemp) || { rm -f "$tmpfile"; return 0; }

    # Any failure — scan error or unaudited findings — downgrades to a
    # warning instead of failing the hook.
    if ! do_scan; then
        rm -f "$tmpfile" "$outfile"
        echo "⚠️  detect-secrets refresh failed or reported unaudited findings; review .secrets.baseline manually (make detect-secrets-audit)" >&2
        return 0
    fi
    rm -f "$tmpfile" "$outfile"

    if git diff --quiet -- .secrets.baseline; then
        echo "✅ .secrets.baseline already up to date" >&2
        return 0
    fi

    # generated_at changes on every scan; only stage substantive changes.
    if git cat-file -e HEAD:.secrets.baseline 2>/dev/null && \
       diff <(git show HEAD:.secrets.baseline | jq -S 'del(.generated_at)') \
            <(jq -S 'del(.generated_at)' .secrets.baseline) > /dev/null; then
        git checkout -- .secrets.baseline
        echo "✅ .secrets.baseline already up to date (timestamp only)" >&2
        return 0
    fi

    git add .secrets.baseline
    echo "✅ .secrets.baseline refreshed" >&2
}

# A post-rewrite hook must never fail the rebase; downgrade all failures
# (ours and the chain's) to warnings.
refresh_secrets_baseline "$@" || echo "⚠️  post-rewrite secrets refresh errored; review .secrets.baseline manually" >&2

if [ -x "$chain_hook" ]; then
    echo "➡️  Handing off to chained post-rewrite hook: $chain_hook" >&2
    "$chain_hook" "$@" < "$stdin_copy" || echo "⚠️  chained post-rewrite hook exited $?" >&2
fi

exit 0
