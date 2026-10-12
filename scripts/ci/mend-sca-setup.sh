#!/usr/bin/env bash
# mend-sca-setup.sh — pre-scan dependency installer for the Mend SCA CLI
#
# Sourced (not executed) by the IBM DevSecOps One Pipeline via the
# mend-custom-script-path property before `mend dep` runs. Its job is to
# ensure the package managers present in this repo are resolvable:
#
#   uv    — used by pyproject.toml / plugins/external/*/pyproject.toml
#   cargo — used by Cargo.toml / crates/*/Cargo.toml
#
# The pipeline container is UBI9 (amd64). Neither tool is pre-installed.
# Tracked-by: github.ibm.com/contextforge-org/internal_issues#1086
#             github.ibm.com/brian-hussey/workflow_mgr#111
#
# NOTE: This file is sourced, not run in a subshell. Do NOT use set -e or
# set -u here — they would propagate to the parent pipeline shell and cause
# unrelated subsequent steps to fail.

# ── uv ────────────────────────────────────────────────────────────────────────

if ! command -v uv &>/dev/null; then
  echo "[mend-sca-setup] Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # The installer drops the binary into ~/.local/bin; export for child processes
  export PATH="$HOME/.local/bin:$PATH"
  echo "[mend-sca-setup] uv installed: $(uv --version)"
else
  echo "[mend-sca-setup] uv already present: $(uv --version)"
fi

# ── cargo / rustup ────────────────────────────────────────────────────────────

if ! command -v cargo &>/dev/null; then
  echo "[mend-sca-setup] Installing Rust toolchain via rustup..."
  curl -LsSf https://sh.rustup.rs | sh -s -- -y --profile minimal --no-modify-path
  export PATH="$HOME/.cargo/bin:$PATH"
  echo "[mend-sca-setup] cargo installed: $(cargo --version)"
else
  echo "[mend-sca-setup] cargo already present: $(cargo --version)"
fi

# Export the updated PATH so the Mend SCA CLI inherits it
export PATH
echo "[mend-sca-setup] Setup complete. PATH=$PATH"
