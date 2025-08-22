#!/usr/bin/env bash
#───────────────────────────────────────────────────────────────────────────────
#  Script : cleanup.sh
#  Author : Mihai Criveti
#  Purpose: Prune old or unused GHCR container versions for IBM's MCP Context Forge
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
#    - Tag whitelisting with regular expression matching
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
#
#  Usage:
#    ./cleanup.sh                 # Dry-run with confirmation prompt
#    DRY_RUN=false ./cleanup.sh --yes  # Actual deletion without prompt (for CI)
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
    echo "❌  No token exported and gh not logged in. Fix with:"
    echo "    gh auth login  (or export GITHUB_TOKEN)"
    exit 1
  fi
fi
export GH_TOKEN="$TOKEN"   # gh api uses this

# Fixed scope checking - check for both required scopes individually
if scopes=$(gh auth status --show-token 2>/dev/null | grep -oP 'Token scopes: \K.*' || echo ""); then
  missing_scopes=()

  # if ! echo "$scopes" | grep -q "read:packages"; then
  #   missing_scopes+=("read:packages")
  # fi

  if ! echo "$scopes" | grep -q "delete:packages"; then
    missing_scopes+=("delete:packages")
  fi

  if [[ ${#missing_scopes[@]} -gt 0 ]]; then
    echo "⚠️  Your token scopes are [$scopes] - but you're missing: [$(IFS=','; echo "${missing_scopes[*]}")]"
    echo "    Run: gh auth refresh -h github.com -s $NEEDED_SCOPES"
    exit 1
  fi
else
  echo "⚠️  Could not verify token scopes. Proceeding anyway..."
fi

##############################################################################
# 2. CONFIG
##############################################################################
ORG="ibm"
PKG="mcp-context-forge"
KEEP_TAGS=( "0.1.0" "v0.1.0" "0.1.1" "v0.1.1" "0.2.0" "v0.2.0" "0.3.0" "v0.3.0" "0.4.0" "v0.4.0" "0.5.0" "v0.5.0" "0.6.0" "v0.6.0" "latest" )
PER_PAGE=100

DRY_RUN=${DRY_RUN:-true}          # default safe
ASK_CONFIRM=true
[[ ${1:-} == "--yes" ]] && ASK_CONFIRM=false
KEEP_REGEX="^($(IFS='|'; echo "${KEEP_TAGS[*]}"))$"

##############################################################################
# 3. MAIN
##############################################################################
delete_ids=()

echo "📦  Scanning ghcr.io/${ORG}/${PKG} ..."

# Process versions and collect IDs to delete
while IFS= read -r row; do
  id=$(jq -r '.id' <<<"$row")
  digest=$(jq -r '.digest' <<<"$row")
  tags_csv=$(jq -r '.tags | join(",")' <<<"$row")
  keep=$(jq -e --arg re "$KEEP_REGEX" 'any(.tags[]?; test($re))' <<<"$row" 2>/dev/null) || keep=false

  if [[ $keep == true ]]; then
    printf "✅  KEEP    %s  [%s]\n" "$digest" "$tags_csv"
  else
    printf "🗑️   DELETE  %s  [%s]\n" "$digest" "$tags_csv"
    delete_ids+=("$id")
  fi
done < <(gh api -H "Accept: application/vnd.github+json" \
            "/orgs/${ORG}/packages/container/${PKG}/versions?per_page=${PER_PAGE}" \
            --paginate | \
         jq -cr --arg re "$KEEP_REGEX" '
           .[] |
           {
             id,
             digest: .metadata.container.digest,
             tags: (.metadata.container.tags // [])
           }
         ')

##############################################################################
# 4. CONFIRMATION & DELETION
##############################################################################
if [[ ${#delete_ids[@]} -eq 0 ]]; then
  echo "✨  Nothing to delete!"
  exit 0
fi

if [[ $DRY_RUN == true ]]; then
  if [[ $ASK_CONFIRM == true ]]; then
    echo
    read -rp "Proceed to delete the ${#delete_ids[@]} versions listed above? (y/N) " reply
    [[ $reply =~ ^[Yy]$ ]] || { echo "Aborted - nothing deleted."; exit 0; }
  fi
  echo "🚀  Re-running in destructive mode ..."
  DRY_RUN=false exec "$0" --yes
else
  echo "🗑️  Deleting ${#delete_ids[@]} versions..."
  for id in "${delete_ids[@]}"; do
    if gh api -X DELETE -H "Accept: application/vnd.github+json" \
              "/orgs/${ORG}/packages/container/${PKG}/versions/${id}" >/dev/null 2>&1; then
      echo "✅  Deleted version ID: $id"
    else
      echo "❌  Failed to delete version ID: $id"
    fi
  done
  echo "Done."
fi
