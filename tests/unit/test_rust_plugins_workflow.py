from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "rust-plugins.yml"
LINTING_WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "linting-full.yml"
MAKEFILE_PATH = Path(__file__).resolve().parents[2] / "Makefile"


def load_workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_linting_workflow() -> dict:
    with LINTING_WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_build_wheels_artifacts_are_unique_per_platform():
    workflow = load_workflow()
    build_wheels_job = workflow["jobs"]["build-wheels"]

    upload_step = next(step for step in build_wheels_job["steps"] if step.get("name") == "Upload wheels as artifacts")

    assert upload_step["with"]["name"] == "wheels-build-${{ matrix.os }}"


def test_rust_ci_compiles_benchmarks_without_running_them():
    workflow = load_workflow()
    jobs = workflow["jobs"]

    assert "benchmark-tests" not in jobs

    release_build_job = jobs["release-build-verification"]
    assert release_build_job["name"] == "Benchmark Build Verification"

    build_step = next(step for step in release_build_job["steps"] if step.get("name") == "Compile Rust plugin benchmarks without running them")
    assert build_step["run"] == "make rust-bench-build"


def test_linting_full_uses_patched_go_and_module_cache_paths():
    workflow = load_linting_workflow()
    steps = workflow["jobs"]["linting-full"]["steps"]

    setup_go_step = next(step for step in steps if step.get("name") == "Set up Go")
    assert setup_go_step["with"]["go-version"] == "1.25.8"
    assert setup_go_step["with"]["cache-dependency-path"].strip().splitlines() == [
        "a2a-agents/go/a2a-echo-agent/go.sum",
        "mcp-servers/go/benchmark-server/go.sum",
        "mcp-servers/go/fast-time-server/go.sum",
        "mcp-servers/go/slow-time-server/go.sum",
    ]


def test_linting_go_toolchain_is_patched_in_makefile():
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    assert "LINT_GO_TOOLCHAIN ?= go1.25.8" in makefile
