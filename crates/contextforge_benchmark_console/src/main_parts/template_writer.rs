pub(crate) fn generate_template_toml(generator: &GeneratorState) -> String {
    let mut lines = Vec::new();

    lines.push("[suite]".to_string());
    push_string_line(&mut lines, "name", generator.get("suite_name"));
    push_string_line(
        &mut lines,
        "description",
        generator.get("suite_description"),
    );
    push_string_line(&mut lines, "output_root", generator.get("output_root"));
    push_bool_line(
        &mut lines,
        "continue_on_failure",
        generator.get("continue_on_failure"),
    );
    push_bool_line(
        &mut lines,
        "save_intermediate_artifacts",
        generator.get("save_intermediate_artifacts"),
    );
    push_bool_line(
        &mut lines,
        "flamegraph_enabled",
        generator.get("flamegraph_enabled"),
    );
    push_optional_string_line(&mut lines, "baseline_run", generator.get("baseline_run"));
    push_optional_scalar_line(
        &mut lines,
        "baseline_rps_drop_pct",
        generator.get("baseline_rps_drop_pct"),
    );
    push_optional_scalar_line(
        &mut lines,
        "baseline_p95_regression_pct",
        generator.get("baseline_p95_regression_pct"),
    );
    push_optional_scalar_line(
        &mut lines,
        "baseline_failure_increase",
        generator.get("baseline_failure_increase"),
    );

    lines.push(String::new());
    lines.push("[defaults.setup]".to_string());
    push_string_line(&mut lines, "target_kind", generator.get("target_kind"));
    push_string_line(&mut lines, "auth_mode", generator.get("auth_mode"));
    push_bool_line(
        &mut lines,
        "plugins_enabled",
        generator.get("plugins_enabled"),
    );
    push_optional_string_line(
        &mut lines,
        "expected_mcp_runtime",
        generator.get("expected_mcp_runtime"),
    );
    push_optional_string_line(
        &mut lines,
        "expected_mcp_runtime_mode",
        generator.get("expected_mcp_runtime_mode"),
    );
    push_optional_string_line(
        &mut lines,
        "expected_a2a_runtime",
        generator.get("expected_a2a_runtime"),
    );

    lines.push(String::new());
    lines.push("[defaults.build]".to_string());
    push_bool_line(&mut lines, "rust_plugins", generator.get("rust_plugins"));
    push_bool_line(
        &mut lines,
        "profiling_image",
        generator.get("profiling_image"),
    );
    push_string_line(
        &mut lines,
        "container_file",
        generator.get("container_file"),
    );
    push_string_line(&mut lines, "image_name", generator.get("image_name"));
    push_string_line(&mut lines, "image_tag", generator.get("image_tag"));
    push_string_line(
        &mut lines,
        "rebuild_policy",
        generator.get("rebuild_policy"),
    );
    append_optional_block(
        &mut lines,
        "[defaults.build.args]",
        generator.get("build_args"),
    );

    lines.push(String::new());
    lines.push("[defaults.runtime]".to_string());
    push_string_line(&mut lines, "http_server", generator.get("http_server"));
    push_string_line(&mut lines, "host", generator.get("runtime_host"));
    push_string_line(
        &mut lines,
        "transport_type",
        generator.get("transport_type"),
    );

    lines.push(String::new());
    lines.push("[defaults.runtime.gunicorn]".to_string());
    push_scalar_line(&mut lines, "workers", generator.get("gunicorn_workers"));
    push_scalar_line(&mut lines, "timeout", generator.get("gunicorn_timeout"));
    push_scalar_line(
        &mut lines,
        "graceful_timeout",
        generator.get("gunicorn_graceful_timeout"),
    );
    push_scalar_line(
        &mut lines,
        "keep_alive",
        generator.get("gunicorn_keep_alive"),
    );
    push_scalar_line(
        &mut lines,
        "max_requests",
        generator.get("gunicorn_max_requests"),
    );
    push_scalar_line(
        &mut lines,
        "max_requests_jitter",
        generator.get("gunicorn_max_requests_jitter"),
    );
    push_scalar_line(&mut lines, "backlog", generator.get("gunicorn_backlog"));
    push_bool_line(
        &mut lines,
        "preload_app",
        generator.get("gunicorn_preload_app"),
    );
    push_bool_line(&mut lines, "dev_mode", generator.get("gunicorn_dev_mode"));
    append_runtime_block_from_fields(
        &mut lines,
        "[defaults.runtime.granian]",
        &[
            ("workers", generator.get("granian_workers"), "number"),
            (
                "runtime_mode",
                generator.get("granian_runtime_mode"),
                "string",
            ),
            (
                "runtime_threads",
                generator.get("granian_runtime_threads"),
                "number",
            ),
            (
                "blocking_threads",
                generator.get("granian_blocking_threads"),
                "number",
            ),
            ("http", generator.get("granian_http"), "number"),
            ("loop", generator.get("granian_loop"), "string"),
            ("task_impl", generator.get("granian_task_impl"), "string"),
            (
                "http1_pipeline_flush",
                generator.get("granian_http1_pipeline_flush"),
                "bool",
            ),
            (
                "http1_buffer_size",
                generator.get("granian_http1_buffer_size"),
                "number",
            ),
            ("backlog", generator.get("granian_backlog"), "number"),
            (
                "backpressure",
                generator.get("granian_backpressure"),
                "number",
            ),
            (
                "respawn_failed",
                generator.get("granian_respawn_failed"),
                "bool",
            ),
            (
                "workers_lifetime",
                generator.get("granian_workers_lifetime"),
                "number",
            ),
            (
                "workers_max_rss",
                generator.get("granian_workers_max_rss"),
                "number",
            ),
            ("dev_mode", generator.get("granian_dev_mode"), "bool"),
            ("log_level", generator.get("granian_log_level"), "string"),
        ],
    );
    append_runtime_block_from_fields(
        &mut lines,
        "[defaults.runtime.uvicorn]",
        &[
            ("workers", generator.get("uvicorn_workers"), "number"),
            ("loop", generator.get("uvicorn_loop"), "string"),
            ("http", generator.get("uvicorn_http"), "string"),
            ("backlog", generator.get("uvicorn_backlog"), "number"),
            (
                "timeout_keep_alive",
                generator.get("uvicorn_timeout_keep_alive"),
                "number",
            ),
            (
                "limit_max_requests",
                generator.get("uvicorn_limit_max_requests"),
                "number",
            ),
            ("log_level", generator.get("uvicorn_log_level"), "string"),
            ("dev_mode", generator.get("uvicorn_dev_mode"), "bool"),
        ],
    );

    lines.push(String::new());
    lines.push("[defaults.topology]".to_string());
    push_string_line(&mut lines, "mode", generator.get("topology_mode"));
    push_scalar_line(&mut lines, "gateway_count", generator.get("gateway_count"));
    push_bool_line(
        &mut lines,
        "ingress_enabled",
        generator.get("ingress_enabled"),
    );
    push_string_line(
        &mut lines,
        "ingress_service",
        generator.get("ingress_service"),
    );
    lines.push(format!(
        "shared_services = [{}]",
        quoted_csv(generator.get("shared_services"))
    ));
    push_string_line(
        &mut lines,
        "gateway_base_service",
        generator.get("gateway_base_service"),
    );
    push_string_line(
        &mut lines,
        "gateway_name_prefix",
        generator.get("gateway_name_prefix"),
    );

    lines.push(String::new());
    lines.push("[defaults.gateway]".to_string());
    push_bool_line(
        &mut lines,
        "trust_proxy_auth",
        generator.get("trust_proxy_auth"),
    );
    push_bool_line(
        &mut lines,
        "disable_access_log",
        generator.get("disable_access_log"),
    );
    push_bool_line(
        &mut lines,
        "templates_auto_reload",
        generator.get("templates_auto_reload"),
    );
    push_bool_line(
        &mut lines,
        "structured_logging_database_enabled",
        generator.get("structured_logging_database_enabled"),
    );
    push_bool_line(
        &mut lines,
        "sqlalchemy_echo",
        generator.get("sqlalchemy_echo"),
    );
    push_string_line(&mut lines, "log_level", generator.get("gateway_log_level"));
    append_optional_block(
        &mut lines,
        "[defaults.gateway.environment]",
        generator.get("gateway_environment"),
    );

    lines.push(String::new());
    lines.push("[defaults.load]".to_string());
    push_string_line(&mut lines, "driver", generator.get("driver"));
    push_bool_line(&mut lines, "headless", generator.get("headless"));
    push_bool_line(&mut lines, "only_summary", generator.get("only_summary"));
    push_bool_line(&mut lines, "html_report", generator.get("html_report"));
    push_scalar_line(&mut lines, "users", generator.get("users"));
    push_scalar_line(&mut lines, "spawn_rate", generator.get("spawn_rate"));
    push_string_line(&mut lines, "run_time", generator.get("run_time"));
    push_optional_scalar_line(&mut lines, "request_count", generator.get("request_count"));
    push_optional_string_line(&mut lines, "host", generator.get("load_host"));
    push_optional_string_line(&mut lines, "seed", generator.get("seed"));
    push_optional_array_line(&mut lines, "tags", generator.get("tags"));
    push_optional_array_line(&mut lines, "exclude_tags", generator.get("exclude_tags"));
    push_optional_array_line(&mut lines, "extra_args", generator.get("load_extra_args"));
    push_string_line(
        &mut lines,
        "target_service",
        generator.get("target_service"),
    );
    append_optional_block(&mut lines, "[defaults.load.env]", generator.get("load_env"));

    lines.push(String::new());
    lines.push(template_endpoints(generator));

    lines.push(String::new());
    lines.push("[defaults.measurement]".to_string());
    push_scalar_line(
        &mut lines,
        "warmup_seconds",
        generator.get("warmup_seconds"),
    );
    push_scalar_line(
        &mut lines,
        "measure_seconds",
        generator.get("measure_seconds"),
    );
    push_scalar_line(
        &mut lines,
        "profile_seconds",
        generator.get("profile_seconds"),
    );
    push_scalar_line(
        &mut lines,
        "cooldown_seconds",
        generator.get("cooldown_seconds"),
    );

    lines.push(String::new());
    lines.push("[defaults.requests]".to_string());
    push_optional_array_line(
        &mut lines,
        "enabled_groups",
        generator.get("enabled_groups"),
    );
    push_optional_array_line(
        &mut lines,
        "disabled_groups",
        generator.get("disabled_groups"),
    );
    push_optional_array_line(
        &mut lines,
        "enabled_endpoints",
        generator.get("enabled_endpoints"),
    );
    push_optional_array_line(
        &mut lines,
        "disabled_endpoints",
        generator.get("disabled_endpoints"),
    );
    push_optional_array_line(&mut lines, "enabled_tags", generator.get("enabled_tags"));
    push_optional_array_line(&mut lines, "disabled_tags", generator.get("disabled_tags"));
    push_bool_line(
        &mut lines,
        "include_admin_endpoints",
        generator.get("include_admin_endpoints"),
    );
    push_bool_line(
        &mut lines,
        "include_mcp_endpoints",
        generator.get("include_mcp_endpoints"),
    );
    push_bool_line(
        &mut lines,
        "include_resource_endpoints",
        generator.get("include_resource_endpoints"),
    );
    push_bool_line(
        &mut lines,
        "include_prompt_endpoints",
        generator.get("include_prompt_endpoints"),
    );
    push_bool_line(
        &mut lines,
        "include_tool_endpoints",
        generator.get("include_tool_endpoints"),
    );

    lines.push(String::new());
    lines.push("[defaults.profiling]".to_string());
    push_bool_line(&mut lines, "enabled", generator.get("profiling_enabled"));
    let profiling_tools = quoted_csv(generator.get("profiling_tools"));
    lines.push(format!("tools = [{}]", profiling_tools));
    push_scalar_line(
        &mut lines,
        "duration_seconds",
        generator.get("profiling_duration_seconds"),
    );
    push_bool_line(&mut lines, "required", generator.get("profiling_required"));

    lines.push(String::new());
    lines.push("[defaults.execution]".to_string());
    push_bool_line(&mut lines, "retry_enabled", generator.get("retry_enabled"));
    push_scalar_line(&mut lines, "max_attempts", generator.get("max_attempts"));
    push_bool_line(&mut lines, "capture_logs", generator.get("capture_logs"));
    push_bool_line(
        &mut lines,
        "save_raw_results",
        generator.get("save_raw_results"),
    );
    push_bool_line(&mut lines, "reuse_stack", generator.get("reuse_stack"));
    append_optional_block(
        &mut lines,
        "[defaults.plugins.example-plugin]",
        generator.get("defaults_plugins_snippet"),
    );

    lines.push(String::new());
    lines.push("[[scenario]]".to_string());
    push_string_line(&mut lines, "name", generator.get("scenario_name"));
    push_string_line(
        &mut lines,
        "description",
        generator.get("scenario_description"),
    );
    push_string_line(&mut lines, "scenario_type", generator.get("scenario_type"));
    append_optional_block(
        &mut lines,
        "[scenario.setup]",
        generator.get("scenario_setup_snippet"),
    );
    append_optional_block(
        &mut lines,
        "[scenario.build]",
        generator.get("scenario_build_snippet"),
    );
    append_optional_block(
        &mut lines,
        "[scenario.runtime]",
        generator.get("scenario_runtime_snippet"),
    );
    append_optional_block(
        &mut lines,
        "[scenario.topology]",
        generator.get("scenario_topology_snippet"),
    );
    if generator.get("topology_mode") == "multi_gateway" {
        lines.push("# Example node-specific overrides:".to_string());
        lines.push("[[scenario.topology.gateway_override]]".to_string());
        lines.push("index = 2".to_string());
        lines.push("[scenario.topology.gateway_override.environment]".to_string());
        lines.push("LOG_LEVEL = \"DEBUG\"".to_string());
        append_optional_block(
            &mut lines,
            "[[scenario.topology.gateway_override]]",
            generator.get("gateway_overrides"),
        );
    }
    append_optional_block(
        &mut lines,
        "[scenario.gateway]",
        generator.get("scenario_gateway_snippet"),
    );
    append_optional_block(
        &mut lines,
        "[scenario.load]",
        generator.get("scenario_load_snippet"),
    );
    append_optional_block(
        &mut lines,
        "[scenario.measurement]",
        generator.get("scenario_measurement_snippet"),
    );
    append_optional_block(
        &mut lines,
        "[scenario.requests]",
        generator.get("scenario_requests_snippet"),
    );
    append_optional_block(
        &mut lines,
        "[scenario.profiling]",
        generator.get("scenario_profiling_snippet"),
    );
    append_optional_block(
        &mut lines,
        "[scenario.execution]",
        generator.get("scenario_execution_snippet"),
    );
    append_optional_block(
        &mut lines,
        "[scenario.plugins.example-plugin]",
        generator.get("scenario_plugins_snippet"),
    );

    lines.join("\n") + "\n"
}
use crate::main_parts::*;
