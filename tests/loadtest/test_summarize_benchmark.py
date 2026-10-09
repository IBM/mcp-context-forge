# -*- coding: utf-8 -*-
"""Location: ./tests/loadtest/test_summarize_benchmark.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Check report summaries when no requests complete.
"""

# Standard
from pathlib import Path
import subprocess
from xml.etree import ElementTree

# Local
from tests.loadtest.summarize_benchmark import docker_resources, summarize_reports


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

    summarize_reports(html_path, csv_path, [("Mode", "legacy"), ("Host", "http://localhost:8080")], [("gateway", "3", "4", "4", "4G", "4G")])

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
    assert [cell.text for cell in resource_table.findall("./tbody/tr/td")] == ["3", "4", "4", "4G", "4G"]


def test_docker_resources_groups_replicas_and_renders_limits(monkeypatch) -> None:
    """Count one row per service, convert docker's raw limits, and read compose CPU reservations."""
    labels = "/stack/docker-compose.yml,/stack/docker-compose.perf.yml\t/stack"
    inspected = "\n".join(
        (
            f"gateway\t4000000000\t0\t100000\t4294967296\t4294967296\t{labels}",
            f"gateway\t4000000000\t0\t100000\t4294967296\t4294967296\t{labels}",
            f"redis\t0\t50000\t100000\t536870912\t0\t{labels}",
        )
    )
    config = '{"services": {"gateway": {"deploy": {"resources": {"reservations": {"cpus": 4, "memory": "4G"}}}}, "redis": {"deploy": {}}}}'
    seen: dict[str, list[str]] = {}

    def fake_run(command, **kwargs):
        """Answer `docker ps`, `docker inspect` and `docker compose config` with fixtures.

        Args:
            command: Argument list the module passes to `subprocess.run`.
            kwargs: `subprocess.run` options; only `cwd` is inspected.

        Returns:
            A completed process carrying the matching stdout.
        """
        seen[command[1]] = [*command, str(kwargs.get("cwd"))]
        stdout = {"ps": "a b c\n", "inspect": inspected}.get(command[1], config)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_resources("proj") == [("gateway", "2", "4", "4", "4G", "4G"), ("redis", "1", "0.5", "-", "512M", "-")]
    assert seen["compose"] == ["docker", "compose", "-f", "/stack/docker-compose.yml", "-f", "/stack/docker-compose.perf.yml", "config", "--format", "json", "/stack"]


def test_docker_resources_without_docker(monkeypatch) -> None:
    """Drop the table instead of failing the run when docker is unreachable."""

    def fail(command, **_kwargs):
        """Raise the error `subprocess.run` raises when docker is absent.

        Args:
            command: Argument list the module passes to `subprocess.run`.
            _kwargs: Ignored `subprocess.run` options.

        Raises:
            FileNotFoundError: Always, standing in for a missing docker binary.
        """
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(subprocess, "run", fail)

    assert docker_resources("proj") == []
