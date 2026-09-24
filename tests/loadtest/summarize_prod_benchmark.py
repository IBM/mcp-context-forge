# -*- coding: utf-8 -*-
"""Location: ./tests/loadtest/summarize_prod_benchmark.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Put aggregate benchmark metrics first in Locust HTML and stats CSV reports.
"""

# Standard
import argparse
import csv
from html import escape
from pathlib import Path


def summarize_reports(html_path: Path, csv_path: Path) -> None:
    """Add HTML summary tables and move the aggregate CSV row before endpoint rows.

    Args:
        html_path: Locust HTML report to update after Locust exits.
        csv_path: Locust stats CSV containing the aggregate metrics.
    """
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
    html = html_path.read_text(encoding="utf-8")
    root = '<div id="root"></div>'
    if root not in html:
        raise ValueError("Locust HTML report has no root container")
    panel = (
        '<section aria-labelledby="benchmark-summary-heading" style="padding:24px;background:#fff;color:#111;">'
        '<h1 id="benchmark-summary-heading" style="margin:0 0 16px;text-align:center;font:600 24px system-ui;">Benchmark summary</h1>'
        '<div role="region" aria-label="Benchmark metrics" tabindex="0" style="overflow-x:auto;">'
        '<table aria-labelledby="benchmark-summary-heading" style="margin:0 auto;border-collapse:collapse;font:16px/1.6 system-ui;white-space:nowrap;text-align:center;">'
        '<thead><tr style="background:#f1f5f9;">'
        + "".join(f'<th scope="col" style="padding:8px 16px;">{escape(label)}</th>' for label, _ in summary)
        + '</tr></thead><tbody><tr style="border-bottom:1px solid #e2e8f0;">'
        + "".join(f'<td style="padding:8px 16px;font-variant-numeric:tabular-nums;">{escape(value)}</td>' for _, value in summary)
        + "</tr></tbody></table></div></section>\n"
    )
    endpoint_rows = []
    for row in sorted((row for row in rows if row is not aggregate), key=lambda row: int(row["Request Count"]), reverse=True):
        p99 = row["99%"]
        values = (
            str(int(row["Request Count"])),
            str(int(row["Failure Count"])),
            f"{float(row['Requests/s']):.1f}",
            f"{float(row['Average Response Time']):.1f}",
            f"{float(p99):.1f}" if p99 and p99 != "N/A" else "N/A",
        )
        endpoint_rows.append(
            '<tr style="border-bottom:1px solid #e2e8f0;">'
            f'<th scope="row" style="padding:8px 16px;text-align:left;font-weight:400;">{escape(row["Name"])}</th>'
            + "".join(f'<td style="padding:8px 16px;text-align:right;font-variant-numeric:tabular-nums;">{escape(value)}</td>' for value in values)
            + "</tr>"
        )
    panel += (
        '<section aria-labelledby="endpoint-breakdown-heading" style="padding:24px;background:#fff;color:#111;">'
        '<h2 id="endpoint-breakdown-heading" style="margin:0 0 16px;text-align:center;font:600 24px system-ui;">Endpoint breakdown</h2>'
        '<div role="region" aria-label="Endpoint metrics" tabindex="0" style="overflow-x:auto;">'
        '<table aria-labelledby="endpoint-breakdown-heading" style="margin:0 auto;border-collapse:collapse;font:16px/1.6 system-ui;white-space:nowrap;">'
        '<thead><tr style="background:#f1f5f9;">'
        + "".join(f'<th scope="col" style="padding:8px 16px;">{label}</th>' for label in ("Name", "Reqs", "Fails", "RPS", "Avg(ms)", "p99(ms)"))
        + "</tr></thead><tbody>"
        + "".join(endpoint_rows)
        + "</tbody></table></div></section>\n"
    )
    html_path.write_text(html.replace(root, panel + root, 1), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerow(aggregate)
        writer.writerows(row for row in rows if row is not aggregate)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    summarize_reports(args.html, args.csv)
