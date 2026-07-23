#!/usr/bin/env bash
# Git merge driver for .secrets.baseline
#
# Invoked by git as: resolve-secrets-baseline-conflict.sh %O %A %B %P
#   %O - ancestor (base) version (temp file)
#   %A - current version (temp file); the driver MUST write the result here
#   %B - incoming version (temp file)
#   %P - path of the conflicted file
#
# Strategy: ignore both candidates and regenerate the baseline from the
# working tree, writing the fresh baseline directly into %A. Exit 0 tells
# git to accept %A as the merged content; any failure (including unaudited
# findings in the regenerated baseline) exits non-zero and git leaves the
# conflict for manual resolution.
#
# This script is a self-contained port of the Makefile's detect-secrets-scan
# target. It must NOT invoke make: the driver is installed outside the
# worktree (see `make configure-secrets-merge-driver`, which copies it to
# <git-common-dir>/git-drivers/) and runs against whatever tree a rebase has
# checked out, including history whose Makefile predates, differs from, or
# ignores the knobs the driver would need (e.g. OUTPUT_TARGET). Keep the
# defaults below in sync with DETECT_SECRETS_* in the Makefile.

set -euo pipefail

output=${2:?"usage: $0 %O %A %B %P (invoked by git as a merge driver)"}

UV_BIN=${UV_BIN:-$(type -p uv 2>/dev/null || echo "$HOME/.local/bin/uv")}
DETECT_SECRETS_SPEC=${DETECT_SECRETS_SPEC:-git+https://github.com/ibm/detect-secrets.git@076672a9a01abdfc7ecee2e7d14f08cdccb73976}
DETECT_SECRETS_FILES_EXCLUDE=${DETECT_SECRETS_FILES_EXCLUDE:-'(?x)( package-lock\.json$ |Cargo\.lock$ |uv\.lock$ |go\.sum$ |mcpgateway/sri_hashes\.json$ )|^.secrets.baseline$'}
# Scan scope: files the branch changes relative to its upstream, mirroring
# the Makefile's `git diff $(GIT_DIFF_TARGET)`. During a rebase, both
# endpoints are recorded in the state dir (onto = upstream tip, orig-head =
# branch tip at rebase start), so the scope is computed commit-to-commit as
# merge-base(onto, orig-head)..orig-head — the branch's full changeset with
# three-dot semantics (upstream-side changes excluded). This is identical
# regardless of which pick conflicts, unlike a working-tree diff that grows
# as picks replay. Plumbing (git diff-tree) keeps output immune to user
# config (diff.renames, external diff drivers). Interactive rebases that
# drop commits yield a slight superset; harmless, as the jq merge below
# intersects results with `git ls-files`.
# During a merge, diff the working tree against merge-base(HEAD, MERGE_HEAD),
# deliberately covering both sides' changes.
# --diff-filter=d excludes deleted files.
# Word-splitting of $DETECT_SECRETS_PATH is intentional (mirrors the Makefile).
git_dir=$(git rev-parse --git-dir)
state_dir=
for d in rebase-merge rebase-apply; do
    if [ -f "$git_dir/$d/onto" ] && [ -f "$git_dir/$d/orig-head" ]; then
        state_dir=$d
        break
    fi
done
if [ -n "$state_dir" ]; then
    onto=$(cat "$git_dir/$state_dir/onto")
    orig=$(cat "$git_dir/$state_dir/orig-head")
    merge_base=$(git merge-base "$onto" "$orig")
    DETECT_SECRETS_PATH=$(git diff-tree -r --name-only --diff-filter=d "$merge_base" "$orig")
elif [ -f "$git_dir/MERGE_HEAD" ]; then
    DETECT_SECRETS_PATH=$(git diff "$(git merge-base HEAD MERGE_HEAD)" --name-only --diff-filter=d)
else
    DETECT_SECRETS_PATH=$(git diff "${GIT_DIFF_TARGET:-main}" --name-only --diff-filter=d)
fi

echo "🔀 Regenerating .secrets.baseline via detect-secrets-scan..."

tmpfile=$(mktemp)
outfile=$(mktemp)
trap 'rm -f "$tmpfile" "$outfile"' EXIT

# While the driver runs, the worktree .secrets.baseline holds the "ours"
# (stage 2) content — clean JSON, safe to seed the --update scan from.
cp .secrets.baseline "$tmpfile"
# shellcheck disable=SC2086
"$UV_BIN" tool run --from "$DETECT_SECRETS_SPEC" detect-secrets scan \
    --update "$tmpfile" \
    --use-all-plugins \
    --exclude-files "$DETECT_SECRETS_FILES_EXCLUDE" \
    $DETECT_SECRETS_PATH

# Merge: keep worktree-baseline entries for files git no longer tracks,
# take freshly scanned results for everything else.
jq --arg exclude "$DETECT_SECRETS_FILES_EXCLUDE" -s '
    .[2] as $gitfiles |
    {
    exclude: { files: $exclude, lines: null },
    generated_at: .[1].generated_at,
    plugins_used: .[1].plugins_used,
    results: (
        (.[0].results | to_entries | [ .[]|select( ([.key] | inside($gitfiles))) ] | from_entries)
        + .[1].results),
    version: .[1].version,
    word_list: .[1].word_list
    }' \
    .secrets.baseline "$tmpfile" \
    <(git ls-files | jq -R -s 'split("\n")[:-1]') \
    > "$outfile"
cp "$outfile" "$output"

echo "📊 detect-secrets findings report:"
"$UV_BIN" tool run --from "$DETECT_SECRETS_SPEC" detect-secrets audit --report "$output"
count=$("$UV_BIN" tool run --from "$DETECT_SECRETS_SPEC" detect-secrets audit --report --json "$output" \
    | jq -r '.stats | .live + .unaudited + .audited_real')
if [ "$count" -gt 0 ]; then
    echo "❌ $count unaudited/live finding(s) in regenerated baseline; leaving conflict for manual resolution (run 'make detect-secrets-audit')" >&2
    exit 1
fi

echo "✅ .secrets.baseline regenerated as merge result"
