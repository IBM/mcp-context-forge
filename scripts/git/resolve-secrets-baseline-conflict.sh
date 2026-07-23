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
# This script is the single implementation of the scan/merge/gate pipeline:
# the Makefile's detect-secrets-scan target is a thin wrapper that execs this
# script. It must NOT invoke make: the driver is installed outside the
# worktree (see `make configure-secrets-merge-driver`, which copies it to
# <git-common-dir>/git-drivers/) and runs against whatever tree a rebase has
# checked out, including history whose Makefile predates, differs from, or
# ignores the knobs the driver would need. Keep the defaults below in sync
# with DETECT_SECRETS_* in the Makefile.

set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
    echo "❌ jq not found; install jq (e.g. 'brew install jq' or 'apt-get install jq') — required by the .secrets.baseline merge driver" >&2
    exit 1
fi

output=${2:?"usage: $0 %O %A %B %P (invoked by git as a merge driver)"}

UV_BIN=${UV_BIN:-$(type -p uv 2>/dev/null || echo "$HOME/.local/bin/uv")}
DETECT_SECRETS_SPEC=${DETECT_SECRETS_SPEC:-git+https://github.com/ibm/detect-secrets.git@076672a9a01abdfc7ecee2e7d14f08cdccb73976}
DETECT_SECRETS_FILES_EXCLUDE=${DETECT_SECRETS_FILES_EXCLUDE:-'(?x)( package-lock\.json$ |Cargo\.lock$ |uv\.lock$ |go\.sum$ |mcpgateway/sri_hashes\.json$ )|^\.secrets\.baseline$'}
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
    # Fresh clones may lack a local main; fall back to origin/main. An
    # explicit DETECT_SECRETS_PATH (e.g. from the Makefile wrapper) wins.
    if [ -z "${GIT_DIFF_TARGET:-}" ]; then
        if git rev-parse --verify -q main >/dev/null 2>&1; then
            GIT_DIFF_TARGET=main
        else
            GIT_DIFF_TARGET=origin/main
        fi
    fi
    DETECT_SECRETS_PATH=${DETECT_SECRETS_PATH:-$(git diff "$GIT_DIFF_TARGET" --name-only --diff-filter=d)}
fi

echo "🔀 Regenerating .secrets.baseline via detect-secrets-scan..." >&2

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
#
#  There's some serious jq magic going on here, so we dig through it
#  line-by-line.
#
#  Note first that 'jq -s' slurps the three inputs into a single array:
#  .[0]  The original .secrets.baseline
#  .[1]  Our new .secrets.baseline (containing only the branch-altered files)
#  .[2]  An array of all the files in the repository.
#
#  (.[2] | INDEX(.)) as $gitfileset
#  ^ builds an object keyed by exact tracked filename, so membership tests
#    below are exact (the old `inside($gitfiles)` used substring semantics:
#    a tracked config.py.bak would keep stale config.py entries alive)
#
#  (.[0].results | to_entries | [ .[]|select($gitfileset[.key]) ] | from_entries)
#  ^ filters the original file to only include entries that are still in the
#    repository, essentially removing any files that have been deleted over time
#
#  + .[1].results
#  ^ merges in the results of the current baseline, overwriting changed line
#    numbers, etc.
#
#  <(git ls-files | jq -R -s 'split("\n")[:-1]')
#  ^ gets the current git files and transforms them into an array (the [:-1]
#    drops the empty element produced by the trailing newline). <() allows the
#    output to be passed like a file reference into jq
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
    > "$outfile"
cp "$outfile" "$output"

# One-line delta summary vs %A (the worktree .secrets.baseline holds the
# stage-2/ours content, i.e. the original %A, while the driver runs).
before_count=$(jq '[.results[] | length] | add // 0' .secrets.baseline)
after_count=$(jq '[.results[] | length] | add // 0' "$output")
added=0; dropped=0
if [ "$after_count" -gt "$before_count" ]; then added=$((after_count - before_count)); fi
if [ "$before_count" -gt "$after_count" ]; then dropped=$((before_count - after_count)); fi
echo "📊 baseline entries vs %A: +${added} / -${dropped}" >&2

# Fail-closed verdict preservation: no entry that %B audited as a real
# secret may vanish from the merged output. Identity is hashed_secret
# under the same file key — line numbers shift across rebases.
base_file=${3:-}
if [ -n "$base_file" ] && [ "$base_file" != "-" ] && [ -s "$base_file" ]; then
    if jq -e . "$base_file" >/dev/null 2>&1; then
        lost=$(jq -r --slurpfile merged "$output" '
            ($merged[0].results // {}) as $m |
            (.results // {}) | to_entries[] |
            .key as $file | .value[] |
            select(.is_secret == true) |
            . as $entry |
            select(([$m[$file][]?.hashed_secret] | index($entry.hashed_secret)) == null) |
            "  \($file): line \($entry.line_number) (hashed_secret \($entry.hashed_secret))"' \
            "$base_file")
        if [ -n "$lost" ]; then
            echo "❌ %B verdict(s) audited as real would be lost in the merged baseline:" >&2
            echo "$lost" >&2
            echo "   Leaving the conflict for manual resolution; re-mark these entries after resolving." >&2
            exit 1
        fi
    else
        echo "⚠️  could not parse %B ($base_file) as JSON; skipping verdict-preservation check" >&2
    fi
else
    echo "ℹ️  no usable %B provided ('${base_file:-<none>}'); skipping verdict-preservation check" >&2
fi

echo "📊 detect-secrets findings report:" >&2
"$UV_BIN" tool run --from "$DETECT_SECRETS_SPEC" detect-secrets audit --report "$output"
count=$("$UV_BIN" tool run --from "$DETECT_SECRETS_SPEC" detect-secrets audit --report --json "$output" \
    | jq -r '.stats | .live + .unaudited + .audited_real') || count=""
case "$count" in
    ''|*[!0-9]*)
        echo "❌ could not read audit stats from regenerated baseline (got '${count}'); leaving conflict for manual resolution" >&2
        exit 1
        ;;
esac
if [ "$count" -gt 0 ]; then
    echo "❌ $count unaudited/live finding(s) in regenerated baseline; leaving conflict for manual resolution (run 'make detect-secrets-audit')" >&2
    exit 1
fi

echo "✅ .secrets.baseline regenerated as merge result" >&2
