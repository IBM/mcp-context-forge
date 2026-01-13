# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pm_mcp_server/src/pm_mcp_server/tools/reporting.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Reporting helpers (status reports, dashboards).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from jinja2 import Template
import orjson

from pm_mcp_server.resource_store import GLOBAL_RESOURCE_STORE
from pm_mcp_server.schemata import HealthDashboard, StatusReportPayload


def _load_template(name: str) -> Template:
    from importlib import resources

    template_bytes = resources.files("pm_mcp_server.data.templates").joinpath(name).read_bytes()
    return Template(template_bytes.decode("utf-8"))


def status_report_generator(payload: StatusReportPayload) -> dict[str, str]:
    """Render markdown status report and return metadata."""

    template = _load_template("status_report.md.j2")
    markdown = template.render(**payload.model_dump(mode="json"))
    resource_id = GLOBAL_RESOURCE_STORE.add(
        markdown.encode("utf-8"), "text/markdown", prefix="report"
    )
    return {
        "resource_id": resource_id,
        "markdown_preview": markdown,
    }


def project_health_dashboard(snapshot: HealthDashboard) -> dict[str, object]:
    """Return structured dashboard summary and persist pretty JSON resource."""

    summary = {
        "status_summary": snapshot.status_summary,
        "schedule_health": snapshot.schedule_health,
        "cost_health": snapshot.cost_health,
        "risk_health": snapshot.risk_health,
        "upcoming_milestones": snapshot.upcoming_milestones,
        "notes": snapshot.notes,
    }
    resource_id = GLOBAL_RESOURCE_STORE.add(
        orjson.dumps(summary, option=orjson.OPT_INDENT_2),
        "application/json",
        prefix="dashboard",
    )
    summary["resource_id"] = resource_id
    return summary


def project_brief_generator(
    name: str,
    objectives: Iterable[str],
    success_criteria: Iterable[str],
    budget: float,
    timeline: str,
) -> dict[str, object]:
    """Produce concise project brief summary."""

    brief = {
        "project_name": name,
        "objectives": list(objectives),
        "success_criteria": list(success_criteria),
        "budget": budget,
        "timeline": timeline,
    }
    resource_id = GLOBAL_RESOURCE_STORE.add(
        orjson.dumps(brief, option=orjson.OPT_INDENT_2),
        "application/json",
        prefix="brief",
    )
    brief["resource_id"] = resource_id
    return brief


def lessons_learned_catalog(entries: list[dict[str, str]]) -> dict[str, list[str]]:
    """Group retrospectives by theme."""

    catalog: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        theme = entry.get("theme", "general")
        insight = entry.get("insight", "")
        if insight:
            catalog[theme].append(insight)
    return {theme: items for theme, items in catalog.items()}


def document_template_library() -> dict[str, str]:
    """Expose packaged templates as downloadable resources."""

    from importlib import resources

    resource_map: dict[str, str] = {}
    templates_pkg = resources.files("pm_mcp_server.data.templates")
    mime_lookup = {
        "status_report.md.j2": "text/x-jinja",
        "raid_log.csv": "text/csv",
    }
    for path in mime_lookup:
        data = templates_pkg.joinpath(path).read_bytes()
        resource_id = GLOBAL_RESOURCE_STORE.add(data, mime_lookup[path], prefix="template")
        resource_map[path] = resource_id
    return resource_map
