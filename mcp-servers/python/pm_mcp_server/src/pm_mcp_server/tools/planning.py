# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pm_mcp_server/src/pm_mcp_server/tools/planning.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Planning and scheduling tools for the PM MCP server.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pm_mcp_server.schemata import (
    CriticalPathResult,
    DiagramArtifact,
    ScheduleModel,
    ScheduleTask,
    WBSNode,
)
from pm_mcp_server.services.diagram import (
    GraphvizUnavailableError,
    render_dependency_network,
    render_gantt_chart,
)

logger = logging.getLogger(__name__)


_SENTENCE_SPLIT = re.compile(r"[\n\.;]+")
_CONJUNCTION_SPLIT = re.compile(r"\b(?:and|then|followed by)\b", flags=re.IGNORECASE)


@dataclass
class ConstraintBundle:
    """Simple holder for optional constraints."""

    finish_no_later_than: str | None = None
    budget_limit: float | None = None


def _tokenize_scope(scope: str) -> list[str]:
    sentences = [chunk.strip() for chunk in _SENTENCE_SPLIT.split(scope) if chunk.strip()]
    tasks: list[str] = []
    for sentence in sentences:
        fragments = [frag.strip() for frag in _CONJUNCTION_SPLIT.split(sentence) if frag.strip()]
        tasks.extend(fragments)
    logger.debug("Tokenized scope '%s' into tasks %s", scope, tasks)
    return tasks or [scope.strip()]


def generate_work_breakdown(
    scope: str,
    phases: Sequence[str] | None = None,
    constraints: dict[str, str] | None = None,
) -> list[WBSNode]:
    """Derive a simple WBS from narrative scope and optional phases."""

    constraint_bundle = ConstraintBundle(
        finish_no_later_than=constraints.get("finish_no_later_than") if constraints else None,
        budget_limit=float(constraints["budget_limit"])
        if constraints and "budget_limit" in constraints
        else None,
    )
    tasks = _tokenize_scope(scope)

    if phases:
        per_phase = max(1, math.ceil(len(tasks) / len(phases)))
        phase_nodes: list[WBSNode] = []
        iterator = iter(tasks)
        for idx, phase in enumerate(phases, start=1):
            children: list[WBSNode] = []
            for child_idx in range(1, per_phase + 1):
                try:
                    task = next(iterator)
                except StopIteration:
                    break
                child_id = f"{idx}.{child_idx}"
                children.append(
                    WBSNode(
                        id=child_id,
                        name=task.capitalize(),
                        owner=None,
                        estimate_days=2.0,
                        children=[],
                    )
                )
            phase_nodes.append(
                WBSNode(
                    id=str(idx),
                    name=phase,
                    owner=None,
                    estimate_days=sum(child.estimate_days or 0 for child in children) or None,
                    children=children,
                )
            )
        remaining = list(iterator)
        for extra_idx, task in enumerate(remaining, start=len(phase_nodes) + 1):
            phase_nodes.append(
                WBSNode(
                    id=str(extra_idx),
                    name=task.capitalize(),
                    owner=None,
                    estimate_days=2.0,
                    children=[],
                )
            )
        _annotate_constraints(phase_nodes, constraint_bundle)
        return phase_nodes

    nodes = [
        WBSNode(
            id=str(idx),
            name=task.capitalize(),
            owner=None,
            estimate_days=2.0,
            children=[],
        )
        for idx, task in enumerate(tasks, start=1)
    ]
    _annotate_constraints(nodes, constraint_bundle)
    return nodes


def _annotate_constraints(nodes: list[WBSNode], bundle: ConstraintBundle) -> None:
    if not bundle.finish_no_later_than and not bundle.budget_limit:
        return
    info = []
    if bundle.finish_no_later_than:
        info.append(f"Finish by {bundle.finish_no_later_than}")
    if bundle.budget_limit:
        info.append(f"Budget cap {bundle.budget_limit:,.0f}")
    if not info:
        return
    note = "; ".join(info)
    # Attach note to top-level node if available; otherwise append as child comment
    if nodes:
        nodes[0].name = f"{nodes[0].name} ({note})"


def build_schedule(wbs: Sequence[WBSNode], default_owner: str | None = None) -> ScheduleModel:
    """Create a sequential schedule from WBS leaves."""

    flat_leaves = list(_iter_leaves(wbs))
    tasks: list[ScheduleTask] = []
    previous_id: str | None = None
    for idx, node in enumerate(flat_leaves, start=1):
        task_id = node.id.replace(".", "-") or f"T{idx}"
        duration = node.estimate_days if node.estimate_days is not None else 2.0
        dependencies = [previous_id] if previous_id else []
        tasks.append(
            ScheduleTask(
                id=task_id,
                name=node.name,
                duration_days=duration,
                dependencies=dependencies,
                owner=node.owner or default_owner,
            )
        )
        previous_id = task_id
    return ScheduleModel(tasks=tasks)


def _iter_leaves(nodes: Sequence[WBSNode]) -> Iterable[WBSNode]:
    for node in nodes:
        if node.children:
            yield from _iter_leaves(node.children)
        else:
            yield node


def critical_path_analysis(schedule: ScheduleModel) -> CriticalPathResult:
    """Run a deterministic CPM analysis over the schedule."""

    tasks = {task.id: task.model_copy(deep=True) for task in schedule.tasks}
    order = _topological_order(tasks)

    earliest: dict[str, float] = {}
    for task_id in order:
        task = tasks[task_id]
        if not task.dependencies:
            start = 0.0
        else:
            start = max(earliest[dep] + tasks[dep].duration_days for dep in task.dependencies)
        earliest[task_id] = start
        task.earliest_start = start
        task.earliest_finish = start + task.duration_days

    project_duration = (
        max((task.earliest_finish or 0.0) for task in tasks.values()) if tasks else 0.0
    )

    latest: dict[str, float] = {task_id: project_duration for task_id in tasks}
    for task_id in reversed(order):
        task = tasks[task_id]
        if not any(task_id in tasks[child].dependencies for child in tasks):
            lf = project_duration
        else:
            lf = min(
                latest[child] - tasks[child].duration_days
                for child in tasks
                if task_id in tasks[child].dependencies
            )
        latest[task_id] = lf
        task.latest_finish = lf
        task.latest_start = lf - task.duration_days
        task.slack = (
            (task.latest_start - task.earliest_start) if task.earliest_start is not None else 0.0
        )
        task.is_critical = abs(task.slack or 0.0) < 1e-6

    critical_ids = [task_id for task_id, task in tasks.items() if task.is_critical]
    generated_resources: dict[str, str] = {}
    try:
        diagram = render_dependency_network(ScheduleModel(tasks=list(tasks.values())), critical_ids)
        if diagram.graphviz_svg_resource:
            generated_resources["network_svg"] = diagram.graphviz_svg_resource
        if diagram.mermaid_markdown_resource:
            generated_resources["network_mermaid"] = diagram.mermaid_markdown_resource
    except GraphvizUnavailableError as exc:
        logger.warning("Graphviz unavailable, returning CPM results without diagrams: %s", exc)

    return CriticalPathResult(
        tasks=list(tasks.values()),
        project_duration=project_duration,
        critical_task_ids=critical_ids,
        generated_resources=generated_resources,
    )


def _topological_order(tasks: dict[str, ScheduleTask]) -> list[str]:
    resolved: list[str] = []
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(node: str) -> None:
        if node in permanent:
            return
        if node in temporary:
            raise ValueError("Cycle detected in dependencies")
        temporary.add(node)
        for dep in tasks[node].dependencies:
            if dep not in tasks:
                raise KeyError(f"Dependency '{dep}' missing from schedule")
            visit(dep)
        temporary.remove(node)
        permanent.add(node)
        resolved.append(node)

    for node in tasks:
        visit(node)
    return resolved


def gantt_artifacts(schedule: ScheduleModel, project_start: str | None) -> DiagramArtifact:
    """Create gantt artifacts using computed CPM fields."""

    tasks = [task.model_copy(deep=True) for task in schedule.tasks]
    try:
        return render_gantt_chart(tasks, project_start)
    except GraphvizUnavailableError as exc:
        logger.warning("Graphviz unavailable, skipping gantt diagram: %s", exc)
        return DiagramArtifact()


def schedule_optimizer(schedule: ScheduleModel) -> ScheduleModel:
    """Trivial optimizer that identifies sequential bottlenecks."""

    if not schedule.tasks:
        return schedule

    longest_task = max(schedule.tasks, key=lambda task: task.duration_days)
    logger.info(
        "Identified longest task %s with duration %.2f", longest_task.id, longest_task.duration_days
    )
    # Suggest splitting by halving duration in scenario copy for demonstration purposes
    optimized_tasks = []
    for task in schedule.tasks:
        if task.id == longest_task.id and task.duration_days > 3:
            optimized_tasks.append(
                task.model_copy(update={"duration_days": task.duration_days * 0.9})
            )
        else:
            optimized_tasks.append(task)
    return ScheduleModel(tasks=optimized_tasks, calendar=schedule.calendar)


def scope_guardrails(scope_statement: str, proposed_items: Sequence[str]) -> dict[str, object]:
    """Flag items that appear outside the defined scope."""

    normalized_scope = scope_statement.lower()
    out_of_scope: list[str] = []
    in_scope: list[str] = []
    for item in proposed_items:
        key_terms = [token for token in re.findall(r"\w+", item.lower()) if len(token) > 3]
        if any(term in normalized_scope for term in key_terms):
            in_scope.append(item)
        else:
            out_of_scope.append(item)
    return {
        "in_scope": in_scope,
        "out_of_scope": out_of_scope,
        "guardrail_summary": "Scope creep detected" if out_of_scope else "Within scope",
    }


def sprint_planning_helper(
    backlog: Sequence[dict[str, object]],
    sprint_capacity: float,
) -> dict[str, object]:
    """Select items for sprint based on priority and capacity."""

    sorted_backlog = sorted(
        backlog,
        key=lambda item: (item.get("priority", 999), -float(item.get("value", 0))),
    )
    committed: list[dict[str, object]] = []
    remaining_capacity = sprint_capacity
    for item in sorted_backlog:
        effort = float(item.get("effort", 1))
        if effort <= remaining_capacity:
            committed.append(item)
            remaining_capacity -= effort
    deferred = [item for item in sorted_backlog if item not in committed]
    return {
        "committed_items": committed,
        "deferred_items": deferred,
        "remaining_capacity": remaining_capacity,
    }
