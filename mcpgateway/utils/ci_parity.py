"""Best-effort local GitHub CI parity runner for ``make ci``.

This module tries to match the workflows GitHub Actions would select for a
branch diff against ``main`` and then run local equivalents where possible.
It is a practical predictor, not a guarantee: some jobs are only approximated,
some GitHub-hosted behavior cannot be reproduced locally, and local toolchain
differences can still affect results.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_BASE_REF = "origin/main"
WORKFLOW_DIR = Path(".github/workflows")


@dataclass(frozen=True)
class SelectedJob:
    """A workflow job selected for the local CI union."""

    workflow_file: str
    workflow_name: str
    job_id: str
    job_name: str
    modes: tuple[str, ...]


@dataclass(frozen=True)
class PlannedJob:
    """A selected workflow job mapped to a local execution strategy."""

    workflow_file: str
    workflow_name: str
    job_id: str
    job_name: str
    modes: tuple[str, ...]
    parity: str
    commands: tuple[str, ...]
    notes: tuple[str, ...]


def _workflow_on_block(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return the parsed workflow trigger block regardless of YAML loader shape."""

    return workflow.get("on", workflow.get(True, {}))


def _load_workflows(repo_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Load all GitHub workflow YAML files from the repository."""

    workflows: list[tuple[Path, dict[str, Any]]] = []
    for workflow_path in sorted((repo_root / WORKFLOW_DIR).glob("*.yml")):
        with workflow_path.open(encoding="utf-8") as handle:
            workflows.append((workflow_path, yaml.safe_load(handle)))
    return workflows


def _normalize_path(path: str) -> str:
    """Normalize a repository-relative path for trigger matching."""

    return path.strip().lstrip("./")


def _matches_pattern(path: str, pattern: str) -> bool:
    """Check whether a changed file matches a workflow path pattern."""

    normalized_path = _normalize_path(path)
    normalized_pattern = _normalize_path(pattern)
    return fnmatch.fnmatchcase(normalized_path, normalized_pattern)


def _matches_paths(changed_files: list[str], patterns: list[str]) -> bool:
    """Return whether any changed file satisfies a workflow paths filter."""

    positive_patterns = [pattern for pattern in patterns if not pattern.startswith("!")]
    negative_patterns = [pattern[1:] for pattern in patterns if pattern.startswith("!")]

    if not positive_patterns:
        return False

    for changed_file in changed_files:
        if any(_matches_pattern(changed_file, pattern) for pattern in positive_patterns):
            if any(_matches_pattern(changed_file, pattern) for pattern in negative_patterns):
                continue
            return True
    return False


def _event_matches(on_block: dict[str, Any], event_name: str, changed_files: list[str]) -> bool:
    """Return whether a workflow event would trigger for the current change set."""

    event_block = on_block.get(event_name)
    if not event_block:
        return False

    branches = event_block.get("branches") or []
    if branches and "main" not in branches:
        return False

    paths = event_block.get("paths") or []
    if not paths:
        return True
    return _matches_paths(changed_files, paths)


def _job_matches_event(job_definition: dict[str, Any], event_name: str, pr_draft: bool) -> bool:
    """Apply the subset of workflow-level job conditions needed for local parity."""

    condition = str(job_definition.get("if", "")).strip()
    if not condition:
        return True

    normalized = " ".join(condition.split())

    if "workflow_dispatch" in normalized or "github.event_name == 'release'" in normalized or "github.event.release" in normalized:
        return False
    if "startsWith(github.ref, 'refs/tags/')" in normalized:
        return False
    if normalized == "github.event_name != 'pull_request'":
        return event_name != "pull_request"
    if normalized == "github.event_name == 'pull_request'":
        return event_name == "pull_request"
    if "github.event_name != 'pull_request' || !github.event.pull_request.draft" in normalized:
        return event_name != "pull_request" or not pr_draft
    if "github.event_name == 'pull_request'" in normalized and "github.base_ref" in normalized:
        return event_name == "pull_request"

    return True


def _selected_modes(modes: set[str]) -> tuple[str, ...]:
    """Return selected trigger modes in stable display order."""

    ordered_modes = [mode for mode in ("pr", "push") if mode in modes]
    return tuple(ordered_modes)


def select_ci_jobs(repo_root: Path, changed_files: list[str] | None = None, pr_draft: bool = False, base_ref: str = DEFAULT_BASE_REF) -> list[SelectedJob]:
    """Select the union of jobs that would run for PR-to-main and push-to-main."""

    changed = [_normalize_path(path) for path in (changed_files or derive_changed_files(repo_root, base_ref))]
    job_index: dict[tuple[str, str], dict[str, Any]] = {}

    for workflow_path, workflow in _load_workflows(repo_root):
        on_block = _workflow_on_block(workflow)
        workflow_file = str(workflow_path.relative_to(repo_root))
        workflow_name = workflow.get("name", workflow_path.stem)

        event_matches = {
            "pr": _event_matches(on_block, "pull_request", changed),
            "push": _event_matches(on_block, "push", changed),
        }

        if not any(event_matches.values()):
            continue

        for job_id, job_definition in (workflow.get("jobs") or {}).items():
            modes: set[str] = set()
            if event_matches["pr"] and _job_matches_event(job_definition, "pull_request", pr_draft):
                modes.add("pr")
            if event_matches["push"] and _job_matches_event(job_definition, "push", pr_draft):
                modes.add("push")
            if not modes:
                continue

            key = (workflow_file, job_id)
            job_index[key] = {
                "workflow_file": workflow_file,
                "workflow_name": workflow_name,
                "job_id": job_id,
                "job_name": job_definition.get("name", job_id),
                "modes": _selected_modes(modes),
            }

    return [SelectedJob(**job) for _, job in sorted(job_index.items())]


def build_execution_plan(repo_root: Path, changed_files: list[str] | None = None, pr_draft: bool = False, base_ref: str = DEFAULT_BASE_REF) -> list[PlannedJob]:
    """Map selected jobs to concrete local commands plus parity metadata."""

    selected_jobs = select_ci_jobs(repo_root=repo_root, changed_files=changed_files, pr_draft=pr_draft, base_ref=base_ref)
    return [_plan_job(job, base_ref=base_ref) for job in selected_jobs]


def derive_changed_files(repo_root: Path, base_ref: str = DEFAULT_BASE_REF) -> list[str]:
    """Derive changed files relative to the merge-base with the configured base ref."""

    merge_base = subprocess.check_output(
        ["git", "merge-base", "HEAD", base_ref],
        cwd=repo_root,
        text=True,
    ).strip()
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{merge_base}..HEAD"],
        cwd=repo_root,
        text=True,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def _multiline(*lines: str) -> str:
    """Build a strict bash snippet from multiple lines."""

    return "set -euo pipefail\n" + "\n".join(lines)


def _plan_job(job: SelectedJob, base_ref: str) -> PlannedJob:  # noqa: PLR0911
    """Map one selected workflow job to a local execution strategy."""

    workflow_file = job.workflow_file
    job_id = job.job_id
    modes = set(job.modes)

    if workflow_file == ".github/workflows/pre-commit.yml" and job_id == "pre-commit":
        return _planned(
            job,
            "exact",
            [
                _multiline(
                    "TMP_INDEX=$(mktemp)",
                    'cleanup() { rm -f "$TMP_INDEX"; }',
                    "trap cleanup EXIT",
                    'export GIT_INDEX_FILE="$TMP_INDEX"',
                    "git read-tree HEAD",
                    "git add -A",
                    "make --no-print-directory pre-commit",
                )
            ],
        )

    if workflow_file == ".github/workflows/lint.yml" and job_id == "python-lint":
        return _planned(
            job,
            "exact",
            [
                "uv tool run ruff==0.15.1 check mcpgateway",
                'uv tool run vulture==2.14 mcpgateway --min-confidence 80 --exclude "*_pb2.py,*_pb2_grpc.py"',
                "uv tool run --with-editable . --with pylint-pydantic==0.3.5 pylint==3.3.9 mcpgateway --rcfile=.pylintrc.mcpgateway --fail-on E --fail-under=10",
                "uv tool run interrogate==1.7.0 -vv mcpgateway --fail-under 100",
                "uv tool run radon==6.0.1 cc mcpgateway --min C --show-complexity && uv tool run radon==6.0.1 mi mcpgateway --min B",
                "uv tool run ruff==0.15.1 check plugins",
                'uv tool run vulture==2.14 plugins --min-confidence 80 --exclude "*_pb2.py,*_pb2_grpc.py"',
                "uv tool run --with-editable . --with pylint-pydantic==0.3.5 pylint==3.3.9 plugins --rcfile=.pylintrc.plugins --fail-on E --fail-under=10",
                "uv tool run interrogate==1.7.0 -vv plugins --fail-under 100",
                "uv tool run radon==6.0.1 cc plugins --min C --show-complexity && uv tool run radon==6.0.1 mi plugins --min B",
            ],
        )

    if workflow_file == ".github/workflows/lint.yml" and job_id == "syntax-check":
        return _planned(
            job,
            "exact",
            [
                "uv tool run yamllint==1.38.0 -c .yamllint .",
                _multiline(
                    "if ! command -v jq >/dev/null 2>&1; then",
                    "  echo 'jq is required for local CI syntax-check parity.'",
                    "  exit 1",
                    "fi",
                    "find . -type f -name '*.json' -not -path './node_modules/*' -print0 | xargs -0 -I{} jq empty '{}'",
                ),
                _multiline(
                    "find . -type f -name '*.toml' \\",
                    "  -not -path './plugin_templates/*' \\",
                    "  -not -path './mcp-servers/templates/*' \\",
                    "  -print0 | xargs -0 -I{} uv tool run tomlcheck==0.2.3 '{}'",
                ),
            ],
        )

    if workflow_file == ".github/workflows/pytest.yml" and job_id == "test":
        commands = [
            _multiline(
                "uv run --extra plugins pytest -n auto \\",
                "  --durations=10 \\",
                "  --ignore=tests/fuzz \\",
                "  --ignore=tests/e2e/test_entra_id_integration.py \\",
                "  --cov=mcpgateway \\",
                "  --cov-report=xml \\",
                "  --cov-report=html \\",
                "  --cov-report=term \\",
                "  --cov-branch \\",
                "  --cov-fail-under=95",
            ),
        ]
        if "pr" in modes:
            commands.append(f"uv run diff-cover coverage.xml --compare-branch={shlex.quote(base_ref)} --fail-under=93")
        commands.extend(
            [
                _multiline(
                    "uv run pytest -n auto \\",
                    "  --doctest-modules mcpgateway/ \\",
                    "  --cov=mcpgateway \\",
                    "  --cov-report=term \\",
                    "  --cov-report=json:doctest-coverage.json \\",
                    "  --cov-fail-under=30 \\",
                    "  --tb=short",
                ),
                _multiline(
                    'uv run python3 -c "',
                    "import subprocess, sys",
                    "result = subprocess.run(['uv', 'run', 'python3', '-m', 'pytest', '--doctest-modules', 'mcpgateway/', '--tb=no', '-q'], capture_output=True)",
                    "if result.returncode == 0:",
                    "    print('✅ All doctests passing')",
                    "else:",
                    "    print('❌ Doctest failures detected')",
                    "    print(result.stdout.decode())",
                    "    print(result.stderr.decode())",
                    "    sys.exit(1)",
                    '"',
                ),
            ]
        )
        return _planned(job, "exact", commands)

    if workflow_file == ".github/workflows/python-package.yml" and job_id == "build-package":
        return _planned(
            job,
            "exact",
            [
                "python3 -m pip install --upgrade pip",
                "python3 -m pip install build uv==0.11.1",
                "make --no-print-directory venv",
                "make --no-print-directory dist",
                "python3 -m pip install twine check-manifest pyroma",
                "twine check dist/*",
                "check-manifest",
                "pyroma -d .",
            ],
            notes=("Artifact upload intentionally omitted locally.",),
        )

    if workflow_file == ".github/workflows/linting-full.yml" and job_id == "linting-full":
        return _planned(
            job,
            "exact",
            [
                "make --no-print-directory sri-verify",
                f"make --no-print-directory linting-full COMMITLINT_FROM=$(git merge-base HEAD {shlex.quote(base_ref)}) COMMITLINT_TO=HEAD",
            ],
        )

    if workflow_file == ".github/workflows/lint-web.yml" and job_id == "lint-web":
        return _planned(
            job,
            "approx",
            [
                _multiline(
                    "npm install --no-save --legacy-peer-deps htmlhint",
                    "npx htmlhint 'mcpgateway/templates/*.html'",
                ),
                _multiline(
                    "npm install --no-save --legacy-peer-deps stylelint stylelint-config-standard @stylistic/stylelint-config stylelint-order",
                    "npx stylelint 'mcpgateway/static/*.css'",
                ),
                _multiline(
                    "npm install --no-save eslint neostandard eslint-config-prettier eslint-plugin-prettier prettier",
                    "npx eslint 'mcpgateway/static/*.js'",
                ),
                _multiline(
                    "npm install --no-save --legacy-peer-deps retire",
                    "npx retire --path mcpgateway/static",
                ),
                _multiline(
                    "if [ ! -f package.json ]; then npm init -y >/dev/null; fi",
                    "npm audit --audit-level=high || true",
                ),
                _multiline(
                    "npm install --no-save --legacy-peer-deps jshint",
                    "if [ -f .jshintrc ]; then",
                    "  npx jshint --config .jshintrc 'mcpgateway/static/*.js'",
                    "else",
                    "  npx jshint --esversion=11 'mcpgateway/static/*.js'",
                    "fi",
                ),
                _multiline(
                    "npm install --no-save --legacy-peer-deps jscpd",
                    "npx jscpd 'mcpgateway/static/' 'mcpgateway/templates/'",
                ),
            ],
            notes=("Node/npm bootstrap is not reproduced locally; GitHub pins Node 20, upgrades npm, and sets the npm registry before running these checks.",),
        )

    if workflow_file == ".github/workflows/lint-web.yml" and job_id == "nodejsscan":
        return _planned(
            job,
            "exact",
            [
                "python3 -m pip install --upgrade pip",
                "pip install nodejsscan",
                "nodejsscan --directory ./mcpgateway/static",
            ],
        )

    if workflow_file == ".github/workflows/vitest.yml" and job_id == "vitest":
        return _planned(
            job,
            "approx",
            ["npm ci", "npx vitest run"],
            notes=("Node/npm bootstrap is not reproduced locally; GitHub pins Node 20 and upgrades npm before running Vitest.",),
        )

    if workflow_file == ".github/workflows/license-check.yml" and job_id == "license-check":
        return _planned(
            job,
            "exact",
            ["make --no-print-directory license-check"],
            notes=("Artifact upload intentionally omitted locally.",),
        )

    if workflow_file == ".github/workflows/dependency-review.yml" and job_id == "dependency-review":
        return _planned(
            job,
            "not_reproducible",
            [],
            notes=("GitHub dependency-review-action has no local equivalent in this repo.",),
        )

    if workflow_file == ".github/workflows/docker-scan.yml" and job_id == "scan":
        return _planned(
            job,
            "exact",
            [
                "docker buildx build -f Containerfile.lite --platform linux/amd64 --load --tag mcp-context-forge-scan:scan .",
                'docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD:/work" anchore/syft:v1.42.3 docker:mcp-context-forge-scan:scan -o spdx-json=/work/sbom.spdx.json',
            ],
            notes=("Artifact upload intentionally omitted locally.",),
        )

    if workflow_file == ".github/workflows/docker-scan.yml" and job_id == "rust-enabled-build":
        return _planned(
            job,
            "exact",
            [
                "docker buildx build -f Containerfile.lite --platform linux/amd64 --build-arg ENABLE_RUST=true .",
            ],
        )

    if workflow_file == ".github/workflows/docker-multiplatform.yml" and job_id == "build":
        return _planned(
            job,
            "approx",
            [
                "docker buildx build -f Containerfile.lite --platform linux/amd64 --load --tag mcp-context-forge-ci:amd64 .",
            ],
            notes=("Local CI only reproduces the amd64 build. Push-time arm64/s390x/ppc64le builds remain uncovered.",),
        )

    if workflow_file == ".github/workflows/docker-multiplatform.yml" and job_id in {"manifest", "sign"}:
        return _planned(
            job,
            "not_reproducible",
            [],
            notes=("Manifest publishing and signing are intentionally blocked in local CI.",),
        )

    if workflow_file == ".github/workflows/helm-publish.yml" and job_id == "lint":
        return _planned(
            job,
            "exact",
            [
                "helm lint charts/mcp-stack --strict",
                "helm template mcp-stack charts/mcp-stack --debug > /dev/null",
            ],
        )

    if workflow_file == ".github/workflows/playwright.yml" and job_id == "playwright-ci-smoke":
        return _planned(
            job,
            "exact",
            [
                _multiline(
                    "export TEST_BASE_URL=http://127.0.0.1:4444",
                    "export GUNICORN_WORKERS=1",
                    "export MCPGATEWAY_UI_ENABLED=true",
                    "export MCPGATEWAY_ADMIN_API_ENABLED=true",
                    "export SECURE_COOKIES=false",
                    "export PLAYWRIGHT_INSTALL_FLAGS=--with-deps",
                    "cleanup() {",
                    "  status=$?",
                    '  if [ -f /tmp/mcpgateway-ci.pid ] && kill -0 "$(cat /tmp/mcpgateway-ci.pid)" 2>/dev/null; then',
                    '    kill "$(cat /tmp/mcpgateway-ci.pid)" || true',
                    "    sleep 1",
                    "  fi",
                    "  if [ $status -ne 0 ]; then",
                    "    tail -n 250 /tmp/mcpgateway-ci.log || true",
                    "  fi",
                    "}",
                    "trap cleanup EXIT",
                    "make --no-print-directory venv install",
                    "npm ci",
                    "npm run vite:build",
                    "cp .env.example .env",
                    "make --no-print-directory serve > /tmp/mcpgateway-ci.log 2>&1 &",
                    "echo $! > /tmp/mcpgateway-ci.pid",
                    "for _ in {1..120}; do",
                    '  if curl -fsS "$TEST_BASE_URL/health" >/dev/null; then break; fi',
                    '  if ! kill -0 "$(cat /tmp/mcpgateway-ci.pid)" 2>/dev/null; then exit 1; fi',
                    "  sleep 1",
                    "done",
                    'curl -fsS "$TEST_BASE_URL/health" >/dev/null',
                    "make --no-print-directory test-ui-ci-smoke",
                )
            ],
            notes=("Artifact upload intentionally omitted locally.",),
        )

    if workflow_file == ".github/workflows/alembic-upgrade-validation.yml" and job_id == "upgrade-validation":
        return _planned(job, "exact", ["bash scripts/ci/run_upgrade_validation.sh"], notes=("Artifact upload intentionally omitted locally.",))

    if workflow_file == ".github/workflows/pytest-rust.yml" and job_id == "test":
        return _planned(
            job,
            "exact",
            [
                _multiline(
                    "docker rm -f ci-parity-redis >/dev/null 2>&1 || true",
                    "docker run -d --rm --name ci-parity-redis -p 6379:6379 redis:7-bookworm >/dev/null",
                    "cleanup() { docker rm -f ci-parity-redis >/dev/null 2>&1 || true; }",
                    "trap cleanup EXIT",
                    "export REQUIRE_RUST=1",
                    "export AUTH_ENCRYPTION_SECRET=ci-rust-auth-encryption-secret-1234567890",
                    "export REDIS_URL=redis://127.0.0.1:6379/0",
                    "export MCP_RUST_REDIS_URL=redis://127.0.0.1:6379/0",
                    "make --no-print-directory rust-install",
                    "make --no-print-directory rust-verify-stubs",
                    "uv run --extra plugins pytest -n 0 \\",
                    "  --durations=5 \\",
                    "  --ignore=tests/fuzz \\",
                    "  --ignore=tests/e2e/test_entra_id_integration.py \\",
                    "  --cov=mcpgateway \\",
                    "  --cov-report=xml \\",
                    "  --cov-report=html \\",
                    "  --cov-report=term \\",
                    "  --cov-branch \\",
                    "  --cov-fail-under=95",
                    f"uv run diff-cover coverage.xml --compare-branch={shlex.quote(base_ref)} --fail-under=93",
                    "uv run --extra plugins pytest -n 0 \\",
                    "  --doctest-modules mcpgateway/ \\",
                    "  --cov=mcpgateway \\",
                    "  --cov-report=term \\",
                    "  --cov-report=json:doctest-coverage.json \\",
                    "  --cov-fail-under=30 \\",
                    "  --tb=short",
                )
            ],
        )

    if workflow_file == ".github/workflows/rust.yml" and job_id == "rust-build":
        return _planned(
            job,
            "approx",
            [
                "make --no-print-directory rust-build-check",
                "make --no-print-directory rust-stub-gen",
                "make --no-print-directory rust-verify-stubs",
            ],
            notes=("GitHub runs this job on both ubuntu-latest and macos-latest; local CI only checks the current host OS.",),
        )

    if workflow_file == ".github/workflows/rust.yml" and job_id == "rust-fmt":
        return _planned(job, "exact", ["make --no-print-directory rust-fmt-check"])

    if workflow_file == ".github/workflows/rust.yml" and job_id == "rust-clippy":
        return _planned(job, "exact", ["make --no-print-directory rust-lint"])

    if workflow_file == ".github/workflows/rust.yml" and job_id == "rust-test":
        return _planned(job, "exact", ["make --no-print-directory rust-test"])

    if workflow_file == ".github/workflows/rust.yml" and job_id == "rust-test-redis":
        return _planned(
            job,
            "exact",
            [
                _multiline(
                    "docker rm -f ci-parity-redis >/dev/null 2>&1 || true",
                    "docker run -d --rm --name ci-parity-redis -p 6379:6379 redis:7-bookworm >/dev/null",
                    "cleanup() { docker rm -f ci-parity-redis >/dev/null 2>&1 || true; }",
                    "trap cleanup EXIT",
                    "export AUTH_ENCRYPTION_SECRET=ci-rust-auth-encryption-secret-1234567890",
                    "export REDIS_URL=redis://127.0.0.1:6379/0",
                    "export MCP_RUST_REDIS_URL=redis://127.0.0.1:6379/0",
                    "cargo test -p contextforge_mcp_runtime --test runtime",
                )
            ],
        )

    if workflow_file == ".github/workflows/rust.yml" and job_id == "build-wheels":
        return _planned(
            job,
            "approx",
            ["make --no-print-directory rust-build-wheels"],
            notes=("GitHub builds wheels on both ubuntu-latest and macos-latest; local CI only checks the current host OS.",),
        )

    if workflow_file == ".github/workflows/rust.yml" and job_id == "security-audit":
        return _planned(job, "exact", ["make --no-print-directory rust-deny"])

    if workflow_file == ".github/workflows/rust.yml" and job_id == "supply-chain-vet":
        return _planned(job, "exact", ["make --no-print-directory rust-vet"])

    if workflow_file == ".github/workflows/rust.yml" and job_id == "license-check":
        return _planned(job, "exact", ["make --no-print-directory rust-licenses"])

    if workflow_file == ".github/workflows/rust.yml" and job_id == "benchmark-build-check":
        return _planned(job, "exact", ["make --no-print-directory rust-bench-check"])

    if workflow_file == ".github/workflows/rust.yml" and job_id == "coverage":
        return _planned(job, "exact", ["make --no-print-directory rust-coverage"], notes=("Artifact upload intentionally omitted locally.",))

    if workflow_file == ".github/workflows/rust.yml" and job_id == "documentation":
        return _planned(job, "exact", ["make --no-print-directory rust-doc"], notes=("Artifact upload intentionally omitted locally.",))

    if workflow_file == ".github/workflows/wrapper.yml" and job_id == "wrapper-e2e":
        return _planned(
            job,
            "exact",
            [
                _multiline(
                    "SECRET=$(openssl rand -base64 32)",
                    'export JWT_SECRET_KEY="$SECRET"',
                    "export GUNICORN_WORKERS=1",
                    "export MCPGATEWAY_UI_ENABLED=true",
                    "export MCPGATEWAY_ADMIN_API_ENABLED=true",
                    "export SSRF_PROTECTION_ENABLED=false",
                    "export ADMIN_REQUIRE_PASSWORD_CHANGE_ON_BOOTSTRAP=false",
                    "export PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false",
                    "make --no-print-directory venv",
                    "make --no-print-directory install",
                    "make --no-print-directory stop-serve || true",
                    "make --no-print-directory serve >/tmp/wrapper-gateway.log 2>&1 &",
                    "GATEWAY_PID=$!",
                    'cleanup() { kill "$GATEWAY_PID" >/dev/null 2>&1 || true; if [ -f fast-time-server.pid ]; then kill "$(cat fast-time-server.pid)" >/dev/null 2>&1 || true; fi; }',
                    "trap cleanup EXIT",
                    "for i in {1..60}; do",
                    "  if curl -s http://localhost:4444 >/dev/null 2>&1; then break; fi",
                    "  sleep 1",
                    "done",
                    'TOKEN=$(uv run --no-dev python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret "$JWT_SECRET_KEY")',
                    "curl -sf -X GET http://localhost:4444/version -H \"Authorization: Bearer $TOKEN\" -H 'Content-Type: application/json'",
                    "cd mcp-servers/go/fast-time-server && go build -o fast-time-server . && chmod +x fast-time-server && cd - >/dev/null",
                    "pkill -9 -f 'fast-time-server' 2>/dev/null || true",
                    "nohup mcp-servers/go/fast-time-server/fast-time-server -transport=dual -listen=0.0.0.0 -port=8080 -log-level=info > fast-time-server.log 2>&1 &",
                    "echo $! > fast-time-server.pid",
                    "for i in {1..30}; do",
                    "  if curl -s http://localhost:8080/health >/dev/null 2>&1; then break; fi",
                    "  sleep 2",
                    "done",
                    'GATEWAY_RESPONSE=$(curl -s -X POST http://localhost:4444/gateways -H "Authorization: Bearer $TOKEN" -H \'Content-Type: application/json\' -d \'{"name":"fast_time","url":"http://localhost:8080/http","transport":"STREAMABLEHTTP"}\')',
                    "if echo \"$GATEWAY_RESPONSE\" | grep -q 'already exists'; then",
                    '  GATEWAYS=$(curl -s http://localhost:4444/gateways -H "Authorization: Bearer $TOKEN")',
                    '  GATEWAY_ID=$(echo "$GATEWAYS" | jq -r \'.[] | select(.name=="fast_time") | .id\')',
                    "else",
                    "  GATEWAY_ID=$(echo \"$GATEWAY_RESPONSE\" | jq -r '.id')",
                    "fi",
                    "for i in {1..30}; do",
                    '  TOOLS=$(curl -s http://localhost:4444/tools -H "Authorization: Bearer $TOKEN")',
                    '  TOOL_COUNT=$(echo "$TOOLS" | jq --arg gid "$GATEWAY_ID" \'[.[] | select(.gatewayId==$gid)] | length\')',
                    '  if [ "$TOOL_COUNT" -gt 0 ]; then break; fi',
                    "  sleep 2",
                    "done",
                    'TOOLS=$(curl -s http://localhost:4444/tools -H "Authorization: Bearer $TOKEN")',
                    'TOOL_IDS=$(echo "$TOOLS" | jq --arg gid "$GATEWAY_ID" -c \'[.[] | select(.gatewayId==$gid) | .id]\')',
                    'SERVER_RESPONSE=$(curl -s -X POST http://localhost:4444/servers -H "Authorization: Bearer $TOKEN" -H \'Content-Type: application/json\' -d "{\\"server\\":{\\"id\\":\\"9779b6698cbd4b4995ee04a4fab38737\\",\\"name\\":\\"Fast Time Server\\",\\"description\\":\\"Virtual server exposing Fast Time MCP tools\\",\\"associated_tools\\":$TOOL_IDS,\\"associated_resources\\":[],\\"associated_prompts\\":[]}}")',
                    "cd crates/wrapper",
                    "cargo build --release --features integration-test",
                    "cd - >/dev/null",
                    'URL="http://localhost:4444/servers/9779b6698cbd4b4995ee04a4fab38737/mcp"',
                    'AUTH="Bearer $TOKEN"',
                    'WRAPPER_BIN="target/release/mcp_stdio_wrapper"',
                    'URL="$URL" AUTH="$AUTH" WRAPPER_BIN="$WRAPPER_BIN" ./target/release/wrapper_integration',  # pragma: allowlist secret
                )
            ],
            notes=("Failure-only artifact upload intentionally omitted locally.",),
        )

    return _planned(job, "not_reproducible", [], notes=("No local runner mapping is defined for this job.",))


def _planned(job: SelectedJob, parity: str, commands: list[str], notes: tuple[str, ...] = ()) -> PlannedJob:
    """Create a planned job record from a selected job and local mapping."""

    return PlannedJob(
        workflow_file=job.workflow_file,
        workflow_name=job.workflow_name,
        job_id=job.job_id,
        job_name=job.job_name,
        modes=job.modes,
        parity=parity,
        commands=tuple(commands),
        notes=notes,
    )


def _parse_changed_files(raw_value: str) -> list[str]:
    """Parse CI_CHANGED_FILES from newline- or comma-separated text."""

    parts: list[str] = []
    for chunk in raw_value.replace(",", "\n").splitlines():
        value = chunk.strip()
        if value:
            parts.append(value)
    return parts


def _run_command(command: str, repo_root: Path) -> None:
    """Execute one mapped shell command inside the repository root."""

    subprocess.run(["bash", "-lc", command], cwd=repo_root, check=True)


def _gap_exit_code(approx_count: int, unreproducible_count: int, strict: bool) -> int:
    """Return the process exit code for parity gaps."""

    if (approx_count or unreproducible_count) and strict:
        return 2
    return 0


def run_ci(repo_root: Path, base_ref: str = DEFAULT_BASE_REF, changed_files: list[str] | None = None, pr_draft: bool = False, allow_approx: bool = True, list_only: bool = False) -> int:
    """Execute the selected local CI job plan and report parity gaps.

    This is best-effort matching for GitHub CI, not a formal guarantee of the
    eventual GitHub result. Approximated and non-reproducible jobs are reported
    explicitly, and best-effort mode can tolerate those gaps.
    """

    actual_changed_files = changed_files or derive_changed_files(repo_root, base_ref)
    execution_plan = build_execution_plan(repo_root=repo_root, changed_files=actual_changed_files, pr_draft=pr_draft, base_ref=base_ref)

    print("== Changed files ==")
    for changed_file in actual_changed_files:
        print(f"- {changed_file}")

    print("\n== Selected jobs ==")
    for job in execution_plan:
        mode_label = ",".join(job.modes)
        print(f"- [{job.parity}] {job.workflow_name} :: {job.job_name} ({job.workflow_file}:{job.job_id}) modes={mode_label}")
        for note in job.notes:
            print(f"  note: {note}")

    if list_only:
        return 0

    exact_count = 0
    approx_count = 0
    unreproducible_count = 0

    for job in execution_plan:
        if job.parity == "exact":
            exact_count += 1
        elif job.parity == "approx":
            approx_count += 1
        else:
            unreproducible_count += 1

        if not job.commands:
            continue

        print(f"\n== Running {job.workflow_name} :: {job.job_name} ==")
        for command in job.commands:
            print(f"$ {command}")
            _run_command(command, repo_root)

    print("\n== Parity summary ==")
    print(f"exactly reproduced: {exact_count}")
    print(f"locally approximated: {approx_count}")
    print(f"not reproducible locally: {unreproducible_count}")

    if approx_count or unreproducible_count:
        if allow_approx:
            print("CI parity gaps were tolerated in best-effort mode. Set CI_ALLOW_APPROX=0 for strict failure on gaps.")
        else:
            print("CI parity gaps detected and strict mode is enabled.")

    return _gap_exit_code(approx_count=approx_count, unreproducible_count=unreproducible_count, strict=not allow_approx)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for ``python -m mcpgateway.utils.ci_parity``."""

    parser = argparse.ArgumentParser(description="Run a best-effort local approximation of GitHub CI. This predicts workflow coverage but does not guarantee the GitHub result.")
    parser.add_argument("--base-ref", default=os.environ.get("CI_BASE_REF", DEFAULT_BASE_REF))
    parser.add_argument("--changed-files", default=os.environ.get("CI_CHANGED_FILES"))
    parser.add_argument("--pr-draft", action="store_true", default=os.environ.get("CI_PR_DRAFT", "0") == "1")
    parser.add_argument("--allow-approx", action="store_true", default=os.environ.get("CI_ALLOW_APPROX", "1") == "1")
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    changed_files = _parse_changed_files(args.changed_files) if args.changed_files else None
    return run_ci(
        repo_root=repo_root,
        base_ref=args.base_ref,
        changed_files=changed_files,
        pr_draft=args.pr_draft,
        allow_approx=args.allow_approx,
        list_only=args.list_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
