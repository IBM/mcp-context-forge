# -*- coding: utf-8 -*-
"""Module Description.
Location: ./mcp-servers/python/pm_mcp_server/tests/unit/tools/test_planning.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

import pytest

from pm_mcp_server.schemata import ScheduleModel, ScheduleTask, WBSNode
from pm_mcp_server.tools import planning


def test_generate_work_breakdown_creates_nodes():
    nodes = planning.generate_work_breakdown(
        "Design and build the dashboard. Rollout and train users."
    )
    assert len(nodes) >= 2
    assert nodes[0].name.lower().startswith("design")


def test_build_schedule_creates_linear_dependencies():
    wbs = [
        WBSNode(id="1", name="Design", estimate_days=3.0, owner="UX", children=[]),
        WBSNode(id="2", name="Build", estimate_days=5.0, owner="Dev", children=[]),
    ]
    schedule = planning.build_schedule(wbs)
    assert len(schedule.tasks) == 2
    assert schedule.tasks[1].dependencies == [schedule.tasks[0].id]


def test_critical_path_flags_zero_slack_tasks():
    schedule = ScheduleModel(
        tasks=[
            ScheduleTask(id="A", name="Start", duration_days=2, dependencies=[]),
            ScheduleTask(id="B", name="Task B", duration_days=3, dependencies=["A"]),
            ScheduleTask(id="C", name="Task C", duration_days=1, dependencies=["B"]),
        ]
    )
    result = planning.critical_path_analysis(schedule)
    critical_ids = {task.id for task in result.tasks if task.is_critical}
    assert critical_ids == {"A", "B", "C"}
    assert pytest.approx(result.project_duration, rel=1e-6) == 6


def test_scope_guardrails_identifies_out_of_scope_items():
    summary = planning.scope_guardrails(
        "Build analytics dashboard for finance KPIs",
        ["Finance dashboard", "Marketing campaign"],
    )
    assert "Marketing campaign" in summary["out_of_scope"]
    assert summary["guardrail_summary"] == "Scope creep detected"


def test_sprint_planning_helper_respects_capacity():
    backlog = [
        {"id": "1", "priority": 1, "effort": 3, "value": 10},
        {"id": "2", "priority": 2, "effort": 5, "value": 8},
        {"id": "3", "priority": 3, "effort": 1, "value": 6},
    ]
    plan = planning.sprint_planning_helper(backlog, sprint_capacity=5)
    committed_ids = {item["id"] for item in plan["committed_items"]}
    assert committed_ids == {"1", "3"}
    assert plan["remaining_capacity"] == pytest.approx(1.0)
