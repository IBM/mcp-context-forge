# -*- coding: utf-8 -*-
"""Tests for analyze_query_log utilities."""

# Standard
from pathlib import Path
import sys

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.utils import analyze_query_log


def _write_jsonl(path: Path, entries):
    lines = [orjson.dumps(entry).decode() for entry in entries]
    path.write_text("\n".join(lines) + "\n")


def test_load_json_log_skips_invalid_lines(tmp_path: Path):
    log_path = tmp_path / "log.jsonl"
    log_path.write_text("{}\ninvalid\n{\"query_count\": 1}\n\n")

    entries = analyze_query_log.load_json_log(log_path)

    assert len(entries) == 2
    assert entries[0] == {}
    assert entries[1]["query_count"] == 1


def test_analyze_logs_basic_stats():
    entries = [
        {"method": "GET", "path": "/a", "query_count": 2, "total_query_ms": 10, "n1_issues": [{"pattern": "select *", "table": "t", "count": 2}]},
        {"method": "GET", "path": "/a", "query_count": 3, "total_query_ms": 5, "n1_issues": []},
        {"method": "POST", "path": "/b", "query_count": 1, "total_query_ms": 2},
    ]

    analysis = analyze_query_log.analyze_logs(entries)

    assert analysis["total_requests"] == 3
    assert analysis["total_queries"] == 6
    assert analysis["avg_queries_per_request"] == 2.0
    assert analysis["requests_with_n1"] == 1
    assert analysis["n1_percentage"] == 33.3
    assert analysis["top_n1_patterns"][0][0].startswith("t:")


def test_print_report_outputs_summary(capsys: pytest.CaptureFixture[str]):
    analysis = {
        "total_requests": 1,
        "total_queries": 2,
        "avg_queries_per_request": 2.0,
        "requests_with_n1": 0,
        "n1_percentage": 0,
        "endpoint_stats": [("GET /", {"count": 1, "total_queries": 2, "avg_queries": 2.0, "max_queries": 2, "n1_count": 0})],
        "top_n1_patterns": [],
    }

    analyze_query_log.print_report(analysis)
    captured = capsys.readouterr().out

    assert "DATABASE QUERY LOG ANALYSIS" in captured
    assert "SUMMARY" in captured


def test_main_missing_log_file(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    missing_path = tmp_path / "missing.jsonl"
    monkeypatch.setattr(sys, "argv", ["prog", "--json", str(missing_path)])

    exit_code = analyze_query_log.main()
    captured = capsys.readouterr().out

    assert exit_code == 1
    assert "Log file not found" in captured


def test_main_empty_log_file(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    log_path = tmp_path / "empty.jsonl"
    log_path.write_text("")
    monkeypatch.setattr(sys, "argv", ["prog", "--json", str(log_path)])

    exit_code = analyze_query_log.main()
    captured = capsys.readouterr().out

    assert exit_code == 1
    assert "Log file is empty" in captured


def test_main_invalid_entries(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    log_path = tmp_path / "invalid.jsonl"
    log_path.write_text("invalid\n")
    monkeypatch.setattr(sys, "argv", ["prog", "--json", str(log_path)])

    exit_code = analyze_query_log.main()
    captured = capsys.readouterr().out

    assert exit_code == 1
    assert "No valid entries" in captured


def test_main_success_and_n1_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    log_path = tmp_path / "valid.jsonl"
    _write_jsonl(
        log_path,
        [
            {"method": "GET", "path": "/", "query_count": 1, "total_query_ms": 1, "n1_issues": []},
            {"method": "GET", "path": "/", "query_count": 2, "total_query_ms": 2, "n1_issues": [{"pattern": "select", "table": "t", "count": 1}]},
        ],
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--json", str(log_path)])

    exit_code = analyze_query_log.main()
    captured = capsys.readouterr().out

    assert "Loaded 2 request entries" in captured
    assert exit_code == 1  # N+1 issues present
