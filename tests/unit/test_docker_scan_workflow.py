# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/unit/test_docker_scan_workflow.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "docker-scan.yml"


def load_workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    if True in workflow and "on" not in workflow:
        workflow["on"] = workflow.pop(True)
    return workflow


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
