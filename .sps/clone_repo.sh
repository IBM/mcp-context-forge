#!/usr/bin/env bash
#
# Clone a GitHub repository using environment variables
#
# Required environment variables:
#   GH_USER  - GitHub username
#   GH_TOKEN - GitHub personal access token
#   GH_URL   - GitHub repository URL (e.g., https://github.com/owner/repo.git)
#
# Usage:
#   export GH_USER="your-username"
#   export GH_TOKEN="your-token"
#   export GH_URL="https://github.com/owner/repo.git"
#   ./scripts/clone_repo.sh

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print error messages
error() {
    echo -e "${RED}ERROR: $1${NC}" >&2
}

# Function to print success messages
success() {
    echo -e "${GREEN}SUCCESS: $1${NC}"
}

# Function to print info messages
info() {
    echo -e "${YELLOW}INFO: $1${NC}"
}

# Validate required environment variables
if [[ -z "${GH_USER:-}" ]]; then
    error "GH_USER environment variable is not set"
    exit 1
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
    error "GH_TOKEN environment variable is not set"
    exit 1
fi

if [[ -z "${GH_URL:-}" ]]; then
    error "GH_URL environment variable is not set"
    exit 1
fi

# Extract repository name from URL
REPO_NAME=$(basename "${GH_URL}" .git)

# Construct authenticated URL
# Handle both https://github.com/owner/repo.git and git@github.com:owner/repo.git formats
if [[ "${GH_URL}" =~ ^https:// ]]; then
    # HTTPS URL format
    AUTH_URL="${GH_URL/https:\/\//https://${GH_USER}:${GH_TOKEN}@}"
elif [[ "${GH_URL}" =~ ^git@ ]]; then
    # SSH URL format - convert to HTTPS with auth
    REPO_PATH="${GH_URL#git@github.com:}"
    REPO_PATH="${REPO_PATH%.git}"
    AUTH_URL="https://${GH_USER}:${GH_TOKEN}@github.com/${REPO_PATH}.git"
else
    error "Unsupported URL format: ${GH_URL}"
    exit 1
fi

info "Cloning repository: ${REPO_NAME}"
info "Target directory: ./${REPO_NAME}"

# Clone the repository
if git clone "${AUTH_URL}" "${REPO_NAME}"; then
    success "Repository cloned successfully to ./${REPO_NAME}"
    
    # Remove credentials from git config for security
    cd "${REPO_NAME}"
    git remote set-url origin "${GH_URL}"
    cd ..
    
    info "Credentials removed from git config"
else
    error "Failed to clone repository"
    exit 1
fi