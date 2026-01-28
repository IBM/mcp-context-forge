# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pm_mcp_server/src/pm_mcp_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

FastMCP entry point for the project management MCP server.
"""

from __future__ import annotations

import argparse
import logging
import sys
from importlib import resources

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from pm_mcp_server import __version__
from pm_mcp_server.resource_store import GLOBAL_RESOURCE_STORE
from pm_mcp_server.schemata import (
    ActionItem,
    ActionItemLog,
    ChangeRequest,
    CriticalPathResult,
    DiagramArtifact,
    EarnedValueInput,
    EarnedValueResult,
    HealthDashboard,
    MeetingSummary,
    RiskEntry,
    RiskRegister,
    ScheduleModel,
    Stakeholder,
    StakeholderMatrixResult,
    StatusReportPayload,
    WBSNode,
)
from pm_mcp_server.tools import collaboration, governance, planning, reporting

# Configure logging to stderr to maintain clean stdio transport
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

mcp = FastMCP("pm-mcp-server", version=__version__)


# ---------------------------------------------------------------------------
# Planning and scheduling tools
# ---------------------------------------------------------------------------


@mcp.tool(
    description="Generate a work breakdown structure from scope narrative.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def generate_work_breakdown(
    scope: str = Field(..., description="Narrative scope statement"),
    phases: list[str] | None = Field(None, description="Optional ordered phase names"),
    constraints: dict[str, str] | None = Field(
        default=None, description="Schedule/budget guardrails (finish_no_later_than, budget_limit)"
    ),
) -> list[WBSNode]:
    return planning.generate_work_breakdown(scope=scope, phases=phases, constraints=constraints)


@mcp.tool(
    description="Convert WBS into a simple sequential schedule model.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def build_schedule(
    wbs: list[WBSNode] = Field(..., description="WBS nodes to schedule"),
    default_owner: str | None = Field(None, description="Fallback owner for tasks"),
) -> ScheduleModel:
    return planning.build_schedule(wbs, default_owner)


@mcp.tool(
    description="Run critical path analysis over a schedule.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def critical_path_analysis(
    schedule: ScheduleModel = Field(..., description="Schedule model to analyse"),
) -> CriticalPathResult:
    return planning.critical_path_analysis(schedule)


@mcp.tool(
    description="Generate gantt chart artefacts from schedule",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def produce_gantt_diagram(
    schedule: ScheduleModel = Field(..., description="Schedule with CPM fields"),
    project_start: str | None = Field(None, description="Project start ISO date"),
) -> DiagramArtifact:
    return planning.gantt_artifacts(schedule, project_start)


@mcp.tool(
    description="Suggest lightweight schedule optimisations",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def schedule_optimizer(
    schedule: ScheduleModel = Field(..., description="Schedule to optimise"),
) -> ScheduleModel:
    return planning.schedule_optimizer(schedule)


@mcp.tool(
    description="Check proposed features against scope guardrails",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def scope_guardrails(
    scope_statement: str = Field(..., description="Authorised scope summary"),
    proposed_items: list[str] = Field(..., description="Items or features to evaluate"),
) -> dict[str, object]:
    return planning.scope_guardrails(scope_statement, proposed_items)


@mcp.tool(
    description="Assemble sprint backlog based on capacity and priority",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def sprint_planning_helper(
    backlog: list[dict[str, object]] = Field(
        ..., description="Backlog items with priority/value/effort"
    ),
    sprint_capacity: float = Field(..., ge=0.0, description="Total available story points or days"),
) -> dict[str, object]:
    return planning.sprint_planning_helper(backlog, sprint_capacity)


# ---------------------------------------------------------------------------
# Governance tools
# ---------------------------------------------------------------------------


@mcp.tool(
    description="Manage and rank risks by severity",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def risk_register_manager(
    risks: list[RiskEntry] = Field(..., description="Risk register entries"),
) -> RiskRegister:
    return governance.risk_register_manager(risks)


@mcp.tool(
    description="Summarise change request impacts",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def change_request_tracker(
    requests: list[ChangeRequest] = Field(..., description="Change requests"),
) -> dict[str, object]:
    return governance.change_request_tracker(requests)


@mcp.tool(
    description="Compare baseline vs actual metrics",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def baseline_vs_actual(
    planned: dict[str, float] = Field(..., description="Baseline metrics"),
    actual: dict[str, float] = Field(..., description="Actual metrics"),
    tolerance_percent: float = Field(10.0, ge=0.0, description="Variance tolerance percent"),
) -> dict[str, dict[str, float | bool]]:
    return governance.baseline_vs_actual(planned, actual, tolerance_percent)


@mcp.tool(
    description="Compute earned value management metrics",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def earned_value_calculator(
    values: list[EarnedValueInput] = Field(..., description="Period EVM entries"),
    budget_at_completion: float = Field(..., gt=0.0, description="Authorised budget"),
) -> EarnedValueResult:
    return governance.earned_value_calculator(values, budget_at_completion)


# ---------------------------------------------------------------------------
# Reporting and documentation
# ---------------------------------------------------------------------------


@mcp.tool(
    description="Render status report markdown via template",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def status_report_generator(
    payload: StatusReportPayload = Field(..., description="Status report payload"),
) -> dict[str, str]:
    return reporting.status_report_generator(payload)


@mcp.tool(
    description="Produce project health dashboard summary",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def project_health_dashboard(
    snapshot: HealthDashboard = Field(..., description="Dashboard snapshot"),
) -> dict[str, object]:
    return reporting.project_health_dashboard(snapshot)


@mcp.tool(
    description="Generate project brief summary",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def project_brief_generator(
    name: str = Field(..., description="Project name"),
    objectives: list[str] = Field(..., description="Objectives"),
    success_criteria: list[str] = Field(..., description="Success criteria"),
    budget: float = Field(..., ge=0.0, description="Budget value"),
    timeline: str = Field(..., description="Timeline narrative"),
) -> dict[str, object]:
    return reporting.project_brief_generator(name, objectives, success_criteria, budget, timeline)


@mcp.tool(
    description="Aggregate lessons learned entries",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def lessons_learned_catalog(
    entries: list[dict[str, str]] = Field(..., description="Lessons learned entries"),
) -> dict[str, list[str]]:
    return reporting.lessons_learned_catalog(entries)


@mcp.tool(
    description="Expose packaged PM templates",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def document_template_library() -> dict[str, str]:
    return reporting.document_template_library()


# ---------------------------------------------------------------------------
# Collaboration & execution support
# ---------------------------------------------------------------------------


@mcp.tool(
    description="Summarise meeting transcript into decisions and actions",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def meeting_minutes_summarizer(
    transcript: str = Field(..., description="Raw meeting notes"),
) -> MeetingSummary:
    return collaboration.meeting_minutes_summarizer(transcript)


@mcp.tool(
    description="Merge action item updates",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def action_item_tracker(
    current: ActionItemLog = Field(..., description="Current action item backlog"),
    updates: list[ActionItem] = Field(..., description="Updates or new action items"),
) -> ActionItemLog:
    return collaboration.action_item_tracker(current, updates)


@mcp.tool(
    description="Report resource allocation variance",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def resource_allocator(
    capacity: dict[str, float] = Field(..., description="Capacity per team"),
    assignments: dict[str, float] = Field(..., description="Assigned load per team"),
) -> dict[str, dict[str, float]]:
    return collaboration.resource_allocator(capacity, assignments)


@mcp.tool(
    description="Produce stakeholder matrix diagram",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def stakeholder_matrix(
    stakeholders: list[Stakeholder] = Field(..., description="Stakeholder entries"),
) -> StakeholderMatrixResult:
    return collaboration.stakeholder_matrix(stakeholders)


@mcp.tool(
    description="Plan communications cadence per stakeholder",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def communications_planner(
    stakeholders: list[Stakeholder] = Field(..., description="Stakeholders"),
    cadence_days: int = Field(7, ge=1, description="Base cadence in days"),
) -> list[dict[str, str]]:
    return collaboration.communications_planner(stakeholders, cadence_days)


# ---------------------------------------------------------------------------
# Resources & prompts
# ---------------------------------------------------------------------------


@mcp.resource(
    "generated-artifact/{resource_id}", description="Return generated artefact from resource store"
)
async def generated_artifact(resource_id: str) -> tuple[str, bytes]:
    mime, content = GLOBAL_RESOURCE_STORE.get(resource_id)
    return mime, content


def _load_prompt(name: str) -> str:
    return resources.files("pm_mcp_server.prompts").joinpath(name).read_text(encoding="utf-8")


@mcp.prompt("status-report")
async def status_report_prompt() -> str:
    return _load_prompt("status_report_prompt.md")


@mcp.prompt("risk-mitigation")
async def risk_mitigation_prompt() -> str:
    return _load_prompt("risk_mitigation_prompt.md")


@mcp.prompt("change-impact")
async def change_impact_prompt() -> str:
    return _load_prompt("change_impact_prompt.md")


@mcp.tool(
    description="Provide glossary definitions for common PM terms",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def glossary_lookup(
    terms: list[str] = Field(..., description="PM terms to define"),
) -> dict[str, str]:
    glossary = {
        "cpi": "Cost Performance Index, EV / AC",
        "spi": "Schedule Performance Index, EV / PV",
        "cpm": "Critical Path Method, identifies zero-slack activities",
        "wbs": "Work Breakdown Structure, hierarchical decomposition of work",
        "rai": "Responsible, Accountable, Informed matrix variant",
    }
    return {term: glossary.get(term.lower(), "Definition unavailable") for term in terms}


@mcp.tool(
    description="List packaged sample data assets",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def sample_data_catalog() -> dict[str, str]:
    sample_pkg = resources.files("pm_mcp_server.data.sample_data")
    resource_map: dict[str, str] = {}
    for path in sample_pkg.iterdir():
        if not path.is_file():
            continue
        data = path.read_bytes()
        resource_id = GLOBAL_RESOURCE_STORE.add(data, "application/json", prefix="sample")
        resource_map[path.name] = resource_id
    return resource_map


def main() -> None:
    parser = argparse.ArgumentParser(description="Project Management FastMCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    if args.transport == "http":
        logger.info("Starting PM MCP Server on HTTP %s:%s", args.host, args.port)
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting PM MCP Server on stdio")
        mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
