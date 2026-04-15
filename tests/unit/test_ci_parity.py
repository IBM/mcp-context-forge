from pathlib import Path

import pytest

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
