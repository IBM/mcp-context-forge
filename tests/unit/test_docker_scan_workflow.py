from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "docker-scan.yml"


def load_workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    if True in workflow and "on" not in workflow:
        workflow["on"] = workflow.pop(True)
    return workflow


def test_docker_scan_tracks_rust_container_inputs() -> None:
    workflow = load_workflow()
    on_block = workflow["on"]

    for event_name in ("push", "pull_request"):
        paths = on_block[event_name]["paths"]
        assert "Containerfile.lite" in paths
        assert "crates/**" in paths
        assert "Cargo.toml" in paths
        assert "Cargo.lock" in paths


def test_docker_scan_has_rust_enabled_smoke_build() -> None:
    workflow = load_workflow()
    job = workflow["jobs"]["rust-enabled-build"]

    assert job["name"] == "Rust-enabled container smoke"
    build_step = next(step for step in job["steps"] if step.get("name") == "Build Rust-enabled image locally")
    assert build_step["with"]["file"] == "Containerfile.lite"
    assert build_step["with"]["platforms"] == "linux/amd64"
    assert build_step["with"]["push"] is False
    assert build_step["with"]["load"] is False
    assert "ENABLE_RUST=true" in build_step["with"]["build-args"]


def test_docker_scan_triggers_on_changed_container_files():
    workflow = load_workflow()
    push_paths = workflow["on"]["push"]["paths"]
    pr_paths = workflow["on"]["pull_request"]["paths"]

    for expected in [
        "Containerfile.lite",
        "a2a-agents/go/a2a-echo-agent/**",
        "mcp-servers/python/python_sandbox_server/docker/**",
        "docker-compose.yml",
        "docker-compose-embedded.yml",
        "docker-compose-verbose-logging.yml",
    ]:
        assert expected in push_paths
        assert expected in pr_paths


def test_docker_scan_builds_changed_dockerfiles():
    workflow = load_workflow()
    matrix = workflow["jobs"]["container-smoke"]["strategy"]["matrix"]["include"]

    assert matrix == [
        {
            "name": "a2a-echo-agent",
            "context": "a2a-agents/go/a2a-echo-agent",
            "file": "a2a-agents/go/a2a-echo-agent/Dockerfile",
            "tag": "mcp-context-forge-a2a-echo-agent:scan",
        },
        {
            "name": "python-sandbox",
            "context": "mcp-servers/python/python_sandbox_server",
            "file": "mcp-servers/python/python_sandbox_server/docker/Dockerfile.sandbox",
            "tag": "mcp-context-forge-python-sandbox:scan",
        },
    ]
