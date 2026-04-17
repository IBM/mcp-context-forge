from pathlib import Path

import pytest

from mcpgateway.utils import ci_parity
from mcpgateway.utils.ci_parity import _gap_exit_code, build_execution_plan, select_ci_jobs

REPO_ROOT = Path(__file__).resolve().parents[2]


def workflow_files(selected_jobs):
    return {job.workflow_file for job in selected_jobs}


def find_job(execution_plan, workflow_file, job_id):
    return next(job for job in execution_plan if job.workflow_file == workflow_file and job.job_id == job_id)


def test_select_ci_jobs_for_python_change_includes_pr_and_push_union():
    selected_jobs = select_ci_jobs(
        repo_root=REPO_ROOT,
        changed_files=["mcpgateway/main.py"],
        pr_draft=False,
    )

    selected_workflows = workflow_files(selected_jobs)

    assert ".github/workflows/pre-commit.yml" in selected_workflows
    assert ".github/workflows/lint.yml" in selected_workflows
    assert ".github/workflows/pytest.yml" in selected_workflows
    assert ".github/workflows/python-package.yml" in selected_workflows
    assert ".github/workflows/linting-full.yml" in selected_workflows
    assert ".github/workflows/playwright.yml" in selected_workflows
    assert ".github/workflows/docker-multiplatform.yml" in selected_workflows
    assert ".github/workflows/docker-scan.yml" in selected_workflows


def test_select_ci_jobs_for_rust_change_uses_rust_specific_workflows():
    selected_jobs = select_ci_jobs(
        repo_root=REPO_ROOT,
        changed_files=["crates/mcp_runtime/src/lib.rs"],
        pr_draft=False,
    )

    selected_workflows = workflow_files(selected_jobs)

    assert ".github/workflows/pre-commit.yml" in selected_workflows
    assert ".github/workflows/pytest-rust.yml" in selected_workflows
    assert ".github/workflows/rust.yml" in selected_workflows
    assert ".github/workflows/docker-scan.yml" in selected_workflows
    assert ".github/workflows/license-check.yml" in selected_workflows


def test_select_ci_jobs_for_static_change_uses_web_workflows():
    selected_jobs = select_ci_jobs(
        repo_root=REPO_ROOT,
        changed_files=["mcpgateway/static/app.js"],
        pr_draft=False,
    )

    selected_workflows = workflow_files(selected_jobs)

    assert ".github/workflows/pre-commit.yml" in selected_workflows
    assert ".github/workflows/lint-web.yml" in selected_workflows
    assert ".github/workflows/vitest.yml" in selected_workflows


def test_select_ci_jobs_for_chart_change_uses_helm_workflow():
    selected_jobs = select_ci_jobs(
        repo_root=REPO_ROOT,
        changed_files=["charts/mcp-stack/Chart.yaml"],
        pr_draft=False,
    )

    selected_workflows = workflow_files(selected_jobs)

    assert ".github/workflows/pre-commit.yml" in selected_workflows
    assert ".github/workflows/helm-publish.yml" in selected_workflows


def test_select_ci_jobs_for_dependency_change_uses_dependency_review():
    selected_jobs = select_ci_jobs(
        repo_root=REPO_ROOT,
        changed_files=["package-lock.json"],
        pr_draft=False,
    )

    selected_workflows = workflow_files(selected_jobs)

    assert ".github/workflows/pre-commit.yml" in selected_workflows
    assert ".github/workflows/dependency-review.yml" in selected_workflows
    assert ".github/workflows/license-check.yml" in selected_workflows
    assert ".github/workflows/vitest.yml" in selected_workflows


def test_draft_pr_suppresses_pr_only_jobs_but_keeps_push_side_of_union():
    selected_jobs = select_ci_jobs(
        repo_root=REPO_ROOT,
        changed_files=["mcpgateway/main.py"],
        pr_draft=True,
    )

    selected_workflows = workflow_files(selected_jobs)

    assert ".github/workflows/pre-commit.yml" not in selected_workflows
    assert ".github/workflows/pytest.yml" in selected_workflows
    assert ".github/workflows/linting-full.yml" in selected_workflows


def test_build_execution_plan_marks_known_parity_gaps():
    execution_plan = build_execution_plan(
        repo_root=REPO_ROOT,
        changed_files=["Containerfile.lite", "Cargo.lock"],
        pr_draft=False,
    )

    dependency_review = find_job(execution_plan, ".github/workflows/dependency-review.yml", "dependency-review")
    docker_manifest = find_job(execution_plan, ".github/workflows/docker-multiplatform.yml", "manifest")
    rust_build = find_job(execution_plan, ".github/workflows/rust.yml", "rust-build")

    assert dependency_review.parity == "not_reproducible"
    assert docker_manifest.parity == "not_reproducible"
    assert rust_build.parity == "approx"


def test_build_execution_plan_marks_node_jobs_as_approx_when_local_bootstrap_differs():
    execution_plan = build_execution_plan(
        repo_root=REPO_ROOT,
        changed_files=["mcpgateway/static/app.js", "package-lock.json"],
        pr_draft=False,
    )

    lint_web = find_job(execution_plan, ".github/workflows/lint-web.yml", "lint-web")
    vitest = find_job(execution_plan, ".github/workflows/vitest.yml", "vitest")

    assert lint_web.parity == "approx"
    assert "Node/npm bootstrap" in lint_web.notes[0]
    assert vitest.parity == "approx"
    assert "Node/npm bootstrap" in vitest.notes[0]


def test_build_execution_plan_never_real_publishes_for_release_only_steps():
    execution_plan = build_execution_plan(
        repo_root=REPO_ROOT,
        changed_files=["charts/mcp-stack/Chart.yaml"],
        pr_draft=False,
    )

    assert all(job.job_id != "publish" for job in execution_plan if job.workflow_file == ".github/workflows/helm-publish.yml")


def test_gap_exit_code_is_best_effort_by_default():
    assert _gap_exit_code(approx_count=1, unreproducible_count=1, strict=False) == 0
    assert _gap_exit_code(approx_count=1, unreproducible_count=1, strict=True) == 2


def test_matches_paths_handles_negative_only_and_exclusions():
    assert ci_parity._matches_paths(["docs/readme.md"], ["!docs/**"]) is False
    assert ci_parity._matches_paths(["docs/readme.md"], ["docs/**", "!docs/**"]) is False
    assert ci_parity._matches_paths(["docs/readme.md"], ["src/**"]) is False


def test_event_matches_requires_main_when_branches_are_restricted():
    assert ci_parity._event_matches({}, "pull_request", ["mcpgateway/main.py"]) is False
    assert ci_parity._event_matches({"pull_request": {"branches": ["release"]}}, "pull_request", ["mcpgateway/main.py"]) is False
    assert ci_parity._event_matches({"pull_request": {"branches": ["main"]}}, "pull_request", ["mcpgateway/main.py"]) is True


@pytest.mark.parametrize(
    ("condition", "event_name", "pr_draft", "expected"),
    [
        ("", "pull_request", False, True),
        ("github.event_name == 'release'", "push", False, False),
        ("startsWith(github.ref, 'refs/tags/')", "push", False, False),
        ("github.event_name != 'pull_request'", "pull_request", False, False),
        ("github.event_name != 'pull_request'", "push", False, True),
        ("github.event_name == 'pull_request'", "pull_request", False, True),
        ("github.event_name == 'pull_request'", "push", False, False),
        ("github.event_name != 'pull_request' || !github.event.pull_request.draft", "pull_request", True, False),
        ("github.event_name != 'pull_request' || !github.event.pull_request.draft", "pull_request", False, True),
        ("github.event_name == 'pull_request' && github.base_ref == 'main'", "pull_request", False, True),
        ("github.event_name == 'pull_request' && github.base_ref == 'main'", "push", False, False),
        ("github.event_name == 'push' && always()", "push", False, True),
    ],
)
def test_job_matches_event_covers_supported_condition_shapes(condition, event_name, pr_draft, expected):
    assert ci_parity._job_matches_event({"if": condition}, event_name, pr_draft) is expected


def test_derive_changed_files_uses_merge_base_and_strips_empty_lines(monkeypatch):
    calls = []

    def fake_check_output(command, cwd, text):
        calls.append((tuple(command), cwd, text))
        if command[:3] == ["git", "merge-base", "HEAD"]:
            return "abc123\n"
        if command[:3] == ["git", "diff", "--name-only"]:
            assert command[3] == "abc123..HEAD"
            return "mcpgateway/main.py\n\nMakefile\n"
        raise AssertionError(command)

    monkeypatch.setattr(ci_parity.subprocess, "check_output", fake_check_output)

    changed_files = ci_parity.derive_changed_files(REPO_ROOT, "origin/main")

    assert changed_files == ["mcpgateway/main.py", "Makefile"]
    assert calls[0][0] == ("git", "merge-base", "HEAD", "origin/main")


def test_parse_changed_files_supports_commas_and_newlines():
    assert ci_parity._parse_changed_files(" a.py,\n b.py ,, \n\nc.py ") == ["a.py", "b.py", "c.py"]


def test_run_command_executes_in_repo_root(monkeypatch):
    captured = {}

    def fake_run(command, cwd, check):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["check"] = check

    monkeypatch.setattr(ci_parity.subprocess, "run", fake_run)

    ci_parity._run_command("echo hi", REPO_ROOT)

    assert captured == {
        "command": ["bash", "-lc", "echo hi"],
        "cwd": REPO_ROOT,
        "check": True,
    }


def test_run_ci_list_only_uses_derived_changed_files_and_prints_plan(monkeypatch, capsys):
    selected_job = ci_parity.PlannedJob(
        workflow_file=".github/workflows/test.yml",
        workflow_name="Example Workflow",
        job_id="example",
        job_name="Example Job",
        modes=("pr", "push"),
        parity="approx",
        commands=("echo hello",),
        notes=("Approx note",),
    )

    monkeypatch.setattr(ci_parity, "derive_changed_files", lambda repo_root, base_ref: ["mcpgateway/utils/ci_parity.py"])
    monkeypatch.setattr(ci_parity, "build_execution_plan", lambda **kwargs: [selected_job])

    exit_code = ci_parity.run_ci(repo_root=REPO_ROOT, list_only=True)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "== Changed files ==" in output
    assert "- mcpgateway/utils/ci_parity.py" in output
    assert "[approx] Example Workflow :: Example Job" in output
    assert "Approx note" in output


def test_run_ci_executes_commands_and_enforces_strict_gap_exit(monkeypatch, capsys):
    executed = []

    monkeypatch.setattr(
        ci_parity,
        "build_execution_plan",
        lambda **kwargs: [
            ci_parity.PlannedJob(
                workflow_file=".github/workflows/exact.yml",
                workflow_name="Exact Workflow",
                job_id="exact",
                job_name="Exact Job",
                modes=("pr",),
                parity="exact",
                commands=("echo exact",),
                notes=(),
            ),
            ci_parity.PlannedJob(
                workflow_file=".github/workflows/gap.yml",
                workflow_name="Gap Workflow",
                job_id="gap",
                job_name="Gap Job",
                modes=("push",),
                parity="not_reproducible",
                commands=(),
                notes=(),
            ),
        ],
    )
    monkeypatch.setattr(ci_parity, "_run_command", lambda command, repo_root: executed.append((command, repo_root)))

    exit_code = ci_parity.run_ci(
        repo_root=REPO_ROOT,
        changed_files=["Makefile"],
        allow_approx=False,
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert executed == [("echo exact", REPO_ROOT)]
    assert "== Running Exact Workflow :: Exact Job ==" in output
    assert "CI parity gaps detected and strict mode is enabled." in output


def test_main_reads_env_and_forwards_arguments(monkeypatch):
    captured = {}

    monkeypatch.setenv("CI_BASE_REF", "origin/release")
    monkeypatch.setenv("CI_CHANGED_FILES", "foo.py,bar.py")
    monkeypatch.setenv("CI_PR_DRAFT", "1")
    monkeypatch.setenv("CI_ALLOW_APPROX", "0")

    def fake_run_ci(**kwargs):
        captured["kwargs"] = kwargs
        return 7

    monkeypatch.setattr(ci_parity, "run_ci", fake_run_ci)

    exit_code = ci_parity.main([])

    assert exit_code == 7
    assert captured["kwargs"] == {
        "repo_root": REPO_ROOT,
        "base_ref": "origin/release",
        "changed_files": ["foo.py", "bar.py"],
        "pr_draft": True,
        "allow_approx": False,
        "list_only": False,
    }


@pytest.mark.parametrize(
    ("changed_file", "workflow_file"),
    [
        (".github/workflows/python-package.yml", ".github/workflows/python-package.yml"),
        (".github/workflows/vitest.yml", ".github/workflows/vitest.yml"),
        (".github/workflows/pytest-rust.yml", ".github/workflows/pytest-rust.yml"),
    ],
)
def test_workflow_file_changes_trigger_their_own_workflow(changed_file, workflow_file):
    selected_jobs = select_ci_jobs(
        repo_root=REPO_ROOT,
        changed_files=[changed_file],
        pr_draft=False,
    )

    assert workflow_file in workflow_files(selected_jobs)
