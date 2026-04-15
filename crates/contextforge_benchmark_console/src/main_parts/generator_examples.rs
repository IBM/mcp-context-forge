pub(crate) fn generator_visibility_note(key: &str) -> &'static str {
    match key {
        "expected_mcp_runtime_mode" => {
            "Visible only after expected_mcp_runtime is set, because runtime mode only matters when you are asserting an MCP runtime."
        }
        "gunicorn_workers"
        | "gunicorn_timeout"
        | "gunicorn_graceful_timeout"
        | "gunicorn_keep_alive"
        | "gunicorn_max_requests"
        | "gunicorn_max_requests_jitter"
        | "gunicorn_backlog"
        | "gunicorn_preload_app"
        | "gunicorn_dev_mode" => "Visible only when http_server is gunicorn.",
        "granian_workers"
        | "granian_runtime_mode"
        | "granian_runtime_threads"
        | "granian_blocking_threads"
        | "granian_http"
        | "granian_loop"
        | "granian_task_impl"
        | "granian_http1_pipeline_flush"
        | "granian_http1_buffer_size"
        | "granian_backlog"
        | "granian_backpressure"
        | "granian_respawn_failed"
        | "granian_workers_lifetime"
        | "granian_workers_max_rss"
        | "granian_dev_mode"
        | "granian_log_level" => "Visible only when http_server is granian.",
        "uvicorn_workers"
        | "uvicorn_loop"
        | "uvicorn_http"
        | "uvicorn_backlog"
        | "uvicorn_timeout_keep_alive"
        | "uvicorn_limit_max_requests"
        | "uvicorn_log_level"
        | "uvicorn_dev_mode" => "Visible only when http_server is uvicorn.",
        "profiling_tools" | "profiling_duration_seconds" | "profiling_required" => {
            "Visible only when profiling_enabled is true."
        }
        "defaults_plugins_snippet" | "scenario_plugins_snippet" => {
            "Visible only when plugins_enabled is true."
        }
        "workload_endpoints" => {
            "Visible once the workload area is in use. Keep it empty if you just want the preset selection and fallback endpoint."
        }
        _ => "Always visible for this generator.",
    }
}

pub(crate) fn generator_example(key: &str) -> &'static str {
    match key {
        "file_stem" => "a2a-invoke-300",
        "template_kind" => "a2a",
        "suite_name" => "contextforge-a2a-compare",
        "suite_description" => "Compare Rust A2A invoke throughput",
        "output_root" => "reports/benchmarks",
        "continue_on_failure" => "false",
        "save_intermediate_artifacts" => "true",
        "flamegraph_enabled" => "false",
        "baseline_run" => "reports/benchmarks/prior-run/run_summary.json",
        "baseline_rps_drop_pct" => "5",
        "baseline_p95_regression_pct" => "10",
        "baseline_failure_increase" => "0",
        "scenario_name" => "gunicorn-a2a-invoke-rust",
        "scenario_description" => "A2A invoke benchmark against Rust mode",
        "scenario_type" => "comparison",
        "target_kind" => "gateway",
        "auth_mode" => "jwt",
        "plugins_enabled" => "false",
        "expected_mcp_runtime" => "rust",
        "expected_mcp_runtime_mode" => "rust-managed",
        "expected_a2a_runtime" => "rust",
        "rust_plugins" => "true",
        "profiling_image" => "false",
        "container_file" => "crates/contextforge_benchmark_runner/assets/Containerfile",
        "image_name" => "mcpgateway/mcpgateway",
        "image_tag" => "benchmark-suite-modular-design",
        "rebuild_policy" => "missing",
        "build_args" => "ENABLE_RUST_MCP_RMCP = \"true\" | ENABLE_A2A = \"true\"",
        "http_server" => "granian",
        "runtime_host" => "127.0.0.1",
        "transport_type" => "streamablehttp",
        "gunicorn_workers" | "granian_workers" | "uvicorn_workers" => "12",
        "gunicorn_timeout" => "30",
        "gunicorn_graceful_timeout" => "30",
        "gunicorn_keep_alive" => "10",
        "gunicorn_max_requests" | "uvicorn_limit_max_requests" => "0",
        "gunicorn_max_requests_jitter" => "0",
        "gunicorn_backlog" | "granian_backlog" | "uvicorn_backlog" => "2048",
        "gunicorn_preload_app" | "granian_respawn_failed" => "true",
        "gunicorn_dev_mode" | "granian_dev_mode" | "uvicorn_dev_mode" => "false",
        "granian_runtime_mode" => "mt",
        "granian_runtime_threads" => "1",
        "granian_blocking_threads" => "512",
        "granian_http" => "1",
        "granian_loop" | "uvicorn_loop" => "auto",
        "granian_task_impl" => "async-std",
        "granian_http1_pipeline_flush" => "false",
        "granian_http1_buffer_size" => "8192",
        "granian_backpressure" => "1024",
        "granian_workers_lifetime" | "granian_workers_max_rss" => "0",
        "granian_log_level" | "uvicorn_log_level" | "gateway_log_level" => "warning",
        "uvicorn_http" => "auto",
        "uvicorn_timeout_keep_alive" => "5",
        "trust_proxy_auth"
        | "sqlalchemy_echo"
        | "templates_auto_reload"
        | "structured_logging_database_enabled" => "false",
        "disable_access_log" => "true",
        "gateway_environment" => "RUST_MCP_MODE = \"edge\" | MCPGATEWAY_UI_ENABLED = \"false\"",
        "target_service" => "nginx",
        "driver" => "contextforge_goose",
        "headless" | "only_summary" | "retry_enabled" | "capture_logs" | "save_raw_results"
        | "reuse_stack" => "true",
        "html_report"
        | "include_admin_endpoints"
        | "include_mcp_endpoints"
        | "include_resource_endpoints"
        | "include_prompt_endpoints"
        | "include_tool_endpoints"
        | "profiling_enabled"
        | "profiling_required" => "false",
        "users" => "300",
        "spawn_rate" => "60",
        "run_time" => "180s",
        "request_count" => "10000",
        "load_host" => "http://gateway:4444",
        "seed" => "1234",
        "tags" => "a2a,hot-path",
        "exclude_tags" => "admin",
        "load_extra_args" => "--report-file,custom-goose-report.html",
        "load_env" => "BENCH_MCP_SESSION_MODE = \"reuse\" | BENCHMARK_TARGET = \"a2a\"",
        "workload_selection" => "weighted-random",
        "fallback_endpoint" => "/health",
        "workload_endpoints" => {
            "[defaults.load.workload.endpoints.\"/a2a/a2a-echo-agent/invoke\"] | enabled = true | weight = 1"
        }
        "warmup_seconds" => "30",
        "measure_seconds" => "120",
        "profile_seconds" => "0",
        "cooldown_seconds" => "30",
        "enabled_groups" => "tools,resources",
        "disabled_groups" => "admin",
        "enabled_endpoints" => "/servers,/health",
        "disabled_endpoints" => "/admin/plugins",
        "enabled_tags" => "mcp,a2a",
        "disabled_tags" => "slow",
        "profiling_tools" => "perf,flamegraph",
        "profiling_duration_seconds" => "30",
        "max_attempts" => "2",
        "defaults_plugins_snippet" => "mode = \"rust\" | timeout_ms = 250",
        "scenario_setup_snippet" => "plugins_enabled = true",
        "scenario_build_snippet" => "image_tag = \"benchmark-override\"",
        "scenario_runtime_snippet" => "http_server = \"granian\"",
        "scenario_gateway_snippet" => "log_level = \"WARNING\"",
        "scenario_load_snippet" => "users = 100",
        "scenario_measurement_snippet" => "warmup_seconds = 10",
        "scenario_requests_snippet" => "enabled_groups = [\"resources\"]",
        "scenario_profiling_snippet" => {
            "enabled = true | tools = [\"perf\", \"flamegraph\"] | duration_seconds = 30 | required = true"
        }
        "scenario_execution_snippet" => "max_attempts = 1",
        "scenario_plugins_snippet" => "mode = \"rust\" | timeout_ms = 500",
        _ => "Set this to the value you want written into the generated scenario.",
    }
}
use crate::main_parts::*;
