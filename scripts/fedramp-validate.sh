#!/usr/bin/env bash
# FedRAMP post-build compliance validation.
# Run inside a container built with ENABLE_FIPS=true.
# Exit 0 = all checks pass. Exit 1 = at least one check failed.
set -euo pipefail

PASS=0
FAIL=0

check() {
    local desc="$1" cmd="$2" expect="$3"
    local actual
    actual=$(eval "$cmd" 2>/dev/null || true)
    if echo "$actual" | grep -q "$expect"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "        expected to contain: $expect"
        echo "        got: $actual"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== FedRAMP Compliance Validation ==="

# RHEL-09-215105 / RHEL-09-672030: FIPS crypto policy active
check "FIPS crypto policy set (RHEL-09-215105/672030)" \
    "update-crypto-policies --show" \
    "FIPS"

# RHEL-09-232045 (rootfiles tmpfile.d): both RPM path and admin-override path
check "rootfiles tmpfile.d present at RPM path /usr/lib (RHEL-09-232045)" \
    "test -f /usr/lib/tmpfiles.d/rootfiles.conf && echo PRESENT" \
    "PRESENT"

check "rootfiles tmpfile.d present at /etc (RHEL-09-232045)" \
    "test -f /etc/tmpfiles.d/rootfiles.conf && echo PRESENT" \
    "PRESENT"

check "rootfiles tmpfile.d contains bash_profile entry (RHEL-09-232045)" \
    "cat /etc/tmpfiles.d/rootfiles.conf" \
    "bash_profile"

# SSH RekeyLimit
check "SSH RekeyLimit configured" \
    "cat /etc/ssh/ssh_config.d/02-rekey-limit.conf" \
    "RekeyLimit 512M 1h"

# RHEL-09-232045 (init file perms): all root dotfiles must be 0740 or less
check "root .bash_profile permissions 0740 (RHEL-09-232045)" \
    "stat -c '%a' /root/.bash_profile" \
    "740"

check "root .bashrc permissions 0740 (RHEL-09-232045)" \
    "stat -c '%a' /root/.bashrc" \
    "740"

check "root .bash_logout permissions 0740 (RHEL-09-232045)" \
    "stat -c '%a' /root/.bash_logout" \
    "740"

check "root .cshrc permissions 0740 (RHEL-09-232045)" \
    "stat -c '%a' /root/.cshrc" \
    "740"

check "root .tcshrc permissions 0740 (RHEL-09-232045)" \
    "stat -c '%a' /root/.tcshrc" \
    "740"

# RHEL-09-232050: interactive user home dirs must be 0750 or less
check "root home dir permissions 0750 (RHEL-09-232050)" \
    "stat -c '%a' /root" \
    "750"

check "/app home dir permissions 0750 (RHEL-09-232050)" \
    "stat -c '%a' /app" \
    "750"

echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="

[ "$FAIL" -eq 0 ]
