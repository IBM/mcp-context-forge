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

# Findings 1/2/3: FIPS crypto policy active
check "FIPS crypto policy set (findings 1/2/3)" \
    "update-crypto-policies --show" \
    "FIPS"

# Finding 8: rootfiles tmpfile.d configured
check "rootfiles tmpfile.d present (finding 8)" \
    "test -f /etc/tmpfiles.d/rootfiles.conf && echo PRESENT" \
    "PRESENT"

check "rootfiles tmpfile.d contains bash_profile entry (finding 8)" \
    "cat /etc/tmpfiles.d/rootfiles.conf" \
    "bash_profile"

# Finding 9: SSH RekeyLimit configured
check "SSH RekeyLimit configured (finding 9)" \
    "cat /etc/ssh/ssh_config.d/02-rekey-limit.conf" \
    "RekeyLimit 512M 1h"

# Finding 7: root init file permissions <= 0740
check "root .bash_profile permissions 0740 (finding 7)" \
    "stat -c '%a' /root/.bash_profile" \
    "740"

check "root .bashrc permissions 0740 (finding 7)" \
    "stat -c '%a' /root/.bashrc" \
    "740"

check "root .bash_logout permissions 0740 (finding 7)" \
    "stat -c '%a' /root/.bash_logout" \
    "740"

echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="

[ "$FAIL" -eq 0 ]
