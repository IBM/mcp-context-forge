# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_source_patterns.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Cross-module static-source invariants.

- The cancellation router must be conditionally registered in main.py
  (gated on ``settings.mcpgateway_tool_cancellation_enabled``).
- ``A2AService.register_agent`` must commit the agent row before
  attempting to create its tool, otherwise the tool references an
  unsaved agent.

Both are static-source assertions rather than behavioural tests —
they catch accidental deletion or reordering at diff-review time.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _extract_function_source(file_source: str, func_name: str) -> str | None:
    tree = ast.parse(file_source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            lines = file_source.splitlines()
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    return None


def test_main_conditionally_registers_cancellation_router() -> None:
    source = (REPO_ROOT / "mcpgateway" / "main.py").read_text(encoding="utf-8")
    for pattern in (
        "if settings.mcpgateway_tool_cancellation_enabled:",
        "app.include_router(cancellation_router)",
        "Cancellation router included",
    ):
        assert pattern in source, f"main.py: missing cancellation router pattern: {pattern}"


def test_a2a_register_agent_commits_before_creating_tool() -> None:
    file_source = (REPO_ROOT / "mcpgateway" / "services" / "a2a_service.py").read_text(encoding="utf-8")
    source = _extract_function_source(file_source, "register_agent")
    assert source is not None, "register_agent function not found in a2a_service.py"

    required = ["db.add(new_agent)", "db.commit()", "create_tool_from_a2a_agent"]
    positions = []
    for pattern in required:
        idx = source.find(pattern)
        assert idx != -1, f"a2a_service.py:register_agent: missing pattern: {pattern}"
        positions.append(idx)
    assert positions[0] < positions[1] < positions[2], "a2a_service.py:register_agent: must db.add -> db.commit -> create_tool_from_a2a_agent in that order"
