# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pm_mcp_server/src/pm_mcp_server/schemata.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Pydantic models used by the project management MCP server.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    """Base model with strict validation used across schemas."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WBSNode(StrictBaseModel):
    """Work breakdown element."""

    id: str = Field(..., description="WBS identifier, e.g., 1.1")
    name: str = Field(..., description="Work package name")
    owner: Optional[str] = Field(None, description="Responsible owner")
    estimate_days: Optional[float] = Field(None, ge=0, description="Estimated duration in days")
    children: List["WBSNode"] = Field(default_factory=list, description="Sub-elements")


class ScheduleTask(StrictBaseModel):
    """Task definition for scheduling and CPM calculations."""

    id: str
    name: str
    duration_days: float = Field(..., ge=0.0)
    dependencies: List[str] = Field(default_factory=list)
    owner: Optional[str] = None
    earliest_start: Optional[float] = None
    earliest_finish: Optional[float] = None
    latest_start: Optional[float] = None
    latest_finish: Optional[float] = None
    slack: Optional[float] = None
    is_critical: Optional[bool] = None


class ScheduleModel(StrictBaseModel):
    """Composite schedule representation."""

    tasks: List[ScheduleTask]
    calendar: Optional[str] = Field(default="standard", description="Calendar profile identifier")


class CriticalPathResult(StrictBaseModel):
    """Critical path computation result."""

    tasks: List[ScheduleTask]
    project_duration: float = Field(..., ge=0.0)
    critical_task_ids: List[str]
    generated_resources: Dict[str, str] = Field(default_factory=dict)


class RiskEntry(StrictBaseModel):
    """Risk register element."""

    id: str
    description: str
    probability: float = Field(..., ge=0.0, le=1.0)
    impact: float = Field(..., ge=0.0, le=1.0)
    mitigation: Optional[str] = None
    owner: Optional[str] = None
    status: str = Field(default="Open")

    @property
    def severity(self) -> float:
        return self.probability * self.impact


class RiskRegister(StrictBaseModel):
    """Risk register results."""

    risks: List[RiskEntry]
    high_risk_ids: List[str]


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

    period_metrics: List[EarnedValuePeriodMetric]
    cpi: float
    spi: float
    estimate_at_completion: float
    variance_at_completion: float


class StatusReportItem(StrictBaseModel):
    """Generic status item for templating."""

    description: str
    owner: Optional[str] = None
    due_date: Optional[date] = None
    severity: Optional[str] = None


class StatusReportPayload(StrictBaseModel):
    """Payload used to render the status report template."""

    reporting_period: str
    overall_health: str
    highlights: List[str]
    schedule: Dict[str, object]
    risks: List[Dict[str, object]]
    next_steps: List[StatusReportItem]


class DiagramArtifact(StrictBaseModel):
    """Reference to generated diagram resources."""

    graphviz_svg_resource: Optional[str] = None
    mermaid_markdown_resource: Optional[str] = None


class ActionItem(StrictBaseModel):
    """Action item entry."""

    id: str
    description: str
    owner: str
    due_date: Optional[str] = None
    status: str = Field(default="Open")


class ActionItemLog(StrictBaseModel):
    """Collection of action items."""

    items: List[ActionItem]


class MeetingSummary(StrictBaseModel):
    """Summarized meeting content."""

    decisions: List[str]
    action_items: ActionItemLog
    notes: List[str]


class Stakeholder(StrictBaseModel):
    """Stakeholder analysis entry."""

    name: str
    influence: str
    interest: str
    role: Optional[str] = None
    engagement_strategy: Optional[str] = None


class StakeholderMatrixResult(StrictBaseModel):
    """Stakeholder analysis output."""

    stakeholders: List[Stakeholder]
    mermaid_resource: Optional[str] = None


class HealthDashboard(StrictBaseModel):
    """Aggregate project health snapshot."""

    status_summary: str
    schedule_health: str
    cost_health: str
    risk_health: str
    upcoming_milestones: List[str]
    notes: Optional[str] = None
