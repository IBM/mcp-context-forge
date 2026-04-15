pub(crate) fn generator_section(key: &str) -> &'static str {
    match key {
        "file_stem" | "template_kind" => "Generator",
        "suite_name"
        | "suite_description"
        | "output_root"
        | "continue_on_failure"
        | "save_intermediate_artifacts"
        | "flamegraph_enabled"
        | "baseline_run"
        | "baseline_rps_drop_pct"
        | "baseline_p95_regression_pct"
        | "baseline_failure_increase" => "Suite",
        "scenario_name" | "scenario_description" | "scenario_type" => "Scenario",
        "target_kind"
        | "auth_mode"
        | "plugins_enabled"
        | "expected_mcp_runtime"
        | "expected_mcp_runtime_mode"
        | "expected_a2a_runtime"
        | "scenario_setup_snippet" => "Setup",
        "rust_plugins"
        | "profiling_image"
        | "container_file"
        | "image_name"
        | "image_tag"
        | "rebuild_policy"
        | "build_args"
        | "scenario_build_snippet" => "Build",
        "http_server"
        | "runtime_host"
        | "transport_type"
        | "gunicorn_workers"
        | "gunicorn_timeout"
        | "gunicorn_graceful_timeout"
        | "gunicorn_keep_alive"
        | "gunicorn_max_requests"
        | "gunicorn_max_requests_jitter"
        | "gunicorn_backlog"
        | "gunicorn_preload_app"
        | "gunicorn_dev_mode"
        | "granian_workers"
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
        | "granian_log_level"
        | "uvicorn_workers"
        | "uvicorn_loop"
        | "uvicorn_http"
        | "uvicorn_backlog"
        | "uvicorn_timeout_keep_alive"
        | "uvicorn_limit_max_requests"
        | "uvicorn_log_level"
        | "uvicorn_dev_mode"
        | "scenario_runtime_snippet" => "Runtime",
        "trust_proxy_auth"
        | "disable_access_log"
        | "templates_auto_reload"
        | "structured_logging_database_enabled"
        | "sqlalchemy_echo"
        | "gateway_log_level"
        | "gateway_environment"
        | "scenario_gateway_snippet" => "Gateway",
        "target_service"
        | "driver"
        | "headless"
        | "only_summary"
        | "html_report"
        | "users"
        | "spawn_rate"
        | "run_time"
        | "request_count"
        | "load_host"
        | "seed"
        | "tags"
        | "exclude_tags"
        | "load_extra_args"
        | "load_env"
        | "workload_selection"
        | "fallback_endpoint"
        | "workload_endpoints"
        | "scenario_load_snippet" => "Load",
        "warmup_seconds"
        | "measure_seconds"
        | "profile_seconds"
        | "cooldown_seconds"
        | "scenario_measurement_snippet" => "Measurement",
        "enabled_groups"
        | "disabled_groups"
        | "enabled_endpoints"
        | "disabled_endpoints"
        | "enabled_tags"
        | "disabled_tags"
        | "include_admin_endpoints"
        | "include_mcp_endpoints"
        | "include_resource_endpoints"
        | "include_prompt_endpoints"
        | "include_tool_endpoints"
        | "scenario_requests_snippet" => "Requests",
        "profiling_enabled"
        | "profiling_tools"
        | "profiling_duration_seconds"
        | "profiling_required"
        | "scenario_profiling_snippet" => "Profiling",
        "retry_enabled"
        | "max_attempts"
        | "capture_logs"
        | "save_raw_results"
        | "reuse_stack"
        | "scenario_execution_snippet" => "Execution",
        "defaults_plugins_snippet" | "scenario_plugins_snippet" => "Plugins",
        _ => "Other",
    }
}

pub(crate) fn generator_config_path(key: &str) -> &'static str {
    match key {
        "file_stem" => "output file name",
        "template_kind" => "starter preset",
        "suite_name" => "suite.name",
        "suite_description" => "suite.description",
        "output_root" => "suite.output_root",
        "continue_on_failure" => "suite.continue_on_failure",
        "save_intermediate_artifacts" => "suite.save_intermediate_artifacts",
        "flamegraph_enabled" => "suite.flamegraph_enabled",
        "baseline_run" => "suite.baseline_run",
        "baseline_rps_drop_pct" => "suite.baseline_rps_drop_pct",
        "baseline_p95_regression_pct" => "suite.baseline_p95_regression_pct",
        "baseline_failure_increase" => "suite.baseline_failure_increase",
        "scenario_name" => "scenario.name",
        "scenario_description" => "scenario.description",
        "scenario_type" => "scenario.scenario_type",
        "target_kind" => "defaults.setup.target_kind",
        "auth_mode" => "defaults.setup.auth_mode",
        "plugins_enabled" => "defaults.setup.plugins_enabled",
        "expected_mcp_runtime" => "defaults.setup.expected_mcp_runtime",
        "expected_mcp_runtime_mode" => "defaults.setup.expected_mcp_runtime_mode",
        "expected_a2a_runtime" => "defaults.setup.expected_a2a_runtime",
        "rust_plugins" => "defaults.build.rust_plugins",
        "profiling_image" => "defaults.build.profiling_image",
        "container_file" => "defaults.build.container_file",
        "image_name" => "defaults.build.image_name",
        "image_tag" => "defaults.build.image_tag",
        "rebuild_policy" => "defaults.build.rebuild_policy",
        "build_args" => "defaults.build.args",
        "http_server" => "defaults.runtime.http_server",
        "runtime_host" => "defaults.runtime.host",
        "transport_type" => "defaults.runtime.transport_type",
        "gunicorn_workers" => "defaults.runtime.gunicorn.workers",
        "gunicorn_timeout" => "defaults.runtime.gunicorn.timeout",
        "gunicorn_graceful_timeout" => "defaults.runtime.gunicorn.graceful_timeout",
        "gunicorn_keep_alive" => "defaults.runtime.gunicorn.keep_alive",
        "gunicorn_max_requests" => "defaults.runtime.gunicorn.max_requests",
        "gunicorn_max_requests_jitter" => "defaults.runtime.gunicorn.max_requests_jitter",
        "gunicorn_backlog" => "defaults.runtime.gunicorn.backlog",
        "gunicorn_preload_app" => "defaults.runtime.gunicorn.preload_app",
        "gunicorn_dev_mode" => "defaults.runtime.gunicorn.dev_mode",
        "granian_workers" => "defaults.runtime.granian.workers",
        "granian_runtime_mode" => "defaults.runtime.granian.runtime_mode",
        "granian_runtime_threads" => "defaults.runtime.granian.runtime_threads",
        "granian_blocking_threads" => "defaults.runtime.granian.blocking_threads",
        "granian_http" => "defaults.runtime.granian.http",
        "granian_loop" => "defaults.runtime.granian.loop",
        "granian_task_impl" => "defaults.runtime.granian.task_impl",
        "granian_http1_pipeline_flush" => "defaults.runtime.granian.http1_pipeline_flush",
        "granian_http1_buffer_size" => "defaults.runtime.granian.http1_buffer_size",
        "granian_backlog" => "defaults.runtime.granian.backlog",
        "granian_backpressure" => "defaults.runtime.granian.backpressure",
        "granian_respawn_failed" => "defaults.runtime.granian.respawn_failed",
        "granian_workers_lifetime" => "defaults.runtime.granian.workers_lifetime",
        "granian_workers_max_rss" => "defaults.runtime.granian.workers_max_rss",
        "granian_dev_mode" => "defaults.runtime.granian.dev_mode",
        "granian_log_level" => "defaults.runtime.granian.log_level",
        "uvicorn_workers" => "defaults.runtime.uvicorn.workers",
        "uvicorn_loop" => "defaults.runtime.uvicorn.loop",
        "uvicorn_http" => "defaults.runtime.uvicorn.http",
        "uvicorn_backlog" => "defaults.runtime.uvicorn.backlog",
        "uvicorn_timeout_keep_alive" => "defaults.runtime.uvicorn.timeout_keep_alive",
        "uvicorn_limit_max_requests" => "defaults.runtime.uvicorn.limit_max_requests",
        "uvicorn_log_level" => "defaults.runtime.uvicorn.log_level",
        "uvicorn_dev_mode" => "defaults.runtime.uvicorn.dev_mode",
        "trust_proxy_auth" => "defaults.gateway.trust_proxy_auth",
        "disable_access_log" => "defaults.gateway.disable_access_log",
        "templates_auto_reload" => "defaults.gateway.templates_auto_reload",
        "structured_logging_database_enabled" => {
            "defaults.gateway.structured_logging_database_enabled"
        }
        "sqlalchemy_echo" => "defaults.gateway.sqlalchemy_echo",
        "gateway_log_level" => "defaults.gateway.log_level",
        "gateway_environment" => "defaults.gateway.environment",
        "target_service" => "defaults.load.target_service",
        "driver" => "defaults.load.driver",
        "headless" => "defaults.load.headless",
        "only_summary" => "defaults.load.only_summary",
        "html_report" => "defaults.load.html_report",
        "users" => "defaults.load.users",
        "spawn_rate" => "defaults.load.spawn_rate",
        "run_time" => "defaults.load.run_time",
        "request_count" => "defaults.load.request_count",
        "load_host" => "defaults.load.host",
        "seed" => "defaults.load.seed",
        "tags" => "defaults.load.tags",
        "exclude_tags" => "defaults.load.exclude_tags",
        "load_extra_args" => "defaults.load.extra_args",
        "load_env" => "defaults.load.env",
        "workload_selection" => "defaults.load.workload.selection",
        "fallback_endpoint" => "defaults.load.workload.fallback_endpoint",
        "workload_endpoints" => "defaults.load.workload.endpoints",
        "warmup_seconds" => "defaults.measurement.warmup_seconds",
        "measure_seconds" => "defaults.measurement.measure_seconds",
        "profile_seconds" => "defaults.measurement.profile_seconds",
        "cooldown_seconds" => "defaults.measurement.cooldown_seconds",
        "enabled_groups" => "defaults.requests.enabled_groups",
        "disabled_groups" => "defaults.requests.disabled_groups",
        "enabled_endpoints" => "defaults.requests.enabled_endpoints",
        "disabled_endpoints" => "defaults.requests.disabled_endpoints",
        "enabled_tags" => "defaults.requests.enabled_tags",
        "disabled_tags" => "defaults.requests.disabled_tags",
        "include_admin_endpoints" => "defaults.requests.include_admin_endpoints",
        "include_mcp_endpoints" => "defaults.requests.include_mcp_endpoints",
        "include_resource_endpoints" => "defaults.requests.include_resource_endpoints",
        "include_prompt_endpoints" => "defaults.requests.include_prompt_endpoints",
        "include_tool_endpoints" => "defaults.requests.include_tool_endpoints",
        "profiling_enabled" => "defaults.profiling.enabled",
        "profiling_tools" => "defaults.profiling.tools",
        "profiling_duration_seconds" => "defaults.profiling.duration_seconds",
        "profiling_required" => "defaults.profiling.required",
        "retry_enabled" => "defaults.execution.retry_enabled",
        "max_attempts" => "defaults.execution.max_attempts",
        "capture_logs" => "defaults.execution.capture_logs",
        "save_raw_results" => "defaults.execution.save_raw_results",
        "reuse_stack" => "defaults.execution.reuse_stack",
        "defaults_plugins_snippet" => "defaults.plugins.<name>",
        "scenario_setup_snippet" => "scenario.setup",
        "scenario_build_snippet" => "scenario.build",
        "scenario_runtime_snippet" => "scenario.runtime",
        "scenario_gateway_snippet" => "scenario.gateway",
        "scenario_load_snippet" => "scenario.load",
        "scenario_measurement_snippet" => "scenario.measurement",
        "scenario_requests_snippet" => "scenario.requests",
        "scenario_profiling_snippet" => "scenario.profiling",
        "scenario_execution_snippet" => "scenario.execution",
        "scenario_plugins_snippet" => "scenario.plugins.<name>",
        _ => "custom",
    }
}

pub(crate) fn generator_format_hint(key: &str) -> &'static str {
    match key {
        "template_kind" => "blank, mcp, or a2a",
        "target_kind" => "gateway or agent",
        "auth_mode" => "jwt, basic, or none",
        "rebuild_policy" => "never, missing, or always",
        "http_server" => "gunicorn, granian, or uvicorn",
        "transport_type" => "streamablehttp, sse, or websocket",
        "target_service" => "nginx or gateway",
        "continue_on_failure"
        | "save_intermediate_artifacts"
        | "flamegraph_enabled"
        | "plugins_enabled"
        | "rust_plugins"
        | "profiling_image"
        | "gunicorn_preload_app"
        | "gunicorn_dev_mode"
        | "granian_http1_pipeline_flush"
        | "granian_respawn_failed"
        | "granian_dev_mode"
        | "trust_proxy_auth"
        | "disable_access_log"
        | "templates_auto_reload"
        | "structured_logging_database_enabled"
        | "sqlalchemy_echo"
        | "headless"
        | "only_summary"
        | "html_report"
        | "include_admin_endpoints"
        | "include_mcp_endpoints"
        | "include_resource_endpoints"
        | "include_prompt_endpoints"
        | "include_tool_endpoints"
        | "profiling_enabled"
        | "profiling_required"
        | "retry_enabled"
        | "capture_logs"
        | "save_raw_results"
        | "reuse_stack"
        | "uvicorn_dev_mode" => "true or false",
        "tags" | "exclude_tags" | "enabled_groups" | "disabled_groups" | "enabled_endpoints"
        | "disabled_endpoints" | "enabled_tags" | "disabled_tags" | "profiling_tools"
        | "load_extra_args" => "comma-separated list",
        "build_args"
        | "gateway_environment"
        | "load_env"
        | "workload_endpoints"
        | "defaults_plugins_snippet"
        | "scenario_setup_snippet"
        | "scenario_build_snippet"
        | "scenario_runtime_snippet"
        | "scenario_gateway_snippet"
        | "scenario_load_snippet"
        | "scenario_measurement_snippet"
        | "scenario_requests_snippet"
        | "scenario_profiling_snippet"
        | "scenario_execution_snippet"
        | "scenario_plugins_snippet" => "raw TOML lines separated by ' | '",
        "users"
        | "spawn_rate"
        | "warmup_seconds"
        | "measure_seconds"
        | "profile_seconds"
        | "cooldown_seconds"
        | "max_attempts"
        | "gunicorn_workers"
        | "gunicorn_timeout"
        | "gunicorn_graceful_timeout"
        | "gunicorn_keep_alive"
        | "gunicorn_max_requests"
        | "gunicorn_max_requests_jitter"
        | "gunicorn_backlog"
        | "granian_workers"
        | "granian_runtime_threads"
        | "granian_blocking_threads"
        | "granian_http1_buffer_size"
        | "granian_backlog"
        | "granian_backpressure"
        | "granian_workers_lifetime"
        | "granian_workers_max_rss"
        | "uvicorn_workers"
        | "uvicorn_backlog"
        | "uvicorn_timeout_keep_alive"
        | "uvicorn_limit_max_requests"
        | "request_count"
        | "profiling_duration_seconds" => "integer number",
        "baseline_rps_drop_pct" | "baseline_p95_regression_pct" | "baseline_failure_increase" => {
            "numeric threshold"
        }
        "run_time" => "duration like 180s or 5m",
        "file_stem" => "filename stem without .toml",
        _ => "plain text",
    }
}
