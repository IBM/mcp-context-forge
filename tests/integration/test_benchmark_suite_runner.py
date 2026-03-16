# -*- coding: utf-8 -*-
"""Integration-style tests for benchmark suite orchestration."""

# Standard
import json
from pathlib import Path
import textwrap

# Third-Party
import pytest

# First-Party
from benchmarks.contextforge.runner import ContainerRuntime, _detect_runtime, execute_suite


def _write_minimal_profile(path: Path, suite_extra: str = "") -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            [suite]
            name = "example"
            continue_on_failure = true
            output_root = "{path.parent.as_posix()}"
            {suite_extra}

            [defaults.setup]
            target_kind = "gateway"
            auth_mode = "none"
            plugins_enabled = false

            [defaults.build]
            rust_plugins = false
            profiling_image = false
            container_file = "Containerfile.lite"
            rebuild_policy = "never"

            [defaults.runtime]
            http_server = "gunicorn"
            host = "127.0.0.1"
            transport_type = "streamablehttp"

            [defaults.load]
            locustfile = "benchmarks/contextforge/locust/locustfile_benchmark_ab.py"
            users = 1
            spawn_rate = 1
            run_time = "5s"
            target_service = "nginx"

            [defaults.requests]
            enabled_groups = ["health"]
            disabled_groups = []
            enabled_endpoints = ["/health"]
            disabled_endpoints = []
            enabled_tags = []
            disabled_tags = []
            include_admin_endpoints = false
            include_mcp_endpoints = false
            include_resource_endpoints = false
            include_prompt_endpoints = false
            include_tool_endpoints = false

            [defaults.measurement]
            warmup_seconds = 1
            measure_seconds = 2
            profile_seconds = 1
            cooldown_seconds = 1

            [defaults.profiling]
            enabled = false
            py_spy = false
            tools = []

            [defaults.execution]
            retry_enabled = true
            max_attempts = 2
            capture_logs = true
            save_raw_results = true

            [[scenario]]
            name = "first"
            description = "First scenario"
            scenario_type = "gateway_core"

            [[scenario]]
            name = "second"
            description = "Second scenario"
            scenario_type = "gateway_core"
            """
        ),
        encoding="utf-8",
    )


def test_detect_runtime_skips_unusable_podman(monkeypatch):
    responses = {
        ("docker", "compose", "version"): (0, ""),
        ("docker", "info"): (0, ""),
        ("podman", "compose", "version"): (0, ""),
        ("podman", "info"): (125, "podman unavailable"),
    }

    def fake_run(args, cwd=None, capture_output=None, text=None, check=None):
        return type(
            "Result",
            (),
            {
                "returncode": responses.get(tuple(args), (127, ""))[0],
                "stdout": responses.get(tuple(args), (127, ""))[1],
                "stderr": responses.get(tuple(args), (127, ""))[1],
            },
        )()

    monkeypatch.setattr("tests.performance.benchmark_suite.subprocess.run", fake_run)
    runtime = _detect_runtime()
    assert runtime == ContainerRuntime(engine="docker", compose_cmd=("docker", "compose"))


def test_execute_suite_retries_and_continues_on_failure(tmp_path: Path, monkeypatch):
    profile = tmp_path / "suite.toml"
    _write_minimal_profile(profile)

    monkeypatch.setattr("tests.performance.benchmark_suite._detect_runtime", lambda: ContainerRuntime(engine="docker", compose_cmd=("docker", "compose")))
    monkeypatch.setattr("tests.performance.benchmark_suite._preflight_runtime", lambda runtime, suite: {"runtime": runtime.engine})

    attempts = {
        "first": iter(
            [
                {"status": "failed", "locust": {"status": "failed"}, "endpoint_metrics": {"status": "unavailable"}, "plugin_timing": {"status": "unavailable"}, "pyspy": {"status": "unavailable"}, "memray": {"status": "unavailable"}, "process_stats": {"status": "unavailable"}, "flamegraph_run": {"status": "failed"}, "database_metrics": {"status": "unavailable"}, "system_metrics": {"status": "unavailable"}, "log_paths": []},
                {"status": "ok", "locust": {"status": "ok"}, "endpoint_metrics": {"status": "ok", "aggregated": {"Request Count": "10", "Requests/s": "5", "95%": "10", "Failure Count": "0"}}, "plugin_timing": {"status": "unavailable"}, "pyspy": {"status": "unavailable"}, "memray": {"status": "unavailable"}, "process_stats": {"status": "unavailable"}, "flamegraph_run": {"status": "unavailable"}, "database_metrics": {"status": "ok"}, "system_metrics": {"status": "ok"}, "log_paths": []},
            ]
        ),
        "second": iter(
            [
                {"status": "failed", "locust": {"status": "failed"}, "endpoint_metrics": {"status": "unavailable"}, "plugin_timing": {"status": "unavailable"}, "pyspy": {"status": "unavailable"}, "memray": {"status": "unavailable"}, "process_stats": {"status": "unavailable"}, "flamegraph_run": {"status": "failed"}, "database_metrics": {"status": "unavailable"}, "system_metrics": {"status": "unavailable"}, "log_paths": []},
                {"status": "failed", "locust": {"status": "failed"}, "endpoint_metrics": {"status": "unavailable"}, "plugin_timing": {"status": "unavailable"}, "pyspy": {"status": "unavailable"}, "memray": {"status": "unavailable"}, "process_stats": {"status": "unavailable"}, "flamegraph_run": {"status": "failed"}, "database_metrics": {"status": "unavailable"}, "system_metrics": {"status": "unavailable"}, "log_paths": []},
            ]
        ),
    }

    def fake_execute_single_attempt(runtime, scenario, scenario_dir, flamegraph_enabled, capture_logs, attempt):
        return next(attempts[scenario["name"]])

    monkeypatch.setattr("tests.performance.benchmark_suite._execute_single_attempt", fake_execute_single_attempt)

    run_dir = execute_suite(str(profile), output_root=tmp_path / "out")
    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert run_summary["scenario_count"] == 2
    statuses = {item["scenario"]: item["status"] for item in run_summary["scenarios"]}
    assert statuses["first"] == "ok"
    assert statuses["second"] == "failed"


def test_execute_suite_writes_baseline_comparison(tmp_path: Path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "scenarios": [
                    {"scenario": "first", "rps": 10, "p95": 10, "failures": 0},
                    {"scenario": "second", "rps": 10, "p95": 10, "failures": 0},
                ]
            }
        ),
        encoding="utf-8",
    )
    profile = tmp_path / "suite.toml"
    _write_minimal_profile(
        profile,
        suite_extra=f'baseline_run = "{baseline.as_posix()}"\nbaseline_rps_drop_pct = 20\nbaseline_p95_regression_pct = 20\nbaseline_failure_increase = 0',
    )

    monkeypatch.setattr("tests.performance.benchmark_suite._detect_runtime", lambda: ContainerRuntime(engine="docker", compose_cmd=("docker", "compose")))
    monkeypatch.setattr("tests.performance.benchmark_suite._preflight_runtime", lambda runtime, suite: {"runtime": runtime.engine})
    monkeypatch.setattr(
        "tests.performance.benchmark_suite._execute_single_attempt",
        lambda runtime, scenario, scenario_dir, flamegraph_enabled, capture_logs, attempt: {
            "status": "ok",
            "locust": {"status": "ok"},
            "endpoint_metrics": {"status": "ok", "aggregated": {"Request Count": "10", "Requests/s": "9", "95%": "11", "Failure Count": "0"}},
            "plugin_timing": {"status": "unavailable"},
            "pyspy": {"status": "unavailable"},
            "memray": {"status": "unavailable"},
            "process_stats": {"status": "unavailable"},
            "flamegraph_run": {"status": "unavailable"},
            "database_metrics": {"status": "ok"},
            "system_metrics": {"status": "ok"},
            "log_paths": [],
        },
    )

    run_dir = execute_suite(str(profile), output_root=tmp_path / "out")
    payload = json.loads((run_dir / "baseline_comparison.json").read_text(encoding="utf-8"))
    assert payload["comparisons"][0]["status"] == "pass"
