#!/bin/bash
# ContextForge Setup Script
# Multi-distribution installer for ContextForge with Docker Compose
#
# Supports:
#   - Ubuntu, Debian (and derivatives)
#   - Rocky Linux, RHEL, CentOS, AlmaLinux, Fedora
#
# PREREQUISITES (run as root first):
# ---------------------------------
#   # Create a dedicated user (optional but recommended):
#   useradd -m contextforge   # or: adduser contextforge
#   passwd contextforge
#   usermod -aG wheel contextforge   # RHEL-family
#   usermod -aG sudo contextforge    # Debian-family
#   su - contextforge
#
# Then run this script as that user (or any user with sudo privileges).

set -euo pipefail

# Determine script directory for sourcing modules
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common functions
if [[ ! -f "$SCRIPT_DIR/lib/common.sh" ]]; then
    echo "ERROR: Cannot find $SCRIPT_DIR/lib/common.sh" >&2
    echo "Make sure the lib/ directory is present alongside this script." >&2
    exit 1
fi
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

# Parse command line arguments
parse_args() {
    INSTALL_DIR="$HOME/mcp-context-forge"
    SKIP_START=false
    SKIP_DOCKER_LOGIN=false
    YES_MODE=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-start)
                SKIP_START=true
                shift
                ;;
            --skip-docker-login)
                SKIP_DOCKER_LOGIN=true
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
                # Try OS-specific option handler
                if type handle_os_option &>/dev/null && handle_os_option "$1"; then
                    shift
                else
                    log_error "Unknown option: $1"
                    show_help
                    exit 1
                fi
                ;;
            *)
                INSTALL_DIR="$1"
                shift
                ;;
        esac
    done

    export INSTALL_DIR SKIP_START SKIP_DOCKER_LOGIN YES_MODE
}

# Show help message
show_help() {
    echo "Usage: $0 [OPTIONS] [INSTALL_DIR]"
    echo
    echo "Multi-distribution ContextForge installer."
    echo
    echo "Supported distributions:"
    echo "  - Ubuntu, Debian (and derivatives like Linux Mint, Pop!_OS)"
    echo "  - Rocky Linux, RHEL, CentOS, AlmaLinux, Fedora"
    echo
    echo "Prerequisites (run as root first):"
    echo "  useradd -m contextforge && passwd contextforge"
    echo "  usermod -aG wheel contextforge   # RHEL-family"
    echo "  usermod -aG sudo contextforge    # Debian-family"
    echo "  su - contextforge"
    echo
    echo "Common options:"
    echo "  --skip-start        Skip starting the services after setup"
    echo "  --skip-docker-login Skip Docker registry login prompt"
    echo "  -y, --yes           Non-interactive mode (auto-confirm prompts)"
    echo "  -h, --help          Show this help message"
    echo
    echo "Environment variables for automated Docker login:"
    echo "  DOCKER_USERNAME     Docker registry username"
    echo "  DOCKER_PASSWORD     Docker registry password (use with caution)"
    echo "  DOCKER_REGISTRY     Registry URL (default: Docker Hub)"
    echo "  DOCKER_CONFIG       Custom Docker config directory"
    echo
    # Show OS-specific help if available
    if type show_os_help &>/dev/null; then
        show_os_help
    fi
    echo "Arguments:"
    echo "  INSTALL_DIR   Directory to install ContextForge (default: ~/mcp-context-forge)"
    echo
    echo "Examples:"
    echo "  $0                              # Interactive install and start"
    echo "  $0 --skip-start                 # Install but don't start services"
    echo "  $0 ~/contextforge               # Install to custom directory"
    echo "  $0 -y --skip-start              # Fully non-interactive install"
}

# Main function
main() {
    echo "========================================"
    echo "  ContextForge Setup Script"
    echo "========================================"
    echo

    # Detect OS before parsing args (so OS-specific options work)
    detect_os

    # Source OS-specific module
    case "$DISTRO_FAMILY" in
        debian)
            if [[ ! -f "$SCRIPT_DIR/lib/debian.sh" ]]; then
                log_error "Cannot find $SCRIPT_DIR/lib/debian.sh"
                exit 1
            fi
            # shellcheck source=lib/debian.sh
            source "$SCRIPT_DIR/lib/debian.sh"
            ;;
        rhel)
            if [[ ! -f "$SCRIPT_DIR/lib/rhel.sh" ]]; then
                log_error "Cannot find $SCRIPT_DIR/lib/rhel.sh"
                exit 1
            fi
            # shellcheck source=lib/rhel.sh
            source "$SCRIPT_DIR/lib/rhel.sh"
            ;;
        *)
            log_error "Unsupported OS family. Detected: $DISTRO_ID"
            log_error "Supported: Ubuntu, Debian, Rocky, RHEL, CentOS, AlmaLinux, Fedora"
            exit 1
            ;;
    esac

    parse_args "$@"

    check_not_root
    check_os
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

main "$@"
