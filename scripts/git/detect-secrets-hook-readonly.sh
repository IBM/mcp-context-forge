#!/usr/bin/env bash
# Run detect-secrets-hook against a temporary copy of .secrets.baseline.
#
# Fail only when a secret is detected (new, verified-unaudited or unaudited).
# Baseline-only changes (line_number, removed secrets, version, generated_at)
# are ignored: the hook rewrites the temporary copy, never the real baseline.
set -uo pipefail

BASELINE="${DETECT_SECRETS_BASELINE:-.secrets.baseline}"
TMP_BASELINE="$(mktemp)"
trap 'rm -f "$TMP_BASELINE"' EXIT

run_hook() {
  detect-secrets-hook --baseline "$TMP_BASELINE" --use-all-plugins --fail-on-unaudited "$@"
}

cp "$BASELINE" "$TMP_BASELINE"

err="$(mktemp)"
trap 'rm -f "$TMP_BASELINE" "$err"' EXIT

run_hook "$@" 2>"$err"
status=$?

# Exit 3 means no new secrets were found, but the hook rewrote the temporary
# baseline (line numbers, removed secrets or version). Not a secret detection:
# rerun on the synced copy to get the real result (e.g. unaudited secrets).
if [ "$status" -eq 3 ]; then
  run_hook "$@"
  status=$?
else
  cat "$err" >&2
fi

exit "$status"
