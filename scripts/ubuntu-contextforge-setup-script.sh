#!/bin/bash
# ContextForge Ubuntu Setup Script
# Author: Mihai Criveti
# This script sets up a fresh Ubuntu system to run ContextForge with Docker Compose
#
# PREREQUISITES (run as root first):
# ---------------------------------
#   adduser contextforge
#   usermod -aG sudo contextforge
#   su - contextforge
#
# Then run this script as the contextforge user.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1" >&2; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1" >&2; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1" >&2; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Check if running as root
check_not_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "Do not run this script as root. Run as a regular user with sudo privileges."
        exit 1
    fi
}

# Check Ubuntu version
check_ubuntu() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "Cannot detect OS. This script is designed for Ubuntu."
        exit 1
    fi
    source /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        log_warn "This script is designed for Ubuntu. Detected: $ID"
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    log_info "Detected: $PRETTY_NAME"
}

# Install system packages
install_system_packages() {
    log_info "Updating package lists..."
    sudo apt update

    log_info "Installing essential packages..."
    sudo apt install -y \
        git \
        make \
        curl \
        ca-certificates \
        gnupg \
        lsb-release
    log_success "System packages installed"
}

# Install Docker
install_docker() {
    if command -v docker &> /dev/null; then
        log_info "Docker is already installed: $(docker --version)"
        return 0
    fi

    log_info "Installing Docker..."

    # Add Docker's official GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    # Add the repository to apt sources
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    log_success "Docker installed: $(docker --version)"
}

# Configure Docker for non-root user
configure_docker_user() {
    if groups "$USER" | grep -q '\bdocker\b'; then
        log_info "User $USER is already in the docker group"
        return 0
    fi

    log_info "Adding $USER to docker group..."
    sudo usermod -aG docker "$USER"
    log_warn "You need to log out and back in for docker group to take effect"
    log_warn "Or run: newgrp docker"
}

# Start and enable Docker service
start_docker_service() {
    log_info "Starting Docker service..."
    sudo systemctl start docker
    sudo systemctl enable docker
    log_success "Docker service started and enabled"
}

# Install uv (Python package manager)
install_uv() {
    if command -v uv &> /dev/null || [[ -x "$HOME/.local/bin/uv" ]]; then
        log_info "uv is already installed"
        return 0
    fi

    log_info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >&2

    # Add to PATH for current session
    export PATH="$HOME/.local/bin:$PATH"

    # Add to .bashrc if not already there
    if ! grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
        log_info "Added ~/.local/bin to PATH in .bashrc"
    fi

    log_success "uv installed"
}

# Clone ContextForge repository
clone_repository() {
    local repo_url="https://github.com/IBM/mcp-context-forge.git"
    local target_dir="${1:-$HOME/mcp-context-forge}"

    if [[ -d "$target_dir" ]]; then
        log_info "Directory $target_dir already exists"
        read -p "Pull latest changes? [Y/n] " -n 1 -r
        echo >&2
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            cd "$target_dir"
            git pull >&2
            log_success "Repository updated"
        fi
    else
        log_info "Cloning ContextForge repository..."
        git clone "$repo_url" "$target_dir" >&2
        log_success "Repository cloned to $target_dir"
    fi
    echo "$target_dir"
}

# Setup environment file
setup_env() {
    local project_dir="$1"
    cd "$project_dir"

    if [[ -f .env ]]; then
        log_info ".env file already exists"
        return 0
    fi

    if [[ -f .env.example ]]; then
        log_info "Creating .env from .env.example..."
        cp .env.example .env
        log_success ".env file created"
        log_warn "Review and customize .env before running in production"
    else
        log_error ".env.example not found"
        exit 1
    fi
}

# Start ContextForge with Docker Compose
start_contextforge() {
    local project_dir="$1"
    cd "$project_dir"

    log_info "Starting ContextForge with Docker Compose..."

    # Use sg to run with docker group if not already in it
    if groups | grep -q '\bdocker\b'; then
        make compose-up
    else
        log_info "Running with docker group privileges..."
        sg docker -c "make compose-up"
    fi

    log_success "ContextForge started"
}

# Verify installation
verify_installation() {
    local project_dir="$1"
    cd "$project_dir"

    log_info "Waiting for services to start..."
    sleep 10

    log_info "Checking container status..."
    if groups | grep -q '\bdocker\b'; then
        make compose-ps
    else
        sg docker -c "make compose-ps"
    fi

    log_info "Checking health endpoint..."
    local max_retries=30
    local retry=0
    while [[ $retry -lt $max_retries ]]; do
        if curl -s http://localhost:4444/health | grep -q "healthy"; then
            log_success "ContextForge is healthy!"
            echo
            echo "======================================"
            echo "  ContextForge is running!"
            echo "  Admin UI: http://localhost:4444"
            echo "  Health:   http://localhost:4444/health"
            echo "  API Docs: http://localhost:4444/docs"
            echo "======================================"
            return 0
        fi
        retry=$((retry + 1))
        sleep 2
    done

    log_warn "Health check did not pass within timeout. Check logs with: make compose-logs"
}

# Print summary
print_summary() {
    local project_dir="$1"
    echo
    log_success "Setup complete!"
    echo
    echo "Next steps:"
    echo "  1. cd $project_dir"
    echo "  2. Review and customize .env file"
    echo "  3. make compose-logs  # View logs"
    echo "  4. make compose-ps    # Check status"
    echo
    echo "Useful commands:"
    echo "  make compose-up       # Start services"
    echo "  make compose-down     # Stop services"
    echo "  make compose-restart  # Restart services"
    echo "  make compose-logs     # View logs"
    echo
}

# Main function
main() {
    echo "========================================"
    echo "  ContextForge Ubuntu Setup Script"
    echo "========================================"
    echo

    local install_dir="${1:-$HOME/mcp-context-forge}"
    local skip_start="${2:-false}"

    check_not_root
    check_ubuntu
    install_system_packages
    install_docker
    start_docker_service
    configure_docker_user
    install_uv

    local project_dir
    project_dir=$(clone_repository "$install_dir")
    setup_env "$project_dir"

    if [[ "$skip_start" != "--skip-start" ]]; then
        start_contextforge "$project_dir"
        verify_installation "$project_dir"
    fi

    print_summary "$project_dir"
}

# Show help
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [INSTALL_DIR] [--skip-start]"
    echo
    echo "Prerequisites (run as root first):"
    echo "  adduser contextforge"
    echo "  usermod -aG sudo contextforge"
    echo "  su - contextforge"
    echo
    echo "Arguments:"
    echo "  INSTALL_DIR   Directory to install ContextForge (default: ~/mcp-context-forge)"
    echo "  --skip-start  Skip starting the services after setup"
    echo
    echo "Examples:"
    echo "  $0                          # Install to ~/mcp-context-forge and start"
    echo "  $0 /opt/contextforge        # Install to /opt/contextforge and start"
    echo "  $0 ~/cf --skip-start        # Install but don't start services"
    exit 0
fi

main "$@"
