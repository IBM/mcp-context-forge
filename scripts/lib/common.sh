# shellcheck shell=bash
# ContextForge Setup - Common Functions
# Shared helpers used by all OS-specific modules

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

# Detect OS family from /etc/os-release
detect_os() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "Cannot detect OS. /etc/os-release not found."
        exit 1
    fi

    source /etc/os-release

    case "$ID" in
        ubuntu|debian|linuxmint|pop)
            DISTRO_FAMILY="debian"
            ;;
        rocky|rhel|centos|almalinux|fedora)
            DISTRO_FAMILY="rhel"
            ;;
        *)
            DISTRO_FAMILY="unknown"
            ;;
    esac

    DISTRO_ID="$ID"
    DISTRO_NAME="${PRETTY_NAME:-$ID}"
    export DISTRO_FAMILY DISTRO_ID DISTRO_NAME
}

# Configure Docker for non-root user
configure_docker_user() {
    if groups "$USER" | grep -qw docker; then
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
    # shellcheck disable=SC2016  # Single quotes intentional - expand at shell startup
    if ! grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
        log_info "Added ~/.local/bin to PATH in .bashrc"
    fi

    log_success "uv installed"
}

# Run docker command, using sg if user is not yet in docker group
run_docker_cmd() {
    if groups | grep -qw docker; then
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
    # Respect DOCKER_CONFIG env var, fall back to default location
    local config_dir="${DOCKER_CONFIG:-$HOME/.docker}"
    local config_file="$config_dir/config.json"

    # Check if config file exists and has auth entries
    if [[ -f "$config_file" ]]; then
        # Check for auths section with entries, or credsStore/credHelpers configured
        if grep -qE '"auths"\s*:\s*\{[^}]+\}|"credsStore"|"credHelpers"' "$config_file" 2>/dev/null; then
            return 0  # Logged in or credential helper configured
        fi
    fi
    return 1  # Not logged in
}

# Prompt user to log in to Docker registry (interactive only)
prompt_docker_login() {
    log_warn "Docker does not appear to be logged in to a registry."
    log_info "Some container images may require authentication to pull."
    echo
    echo "How would you like to authenticate with Docker Hub (or another registry)?"
    echo
    echo "  1) Interactive login (recommended) - prompts for username and password"
    echo "  2) Skip login - continue without authenticating"
    echo
    read -p "Select an option [1-2]: " -n 1 -r login_choice
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
            log_warn "Skipping Docker login. Image pulls may fail if authentication is required."
            ;;
        *)
            log_warn "Invalid option. Skipping Docker login."
            ;;
    esac
}

# Ensure Docker login before pulling images
# Supports:
#   - SKIP_DOCKER_LOGIN=true to skip entirely
#   - DOCKER_USERNAME + DOCKER_PASSWORD env vars for automated auth
#   - DOCKER_REGISTRY env var for non-Docker Hub registries
ensure_docker_login() {
    # Skip if explicitly requested
    if [[ "${SKIP_DOCKER_LOGIN:-false}" == true ]]; then
        log_info "Skipping Docker login (SKIP_DOCKER_LOGIN=true)"
        return 0
    fi

    # Already logged in
    if check_docker_login; then
        log_info "Docker registry credentials detected"
        return 0
    fi

    # Try automated login via environment variables
    if [[ -n "${DOCKER_USERNAME:-}" && -n "${DOCKER_PASSWORD:-}" ]]; then
        log_info "Attempting Docker login via environment variables..."
        local registry_arg=""
        if [[ -n "${DOCKER_REGISTRY:-}" ]]; then
            registry_arg="$DOCKER_REGISTRY"
            log_info "Using registry: $DOCKER_REGISTRY"
        fi
        # Pipe password directly to avoid storing in shell variable
        if printenv DOCKER_PASSWORD | run_docker_cmd docker login -u "$DOCKER_USERNAME" --password-stdin ${registry_arg:+"$registry_arg"}; then
            log_success "Docker login successful"
            return 0
        else
            log_error "Docker login failed with provided credentials"
            return 1
        fi
    fi

    # Non-interactive mode without credentials - skip with warning
    if [[ "${YES_MODE:-false}" == true ]]; then
        log_warn "No Docker credentials found and running in non-interactive mode (-y)"
        log_warn "Skipping Docker login. Image pulls may fail if authentication is required."
        log_info "To provide credentials non-interactively, set DOCKER_USERNAME and DOCKER_PASSWORD"
        log_info "Or set SKIP_DOCKER_LOGIN=true to suppress this warning"
        return 0
    fi

    # Interactive prompt
    prompt_docker_login
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
            cd "$target_dir" || exit 1
            git pull >&2
            log_success "Repository updated"
        else
            read -p "Pull latest changes? [Y/n] " -n 1 -r
            echo >&2
            if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                cd "$target_dir" || exit 1
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
    cd "$project_dir" || exit 1

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
    cd "$project_dir" || exit 1

    # Ensure Docker login before attempting to pull images
    ensure_docker_login

    log_info "Starting ContextForge with Docker Compose..."

    # Use sg to run with docker group if not already in it
    if groups | grep -qw docker; then
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
    cd "$project_dir" || exit 1

    log_info "Waiting for services to start..."
    sleep 10

    log_info "Checking container status..."
    if groups | grep -qw docker; then
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
