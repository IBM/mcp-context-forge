# shellcheck shell=bash
# ContextForge Setup - RHEL/Rocky/CentOS Functions
# OS-specific functions for RHEL-family distributions

# Initialize RHEL-specific variables
REMOVE_PODMAN=false

# Check if running on a supported RHEL-family distro
check_os() {
    log_info "Detected: $DISTRO_NAME"

    case "$DISTRO_ID" in
        rocky|rhel|centos|almalinux)
            return 0
            ;;
        fedora)
            log_warn "Fedora support is experimental. This script is primarily tested on Rocky/RHEL."
            if [[ "$YES_MODE" == true ]]; then
                log_info "Continuing in non-interactive mode..."
            else
                read -p "Continue anyway? [y/N] " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit 1
                fi
            fi
            return 0
            ;;
        *)
            log_error "Unsupported RHEL-family distribution: $DISTRO_ID"
            exit 1
            ;;
    esac
}

# Install system packages using dnf
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

# Handle podman/runc conflicts before Docker installation
handle_podman_conflict() {
    if ! rpm -q podman &>/dev/null && ! rpm -q runc &>/dev/null; then
        return 0  # No conflict
    fi

    if [[ "$REMOVE_PODMAN" == true ]]; then
        log_warn "Removing podman and runc (--remove-podman specified)..."
        sudo dnf remove -y podman runc 2>/dev/null || true
        return 0
    fi

    log_warn "podman and/or runc are installed. These conflict with Docker CE."
    log_warn "Removing them may break existing container workflows."
    echo

    if [[ "$YES_MODE" == true ]]; then
        log_error "Cannot install Docker CE while podman/runc are present."
        log_info "Re-run with --remove-podman flag to auto-remove them."
        exit 1
    fi

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
}

# Install Docker on RHEL/Rocky/CentOS
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

    # Handle podman/runc conflict
    handle_podman_conflict

    # Add Docker's official repository
    sudo dnf -y install dnf-plugins-core

    # Determine the correct Docker repo based on distro
    local docker_repo
    case "$DISTRO_ID" in
        fedora)
            docker_repo="https://download.docker.com/linux/fedora/docker-ce.repo"
            ;;
        *)
            # Rocky, RHEL, CentOS, AlmaLinux all use the RHEL repo
            docker_repo="https://download.docker.com/linux/rhel/docker-ce.repo"
            ;;
    esac

    sudo dnf config-manager --add-repo "$docker_repo"

    # Install Docker packages (--allowerasing handles any remaining package conflicts)
    sudo dnf install -y --allowerasing docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    log_success "Docker installed: $(docker --version)"
}

# Handle RHEL-specific CLI options (called by parse_args)
handle_os_option() {
    case "$1" in
        --remove-podman)
            REMOVE_PODMAN=true
            return 0  # Option handled
            ;;
    esac
    return 1  # Option not handled
}

# Show RHEL-specific help
show_os_help() {
    echo "RHEL/Rocky-specific options:"
    echo "  --remove-podman  Remove podman/runc without prompting (required for Docker CE)"
    echo
}
