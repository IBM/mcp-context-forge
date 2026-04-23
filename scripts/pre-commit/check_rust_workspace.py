#!/usr/bin/env python3
"""Pre-commit hook: verify deny.toml RUSTSEC advisory ignore list.

A set of RUSTSEC advisories has been explicitly triaged and added to
``deny.toml``'s ``advisories.ignore`` list. Accidentally removing an entry
would silently re-enable an alert that the team has already assessed as
not-applicable. Adding new entries is fine (requires human review), but
removing these specific ones without deliberate follow-up is not.

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

REQUIRED_ADVISORY_IGNORES = {
    "RUSTSEC-2025-0075",
    "RUSTSEC-2025-0080",
    "RUSTSEC-2025-0081",
    "RUSTSEC-2025-0090",
    "RUSTSEC-2025-0098",
    "RUSTSEC-2025-0100",
}


def main() -> int:
    if not DENY_TOML.exists():
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
