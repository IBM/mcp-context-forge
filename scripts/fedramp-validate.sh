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

# RHEL-09-215105 / RHEL-09-672030: FIPS:STIG crypto sub-policy
check "FIPS:STIG crypto sub-policy set (RHEL-09-215105/672030)" \
    "update-crypto-policies --show" \
    "FIPS:STIG"

# RHEL-09-232045 (rootfiles tmpfile.d): OVAL requires C-type entries with 600 perms
# Check /etc/tmpfiles.d/ (primary path the OVAL validates)
for dotfile in .bash_logout .bash_profile .bashrc .cshrc .tcshrc; do
    check "rootfiles /etc/tmpfiles.d has C 600 entry for ${dotfile} (RHEL-09-232045)" \
        "grep -F \"C /root/${dotfile}\" /etc/tmpfiles.d/rootfiles.conf" \
        "600 root root"
done

# Check /usr/lib/tmpfiles.d/ (RPM-managed path, mirrored for belt-and-suspenders)
for dotfile in .bash_logout .bash_profile .bashrc .cshrc .tcshrc; do
    check "rootfiles /usr/lib/tmpfiles.d has C 600 entry for ${dotfile} (RHEL-09-232045)" \
        "grep -F \"C /root/${dotfile}\" /usr/lib/tmpfiles.d/rootfiles.conf" \
        "600 root root"
done

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

# /app must stay group-owned by root (GID 0): OpenShift's arbitrary-UID model always
# runs containers with GID 0, and 0750 strips "other" access — without group=root,
# arbitrary-UID pods lose all access to /app (ModuleNotFoundError: No module named
# 'gunicorn' at startup). Owner-UID match (10001) still works via owner bits regardless.
check "/app group ownership is root (OpenShift arbitrary-UID compatibility)" \
    "stat -c '%G' /app" \
    "root"

# RHEL-09-232045: /app user dotfiles must be 0740 or less permissive
# -perm /037 matches: group-write (020), group-execute (010), other-rwx (007)
check "/app dotfiles permissions 0740 or less (RHEL-09-232045)" \
    "find /app -maxdepth 1 -name '.*' -type f -perm /037 -printf '%f\n' | sort | tr '\n' ',' | sed 's/,$//'" \
    ""

# Regression guard for WO issue #68373: "ModuleNotFoundError: No module named
# 'gunicorn'" at pod startup has surfaced from two independent FIPS-block root
# causes — (1) /app losing GID-0 access at 0750 (fixed by the group-ownership
# check above) and (2) subscription-manager (RHEL-09-215010) silently
# overwriting /usr/bin/python3 with UBI9's system python3 (3.9), breaking the
# venv interpreter binding. This end-to-end check exercises the actual
# failure mode directly, so either cause — or any future variant — fails here
# instead of in a customer pod.
check "runtime python3 can import gunicorn from the venv (regression: #68373)" \
    "python3 -c 'import gunicorn; print(\"GUNICORN_OK\")'" \
    "GUNICORN_OK"

echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="

[ "$FAIL" -eq 0 ]
