# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pm_mcp_server/src/pm_mcp_server/tools/governance.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Governance-oriented tools (risks, change control, earned value).
"""

from __future__ import annotations

from pm_mcp_server.schemata import (
    ChangeRequest,
    EarnedValueInput,
    EarnedValuePeriodMetric,
    EarnedValueResult,
    RiskEntry,
    RiskRegister,
)


def risk_register_manager(risks: list[RiskEntry]) -> RiskRegister:
    """Return register metadata including high severity risks."""

    sorted_risks = sorted(risks, key=lambda risk: risk.severity, reverse=True)
    severities = [risk.severity for risk in sorted_risks]
    if not severities:
        threshold = 0.0
    else:
        high_count = max(1, round(len(severities) * 0.25))
        threshold = sorted(severities, reverse=True)[high_count - 1]
    high_risks = [risk.id for risk in sorted_risks if risk.severity >= threshold]
    return RiskRegister(risks=sorted_risks, high_risk_ids=high_risks)


def change_request_tracker(requests: list[ChangeRequest]) -> dict[str, object]:
    """Summarise change requests portfolio."""

    totals = {
        "count": len(requests),
        "approved": sum(1 for req in requests if req.status.lower() == "approved"),
        "proposed": sum(1 for req in requests if req.status.lower() == "proposed"),
        "rejected": sum(1 for req in requests if req.status.lower() == "rejected"),
        "total_schedule_days": sum(req.schedule_impact_days for req in requests),
        "total_cost_impact": sum(req.cost_impact for req in requests),
    }
    return totals


def baseline_vs_actual(
    planned: dict[str, float],
    actual: dict[str, float],
    tolerance_percent: float = 10.0,
) -> dict[str, dict[str, float | bool]]:
    """Compare planned vs actual metrics and flag variances."""

    report: dict[str, dict[str, float | bool]] = {}
    for key, planned_value in planned.items():
        actual_value = actual.get(key)
        if actual_value is None:
            continue
        variance = actual_value - planned_value
        variance_pct = (variance / planned_value * 100.0) if planned_value else 0.0
        report[key] = {
            "planned": planned_value,
            "actual": actual_value,
            "variance": variance,
            "variance_percent": variance_pct,
            "exceeds_tolerance": abs(variance_pct) > tolerance_percent,
        }
    return report


def earned_value_calculator(
    values: list[EarnedValueInput],
    budget_at_completion: float,
) -> EarnedValueResult:
    """Compute CPI/SPI metrics and EAC/VAC."""

    period_metrics: list[EarnedValuePeriodMetric] = []
    cumulative_pv = 0.0
    cumulative_ev = 0.0
    cumulative_ac = 0.0

    for entry in values:
        cumulative_pv += entry.planned_value
        cumulative_ev += entry.earned_value
        cumulative_ac += entry.actual_cost
        cpi = cumulative_ev / cumulative_ac if cumulative_ac else 0.0
        spi = cumulative_ev / cumulative_pv if cumulative_pv else 0.0
        period_metrics.append(
            EarnedValuePeriodMetric(
                period=entry.period,
                cpi=round(cpi, 3),
                spi=round(spi, 3),
                pv=cumulative_pv,
                ev=cumulative_ev,
                ac=cumulative_ac,
            )
        )

    cpi = period_metrics[-1].cpi if period_metrics else 0.0
    spi = period_metrics[-1].spi if period_metrics else 0.0
    estimate_at_completion = budget_at_completion / cpi if cpi else budget_at_completion
    variance_at_completion = budget_at_completion - estimate_at_completion

    return EarnedValueResult(
        period_metrics=period_metrics,
        cpi=cpi,
        spi=spi,
        estimate_at_completion=round(estimate_at_completion, 2),
        variance_at_completion=round(variance_at_completion, 2),
    )
