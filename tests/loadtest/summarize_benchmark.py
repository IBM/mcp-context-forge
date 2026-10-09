# -*- coding: utf-8 -*-
"""Location: ./tests/loadtest/summarize_benchmark.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Put aggregate benchmark metrics first in Locust HTML and stats CSV reports.
"""

# Standard
import argparse
from collections.abc import Sequence
import csv
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import subprocess

# Docker applies compose `reservations.cpus` only in swarm mode, so a running
# container never carries the value; read it from the compose config instead.
RESOURCE_HEADERS = ("Service", "Replicas", "CPU limit", "CPU reservation", "Mem limit", "Mem reservation")
_DOCKER_FORMAT = (
    '{{index .Config.Labels "com.docker.compose.service"}}\t{{.HostConfig.NanoCpus}}\t{{.HostConfig.CpuQuota}}\t{{.HostConfig.CpuPeriod}}\t{{.HostConfig.Memory}}\t{{.HostConfig.MemoryReservation}}'
    '\t{{index .Config.Labels "com.docker.compose.project.config_files"}}\t{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
)
# The Locust bundle titles percentile columns `100*<expr>+"%ile (ms)"`. Rewrite the
# suffix so the rendered header reads p50, p90, p99 like the summary table above it.
_PERCENTILE_TITLE = re.compile(r'(100\*[^+"]{1,20}?)\+"%ile \(ms\)"')


def _git_version() -> str:
    """Describe the checked-out commit as a short SHA plus any tag on it.

    Returns:
        `<sha>`, `<sha> (<tag>)`, or an empty string outside a git checkout.
    """
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        tags = subprocess.run(["git", "tag", "--points-at", "HEAD"], capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{sha} ({', '.join(tags)})" if tags else sha


def append_history(history_path: Path, summary: Sequence[tuple[str, str]], reports: Sequence[tuple[str, str]] = ()) -> None:
    """Append one benchmark summary row to the historic results CSV.

    Args:
        history_path: CSV collecting every run; written with a header when absent.
        summary: Label/value pairs of the aggregate metrics for this run.
        reports: Label/value pairs naming the report files of this run.
    """
    header = ["Timestamp", "Commit"] + [label for label, _ in summary] + [label for label, _ in reports]
    write_header = not history_path.exists() or not history_path.read_text(encoding="utf-8").strip()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        if write_header:
            writer.writerow(header)
        writer.writerow([datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"), _git_version()] + [value for _, value in summary] + [value for _, value in reports])


def _cpus(nanocpus: str, quota: str, period: str) -> str:
    """Render a container CPU limit as a core count.

    Args:
        nanocpus: `HostConfig.NanoCpus`, set by compose `limits.cpus`.
        quota: `HostConfig.CpuQuota`, set by `--cpu-quota`.
        period: `HostConfig.CpuPeriod` matching `quota`.

    Returns:
        The core count, or `-` when the container runs unlimited.
    """
    cores = int(nanocpus) / 1e9
    if not cores and int(quota) > 0 and int(period) > 0:
        cores = int(quota) / int(period)
    return f"{cores:g}" if cores else "-"


def _bytes(value: str) -> str:
    """Render a container memory limit in the unit compose files use.

    Args:
        value: Byte count from `HostConfig`; `0` means unlimited.

    Returns:
        A size such as `4G` or `512M`, or `-` when unlimited.
    """
    size = int(value)
    for unit, scale in (("G", 2**30), ("M", 2**20)):
        if size >= scale:
            return f"{size / scale:g}{unit}"
    return str(size) if size else "-"


def _compose_cpu_reservations(config_files: str, working_dir: str) -> dict[str, str]:
    """Read the declared `reservations.cpus` of every service in a compose project.

    Args:
        config_files: Comma-separated compose files from the project label.
        working_dir: Directory the project started from, used for interpolation.

    Returns:
        Core counts keyed by service name; empty when the config cannot be read.
    """
    files = [argument for path in config_files.split(",") if path for argument in ("-f", path)]
    if not files:
        return {}
    try:
        rendered = subprocess.run(["docker", "compose", *files, "config", "--format", "json"], capture_output=True, text=True, check=True, cwd=working_dir or None).stdout
        services = json.loads(rendered)["services"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return {}
    declared = {name: ((service.get("deploy") or {}).get("resources") or {}).get("reservations", {}).get("cpus") for name, service in services.items()}
    return {name: f"{float(cores):g}" for name, cores in declared.items() if cores}


def docker_resources(project: str) -> list[tuple[str, ...]]:
    """Read the running replica count and resource limits of a compose project.

    Args:
        project: Compose project label, usually the directory the stack started from.

    Returns:
        One row per service, matching `RESOURCE_HEADERS`; empty when docker is
        unreachable or the project has no running container.
    """
    try:
        ids = subprocess.run(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}"], capture_output=True, text=True, check=True).stdout.split()
        if not ids:
            return []
        inspected = subprocess.run(["docker", "inspect", "--format", _DOCKER_FORMAT, *ids], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    replicas: dict[str, int] = {}
    limits: dict[str, tuple[str, str, str]] = {}
    config_files = working_dir = ""
    for line in inspected.splitlines():
        service, nanocpus, quota, period, memory, reservation, config_files, working_dir = line.split("\t")
        if not service:
            continue
        replicas[service] = replicas.get(service, 0) + 1
        # ponytail: first container of a service wins; scale a service with uneven
        # limits and the odd replica stays hidden.
        limits.setdefault(service, (_cpus(nanocpus, quota, period), _bytes(memory), _bytes(reservation)))
    cpu_reservations = _compose_cpu_reservations(config_files, working_dir)
    return [(service, str(replicas[service]), limits[service][0], cpu_reservations.get(service, "-"), *limits[service][1:]) for service in sorted(replicas)]


def _table(anchor: str, title: str, headers: Sequence[str], rows: Sequence[Sequence[str]], row_header: bool = False) -> str:
    """Render one titled HTML table section.

    Args:
        anchor: Unique id used by the heading and the table label.
        title: Heading text above the table.
        headers: Column labels.
        rows: Table body, one tuple per row.
        row_header: Render the first cell of each row as a row header.

    Returns:
        The section markup.
    """
    body = ""
    for row in rows:
        cells = ""
        for index, value in enumerate(row):
            if row_header and index == 0:
                cells += f'<th scope="row" style="padding:8px 16px;text-align:left;font-weight:400;">{escape(value)}</th>'
            else:
                cells += f'<td style="padding:8px 16px;font-variant-numeric:tabular-nums;">{escape(value)}</td>'
        body += f'<tr style="border-bottom:1px solid #e2e8f0;">{cells}</tr>'
    return (
        f'<section aria-labelledby="{anchor}-heading" style="padding:24px;background:#fff;color:#111;">'
        f'<h2 id="{anchor}-heading" style="margin:0 0 16px;text-align:center;font:600 24px system-ui;">{escape(title)}</h2>'
        f'<div role="region" aria-label="{escape(title)}" tabindex="0" style="overflow-x:auto;">'
        f'<table aria-labelledby="{anchor}-heading" style="margin:0 auto;border-collapse:collapse;font:16px/1.6 system-ui;white-space:nowrap;text-align:center;">'
        '<thead><tr style="background:#f1f5f9;">'
        + "".join(f'<th scope="col" style="padding:8px 16px;">{escape(label)}</th>' for label in headers)
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div></section>\n"
    )


def summarize_reports(
    html_path: Path,
    csv_path: Path,
    context: list[tuple[str, str]] | None = None,
    resources: list[tuple[str, ...]] | None = None,
    history_path: Path | None = None,
) -> None:
    """Add the summary tables to the Locust HTML report.

    Args:
        html_path: Locust HTML report to update after Locust exits.
        csv_path: Locust stats CSV containing the aggregate metrics; read only.
        context: Run settings such as mode, host and server, shown before the metrics.
        resources: Service resource rows matching `RESOURCE_HEADERS`.
        history_path: CSV that collects the aggregate metrics of every run.
    """
    context = context or []
    resources = resources or []
    with csv_path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    aggregate = next(row for row in rows if row["Name"] == "Aggregated" and not row["Type"])
    metrics = (
        ("Average", "Average Response Time"),
        ("Min", "Min Response Time"),
        ("Max", "Max Response Time"),
        ("p50", "50%"),
        ("p90", "90%"),
        ("p95", "95%"),
        ("p99", "99%"),
    )
    requests = int(aggregate["Request Count"])
    failures = int(aggregate["Failure Count"])
    error_percent = failures / requests * 100 if requests else 0.0
    summary = [
        ("Requests/sec (RPS)", f"{float(aggregate['Requests/s']):.2f}"),
        ("Error rate", f"{error_percent:.2f}%"),
        ("Total Requests", str(requests)),
        ("Total Failures", str(failures)),
    ]
    for label, column in metrics:
        value = aggregate[column]
        formatted = f"{float(value):.2f}" if value and value != "N/A" else "N/A"
        summary.append((f"{label} (ms)", formatted))
    if history_path:
        append_history(history_path, summary, (("HTML Report", html_path.name),))
    html = _PERCENTILE_TITLE.sub(r'"p"+\1', html_path.read_text(encoding="utf-8"))
    root = '<div id="root"></div>'
    if root not in html:
        raise ValueError("Locust HTML report has no root container")
    title = f"Benchmark summary Commit - {_git_version() or 'unknown'}"
    panel = _table("benchmark-summary", title, tuple(label for label, _ in summary), [tuple(value for _, value in summary)])
    endpoint_rows = []
    for row in sorted((row for row in rows if row is not aggregate), key=lambda row: int(row["Request Count"]), reverse=True):
        p99 = row["99%"]
        endpoint_rows.append(
            (
                row["Name"],
                str(int(row["Request Count"])),
                str(int(row["Failure Count"])),
                f"{float(row['Requests/s']):.1f}",
                f"{float(row['Average Response Time']):.1f}",
                f"{float(p99):.1f}" if p99 and p99 != "N/A" else "N/A",
            )
        )
    panel += _table("endpoint-breakdown", "Endpoint breakdown", ("Name", "Reqs", "Fails", "RPS", "Avg(ms)", "p99(ms)"), endpoint_rows, row_header=True)
    if context:
        panel += _table("run-context", "Run context", ("Setting", "Value"), context, row_header=True)
    if resources:
        panel += _table("service-resources", "Service resources", RESOURCE_HEADERS, resources, row_header=True)
    html_path.write_text(html.replace(root, panel + root, 1), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--mode")
    parser.add_argument("--host")
    parser.add_argument("--server")
    parser.add_argument("--project")
    parser.add_argument("--history", type=Path, default=Path("tests/loadtest/historic_load_data.csv"))
    args = parser.parse_args()
    run_context = [(label, value) for label, value in (("Mode", args.mode), ("Host", args.host), ("Server", args.server)) if value]
    summarize_reports(args.html, args.csv, run_context, docker_resources(args.project) if args.project else [], args.history)
