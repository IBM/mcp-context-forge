#!/usr/bin/env python3
"""Pre-commit hook: verify GitHub Actions SHA pinning.

Every third-party action referenced via ``uses:`` must be pinned to a full
40-char commit SHA (not a tag or short SHA). Tag refs are mutable and a
compromised tag can inject arbitrary code into CI — pinning to a SHA blocks
that supply-chain vector.

Exit codes:
    0 - all checks pass
    1 - violations detected (printed to stderr)
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _check_sha_pinning() -> list[str]:
    violations: list[str] = []

    for wf_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        try:
            workflow = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            violations.append(f"{wf_path.name}: YAML parse error: {exc}")
            continue
        if not workflow:
            continue

        for job_name, job in workflow.get("jobs", {}).items():
            for step in job.get("steps", []) or []:
                uses = step.get("uses")
                if not uses:
                    continue
                # Local actions (./path) and reusable-workflow calls inside the same repo
                # are not pinnable by SHA; skip.
                if uses.startswith("./") or uses.startswith("../"):
                    continue
                _, _, ref = uses.partition("@")
                if not (len(ref) == 40 and all(ch in "0123456789abcdef" for ch in ref)):
                    violations.append(f"{wf_path.name}:{job_name}: action not pinned to SHA: {uses}")

    return violations


def main() -> int:
    violations = _check_sha_pinning()
    if violations:
        print("CI workflow violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
