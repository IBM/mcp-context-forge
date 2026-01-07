#!/bin/bash
# Tune OS for high-load Locust testing (4000+ users)
# Run with: sudo scripts/tune-loadtest.sh
#
# This script optimizes kernel TCP settings for high-concurrency load testing.
# Settings are temporary and reset on reboot.
#
# For WSL2: Some settings require .wslconfig changes (see output).
# For Docker: Containers inherit host kernel settings for net.core.* sysctls.

set -e

echo "=== Locust High-Load OS Tuning ==="
echo ""

# Detect environment
IS_WSL2=false
IS_DOCKER_HOST=false

if grep -qi microsoft /proc/version 2>/dev/null; then
    IS_WSL2=true
    echo "[INFO] WSL2 environment detected"
fi

if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    IS_DOCKER_HOST=true
    echo "[INFO] Docker available"
fi

echo ""

# =============================================================================
# File Descriptor Limits
# =============================================================================
echo "--- File Descriptor Limits ---"

# Current shell limits (for Locust client)
ulimit -n 65536 2>/dev/null && echo "[OK] ulimit -n 65536 (open files)" || \
    echo "[WARN] Cannot set ulimit -n (add to /etc/security/limits.conf or run as root)"

ulimit -u 65536 2>/dev/null && echo "[OK] ulimit -u 65536 (max processes)" || \
    echo "[WARN] Cannot set ulimit -u"

echo ""

# =============================================================================
# Kernel TCP Tuning (requires root)
# =============================================================================
echo "--- Kernel TCP Tuning ---"

if [ "$EUID" -eq 0 ]; then
    # Connection backlog - critical for high concurrency
    # These are host-level and inherited by Docker containers
    sysctl -w net.core.somaxconn=65535 && echo "[OK] net.core.somaxconn=65535"
    sysctl -w net.core.netdev_max_backlog=65535 && echo "[OK] net.core.netdev_max_backlog=65535"
    sysctl -w net.ipv4.tcp_max_syn_backlog=65535 && echo "[OK] net.ipv4.tcp_max_syn_backlog=65535"

    # Ephemeral port range - more ports for outbound connections
    sysctl -w net.ipv4.ip_local_port_range="1024 65535" && echo "[OK] net.ipv4.ip_local_port_range=1024-65535"

    # TIME_WAIT socket reuse - faster connection recycling
    # Boolean (0 or 1); only affects client-side (outbound) connections
    sysctl -w net.ipv4.tcp_tw_reuse=1 && echo "[OK] net.ipv4.tcp_tw_reuse=1"

    # Reduce TIME_WAIT timeout (default 60s)
    sysctl -w net.ipv4.tcp_fin_timeout=15 && echo "[OK] net.ipv4.tcp_fin_timeout=15"

    # TCP keepalive - detect dead connections faster
    sysctl -w net.ipv4.tcp_keepalive_time=60 && echo "[OK] net.ipv4.tcp_keepalive_time=60"
    sysctl -w net.ipv4.tcp_keepalive_intvl=10 && echo "[OK] net.ipv4.tcp_keepalive_intvl=10"
    sysctl -w net.ipv4.tcp_keepalive_probes=6 && echo "[OK] net.ipv4.tcp_keepalive_probes=6"

    # TCP memory tuning (min, default, max in pages)
    # Increase for high-throughput scenarios
    sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216" && echo "[OK] net.ipv4.tcp_rmem (receive buffer)"
    sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216" && echo "[OK] net.ipv4.tcp_wmem (send buffer)"
    sysctl -w net.core.rmem_max=16777216 && echo "[OK] net.core.rmem_max=16MB"
    sysctl -w net.core.wmem_max=16777216 && echo "[OK] net.core.wmem_max=16MB"

    # Increase max orphan sockets (connections in FIN_WAIT)
    sysctl -w net.ipv4.tcp_max_orphans=65536 && echo "[OK] net.ipv4.tcp_max_orphans=65536"

    # Enable TCP Fast Open (client + server)
    sysctl -w net.ipv4.tcp_fastopen=3 2>/dev/null && echo "[OK] net.ipv4.tcp_fastopen=3" || \
        echo "[SKIP] tcp_fastopen not available"

    # File handle limits
    sysctl -w fs.file-max=2097152 && echo "[OK] fs.file-max=2097152"
    sysctl -w fs.nr_open=2097152 2>/dev/null && echo "[OK] fs.nr_open=2097152" || true

    echo ""
    echo "[OK] Kernel TCP settings applied"
else
    echo "[WARN] Not running as root - kernel settings skipped"
    echo ""
    echo "Run with sudo, or apply manually:"
    echo "  sudo sysctl -w net.core.somaxconn=65535"
    echo "  sudo sysctl -w net.core.netdev_max_backlog=65535"
    echo "  sudo sysctl -w net.ipv4.tcp_max_syn_backlog=65535"
    echo "  sudo sysctl -w net.ipv4.ip_local_port_range='1024 65535'"
    echo "  sudo sysctl -w net.ipv4.tcp_tw_reuse=1"
    echo "  sudo sysctl -w net.ipv4.tcp_fin_timeout=15"
    echo "  sudo sysctl -w fs.file-max=2097152"
fi

echo ""

# =============================================================================
# WSL2-Specific Guidance
# =============================================================================
if [ "$IS_WSL2" = true ]; then
    echo "--- WSL2-Specific Configuration ---"
    echo ""
    echo "WSL2 kernel settings are applied above, but for persistence and"
    echo "memory limits, create/edit %USERPROFILE%\\.wslconfig on Windows:"
    echo ""
    echo "  [wsl2]"
    echo "  memory=8GB              # Adjust based on your RAM (default: 50%)"
    echo "  processors=4            # Number of CPUs for WSL2"
    echo "  swap=2GB                # Swap file size"
    echo "  localhostForwarding=true"
    echo ""
    echo "  [experimental]"
    echo "  sparseVhd=true          # Reclaim disk space automatically"
    echo ""
    echo "After editing, restart WSL: wsl --shutdown"
    echo ""

    # Check current WSL2 memory
    TOTAL_MEM=$(free -g | awk '/^Mem:/{print $2}')
    echo "[INFO] Current WSL2 memory: ${TOTAL_MEM}GB"
    if [ "$TOTAL_MEM" -lt 6 ]; then
        echo "[WARN] Less than 6GB RAM in WSL2 - consider increasing in .wslconfig"
    fi
    echo ""
fi

# =============================================================================
# Docker-Specific Guidance
# =============================================================================
if [ "$IS_DOCKER_HOST" = true ]; then
    echo "--- Docker Configuration ---"
    echo ""

    # Check Docker default ulimits
    DOCKER_NOFILE=$(docker info 2>/dev/null | grep -i "default ulimit" | head -1 || echo "")
    if [ -n "$DOCKER_NOFILE" ]; then
        echo "[INFO] Docker $DOCKER_NOFILE"
    fi

    echo "Your docker-compose.yml already sets container ulimits."
    echo "Host-level net.core.* sysctls (set above) are inherited by containers."
    echo ""
    echo "For Docker Desktop on WSL2, also check Docker Desktop settings:"
    echo "  - Resources > Advanced > Memory: 6GB+ recommended"
    echo "  - Resources > Advanced > CPUs: 4+ recommended"
    echo ""

    # Check if Docker is using too much memory
    DOCKER_MEM=$(docker system info 2>/dev/null | grep "Total Memory" | awk '{print $3}' || echo "")
    if [ -n "$DOCKER_MEM" ]; then
        echo "[INFO] Docker total memory: $DOCKER_MEM"
    fi

    echo "Tip: Run 'docker stats' during load test to monitor container resources."
    echo ""
fi

# =============================================================================
# Verification Commands
# =============================================================================
echo "--- Verification Commands ---"
echo ""
echo "Check current settings:"
echo "  sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog"
echo "  ulimit -n -u"
echo "  cat /proc/sys/fs/file-max"
echo ""
echo "Monitor during load test:"
echo "  watch -n1 'ss -s'                    # Socket statistics"
echo "  watch -n1 'cat /proc/net/sockstat'   # Socket memory"
echo "  docker stats                         # Container resources"
echo ""

# =============================================================================
# Make Sysctl Settings Persistent (optional)
# =============================================================================
echo "--- Sysctl Persistence (Optional) ---"
echo ""
echo "To make kernel settings persistent across reboots:"
echo ""
echo "  sudo tee /etc/sysctl.d/99-loadtest.conf << 'EOF'"
echo "net.core.somaxconn=65535"
echo "net.core.netdev_max_backlog=65535"
echo "net.ipv4.tcp_max_syn_backlog=65535"
echo "net.ipv4.ip_local_port_range=1024 65535"
echo "net.ipv4.tcp_tw_reuse=1"
echo "net.ipv4.tcp_fin_timeout=15"
echo "net.ipv4.tcp_keepalive_time=60"
echo "net.ipv4.tcp_keepalive_intvl=10"
echo "net.ipv4.tcp_keepalive_probes=6"
echo "net.core.rmem_max=16777216"
echo "net.core.wmem_max=16777216"
echo "fs.file-max=2097152"
echo "EOF"
echo ""
echo "  sudo sysctl --system   # Reload all sysctl configs"
echo ""

# =============================================================================
# User Limits Persistence (/etc/security/limits.conf)
# =============================================================================
echo "--- User Limits Persistence ---"
echo ""

# Check current nofile limit
CURRENT_NOFILE=$(ulimit -n 2>/dev/null || echo "unknown")
CURRENT_NPROC=$(ulimit -u 2>/dev/null || echo "unknown")

echo "[INFO] Current limits: nofile=$CURRENT_NOFILE, nproc=$CURRENT_NPROC"

if [ "$CURRENT_NOFILE" != "unknown" ] && [ "$CURRENT_NOFILE" -lt 65536 ]; then
    echo "[WARN] nofile limit ($CURRENT_NOFILE) is below recommended 65536"
    echo ""
    echo "Add to /etc/security/limits.conf for persistent limits:"
    echo ""
    echo "  sudo tee -a /etc/security/limits.conf << 'EOF'"
    echo ""
    echo "# Load Testing Limits (Locust 4000+ users)"
    echo "*               soft    nofile          65536"
    echo "*               hard    nofile          65536"
    echo "*               soft    nproc           65536"
    echo "*               hard    nproc           65536"
    echo "*               soft    sigpending      65536"
    echo "*               hard    sigpending      65536"
    echo "*               soft    memlock         unlimited"
    echo "*               hard    memlock         unlimited"
    echo "*               soft    msgqueue        819200"
    echo "*               hard    msgqueue        819200"
    echo "root            soft    nofile          65536"
    echo "root            hard    nofile          65536"
    echo "root            soft    nproc           65536"
    echo "root            hard    nproc           65536"
    echo "EOF"
    echo ""
    echo "Then restart your shell (or WSL: wsl --shutdown)"
else
    echo "[OK] nofile limit is adequate ($CURRENT_NOFILE)"
fi
echo ""

echo "=== Done ==="
