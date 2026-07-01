#!/usr/bin/env python3
"""Pre-commit hook: verify deny.toml RUSTSEC advisory ignore list.

A set of RUSTSEC advisories has been explicitly triaged and added to
``deny.toml``'s ``advisories.ignore`` list. Accidentally removing an entry
would silently re-enable an alert that the team has already assessed as
not-applicable while the affected dependency path remains present. Adding new
entries is fine (requires human review), but removing these specific ones
without removing the dependency path is not.

Exit codes:
    0 - all required advisory ignores present
    1 - one or more missing (printed to stderr)
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DENY_TOML = REPO_ROOT / "deny.toml"
CARGO_LOCK = REPO_ROOT / "Cargo.lock"

REQUIRED_ADVISORY_IGNORES = {
    "RUSTSEC-2025-0075",
    "RUSTSEC-2025-0080",
    "RUSTSEC-2025-0081",
    "RUSTSEC-2025-0090",
    "RUSTSEC-2025-0098",
    "RUSTSEC-2025-0100",
}

RUST_UNIC_PACKAGES = {
    "rustpython-parser",
    "rustpython-parser-core",
    "rustpython-ast",
    "unic-char-property",
    "unic-char-range",
    "unic-common",
    "unic-emoji-char",
    "unic-ucd-ident",
    "unic-ucd-version",
}


def lock_contains_rust_unic_path() -> bool:
    if not CARGO_LOCK.exists():
        return False

    lock = tomllib.loads(CARGO_LOCK.read_text(encoding="utf-8"))
    packages = {package.get("name") for package in lock.get("package", [])}
    return bool(RUST_UNIC_PACKAGES & packages)


def main() -> int:
    if not DENY_TOML.exists() or not lock_contains_rust_unic_path():
        return 0

    config = tomllib.loads(DENY_TOML.read_text(encoding="utf-8"))
    actual = set(config.get("advisories", {}).get("ignore", []))
    missing = REQUIRED_ADVISORY_IGNORES - actual

    if missing:
        print("Rust workspace violations:", file=sys.stderr)
        print(f"  deny.toml: missing advisory ignores: {sorted(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
