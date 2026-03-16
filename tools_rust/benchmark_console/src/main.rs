use std::env;
use std::fs;
use std::io::{self, Stdout};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use crossterm::cursor::{Hide, Show};
use crossterm::event::{self, Event, KeyCode, KeyEvent};
use crossterm::execute;
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
};
use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Tabs, Wrap};

type AppResult<T> = Result<T, Box<dyn std::error::Error>>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Action {
    Run,
    Validate,
    Smoke,
    CheckRuntime,
    List,
    Report,
    Compare,
    Generate,
}

impl Action {
    const ALL: [Action; 8] = [
        Action::Run,
        Action::Validate,
        Action::Smoke,
        Action::CheckRuntime,
        Action::List,
        Action::Report,
        Action::Compare,
        Action::Generate,
    ];

    fn label(self) -> &'static str {
        match self {
            Action::Run => "Run",
            Action::Validate => "Validate",
            Action::Smoke => "Smoke",
            Action::CheckRuntime => "Check",
            Action::List => "List",
            Action::Report => "Report",
            Action::Compare => "Compare",
            Action::Generate => "Generate",
        }
    }

    fn help(self) -> &'static str {
        match self {
            Action::Run => "Execute the selected scenario end to end.",
            Action::Validate => "Resolve configs and generate reports without load.",
            Action::Smoke => "Run the selected scenario in smoke mode.",
            Action::CheckRuntime => "Check container runtime prerequisites only.",
            Action::List => "List committed scenarios and exit.",
            Action::Report => "Re-render a saved run summary.",
            Action::Compare => "Re-render comparison output for a saved run.",
            Action::Generate => "Generate a full TOML scenario template with all supported sections.",
        }
    }

    fn supports_scenario(self) -> bool {
        !matches!(self, Action::List | Action::Report | Action::Compare | Action::Generate)
    }

    fn supports_all(self) -> bool {
        matches!(
            self,
            Action::Run | Action::Validate | Action::Smoke | Action::CheckRuntime
        )
    }

    fn supports_clean(self) -> bool {
        matches!(self, Action::Run | Action::Smoke)
    }

    fn needs_run_path(self) -> bool {
        matches!(self, Action::Report | Action::Compare)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum InputMode {
    Normal,
    EditRunPath,
    EditExtraArgs,
    EditGeneratorField,
}

impl InputMode {
    fn label(self) -> &'static str {
        match self {
            InputMode::Normal => "Normal",
            InputMode::EditRunPath => "Editing Run Path",
            InputMode::EditExtraArgs => "Editing Extra Args",
            InputMode::EditGeneratorField => "Editing Generator Field",
        }
    }
}

#[derive(Clone, Copy)]
enum GeneratorFieldKind {
    Text,
    Bool,
    Choice(&'static [&'static str]),
}

struct GeneratorField {
    label: &'static str,
    key: &'static str,
    kind: GeneratorFieldKind,
    value: String,
    help: &'static str,
}

struct GeneratorState {
    fields: Vec<GeneratorField>,
    selected: usize,
    selected_section: usize,
}

impl GeneratorState {
    fn new() -> Self {
        Self {
            fields: vec![
                GeneratorField { label: "File Stem", key: "file_stem", kind: GeneratorFieldKind::Text, value: "new-scenario".to_string(), help: "Output file name under benchmarks/contextforge/scenarios/." },
                GeneratorField { label: "Template Kind", key: "template_kind", kind: GeneratorFieldKind::Choice(&["blank", "mcp", "a2a"]), value: "blank".to_string(), help: "Choose a starter workload shape." },
                GeneratorField { label: "Suite Name", key: "suite_name", kind: GeneratorFieldKind::Text, value: "benchmark-generated-suite".to_string(), help: "The [suite].name value." },
                GeneratorField { label: "Suite Desc", key: "suite_description", kind: GeneratorFieldKind::Text, value: "Generated benchmark scenario template".to_string(), help: "The [suite].description value." },
                GeneratorField { label: "Output Root", key: "output_root", kind: GeneratorFieldKind::Text, value: "reports/benchmarks".to_string(), help: "Benchmark output directory." },
                GeneratorField { label: "Continue Fail", key: "continue_on_failure", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "suite.continue_on_failure" },
                GeneratorField { label: "Save Artifacts", key: "save_intermediate_artifacts", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "suite.save_intermediate_artifacts" },
                GeneratorField { label: "Flamegraphs", key: "flamegraph_enabled", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "suite.flamegraph_enabled" },
                GeneratorField { label: "Baseline Run", key: "baseline_run", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional prior run_summary.json path." },
                GeneratorField { label: "Baseline RPS%", key: "baseline_rps_drop_pct", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional allowed RPS drop percentage." },
                GeneratorField { label: "Baseline P95%", key: "baseline_p95_regression_pct", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional allowed p95 regression percentage." },
                GeneratorField { label: "Baseline Fail+", key: "baseline_failure_increase", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional allowed failure increase." },
                GeneratorField { label: "Scenario Name", key: "scenario_name", kind: GeneratorFieldKind::Text, value: "generated-scenario".to_string(), help: "Name for the first [[scenario]] entry." },
                GeneratorField { label: "Scenario Desc", key: "scenario_description", kind: GeneratorFieldKind::Text, value: "Generated benchmark scenario".to_string(), help: "Description for the first [[scenario]] entry." },
                GeneratorField { label: "Scenario Type", key: "scenario_type", kind: GeneratorFieldKind::Text, value: "custom".to_string(), help: "Freeform scenario_type label." },
                GeneratorField { label: "Target Kind", key: "target_kind", kind: GeneratorFieldKind::Choice(&["gateway", "agent"]), value: "gateway".to_string(), help: "defaults.setup.target_kind" },
                GeneratorField { label: "Auth Mode", key: "auth_mode", kind: GeneratorFieldKind::Choice(&["jwt", "basic", "none"]), value: "jwt".to_string(), help: "defaults.setup.auth_mode" },
                GeneratorField { label: "Plugins", key: "plugins_enabled", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.setup.plugins_enabled" },
                GeneratorField { label: "Expect MCP", key: "expected_mcp_runtime", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional defaults.setup.expected_mcp_runtime" },
                GeneratorField { label: "Expect MCP Mode", key: "expected_mcp_runtime_mode", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional defaults.setup.expected_mcp_runtime_mode" },
                GeneratorField { label: "Expect A2A", key: "expected_a2a_runtime", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional defaults.setup.expected_a2a_runtime" },
                GeneratorField { label: "Repo URL", key: "repo_url", kind: GeneratorFieldKind::Text, value: "https://github.com/IBM/mcp-context-forge".to_string(), help: "defaults.build.repo_url" },
                GeneratorField { label: "Git Ref", key: "git_ref", kind: GeneratorFieldKind::Text, value: "main".to_string(), help: "defaults.build.git_ref" },
                GeneratorField { label: "Git Commit", key: "git_commit", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional pinned commit." },
                GeneratorField { label: "Rust Plugins", key: "rust_plugins", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.build.rust_plugins" },
                GeneratorField { label: "Profiling Img", key: "profiling_image", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.build.profiling_image" },
                GeneratorField { label: "Container File", key: "container_file", kind: GeneratorFieldKind::Text, value: "benchmarks/contextforge/Containerfile".to_string(), help: "defaults.build.container_file" },
                GeneratorField { label: "Image Name", key: "image_name", kind: GeneratorFieldKind::Text, value: "mcpgateway/mcpgateway".to_string(), help: "defaults.build.image_name" },
                GeneratorField { label: "Image Tag", key: "image_tag", kind: GeneratorFieldKind::Text, value: "benchmark-suite-generated".to_string(), help: "defaults.build.image_tag" },
                GeneratorField { label: "Rebuild", key: "rebuild_policy", kind: GeneratorFieldKind::Choice(&["never", "missing", "always"]), value: "missing".to_string(), help: "defaults.build.rebuild_policy" },
                GeneratorField { label: "Build Args", key: "build_args", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional build args. Use 'KEY = \"value\" | OTHER = \"x\"'." },
                GeneratorField { label: "HTTP Server", key: "http_server", kind: GeneratorFieldKind::Choice(&["gunicorn", "granian", "uvicorn"]), value: "gunicorn".to_string(), help: "defaults.runtime.http_server" },
                GeneratorField { label: "Runtime Host", key: "runtime_host", kind: GeneratorFieldKind::Text, value: "127.0.0.1".to_string(), help: "defaults.runtime.host" },
                GeneratorField { label: "Transport", key: "transport_type", kind: GeneratorFieldKind::Choice(&["streamablehttp", "sse", "websocket"]), value: "streamablehttp".to_string(), help: "defaults.runtime.transport_type" },
                GeneratorField { label: "Gunicorn Workers", key: "gunicorn_workers", kind: GeneratorFieldKind::Text, value: "12".to_string(), help: "defaults.runtime.gunicorn.workers" },
                GeneratorField { label: "Gunicorn Timeout", key: "gunicorn_timeout", kind: GeneratorFieldKind::Text, value: "30".to_string(), help: "defaults.runtime.gunicorn.timeout" },
                GeneratorField { label: "Gunicorn Grace", key: "gunicorn_graceful_timeout", kind: GeneratorFieldKind::Text, value: "30".to_string(), help: "defaults.runtime.gunicorn.graceful_timeout" },
                GeneratorField { label: "Gunicorn KeepAlive", key: "gunicorn_keep_alive", kind: GeneratorFieldKind::Text, value: "10".to_string(), help: "defaults.runtime.gunicorn.keep_alive" },
                GeneratorField { label: "Gunicorn MaxReq", key: "gunicorn_max_requests", kind: GeneratorFieldKind::Text, value: "0".to_string(), help: "defaults.runtime.gunicorn.max_requests" },
                GeneratorField { label: "Gunicorn Jitter", key: "gunicorn_max_requests_jitter", kind: GeneratorFieldKind::Text, value: "0".to_string(), help: "defaults.runtime.gunicorn.max_requests_jitter" },
                GeneratorField { label: "Gunicorn Backlog", key: "gunicorn_backlog", kind: GeneratorFieldKind::Text, value: "16384".to_string(), help: "defaults.runtime.gunicorn.backlog" },
                GeneratorField { label: "Gunicorn Preload", key: "gunicorn_preload_app", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "defaults.runtime.gunicorn.preload_app" },
                GeneratorField { label: "Gunicorn Dev", key: "gunicorn_dev_mode", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.runtime.gunicorn.dev_mode" },
                GeneratorField { label: "Granian Workers", key: "granian_workers", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Worker process count when using Granian." },
                GeneratorField { label: "Granian Mode", key: "granian_runtime_mode", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Granian runtime_mode, for example st or mt." },
                GeneratorField { label: "Granian Threads", key: "granian_runtime_threads", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Async runtime threads per worker." },
                GeneratorField { label: "Granian Blocking", key: "granian_blocking_threads", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Blocking thread pool size." },
                GeneratorField { label: "Granian HTTP", key: "granian_http", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "HTTP protocol mode used by Granian." },
                GeneratorField { label: "Granian Loop", key: "granian_loop", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Granian event loop selection." },
                GeneratorField { label: "Granian Task Impl", key: "granian_task_impl", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Task implementation backend for Granian." },
                GeneratorField { label: "Granian Flush", key: "granian_http1_pipeline_flush", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "Flush HTTP/1 pipelined responses immediately." },
                GeneratorField { label: "Granian Buf Size", key: "granian_http1_buffer_size", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "HTTP/1 buffer size in bytes." },
                GeneratorField { label: "Granian Backlog", key: "granian_backlog", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Listen backlog for pending connections." },
                GeneratorField { label: "Granian Pressure", key: "granian_backpressure", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Backpressure queue limit." },
                GeneratorField { label: "Granian Respawn", key: "granian_respawn_failed", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "Respawn failed workers automatically." },
                GeneratorField { label: "Granian Lifetime", key: "granian_workers_lifetime", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Maximum worker lifetime." },
                GeneratorField { label: "Granian Max RSS", key: "granian_workers_max_rss", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Restart workers over this RSS threshold." },
                GeneratorField { label: "Granian Dev", key: "granian_dev_mode", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "Enable Granian dev mode." },
                GeneratorField { label: "Granian Log", key: "granian_log_level", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Granian log level." },
                GeneratorField { label: "Uvicorn Workers", key: "uvicorn_workers", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Worker process count when using Uvicorn." },
                GeneratorField { label: "Uvicorn Loop", key: "uvicorn_loop", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Event loop implementation, for example auto or uvloop." },
                GeneratorField { label: "Uvicorn HTTP", key: "uvicorn_http", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "HTTP protocol implementation." },
                GeneratorField { label: "Uvicorn Backlog", key: "uvicorn_backlog", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Listen backlog for pending connections." },
                GeneratorField { label: "Uvicorn KeepAlive", key: "uvicorn_timeout_keep_alive", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Keep-alive timeout in seconds." },
                GeneratorField { label: "Uvicorn MaxReq", key: "uvicorn_limit_max_requests", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Restart worker after this many requests." },
                GeneratorField { label: "Uvicorn Log", key: "uvicorn_log_level", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Uvicorn log level." },
                GeneratorField { label: "Uvicorn Dev", key: "uvicorn_dev_mode", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "Enable Uvicorn dev mode." },
                GeneratorField { label: "Trust Proxy", key: "trust_proxy_auth", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.gateway.trust_proxy_auth" },
                GeneratorField { label: "Disable Access Log", key: "disable_access_log", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "defaults.gateway.disable_access_log" },
                GeneratorField { label: "Templates Reload", key: "templates_auto_reload", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.gateway.templates_auto_reload" },
                GeneratorField { label: "Structured DB Log", key: "structured_logging_database_enabled", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.gateway.structured_logging_database_enabled" },
                GeneratorField { label: "SQL Echo", key: "sqlalchemy_echo", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.gateway.sqlalchemy_echo" },
                GeneratorField { label: "Gateway Log", key: "gateway_log_level", kind: GeneratorFieldKind::Text, value: "ERROR".to_string(), help: "defaults.gateway.log_level" },
                GeneratorField { label: "Gateway Env", key: "gateway_environment", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional lines with ' | ' separators, e.g. RUST_MCP_MODE = \"edge\"" },
                GeneratorField { label: "Target Service", key: "target_service", kind: GeneratorFieldKind::Choice(&["nginx", "gateway"]), value: "nginx".to_string(), help: "defaults.load.target_service" },
                GeneratorField { label: "Locust File", key: "locustfile", kind: GeneratorFieldKind::Text, value: "benchmarks/contextforge/locust/locustfile_benchmark_ab.py".to_string(), help: "defaults.load.locustfile" },
                GeneratorField { label: "User Class", key: "user_class", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "defaults.load.user_class" },
                GeneratorField { label: "Headless", key: "headless", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "defaults.load.headless" },
                GeneratorField { label: "Only Summary", key: "only_summary", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "defaults.load.only_summary" },
                GeneratorField { label: "HTML Report", key: "html_report", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.load.html_report" },
                GeneratorField { label: "Users", key: "users", kind: GeneratorFieldKind::Text, value: "300".to_string(), help: "defaults.load.users" },
                GeneratorField { label: "Spawn Rate", key: "spawn_rate", kind: GeneratorFieldKind::Text, value: "60".to_string(), help: "defaults.load.spawn_rate" },
                GeneratorField { label: "Run Time", key: "run_time", kind: GeneratorFieldKind::Text, value: "180s".to_string(), help: "defaults.load.run_time" },
                GeneratorField { label: "Request Count", key: "request_count", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional defaults.load.request_count" },
                GeneratorField { label: "Load Host", key: "load_host", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional defaults.load.host" },
                GeneratorField { label: "Seed", key: "seed", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional defaults.load.seed" },
                GeneratorField { label: "Tags", key: "tags", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Comma-separated defaults.load.tags" },
                GeneratorField { label: "Exclude Tags", key: "exclude_tags", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Comma-separated defaults.load.exclude_tags" },
                GeneratorField { label: "Extra Args CSV", key: "load_extra_args", kind: GeneratorFieldKind::Text, value: "--reset-stats".to_string(), help: "Comma-separated defaults.load.extra_args" },
                GeneratorField { label: "Load Env", key: "load_env", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional lines with ' | ' separators, e.g. BENCH_MCP_SESSION_MODE = \"reuse\"" },
                GeneratorField { label: "Selection", key: "workload_selection", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional defaults.load.workload.selection" },
                GeneratorField { label: "Fallback", key: "fallback_endpoint", kind: GeneratorFieldKind::Text, value: "/health".to_string(), help: "defaults.load.workload.fallback_endpoint" },
                GeneratorField { label: "Workload Endpoints", key: "workload_endpoints", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for workload endpoint tables." },
                GeneratorField { label: "Warmup", key: "warmup_seconds", kind: GeneratorFieldKind::Text, value: "30".to_string(), help: "defaults.measurement.warmup_seconds" },
                GeneratorField { label: "Measure", key: "measure_seconds", kind: GeneratorFieldKind::Text, value: "120".to_string(), help: "defaults.measurement.measure_seconds" },
                GeneratorField { label: "Profile", key: "profile_seconds", kind: GeneratorFieldKind::Text, value: "0".to_string(), help: "defaults.measurement.profile_seconds" },
                GeneratorField { label: "Cooldown", key: "cooldown_seconds", kind: GeneratorFieldKind::Text, value: "30".to_string(), help: "defaults.measurement.cooldown_seconds" },
                GeneratorField { label: "Req Enabled Groups", key: "enabled_groups", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Comma-separated defaults.requests.enabled_groups" },
                GeneratorField { label: "Req Disabled Groups", key: "disabled_groups", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Comma-separated defaults.requests.disabled_groups" },
                GeneratorField { label: "Req Enabled Endp", key: "enabled_endpoints", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Comma-separated defaults.requests.enabled_endpoints" },
                GeneratorField { label: "Req Disabled Endp", key: "disabled_endpoints", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Comma-separated defaults.requests.disabled_endpoints" },
                GeneratorField { label: "Req Enabled Tags", key: "enabled_tags", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Comma-separated defaults.requests.enabled_tags" },
                GeneratorField { label: "Req Disabled Tags", key: "disabled_tags", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Comma-separated defaults.requests.disabled_tags" },
                GeneratorField { label: "Incl Admin", key: "include_admin_endpoints", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.requests.include_admin_endpoints" },
                GeneratorField { label: "Incl MCP", key: "include_mcp_endpoints", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.requests.include_mcp_endpoints" },
                GeneratorField { label: "Incl Resource", key: "include_resource_endpoints", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.requests.include_resource_endpoints" },
                GeneratorField { label: "Incl Prompt", key: "include_prompt_endpoints", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.requests.include_prompt_endpoints" },
                GeneratorField { label: "Incl Tool", key: "include_tool_endpoints", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.requests.include_tool_endpoints" },
                GeneratorField { label: "Profiling On", key: "profiling_enabled", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.profiling.enabled" },
                GeneratorField { label: "Profiling Tools", key: "profiling_tools", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Comma-separated defaults.profiling.tools" },
                GeneratorField { label: "Py Spy", key: "py_spy", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.profiling.py_spy" },
                GeneratorField { label: "Profile Dur", key: "profiling_duration_seconds", kind: GeneratorFieldKind::Text, value: "0".to_string(), help: "defaults.profiling.duration_seconds" },
                GeneratorField { label: "Profile Required", key: "profiling_required", kind: GeneratorFieldKind::Bool, value: "false".to_string(), help: "defaults.profiling.required" },
                GeneratorField { label: "Retry Enabled", key: "retry_enabled", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "defaults.execution.retry_enabled" },
                GeneratorField { label: "Max Attempts", key: "max_attempts", kind: GeneratorFieldKind::Text, value: "2".to_string(), help: "defaults.execution.max_attempts" },
                GeneratorField { label: "Capture Logs", key: "capture_logs", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "defaults.execution.capture_logs" },
                GeneratorField { label: "Save Raw", key: "save_raw_results", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "defaults.execution.save_raw_results" },
                GeneratorField { label: "Reuse Stack", key: "reuse_stack", kind: GeneratorFieldKind::Bool, value: "true".to_string(), help: "defaults.execution.reuse_stack" },
                GeneratorField { label: "Defaults Plugins", key: "defaults_plugins_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [defaults.plugins.<name>]." },
                GeneratorField { label: "Scenario Setup", key: "scenario_setup_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.setup]." },
                GeneratorField { label: "Scenario Build", key: "scenario_build_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.build]." },
                GeneratorField { label: "Scenario Runtime", key: "scenario_runtime_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.runtime]." },
                GeneratorField { label: "Scenario Gateway", key: "scenario_gateway_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.gateway]." },
                GeneratorField { label: "Scenario Load", key: "scenario_load_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.load]." },
                GeneratorField { label: "Scenario Measure", key: "scenario_measurement_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.measurement]." },
                GeneratorField { label: "Scenario Requests", key: "scenario_requests_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.requests]." },
                GeneratorField { label: "Scenario Profiling", key: "scenario_profiling_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.profiling]." },
                GeneratorField { label: "Scenario Execution", key: "scenario_execution_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.execution]." },
                GeneratorField { label: "Scenario Plugins", key: "scenario_plugins_snippet", kind: GeneratorFieldKind::Text, value: "".to_string(), help: "Optional raw TOML lines with ' | ' separators for [scenario.plugins.<name>]." },
            ],
            selected: 0,
            selected_section: 0,
        }
    }

    fn sections() -> &'static [&'static str] {
        &[
            "All",
            "Generator",
            "Suite",
            "Scenario",
            "Setup",
            "Build",
            "Runtime",
            "Gateway",
            "Load",
            "Measurement",
            "Requests",
            "Profiling",
            "Execution",
            "Plugins",
        ]
    }

    fn selected_section_name(&self) -> &'static str {
        Self::sections()[self.selected_section]
    }

    fn visible_indices(&self) -> Vec<usize> {
        self.fields
            .iter()
            .enumerate()
            .filter_map(|(index, field)| {
                let in_section = self.selected_section_name() == "All" || generator_section(field.key) == self.selected_section_name();
                (in_section && self.is_visible(field.key)).then_some(index)
            })
            .collect()
    }

    fn ensure_visible_selection(&mut self) {
        let visible = self.visible_indices();
        if visible.is_empty() {
            self.selected = 0;
            return;
        }
        if visible.contains(&self.selected) {
            return;
        }
        self.selected = *visible
            .iter()
            .find(|index| **index > self.selected)
            .unwrap_or(&visible[0]);
    }

    fn selected_field(&self) -> &GeneratorField {
        &self.fields[self.selected]
    }

    fn selected_field_mut(&mut self) -> &mut GeneratorField {
        &mut self.fields[self.selected]
    }

    fn move_selected(&mut self, delta: isize) {
        let visible = self.visible_indices();
        if visible.is_empty() {
            return;
        }
        let current_pos = visible.iter().position(|index| *index == self.selected).unwrap_or(0) as isize;
        let len = visible.len() as isize;
        let next_pos = (current_pos + delta).rem_euclid(len) as usize;
        self.selected = visible[next_pos];
    }

    fn move_section(&mut self, delta: isize) {
        let len = Self::sections().len() as isize;
        self.selected_section = (self.selected_section as isize + delta).rem_euclid(len) as usize;
        self.ensure_visible_selection();
    }

    fn get(&self, key: &str) -> &str {
        self.fields
            .iter()
            .find(|field| field.key == key)
            .map(|field| field.value.as_str())
            .unwrap_or("")
    }

    fn toggle_or_cycle(&mut self) {
        let field = self.selected_field_mut();
        match field.kind {
            GeneratorFieldKind::Bool => {
                field.value = if field.value == "true" { "false" } else { "true" }.to_string();
            }
            GeneratorFieldKind::Choice(options) => {
                let current = options.iter().position(|value| *value == field.value).unwrap_or(0);
                field.value = options[(current + 1) % options.len()].to_string();
            }
            GeneratorFieldKind::Text => {}
        }
        self.ensure_visible_selection();
    }

    fn is_visible(&self, key: &str) -> bool {
        let http_server = self.get("http_server");
        let profiling_enabled = self.get("profiling_enabled") == "true";
        let plugins_enabled = self.get("plugins_enabled") == "true";
        let workload_selection_present = !self.get("workload_selection").trim().is_empty() || self.get("template_kind") != "blank";

        match key {
            "expected_mcp_runtime_mode" => !self.get("expected_mcp_runtime").trim().is_empty(),
            "gunicorn_workers"
            | "gunicorn_timeout"
            | "gunicorn_graceful_timeout"
            | "gunicorn_keep_alive"
            | "gunicorn_max_requests"
            | "gunicorn_max_requests_jitter"
            | "gunicorn_backlog"
            | "gunicorn_preload_app"
            | "gunicorn_dev_mode" => http_server == "gunicorn",
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
            | "granian_log_level" => http_server == "granian",
            "uvicorn_workers"
            | "uvicorn_loop"
            | "uvicorn_http"
            | "uvicorn_backlog"
            | "uvicorn_timeout_keep_alive"
            | "uvicorn_limit_max_requests"
            | "uvicorn_log_level"
            | "uvicorn_dev_mode" => http_server == "uvicorn",
            "profiling_tools" | "py_spy" | "profiling_duration_seconds" | "profiling_required" => profiling_enabled,
            "defaults_plugins_snippet" | "scenario_plugins_snippet" => plugins_enabled,
            "workload_selection" | "fallback_endpoint" => true,
            "workload_endpoints" => workload_selection_present,
            _ => true,
        }
    }
}

struct App {
    action_index: usize,
    scenario_index: usize,
    scenarios: Vec<String>,
    run_path: String,
    extra_args: String,
    all: bool,
    clean: bool,
    mode: InputMode,
    status: String,
    should_quit: bool,
    generator: GeneratorState,
}

impl App {
    fn new(scenarios: Vec<String>) -> Self {
        Self {
            action_index: 0,
            scenario_index: 0,
            scenarios,
            run_path: String::new(),
            extra_args: String::new(),
            all: false,
            clean: true,
            mode: InputMode::Normal,
            status: "Use 1-8 or left/right for action, Enter to run, g=save template when Generate is selected.".to_string(),
            should_quit: false,
            generator: GeneratorState::new(),
        }
    }

    fn action(&self) -> Action {
        Action::ALL[self.action_index]
    }

    fn scenario(&self) -> &str {
        self.scenarios
            .get(self.scenario_index)
            .map(String::as_str)
            .unwrap_or("modular-design-300")
    }

    fn set_action_index(&mut self, index: usize) {
        self.action_index = index % Action::ALL.len();
        if !self.action().supports_all() {
            self.all = false;
        }
        if !self.action().supports_clean() {
            self.clean = false;
        }
        self.status = self.action().help().to_string();
    }

    fn move_action(&mut self, delta: isize) {
        let len = Action::ALL.len() as isize;
        let next = (self.action_index as isize + delta).rem_euclid(len) as usize;
        self.set_action_index(next);
    }

    fn move_scenario(&mut self, delta: isize) {
        if self.scenarios.is_empty() {
            return;
        }
        let len = self.scenarios.len() as isize;
        self.scenario_index = (self.scenario_index as isize + delta).rem_euclid(len) as usize;
        self.status = format!("Selected scenario: {}", self.scenario());
    }
}

fn main() -> AppResult<()> {
    let root = env::current_dir()?;
    let scenarios = discover_scenarios(&root)?;

    if env::args().nth(1).as_deref() == Some("--list-scenarios") {
        for scenario in scenarios {
            println!("{scenario}");
        }
        return Ok(());
    }

    let mut terminal = setup_terminal()?;
    let result = run_app(&mut terminal, App::new(scenarios), &root);
    restore_terminal(&mut terminal)?;
    result
}

fn discover_scenarios(root: &Path) -> AppResult<Vec<String>> {
    let mut scenarios = fs::read_dir(root.join("benchmarks/contextforge/scenarios"))?
        .filter_map(|entry| {
            let path = entry.ok()?.path();
            if path.extension().and_then(|value| value.to_str()) != Some("toml") {
                return None;
            }
            path.file_stem()
                .and_then(|value| value.to_str())
                .map(|value| value.to_string())
        })
        .collect::<Vec<_>>();
    scenarios.sort();
    Ok(scenarios)
}

fn setup_terminal() -> AppResult<Terminal<CrosstermBackend<Stdout>>> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, Hide)?;
    Ok(Terminal::new(CrosstermBackend::new(stdout))?)
}

fn restore_terminal(terminal: &mut Terminal<CrosstermBackend<Stdout>>) -> AppResult<()> {
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), Show, LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    Ok(())
}

fn run_app(
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
    mut app: App,
    root: &Path,
) -> AppResult<()> {
    while !app.should_quit {
        terminal.draw(|frame| draw(frame, &app))?;
        if event::poll(Duration::from_millis(100))? {
            if let Event::Key(key) = event::read()? {
                handle_key_event(&mut app, key, root, terminal)?;
            }
        }
    }
    Ok(())
}

fn handle_key_event(
    app: &mut App,
    key: KeyEvent,
    root: &Path,
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
) -> AppResult<()> {
    match app.mode {
        InputMode::Normal => handle_normal_mode(app, key, root, terminal),
        InputMode::EditRunPath => handle_text_input(app, key, InputMode::EditRunPath),
        InputMode::EditExtraArgs => handle_text_input(app, key, InputMode::EditExtraArgs),
        InputMode::EditGeneratorField => handle_text_input(app, key, InputMode::EditGeneratorField),
    }
}

fn handle_normal_mode(
    app: &mut App,
    key: KeyEvent,
    root: &Path,
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
) -> AppResult<()> {
    if app.action() == Action::Generate {
        return handle_generate_mode(app, key, root);
    }

    match key.code {
        KeyCode::Char('q') | KeyCode::Esc => app.should_quit = true,
        KeyCode::Left => app.move_action(-1),
        KeyCode::Right => app.move_action(1),
        KeyCode::Up | KeyCode::Char('k') => app.move_scenario(-1),
        KeyCode::Down | KeyCode::Char('j') => app.move_scenario(1),
        KeyCode::Char('1') => app.set_action_index(0),
        KeyCode::Char('2') => app.set_action_index(1),
        KeyCode::Char('3') => app.set_action_index(2),
        KeyCode::Char('4') => app.set_action_index(3),
        KeyCode::Char('5') => app.set_action_index(4),
        KeyCode::Char('6') => app.set_action_index(5),
        KeyCode::Char('7') => app.set_action_index(6),
        KeyCode::Char('8') => app.set_action_index(7),
        KeyCode::Char('a') => {
            if app.action().supports_all() {
                app.all = !app.all;
                app.status = format!("Run all scenarios: {}", yes_no(app.all));
            } else {
                app.status = "This action does not support all-scenario mode.".to_string();
            }
        }
        KeyCode::Char('c') => {
            if app.action().supports_clean() {
                app.clean = !app.clean;
                app.status = format!("Clean before launch: {}", yes_no(app.clean));
            } else {
                app.status = "This action does not use cleanup.".to_string();
            }
        }
        KeyCode::Char('p') => {
            if app.action().needs_run_path() {
                app.mode = InputMode::EditRunPath;
                app.status = "Editing run path. Type, Backspace to delete, Enter to finish.".to_string();
            } else {
                app.status = "Run path is only used for Report and Compare.".to_string();
            }
        }
        KeyCode::Char('e') => {
            app.mode = InputMode::EditExtraArgs;
            app.status = "Editing extra args. Type, Backspace to delete, Enter to finish.".to_string();
        }
        KeyCode::Enter | KeyCode::Char('r') => launch_action(app, root, terminal)?,
        _ => {}
    }
    Ok(())
}

fn handle_generate_mode(app: &mut App, key: KeyEvent, root: &Path) -> AppResult<()> {
    match key.code {
        KeyCode::Char('q') | KeyCode::Esc => app.should_quit = true,
        KeyCode::Left => app.move_action(-1),
        KeyCode::Right => app.move_action(1),
        KeyCode::Char('[') | KeyCode::PageUp => {
            app.generator.move_section(-1);
            app.status = format!("Section: {}", app.generator.selected_section_name());
        }
        KeyCode::Char(']') | KeyCode::PageDown => {
            app.generator.move_section(1);
            app.status = format!("Section: {}", app.generator.selected_section_name());
        }
        KeyCode::Up | KeyCode::Char('k') => app.generator.move_selected(-1),
        KeyCode::Down | KeyCode::Char('j') => app.generator.move_selected(1),
        KeyCode::Char('1') => app.set_action_index(0),
        KeyCode::Char('2') => app.set_action_index(1),
        KeyCode::Char('3') => app.set_action_index(2),
        KeyCode::Char('4') => app.set_action_index(3),
        KeyCode::Char('5') => app.set_action_index(4),
        KeyCode::Char('6') => app.set_action_index(5),
        KeyCode::Char('7') => app.set_action_index(6),
        KeyCode::Char('8') => app.set_action_index(7),
        KeyCode::Char('t') => {
            app.generator.toggle_or_cycle();
            app.status = format!("Updated {}", app.generator.selected_field().label);
        }
        KeyCode::Enter | KeyCode::Char('e') => match app.generator.selected_field().kind {
            GeneratorFieldKind::Text => {
                app.mode = InputMode::EditGeneratorField;
                app.status = format!("Editing {}", app.generator.selected_field().label);
            }
            GeneratorFieldKind::Bool | GeneratorFieldKind::Choice(_) => {
                app.generator.toggle_or_cycle();
                app.status = format!("Updated {}", app.generator.selected_field().label);
            }
        },
        KeyCode::Char('g') | KeyCode::Char('s') => {
            let path = save_generated_template(root, &mut app.scenarios, &app.generator)?;
            app.status = format!("Saved scenario template to {}", path.display());
        }
        _ => {}
    }
    Ok(())
}

fn handle_text_input(app: &mut App, key: KeyEvent, mode: InputMode) -> AppResult<()> {
    let buffer: &mut String = match mode {
        InputMode::EditRunPath => &mut app.run_path,
        InputMode::EditExtraArgs => &mut app.extra_args,
        InputMode::EditGeneratorField => &mut app.generator.selected_field_mut().value,
        InputMode::Normal => return Ok(()),
    };

    match key.code {
        KeyCode::Esc => {
            app.mode = InputMode::Normal;
            app.status = "Cancelled edit.".to_string();
        }
        KeyCode::Enter => {
            app.mode = InputMode::Normal;
            if mode == InputMode::EditGeneratorField {
                app.generator.ensure_visible_selection();
            }
            app.status = "Saved input.".to_string();
        }
        KeyCode::Backspace => {
            buffer.pop();
        }
        KeyCode::Char(c) => {
            buffer.push(c);
        }
        _ => {}
    }
    Ok(())
}

fn launch_action(
    app: &mut App,
    root: &Path,
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
) -> AppResult<()> {
    let mut command_spec = build_command(app, root)?;
    if app.clean && app.action().supports_clean() {
        suspend_tui(terminal)?;
        let cleanup_status = run_cleanup(root)?;
        if !cleanup_status.success() {
            println!("Cleanup exited with status: {cleanup_status}");
        }
        prompt_to_continue()?;
        resume_tui(terminal)?;
    }

    suspend_tui(terminal)?;
    println!("\nRunning: {}\n", format_command(&command_spec.command, &command_spec.args));
    let status = Command::new(&command_spec.command)
        .args(&command_spec.args)
        .envs(command_spec.env.drain(..))
        .current_dir(root)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .status()?;
    println!("\nCommand exited with status: {status}\n");
    prompt_to_continue()?;
    resume_tui(terminal)?;
    app.status = format!("Last command exited with status: {status}");
    Ok(())
}

struct CommandSpec {
    command: String,
    args: Vec<String>,
    env: Vec<(String, String)>,
}

fn build_command(app: &App, root: &Path) -> AppResult<CommandSpec> {
    let action = app.action();
    let mut args = python_prefix(root);
    args.extend(["-m".to_string(), "benchmarks.contextforge".to_string()]);

    match action {
        Action::List => args.push("--list".to_string()),
        Action::Run | Action::Validate | Action::Smoke | Action::CheckRuntime => {
            if app.all && action.supports_all() {
                args.push("--all".to_string());
            } else {
                args.push("--scenario".to_string());
                args.push(app.scenario().to_string());
            }
            match action {
                Action::Validate => args.push("--validate".to_string()),
                Action::Smoke => args.push("--smoke".to_string()),
                Action::CheckRuntime => args.push("--check-runtime".to_string()),
                _ => {}
            }
        }
        Action::Report => {
            if app.run_path.trim().is_empty() {
                return Err("Report needs a run path. Press 'p' to edit it.".into());
            }
            args.push("--report-run".to_string());
            args.push(app.run_path.trim().to_string());
        }
        Action::Compare => {
            if app.run_path.trim().is_empty() {
                return Err("Compare needs a run path. Press 'p' to edit it.".into());
            }
            args.push("--compare-run".to_string());
            args.push(app.run_path.trim().to_string());
        }
        Action::Generate => {
            return Err("Generate uses 'g' to save a scenario file, not Enter to run.".into());
        }
    }

    if !app.extra_args.trim().is_empty() {
        args.extend(shlex::split(&app.extra_args).ok_or("Could not parse extra args.")?);
    }

    Ok(CommandSpec {
        command: args.remove(0),
        args,
        env: vec![(
            "CONTAINER_RUNTIME".to_string(),
            env::var("CONTAINER_RUNTIME").unwrap_or_else(|_| "podman".to_string()),
        )],
    })
}

fn python_prefix(root: &Path) -> Vec<String> {
    let venv_python = root.join(".venv/bin/python");
    if venv_python.exists() {
        return vec![venv_python.display().to_string()];
    }
    if command_exists("uv") {
        return vec!["uv".to_string(), "run".to_string(), "python".to_string()];
    }
    vec!["python3".to_string()]
}

fn run_cleanup(root: &Path) -> AppResult<std::process::ExitStatus> {
    let script = r#"
import os
import shutil
import subprocess
from pathlib import Path

engine = os.environ.get("CONTAINER_RUNTIME", "podman").strip() or "podman"
if not shutil.which(engine):
    engine = "docker" if shutil.which("docker") else "podman"

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None

removed_pods = 0
removed_containers = 0
if engine == "podman":
    pod_list = run(["podman", "pod", "ps", "-a", "--format", "{{.Name}}"])
    if pod_list:
        for pod in [line.strip() for line in (pod_list.stdout or "").splitlines() if line.strip().startswith("bench-")]:
            result = run(["podman", "pod", "rm", "-f", pod])
            if result and result.returncode == 0:
                removed_pods += 1

container_list = run([engine, "ps", "-a", "--format", "{{.Names}}"])
if container_list:
    for name in [line.strip() for line in (container_list.stdout or "").splitlines() if line.strip().startswith("bench-")]:
        result = run([engine, "rm", "-f", name])
        if result and result.returncode == 0:
            removed_containers += 1

reports_dir = Path("reports/benchmarks")
for pattern in [
    "_runtime_staging/all-scenarios_*",
    "_runtime_staging/modular-design-300_*",
    "_runtime_staging/a2a-invoke-300_*",
    "_runtime_staging/shared_stacks",
    "_runtime_staging/source_checkouts",
    "all-scenarios_*",
    "modular-design-300_*",
    "a2a-invoke-300_*",
]:
    for path in reports_dir.glob(pattern):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)

print(f"Removed {removed_pods} benchmark pod(s) and {removed_containers} benchmark container(s).")
"#;

    Ok(Command::new("python3")
        .arg("-c")
        .arg(script)
        .env(
            "CONTAINER_RUNTIME",
            env::var("CONTAINER_RUNTIME").unwrap_or_else(|_| "podman".to_string()),
        )
        .current_dir(root)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .status()?)
}

fn save_generated_template(root: &Path, scenarios: &mut Vec<String>, generator: &GeneratorState) -> AppResult<PathBuf> {
    let file_stem = sanitize_file_stem(generator.get("file_stem"));
    let target = root
        .join("benchmarks/contextforge/scenarios")
        .join(format!("{file_stem}.toml"));
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&target, generate_template_toml(generator))?;
    *scenarios = discover_scenarios(root)?;
    Ok(target)
}

fn sanitize_file_stem(value: &str) -> String {
    let mut stem = value
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '-' })
        .collect::<String>()
        .trim_matches('-')
        .to_string();
    if stem.is_empty() {
        stem = "generated-scenario".to_string();
    }
    stem
}

fn parse_pipe_lines(value: &str) -> Vec<String> {
    value
        .split('|')
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(ToString::to_string)
        .collect()
}

fn parse_csv_items(value: &str) -> Vec<String> {
    value
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .map(ToString::to_string)
        .collect()
}

fn quoted_csv(value: &str) -> String {
    parse_csv_items(value)
        .into_iter()
        .map(|item| format!("\"{}\"", escape_toml(&item)))
        .collect::<Vec<_>>()
        .join(", ")
}

fn push_string_line(lines: &mut Vec<String>, key: &str, value: &str) {
    lines.push(format!("{key} = \"{}\"", escape_toml(value)));
}

fn push_bool_line(lines: &mut Vec<String>, key: &str, value: &str) {
    lines.push(format!("{key} = {}", if value == "true" { "true" } else { "false" }));
}

fn push_scalar_line(lines: &mut Vec<String>, key: &str, value: &str) {
    lines.push(format!("{key} = {value}"));
}

fn push_optional_string_line(lines: &mut Vec<String>, key: &str, value: &str) {
    if !value.trim().is_empty() {
        push_string_line(lines, key, value.trim());
    }
}

fn push_optional_scalar_line(lines: &mut Vec<String>, key: &str, value: &str) {
    if !value.trim().is_empty() {
        push_scalar_line(lines, key, value.trim());
    }
}

fn push_optional_array_line(lines: &mut Vec<String>, key: &str, value: &str) {
    let items = quoted_csv(value);
    if !items.is_empty() {
        lines.push(format!("{key} = [{items}]"));
    }
}

fn append_optional_block(lines: &mut Vec<String>, title: &str, raw: &str) {
    let entries = parse_pipe_lines(raw);
    if !entries.is_empty() {
        lines.push(String::new());
        lines.push(title.to_string());
        lines.extend(entries);
    }
}

fn append_runtime_block_from_fields(lines: &mut Vec<String>, title: &str, fields: &[(&str, &str, &str)]) {
    let mut block = Vec::new();
    for (key, value, kind) in fields {
        if value.trim().is_empty() {
            continue;
        }
        match *kind {
            "bool" => push_bool_line(&mut block, key, value),
            "string" => push_string_line(&mut block, key, value.trim()),
            _ => push_scalar_line(&mut block, key, value.trim()),
        }
    }
    if !block.is_empty() {
        lines.push(String::new());
        lines.push(title.to_string());
        lines.extend(block);
    }
}

fn template_endpoints(generator: &GeneratorState) -> String {
    let custom = parse_pipe_lines(generator.get("workload_endpoints"));
    if !custom.is_empty() {
        return format!(
            "[defaults.load.workload]\nselection = \"{}\"\nfallback_endpoint = \"{}\"\n\n{}",
            escape_toml(generator.get("workload_selection")),
            escape_toml(generator.get("fallback_endpoint")),
            custom.join("\n")
        );
    }

    match generator.get("template_kind") {
        "a2a" => format!(
            r#"[defaults.load.workload]
selection = "{}"
fallback_endpoint = "{}"

[defaults.load.workload.endpoints."/health"]
enabled = false

[defaults.load.workload.endpoints."/servers"]
enabled = false

[defaults.load.workload.endpoints."/a2a"]
enabled = false

[defaults.load.workload.endpoints."/a2a/a2a-echo-agent/invoke"]
enabled = true
weight = 1
"#,
            generator.get("workload_selection"),
            generator.get("fallback_endpoint")
        ),
        "mcp" => format!(
            r#"[defaults.load.workload]
selection = "{}"
fallback_endpoint = "{}"

[defaults.load.workload.endpoints."/health"]
enabled = false

[defaults.load.workload.endpoints."/ready"]
enabled = false

[defaults.load.workload.endpoints."/admin/plugins"]
enabled = false

[defaults.load.workload.endpoints."/servers"]
enabled = true
weight = 2

[defaults.load.workload.endpoints."/mcp tools/list"]
enabled = true
weight = 6

[defaults.load.workload.endpoints."/mcp tools/call fast-time-get-system-time"]
enabled = true
weight = 14

[defaults.load.workload.endpoints."/mcp tools/call fast-time-convert-time"]
enabled = true
weight = 12
"#,
            generator.get("workload_selection"),
            generator.get("fallback_endpoint")
        ),
        _ => format!(
            r#"[defaults.load.workload]
# selection = "{}"
fallback_endpoint = "{}"

# Add endpoint tables as needed:
# [defaults.load.workload.endpoints."/health"]
# enabled = true
# weight = 1
"#,
            generator.get("workload_selection"),
            generator.get("fallback_endpoint")
        ),
    }
}

fn generate_template_toml(generator: &GeneratorState) -> String {
    let mut lines = Vec::new();

    lines.push("[suite]".to_string());
    push_string_line(&mut lines, "name", generator.get("suite_name"));
    push_string_line(&mut lines, "description", generator.get("suite_description"));
    push_string_line(&mut lines, "output_root", generator.get("output_root"));
    push_bool_line(&mut lines, "continue_on_failure", generator.get("continue_on_failure"));
    push_bool_line(&mut lines, "save_intermediate_artifacts", generator.get("save_intermediate_artifacts"));
    push_bool_line(&mut lines, "flamegraph_enabled", generator.get("flamegraph_enabled"));
    push_optional_string_line(&mut lines, "baseline_run", generator.get("baseline_run"));
    push_optional_scalar_line(&mut lines, "baseline_rps_drop_pct", generator.get("baseline_rps_drop_pct"));
    push_optional_scalar_line(&mut lines, "baseline_p95_regression_pct", generator.get("baseline_p95_regression_pct"));
    push_optional_scalar_line(&mut lines, "baseline_failure_increase", generator.get("baseline_failure_increase"));

    lines.push(String::new());
    lines.push("[defaults.setup]".to_string());
    push_string_line(&mut lines, "target_kind", generator.get("target_kind"));
    push_string_line(&mut lines, "auth_mode", generator.get("auth_mode"));
    push_bool_line(&mut lines, "plugins_enabled", generator.get("plugins_enabled"));
    push_optional_string_line(&mut lines, "expected_mcp_runtime", generator.get("expected_mcp_runtime"));
    push_optional_string_line(&mut lines, "expected_mcp_runtime_mode", generator.get("expected_mcp_runtime_mode"));
    push_optional_string_line(&mut lines, "expected_a2a_runtime", generator.get("expected_a2a_runtime"));

    lines.push(String::new());
    lines.push("[defaults.build]".to_string());
    push_bool_line(&mut lines, "rust_plugins", generator.get("rust_plugins"));
    push_bool_line(&mut lines, "profiling_image", generator.get("profiling_image"));
    push_string_line(&mut lines, "container_file", generator.get("container_file"));
    push_string_line(&mut lines, "image_name", generator.get("image_name"));
    push_string_line(&mut lines, "image_tag", generator.get("image_tag"));
    push_string_line(&mut lines, "rebuild_policy", generator.get("rebuild_policy"));
    push_string_line(&mut lines, "repo_url", generator.get("repo_url"));
    push_string_line(&mut lines, "git_ref", generator.get("git_ref"));
    push_optional_string_line(&mut lines, "git_commit", generator.get("git_commit"));
    append_optional_block(&mut lines, "[defaults.build.args]", generator.get("build_args"));

    lines.push(String::new());
    lines.push("[defaults.runtime]".to_string());
    push_string_line(&mut lines, "http_server", generator.get("http_server"));
    push_string_line(&mut lines, "host", generator.get("runtime_host"));
    push_string_line(&mut lines, "transport_type", generator.get("transport_type"));

    lines.push(String::new());
    lines.push("[defaults.runtime.gunicorn]".to_string());
    push_scalar_line(&mut lines, "workers", generator.get("gunicorn_workers"));
    push_scalar_line(&mut lines, "timeout", generator.get("gunicorn_timeout"));
    push_scalar_line(&mut lines, "graceful_timeout", generator.get("gunicorn_graceful_timeout"));
    push_scalar_line(&mut lines, "keep_alive", generator.get("gunicorn_keep_alive"));
    push_scalar_line(&mut lines, "max_requests", generator.get("gunicorn_max_requests"));
    push_scalar_line(&mut lines, "max_requests_jitter", generator.get("gunicorn_max_requests_jitter"));
    push_scalar_line(&mut lines, "backlog", generator.get("gunicorn_backlog"));
    push_bool_line(&mut lines, "preload_app", generator.get("gunicorn_preload_app"));
    push_bool_line(&mut lines, "dev_mode", generator.get("gunicorn_dev_mode"));
    append_runtime_block_from_fields(
        &mut lines,
        "[defaults.runtime.granian]",
        &[
            ("workers", generator.get("granian_workers"), "number"),
            ("runtime_mode", generator.get("granian_runtime_mode"), "string"),
            ("runtime_threads", generator.get("granian_runtime_threads"), "number"),
            ("blocking_threads", generator.get("granian_blocking_threads"), "number"),
            ("http", generator.get("granian_http"), "number"),
            ("loop", generator.get("granian_loop"), "string"),
            ("task_impl", generator.get("granian_task_impl"), "string"),
            ("http1_pipeline_flush", generator.get("granian_http1_pipeline_flush"), "bool"),
            ("http1_buffer_size", generator.get("granian_http1_buffer_size"), "number"),
            ("backlog", generator.get("granian_backlog"), "number"),
            ("backpressure", generator.get("granian_backpressure"), "number"),
            ("respawn_failed", generator.get("granian_respawn_failed"), "bool"),
            ("workers_lifetime", generator.get("granian_workers_lifetime"), "number"),
            ("workers_max_rss", generator.get("granian_workers_max_rss"), "number"),
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
            ("timeout_keep_alive", generator.get("uvicorn_timeout_keep_alive"), "number"),
            ("limit_max_requests", generator.get("uvicorn_limit_max_requests"), "number"),
            ("log_level", generator.get("uvicorn_log_level"), "string"),
            ("dev_mode", generator.get("uvicorn_dev_mode"), "bool"),
        ],
    );

    lines.push(String::new());
    lines.push("[defaults.gateway]".to_string());
    push_bool_line(&mut lines, "trust_proxy_auth", generator.get("trust_proxy_auth"));
    push_bool_line(&mut lines, "disable_access_log", generator.get("disable_access_log"));
    push_bool_line(&mut lines, "templates_auto_reload", generator.get("templates_auto_reload"));
    push_bool_line(&mut lines, "structured_logging_database_enabled", generator.get("structured_logging_database_enabled"));
    push_bool_line(&mut lines, "sqlalchemy_echo", generator.get("sqlalchemy_echo"));
    push_string_line(&mut lines, "log_level", generator.get("gateway_log_level"));
    append_optional_block(&mut lines, "[defaults.gateway.environment]", generator.get("gateway_environment"));

    lines.push(String::new());
    lines.push("[defaults.load]".to_string());
    push_string_line(&mut lines, "locustfile", generator.get("locustfile"));
    push_optional_string_line(&mut lines, "user_class", generator.get("user_class"));
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
    push_string_line(&mut lines, "target_service", generator.get("target_service"));
    append_optional_block(&mut lines, "[defaults.load.env]", generator.get("load_env"));

    lines.push(String::new());
    lines.push(template_endpoints(generator));

    lines.push(String::new());
    lines.push("[defaults.measurement]".to_string());
    push_scalar_line(&mut lines, "warmup_seconds", generator.get("warmup_seconds"));
    push_scalar_line(&mut lines, "measure_seconds", generator.get("measure_seconds"));
    push_scalar_line(&mut lines, "profile_seconds", generator.get("profile_seconds"));
    push_scalar_line(&mut lines, "cooldown_seconds", generator.get("cooldown_seconds"));

    lines.push(String::new());
    lines.push("[defaults.requests]".to_string());
    push_optional_array_line(&mut lines, "enabled_groups", generator.get("enabled_groups"));
    push_optional_array_line(&mut lines, "disabled_groups", generator.get("disabled_groups"));
    push_optional_array_line(&mut lines, "enabled_endpoints", generator.get("enabled_endpoints"));
    push_optional_array_line(&mut lines, "disabled_endpoints", generator.get("disabled_endpoints"));
    push_optional_array_line(&mut lines, "enabled_tags", generator.get("enabled_tags"));
    push_optional_array_line(&mut lines, "disabled_tags", generator.get("disabled_tags"));
    push_bool_line(&mut lines, "include_admin_endpoints", generator.get("include_admin_endpoints"));
    push_bool_line(&mut lines, "include_mcp_endpoints", generator.get("include_mcp_endpoints"));
    push_bool_line(&mut lines, "include_resource_endpoints", generator.get("include_resource_endpoints"));
    push_bool_line(&mut lines, "include_prompt_endpoints", generator.get("include_prompt_endpoints"));
    push_bool_line(&mut lines, "include_tool_endpoints", generator.get("include_tool_endpoints"));

    lines.push(String::new());
    lines.push("[defaults.profiling]".to_string());
    push_bool_line(&mut lines, "enabled", generator.get("profiling_enabled"));
    let profiling_tools = quoted_csv(generator.get("profiling_tools"));
    lines.push(format!("tools = [{}]", profiling_tools));
    push_bool_line(&mut lines, "py_spy", generator.get("py_spy"));
    push_scalar_line(&mut lines, "duration_seconds", generator.get("profiling_duration_seconds"));
    push_bool_line(&mut lines, "required", generator.get("profiling_required"));

    lines.push(String::new());
    lines.push("[defaults.execution]".to_string());
    push_bool_line(&mut lines, "retry_enabled", generator.get("retry_enabled"));
    push_scalar_line(&mut lines, "max_attempts", generator.get("max_attempts"));
    push_bool_line(&mut lines, "capture_logs", generator.get("capture_logs"));
    push_bool_line(&mut lines, "save_raw_results", generator.get("save_raw_results"));
    push_bool_line(&mut lines, "reuse_stack", generator.get("reuse_stack"));
    append_optional_block(&mut lines, "[defaults.plugins.example-plugin]", generator.get("defaults_plugins_snippet"));

    lines.push(String::new());
    lines.push("[[scenario]]".to_string());
    push_string_line(&mut lines, "name", generator.get("scenario_name"));
    push_string_line(&mut lines, "description", generator.get("scenario_description"));
    push_string_line(&mut lines, "scenario_type", generator.get("scenario_type"));
    append_optional_block(&mut lines, "[scenario.setup]", generator.get("scenario_setup_snippet"));
    append_optional_block(&mut lines, "[scenario.build]", generator.get("scenario_build_snippet"));
    append_optional_block(&mut lines, "[scenario.runtime]", generator.get("scenario_runtime_snippet"));
    append_optional_block(&mut lines, "[scenario.gateway]", generator.get("scenario_gateway_snippet"));
    append_optional_block(&mut lines, "[scenario.load]", generator.get("scenario_load_snippet"));
    append_optional_block(&mut lines, "[scenario.measurement]", generator.get("scenario_measurement_snippet"));
    append_optional_block(&mut lines, "[scenario.requests]", generator.get("scenario_requests_snippet"));
    append_optional_block(&mut lines, "[scenario.profiling]", generator.get("scenario_profiling_snippet"));
    append_optional_block(&mut lines, "[scenario.execution]", generator.get("scenario_execution_snippet"));
    append_optional_block(&mut lines, "[scenario.plugins.example-plugin]", generator.get("scenario_plugins_snippet"));

    lines.join("\n") + "\n"
}

fn escape_toml(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

fn suspend_tui(terminal: &mut Terminal<CrosstermBackend<Stdout>>) -> AppResult<()> {
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), Show, LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    Ok(())
}

fn resume_tui(terminal: &mut Terminal<CrosstermBackend<Stdout>>) -> AppResult<()> {
    enable_raw_mode()?;
    execute!(terminal.backend_mut(), EnterAlternateScreen, Hide)?;
    Ok(())
}

fn prompt_to_continue() -> AppResult<()> {
    // Previously this paused for user input:
    // println!("Press Enter to return to the benchmark console...");
    // io::stdin().read_line(&mut String::new())?;
    // The console now resumes immediately after commands complete.
    Ok(())
}

fn command_exists(name: &str) -> bool {
    env::var_os("PATH")
        .map(|paths| env::split_paths(&paths).any(|path| path.join(name).exists()))
        .unwrap_or(false)
}

fn format_command(command: &str, args: &[String]) -> String {
    std::iter::once(command.to_string())
        .chain(args.iter().cloned())
        .collect::<Vec<_>>()
        .join(" ")
}

fn yes_no(value: bool) -> &'static str {
    if value { "yes" } else { "no" }
}

fn draw(frame: &mut ratatui::Frame<'_>, app: &App) {
    let chunks = if app.action() == Action::Generate {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Min(16),
                Constraint::Length(4),
            ])
            .split(frame.area())
    } else {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(14),
                Constraint::Min(10),
                Constraint::Length(4),
            ])
            .split(frame.area())
    };

    let header = Paragraph::new(vec![
        Line::from(Span::styled(
            "ContextForge Benchmark Console",
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
        )),
        Line::from(format!("Mode: {}", app.mode.label())),
    ])
    .block(Block::default().borders(Borders::ALL).title("Launcher"));
    frame.render_widget(header, chunks[0]);

    let tabs = Tabs::new(
        Action::ALL
            .iter()
            .enumerate()
            .map(|(index, action)| Line::from(format!("{} {}", index + 1, action.label())))
            .collect::<Vec<_>>(),
    )
    .select(app.action_index)
    .block(Block::default().borders(Borders::ALL).title("Actions"))
    .highlight_style(
        Style::default()
            .fg(Color::Black)
            .bg(Color::Cyan)
            .add_modifier(Modifier::BOLD),
    );
    frame.render_widget(tabs, chunks[1]);

    if app.action() == Action::Generate {
        draw_generator_sections(frame, chunks[2], app);
        let body = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(62), Constraint::Percentage(38)])
            .split(chunks[3]);
        let left = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(10), Constraint::Length(10)])
            .split(body[0]);
        draw_generator_fields(frame, left[0], app);
        draw_generator_selection(frame, left[1], app);
        draw_generator_reference(frame, body[1], app);
    } else {
        let body = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(40), Constraint::Percentage(60)])
            .split(chunks[2]);
        draw_scenarios(frame, body[0], app);
        draw_selection(frame, body[1], app);
        draw_preview(frame, chunks[3], app);
    }
    draw_help(frame, chunks[4], app);
}

fn draw_generator_sections(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let tabs = Tabs::new(
        GeneratorState::sections()
            .iter()
            .map(|section| Line::from((*section).to_string()))
            .collect::<Vec<_>>(),
    )
    .select(app.generator.selected_section)
    .block(Block::default().borders(Borders::ALL).title("Generator Sections"))
    .highlight_style(
        Style::default()
            .fg(Color::Black)
            .bg(Color::Green)
            .add_modifier(Modifier::BOLD),
    );
    frame.render_widget(tabs, area);
}

fn draw_scenarios(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let items = app
        .scenarios
        .iter()
        .map(|scenario| ListItem::new(scenario.clone()))
        .collect::<Vec<_>>();
    let list = List::new(items)
        .block(Block::default().borders(Borders::ALL).title("Scenarios"))
        .highlight_style(
            Style::default()
                .fg(Color::Black)
                .bg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )
        .highlight_symbol(">> ");
    let mut state = ListState::default();
    state.select(Some(app.scenario_index));
    frame.render_stateful_widget(list, area, &mut state);
}

fn draw_selection(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let lines = vec![
        line_pair("Action", app.action().label()),
        line_pair(
            "Scenario",
            if app.action().supports_scenario() {
                app.scenario()
            } else {
                "(not used)"
            },
        ),
        line_pair(
            "Run all",
            if app.action().supports_all() {
                yes_no(app.all)
            } else {
                "(not used)"
            },
        ),
        line_pair(
            "Clean first",
            if app.action().supports_clean() {
                yes_no(app.clean)
            } else {
                "(not used)"
            },
        ),
        line_pair(
            "Run path",
            if app.run_path.is_empty() {
                if app.action().needs_run_path() {
                    "press 'p' to set"
                } else {
                    "(not used)"
                }
            } else {
                &app.run_path
            },
        ),
        line_pair(
            "Extra args",
            if app.extra_args.is_empty() {
                "press 'e' to edit"
            } else {
                &app.extra_args
            },
        ),
    ];
    let widget = Paragraph::new(lines)
        .block(Block::default().borders(Borders::ALL).title("Selection"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_preview(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let mut lines = vec![Line::from(Span::styled(app.action().help(), Style::default().fg(Color::Cyan)))];
    match build_command(app, Path::new(".")) {
        Ok(command) => {
            lines.push(Line::from(""));
            lines.push(Line::from(Span::styled("Command preview", Style::default().add_modifier(Modifier::BOLD))));
            lines.push(Line::from(format_command(&command.command, &command.args)));
        }
        Err(error) => {
            lines.push(Line::from(""));
            lines.push(Line::from(Span::styled(format!("Configuration error: {error}"), Style::default().fg(Color::Red))));
        }
    }
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(format!("Status: {}", app.status), Style::default().fg(Color::Magenta))));
    let widget = Paragraph::new(lines)
        .block(Block::default().borders(Borders::ALL).title("Preview"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_generator_fields(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let visible = app.generator.visible_indices();
    let items = visible
        .iter()
        .map(|index| {
            let field = &app.generator.fields[*index];
            ListItem::new(format!("{}{}: {}", generator_indent(field.key), field.label, field.value))
        })
        .collect::<Vec<_>>();
    let visible_pos = visible
        .iter()
        .position(|index| *index == app.generator.selected)
        .unwrap_or(0);
    let list = List::new(items)
        .block(Block::default().borders(Borders::ALL).title(format!(
            "{} Fields ({}/{} visible, {} total)",
            app.generator.selected_section_name(),
            visible_pos + 1,
            visible.len(),
            app.generator.fields.len()
        )))
        .highlight_style(
            Style::default()
                .fg(Color::Black)
                .bg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )
        .highlight_symbol(">> ");
    let mut state = ListState::default();
    state.select(Some(visible_pos));
    frame.render_stateful_widget(list, area, &mut state);
}

fn draw_generator_selection(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let field = app.generator.selected_field();
    let lines = vec![
        line_pair("Section Filter", app.generator.selected_section_name()),
        line_pair("Section", generator_section(field.key)),
        line_pair("Config Key", generator_config_path(field.key)),
        line_pair("Field", field.label),
        line_pair("Value", &field.value),
        line_pair("Kind", match field.kind { GeneratorFieldKind::Text => "text", GeneratorFieldKind::Bool => "bool", GeneratorFieldKind::Choice(_) => "choice" }),
        line_pair("Schema", field.help),
        line_pair("Format", generator_format_hint(field.key)),
        line_pair("Visible Because", generator_visibility_note(field.key)),
        line_pair("Edit", "Enter/e edits, t toggles bool/choice"),
        line_pair("Save", "g or s writes the scenario file"),
    ];
    let widget = Paragraph::new(lines)
        .block(Block::default().borders(Borders::ALL).title("Template Builder"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_generator_reference(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let field = app.generator.selected_field();
    let detail = format!(
        "Option:\n{} [{}]\n\nWhat it does:\n{}\n\nWhen to change it:\n{}\n\nAccepted values:\n{}\n\nVisibility:\n{}\n\nExample:\n{}",
        field.label,
        generator_config_path(field.key),
        generator_explanation(field.key),
        generator_change_reason(field.key),
        generator_format_hint(field.key),
        generator_visibility_note(field.key),
        generator_example(field.key)
    );
    let widget = Paragraph::new(detail)
        .block(Block::default().borders(Borders::ALL).title("Option Guide"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn generator_indent(key: &str) -> &'static str {
    match key {
        "gunicorn_workers"
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
        | "profiling_tools"
        | "py_spy"
        | "profiling_duration_seconds"
        | "profiling_required" => "  ",
        _ => "",
    }
}

fn line_pair<'a>(label: &'a str, value: &'a str) -> Line<'a> {
    Line::from(vec![
        Span::styled(format!("{label}: "), Style::default().fg(Color::White)),
        Span::styled(value.to_string(), Style::default().fg(Color::Green)),
    ])
}

fn generator_section(key: &str) -> &'static str {
    match key {
        "file_stem" | "template_kind" => "Generator",
        "suite_name" | "suite_description" | "output_root" | "continue_on_failure" | "save_intermediate_artifacts" | "flamegraph_enabled" | "baseline_run" | "baseline_rps_drop_pct" | "baseline_p95_regression_pct" | "baseline_failure_increase" => "Suite",
        "scenario_name" | "scenario_description" | "scenario_type" => "Scenario",
        "target_kind" | "auth_mode" | "plugins_enabled" | "expected_mcp_runtime" | "expected_mcp_runtime_mode" | "expected_a2a_runtime" | "scenario_setup_snippet" => "Setup",
        "repo_url" | "git_ref" | "git_commit" | "rust_plugins" | "profiling_image" | "container_file" | "image_name" | "image_tag" | "rebuild_policy" | "build_args" | "scenario_build_snippet" => "Build",
        "http_server" | "runtime_host" | "transport_type" | "gunicorn_workers" | "gunicorn_timeout" | "gunicorn_graceful_timeout" | "gunicorn_keep_alive" | "gunicorn_max_requests" | "gunicorn_max_requests_jitter" | "gunicorn_backlog" | "gunicorn_preload_app" | "gunicorn_dev_mode" | "granian_workers" | "granian_runtime_mode" | "granian_runtime_threads" | "granian_blocking_threads" | "granian_http" | "granian_loop" | "granian_task_impl" | "granian_http1_pipeline_flush" | "granian_http1_buffer_size" | "granian_backlog" | "granian_backpressure" | "granian_respawn_failed" | "granian_workers_lifetime" | "granian_workers_max_rss" | "granian_dev_mode" | "granian_log_level" | "uvicorn_workers" | "uvicorn_loop" | "uvicorn_http" | "uvicorn_backlog" | "uvicorn_timeout_keep_alive" | "uvicorn_limit_max_requests" | "uvicorn_log_level" | "uvicorn_dev_mode" | "scenario_runtime_snippet" => "Runtime",
        "trust_proxy_auth" | "disable_access_log" | "templates_auto_reload" | "structured_logging_database_enabled" | "sqlalchemy_echo" | "gateway_log_level" | "gateway_environment" | "scenario_gateway_snippet" => "Gateway",
        "target_service" | "locustfile" | "user_class" | "headless" | "only_summary" | "html_report" | "users" | "spawn_rate" | "run_time" | "request_count" | "load_host" | "seed" | "tags" | "exclude_tags" | "load_extra_args" | "load_env" | "workload_selection" | "fallback_endpoint" | "workload_endpoints" | "scenario_load_snippet" => "Load",
        "warmup_seconds" | "measure_seconds" | "profile_seconds" | "cooldown_seconds" | "scenario_measurement_snippet" => "Measurement",
        "enabled_groups" | "disabled_groups" | "enabled_endpoints" | "disabled_endpoints" | "enabled_tags" | "disabled_tags" | "include_admin_endpoints" | "include_mcp_endpoints" | "include_resource_endpoints" | "include_prompt_endpoints" | "include_tool_endpoints" | "scenario_requests_snippet" => "Requests",
        "profiling_enabled" | "profiling_tools" | "py_spy" | "profiling_duration_seconds" | "profiling_required" | "scenario_profiling_snippet" => "Profiling",
        "retry_enabled" | "max_attempts" | "capture_logs" | "save_raw_results" | "reuse_stack" | "scenario_execution_snippet" => "Execution",
        "defaults_plugins_snippet" | "scenario_plugins_snippet" => "Plugins",
        _ => "Other",
    }
}

fn generator_config_path(key: &str) -> &'static str {
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
        "repo_url" => "defaults.build.repo_url",
        "git_ref" => "defaults.build.git_ref",
        "git_commit" => "defaults.build.git_commit",
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
        "structured_logging_database_enabled" => "defaults.gateway.structured_logging_database_enabled",
        "sqlalchemy_echo" => "defaults.gateway.sqlalchemy_echo",
        "gateway_log_level" => "defaults.gateway.log_level",
        "gateway_environment" => "defaults.gateway.environment",
        "target_service" => "defaults.load.target_service",
        "locustfile" => "defaults.load.locustfile",
        "user_class" => "defaults.load.user_class",
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
        "py_spy" => "defaults.profiling.py_spy",
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

fn generator_format_hint(key: &str) -> &'static str {
    match key {
        "template_kind" => "blank, mcp, or a2a",
        "target_kind" => "gateway or agent",
        "auth_mode" => "jwt, basic, or none",
        "rebuild_policy" => "never, missing, or always",
        "http_server" => "gunicorn, granian, or uvicorn",
        "transport_type" => "streamablehttp, sse, or websocket",
        "target_service" => "nginx or gateway",
        "continue_on_failure" | "save_intermediate_artifacts" | "flamegraph_enabled" | "plugins_enabled" | "rust_plugins" | "profiling_image" | "gunicorn_preload_app" | "gunicorn_dev_mode" | "granian_http1_pipeline_flush" | "granian_respawn_failed" | "granian_dev_mode" | "trust_proxy_auth" | "disable_access_log" | "templates_auto_reload" | "structured_logging_database_enabled" | "sqlalchemy_echo" | "headless" | "only_summary" | "html_report" | "include_admin_endpoints" | "include_mcp_endpoints" | "include_resource_endpoints" | "include_prompt_endpoints" | "include_tool_endpoints" | "profiling_enabled" | "py_spy" | "profiling_required" | "retry_enabled" | "capture_logs" | "save_raw_results" | "reuse_stack" | "uvicorn_dev_mode" => "true or false",
        "tags" | "exclude_tags" | "enabled_groups" | "disabled_groups" | "enabled_endpoints" | "disabled_endpoints" | "enabled_tags" | "disabled_tags" | "profiling_tools" | "load_extra_args" => "comma-separated list",
        "build_args" | "gateway_environment" | "load_env" | "workload_endpoints" | "defaults_plugins_snippet" | "scenario_setup_snippet" | "scenario_build_snippet" | "scenario_runtime_snippet" | "scenario_gateway_snippet" | "scenario_load_snippet" | "scenario_measurement_snippet" | "scenario_requests_snippet" | "scenario_profiling_snippet" | "scenario_execution_snippet" | "scenario_plugins_snippet" => "raw TOML lines separated by ' | '",
        "users" | "spawn_rate" | "warmup_seconds" | "measure_seconds" | "profile_seconds" | "cooldown_seconds" | "max_attempts" | "gunicorn_workers" | "gunicorn_timeout" | "gunicorn_graceful_timeout" | "gunicorn_keep_alive" | "gunicorn_max_requests" | "gunicorn_max_requests_jitter" | "gunicorn_backlog" | "granian_workers" | "granian_runtime_threads" | "granian_blocking_threads" | "granian_http1_buffer_size" | "granian_backlog" | "granian_backpressure" | "granian_workers_lifetime" | "granian_workers_max_rss" | "uvicorn_workers" | "uvicorn_backlog" | "uvicorn_timeout_keep_alive" | "uvicorn_limit_max_requests" | "request_count" | "profiling_duration_seconds" => "integer number",
        "baseline_rps_drop_pct" | "baseline_p95_regression_pct" | "baseline_failure_increase" => "numeric threshold",
        "run_time" => "duration like 180s or 5m",
        "git_commit" => "full or short git sha",
        "file_stem" => "filename stem without .toml",
        _ => "plain text",
    }
}

fn generator_explanation(key: &str) -> &'static str {
    match key {
        "file_stem" => "Sets the scenario file name written into benchmarks/contextforge/scenarios so the template becomes a committed, repeatable scenario.",
        "template_kind" => "Seeds the workload block with a sensible starting shape. Blank leaves workload routing mostly open, mcp favors MCP-heavy endpoints, and a2a targets the A2A invoke path.",
        "baseline_run" | "baseline_rps_drop_pct" | "baseline_p95_regression_pct" | "baseline_failure_increase" => "These suite baseline controls let the run compare itself against a previous saved run and flag regressions in throughput, latency, or failures.",
        "repo_url" | "git_ref" | "git_commit" => "These build source fields control reproducibility. Use repo_url plus git_ref or git_commit so the benchmark can re-create the exact code under test.",
        "build_args" => "Build args become entries under defaults.build.args and are passed into the benchmark image build. Use them for build-time toggles like enabling Rust paths.",
        "runtime_host" => "This is the bind host used by the app process inside the benchmark container stack.",
        "gateway_environment" | "load_env" => "These are environment variable maps written as TOML key-value lines. They let you inject runtime knobs without changing source code.",
        "workload_endpoints" => "This defines explicit endpoint weights and enablement inside defaults.load.workload.endpoints. Use it when you want precise traffic mixes instead of the built-in presets.",
        "defaults_plugins_snippet" | "scenario_plugins_snippet" => "Plugin configuration is open-ended because plugin names vary. These fields let you define per-plugin tables while still staying inside the scenario generator.",
        "scenario_setup_snippet" | "scenario_build_snippet" | "scenario_runtime_snippet" | "scenario_gateway_snippet" | "scenario_load_snippet" | "scenario_measurement_snippet" | "scenario_requests_snippet" | "scenario_profiling_snippet" | "scenario_execution_snippet" => "Scenario override blocks let one [[scenario]] diverge from the defaults table without duplicating the entire suite config.",
        _ if key.starts_with("gunicorn_") => "This tunes the Gunicorn runtime block used when http_server is set to gunicorn. It affects concurrency, connection handling, recycling, and developer-mode behavior.",
        _ if key.starts_with("granian_") => "This tunes the Granian runtime block used when http_server is set to granian. It controls worker counts, threading, protocol behavior, and safety knobs.",
        _ if key.starts_with("uvicorn_") => "This tunes the Uvicorn runtime block used when http_server is set to uvicorn. It covers workers, event loop, HTTP stack, backlog, and restart limits.",
        _ if key.starts_with("include_") || matches!(key, "enabled_groups" | "disabled_groups" | "enabled_endpoints" | "disabled_endpoints" | "enabled_tags" | "disabled_tags") => "These request filters constrain which benchmark request groups, endpoints, or tags are active in the generated scenario.",
        _ if matches!(key, "users" | "spawn_rate" | "run_time" | "request_count" | "target_service" | "locustfile" | "user_class" | "headless" | "only_summary" | "html_report" | "load_host" | "seed" | "tags" | "exclude_tags" | "load_extra_args" | "workload_selection" | "fallback_endpoint") => "These load settings shape how Locust drives traffic: which user class runs, how many users spawn, how long the test lasts, and which requests are selected.",
        _ if matches!(key, "profiling_enabled" | "profiling_tools" | "py_spy" | "profiling_duration_seconds" | "profiling_required") => "These profiling settings decide whether runtime profiling is collected, which profilers run, and whether a missing profile should fail the scenario.",
        _ if matches!(key, "retry_enabled" | "max_attempts" | "capture_logs" | "save_raw_results" | "reuse_stack") => "These execution settings control retries and artifact capture around the benchmark run itself.",
        _ => "This option maps directly to the benchmark scenario schema and is saved into the generated TOML as part of the suite or scenario definition.",
    }
}

fn generator_change_reason(key: &str) -> &'static str {
    match key {
        "file_stem" => "Change this when you want to create a new committed scenario instead of overwriting the default generated filename.",
        "template_kind" => "Change this first if you want the generator to start from an MCP-oriented or A2A-oriented workload mix.",
        "repo_url" | "git_ref" | "git_commit" => "Change these when benchmarking another branch, a pinned commit, or a different repository source.",
        "locustfile" | "user_class" | "workload_endpoints" => "Change these when the traffic shape itself is the thing you are experimenting with.",
        "http_server" => "Change this when comparing Gunicorn, Granian, and Uvicorn under the same workload.",
        "users" | "spawn_rate" | "run_time" => "Change these when you want to scale concurrency, shorten smoke tests, or run longer steady-state benchmarks.",
        "baseline_run" | "baseline_rps_drop_pct" | "baseline_p95_regression_pct" | "baseline_failure_increase" => "Change these when you need automated pass/fail gates against a known-good prior run.",
        _ if key.starts_with("gunicorn_") || key.starts_with("granian_") || key.starts_with("uvicorn_") => "Change this when you are tuning server-process behavior, not the application code or load mix.",
        _ if key.starts_with("scenario_") => "Change this when only one scenario in the file should override the defaults block.",
        _ => "Change this when the default generated value does not match the system, runtime, or traffic shape you want to test.",
    }
}

fn generator_visibility_note(key: &str) -> &'static str {
    match key {
        "expected_mcp_runtime_mode" => "Visible only after expected_mcp_runtime is set, because runtime mode only matters when you are asserting an MCP runtime.",
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
        "profiling_tools" | "py_spy" | "profiling_duration_seconds" | "profiling_required" => "Visible only when profiling_enabled is true.",
        "defaults_plugins_snippet" | "scenario_plugins_snippet" => "Visible only when plugins_enabled is true.",
        "workload_endpoints" => "Visible once the workload area is in use. Keep it empty if you just want the preset selection and fallback endpoint.",
        _ => "Always visible for this generator.",
    }
}

fn generator_example(key: &str) -> &'static str {
    match key {
        "file_stem" => "a2a-invoke-300",
        "template_kind" => "a2a",
        "suite_name" => "contextforge-a2a-compare",
        "suite_description" => "Compare Python and Rust A2A invoke throughput",
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
        "repo_url" => "https://github.com/IBM/mcp-context-forge",
        "git_ref" => "modular-design",
        "git_commit" => "f64721741a23cc17d0867943b70a67472203d18b",
        "rust_plugins" => "true",
        "profiling_image" => "false",
        "container_file" => "benchmarks/contextforge/Containerfile",
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
        "trust_proxy_auth" | "sqlalchemy_echo" | "templates_auto_reload" | "structured_logging_database_enabled" => "false",
        "disable_access_log" => "true",
        "gateway_environment" => "RUST_MCP_MODE = \"edge\" | MCPGATEWAY_UI_ENABLED = \"false\"",
        "target_service" => "nginx",
        "locustfile" => "benchmarks/contextforge/locust/locustfile_benchmark_ab.py",
        "user_class" => "BenchmarkUser",
        "headless" | "only_summary" | "retry_enabled" | "capture_logs" | "save_raw_results" | "reuse_stack" => "true",
        "html_report" | "include_admin_endpoints" | "include_mcp_endpoints" | "include_resource_endpoints" | "include_prompt_endpoints" | "include_tool_endpoints" | "profiling_enabled" | "py_spy" | "profiling_required" => "false",
        "users" => "300",
        "spawn_rate" => "60",
        "run_time" => "180s",
        "request_count" => "10000",
        "load_host" => "http://gateway:4444",
        "seed" => "1234",
        "tags" => "a2a,hot-path",
        "exclude_tags" => "admin",
        "load_extra_args" => "--reset-stats,--skip-log-setup",
        "load_env" => "BENCH_MCP_SESSION_MODE = \"reuse\" | BENCHMARK_TARGET = \"a2a\"",
        "workload_selection" => "weighted-random",
        "fallback_endpoint" => "/health",
        "workload_endpoints" => "[defaults.load.workload.endpoints.\"/a2a/a2a-echo-agent/invoke\"] | enabled = true | weight = 1",
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
        "profiling_tools" => "py_spy,process_stats",
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
        "scenario_profiling_snippet" => "enabled = true | tools = [\"py_spy\"]",
        "scenario_execution_snippet" => "max_attempts = 1",
        "scenario_plugins_snippet" => "mode = \"python\" | timeout_ms = 500",
        _ => "Set this to the value you want written into the generated scenario.",
    }
}

fn draw_help(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let help = match app.mode {
        InputMode::EditRunPath | InputMode::EditExtraArgs | InputMode::EditGeneratorField => {
            "Type text, Backspace deletes, Enter saves, Esc cancels"
        }
        InputMode::Normal if app.action() == Action::Generate => {
            "1-8/left-right: action  [ ] or PgUp/PgDn: section  j/k: field  e/Enter: edit  t: toggle/cycle  g or s: save template  use ',' CSV and ' | ' raw TOML lines  q: quit"
        }
        _ => {
            "1-8/left-right: action  j/k or up/down: scenario  a: toggle all  c: toggle clean  p: edit run path  e: edit extra args  Enter/r: run  q: quit"
        }
    };
    let widget = Paragraph::new(help)
        .block(Block::default().borders(Borders::ALL).title("Keys"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}
