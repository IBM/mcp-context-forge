# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pm_mcp_server/src/pm_mcp_server/schemata.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Pydantic models used by the project management MCP server.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    """Base model with strict validation used across schemas."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WBSNode(StrictBaseModel):
    """Work breakdown element."""

    id: str = Field(..., description="WBS identifier, e.g., 1.1")
    name: str = Field(..., description="Work package name")
    owner: str | None = Field(None, description="Responsible owner")
    estimate_days: float | None = Field(None, ge=0, description="Estimated duration in days")
    children: list[WBSNode] = Field(default_factory=list, description="Sub-elements")


class ScheduleTask(StrictBaseModel):
    """Task definition for scheduling and CPM calculations."""

    id: str
    name: str
    duration_days: float = Field(..., ge=0.0)
    dependencies: list[str] = Field(default_factory=list)
    owner: str | None = None
    earliest_start: float | None = None
    earliest_finish: float | None = None
    latest_start: float | None = None
    latest_finish: float | None = None
    slack: float | None = None
    is_critical: bool | None = None


class ScheduleModel(StrictBaseModel):
    """Composite schedule representation."""

    tasks: list[ScheduleTask]
    calendar: str | None = Field(default="standard", description="Calendar profile identifier")


class CriticalPathResult(StrictBaseModel):
    """Critical path computation result."""

    tasks: list[ScheduleTask]
    project_duration: float = Field(..., ge=0.0)
    critical_task_ids: list[str]
    generated_resources: dict[str, str] = Field(default_factory=dict)


class RiskEntry(StrictBaseModel):
    """Risk register element."""

    id: str
    description: str
    probability: float = Field(..., ge=0.0, le=1.0)
    impact: float = Field(..., ge=0.0, le=1.0)
    mitigation: str | None = None
    owner: str | None = None
    status: str = Field(default="Open")

    @property
    def severity(self) -> float:
        return self.probability * self.impact


class RiskRegister(StrictBaseModel):
    """Risk register results."""

    risks: list[RiskEntry]
    high_risk_ids: list[str]


class ChangeRequest(StrictBaseModel):
    """Change request tracking entry."""

    id: str
    description: str
    schedule_impact_days: float = 0.0
    cost_impact: float = 0.0
    scope_impact: str = ""
    recommendation: str = ""
    status: str = "Proposed"


class EarnedValueInput(StrictBaseModel):
    """Inputs for earned value calculations."""

    period: str
    planned_value: float
    earned_value: float
    actual_cost: float


class EarnedValuePeriodMetric(StrictBaseModel):
    """Per-period earned value metrics."""

    period: str
    cpi: float
    spi: float
    pv: float
    ev: float
    ac: float


class EarnedValueResult(StrictBaseModel):
    """Earned value metrics."""

    period_metrics: list[EarnedValuePeriodMetric]
    cpi: float
    spi: float
    estimate_at_completion: float
    variance_at_completion: float


class StatusReportItem(StrictBaseModel):
    """Generic status item for templating."""

    description: str
    owner: str | None = None
    due_date: date | None = None
    severity: str | None = None


class StatusReportPayload(StrictBaseModel):
    """Payload used to render the status report template."""

    reporting_period: str
    overall_health: str
    highlights: list[str]
    schedule: dict[str, object]
    risks: list[dict[str, object]]
    next_steps: list[StatusReportItem]


class DiagramArtifact(StrictBaseModel):
    """Reference to generated diagram resources."""

    graphviz_svg_resource: str | None = None
    mermaid_markdown_resource: str | None = None


class ActionItem(StrictBaseModel):
    """Action item entry."""

    id: str
    description: str
    owner: str
    due_date: str | None = None
    status: str = Field(default="Open")


class ActionItemLog(StrictBaseModel):
    """Collection of action items."""

    items: list[ActionItem]


class MeetingSummary(StrictBaseModel):
    """Summarized meeting content."""

    decisions: list[str]
    action_items: ActionItemLog
    notes: list[str]


class Stakeholder(StrictBaseModel):
    """Stakeholder analysis entry."""

    name: str
    influence: str
    interest: str
    role: str | None = None
    engagement_strategy: str | None = None


class StakeholderMatrixResult(StrictBaseModel):
    """Stakeholder analysis output."""

    stakeholders: list[Stakeholder]
    mermaid_resource: str | None = None


class HealthDashboard(StrictBaseModel):
    """Aggregate project health snapshot."""

    status_summary: str
    schedule_health: str
    cost_health: str
    risk_health: str
    upcoming_milestones: list[str]
    notes: str | None = None
