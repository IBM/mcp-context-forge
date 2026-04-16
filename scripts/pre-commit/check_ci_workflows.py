#!/usr/bin/env python3
"""Pre-commit hook: verify CI workflow configuration.

Checks that:
- GitHub Actions workflow steps pin third-party actions to full SHAs
- Rust CI workflow structure matches expectations
- Go toolchain version is pinned in workflows and Makefile
- pytest-rust workflow tracks correct paths

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
MAKEFILE_PATH = REPO_ROOT / "Makefile"


def _load_workflow(name: str) -> dict | None:
    path = WORKFLOWS_DIR / name
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _check_sha_pinning() -> list[str]:
    """Verify all third-party actions are pinned to full 40-char SHAs."""
    violations: list[str] = []

    for wf_name in ("rust.yml", "pytest-rust.yml", "pytest.yml"):
        workflow = _load_workflow(wf_name)
        if workflow is None:
            continue

        for job_name, job in workflow.get("jobs", {}).items():
            for step in job.get("steps", []):
                uses = step.get("uses")
                if not uses:
                    continue
                _, _, ref = uses.partition("@")
                if not (len(ref) == 40 and all(ch in "0123456789abcdef" for ch in ref)):
                    violations.append(f"{wf_name}:{job_name}: action not pinned to SHA: {uses}")

    return violations


def _check_rust_workflow() -> list[str]:
    """Verify Rust CI workflow structure."""
    violations: list[str] = []
    workflow = _load_workflow("rust.yml")
    if workflow is None:
        return []

    jobs = workflow.get("jobs", {})
    on_block = workflow.get("on", workflow.get(True, {}))

    # No split PR jobs
    for old_job in ("pr-style", "pr-test", "pr-policy"):
        if old_job in jobs:
            violations.append(f"rust.yml: should not have {old_job} job")

    # Required jobs exist with correct draft-skip condition
    expected_jobs = [
        "rust-build",
        "rust-fmt",
        "rust-clippy",
        "rust-test",
        "rust-test-redis",
        "build-wheels",
        "security-audit",
        "supply-chain-vet",
        "license-check",
        "benchmark-build-check",
        "coverage",
        "documentation",
    ]
    draft_condition = "github.event_name != 'pull_request' || !github.event.pull_request.draft"
    for job_name in expected_jobs:
        if job_name not in jobs:
            violations.append(f"rust.yml: missing job {job_name}")
        elif jobs[job_name].get("if") != draft_condition:
            violations.append(f"rust.yml:{job_name}: missing or wrong draft-skip condition")

    # Trigger paths
    if on_block:
        for event in ("push", "pull_request"):
            paths = on_block.get(event, {}).get("paths", [])
            if "Makefile" not in paths:
                violations.append(f"rust.yml: {event} paths missing Makefile")
            if "mcpgateway/db.py" not in paths:
                violations.append(f"rust.yml: {event} paths missing mcpgateway/db.py")
            if "mcpgateway/alembic/**" not in paths:
                violations.append(f"rust.yml: {event} paths missing mcpgateway/alembic/**")
            if "mcp-servers/rust/**" in paths:
                violations.append(f"rust.yml: {event} paths should not include mcp-servers/rust/**")

    # Benchmark job
    if "benchmark-tests" in jobs:
        violations.append("rust.yml: should not have benchmark-tests job (use benchmark-build-check)")

    if "benchmark-build-check" in jobs:
        job = jobs["benchmark-build-check"]
        if job.get("name") != "Benchmarks (build check only)":
            violations.append("rust.yml:benchmark-build-check: wrong job name")

    return violations


def _check_go_toolchain() -> list[str]:
    """Verify Go toolchain version pinning."""
    violations: list[str] = []

    workflow = _load_workflow("linting-full.yml")
    if workflow:
        steps = workflow.get("jobs", {}).get("linting-full", {}).get("steps", [])
        setup_go = next((s for s in steps if s.get("name") == "Set up Go"), None)
        if setup_go:
            if setup_go.get("with", {}).get("go-version") != "1.26.2":
                violations.append("linting-full.yml: Go version should be 1.26.2")
        else:
            violations.append("linting-full.yml: missing 'Set up Go' step")

    if MAKEFILE_PATH.exists():
        makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
        if "LINT_GO_TOOLCHAIN ?= go1.26.2" not in makefile:
            violations.append("Makefile: missing LINT_GO_TOOLCHAIN ?= go1.26.2")

    return violations


def _check_pytest_rust_workflow() -> list[str]:
    """Verify pytest-rust workflow configuration."""
    violations: list[str] = []
    workflow = _load_workflow("pytest-rust.yml")
    if workflow is None:
        return []

    on_block = workflow.get("on", workflow.get(True, {}))
    if on_block:
        for event in ("push", "pull_request"):
            paths = on_block.get(event, {}).get("paths", [])
            if "Makefile" in paths:
                violations.append(f"pytest-rust.yml: {event} paths should not include Makefile")
            if "mcp-servers/rust/**" in paths:
                violations.append(f"pytest-rust.yml: {event} paths should not include mcp-servers/rust/**")

    test_job = workflow.get("jobs", {}).get("test", {})
    env = test_job.get("env", {})
    if env.get("REQUIRE_RUST") != "1":
        violations.append("pytest-rust.yml: test job should set REQUIRE_RUST=1")

    return violations


def main() -> int:
    violations: list[str] = []
    violations.extend(_check_sha_pinning())
    violations.extend(_check_rust_workflow())
    violations.extend(_check_go_toolchain())
    violations.extend(_check_pytest_rust_workflow())

    if violations:
        print("CI workflow violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
