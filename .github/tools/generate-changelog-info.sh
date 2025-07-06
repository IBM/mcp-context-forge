#!/usr/bin/env bash
#
# generate-changelog-info.sh
# Author: Mihai Criveti
#
# Dump to one file:
#   1. Full commit logs since a tag
#   2. A chronologically-sorted list of issues closed since that tag
#   3. Full JSON-formatted details for every one of those issues
#
# Dependencies: git, GitHub CLI (`gh`), jq
# Usage:        ./generate-changelog-info.sh [TAG] [OUTPUT_FILE]
#               TAG defaults to v0.1.1
#               OUTPUT_FILE defaults to changelog_info.txt
#
set -euo pipefail

TAG=${1:-v0.1.1}
OUT=${2:-changelog_info.txt}

###############################################################################
# 1.  Commit log
###############################################################################
{
  echo "#############################"
  echo "## COMMITS since ${TAG}"
  echo "#############################"
} >"$OUT"

git log "${TAG}"..HEAD --reverse --no-merges \
  --pretty=format:'%H%nAuthor: %an <%ae>%nDate:   %ad%n%n%s%n%n%b%n----' \
  --date=short >>"$OUT"

###############################################################################
# 2.  Closed-issue list (oldest → newest)
###############################################################################
CUTOFF=$(git log -1 --format=%cI "$TAG")   # ISO time of the tag

echo -e "\n#############################" >>"$OUT"
echo   "## ISSUES closed since ${TAG}"  >>"$OUT"
echo   "#############################" >>"$OUT"

ISSUES_JSON=$(gh issue list --state closed \
  --search "closed:>=$CUTOFF" \
  --limit 1000 \
  --json number,title,closedAt,url)

echo "$ISSUES_JSON" | jq -r '
  sort_by(.closedAt)[]
  | "#\(.number) - \(.title) (closed: \(.closedAt))"
' >>"$OUT"

###############################################################################
# 3.  Full issue details
###############################################################################
echo -e "\n#############################" >>"$OUT"
echo   "## ISSUE DETAILS"              >>"$OUT"
echo   "#############################" >>"$OUT"

# Extract the numbers, then loop for detailed views
echo "$ISSUES_JSON" | jq -r '.[].number' | while read -r NUM; do
  echo -e "\n---- ISSUE #$NUM ----" >>"$OUT"
  gh issue view "$NUM" --json number,title,author,labels,assignees,closedAt,createdAt,url,body \
    | jq -r '
        "Number: \(.number)",
        "Title:  \(.title)",
        "URL:    \(.url)",
        "Author: \(.author.login // "unknown")",
        "Labels: \(.labels | map(.name) | join(", "))",
        "Assignees: \(.assignees | map(.login) | join(", "))",
        "Created: \(.createdAt)",
        "Closed:  \(.closedAt)",
        "",
        "Body:\n" + (.body // "*No description*")
      ' >>"$OUT"
done

echo -e "\nAll done!  Results written to: $OUT"
