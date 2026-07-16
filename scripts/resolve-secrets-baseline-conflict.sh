#!/usr/bin/env bash
# Git merge driver for .secrets.baseline conflicts during rebase
# This script automatically resolves conflicts in .secrets.baseline by taking --ours version
#
# Setup as merge driver:
#   git config merge.secrets-baseline.name "Auto-resolve .secrets.baseline conflicts with --ours"
#   git config merge.secrets-baseline.driver "scripts/resolve-secrets-baseline-conflict.sh %O %A %B %P"
#
# Then add to .gitattributes:
#   .secrets.baseline merge=secrets-baseline
#
# Or use manually during rebase:
#   scripts/resolve-secrets-baseline-conflict.sh

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to log messages
log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    log_error "Not in a git repository"
    exit 1
fi

# Check if we're in a rebase
if ! git rev-parse --verify REBASE_HEAD > /dev/null 2>&1; then
    log_warn "Not currently in a rebase operation"
    exit 0
fi

# Check if .secrets.baseline has conflicts
if ! git diff --name-only --diff-filter=U | grep -q "^\.secrets\.baseline$"; then
    log_info "No conflicts in .secrets.baseline"
    exit 0
fi

log_info "Detected conflict in .secrets.baseline during rebase"

# Strategy: Take --theirs (incoming changes) to preserve updates, then regenerate baseline
log_info "Taking --theirs version to preserve incoming updates"
git checkout --theirs .secrets.baseline

# Regenerate baseline to update line numbers for files changed in this commit only
log_info "Regenerating baseline with detect-secrets for changed files only"
if command -v detect-secrets >/dev/null 2>&1; then
    # Get list of files changed in the commit being rebased
    CHANGED_FILES=$(git diff-tree --no-commit-id --name-only -r REBASE_HEAD 2>/dev/null || echo "")

    if [ -n "$CHANGED_FILES" ]; then
        log_info "Scanning $(echo "$CHANGED_FILES" | wc -l | tr -d ' ') changed file(s)"
        # Scan only the changed files and update baseline
        if echo "$CHANGED_FILES" | xargs detect-secrets scan --baseline .secrets.baseline --update .secrets.baseline 2>&1 | grep -q "Updated"; then
            log_info "Baseline updated successfully with current line numbers"
        else
            log_info "Baseline already up-to-date for changed files"
        fi
    else
        log_warn "Could not determine changed files, skipping baseline update"
    fi
else
    log_warn "detect-secrets not found, skipping baseline regeneration"
    log_warn "Install with: pip install --user detect-secrets"
fi

# Stage the resolved file
git add .secrets.baseline
log_info "Staged resolved .secrets.baseline"

# Check if there are any other conflicts
OTHER_CONFLICTS=$(git diff --name-only --diff-filter=U | grep -v "^\.secrets\.baseline$" || true)

if [ -z "$OTHER_CONFLICTS" ]; then
    log_info "No other conflicts detected, continuing rebase"
    git rebase --continue
    exit 0
else
    log_warn "Other conflicts still exist:"
    echo "$OTHER_CONFLICTS"
    log_info "Resolved .secrets.baseline, but manual intervention needed for other files"
    exit 0
fi
