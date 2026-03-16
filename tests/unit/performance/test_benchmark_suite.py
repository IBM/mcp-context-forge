# -*- coding: utf-8 -*-
"""Tests for the benchmark suite runner."""

# Standard
import json
import subprocess
import textwrap
from pathlib import Path

# Third-Party
import pytest

# First-Party
from benchmarks.contextforge.runner import (
    ContainerRuntime,
    REPO_ROOT,
    _a2a_registration_probe,
    _benchmark_registration_probe,
    _benchmark_token,
    _collect_system_metrics,
    _compose_candidates,
    _compose_probe_detail,
    _collect_plugin_timing,
    _compose_base_args,
    _compose_env_args,
    _ensure_benchmark_image,
    _ensure_locust_image,
    _ensure_podman_ready,
    _ensure_scenario_source,
    _is_mountable_runtime_path,
    _measurement_window_summary,
    _locust_run_command,
    _prepare_benchmark_build_context,
    _profiling_variant,
    _run_command,
    _scenario_image_name,
    _scenario_uses_a2a_fixture,
    _scenario_uses_fast_time_fixture,
    _scenario_env,
    _scenario_memory_metrics,
    _verify_a2a_runtime_expectations,
    _verify_runtime_expectations,
    _service_container_id,
    _write_compose_override,
    compare_scenarios,
    list_scenarios,
    main,
    regenerate_reports,
    resolve_suite,
)


def test_resolve_suite_applies_defaults_and_target_service(tmp_path: Path):
    profile = tmp_path / "suite.toml"
    profile.write_text(
        textwrap.dedent(
            """
            [suite]
            name = "example"

            [defaults.setup]
            target_kind = "gateway"
            auth_mode = "none"
            plugins_enabled = false

            [defaults.runtime]
            http_server = "gunicorn"

            [defaults.load]
            locustfile = "benchmarks/contextforge/locust/locustfile_benchmark_ab.py"
            users = 1
            spawn_rate = 1
            run_time = "10s"
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
            measure_seconds = 5
            profile_seconds = 2
            cooldown_seconds = 1

            [defaults.profiling]
            enabled = false
            py_spy = false
            tools = []

            [[scenario]]
            name = "first"
            description = "First scenario"
            scenario_type = "gateway_core"
            """
        ),
        encoding="utf-8",
    )

    resolved = resolve_suite(profile)
    scenario = resolved["scenarios"][0]
    assert scenario["runtime"]["http_server"] == "gunicorn"
    assert scenario["load"]["target_service"] == "nginx"


def test_resolve_suite_accepts_uvicorn_runtime(tmp_path: Path):
    profile = tmp_path / "suite.toml"
    profile.write_text(
        textwrap.dedent(
            """
            [suite]
            name = "example"

            [defaults.setup]
            target_kind = "gateway"
            auth_mode = "none"
            plugins_enabled = false

            [defaults.runtime]
            http_server = "uvicorn"

            [defaults.runtime.uvicorn]
            workers = 2
            loop = "uvloop"
            http = "httptools"
            backlog = 1024
            timeout_keep_alive = 5
            limit_max_requests = 1000
            log_level = "error"
            dev_mode = false

            [defaults.load]
            locustfile = "benchmarks/contextforge/locust/locustfile_benchmark_ab.py"
            users = 1
            spawn_rate = 1
            run_time = "10s"
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
            measure_seconds = 5
            profile_seconds = 2
            cooldown_seconds = 1

            [defaults.profiling]
            enabled = false
            py_spy = false
            tools = []

            [[scenario]]
            name = "first"
            description = "First scenario"
            scenario_type = "gateway_core"
            """
        ),
        encoding="utf-8",
    )

    resolved = resolve_suite(profile)
    scenario = resolved["scenarios"][0]
    assert scenario["runtime"]["http_server"] == "uvicorn"
    assert scenario["runtime"]["uvicorn"]["workers"] == 2


def test_resolve_suite_accepts_execution_reuse_stack(tmp_path: Path):
    profile = tmp_path / "suite.toml"
    profile.write_text(
        textwrap.dedent(
            """
            [suite]
            name = "example"

            [defaults.setup]
            target_kind = "gateway"
            auth_mode = "jwt"
            plugins_enabled = false

            [defaults.runtime]
            http_server = "gunicorn"

            [defaults.load]
            locustfile = "tests/loadtest/locustfile_highthroughput.py"
            users = 1
            spawn_rate = 1
            run_time = "10s"
            target_service = "nginx"

            [defaults.measurement]
            warmup_seconds = 0
            measure_seconds = 5
            profile_seconds = 0
            cooldown_seconds = 0

            [defaults.profiling]
            enabled = false
            py_spy = false
            tools = []

            [defaults.execution]
            retry_enabled = true
            max_attempts = 2
            reuse_stack = true

            [[scenario]]
            name = "first"
            description = "First scenario"
            scenario_type = "gateway_core"
            """
        ),
        encoding="utf-8",
    )

    resolved = resolve_suite(profile)
    assert resolved["scenarios"][0]["execution"]["reuse_stack"] is True


def test_resolve_suite_accepts_git_source_runtime_expectations_and_gateway_environment(tmp_path: Path):
    profile = tmp_path / "suite.toml"
    profile.write_text(
        textwrap.dedent(
            """
            [suite]
            name = "example"

            [defaults.setup]
            target_kind = "gateway"
            auth_mode = "jwt"
            plugins_enabled = false

            [defaults.runtime]
            http_server = "gunicorn"

            [defaults.gateway]
            log_level = "ERROR"

            [defaults.gateway.environment]
            EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED = "true"

            [defaults.build]
            repo_url = "https://github.com/IBM/mcp-context-forge"
            git_ref = "modular-design"
            git_commit = "abcdef1234567"

            [defaults.build.args]
            ENABLE_RUST_MCP_RMCP = "true"

            [defaults.load]
            locustfile = "tests/loadtest/locustfile_mcp_protocol.py"
            users = 10
            spawn_rate = 2
            run_time = "30s"
            target_service = "nginx"

            [defaults.measurement]
            warmup_seconds = 1
            measure_seconds = 5
            profile_seconds = 0
            cooldown_seconds = 1

            [defaults.profiling]
            enabled = false
            py_spy = false
            tools = []

            [[scenario]]
            name = "first"
            description = "First scenario"
            scenario_type = "mcp_runtime"

            [scenario.setup]
            expected_mcp_runtime = "rust"
            expected_mcp_runtime_mode = "rust-managed"
            """
        ),
        encoding="utf-8",
    )

    resolved = resolve_suite(profile)
    scenario = resolved["scenarios"][0]
    assert scenario["build"]["git_ref"] == "modular-design"
    assert scenario["build"]["repo_url"] == "https://github.com/IBM/mcp-context-forge"
    assert scenario["build"]["git_commit"] == "abcdef1234567"
    assert scenario["build"]["args"]["ENABLE_RUST_MCP_RMCP"] == "true"
    assert scenario["setup"]["expected_mcp_runtime"] == "rust"
    assert scenario["gateway"]["environment"]["EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED"] == "true"


def test_resolve_suite_rejects_unsupported_keys(tmp_path: Path):
    profile = tmp_path / "suite.toml"
    profile.write_text(
        textwrap.dedent(
            """
            [suite]
            name = "example"

            [defaults.setup]
            target_kind = "gateway"
            auth_mode = "none"
            plugins_enabled = false
            measurement_model = "steady_state"

            [defaults.runtime]
            http_server = "gunicorn"

            [defaults.load]
            locustfile = "benchmarks/contextforge/locust/locustfile_benchmark_ab.py"
            users = 1
            spawn_rate = 1
            run_time = "10s"
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
            measure_seconds = 5
            profile_seconds = 2
            cooldown_seconds = 1

            [defaults.profiling]
            enabled = false
            py_spy = false
            tools = []

            [[scenario]]
            name = "first"
            description = "First scenario"
            scenario_type = "gateway_core"
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported keys"):
        resolve_suite(profile)


def test_resolve_suite_accepts_toml_workload_endpoint_overrides(tmp_path: Path):
    profile = tmp_path / "suite.toml"
    profile.write_text(
        textwrap.dedent(
            """
            [suite]
            name = "example"

            [defaults.setup]
            target_kind = "gateway"
            auth_mode = "jwt"
            plugins_enabled = true

            [defaults.runtime]
            http_server = "granian"

            [defaults.load]
            locustfile = "benchmarks/contextforge/locust/locustfile_benchmark_ab.py"
            users = 10
            spawn_rate = 2
            run_time = "30s"
            target_service = "nginx"

            [defaults.load.workload]
            fallback_endpoint = "/health"

            [defaults.load.workload.endpoints."/health"]
            enabled = false

            [defaults.load.workload.endpoints."/mcp tools/call fast-time-get-system-time"]
            enabled = true
            weight = 11

            [defaults.measurement]
            warmup_seconds = 1
            measure_seconds = 5
            profile_seconds = 2
            cooldown_seconds = 1

            [defaults.profiling]
            enabled = false
            py_spy = false
            tools = []

            [[scenario]]
            name = "first"
            description = "First scenario"
            scenario_type = "gateway_core"
            """
        ),
        encoding="utf-8",
    )

    resolved = resolve_suite(profile)
    workload = resolved["scenarios"][0]["load"]["workload"]
    assert workload["fallback_endpoint"] == "/health"
    assert workload["endpoints"]["/mcp tools/call fast-time-get-system-time"]["weight"] == 11


def test_resolve_suite_rejects_unknown_workload_endpoint(tmp_path: Path):
    profile = tmp_path / "suite.toml"
    profile.write_text(
        textwrap.dedent(
            """
            [suite]
            name = "example"

            [defaults.setup]
            target_kind = "gateway"
            auth_mode = "jwt"
            plugins_enabled = true

            [defaults.runtime]
            http_server = "granian"

            [defaults.load]
            locustfile = "benchmarks/contextforge/locust/locustfile_benchmark_ab.py"
            users = 10
            spawn_rate = 2
            run_time = "30s"
            target_service = "nginx"

            [defaults.load.workload]
            fallback_endpoint = "/health"

            [defaults.load.workload.endpoints."/rpc missing"]
            enabled = true
            weight = 1

            [defaults.measurement]
            warmup_seconds = 1
            measure_seconds = 5
            profile_seconds = 2
            cooldown_seconds = 1

            [defaults.profiling]
            enabled = false
            py_spy = false
            tools = []

            [[scenario]]
            name = "first"
            description = "First scenario"
            scenario_type = "gateway_core"
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown endpoint"):
        resolve_suite(profile)


def test_measurement_window_summary_uses_history_window(tmp_path: Path):
    history = tmp_path / "locust_stats_history.csv"
    history.write_text(
        textwrap.dedent(
            """Timestamp,Requests/s,95%,99%,Total Request Count,Total Failure Count,Total Median Response Time,Total Average Response Time
            100,1,10,12,1,0,7,8
            101,2,20,24,3,0,8,9
            102,3,30,36,6,1,9,10
            103,4,40,48,10,1,10,11
            104,5,50,60,15,1,11,12
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    summary = _measurement_window_summary(str(tmp_path / "locust"), {"warmup_seconds": 1, "measure_seconds": 2, "cooldown_seconds": 1})
    assert summary["status"] == "ok"
    assert summary["aggregated"]["Request Count"] == 7.0
    assert summary["aggregated"]["95%"] == 40.0


def test_collect_plugin_timing_merges_process_files(tmp_path: Path):
    timing_dir = tmp_path / "plugin_timing"
    timing_dir.mkdir()
    (timing_dir / "111.json").write_text(
        json.dumps({"SecretsDetection": {"tool_pre_invoke": {"count": 2, "avg_ms": 2.0, "min_ms": 1.0, "max_ms": 3.0, "p95_ms": 3.0, "p99_ms": 3.0, "total_ms": 4.0}}}),
        encoding="utf-8",
    )
    (timing_dir / "222.json").write_text(
        json.dumps({"SecretsDetection": {"tool_pre_invoke": {"count": 3, "avg_ms": 4.0, "min_ms": 2.0, "max_ms": 6.0, "p95_ms": 6.0, "p99_ms": 6.0, "total_ms": 12.0}}}),
        encoding="utf-8",
    )

    merged = _collect_plugin_timing(tmp_path)
    hook = merged["timings"]["SecretsDetection"]["tool_pre_invoke"]
    assert merged["status"] == "ok"
    assert hook["count"] == 5
    assert hook["avg_ms"] == pytest.approx(3.2)
    assert hook["p95_ms"] == 6.0


def test_collect_system_metrics_uses_procfs_probe(monkeypatch):
    calls = []

    def fake_run_compose(compose_args, extra, env=None, check=True, timeout=None):
        calls.append(extra)
        assert timeout is None
        service = extra[2]
        command = extra[-1]
        if "ps -e -o rss=,vsz=,comm=" in command:
            if service == "nginx":
                return type("Result", (), {"returncode": 0, "stdout": "1024 4096 nginx\n512 1024 worker\n", "stderr": ""})()
            return type("Result", (), {"returncode": 0, "stdout": "2048 8192 redis-server\n", "stderr": ""})()
        if service == "nginx":
            return type("Result", (), {"returncode": 0, "stdout": "Name:\tnginx\nVmRSS:\t    4096 kB\n", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "1 2048 8192 redis-server\n", "stderr": ""})()

    monkeypatch.setattr("tests.performance.benchmark_suite._run_compose", fake_run_compose)

    payload = _collect_system_metrics(["docker", "compose", "-p", "bench", "-f", "/tmp/compose.yml"])
    assert payload["status"] == "ok"
    assert "cat /proc/1/status" in calls[0][-1]
    assert payload["services"]["nginx"]["status"] == "ok"
    assert payload["services"]["nginx"]["source"] == "procfs"
    assert payload["services"]["nginx"]["process_totals"]["rss_mb"] == 1.5
    assert payload["services"]["redis"]["source"] == "ps"


def test_scenario_memory_metrics_prefers_process_stats_then_gateway_system_metrics():
    process_stats_summary = {
        "process_stats": {"status": "ok", "snapshot": "PID %CPU %MEM RSS VSZ COMMAND\n10 1.0 2.0 20480 40960 uvicorn"},
        "system_metrics": {"status": "ok", "services": {"gateway": {"status": "ok", "source": "procfs", "snapshot": "Name:\tgateway\nVmRSS:\t9999 kB\nVmSize:\t19999 kB\n"}}},
    }
    process_memory = _scenario_memory_metrics(process_stats_summary)
    assert process_memory["status"] == "ok"
    assert process_memory["source"] == "process_stats"
    assert process_memory["rss_mb"] == 20.0

    system_summary = {
        "process_stats": {"status": "unavailable"},
        "system_metrics": {"status": "ok", "services": {"gateway": {"status": "ok", "source": "procfs", "snapshot": "Name:\tgateway\nVmRSS:\t4096 kB\nVmSize:\t8192 kB\n"}}},
    }
    system_memory = _scenario_memory_metrics(system_summary)
    assert system_memory["status"] == "ok"
    assert system_memory["source"] == "system_metrics.procfs"
    assert system_memory["rss_mb"] == 4.0


def test_scenario_memory_metrics_prefers_gateway_process_table_totals():
    summary = {
        "process_stats": {"status": "unavailable"},
        "system_metrics": {
            "status": "ok",
            "services": {
                "gateway": {
                    "status": "ok",
                    "source": "procfs",
                    "snapshot": "Name:\tgateway\nVmRSS:\t4096 kB\nVmSize:\t8192 kB\n",
                    "process_totals": {"rss_mb": 96.5, "vms_mb": 512.0, "process_count": 13.0},
                }
            },
        },
    }

    memory = _scenario_memory_metrics(summary)
    assert memory["status"] == "ok"
    assert memory["source"] == "system_metrics.process_table"
    assert memory["rss_mb"] == 96.5
    assert memory["process_count"] == 13.0


def test_compare_scenarios_uses_concrete_plugin_metrics():
    left = {
        "scenario": "left",
        "endpoint_metrics": {"status": "ok", "aggregated": {"Request Count": "10", "Requests/s": "5", "95%": "10", "99%": "15", "Failure Count": "0"}},
        "plugin_timing": {"timings": {"SecretsDetection": {"tool_pre_invoke": {"avg_ms": 2.0, "p95_ms": 3.0, "total_ms": 20.0, "count": 10}}}},
        "runtime": {"http_server": "gunicorn"},
        "load": {"locustfile": "benchmarks/contextforge/locust/locustfile_benchmark_ab.py", "target_service": "nginx"},
        "requests": {"enabled_groups": ["tools"]},
        "measurement": {"measure_seconds": 10},
        "setup": {"auth_mode": "jwt"},
        "process_stats": {"status": "ok", "snapshot": "PID %CPU %MEM RSS VSZ COMMAND\n10 1.0 2.0 20480 40960 gunicorn"},
    }
    right = {
        "scenario": "right",
        "endpoint_metrics": {"status": "ok", "aggregated": {"Request Count": "20", "Requests/s": "8", "95%": "7", "99%": "12", "Failure Count": "1"}},
        "plugin_timing": {"timings": {"SecretsDetection": {"tool_pre_invoke": {"avg_ms": 1.0, "p95_ms": 1.5, "total_ms": 10.0, "count": 10}}}},
        "runtime": {"http_server": "granian"},
        "load": {"locustfile": "benchmarks/contextforge/locust/locustfile_benchmark_ab.py", "target_service": "nginx"},
        "requests": {"enabled_groups": ["tools"]},
        "measurement": {"measure_seconds": 10},
        "setup": {"auth_mode": "jwt"},
        "process_stats": {"status": "ok", "snapshot": "PID %CPU %MEM RSS VSZ COMMAND\n11 1.0 2.0 10240 30720 granian"},
    }

    comparison = compare_scenarios(left, right)
    hook = comparison["plugin_deltas"]["SecretsDetection"]["tool_pre_invoke"]
    assert comparison["metrics"]["status"] == "ok"
    assert hook["avg_ms_delta"] == -1.0
    assert "runtime.http_server" in comparison["changed_dimensions"]
    assert comparison["metric_details"]["rss_mb"]["winner"] == "right"
    assert comparison["metric_details"]["rss_mb"]["delta"] == -10.0


def test_compare_scenarios_marks_validation_metrics_unavailable():
    comparison = compare_scenarios(
        {"scenario": "left", "endpoint_metrics": {"status": "omitted"}, "plugin_timing": {}, "runtime": {}, "load": {}, "requests": {}, "measurement": {}, "setup": {}},
        {"scenario": "right", "endpoint_metrics": {"status": "omitted"}, "plugin_timing": {}, "runtime": {}, "load": {}, "requests": {}, "measurement": {}, "setup": {}},
    )
    assert comparison["metrics"]["status"] == "unavailable"


def test_regenerate_reports_builds_run_summary(tmp_path: Path):
    run_dir = tmp_path / "run"
    left_dir = run_dir / "scenarios" / "left"
    right_dir = run_dir / "scenarios" / "right"
    left_dir.mkdir(parents=True)
    right_dir.mkdir(parents=True)

    for scenario_name, scenario_dir in (("left", left_dir), ("right", right_dir)):
        payload = {
            "scenario": scenario_name,
            "status": "ok",
            "runtime": {"http_server": "gunicorn"},
            "load": {"locustfile": "benchmarks/contextforge/locust/locustfile_benchmark_ab.py", "target_service": "nginx"},
            "setup": {"auth_mode": "jwt"},
            "measurement": {"measure_seconds": 10},
            "requests": {"enabled_groups": ["tools"]},
            "endpoint_metrics": {"status": "ok", "aggregated": {"Request Count": "10", "Requests/s": "5", "95%": "10", "Failure Count": "0"}},
            "plugin_timing": {"status": "unavailable"},
            "pyspy": {"status": "unavailable"},
            "memray": {"status": "unavailable"},
            "process_stats": {"status": "ok", "snapshot": "PID %CPU %MEM RSS VSZ COMMAND\n10 1.0 2.0 20480 40960 gunicorn"},
            "database_metrics": {"status": "omitted"},
            "system_metrics": {"status": "omitted"},
            "flamegraph_run": {"status": "unavailable"},
        }
        (scenario_dir / "summary.json").write_text(json.dumps(payload), encoding="utf-8")

    regenerate_reports(run_dir)
    assert (run_dir / "comparison_matrix.json").exists()
    assert (run_dir / "run_summary.json").exists()
    report = json.loads((run_dir / "scenario_comparison_report.json").read_text(encoding="utf-8"))
    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    report_markdown = (run_dir / "scenario_comparison_report.md").read_text(encoding="utf-8")
    report_html = (run_dir / "scenario_comparison_report.html").read_text(encoding="utf-8")
    assert report["scenarios"][0]["core_metrics"]["rss_mb"] == 20.0
    assert run_summary["scenarios"][0]["gateway_rss_mb"] == 20.0
    assert "| Scenario | Status | Runtime | RPS | p95 | Gateway RSS | Gateway VMS | Failures | Insights | Error |" in report_markdown
    assert "| Left | Right | RPS Delta | p95 Delta | Gateway RSS Delta | Fair | Notes |" in report_markdown
    assert "| `left` | `ok` | `gunicorn` | 5.00 | 10.00 ms | 20.00 MB | 40.00 MB | 0.00 |" in report_markdown
    assert "| `left` | `right` | 0.00 | 0.00 ms | 0.00 MB | yes | none |" in report_markdown
    assert "Gateway RSS delta" in report_html
    assert "color-scheme: dark" in report_html
    assert "--bg: #0f172a;" in report_html


def test_scenario_env_uses_target_service_and_request_selection():
    scenario = {
        "load": {"target_service": "gateway", "request_count": 25, "seed": 123, "env": {"LOADTEST_STRICT_VALIDATION": "true"}},
        "requests": {
            "enabled_groups": ["tools"],
            "disabled_groups": [],
            "enabled_endpoints": ["/mcp tools/call fast-time-get-system-time"],
            "disabled_endpoints": [],
            "enabled_tags": ["plugin-heavy"],
            "disabled_tags": [],
            "include_admin_endpoints": False,
            "include_mcp_endpoints": True,
            "include_resource_endpoints": False,
            "include_prompt_endpoints": False,
            "include_tool_endpoints": True,
        },
        "profiling": {"required": True},
    }

    env = _scenario_env(scenario)
    assert env["LOADTEST_HOST"] == "http://gateway:4444"
    assert env["BENCH_INCLUDE_MCP_ENDPOINTS"] == "true"
    assert env["LOADTEST_STRICT_VALIDATION"] == "true"

    args = _compose_env_args(env)
    assert "LOADTEST_HOST=http://gateway:4444" in args


def test_scenario_env_serializes_workload_config():
    scenario = {
        "load": {
            "target_service": "nginx",
            "workload": {
                "fallback_endpoint": "/health",
                "endpoints": {
                    "/health": {"enabled": False},
                    "/mcp tools/call fast-time-get-system-time": {"enabled": True, "weight": 9},
                },
            },
        },
        "profiling": {"required": False},
    }

    env = _scenario_env(scenario)
    workload = json.loads(env["BENCH_WORKLOAD"])
    assert env["LOADTEST_HOST"] == "http://nginx:80"
    assert workload["endpoints"]["/mcp tools/call fast-time-get-system-time"]["weight"] == 9
    assert "BENCH_ENABLED_GROUPS" not in env


def test_write_compose_override_omits_disabled_granian_lifetime_knobs(tmp_path: Path):
    scenario = {
        "name": "granian-test",
        "setup": {"auth_mode": "jwt", "plugins_enabled": False},
        "gateway": {},
        "runtime": {
            "http_server": "granian",
            "transport_type": "streamablehttp",
            "granian": {
                "workers": 4,
                "workers_lifetime": 0,
                "workers_max_rss": 0,
                "runtime_mode": "mt",
            },
        },
    }

    compose_path = _write_compose_override(
        scenario,
        tmp_path,
        "mcpgateway/mcpgateway:latest",
        "mcpgateway/nginx-cache:test",
        "mcpgateway/a2a-echo-agent:test",
        REPO_ROOT,
    )
    compose_text = compose_path.read_text(encoding="utf-8")
    assert "GRANIAN_WORKERS_LIFETIME" not in compose_text
    assert "GRANIAN_WORKERS_MAX_RSS" not in compose_text
    assert "fast_time_server" in compose_text
    assert "register_fast_time" in compose_text


def test_write_compose_override_includes_a2a_services_for_a2a_workload(tmp_path: Path):
    scenario = {
        "name": "a2a-compare",
        "setup": {"auth_mode": "jwt", "plugins_enabled": False},
        "gateway": {},
        "runtime": {"http_server": "gunicorn", "transport_type": "streamablehttp", "gunicorn": {"workers": 2}},
        "load": {
            "target_service": "nginx",
            "workload": {
                "fallback_endpoint": "/a2a/a2a-echo-agent/invoke",
                "endpoints": {
                    "/a2a": {"enabled": False},
                    "/a2a/a2a-echo-agent/invoke": {"enabled": True, "weight": 1},
                },
            },
        },
    }

    compose_path = _write_compose_override(
        scenario,
        tmp_path,
        "mcpgateway/mcpgateway:latest",
        "mcpgateway/nginx-cache:test",
        "mcpgateway/a2a-echo-agent:test",
        REPO_ROOT,
    )
    compose_text = compose_path.read_text(encoding="utf-8")
    assert "a2a_echo_agent" in compose_text
    assert "register_a2a_echo" in compose_text
    assert "fast_time_server" not in compose_text


def test_write_compose_override_merges_gateway_environment(tmp_path: Path):
    scenario = {
        "name": "runtime-probe",
        "setup": {"auth_mode": "jwt", "plugins_enabled": False},
        "gateway": {"log_level": "ERROR", "environment": {"EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED": "true", "MCP_RUST_LOG": "warn"}},
        "runtime": {"http_server": "gunicorn", "transport_type": "streamablehttp", "gunicorn": {"workers": 2}},
    }

    compose_path = _write_compose_override(
        scenario,
        tmp_path,
        "mcpgateway/mcpgateway:latest",
        "mcpgateway/nginx-cache:test",
        "mcpgateway/a2a-echo-agent:test",
        REPO_ROOT,
    )
    compose_text = compose_path.read_text(encoding="utf-8")
    assert "- EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true" in compose_text
    assert "- MCP_RUST_LOG=warn" in compose_text


def test_write_compose_override_resolves_compose_variable_expressions(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED", raising=False)
    scenario = {
        "name": "compose-env-preserve",
        "setup": {"auth_mode": "jwt", "plugins_enabled": False},
        "gateway": {"environment": {"RUST_MCP_MODE": "edge"}},
        "runtime": {"http_server": "gunicorn", "transport_type": "streamablehttp", "gunicorn": {"workers": 2}},
    }

    compose_path = _write_compose_override(
        scenario,
        tmp_path,
        "mcpgateway/mcpgateway:latest",
        "mcpgateway/nginx-cache:test",
        "mcpgateway/a2a-echo-agent:test",
        REPO_ROOT,
    )
    compose_text = compose_path.read_text(encoding="utf-8")
    assert "- DATABASE_URL=postgresql+psycopg://postgres:mysecretpassword@pgbouncer:6432/mcp" in compose_text
    assert "- RUST_MCP_MODE=edge" in compose_text
    assert "EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED=" not in compose_text


def test_ensure_benchmark_image_only_builds_missing_when_needed(monkeypatch):
    calls = []

    def fake_run(args, env=None, check=True, timeout=None):
        calls.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("tests.performance.benchmark_suite._run_command", fake_run)
    monkeypatch.setattr(
        "tests.performance.benchmark_suite._ensure_scenario_source",
        lambda scenario: type(
            "ScenarioSource",
            (),
            {"repo_root": REPO_ROOT, "commit": "0123456789ab", "ref_label": "workspace", "content_fingerprint": "0123456789ab"},
        )(),
    )
    image = _ensure_benchmark_image(
        ContainerRuntime(engine="docker", compose_cmd=("docker", "compose")),
        {"build": {"rebuild_policy": "missing", "container_file": "Containerfile.lite"}},
    )
    assert image == "mcpgateway/mcpgateway:latest"
    assert calls == [["docker", "image", "inspect", "mcpgateway/mcpgateway:latest"]]


def test_ensure_benchmark_image_includes_custom_build_args(monkeypatch):
    calls = []

    def fake_run(args, env=None, check=True, timeout=None):
        calls.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("tests.performance.benchmark_suite._run_command", fake_run)
    monkeypatch.setattr(
        "tests.performance.benchmark_suite._ensure_scenario_source",
        lambda scenario: type(
            "ScenarioSource",
            (),
            {"repo_root": REPO_ROOT, "commit": "0123456789ab", "ref_label": "workspace", "content_fingerprint": "0123456789ab"},
        )(),
    )
    monkeypatch.setattr("tests.performance.benchmark_suite._prepare_benchmark_build_context", lambda source: REPO_ROOT)
    image = _ensure_benchmark_image(
        ContainerRuntime(engine="docker", compose_cmd=("docker", "compose")),
        {
            "name": "rust-mcp-pr",
            "build": {
                "rebuild_policy": "always",
                "container_file": "Containerfile.lite",
                "args": {"ENABLE_RUST_MCP_RMCP": "true"},
            },
        },
    )
    assert image == "mcpgateway/mcpgateway:latest"
    build_cmd = calls[-1]
    assert "--build-arg" in build_cmd
    assert "ENABLE_RUST_MCP_RMCP=true" in build_cmd


def test_ensure_benchmark_image_falls_back_to_repo_container_file(monkeypatch):
    calls = []

    def fake_run(args, env=None, check=True, timeout=None):
        calls.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("tests.performance.benchmark_suite._run_command", fake_run)
    monkeypatch.setattr(
        "tests.performance.benchmark_suite._ensure_scenario_source",
        lambda scenario: type(
            "ScenarioSource",
            (),
            {"repo_root": REPO_ROOT, "commit": "0123456789ab", "ref_label": "workspace", "content_fingerprint": "0123456789ab"},
        )(),
    )
    monkeypatch.setattr("tests.performance.benchmark_suite._prepare_benchmark_build_context", lambda source: REPO_ROOT / "reports" / "benchmarks" / "_runtime_staging" / "missing-context")

    image = _ensure_benchmark_image(
        ContainerRuntime(engine="docker", compose_cmd=("docker", "compose")),
        {
            "name": "a2a-bench",
            "build": {
                "rebuild_policy": "always",
                "container_file": "benchmarks/contextforge/Containerfile",
            },
        },
    )

    assert image == "mcpgateway/mcpgateway:latest"
    assert str(REPO_ROOT / "benchmarks" / "contextforge" / "Containerfile") in calls[-1]


def test_scenario_image_name_suffixes_git_sourced_images():
    scenario = {"build": {"image_name": "mcpgateway/mcpgateway", "image_tag": "benchmark-suite"}}
    scenario["_scenario_source"] = type(
        "ScenarioSource",
        (),
        {"repo_root": REPO_ROOT, "commit": "abcdef1234567890", "ref_label": "origin/modular-design", "content_fingerprint": "abcdef123456"},
    )()
    assert _scenario_image_name(scenario) == "mcpgateway/mcpgateway:benchmark-suite-abcdef123456"


def test_ensure_scenario_source_clones_repo_url_and_checks_out_requested_commit(monkeypatch, tmp_path: Path):
    calls = []
    commit = "f64721741a23cc17d0867943b70a67472203d18b"
    checkout_root = tmp_path / "_runtime_staging"
    checkout_dir = checkout_root / "source_checkouts" / "repo-cache"

    def fake_run(args, env=None, check=True, timeout=None):
        calls.append(list(args))
        command = list(args)
        if command[:2] == ["git", "clone"]:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if command[:4] == ["git", "-C", str(checkout_dir), "remote"]:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if command[:5] == ["git", "-C", str(checkout_dir), "fetch", "--tags"]:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if command[:5] == ["git", "-C", str(checkout_dir), "fetch", "origin"]:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if command[:5] == ["git", "-C", str(checkout_dir), "rev-parse", "--verify"]:
            return type("Result", (), {"returncode": 0, "stdout": f"{command[-1]}\n", "stderr": ""})()
        if command[:4] == ["git", "-C", str(checkout_dir), "rev-parse"] and command[-1] == commit:
            return type("Result", (), {"returncode": 0, "stdout": f"{commit}\n", "stderr": ""})()
        if command[:4] == ["git", "-C", str(checkout_dir), "rev-parse"] and command[-1] == "HEAD":
            return type("Result", (), {"returncode": 0, "stdout": "old-head\n", "stderr": ""})()
        if command[:5] == ["git", "-C", str(checkout_dir), "checkout", "--detach"]:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        raise AssertionError(command)

    monkeypatch.setattr("tests.performance.benchmark_suite._run_command", fake_run)
    monkeypatch.setattr("tests.performance.benchmark_suite.RUNTIME_STAGING_ROOT", checkout_root)
    monkeypatch.setattr("tests.performance.benchmark_suite._repo_cache_key", lambda repo_url, git_ref, git_commit: "repo-cache")

    scenario = {
        "name": "pr-compare",
        "build": {
            "repo_url": "https://github.com/IBM/mcp-context-forge",
            "git_ref": "modular-design",
            "git_commit": commit,
        },
    }

    source = _ensure_scenario_source(scenario)
    assert source.commit == commit
    assert source.repo_url == "https://github.com/IBM/mcp-context-forge"
    assert any(command[:2] == ["git", "clone"] for command in calls)
    assert any(command[-2:] == ["origin", "modular-design"] for command in calls if len(command) >= 2)
    assert any(command[:4] == ["git", "-C", str(checkout_dir), "checkout"] for command in calls)


def test_prepare_benchmark_build_context_excludes_ignored_untracked_dirs(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "bench@example.com"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Benchmark"], cwd=repo_root, check=True, capture_output=True)
    (repo_root / ".gitignore").write_text("target/\n", encoding="utf-8")
    (repo_root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "tracked.txt"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, check=True, capture_output=True)
    (repo_root / "notes.txt").write_text("keep me\n", encoding="utf-8")
    ignored_dir = repo_root / "plugins_rust" / "pii_filter" / "target"
    ignored_dir.mkdir(parents=True)
    (ignored_dir / "artifact").write_text("skip me\n", encoding="utf-8")

    source = type("ScenarioSource", (), {"repo_root": repo_root, "commit": "abcdef1234567890", "ref_label": "workspace", "content_fingerprint": "ctx-fixture"})()
    context_root = _prepare_benchmark_build_context(source)

    assert (context_root / "tracked.txt").exists()
    assert (context_root / "notes.txt").exists()
    assert not (context_root / "plugins_rust" / "pii_filter" / "target" / "artifact").exists()


def test_ensure_locust_image_pulls_when_missing(monkeypatch):
    calls = []

    def fake_run(args, env=None, check=True, timeout=None):
        calls.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "missing"})()
        if args[:2] == ["docker", "pull"]:
            return type("Result", (), {"returncode": 0, "stdout": "pulled", "stderr": ""})()
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr("tests.performance.benchmark_suite._run_command", fake_run)

    image = _ensure_locust_image(ContainerRuntime(engine="docker", compose_cmd=("docker", "compose")))
    assert image == "docker.io/locustio/locust:latest"
    assert calls == [
        ["docker", "image", "inspect", "docker.io/locustio/locust:latest"],
        ["docker", "pull", "docker.io/locustio/locust:latest"],
    ]


def test_locust_run_command_skips_html_when_disabled(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("tests.performance.benchmark_suite._ensure_locust_image", lambda runtime: "docker.io/locustio/locust:latest")
    monkeypatch.setattr("tests.performance.benchmark_suite._benchmark_token", lambda runtime, compose_args: "token")

    scenario = {
        "name": "steady",
        "load": {
            "locustfile": "tests/loadtest/locustfile_highthroughput.py",
            "host": "http://nginx:80",
            "users": 1,
            "spawn_rate": 1,
            "run_time": "5s",
            "headless": True,
            "only_summary": True,
            "html_report": False,
            "target_service": "nginx",
        },
        "measurement": {},
        "profiling": {},
        "runtime": {"http_server": "gunicorn"},
        "setup": {"auth_mode": "jwt"},
    }

    command = _locust_run_command(ContainerRuntime(engine="docker", compose_cmd=("docker", "compose")), ["docker", "compose"], "bench-test", scenario, tmp_path, "locust_metrics")
    assert not any(part.startswith("--html=") for part in command)
    assert "--exit-code-on-error=0" in command


def test_verify_runtime_expectations_reports_mismatched_runtime(monkeypatch):
    monkeypatch.setattr("tests.performance.benchmark_suite._benchmark_token", lambda runtime, compose_args: "token")
    monkeypatch.setattr(
        "tests.performance.benchmark_suite._mcp_runtime_probe",
        lambda compose_args, token: (
            True,
            {
                "health_headers": {"x-contextforge-mcp-runtime-mode": "python-rust-built-disabled"},
                "health_body": {"mcp_runtime": {"mode": "python-rust-built-disabled"}},
                "mcp_headers": {"x-contextforge-mcp-runtime": "python"},
            },
        ),
    )

    ok, detail = _verify_runtime_expectations(
        ContainerRuntime(engine="docker", compose_cmd=("docker", "compose")),
        ["docker", "compose"],
        {"setup": {"expected_mcp_runtime": "rust", "expected_mcp_runtime_mode": "rust-managed"}},
    )

    assert ok is False
    assert "expected MCP runtime header 'rust', got 'python'" in detail


def test_compose_base_args_does_not_force_testing_profile(tmp_path: Path):
    args = _compose_base_args(ContainerRuntime(engine="podman", compose_cmd=("podman", "compose")), "bench-test", tmp_path / "override.yml")
    assert args == ["podman", "compose", "-p", "bench-test", "-f", str(tmp_path / "override.yml")]


def test_main_uses_requested_scenario(monkeypatch, tmp_path: Path):
    observed: dict[str, object] = {}

    def fake_execute_suite(profile, validate_only=False, smoke=False, output_root=None, check_runtime_only=False, run_all=False):
        observed["scenario"] = profile
        observed["validate_only"] = validate_only
        observed["smoke"] = smoke
        observed["output_root"] = output_root
        observed["check_runtime_only"] = check_runtime_only
        observed["run_all"] = run_all
        return tmp_path

    monkeypatch.setattr("benchmarks.contextforge.runner.execute_suite", fake_execute_suite)

    assert main(["--scenario", "modular-design-300", "--validate"]) == 0
    assert observed["scenario"] == "modular-design-300"
    assert observed["validate_only"] is True
    assert observed["run_all"] is False


def test_main_can_run_all_scenarios(monkeypatch, tmp_path: Path):
    observed: dict[str, object] = {}

    def fake_execute_suite(profile, validate_only=False, smoke=False, output_root=None, check_runtime_only=False, run_all=False):
        observed["scenario"] = profile
        observed["run_all"] = run_all
        return tmp_path

    monkeypatch.setattr("benchmarks.contextforge.runner.execute_suite", fake_execute_suite)

    assert main(["--all", "--validate"]) == 0
    assert observed["scenario"] == "all-scenarios"
    assert observed["run_all"] is True


def test_list_scenarios_reads_self_contained_bundle():
    scenarios = list_scenarios()
    assert "a2a-invoke-300" in scenarios
    assert "modular-design-300" in scenarios


def test_resolve_suite_rejects_legacy_git_remote(tmp_path: Path):
    profile = tmp_path / "legacy.toml"
    profile.write_text(
        textwrap.dedent(
            """
            [suite]
            name = "legacy"

            [defaults.setup]
            target_kind = "gateway"
            auth_mode = "jwt"
            plugins_enabled = false

            [defaults.runtime]
            http_server = "gunicorn"

            [defaults.load]
            locustfile = "benchmarks/contextforge/locust/locustfile_benchmark_ab.py"
            users = 1
            spawn_rate = 1
            run_time = "10s"
            target_service = "nginx"

            [defaults.measurement]
            warmup_seconds = 0
            measure_seconds = 5
            profile_seconds = 0
            cooldown_seconds = 0

            [defaults.profiling]
            enabled = false
            py_spy = false
            tools = []

            [[scenario]]
            name = "legacy-source"
            description = "Uses old source schema"
            scenario_type = "gateway_core"

            [scenario.build]
            git_remote = "origin"
            git_branch = "main"
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported keys: git_branch, git_remote"):
        resolve_suite(profile)


def test_profiling_variant_disables_stack_reuse():
    scenario = {
        "execution": {"reuse_stack": True},
        "runtime": {"http_server": "gunicorn", "gunicorn": {"workers": 12}},
    }

    profiling = _profiling_variant(scenario)
    assert profiling["execution"]["reuse_stack"] is False
    assert profiling["runtime"]["gunicorn"]["workers"] == 1


def test_ensure_podman_ready_switches_to_running_machine(monkeypatch):
    state = {"default_connection": "stale"}

    def fake_run(args, env=None, check=True, timeout=None):
        if args == ["podman", "info"]:
            if state["default_connection"] == "benchvm2":
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            return type("Result", (), {"returncode": 125, "stdout": "", "stderr": "connection refused"})()
        if args == ["podman", "machine", "list", "--format", "json"]:
            payload = json.dumps([{"Name": "benchvm2", "Default": False, "Running": True}, {"Name": "stale", "Default": True, "Running": False}])
            return type("Result", (), {"returncode": 0, "stdout": payload, "stderr": ""})()
        if args == ["podman", "system", "connection", "list", "--format", "json"]:
            payload = json.dumps([{"Name": "benchvm2", "Default": False}, {"Name": "stale", "Default": True}])
            return type("Result", (), {"returncode": 0, "stdout": payload, "stderr": ""})()
        if args == ["podman", "system", "connection", "default", "benchvm2"]:
            state["default_connection"] = "benchvm2"
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr("tests.performance.benchmark_suite._run_command", fake_run)
    monkeypatch.setattr("tests.performance.benchmark_suite.shutil.which", lambda cmd: "/opt/homebrew/bin/podman" if cmd == "podman" else None)

    assert _ensure_podman_ready() is True


def test_ensure_podman_ready_requires_successful_info_after_switch(monkeypatch):
    def fake_run(args, env=None, check=True, timeout=None):
        if args == ["podman", "info"]:
            return type("Result", (), {"returncode": 125, "stdout": "", "stderr": "not ready"})()
        if args == ["podman", "machine", "list", "--format", "json"]:
            return type("Result", (), {"returncode": 0, "stdout": '[{"Name":"benchvm","Default":true,"Running":true}]', "stderr": ""})()
        if args == ["podman", "system", "connection", "list", "--format", "json"]:
            return type("Result", (), {"returncode": 0, "stdout": '[{"Name":"benchvm","Default":true}]', "stderr": ""})()
        if args == ["podman", "system", "connection", "default", "benchvm"]:
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr("tests.performance.benchmark_suite._run_command", fake_run)
    monkeypatch.setattr("tests.performance.benchmark_suite.shutil.which", lambda cmd: "/opt/homebrew/bin/podman" if cmd == "podman" else None)

    assert _ensure_podman_ready() is False


def test_service_container_id_uses_podman_labels_for_podman_compose(monkeypatch):
    def fake_run(args, env=None, check=True, timeout=None):
        if args[:2] == ["podman-compose", "-p"] or args[:2] == ["podman", "compose"] or args[:2] == ["docker", "compose"]:
            return type("Result", (), {"returncode": 0, "stdout": "abc123\n", "stderr": ""})()
        assert args[:4] == ["podman", "ps", "-a", "--filter"]
        return type("Result", (), {"returncode": 0, "stdout": "abc123\n", "stderr": ""})()

    monkeypatch.setattr("tests.performance.benchmark_suite._run_command", fake_run)
    monkeypatch.setattr("tests.performance.benchmark_suite.shutil.which", lambda binary: "/usr/bin/podman" if binary == "podman" else None)

    container_id = _service_container_id(["podman-compose", "-p", "bench-test", "-f", "/tmp/compose.yml"], "postgres")
    assert container_id == "abc123"

    container_id = _service_container_id(["podman", "compose", "-p", "bench-test", "-f", "/tmp/compose.yml"], "postgres")
    assert container_id == "abc123"

    container_id = _service_container_id(["docker", "compose", "-p", "bench-test", "-f", "/tmp/compose.yml"], "postgres")
    assert container_id == "abc123"


def test_service_container_id_falls_back_to_podman_labels_for_docker_compose(monkeypatch):
    calls = []

    def fake_run(args, env=None, check=True, timeout=None):
        calls.append(args)
        if args[:2] == ["docker", "compose"]:
            return type("Result", (), {"returncode": 2, "stdout": "", "stderr": "podman-compose: error: unrecognized arguments: postgres"})()
        assert args[:4] == ["podman", "ps", "-a", "--filter"]
        return type("Result", (), {"returncode": 0, "stdout": "abc123\n", "stderr": ""})()

    monkeypatch.setattr("tests.performance.benchmark_suite._run_command", fake_run)
    monkeypatch.setattr("tests.performance.benchmark_suite.shutil.which", lambda binary: "/usr/bin/podman" if binary == "podman" else None)

    container_id = _service_container_id(["docker", "compose", "-p", "bench-test", "-f", "/tmp/compose.yml"], "postgres")

    assert container_id == "abc123"
    assert calls[0] == ["docker", "compose", "-p", "bench-test", "-f", "/tmp/compose.yml", "ps", "-q", "postgres"]
    assert calls[1][:4] == ["podman", "ps", "-a", "--filter"]


def test_benchmark_token_uses_gateway_container_output(monkeypatch):
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1pbiJ9.signature"
    observed_command = {}

    def fake_run_compose(compose_args, extra, env=None, check=True, timeout=None):
        assert extra[:4] == ["exec", "-T", "gateway", "sh"]
        assert timeout == 20
        observed_command["value"] = extra[-1]
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": f'>>>> Executing external compose provider "/opt/homebrew/bin/podman-compose". <<<<\n{token}\n',
                "stderr": "",
            },
        )()

    monkeypatch.setattr("tests.performance.benchmark_suite._run_compose", fake_run_compose)

    resolved = _benchmark_token(ContainerRuntime(engine="docker", compose_cmd=("docker", "compose")), ["docker", "compose", "-p", "bench-test"])
    assert resolved == token
    assert "--admin" in observed_command["value"]
    assert "--full-name 'Benchmark Admin'" in observed_command["value"]


def test_compose_probe_detail_suppresses_podman_compose_noise():
    result = type(
        "Result",
        (),
        {
            "stdout": "",
            "stderr": 'Error: executing /opt/homebrew/bin/podman-compose -p bench-test exec -T gateway sh -lc "..."',
        },
    )()

    assert _compose_probe_detail(result, "gateway health probe still failing") == "gateway health probe still failing"


def test_compose_candidates_prefer_docker_shim_for_podman(monkeypatch):
    monkeypatch.setattr("tests.performance.benchmark_suite._binary_is_podman_shim", lambda binary: binary == "docker")

    assert _compose_candidates("podman") == (("docker", "compose"), ("podman", "compose"), ("podman-compose",))


def test_run_command_preserves_explicit_warning_override(monkeypatch):
    observed = {}

    def fake_run(args, cwd=None, env=None, capture_output=None, text=None, check=None, timeout=None):
        observed["env"] = env
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("tests.performance.benchmark_suite.subprocess.run", fake_run)

    _run_command(["docker", "compose", "version"], env={"PODMAN_COMPOSE_WARNING_LOGS": "true"}, check=False, timeout=10)

    assert observed["env"]["PODMAN_COMPOSE_WARNING_LOGS"] == "true"
    assert "PODMAN_COMPOSE_PROVIDER_WARNING" not in observed["env"]


def test_benchmark_registration_probe_uses_virtual_server_associations(monkeypatch):
    payload = {
        "ready": True,
        "server_found": True,
        "associated_tools": ["fast-time-get-system-time", "fast-time-convert-time"],
        "associated_resources_count": 4,
        "associated_prompts_count": 3,
    }

    def fake_run_compose(compose_args, extra, env=None, check=True, timeout=None):
        assert extra[:4] == ["exec", "-T", "gateway", "sh"]
        assert "/servers" in extra[-1]
        assert "/tools" not in extra[-1]
        assert timeout == 10
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr("tests.performance.benchmark_suite._run_compose", fake_run_compose)

    ready, detail = _benchmark_registration_probe(["docker", "compose", "-p", "bench-test"], "token")
    assert ready is True
    assert '"server_found": true' in detail


def test_a2a_registration_probe_detects_registered_echo_agent(monkeypatch):
    payload = {"ready": True, "agent_found": True, "agent_id": "a2a-1"}

    def fake_run_compose(compose_args, extra, env=None, check=True, timeout=None):
        assert extra[:4] == ["exec", "-T", "gateway", "sh"]
        assert "/a2a" in extra[-1]
        assert timeout == 10
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr("tests.performance.benchmark_suite._run_compose", fake_run_compose)

    ready, detail = _a2a_registration_probe(["docker", "compose", "-p", "bench-test"], "token")
    assert ready is True
    assert '"agent_found": true' in detail


def test_verify_a2a_runtime_expectations_reports_mismatched_runtime(monkeypatch):
    monkeypatch.setattr("tests.performance.benchmark_suite._a2a_runtime_probe", lambda compose_args: (True, {"runtime": "python"}))

    ok, detail = _verify_a2a_runtime_expectations(["docker", "compose"], {"setup": {"expected_a2a_runtime": "rust"}})

    assert ok is False
    assert "expected A2A runtime 'rust', got 'python'" in detail


def test_scenario_fixture_detection_distinguishes_a2a_and_mcp_workloads():
    a2a_scenario = {
        "load": {
            "workload": {
                "fallback_endpoint": "/a2a/a2a-echo-agent/invoke",
                "endpoints": {
                    "/a2a": {"enabled": False},
                    "/a2a/a2a-echo-agent/invoke": {"enabled": True, "weight": 1},
                },
            }
        }
    }
    mcp_scenario = {
        "load": {
            "workload": {
                "fallback_endpoint": "/mcp tools/list",
                "endpoints": {
                    "/mcp tools/list": {"enabled": True, "weight": 1},
                },
            }
        }
    }

    assert _scenario_uses_a2a_fixture(a2a_scenario) is True
    assert _scenario_uses_fast_time_fixture(a2a_scenario) is False
    assert _scenario_uses_fast_time_fixture(mcp_scenario) is True
    assert _scenario_uses_a2a_fixture(mcp_scenario) is False


def test_is_mountable_runtime_path_matches_user_space():
    assert _is_mountable_runtime_path(Path("/Users/luca/example")) is True
    assert _is_mountable_runtime_path(Path("/tmp/example")) is False
