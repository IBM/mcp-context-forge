# -*- coding: utf-8 -*-
"""Module Description.
Location: ./mcp-servers/python/pm_mcp_server/tests/unit/tools/test_collaboration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

from pm_mcp_server.schemata import ActionItem, ActionItemLog, Stakeholder
from pm_mcp_server.tools import collaboration


def test_meeting_minutes_summarizer_extracts_decisions_and_actions():
    transcript = """
    Decision: Move launch to May.
    Action: Alex to update plan.
    Note: Share summary with execs.
    """
    summary = collaboration.meeting_minutes_summarizer(transcript)
    assert "Move launch to May." in summary.decisions
    assert summary.action_items.items[0].description.startswith("Alex")
    assert summary.notes == ["Share summary with execs."]


def test_action_item_tracker_merges_updates():
    current = ActionItemLog(items=[ActionItem(id="AI-1", description="Old", owner="PM")])
    updates = [
        ActionItem(id="AI-1", description="Updated", owner="PM"),
        ActionItem(id="AI-2", description="New", owner="Lead"),
    ]
    merged = collaboration.action_item_tracker(current, updates)
    assert len(merged.items) == 2
    assert any(item.description == "Updated" for item in merged.items)


def test_stakeholder_matrix_returns_resource():
    stakeholders = [Stakeholder(name="Alex", influence="High", interest="High")]
    result = collaboration.stakeholder_matrix(stakeholders)
    assert result.mermaid_resource.startswith("resource://")


def test_communications_planner_assigns_dates():
    stakeholders = [Stakeholder(name="Alex", influence="High", interest="Low")]
    plan = collaboration.communications_planner(stakeholders, cadence_days=7)
    assert plan[0]["stakeholder"] == "Alex"
