#!/usr/bin/env bash
# Setup git hooks and merge drivers for the repository
# This script is idempotent and can be run multiple times safely

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

log_step() {
    echo -e "${BLUE}[STEP]${NC} $*"
}

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    log_error "Not in a git repository"
    exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

log_info "Setting up git hooks and merge drivers for repository: $REPO_ROOT"
echo ""

# Step 1: Configure git merge driver for .secrets.baseline
log_step "Configuring git merge driver for .secrets.baseline"

MERGE_DRIVER_NAME="secrets-baseline"
MERGE_DRIVER_DESC="Auto-resolve .secrets.baseline conflicts with --ours"
MERGE_DRIVER_CMD="scripts/resolve-secrets-baseline-conflict.sh %O %A %B %P"
MERGE_SCRIPT_PATH="scripts/resolve-secrets-baseline-conflict.sh"

# Check if merge driver is already configured
CURRENT_DRIVER=$(git config --get "merge.${MERGE_DRIVER_NAME}.driver" || echo "")

# Check if merge script has been modified (compare with git HEAD)
SCRIPT_MODIFIED=false
if [ -f "$MERGE_SCRIPT_PATH" ]; then
    if git diff --quiet HEAD -- "$MERGE_SCRIPT_PATH" 2>/dev/null; then
        log_info "Merge script is up-to-date with repository"
    else
        log_warn "Merge script has uncommitted changes"
        SCRIPT_MODIFIED=true
    fi
fi

if [ "$CURRENT_DRIVER" = "$MERGE_DRIVER_CMD" ] && [ "$SCRIPT_MODIFIED" = false ]; then
    log_info "Merge driver already configured correctly"
else
    if [ "$SCRIPT_MODIFIED" = true ]; then
        log_info "Reconfiguring merge driver due to script changes"
    fi
    git config "merge.${MERGE_DRIVER_NAME}.name" "$MERGE_DRIVER_DESC"
    git config "merge.${MERGE_DRIVER_NAME}.driver" "$MERGE_DRIVER_CMD"
    log_info "Configured merge driver: $MERGE_DRIVER_NAME"
fi

# Step 2: Add .gitattributes entry if not present
log_step "Configuring .gitattributes"

GITATTRIBUTES_FILE=".gitattributes"
GITATTRIBUTES_ENTRY=".secrets.baseline merge=secrets-baseline"

if [ ! -f "$GITATTRIBUTES_FILE" ]; then
    log_warn ".gitattributes file does not exist, creating it"
    echo "$GITATTRIBUTES_ENTRY" > "$GITATTRIBUTES_FILE"
    log_info "Created .gitattributes with merge driver entry"
elif grep -qF "$GITATTRIBUTES_ENTRY" "$GITATTRIBUTES_FILE"; then
    log_info ".gitattributes already contains merge driver entry"
else
    echo "$GITATTRIBUTES_ENTRY" >> "$GITATTRIBUTES_FILE"
    log_info "Added merge driver entry to .gitattributes"
fi

# Step 3: Install pre-commit hooks
log_step "Installing pre-commit hooks"

if ! command -v pre-commit &> /dev/null; then
    log_warn "pre-commit is not installed. Install it with: pip install pre-commit"
    log_warn "Skipping pre-commit installation"
else
    if pre-commit install; then
        log_info "Pre-commit hooks installed successfully"
    else
        log_error "Failed to install pre-commit hooks"
        exit 1
    fi
fi

echo ""
log_info "Git hooks setup complete!"
echo ""
echo "Summary:"
echo "  ✓ Merge driver configured for .secrets.baseline"
echo "  ✓ .gitattributes updated"
if command -v pre-commit &> /dev/null; then
    echo "  ✓ Pre-commit hooks installed"
else
    echo "  ⚠ Pre-commit hooks skipped (pre-commit not installed)"
fi
echo ""
log_info "You can now run 'git rebase' and .secrets.baseline conflicts will be auto-resolved"
