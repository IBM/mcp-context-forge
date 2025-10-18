# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pm_mcp_server/src/pm_mcp_server/services/diagram.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Utilities for producing diagram artefacts.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import date, timedelta

from dateutil.parser import isoparse

try:
    from graphviz import Digraph
except ImportError as exc:  # pragma: no cover - handled by raising runtime error
    Digraph = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from pm_mcp_server.resource_store import GLOBAL_RESOURCE_STORE
from pm_mcp_server.schemata import DiagramArtifact, ScheduleModel, ScheduleTask

logger = logging.getLogger(__name__)


class GraphvizUnavailableError(RuntimeError):
    """Raised when Graphviz binaries are missing."""


def _ensure_graphviz() -> None:
    if Digraph is None:
        raise GraphvizUnavailableError(
            "Graphviz Python bindings not installed. Install 'graphviz' package to enable diagrams."
        ) from _IMPORT_ERROR
    try:
        test_graph = Digraph("sanity")
        test_graph.node("A")
        test_graph.node("B")
        test_graph.edge("A", "B")
        test_graph.pipe(format="svg")
    except OSError as exc:  # Graphviz binary missing
        raise GraphvizUnavailableError(
            "Graphviz executables not found. Install graphviz package/binaries to enable diagrams."
        ) from exc


def render_dependency_network(
    schedule: ScheduleModel, critical_task_ids: Iterable[str]
) -> DiagramArtifact:
    """Render a dependency network diagram and mermaid fallback."""

    _ensure_graphviz()
    critical_set = set(critical_task_ids)
    graph = Digraph("project-network", graph_attr={"rankdir": "LR", "splines": "spline"})
    graph.attr("node", shape="box", style="rounded,filled", fontname="Helvetica")

    for task in schedule.tasks:
        is_critical = task.id in critical_set
        fill = "#FDEDEC" if is_critical else "#E8F1FB"
        color = "#D62728" if is_critical else "#1F77B4"
        label = f"{task.name}\n{task.duration_days}d"
        if task.earliest_start is not None:
            label += f"\nES {task.earliest_start:.1f}"
        if task.slack is not None:
            label += f"\nSlack {task.slack:.1f}"
        graph.node(task.id, label=label, fillcolor=fill, color=color)

    for task in schedule.tasks:
        for dep in task.dependencies:
            edge_color = "#D62728" if dep in critical_set and task.id in critical_set else "#1F77B4"
            graph.edge(dep, task.id, color=edge_color)

    svg_bytes = graph.pipe(format="svg")
    svg_resource = GLOBAL_RESOURCE_STORE.add(svg_bytes, "image/svg+xml", prefix="diagram")

    mermaid_lines = ["flowchart LR"]
    for task in schedule.tasks:
        label = task.name.replace("\n", " ")
        if task.id in critical_set:
            mermaid_lines.append(f"    {task.id}[/{label}/]")
        else:
            mermaid_lines.append(f"    {task.id}({label})")
    for task in schedule.tasks:
        for dep in task.dependencies:
            mermaid_lines.append(f"    {dep} --> {task.id}")

    mermaid_resource = GLOBAL_RESOURCE_STORE.add(
        "\n".join(mermaid_lines).encode("utf-8"), "text/mermaid", prefix="diagram"
    )

    return DiagramArtifact(
        graphviz_svg_resource=svg_resource,
        mermaid_markdown_resource=mermaid_resource,
    )


def render_gantt_chart(tasks: Sequence[ScheduleTask], project_start: str | None) -> DiagramArtifact:
    """Render a lightweight Gantt overview using Graphviz with mermaid fallback."""

    _ensure_graphviz()
    graph = Digraph("gantt", graph_attr={"rankdir": "LR", "nodesep": "0.5", "ranksep": "1"})
    graph.attr("node", shape="record", fontname="Helvetica", style="filled", fillcolor="#E8F1FB")

    start_date = isoparse(project_start).date() if project_start else date.today()

    mermaid_lines = ["gantt", "    dateFormat  YYYY-MM-DD", "    axisFormat  %m/%d"]

    for task in tasks:
        es = task.earliest_start or 0.0
        ef = task.earliest_finish or es + task.duration_days
        delta_start = timedelta(days=es)
        real_start = start_date + delta_start
        label = (
            f"{{{task.name}|Start: {real_start.isoformat()}|Duration: {task.duration_days:.1f}d}}"
        )
        graph.node(task.id, label=label)
        for dep in task.dependencies:
            graph.edge(dep, task.id, style="dotted")
        mermaid_lines.append(
            f"    {task.id} :{task.id}, {real_start.isoformat()}, {task.duration_days:.1f}d"
        )

    svg_bytes = graph.pipe(format="svg")
    svg_resource = GLOBAL_RESOURCE_STORE.add(svg_bytes, "image/svg+xml", prefix="gantt")
    mermaid_resource = GLOBAL_RESOURCE_STORE.add(
        "\n".join(mermaid_lines).encode("utf-8"), "text/mermaid", prefix="gantt"
    )

    return DiagramArtifact(
        graphviz_svg_resource=svg_resource,
        mermaid_markdown_resource=mermaid_resource,
    )
