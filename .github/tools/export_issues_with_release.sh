#!/usr/bin/env bash
#
# export_issues_with_release.sh
# -----------------------------
# Export all issues from a GitHub repository to CSV, including
# the milestone (treated as the "release") name & description.
#
# Prerequisites
#   - GitHub CLI (`gh`) logged-in with repo read scope
#   - jq 1.6+
#
# Usage
#   ./export_issues_with_release.sh [output.csv]
#
# Environment overrides
#   REPO   - target repo in OWNER/NAME form (default: current directory's repo)
#   STATE  - issue states to include: open|closed|all  (default: all)
#   LIMIT  - max issues to fetch (default: 9999)
#
# Example
#   ./export_issues_with_release.sh /tmp/issues.csv
#

set -euo pipefail

### Config --------------------------------------------------------------------
OUTPUT="${1:-issues.csv}"
STATE="${STATE:-all}"      # open|closed|all
LIMIT="${LIMIT:-9999}"
REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

### Fetch & transform ---------------------------------------------------------
echo "📦 Exporting issues for $REPO  (state=$STATE, limit=$LIMIT) ..."

gh issue list --repo "$REPO"                           \
              --state "$STATE" --limit "$LIMIT"        \
              --json number,title,state,milestone      \
              --jq '
                # ---- emit CSV header first
                (["issue_number","title","state","release","release_description"] | @csv),
                # ---- then one CSV row per issue
                (.[] |
                  [ .number,
                    (.title | gsub("\n"; " ") ),      # strip line-breaks
                    .state,
                    ( .milestone.title // "" ),
                    ( .milestone.description // "" | gsub("\r?\n"; " ") )
                  ] | @csv)
              ' > "$OUTPUT"

echo "✅  Wrote $(wc -l <"$OUTPUT") lines to $OUTPUT"
