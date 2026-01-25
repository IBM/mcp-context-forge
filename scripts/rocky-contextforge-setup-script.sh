#!/bin/bash
# ContextForge Rocky Linux Setup Script
# Author: Mihai Criveti (Original Ubuntu script)
# Rocky Linux adaptation
# This script sets up a fresh Rocky Linux system to run ContextForge with Docker Compose
#
# PREREQUISITES (run as root first):
# ---------------------------------
#   useradd -m contextforge
#   passwd contextforge
#   usermod -aG wheel contextforge
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

# Check Rocky Linux or RHEL-compatible distro
check_rocky() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "Cannot detect OS. This script is designed for Rocky Linux and RHEL-compatible distributions."
        exit 1
    fi
    source /etc/os-release
    case "$ID" in
        rocky|rhel|centos|almalinux)
            log_info "Detected: $PRETTY_NAME"
            ;;
        *)
            log_warn "This script is designed for Rocky Linux and RHEL-compatible distributions. Detected: $ID"
            if [[ "$YES_MODE" == true ]]; then
                log_error "Unsupported OS in non-interactive mode. Use -y only on supported distributions."
                exit 1
            fi
            read -p "Continue anyway? [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
            ;;
    esac
}

# Install system packages
install_system_packages() {
    log_info "Installing essential packages..."
    # Use --allowerasing to handle curl-minimal vs curl conflict in minimal images
    sudo dnf install -y --allowerasing \
        git \
        make \
        curl \
        ca-certificates \
        gnupg2
    log_success "System packages installed"
}

# Install Docker
install_docker() {
    if command -v docker &> /dev/null; then
        log_info "Docker is already installed: $(docker --version)"
        return 0
    fi

    log_info "Installing Docker..."

    # Remove old Docker packages
    sudo dnf remove -y docker \
        docker-client \
        docker-client-latest \
        docker-common \
        docker-latest \
        docker-latest-logrotate \
        docker-logrotate \
        docker-engine 2>/dev/null || true

    # Check if podman/runc are installed and handle removal
    if rpm -q podman &>/dev/null || rpm -q runc &>/dev/null; then
        if [[ "$REMOVE_PODMAN" == true ]]; then
            log_warn "Removing podman and runc (--remove-podman specified)..."
            sudo dnf remove -y podman runc 2>/dev/null || true
        else
            log_warn "podman and/or runc are installed. These conflict with Docker CE."
            log_warn "Removing them may break existing container workflows."
            echo
            read -p "Remove podman and runc to proceed with Docker installation? [y/N] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                log_info "Removing podman and runc..."
                sudo dnf remove -y podman runc 2>/dev/null || true
            else
                log_error "Cannot install Docker CE while podman/runc are present."
                log_info "Either remove them manually or re-run with --remove-podman flag."
                exit 1
            fi
        fi
    fi

    # Add Docker's official repository
    sudo dnf -y install dnf-plugins-core
    sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo

    # Install Docker packages (--allowerasing handles any remaining package conflicts)
    sudo dnf install -y --allowerasing docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

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
        # Check if it's a git repository
        if [[ ! -d "$target_dir/.git" ]]; then
            log_error "Directory $target_dir exists but is not a git repository."
            log_error "Please remove or rename it, or choose a different install directory."
            exit 1
        fi

        log_info "Directory $target_dir already exists"
        if [[ "$YES_MODE" == true ]]; then
            log_info "Pulling latest changes (non-interactive mode)..."
            cd "$target_dir"
            git pull >&2
            log_success "Repository updated"
        else
            read -p "Pull latest changes? [Y/n] " -n 1 -r
            echo >&2
            if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                cd "$target_dir"
                git pull >&2
                log_success "Repository updated"
            fi
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

# Run docker command, using sg if user is not yet in docker group
run_docker_cmd() {
    if groups | grep -q '\bdocker\b'; then
        "$@"
    else
        # Properly quote arguments for sg -c
        local cmd=""
        for arg in "$@"; do
            cmd+="${cmd:+ }$(printf '%q' "$arg")"
        done
        sg docker -c "$cmd"
    fi
}

# Check if Docker is logged in to a registry
check_docker_login() {
    local config_file="$HOME/.docker/config.json"

    # Check if config file exists and has auth entries
    if [[ -f "$config_file" ]]; then
        # Check for auths section with entries, or credsStore/credHelpers configured
        if grep -qE '"auths"\s*:\s*\{[^}]+\}|"credsStore"|"credHelpers"' "$config_file" 2>/dev/null; then
            return 0  # Logged in or credential helper configured
        fi
    fi
    return 1  # Not logged in
}

# Prompt user to log in to Docker registry
prompt_docker_login() {
    log_warn "Docker does not appear to be logged in to a registry."
    log_info "Some container images may require authentication to pull."
    echo
    echo "How would you like to authenticate with Docker Hub (or another registry)?"
    echo
    echo "  1) Interactive login (recommended) - prompts for username and password"
    echo "  2) Username with password from stdin - for piped/automated input"
    echo "  3) Skip login - continue without authenticating"
    echo
    read -p "Select an option [1-3]: " -n 1 -r login_choice
    echo

    case "$login_choice" in
        1)
            log_info "Starting interactive Docker login..."
            read -r -p "Registry URL (press Enter for Docker Hub): " registry_url
            if [[ -n "$registry_url" ]]; then
                run_docker_cmd docker login "$registry_url"
            else
                run_docker_cmd docker login
            fi
            ;;
        2)
            read -r -p "Registry URL (press Enter for Docker Hub): " registry_url
            read -r -p "Username: " docker_username
            read -r -s -p "Password: " docker_password
            echo  # newline after hidden password input
            if [[ -n "$registry_url" ]]; then
                printf '%s' "$docker_password" | run_docker_cmd docker login -u "$docker_username" --password-stdin "$registry_url"
            else
                printf '%s' "$docker_password" | run_docker_cmd docker login -u "$docker_username" --password-stdin
            fi
            unset docker_password  # Clear password from memory
            ;;
        3)
            log_warn "Skipping Docker login. Image pulls may fail if authentication is required."
            ;;
        *)
            log_warn "Invalid option. Skipping Docker login."
            ;;
    esac
}

# Ensure Docker login before pulling images
ensure_docker_login() {
    if check_docker_login; then
        log_info "Docker registry credentials detected"
        return 0
    fi

    prompt_docker_login
}

# Start ContextForge with Docker Compose
start_contextforge() {
    local project_dir="$1"
    cd "$project_dir"

    # Ensure Docker login before attempting to pull images
    # Note: check_docker_login reads config file (no docker group needed)
    # but docker login command requires docker group access
    ensure_docker_login

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

# Parse command line arguments
parse_args() {
    INSTALL_DIR="$HOME/mcp-context-forge"
    SKIP_START=false
    REMOVE_PODMAN=false
    YES_MODE=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-start)
                SKIP_START=true
                shift
                ;;
            --remove-podman)
                REMOVE_PODMAN=true
                shift
                ;;
            -y|--yes)
                YES_MODE=true
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            -*)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
            *)
                INSTALL_DIR="$1"
                shift
                ;;
        esac
    done
}

# Main function
main() {
    echo "========================================"
    echo "  ContextForge Rocky Linux Setup Script"
    echo "========================================"
    echo

    parse_args "$@"

    check_not_root
    check_rocky
    install_system_packages
    install_docker
    start_docker_service
    configure_docker_user
    install_uv

    local project_dir
    project_dir=$(clone_repository "$INSTALL_DIR")
    setup_env "$project_dir"

    if [[ "$SKIP_START" != true ]]; then
        start_contextforge "$project_dir"
        verify_installation "$project_dir"
    fi

    print_summary "$project_dir"
}

# Show help
show_help() {
    echo "Usage: $0 [OPTIONS] [INSTALL_DIR]"
    echo
    echo "Prerequisites (run as root first):"
    echo "  useradd -m contextforge"
    echo "  passwd contextforge"
    echo "  usermod -aG wheel contextforge"
    echo "  su - contextforge"
    echo
    echo "Options:"
    echo "  --skip-start     Skip starting the services after setup"
    echo "  --remove-podman  Remove podman/runc without prompting"
    echo "  -y, --yes        Non-interactive mode (auto-confirm prompts, fail on unsupported OS)"
    echo "  -h, --help       Show this help message"
    echo
    echo "Arguments:"
    echo "  INSTALL_DIR      Directory to install ContextForge (default: ~/mcp-context-forge)"
    echo
    echo "Examples:"
    echo "  $0                                        # Interactive install and start"
    echo "  $0 --skip-start                           # Install but don't start services"
    echo "  $0 ~/contextforge                         # Install to ~/contextforge and start"
    echo "  $0 -y --remove-podman --skip-start        # Fully non-interactive install"
}

main "$@"
