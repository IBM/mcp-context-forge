#!/usr/bin/env bash
# Refresh A2A invoke baseline from the fixed legacy-main commit (b4d8770). Runs
# benchmarks on that commit so the baseline is from Python-path-only code; then
# restores the baseline file on the current branch. Ensures delay consistency
# (same benchmark code and A2A_BENCH_SEED). Must match A2A_INVOKE_MAIN_BASELINE_COMMIT
# in test_a2a_invoke_benchmark.py.
#
# Usage: from your feature branch, run:
#   ./benchmarks/refresh_a2a_baseline_from_main.sh
#
# Then commit the updated baseline:
#   git add benchmarks/a2a_invoke_baseline_main.json
#   git commit -s -m "chore: refresh A2A invoke baseline from main"

set -euo pipefail

# Fixed legacy main commit we compare against (must match test_a2a_invoke_benchmark.py)
BASELINE_COMMIT="b4d87709421ca2b0aab648ad145ecc50bd316433"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git branch --show-current)"
if [[ -z "$BRANCH" ]]; then
  echo "Not on a branch (detached HEAD?). Abort." >&2
  exit 1
fi

echo "Current branch: $BRANCH"
echo "Stashing all local changes so checkout can succeed..."
git stash push -u -m "a2a-baseline-refresh" 2>/dev/null || true

echo "Checking out baseline commit $BASELINE_COMMIT (legacy main)..."
git checkout "$BASELINE_COMMIT"

echo "Reinstalling package so gateway code is from this commit..."
uv sync

echo "Bringing A2A benchmark code from $BRANCH..."
git checkout "$BRANCH" -- benchmarks/test_a2a_invoke_benchmark.py benchmarks/conftest.py

echo "Running full A2A invoke benchmark on legacy main (SAVE_A2A_INVOKE_BASELINE=1)..."
echo "This may take several minutes (includes slow scenarios)."
SAVE_A2A_INVOKE_BASELINE=1 uv run --active --extra fuzz pytest benchmarks/test_a2a_invoke_benchmark.py -v --benchmark-only --benchmark-min-rounds=2

BASELINE="benchmarks/a2a_invoke_baseline_main.json"
if [[ ! -f "$BASELINE" ]]; then
  echo "Baseline file was not created. Abort." >&2
  git checkout "$BRANCH"
  git stash pop 2>/dev/null || true
  exit 1
fi

cp "$BASELINE" /tmp/a2a_invoke_baseline_main.json
echo "Baseline saved to /tmp/a2a_invoke_baseline_main.json"

echo "Checking out $BRANCH..."
git checkout "$BRANCH"

cp /tmp/a2a_invoke_baseline_main.json "$BASELINE"
echo "Copied new baseline into $BASELINE on branch."

git stash pop 2>/dev/null || true

echo "Done. Baseline from $BASELINE_COMMIT (legacy main) is now in $BASELINE."
echo "Commit it: git add $BASELINE && git commit -s -m \"chore: refresh A2A invoke baseline from main\""
