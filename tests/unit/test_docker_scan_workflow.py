from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "docker-scan.yml"


def load_workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_docker_scan_tracks_rust_container_inputs() -> None:
    workflow = load_workflow()
    on_block = workflow.get("on", workflow.get(True))

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
