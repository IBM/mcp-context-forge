# -*- coding: utf-8 -*-
"""Module Description.
Location: ./mcp-servers/python/pm_mcp_server/tests/unit/tools/test_governance.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

from pm_mcp_server.schemata import ChangeRequest, EarnedValueInput, RiskEntry
from pm_mcp_server.tools import governance


def test_risk_register_ranks_highest_severity():
    risks = [
        RiskEntry(id="R1", description="Vendor delay", probability=0.5, impact=0.8),
        RiskEntry(id="R2", description="Scope creep", probability=0.3, impact=0.2),
    ]
    register = governance.risk_register_manager(risks)
    assert register.risks[0].id == "R1"
    assert register.high_risk_ids == ["R1"]


def test_change_request_tracker_sums_impacts():
    result = governance.change_request_tracker(
        [
            ChangeRequest(
                id="CR1", description="Extend scope", schedule_impact_days=3, cost_impact=2000
            ),
            ChangeRequest(
                id="CR2",
                description="Refactor",
                schedule_impact_days=-1,
                cost_impact=-500,
                status="Approved",
            ),
        ]
    )
    assert result["count"] == 2
    assert result["total_schedule_days"] == 2
    assert result["approved"] == 1


def test_baseline_vs_actual_flags_variance():
    report = governance.baseline_vs_actual({"cost": 100}, {"cost": 130}, tolerance_percent=20)
    assert report["cost"]["variance"] == 30
    assert report["cost"]["exceeds_tolerance"] is True


def test_earned_value_calculator_outputs_metrics():
    values = [
        EarnedValueInput(period="2024-01", planned_value=100, earned_value=90, actual_cost=110),
        EarnedValueInput(period="2024-02", planned_value=120, earned_value=130, actual_cost=115),
    ]
    result = governance.earned_value_calculator(values, budget_at_completion=500)
    assert result.period_metrics[-1].cpi > 0
    assert result.estimate_at_completion > 0
