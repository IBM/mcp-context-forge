from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "rust.yml"
PYTEST_RUST_WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pytest-rust.yml"
LINTING_WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "linting-full.yml"
MAKEFILE_PATH = Path(__file__).resolve().parents[2] / "Makefile"


def load_workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_linting_workflow() -> dict:
    with LINTING_WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_pytest_rust_workflow() -> dict:
    with PYTEST_RUST_WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_build_wheels_artifacts_are_unique_per_platform():
    workflow = load_workflow()
    build_wheels_job = workflow["jobs"]["build-wheels"]

    upload_step = next(step for step in build_wheels_job["steps"] if step.get("name") == "Upload wheels")

    assert upload_step["with"]["name"] == "wheels-${{ matrix.os }}"


def test_pull_requests_run_the_full_rust_validation_jobs():
    workflow = load_workflow()
    jobs = workflow["jobs"]

    assert "pr-style" not in jobs
    assert "pr-test" not in jobs
    assert "pr-policy" not in jobs

    for job_name in (
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
    ):
        assert jobs[job_name]["if"] == "github.event_name != 'pull_request' || !github.event.pull_request.draft"

    rust_test_redis_job = jobs["rust-test-redis"]
    assert rust_test_redis_job["services"]["redis"]["image"] == "redis:7-bookworm"
    assert rust_test_redis_job["env"]["AUTH_ENCRYPTION_SECRET"] == "ci-rust-auth-encryption-secret-1234567890"
    assert rust_test_redis_job["env"]["REDIS_URL"] == "redis://127.0.0.1:6379/0"
    assert rust_test_redis_job["env"]["MCP_RUST_REDIS_URL"] == "redis://127.0.0.1:6379/0"

    build_wheels_job = jobs["build-wheels"]
    assert build_wheels_job["strategy"]["matrix"]["os"] == '${{ fromJSON(\'["ubuntu-latest", "macos-latest"]\') }}'
    assert jobs["rust-build"]["strategy"]["matrix"]["os"] == '${{ fromJSON(\'["ubuntu-latest", "macos-latest"]\') }}'
    assert jobs["rust-test"]["strategy"]["matrix"]["os"] == '${{ fromJSON(\'["ubuntu-latest", "macos-latest"]\') }}'
    assert jobs["rust-fmt"]["runs-on"] == "ubuntu-latest"
    assert "strategy" not in jobs["rust-fmt"]
    assert jobs["rust-clippy"]["runs-on"] == "ubuntu-latest"
    assert "strategy" not in jobs["rust-clippy"]


def test_rust_ci_tracks_makefile_for_push_and_pull_request():
    workflow = load_workflow()
    on_block = workflow.get("on", workflow.get(True))

    assert "Makefile" in on_block["push"]["paths"]
    assert "Makefile" in on_block["pull_request"]["paths"]
    assert "mcpgateway/db.py" in on_block["push"]["paths"]
    assert "mcpgateway/db.py" in on_block["pull_request"]["paths"]
    assert "mcpgateway/alembic/**" in on_block["push"]["paths"]
    assert "mcpgateway/alembic/**" in on_block["pull_request"]["paths"]
    assert "mcp-servers/rust/**" not in on_block["push"]["paths"]
    assert "mcp-servers/rust/**" not in on_block["pull_request"]["paths"]


def test_rust_ci_compiles_benchmarks_without_running_them():
    workflow = load_workflow()
    jobs = workflow["jobs"]

    assert "benchmark-tests" not in jobs

    release_build_job = jobs["benchmark-build-check"]
    assert release_build_job["name"] == "Benchmarks (build check only)"

    build_step = next(step for step in release_build_job["steps"] if step.get("name") == "Verify benchmarks build (no run)")
    assert build_step["run"] == "make rust-bench-check"


def test_rust_ci_enforces_rust_deny_in_dependency_policy_job():
    workflow = load_workflow()
    security_audit_job = workflow["jobs"]["security-audit"]

    assert security_audit_job["name"] == "Dependency policy"
    deny_step = next(step for step in security_audit_job["steps"] if step.get("name") == "Run rust-deny")
    assert deny_step["run"] == "make rust-deny"


def test_rust_workflows_pin_third_party_actions():
    workflow = load_workflow()
    pytest_rust_workflow = load_pytest_rust_workflow()
    python_workflow = yaml.safe_load((WORKFLOW_PATH.parent / "pytest.yml").read_text(encoding="utf-8"))

    def _assert_pinned(job_steps: list[dict]) -> None:
        for step in job_steps:
            uses = step.get("uses")
            if uses:
                _, _, ref = uses.partition("@")
                assert len(ref) == 40 and all(ch in "0123456789abcdef" for ch in ref), f"workflow action should be pinned to a full SHA, found {uses}"

    for job in workflow["jobs"].values():
        _assert_pinned(job.get("steps", []))
    _assert_pinned(pytest_rust_workflow["jobs"]["test"]["steps"])
    _assert_pinned(python_workflow["jobs"]["test"]["steps"])


def test_rust_release_workflow_is_dynamic_and_tag_driven():
    workflow = load_workflow()
    on_block = workflow.get("on", workflow.get(True))

    assert "v*" in on_block["push"]["tags"]
    assert "Makefile" in on_block["push"]["paths"]

    resolve_job = workflow["jobs"]["resolve-release"]
    assert resolve_job["outputs"]["has_pyo3_release_crates"] == "${{ steps.resolve.outputs.has_pyo3_release_crates }}"
    assert resolve_job["outputs"]["pyo3_release_crates"] == "${{ steps.resolve.outputs.pyo3_release_crates }}"
    resolve_step = next(step for step in resolve_job["steps"] if step.get("id") == "resolve")
    assert "has_pyo3_release_crates" in resolve_step["run"]
    assert "pyo3_release_crates" in resolve_step["run"]

    release_wheel_job = workflow["jobs"]["release-wheel"]
    assert release_wheel_job["strategy"]["matrix"]["include"] == "${{ fromJson(needs.resolve-release.outputs.wheel_matrix) }}"
    assert {"security-audit", "supply-chain-vet", "license-check"}.issubset(release_wheel_job["needs"])
    assert "needs.resolve-release.outputs.has_pyo3_release_crates == 'true'" in release_wheel_job["if"]

    release_publish_job = workflow["jobs"]["release-publish"]
    assert release_publish_job["environment"]["name"] == "pypi"
    assert release_publish_job["permissions"]["id-token"] == "write"
    publish_step = next(step for step in release_publish_job["steps"] if step.get("name") == "Publish distributions to PyPI")
    assert publish_step["run"] == "uv publish dist/*"


def test_containerfile_lite_uses_workspace_runtime_and_native_extensions():
    containerfile = (WORKFLOW_PATH.parents[2] / "Containerfile.lite").read_text(encoding="utf-8")

    assert "ENABLE_RUST=true but no Rust wheels were produced" not in containerfile
    assert "COPY mcp-servers/rust/ /build/mcp-servers/rust/" not in containerfile
    assert "FROM registry.access.redhat.com/ubi10/ubi:10.1-1776145136 AS rust-builder-base" in containerfile
    assert "Rust plugins" not in containerfile
    assert "Skipping Rust plugin build" not in containerfile
    assert "rust-wheels" not in containerfile
    assert "COPY Cargo.toml Cargo.lock /build/" in containerfile
    assert "COPY crates/ /build/crates/" in containerfile
    assert "/build/native-extension-wheels" in containerfile
    assert "/build/rust-sidecars" not in containerfile
    assert 'subprocess.check_output(["cargo", "metadata", "--no-deps", "--format-version", "1"]' not in containerfile
    assert 'target.get("kind") != ["bin"]' not in containerfile
    assert 'target.get("required-features") or target.get("required_features")' not in containerfile
    assert 'build-backend = "maturin"' not in containerfile
    assert '"maturin==1.12.6"' in containerfile
    assert '[sys.executable, "-m", "maturin", "build", "--release"' in containerfile
    assert "Installing local native extensions..." in containerfile
    assert "No local native extensions discovered" in containerfile
    assert "cargo build --release -p contextforge_mcp_runtime" in containerfile
    assert "/build/target/release/contextforge-mcp-runtime" in containerfile
    assert "pii_filter_rust" not in containerfile


def test_pytest_rust_tracks_makefile_and_installs_plugin_extra():
    workflow = load_pytest_rust_workflow()
    on_block = workflow.get("on", workflow.get(True))

    assert "Makefile" not in on_block["push"]["paths"]
    assert "Makefile" not in on_block["pull_request"]["paths"]
    assert "mcp-servers/rust/**" not in on_block["push"]["paths"]
    assert "mcp-servers/rust/**" not in on_block["pull_request"]["paths"]

    build_step = next(step for step in workflow["jobs"]["test"]["steps"] if step.get("name") == "🔨  Build Rust extensions")
    assert "make rust-install && make rust-verify-stubs" in build_step["run"]

    pytest_step = next(step for step in workflow["jobs"]["test"]["steps"] if step.get("name") == "🧪  Run pytest")
    assert "uv run --extra plugins pytest -n 0" in pytest_step["run"]
    assert workflow["jobs"]["test"]["env"]["REQUIRE_RUST"] == "1"
    assert workflow["jobs"]["test"]["env"]["AUTH_ENCRYPTION_SECRET"] == "ci-rust-auth-encryption-secret-1234567890"
    assert workflow["jobs"]["test"]["env"]["REDIS_URL"] == "redis://127.0.0.1:6379/0"
    assert workflow["jobs"]["test"]["env"]["MCP_RUST_REDIS_URL"] == "redis://127.0.0.1:6379/0"

    doctest_step = next(step for step in workflow["jobs"]["test"]["steps"] if step.get("name") == "📊  Doctest coverage with threshold")
    assert "uv run --extra plugins pytest -n 0" in doctest_step["run"]


def test_pytest_workflows_do_not_run_doctests_twice():
    pytest_rust_workflow = load_pytest_rust_workflow()
    python_workflow = yaml.safe_load((WORKFLOW_PATH.parent / "pytest.yml").read_text(encoding="utf-8"))

    rust_step_names = [step.get("name") for step in pytest_rust_workflow["jobs"]["test"]["steps"]]
    python_step_names = [step.get("name") for step in python_workflow["jobs"]["test"]["steps"]]

    assert "📊  Doctest coverage validation" not in rust_step_names
    assert "📊  Doctest coverage validation" in python_step_names

    assert "📊  Doctest coverage with threshold" in rust_step_names
    assert "📊  Doctest coverage with threshold" in python_step_names

    rust_doctest_step = next(step for step in pytest_rust_workflow["jobs"]["test"]["steps"] if step.get("name") == "📊  Doctest coverage with threshold")
    python_doctest_step = next(step for step in python_workflow["jobs"]["test"]["steps"] if step.get("name") == "📊  Doctest coverage with threshold")
    python_validation_step = next(step for step in python_workflow["jobs"]["test"]["steps"] if step.get("name") == "📊  Doctest coverage validation")

    assert "uv run --extra plugins pytest -n 0" in rust_doctest_step["run"]
    assert "uv run pytest -n auto" in python_doctest_step["run"]
    assert "uv run python3 -c" in python_validation_step["run"]


def test_linting_full_uses_patched_go_and_module_cache_paths():
    workflow = load_linting_workflow()
    steps = workflow["jobs"]["linting-full"]["steps"]

    setup_go_step = next(step for step in steps if step.get("name") == "Set up Go")
    assert setup_go_step["with"]["go-version"] == "1.26.2"
    assert setup_go_step["with"]["cache-dependency-path"].strip().splitlines() == [
        "a2a-agents/go/a2a-echo-agent/go.sum",
        "mcp-servers/go/benchmark-server/go.sum",
        "mcp-servers/go/fast-time-server/go.sum",
        "mcp-servers/go/slow-time-server/go.sum",
    ]


def test_linting_go_toolchain_is_patched_in_makefile():
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    assert "LINT_GO_TOOLCHAIN ?= go1.26.2" in makefile
