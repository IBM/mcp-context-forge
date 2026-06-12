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


def test_docker_scan_builds_changed_dockerfiles():
    workflow = load_workflow()
    matrix = workflow["jobs"]["container-smoke"]["strategy"]["matrix"]["include"]

    assert matrix == [
        {
            "name": "python-sandbox",
            "context": "mcp-servers/python/python_sandbox_server",
            "file": "mcp-servers/python/python_sandbox_server/docker/Dockerfile.sandbox",
            "tag": "mcp-context-forge-python-sandbox:scan",
        },
    ]
