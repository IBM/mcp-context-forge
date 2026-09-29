# -*- coding: utf-8 -*-
"""Location: ./tests/loadtest/test_summarize_prod_benchmark.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Check report summaries when no requests complete.
"""

# Standard
import csv
from pathlib import Path
from xml.etree import ElementTree

# Local
from tests.loadtest.summarize_prod_benchmark import summarize_reports


def test_empty_report_preserves_unavailable_percentiles(tmp_path: Path) -> None:
    """Keep missing percentiles distinct from measured zero latency."""
    html_path = tmp_path / "report.html"
    csv_path = tmp_path / "stats.csv"
    html_path.write_text('<html><body><script>t=[{title:100*e+"%ile (ms)"}]</script><div id="root"></div></body></html>', encoding="utf-8")
    csv_path.write_text(
        "Type,Name,Request Count,Failure Count,Requests/s,Average Response Time,Min Response Time,Max Response Time,50%,90%,95%,99%\n"
        "POST,tools/call,0,0,0,0,0,0,N/A,N/A,N/A,N/A\n"
        ",Aggregated,0,0,0,0,0,0,N/A,N/A,N/A,N/A\n",
        encoding="utf-8",
    )

    summarize_reports(html_path, csv_path, [("Mode", "legacy"), ("Host", "http://localhost:8080")], [("gateway", "3", "4", "4G", "4", "4G")])

    html = html_path.read_text(encoding="utf-8")
    table = ElementTree.fromstring(html).find(".//table")
    assert 'title:"p"+100*e' in html and "%ile" not in html
    assert table is not None
    values = dict(zip((cell.text for cell in table.findall("./thead/tr/th")), (cell.text for cell in table.findall("./tbody/tr/td")), strict=True))
    assert values["Requests/sec (RPS)"] == "0.00"
    assert values["Error rate"] == "0.00%"
    for percentile in ("p50", "p90", "p95", "p99"):
        assert values[f"{percentile} (ms)"] == "N/A"
    endpoint_table = ElementTree.fromstring(html).find('.//table[@aria-labelledby="endpoint-breakdown-heading"]')
    assert endpoint_table is not None
    endpoint_rows = endpoint_table.findall("./tbody/tr")
    assert [row.findtext("th") for row in endpoint_rows] == ["tools/call"]
    assert [cell.text for cell in endpoint_rows[0].findall("td")] == ["0", "0", "0.0", "0.0", "N/A"]
    context_table = ElementTree.fromstring(html).find('.//table[@aria-labelledby="run-context-heading"]')
    assert [(row.findtext("th"), row.findtext("td")) for row in context_table.findall("./tbody/tr")] == [("Mode", "legacy"), ("Host", "http://localhost:8080")]
    resource_table = ElementTree.fromstring(html).find('.//table[@aria-labelledby="service-resources-heading"]')
    assert [cell.text for cell in resource_table.findall("./tbody/tr/td")] == ["3", "4", "4G", "4", "4G"]
    blocks = csv_path.read_text(encoding="utf-8").split("\n\n")
    assert blocks[0].splitlines() == ["Setting,Value", "Mode,legacy", "Host,http://localhost:8080"]
    assert blocks[1].splitlines()[1] == "gateway,3,4,4G,4,4G"
    rows = list(csv.DictReader(blocks[-1].splitlines()))
    assert [row["Name"] for row in rows] == ["Aggregated", "tools/call"]
    assert rows[0]["99%"] == "N/A"
