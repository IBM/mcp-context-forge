#!/usr/bin/env bash
#───────────────────────────────────────────────────────────────────────────────
#  Script : cleanup-ghcr-versions.sh
#  Author : Mihai Criveti
#  Purpose: Prune old or unused GHCR container versions for IBM's ContextForge
#  Copyright 2025
#  SPDX-License-Identifier: Apache-2.0
#
#  Description:
#    This script safely manages container versions in GitHub Container Registry
#    (ghcr.io) under the IBM organization, specifically targeting the
#    `mcp-context-forge` package. It supports interactive and non-interactive
#    deletion modes to help you keep the container registry clean.
#
#    Features:
#    - Dry-run by default to avoid accidental deletion
#    - Pattern-based tag protection (latest, v*, semver)
#    - Age-based retention (keep images younger than N days)
#    - Month-based filtering for incremental cleanup
#    - Max delete limit for testing
#    - GitHub CLI integration with scope validation
#    - CI/CD-compatible via environment overrides
#
#  Requirements:
#    - GitHub CLI (gh) v2.x with appropriate scopes
#    - jq (command-line JSON processor)
#
#  Required Token Scopes:
#    delete:packages
#
#  Authentication Notes:
#    Authenticate with:
#      gh auth refresh -h github.com -s read:packages,delete:packages
#    Or:
#      gh auth logout
#      gh auth login --scopes "read:packages,delete:packages,write:packages,repo,read:org,gist"
#
#    Verify authentication with:
#      gh auth status -t
#
#  Environment Variables:
#    GITHUB_TOKEN / GH_TOKEN : GitHub token with required scopes
#    DRY_RUN                 : Set to "false" to enable actual deletions (default: true)
#    KEEP_DAYS               : Keep images younger than N days (default: 7)
#    MONTH                   : Only process images from this month, e.g. "2025-06" (default: all)
#    MAX_DELETE              : Stop after deleting N images (default: unlimited)
#    ORG                     : GitHub org (default: ibm)
#    PKG                     : Package name (default: mcp-context-forge)
#
#  Usage:
#    ./cleanup-ghcr-versions.sh                          # Dry-run, all months
#    MONTH=2025-06 ./cleanup-ghcr-versions.sh            # Dry-run, June 2025 only
#    MONTH=2025-06 MAX_DELETE=10 DRY_RUN=false ./cleanup-ghcr-versions.sh --yes
#    KEEP_DAYS=14 ./cleanup-ghcr-versions.sh             # Keep 14 days
#
#───────────────────────────────────────────────────────────────────────────────

set -euo pipefail

##############################################################################
# 1. PICK A TOKEN
##############################################################################
NEEDED_SCOPES="delete:packages"

if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  TOKEN="$GITHUB_TOKEN"
elif [[ -n "${GH_TOKEN:-}" ]]; then
  TOKEN="$GH_TOKEN"
else
  # fall back to whatever gh already has
  if ! TOKEN=$(gh auth token 2>/dev/null); then
    echo "No token exported and gh not logged in. Fix with:"
    echo "    gh auth login  (or export GITHUB_TOKEN)"
    exit 1
  fi
fi
export GH_TOKEN="$TOKEN"   # gh api uses this

# Scope checking (best-effort, not all token types expose scopes)
if scopes=$(gh auth status --show-token 2>/dev/null | grep -oP 'Token scopes: \K.*' || echo ""); then
  if [[ -n "$scopes" ]] && ! echo "$scopes" | grep -q "delete:packages"; then
    echo "WARNING: Token scopes [$scopes] may be missing delete:packages"
    echo "    Run: gh auth refresh -h github.com -s $NEEDED_SCOPES"
    exit 1
  fi
fi

##############################################################################
# 2. CONFIG
##############################################################################
ORG="${ORG:-ibm}"
PKG="${PKG:-mcp-context-forge}"
KEEP_DAYS="${KEEP_DAYS:-7}"
MONTH="${MONTH:-}"              # e.g. "2025-06" — empty means all months
MAX_DELETE="${MAX_DELETE:-0}"    # 0 = unlimited
PER_PAGE=100

DRY_RUN="${DRY_RUN:-true}"          # default safe
ASK_CONFIRM=true
[[ "${1:-}" == "--yes" ]] && ASK_CONFIRM=false

# Pattern-based protection: keep latest, any semver tag (v*), and explicit versions
# This regex matches tags to PROTECT from deletion
KEEP_REGEX="^(latest|v[0-9].*|[0-9]+\.[0-9]+\.[0-9]+.*)$"

# Age-based cutoff
CUTOFF=$(date -u -d "${KEEP_DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || \
         date -u -v-${KEEP_DAYS}d +%Y-%m-%dT%H:%M:%SZ)  # Linux || macOS

##############################################################################
# 3. SCAN
##############################################################################
delete_ids=()
kept=0
skipped_recent=0
skipped_month=0

echo "Scanning ghcr.io/${ORG}/${PKG} ..."
echo "  Protect pattern: ${KEEP_REGEX}"
echo "  Keep images newer than: ${KEEP_DAYS} days (cutoff: ${CUTOFF})"
[[ -n "$MONTH" ]] && echo "  Month filter: ${MONTH}"
[[ "$MAX_DELETE" -gt 0 ]] 2>/dev/null && echo "  Max deletions: ${MAX_DELETE}"
echo "  Dry run: ${DRY_RUN}"
echo ""

while IFS= read -r row; do
  id=$(jq -r '.id' <<<"$row")
  updated=$(jq -r '.updated' <<<"$row")
  tags_csv=$(jq -r '.tags | join(",")' <<<"$row")

  # Check if any tag matches the protection pattern
  keep=$(jq -e --arg re "$KEEP_REGEX" 'any(.tags[]?; test($re))' <<<"$row" 2>/dev/null) || keep=false

  if [[ "$keep" == "true" ]]; then
    printf "  KEEP (protected tag)  id=%-12s  [%s]\n" "$id" "$tags_csv"
    kept=$((kept + 1))
    continue
  fi

  # Check age — keep images newer than cutoff
  if [[ "$updated" > "$CUTOFF" ]]; then
    printf "  KEEP (recent)         id=%-12s  [%s]  updated=%s\n" "$id" "$tags_csv" "$updated"
    skipped_recent=$((skipped_recent + 1))
    continue
  fi

  # Month filter — skip images outside the requested month
  if [[ -n "$MONTH" ]]; then
    image_month="${updated:0:7}"  # extract YYYY-MM from YYYY-MM-DDT...
    if [[ "$image_month" != "$MONTH" ]]; then
      skipped_month=$((skipped_month + 1))
      continue
    fi
  fi

  # Check max delete limit
  if [[ "$MAX_DELETE" -gt 0 ]] && [[ ${#delete_ids[@]} -ge "$MAX_DELETE" ]]; then
    break
  fi

  # Mark for deletion
  printf "  DELETE                id=%-12s  [%s]  updated=%s\n" "$id" "$tags_csv" "$updated"
  delete_ids+=("$id")
done < <(gh api -H "Accept: application/vnd.github+json" \
            "/orgs/${ORG}/packages/container/${PKG}/versions?per_page=${PER_PAGE}" \
            --paginate | \
         jq -cr '
           .[] |
           {
             id,
             updated: .updated_at,
             tags: (.metadata.container.tags // [])
           }
         ')

##############################################################################
# 4. SUMMARY
##############################################################################
echo ""
if [[ -n "$MONTH" ]]; then
  echo "Summary for ${MONTH}: ${#delete_ids[@]} to delete"
  echo "  Scanned: ${kept} protected, ${skipped_recent} recent, ${skipped_month} outside ${MONTH}"
else
  echo "Summary: ${#delete_ids[@]} to delete, ${kept} protected, ${skipped_recent} recent"
fi
[[ "$MAX_DELETE" -gt 0 ]] 2>/dev/null && echo "  (capped at MAX_DELETE=${MAX_DELETE})"

if [[ ${#delete_ids[@]} -eq 0 ]]; then
  echo "Nothing to delete."
  exit 0
fi

##############################################################################
# 5. CONFIRMATION & DELETION
##############################################################################
if [[ "$DRY_RUN" == "true" ]]; then
  echo ""
  echo "DRY RUN — no images were deleted."
  if [[ "$ASK_CONFIRM" == "true" ]]; then
    echo "Re-run with DRY_RUN=false to actually delete."
  fi
  exit 0
fi

# In destructive mode, optionally ask for confirmation
if [[ "$ASK_CONFIRM" == "true" ]]; then
  echo ""
  read -rp "Proceed to delete ${#delete_ids[@]} versions? (y/N) " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

# GitHub secondary rate limits: 900 points/min, DELETE = 5 points each
# = 180 DELETEs/min max. We do waves of 30 + 10s pause = ~120/min (safe).
WAVE_SIZE=30
WAVE_PAUSE=10

echo ""
echo "Deleting ${#delete_ids[@]} versions in waves of ${WAVE_SIZE}..."
deleted=0
failed=0
wave_count=0

for id in "${delete_ids[@]}"; do
  if gh api -X DELETE -H "Accept: application/vnd.github+json" \
            "/orgs/${ORG}/packages/container/${PKG}/versions/${id}" >/dev/null 2>&1; then
    echo "  Deleted: ${id}"
    deleted=$((deleted + 1))
  else
    echo "  FAILED:  ${id}"
    failed=$((failed + 1))
  fi

  wave_count=$((wave_count + 1))
  if [[ $wave_count -ge $WAVE_SIZE ]]; then
    remaining=$(( ${#delete_ids[@]} - deleted - failed ))
    if [[ $remaining -gt 0 ]]; then
      echo "  -- wave complete, pausing ${WAVE_PAUSE}s (${remaining} remaining) --"
      sleep "$WAVE_PAUSE"
    fi
    wave_count=0
  fi
done

echo ""
echo "Done. Deleted: ${deleted}, Failed: ${failed}"
[[ "$failed" -eq 0 ]] || exit 1
