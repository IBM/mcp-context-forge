# -*- coding: utf-8 -*-
"""Module Description.
Location: ./mcp-servers/python/pm_mcp_server/tests/unit/tools/test_reporting.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

from pm_mcp_server.resource_store import GLOBAL_RESOURCE_STORE
from pm_mcp_server.schemata import StatusReportPayload
from pm_mcp_server.tools import reporting


def test_status_report_generator_renders_markdown():
    payload = StatusReportPayload(
        reporting_period="Week 1",
        overall_health="Green",
        highlights=["Kickoff complete"],
        schedule={"percent_complete": 25, "critical_items": ["Design"]},
        risks=[{"id": "R1", "severity": "High", "description": "", "owner": "PM"}],
        next_steps=[],
    )
    result = reporting.status_report_generator(payload)
    assert "resource_id" in result
    mime, content = GLOBAL_RESOURCE_STORE.get(result["resource_id"])
    assert mime == "text/markdown"
    assert "Project Status Report" in content.decode("utf-8")


def test_project_brief_generator_serialises_summary():
    brief = reporting.project_brief_generator(
        name="Apollo",
        objectives=["Launch MVP"],
        success_criteria=["Adoption"],
        budget=100000,
        timeline="Q1 2025",
    )
    assert brief["project_name"] == "Apollo"
    assert "resource_id" in brief


def test_document_template_library_exposes_templates():
    templates = reporting.document_template_library()
    assert "status_report.md.j2" in templates
