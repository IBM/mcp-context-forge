# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pm_mcp_server/src/pm_mcp_server/tools/collaboration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Collaboration and communication helper tools.
"""

from __future__ import annotations

import datetime as dt
import re

from pm_mcp_server.resource_store import GLOBAL_RESOURCE_STORE
from pm_mcp_server.schemata import (
    ActionItem,
    ActionItemLog,
    MeetingSummary,
    Stakeholder,
    StakeholderMatrixResult,
)

_DECISION_PATTERN = re.compile(r"\b(decision|decided)[:\-]\s*(.+)", re.IGNORECASE)
_ACTION_PATTERN = re.compile(r"\b(action|todo|ai)[:\-]\s*(.+)", re.IGNORECASE)
_NOTE_PATTERN = re.compile(r"\b(note)[:\-]\s*(.+)", re.IGNORECASE)


def meeting_minutes_summarizer(transcript: str) -> MeetingSummary:
    """Extract naive decisions/action items from raw transcript."""

    decisions: list[str] = []
    action_items: list[ActionItem] = []
    notes: list[str] = []

    for idx, line in enumerate(transcript.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if match := _DECISION_PATTERN.search(line):
            decisions.append(match.group(2).strip())
        elif match := _ACTION_PATTERN.search(line):
            action_items.append(
                ActionItem(id=f"AI-{idx}", description=match.group(2).strip(), owner="Unassigned")
            )
        elif match := _NOTE_PATTERN.search(line):
            notes.append(match.group(2).strip())

    return MeetingSummary(
        decisions=decisions,
        action_items=ActionItemLog(items=action_items),
        notes=notes,
    )


def action_item_tracker(current: ActionItemLog, updates: list[ActionItem]) -> ActionItemLog:
    """Merge updates into current action item backlog by id."""

    items: dict[str, ActionItem] = {item.id: item for item in current.items}
    for update in updates:
        items[update.id] = update
    return ActionItemLog(items=list(items.values()))


def resource_allocator(
    capacity: dict[str, float], assignments: dict[str, float]
) -> dict[str, dict[str, float]]:
    """Highlight over/under allocations."""

    report: dict[str, dict[str, float]] = {}
    for team, cap in capacity.items():
        assigned = assignments.get(team, 0.0)
        variance = cap - assigned
        report[team] = {
            "capacity": cap,
            "assigned": assigned,
            "variance": variance,
            "status": "Overallocated"
            if variance < 0
            else "Available"
            if variance > 0
            else "Balanced",
        }
    return report


def stakeholder_matrix(stakeholders: list[Stakeholder]) -> StakeholderMatrixResult:
    """Generate mermaid flowchart grouping stakeholders by power/interest."""

    categories: dict[str, list[str]] = {
        "Manage Closely": [],
        "Keep Satisfied": [],
        "Keep Informed": [],
        "Monitor": [],
    }
    mapping = {
        ("high", "high"): "Manage Closely",
        ("high", "low"): "Keep Satisfied",
        ("low", "high"): "Keep Informed",
        ("low", "low"): "Monitor",
    }
    for stakeholder in stakeholders:
        key = (stakeholder.influence.lower(), stakeholder.interest.lower())
        categories[mapping.get(key, "Manage Closely")].append(stakeholder.name)

    lines = ["flowchart TB"]
    for cat, names in categories.items():
        safe_cat = cat.replace(" ", "_")
        lines.append(f"    subgraph {safe_cat}[{cat}]")
        if names:
            for name in names:
                node_id = name.replace(" ", "_")
                lines.append(f"        {node_id}({name})")
        else:
            lines.append("        placeholder((No Stakeholders))")
        lines.append("    end")

    mermaid_resource = GLOBAL_RESOURCE_STORE.add(
        "\n".join(lines).encode("utf-8"), "text/mermaid", prefix="stakeholder"
    )
    return StakeholderMatrixResult(stakeholders=stakeholders, mermaid_resource=mermaid_resource)


def communications_planner(
    stakeholders: list[Stakeholder], cadence_days: int = 7
) -> list[dict[str, str]]:
    """Create simple communications schedule."""

    today = dt.date.today()
    plan: list[dict[str, str]] = []
    for stakeholder in stakeholders:
        cadence_multiplier = 1
        if stakeholder.influence.lower() == "high" or stakeholder.interest.lower() == "high":
            cadence_multiplier = 1
        else:
            cadence_multiplier = 2
        next_touch = today + dt.timedelta(days=cadence_days * cadence_multiplier)
        plan.append(
            {
                "stakeholder": stakeholder.name,
                "next_touchpoint": next_touch.isoformat(),
                "message_focus": stakeholder.engagement_strategy or "Project update",
            }
        )
    return plan
