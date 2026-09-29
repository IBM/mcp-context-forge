# -*- coding: utf-8 -*-
"""Location: ./tests/loadtest/summarize_prod_benchmark.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Put aggregate benchmark metrics first in Locust HTML and stats CSV reports.
"""

# Standard
import argparse
from collections.abc import Sequence
import csv
from html import escape
import os
from pathlib import Path
import re

# Third-Party
import yaml

RESOURCE_HEADERS = ("Service", "Replicas", "CPU limit", "Mem limit", "CPU reservation", "Mem reservation")
_COMPOSE_VAR = re.compile(r"^\$\{(\w+)(?::-([^}]*))?\}$")
# The Locust bundle titles percentile columns `100*<expr>+"%ile (ms)"`. Rewrite the
# suffix so the rendered header reads p50, p90, p99 like the summary table above it.
_PERCENTILE_TITLE = re.compile(r'(100\*[^+"]{1,20}?)\+"%ile \(ms\)"')


def _expand(value: object) -> str:
    """Resolve a compose `${VAR:-default}` placeholder against the environment.

    Args:
        value: Raw compose value, either a literal or a variable placeholder.

    Returns:
        The environment value, the placeholder default, or the literal.
    """
    text = str(value).strip()
    match = _COMPOSE_VAR.match(text)
    if not match:
        return text
    return os.environ.get(match.group(1)) or match.group(2) or ""


def compose_resources(compose_path: Path) -> list[tuple[str, ...]]:
    """Read the per-service replica count and resource pins from a compose file.

    Args:
        compose_path: Compose file holding the `deploy` blocks.

    Returns:
        One row per service, matching `RESOURCE_HEADERS`.
    """
    services = (yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}).get("services") or {}
    rows = []
    for name, service in services.items():
        deploy = (service or {}).get("deploy") or {}
        resources = deploy.get("resources") or {}
        limits = resources.get("limits") or {}
        reservations = resources.get("reservations") or {}
        rows.append(
            (
                name,
                _expand(deploy.get("replicas", 1)),
                str(limits.get("cpus", "-")),
                str(limits.get("memory", "-")),
                str(reservations.get("cpus", "-")),
                str(reservations.get("memory", "-")),
            )
        )
    return rows


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


def summarize_reports(html_path: Path, csv_path: Path, context: list[tuple[str, str]] | None = None, resources: list[tuple[str, ...]] | None = None) -> None:
    """Add HTML summary tables and move the aggregate CSV row before endpoint rows.

    Args:
        html_path: Locust HTML report to update after Locust exits.
        csv_path: Locust stats CSV containing the aggregate metrics.
        context: Run settings such as mode, host and server, shown before the metrics.
        resources: Service resource rows matching `RESOURCE_HEADERS`.
    """
    context = context or []
    resources = resources or []
    with csv_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        fields = reader.fieldnames
        if fields is None:
            raise ValueError("Locust stats CSV has no header")
        rows = list(reader)
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
    html = _PERCENTILE_TITLE.sub(r'"p"+\1', html_path.read_text(encoding="utf-8"))
    root = '<div id="root"></div>'
    if root not in html:
        raise ValueError("Locust HTML report has no root container")
    panel = _table("benchmark-summary", "Benchmark summary", tuple(label for label, _ in summary), [tuple(value for _, value in summary)])
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
    with csv_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        for block in ([("Setting", "Value"), *context], [RESOURCE_HEADERS, *resources]):
            if len(block) > 1:
                writer.writerows(block)
                writer.writerow([])
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerow(aggregate)
        writer.writerows(row for row in rows if row is not aggregate)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--mode")
    parser.add_argument("--host")
    parser.add_argument("--server")
    parser.add_argument("--compose", type=Path)
    args = parser.parse_args()
    run_context = [(label, value) for label, value in (("Mode", args.mode), ("Host", args.host), ("Server", args.server)) if value]
    summarize_reports(args.html, args.csv, run_context, compose_resources(args.compose) if args.compose else [])
