"""Regression tests for the secrets-baseline-only CI decision workflow."""

from __future__ import annotations

import io
import json
import re
import runpy
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

PRE_COMMIT_WORKFLOW = Path(".github/workflows/pre-commit.yml")
DECISION_SCRIPT = Path(".github/scripts/secret_baseline_ci_decision.py")
MAKEFILE = Path("Makefile")


class _JsonResponse(io.BytesIO):
    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _step_if_expression(step_name: str) -> str:
    lines = PRE_COMMIT_WORKFLOW.read_text(encoding="utf-8").splitlines()
    marker = f"      - name: {step_name}"
    start = lines.index(marker) + 1
    for line in lines[start:]:
        if line.startswith("      - name: "):
            break
        if line.startswith("        if: "):
            return line.removeprefix("        if: ")
    raise AssertionError(f"missing if expression for step {step_name}")


def _run_decision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    event_name: str = "push",
    event: dict[str, Any] | None = None,
    commit_files: list[str | dict[str, Any]] | None = None,
    parent_sha: str = "previous",
    successful_head_sha: str | None = None,
    successful_run_branch: str = "main",
    successful_run_event: str = "push",
    fail_commit_api: bool = False,
    fail_workflow_runs_api: bool = False,
    ref_type: str = "branch",
    forbid_api_calls: bool = False,
) -> str:
    output = tmp_path / "github-output"
    summary = tmp_path / "github-summary"
    event_payload = event or {"after": "latest", "before": "stale-before", "repository": {"default_branch": "main"}}

    env = {
        "GH_TOKEN": "token",
        "WORKFLOW_FILE": "pytest.yml",
        "EVENT_NAME": event_name,
        "EVENT_JSON": json.dumps(event_payload),
        "GITHUB_API_URL": "https://api.github.test",
        "GITHUB_REPOSITORY_NAME": "owner/repo",
        "GITHUB_REF_TYPE_VALUE": ref_type,
        "GITHUB_SHA_VALUE": "latest",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def fake_urlopen(request: urllib.request.Request, timeout: int = 20) -> _JsonResponse:
        if forbid_api_calls:
            raise AssertionError(f"unexpected API request: {request.full_url}")
        assert timeout == 20
        url = urllib.parse.urlparse(request.full_url)
        query = urllib.parse.parse_qs(url.query)

        if url.path == "/repos/owner/repo/commits/latest":
            if fail_commit_api:
                raise OSError("api unavailable")
            files = [item if isinstance(item, dict) else {"filename": item, "status": "modified"} for item in (commit_files or [])]
            payload = {
                "files": files,
                "parents": [{"sha": parent_sha}] if parent_sha else [],
            }
            return _JsonResponse(json.dumps(payload).encode("utf-8"))

        if url.path == "/repos/owner/repo/actions/workflows/pytest.yml/runs":
            if fail_workflow_runs_api:
                raise OSError("workflow runs unavailable")
            assert query.get("event") == [event_name]
            if event_name == "push":
                assert query.get("branch") == ["main"]
                assert query.get("exclude_pull_requests") == ["true"]
            else:
                assert "branch" not in query
                assert "exclude_pull_requests" not in query
            assert query.get("status") == ["success"]
            workflow_runs = []
            if query.get("head_sha") == [successful_head_sha]:
                workflow_runs.append({"event": successful_run_event, "head_branch": successful_run_branch, "head_sha": successful_head_sha})
            return _JsonResponse(json.dumps({"total_count": len(workflow_runs), "workflow_runs": workflow_runs}).encode("utf-8"))

        raise AssertionError(f"unexpected API request: {request.full_url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(DECISION_SCRIPT), run_name="__main__")
    assert exc.value.code == 0

    return output.read_text(encoding="utf-8")


def test_pull_request_baseline_only_without_previous_success_runs_full_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        event_name="pull_request",
        event={"pull_request": {"head": {"sha": "latest", "repo": {"full_name": "owner/repo"}}}},
        commit_files=[".secrets.baseline"],
        parent_sha="actual-parent",
        successful_head_sha="different-sha",
    )

    assert "run-full-ci=true" in output


def test_mixed_push_commit_runs_full_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        commit_files=[".secrets.baseline", "mcpgateway/main.py"],
        successful_head_sha="previous",
    )

    assert "run-full-ci=true" in output


@pytest.mark.parametrize("status", ["added", "removed", "renamed"])
def test_non_modified_secrets_baseline_status_runs_full_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        commit_files=[{"filename": ".secrets.baseline", "previous_filename": "other.txt", "status": status}],
        successful_head_sha="previous",
    )

    assert "run-full-ci=true" in output


def test_baseline_only_push_uses_parent_commit_for_previous_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        commit_files=[".secrets.baseline"],
        parent_sha="actual-parent",
        successful_head_sha="actual-parent",
    )

    assert "run-full-ci=false" in output


def test_baseline_only_pull_request_uses_parent_commit_for_previous_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        event_name="pull_request",
        event={"pull_request": {"head": {"sha": "latest", "repo": {"full_name": "owner/repo"}}}},
        commit_files=[".secrets.baseline"],
        parent_sha="actual-parent",
        successful_head_sha="actual-parent",
        successful_run_event="pull_request",
    )

    assert "run-full-ci=false" in output


def test_baseline_only_push_without_previous_success_runs_full_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        commit_files=[".secrets.baseline"],
        parent_sha="actual-parent",
        successful_head_sha="different-sha",
    )

    assert "run-full-ci=true" in output


@pytest.mark.parametrize(
    ("run_branch", "run_event"),
    [
        ("feature", "push"),
        ("main", "pull_request"),
    ],
)
def test_only_default_branch_push_success_allows_skip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_branch: str, run_event: str) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        commit_files=[".secrets.baseline"],
        parent_sha="actual-parent",
        successful_head_sha="actual-parent",
        successful_run_branch=run_branch,
        successful_run_event=run_event,
    )

    assert "run-full-ci=true" in output


def test_commit_api_failure_runs_full_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _run_decision(monkeypatch, tmp_path, fail_commit_api=True)

    assert "run-full-ci=true" in output


def test_tag_push_runs_full_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        commit_files=[".secrets.baseline"],
        successful_head_sha="previous",
        ref_type="tag",
    )

    assert "run-full-ci=true" in output


def test_baseline_only_push_without_parent_runs_full_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        commit_files=[".secrets.baseline"],
        parent_sha="",
        successful_head_sha="previous",
    )

    assert "run-full-ci=true" in output


def test_previous_workflow_api_failure_runs_full_ci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = _run_decision(
        monkeypatch,
        tmp_path,
        commit_files=[".secrets.baseline"],
        fail_workflow_runs_api=True,
    )

    assert "run-full-ci=true" in output


@pytest.mark.parametrize(
    ("event_name", "decision_result", "run_full_ci", "expected"),
    [
        ("pull_request", "skipped", "", True),
        ("push", "failure", "", True),
        ("push", "success", "", True),
        ("push", "success", "tru", True),
        ("push", "success", "true", True),
        ("push", "success", "false", False),
        ("pull_request", "success", "false", False),
    ],
)
def test_full_ci_gate_only_skips_on_explicit_false(event_name: str, decision_result: str, run_full_ci: str, expected: bool) -> None:
    full_ci_if = _step_if_expression("Run pre-commit")
    assert full_ci_if == "needs.ci-decision.result != 'success' || needs.ci-decision.outputs.run-full-ci != 'false'"

    should_run_full_ci = decision_result != "success" or run_full_ci != "false"

    assert should_run_full_ci is expected


def test_pre_commit_uses_shared_decision_for_fast_path() -> None:
    text = PRE_COMMIT_WORKFLOW.read_text(encoding="utf-8")
    full_ci_if = "needs.ci-decision.result != 'success' || needs.ci-decision.outputs.run-full-ci != 'false'"
    secrets_only_if = "needs.ci-decision.result == 'success' && needs.ci-decision.outputs.run-full-ci == 'false'"

    assert "git diff-tree" not in text
    assert "github.event.pull_request.head.sha" not in text
    assert "github.event.pull_request.head.repo.full_name" not in text
    assert "uses: ./.github/workflows/secret-baseline-ci-decision.yml" not in text
    assert "python3 <<'PY'" not in text
    assert "python3 .github/scripts/secret_baseline_ci_decision.py" in text
    assert Path(".github/workflows/secret-baseline-ci-decision.yml").exists() is False
    assert DECISION_SCRIPT.exists()
    assert re.search(r"ci-decision:\n\s+name: Full CI decision", text)
    assert _step_if_expression("Set up Go") == full_ci_if
    assert _step_if_expression("Run pre-commit") == full_ci_if
    assert _step_if_expression("Run detect-secrets validation") == secrets_only_if


def test_pr_workflows_gate_heavy_jobs_on_ci_decision() -> None:
    workflows = [
        Path(".github/workflows/pytest.yml"),
        Path(".github/workflows/python-package.yml"),
        Path(".github/workflows/vitest.yml"),
        Path(".github/workflows/rust.yml"),
    ]
    expected_gate = "needs.ci-decision.outputs.run-full-ci != 'false'"

    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        assert "WORKFLOW_FILE:" in text
        assert "python3 .github/scripts/secret_baseline_ci_decision.py" in text
        assert expected_gate in text


def test_detect_secrets_hook_target_scans_tracked_files() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")

    assert "git ls-files -z | xargs -0 $(UV_BIN) tool run --from '$(DETECT_SECRETS_SPEC)' detect-secrets-hook" in text
    assert "--fail-on-unaudited \\\n\t\t--" in text
