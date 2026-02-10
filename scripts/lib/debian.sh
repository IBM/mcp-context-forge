# shellcheck shell=bash
# ContextForge Setup - Debian/Ubuntu Functions
# OS-specific functions for Debian-family distributions

# Check if running on a supported Debian-family distro
check_os() {
    log_info "Detected: $DISTRO_NAME"

    case "$DISTRO_ID" in
        ubuntu|debian)
            return 0
            ;;
        linuxmint|pop)
            log_warn "This script is primarily tested on Ubuntu/Debian. Detected: $DISTRO_ID"
            if [[ "$YES_MODE" == true ]]; then
                log_info "Continuing in non-interactive mode..."
                return 0
            else
                read -p "Continue anyway? [y/N] " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit 1
                fi
                return 0
            fi
            ;;
        *)
            log_error "Unsupported Debian-family distribution: $DISTRO_ID"
            exit 1
            ;;
    esac
}

# Install system packages using apt
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

# Install Docker on Debian/Ubuntu
install_docker() {
    if command -v docker &> /dev/null; then
        log_info "Docker is already installed: $(docker --version)"
        return 0
    fi

    log_info "Installing Docker..."

    # Determine the correct Docker repo base (and matching GPG key URL) based on distro
    local docker_repo_base
    case "$DISTRO_ID" in
        ubuntu)
            docker_repo_base="https://download.docker.com/linux/ubuntu"
            ;;
        debian)
            docker_repo_base="https://download.docker.com/linux/debian"
            ;;
        *)
            # For derivatives, try Ubuntu repo
            docker_repo_base="https://download.docker.com/linux/ubuntu"
            log_warn "Using Ubuntu Docker repo for $DISTRO_ID"
            ;;
    esac

    # Add Docker's official GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "$docker_repo_base/gpg" | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    # Add the repository to apt sources
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] $docker_repo_base \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    log_success "Docker installed: $(docker --version)"
}

# Register Debian-specific CLI options (called by parse_args)
register_os_options() {
    # No additional options for Debian
    :
}

# Handle Debian-specific CLI options (called by parse_args)
handle_os_option() {
    # No additional options for Debian
    return 1  # Option not handled
}

# Show Debian-specific help
show_os_help() {
    # No additional help for Debian
    :
}
