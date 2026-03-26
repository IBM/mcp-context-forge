use std::env;
use std::fs;
use std::io::{self, BufRead, BufReader, Stdout};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::thread;
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
use toml::Value as TomlValue;

type AppResult<T> = Result<T, Box<dyn std::error::Error>>;
const MAX_LOG_LINES: usize = 500;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LogSource {
    Stdout,
    Stderr,
    System,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct LogLine {
    source: LogSource,
    text: String,
}

#[derive(Debug)]
struct RunningCommand {
    child: Child,
    receiver: Receiver<LogLine>,
    command_label: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct SuiteSummary {
    file_stem: String,
    suite_name: String,
    description: String,
}

impl SuiteSummary {
    fn label(&self) -> &str {
        &self.file_stem
    }

    fn suite_name(&self) -> &str {
        if self.suite_name.is_empty() {
            &self.file_stem
        } else {
            &self.suite_name
        }
    }

    fn description(&self) -> &str {
        if self.description.is_empty() {
            "No suite description is defined in this scenario TOML yet."
        } else {
            &self.description
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct PreviewSections {
    run_plan: Vec<String>,
    execution: Vec<String>,
    checks: Vec<String>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct SelectionSummary {
    action_label: String,
    suite_label: String,
    clean_label: String,
    run_mode_label: String,
    run_path_label: String,
    extra_args_label: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AppView {
    Launcher,
    SuiteInspector,
    RunMonitor,
    Generator,
}

impl AppView {
    const ALL: [AppView; 4] = [
        AppView::Launcher,
        AppView::SuiteInspector,
        AppView::RunMonitor,
        AppView::Generator,
    ];

    fn label(self) -> &'static str {
        match self {
            AppView::Launcher => "Launcher",
            AppView::SuiteInspector => "Inspector",
            AppView::RunMonitor => "Run Monitor",
            AppView::Generator => "Generator",
        }
    }

    fn supports_suite_navigation(self) -> bool {
        matches!(self, AppView::Launcher | AppView::SuiteInspector)
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct ScenarioCardSummary {
    name: String,
    description: String,
    scenario_type: String,
    settings: Vec<(String, String)>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct SuiteInspectorSummary {
    suite_name: String,
    suite_description: String,
    scenario_count_label: String,
    comparison_question: String,
    scenario_cards: Vec<ScenarioCardSummary>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct RunScenarioSummary {
    name: String,
    status: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct GeneratorFocusSummary {
    section_filter: String,
    field_label: String,
    config_key: String,
    value: String,
    kind: String,
    schema: String,
    format_hint: String,
    visibility: String,
    purpose: String,
    effect: String,
    example: String,
}

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
            Action::Generate => {
                "Generate a fully Rust-native TOML scenario template with all supported sections."
            }
        }
    }

    fn supports_scenario(self) -> bool {
        !matches!(
            self,
            Action::List | Action::Report | Action::Compare | Action::Generate
        )
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
                GeneratorField {
                    label: "File Stem",
                    key: "file_stem",
                    kind: GeneratorFieldKind::Text,
                    value: "new-scenario".to_string(),
                    help: "Output file name under tools_rust/contextforge_benchmark/assets/scenarios/.",
                },
                GeneratorField {
                    label: "Template Kind",
                    key: "template_kind",
                    kind: GeneratorFieldKind::Choice(&["blank", "mcp", "a2a"]),
                    value: "blank".to_string(),
                    help: "Choose a starter workload shape.",
                },
                GeneratorField {
                    label: "Suite Name",
                    key: "suite_name",
                    kind: GeneratorFieldKind::Text,
                    value: "benchmark-generated-suite".to_string(),
                    help: "The [suite].name value.",
                },
                GeneratorField {
                    label: "Suite Desc",
                    key: "suite_description",
                    kind: GeneratorFieldKind::Text,
                    value: "Generated benchmark scenario template".to_string(),
                    help: "The [suite].description value.",
                },
                GeneratorField {
                    label: "Output Root",
                    key: "output_root",
                    kind: GeneratorFieldKind::Text,
                    value: "reports/benchmarks".to_string(),
                    help: "Benchmark output directory.",
                },
                GeneratorField {
                    label: "Continue Fail",
                    key: "continue_on_failure",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "suite.continue_on_failure",
                },
                GeneratorField {
                    label: "Save Artifacts",
                    key: "save_intermediate_artifacts",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "suite.save_intermediate_artifacts",
                },
                GeneratorField {
                    label: "Flamegraphs",
                    key: "flamegraph_enabled",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "suite.flamegraph_enabled",
                },
                GeneratorField {
                    label: "Baseline Run",
                    key: "baseline_run",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional prior run_summary.json path.",
                },
                GeneratorField {
                    label: "Baseline RPS%",
                    key: "baseline_rps_drop_pct",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional allowed RPS drop percentage.",
                },
                GeneratorField {
                    label: "Baseline P95%",
                    key: "baseline_p95_regression_pct",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional allowed p95 regression percentage.",
                },
                GeneratorField {
                    label: "Baseline Fail+",
                    key: "baseline_failure_increase",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional allowed failure increase.",
                },
                GeneratorField {
                    label: "Scenario Name",
                    key: "scenario_name",
                    kind: GeneratorFieldKind::Text,
                    value: "generated-scenario".to_string(),
                    help: "Name for the first [[scenario]] entry.",
                },
                GeneratorField {
                    label: "Scenario Desc",
                    key: "scenario_description",
                    kind: GeneratorFieldKind::Text,
                    value: "Generated benchmark scenario".to_string(),
                    help: "Description for the first [[scenario]] entry.",
                },
                GeneratorField {
                    label: "Scenario Type",
                    key: "scenario_type",
                    kind: GeneratorFieldKind::Text,
                    value: "custom".to_string(),
                    help: "Freeform scenario_type label.",
                },
                GeneratorField {
                    label: "Target Kind",
                    key: "target_kind",
                    kind: GeneratorFieldKind::Choice(&["gateway", "agent"]),
                    value: "gateway".to_string(),
                    help: "defaults.setup.target_kind",
                },
                GeneratorField {
                    label: "Auth Mode",
                    key: "auth_mode",
                    kind: GeneratorFieldKind::Choice(&["jwt", "basic", "none"]),
                    value: "jwt".to_string(),
                    help: "defaults.setup.auth_mode",
                },
                GeneratorField {
                    label: "Plugins",
                    key: "plugins_enabled",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.setup.plugins_enabled",
                },
                GeneratorField {
                    label: "Expect MCP",
                    key: "expected_mcp_runtime",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional defaults.setup.expected_mcp_runtime",
                },
                GeneratorField {
                    label: "Expect MCP Mode",
                    key: "expected_mcp_runtime_mode",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional defaults.setup.expected_mcp_runtime_mode",
                },
                GeneratorField {
                    label: "Expect A2A",
                    key: "expected_a2a_runtime",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional defaults.setup.expected_a2a_runtime",
                },
                GeneratorField {
                    label: "Rust Plugins",
                    key: "rust_plugins",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.build.rust_plugins",
                },
                GeneratorField {
                    label: "Profiling Img",
                    key: "profiling_image",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.build.profiling_image",
                },
                GeneratorField {
                    label: "Container File",
                    key: "container_file",
                    kind: GeneratorFieldKind::Text,
                    value: "tools_rust/contextforge_benchmark/assets/Containerfile".to_string(),
                    help: "defaults.build.container_file",
                },
                GeneratorField {
                    label: "Image Name",
                    key: "image_name",
                    kind: GeneratorFieldKind::Text,
                    value: "mcpgateway/mcpgateway".to_string(),
                    help: "defaults.build.image_name",
                },
                GeneratorField {
                    label: "Image Tag",
                    key: "image_tag",
                    kind: GeneratorFieldKind::Text,
                    value: "benchmark-suite-generated".to_string(),
                    help: "defaults.build.image_tag",
                },
                GeneratorField {
                    label: "Rebuild",
                    key: "rebuild_policy",
                    kind: GeneratorFieldKind::Choice(&["never", "missing", "always"]),
                    value: "missing".to_string(),
                    help: "defaults.build.rebuild_policy",
                },
                GeneratorField {
                    label: "Build Args",
                    key: "build_args",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional build args. Use 'KEY = \"value\" | OTHER = \"x\"'.",
                },
                GeneratorField {
                    label: "HTTP Server",
                    key: "http_server",
                    kind: GeneratorFieldKind::Choice(&["gunicorn", "granian", "uvicorn"]),
                    value: "gunicorn".to_string(),
                    help: "defaults.runtime.http_server",
                },
                GeneratorField {
                    label: "Runtime Host",
                    key: "runtime_host",
                    kind: GeneratorFieldKind::Text,
                    value: "127.0.0.1".to_string(),
                    help: "defaults.runtime.host",
                },
                GeneratorField {
                    label: "Transport",
                    key: "transport_type",
                    kind: GeneratorFieldKind::Choice(&["streamablehttp", "sse", "websocket"]),
                    value: "streamablehttp".to_string(),
                    help: "defaults.runtime.transport_type",
                },
                GeneratorField {
                    label: "Gunicorn Workers",
                    key: "gunicorn_workers",
                    kind: GeneratorFieldKind::Text,
                    value: "12".to_string(),
                    help: "defaults.runtime.gunicorn.workers",
                },
                GeneratorField {
                    label: "Gunicorn Timeout",
                    key: "gunicorn_timeout",
                    kind: GeneratorFieldKind::Text,
                    value: "30".to_string(),
                    help: "defaults.runtime.gunicorn.timeout",
                },
                GeneratorField {
                    label: "Gunicorn Grace",
                    key: "gunicorn_graceful_timeout",
                    kind: GeneratorFieldKind::Text,
                    value: "30".to_string(),
                    help: "defaults.runtime.gunicorn.graceful_timeout",
                },
                GeneratorField {
                    label: "Gunicorn KeepAlive",
                    key: "gunicorn_keep_alive",
                    kind: GeneratorFieldKind::Text,
                    value: "10".to_string(),
                    help: "defaults.runtime.gunicorn.keep_alive",
                },
                GeneratorField {
                    label: "Gunicorn MaxReq",
                    key: "gunicorn_max_requests",
                    kind: GeneratorFieldKind::Text,
                    value: "0".to_string(),
                    help: "defaults.runtime.gunicorn.max_requests",
                },
                GeneratorField {
                    label: "Gunicorn Jitter",
                    key: "gunicorn_max_requests_jitter",
                    kind: GeneratorFieldKind::Text,
                    value: "0".to_string(),
                    help: "defaults.runtime.gunicorn.max_requests_jitter",
                },
                GeneratorField {
                    label: "Gunicorn Backlog",
                    key: "gunicorn_backlog",
                    kind: GeneratorFieldKind::Text,
                    value: "16384".to_string(),
                    help: "defaults.runtime.gunicorn.backlog",
                },
                GeneratorField {
                    label: "Gunicorn Preload",
                    key: "gunicorn_preload_app",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "defaults.runtime.gunicorn.preload_app",
                },
                GeneratorField {
                    label: "Gunicorn Dev",
                    key: "gunicorn_dev_mode",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.runtime.gunicorn.dev_mode",
                },
                GeneratorField {
                    label: "Granian Workers",
                    key: "granian_workers",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Worker process count when using Granian.",
                },
                GeneratorField {
                    label: "Granian Mode",
                    key: "granian_runtime_mode",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Granian runtime_mode, for example st or mt.",
                },
                GeneratorField {
                    label: "Granian Threads",
                    key: "granian_runtime_threads",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Async runtime threads per worker.",
                },
                GeneratorField {
                    label: "Granian Blocking",
                    key: "granian_blocking_threads",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Blocking thread pool size.",
                },
                GeneratorField {
                    label: "Granian HTTP",
                    key: "granian_http",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "HTTP protocol mode used by Granian.",
                },
                GeneratorField {
                    label: "Granian Loop",
                    key: "granian_loop",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Granian event loop selection.",
                },
                GeneratorField {
                    label: "Granian Task Impl",
                    key: "granian_task_impl",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Task implementation backend for Granian.",
                },
                GeneratorField {
                    label: "Granian Flush",
                    key: "granian_http1_pipeline_flush",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "Flush HTTP/1 pipelined responses immediately.",
                },
                GeneratorField {
                    label: "Granian Buf Size",
                    key: "granian_http1_buffer_size",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "HTTP/1 buffer size in bytes.",
                },
                GeneratorField {
                    label: "Granian Backlog",
                    key: "granian_backlog",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Listen backlog for pending connections.",
                },
                GeneratorField {
                    label: "Granian Pressure",
                    key: "granian_backpressure",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Backpressure queue limit.",
                },
                GeneratorField {
                    label: "Granian Respawn",
                    key: "granian_respawn_failed",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "Respawn failed workers automatically.",
                },
                GeneratorField {
                    label: "Granian Lifetime",
                    key: "granian_workers_lifetime",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Maximum worker lifetime.",
                },
                GeneratorField {
                    label: "Granian Max RSS",
                    key: "granian_workers_max_rss",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Restart workers over this RSS threshold.",
                },
                GeneratorField {
                    label: "Granian Dev",
                    key: "granian_dev_mode",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "Enable Granian dev mode.",
                },
                GeneratorField {
                    label: "Granian Log",
                    key: "granian_log_level",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Granian log level.",
                },
                GeneratorField {
                    label: "Uvicorn Workers",
                    key: "uvicorn_workers",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Worker process count when using Uvicorn.",
                },
                GeneratorField {
                    label: "Uvicorn Loop",
                    key: "uvicorn_loop",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Event loop implementation, for example auto or uvloop.",
                },
                GeneratorField {
                    label: "Uvicorn HTTP",
                    key: "uvicorn_http",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "HTTP protocol implementation.",
                },
                GeneratorField {
                    label: "Uvicorn Backlog",
                    key: "uvicorn_backlog",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Listen backlog for pending connections.",
                },
                GeneratorField {
                    label: "Uvicorn KeepAlive",
                    key: "uvicorn_timeout_keep_alive",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Keep-alive timeout in seconds.",
                },
                GeneratorField {
                    label: "Uvicorn MaxReq",
                    key: "uvicorn_limit_max_requests",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Restart worker after this many requests.",
                },
                GeneratorField {
                    label: "Uvicorn Log",
                    key: "uvicorn_log_level",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Uvicorn log level.",
                },
                GeneratorField {
                    label: "Uvicorn Dev",
                    key: "uvicorn_dev_mode",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "Enable Uvicorn dev mode.",
                },
                GeneratorField {
                    label: "Trust Proxy",
                    key: "trust_proxy_auth",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.gateway.trust_proxy_auth",
                },
                GeneratorField {
                    label: "Disable Access Log",
                    key: "disable_access_log",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "defaults.gateway.disable_access_log",
                },
                GeneratorField {
                    label: "Templates Reload",
                    key: "templates_auto_reload",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.gateway.templates_auto_reload",
                },
                GeneratorField {
                    label: "Structured DB Log",
                    key: "structured_logging_database_enabled",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.gateway.structured_logging_database_enabled",
                },
                GeneratorField {
                    label: "SQL Echo",
                    key: "sqlalchemy_echo",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.gateway.sqlalchemy_echo",
                },
                GeneratorField {
                    label: "Gateway Log",
                    key: "gateway_log_level",
                    kind: GeneratorFieldKind::Text,
                    value: "ERROR".to_string(),
                    help: "defaults.gateway.log_level",
                },
                GeneratorField {
                    label: "Gateway Env",
                    key: "gateway_environment",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional lines with ' | ' separators, e.g. RUST_MCP_MODE = \"edge\"",
                },
                GeneratorField {
                    label: "Target Service",
                    key: "target_service",
                    kind: GeneratorFieldKind::Choice(&["nginx", "gateway"]),
                    value: "nginx".to_string(),
                    help: "defaults.load.target_service",
                },
                GeneratorField {
                    label: "Load Driver",
                    key: "driver",
                    kind: GeneratorFieldKind::Text,
                    value: "contextforge_goose".to_string(),
                    help: "defaults.load.driver",
                },
                GeneratorField {
                    label: "Headless",
                    key: "headless",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "defaults.load.headless",
                },
                GeneratorField {
                    label: "Only Summary",
                    key: "only_summary",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "defaults.load.only_summary",
                },
                GeneratorField {
                    label: "HTML Report",
                    key: "html_report",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.load.html_report",
                },
                GeneratorField {
                    label: "Users",
                    key: "users",
                    kind: GeneratorFieldKind::Text,
                    value: "300".to_string(),
                    help: "defaults.load.users",
                },
                GeneratorField {
                    label: "Spawn Rate",
                    key: "spawn_rate",
                    kind: GeneratorFieldKind::Text,
                    value: "60".to_string(),
                    help: "defaults.load.spawn_rate",
                },
                GeneratorField {
                    label: "Run Time",
                    key: "run_time",
                    kind: GeneratorFieldKind::Text,
                    value: "180s".to_string(),
                    help: "defaults.load.run_time",
                },
                GeneratorField {
                    label: "Request Count",
                    key: "request_count",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional defaults.load.request_count",
                },
                GeneratorField {
                    label: "Load Host",
                    key: "load_host",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional defaults.load.host",
                },
                GeneratorField {
                    label: "Seed",
                    key: "seed",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional defaults.load.seed",
                },
                GeneratorField {
                    label: "Tags",
                    key: "tags",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Comma-separated defaults.load.tags",
                },
                GeneratorField {
                    label: "Exclude Tags",
                    key: "exclude_tags",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Comma-separated defaults.load.exclude_tags",
                },
                GeneratorField {
                    label: "Extra Args CSV",
                    key: "load_extra_args",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Comma-separated defaults.load.extra_args",
                },
                GeneratorField {
                    label: "Load Env",
                    key: "load_env",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional lines with ' | ' separators, e.g. BENCH_MCP_SESSION_MODE = \"reuse\"",
                },
                GeneratorField {
                    label: "Selection",
                    key: "workload_selection",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional defaults.load.workload.selection",
                },
                GeneratorField {
                    label: "Fallback",
                    key: "fallback_endpoint",
                    kind: GeneratorFieldKind::Text,
                    value: "/health".to_string(),
                    help: "defaults.load.workload.fallback_endpoint",
                },
                GeneratorField {
                    label: "Workload Endpoints",
                    key: "workload_endpoints",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for workload endpoint tables.",
                },
                GeneratorField {
                    label: "Warmup",
                    key: "warmup_seconds",
                    kind: GeneratorFieldKind::Text,
                    value: "30".to_string(),
                    help: "defaults.measurement.warmup_seconds",
                },
                GeneratorField {
                    label: "Measure",
                    key: "measure_seconds",
                    kind: GeneratorFieldKind::Text,
                    value: "120".to_string(),
                    help: "defaults.measurement.measure_seconds",
                },
                GeneratorField {
                    label: "Profile",
                    key: "profile_seconds",
                    kind: GeneratorFieldKind::Text,
                    value: "0".to_string(),
                    help: "defaults.measurement.profile_seconds",
                },
                GeneratorField {
                    label: "Cooldown",
                    key: "cooldown_seconds",
                    kind: GeneratorFieldKind::Text,
                    value: "30".to_string(),
                    help: "defaults.measurement.cooldown_seconds",
                },
                GeneratorField {
                    label: "Req Enabled Groups",
                    key: "enabled_groups",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Comma-separated defaults.requests.enabled_groups",
                },
                GeneratorField {
                    label: "Req Disabled Groups",
                    key: "disabled_groups",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Comma-separated defaults.requests.disabled_groups",
                },
                GeneratorField {
                    label: "Req Enabled Endp",
                    key: "enabled_endpoints",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Comma-separated defaults.requests.enabled_endpoints",
                },
                GeneratorField {
                    label: "Req Disabled Endp",
                    key: "disabled_endpoints",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Comma-separated defaults.requests.disabled_endpoints",
                },
                GeneratorField {
                    label: "Req Enabled Tags",
                    key: "enabled_tags",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Comma-separated defaults.requests.enabled_tags",
                },
                GeneratorField {
                    label: "Req Disabled Tags",
                    key: "disabled_tags",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Comma-separated defaults.requests.disabled_tags",
                },
                GeneratorField {
                    label: "Incl Admin",
                    key: "include_admin_endpoints",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.requests.include_admin_endpoints",
                },
                GeneratorField {
                    label: "Incl MCP",
                    key: "include_mcp_endpoints",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.requests.include_mcp_endpoints",
                },
                GeneratorField {
                    label: "Incl Resource",
                    key: "include_resource_endpoints",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.requests.include_resource_endpoints",
                },
                GeneratorField {
                    label: "Incl Prompt",
                    key: "include_prompt_endpoints",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.requests.include_prompt_endpoints",
                },
                GeneratorField {
                    label: "Incl Tool",
                    key: "include_tool_endpoints",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.requests.include_tool_endpoints",
                },
                GeneratorField {
                    label: "Profiling On",
                    key: "profiling_enabled",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.profiling.enabled",
                },
                GeneratorField {
                    label: "Rust Profilers",
                    key: "profiling_tools",
                    kind: GeneratorFieldKind::Text,
                    value: "perf,flamegraph".to_string(),
                    help: "Comma-separated Rust-native profilers such as perf and flamegraph.",
                },
                GeneratorField {
                    label: "Profile Dur",
                    key: "profiling_duration_seconds",
                    kind: GeneratorFieldKind::Text,
                    value: "0".to_string(),
                    help: "defaults.profiling.duration_seconds",
                },
                GeneratorField {
                    label: "Profile Required",
                    key: "profiling_required",
                    kind: GeneratorFieldKind::Bool,
                    value: "false".to_string(),
                    help: "defaults.profiling.required",
                },
                GeneratorField {
                    label: "Retry Enabled",
                    key: "retry_enabled",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "defaults.execution.retry_enabled",
                },
                GeneratorField {
                    label: "Max Attempts",
                    key: "max_attempts",
                    kind: GeneratorFieldKind::Text,
                    value: "2".to_string(),
                    help: "defaults.execution.max_attempts",
                },
                GeneratorField {
                    label: "Capture Logs",
                    key: "capture_logs",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "defaults.execution.capture_logs",
                },
                GeneratorField {
                    label: "Save Raw",
                    key: "save_raw_results",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "defaults.execution.save_raw_results",
                },
                GeneratorField {
                    label: "Reuse Stack",
                    key: "reuse_stack",
                    kind: GeneratorFieldKind::Bool,
                    value: "true".to_string(),
                    help: "defaults.execution.reuse_stack",
                },
                GeneratorField {
                    label: "Defaults Plugins",
                    key: "defaults_plugins_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [defaults.plugins.<name>].",
                },
                GeneratorField {
                    label: "Scenario Setup",
                    key: "scenario_setup_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.setup].",
                },
                GeneratorField {
                    label: "Scenario Build",
                    key: "scenario_build_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.build].",
                },
                GeneratorField {
                    label: "Scenario Runtime",
                    key: "scenario_runtime_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.runtime].",
                },
                GeneratorField {
                    label: "Scenario Gateway",
                    key: "scenario_gateway_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.gateway].",
                },
                GeneratorField {
                    label: "Scenario Load",
                    key: "scenario_load_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.load].",
                },
                GeneratorField {
                    label: "Scenario Measure",
                    key: "scenario_measurement_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.measurement].",
                },
                GeneratorField {
                    label: "Scenario Requests",
                    key: "scenario_requests_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.requests].",
                },
                GeneratorField {
                    label: "Scenario Profiling",
                    key: "scenario_profiling_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.profiling], using Rust-native profiling settings.",
                },
                GeneratorField {
                    label: "Scenario Execution",
                    key: "scenario_execution_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.execution].",
                },
                GeneratorField {
                    label: "Scenario Plugins",
                    key: "scenario_plugins_snippet",
                    kind: GeneratorFieldKind::Text,
                    value: "".to_string(),
                    help: "Optional raw TOML lines with ' | ' separators for [scenario.plugins.<name>].",
                },
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
                let in_section = self.selected_section_name() == "All"
                    || generator_section(field.key) == self.selected_section_name();
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
        let current_pos = visible
            .iter()
            .position(|index| *index == self.selected)
            .unwrap_or(0) as isize;
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
                field.value = if field.value == "true" {
                    "false"
                } else {
                    "true"
                }
                .to_string();
            }
            GeneratorFieldKind::Choice(options) => {
                let current = options
                    .iter()
                    .position(|value| *value == field.value)
                    .unwrap_or(0);
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
        let workload_selection_present = !self.get("workload_selection").trim().is_empty()
            || self.get("template_kind") != "blank";

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
            "profiling_tools" | "profiling_duration_seconds" | "profiling_required" => {
                profiling_enabled
            }
            "defaults_plugins_snippet" | "scenario_plugins_snippet" => plugins_enabled,
            "workload_selection" | "fallback_endpoint" => true,
            "workload_endpoints" => workload_selection_present,
            _ => true,
        }
    }
}

struct App {
    active_view: AppView,
    action_index: usize,
    last_standard_action_index: usize,
    scenario_index: usize,
    scenarios: Vec<SuiteSummary>,
    run_path: String,
    extra_args: String,
    all: bool,
    clean: bool,
    mode: InputMode,
    status: String,
    should_quit: bool,
    generator: GeneratorState,
    log_lines: Vec<LogLine>,
    dropped_log_lines: usize,
    log_scroll: usize,
    running_command: Option<RunningCommand>,
    current_run_scenario: Option<String>,
    run_scenarios: Vec<RunScenarioSummary>,
    last_command_label: Option<String>,
    last_run_dir: Option<String>,
    last_run_outcome: Option<String>,
}

impl App {
    fn new(scenarios: Vec<SuiteSummary>) -> Self {
        Self {
            active_view: AppView::Launcher,
            action_index: 0,
            last_standard_action_index: 0,
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
            log_lines: Vec::new(),
            dropped_log_lines: 0,
            log_scroll: 0,
            running_command: None,
            current_run_scenario: None,
            run_scenarios: Vec::new(),
            last_command_label: None,
            last_run_dir: None,
            last_run_outcome: None,
        }
    }

    fn action(&self) -> Action {
        Action::ALL[self.action_index]
    }

    fn scenario(&self) -> &str {
        self.scenarios
            .get(self.scenario_index)
            .map(SuiteSummary::label)
            .unwrap_or("rust-mcp-runtime-300")
    }

    fn selected_suite(&self) -> Option<&SuiteSummary> {
        self.scenarios.get(self.scenario_index)
    }

    fn set_action_index(&mut self, index: usize) {
        self.action_index = index % Action::ALL.len();
        if self.action() != Action::Generate {
            self.last_standard_action_index = self.action_index;
        }
        if !self.action().supports_all() {
            self.all = false;
        }
        if !self.action().supports_clean() {
            self.clean = false;
        }
        if self.action() == Action::Generate {
            self.active_view = AppView::Generator;
        } else if self.active_view == AppView::Generator {
            self.active_view = AppView::Launcher;
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

    fn set_view(&mut self, view: AppView) {
        self.active_view = view;
        match view {
            AppView::Generator => {
                if self.action() != Action::Generate {
                    self.last_standard_action_index = self.action_index;
                    self.action_index = Action::ALL
                        .iter()
                        .position(|action| *action == Action::Generate)
                        .unwrap_or(self.action_index);
                }
            }
            _ => {
                if self.action() == Action::Generate {
                    self.action_index = self.last_standard_action_index;
                }
            }
        }
        self.status = match self.active_view {
            AppView::Launcher => "Launcher view: choose a suite and action.".to_string(),
            AppView::SuiteInspector => {
                "Suite Inspector: compare scenario cards for the selected suite.".to_string()
            }
            AppView::RunMonitor => {
                "Run Monitor: follow live logs and per-scenario progress.".to_string()
            }
            AppView::Generator => "Generator: edit and save a benchmark template.".to_string(),
        };
    }

    fn cycle_view(&mut self, delta: isize) {
        let views = if self.running_command.is_some() {
            vec![
                AppView::Launcher,
                AppView::SuiteInspector,
                AppView::RunMonitor,
                AppView::Generator,
            ]
        } else {
            vec![
                AppView::Launcher,
                AppView::SuiteInspector,
                AppView::RunMonitor,
                AppView::Generator,
            ]
        };
        let current = views
            .iter()
            .position(|view| *view == self.active_view)
            .unwrap_or(0) as isize;
        let next = (current + delta).rem_euclid(views.len() as isize) as usize;
        self.set_view(views[next]);
    }

    fn push_log_line(&mut self, source: LogSource, text: String) {
        if text.trim().is_empty() {
            return;
        }
        self.apply_progress_line(&text);
        self.status = text.clone();
        self.log_lines.push(LogLine { source, text });
        self.log_scroll = 0;
        if self.log_lines.len() > MAX_LOG_LINES {
            let drop_count = self.log_lines.len() - MAX_LOG_LINES;
            self.log_lines.drain(0..drop_count);
            self.dropped_log_lines += drop_count;
        }
    }

    fn apply_progress_line(&mut self, text: &str) {
        if let Some(name) = parse_scenario_start(text) {
            self.current_run_scenario = Some(name.clone());
            self.upsert_run_scenario(&name, "running");
        }
        if let Some((name, status)) = parse_scenario_completion(text) {
            self.current_run_scenario = None;
            self.upsert_run_scenario(&name, &status);
        }
        if let Some(run_dir) = parse_run_dir(text) {
            self.last_run_dir = Some(run_dir);
        }
        if let Some(outcome) = parse_run_outcome(text) {
            self.last_run_outcome = Some(outcome);
        }
    }

    fn upsert_run_scenario(&mut self, name: &str, status: &str) {
        if let Some(item) = self.run_scenarios.iter_mut().find(|item| item.name == name) {
            item.status = status.to_string();
            return;
        }
        self.run_scenarios.push(RunScenarioSummary {
            name: name.to_string(),
            status: status.to_string(),
        });
    }
}

fn main() -> AppResult<()> {
    let root = env::current_dir()?;
    let scenarios = discover_scenarios(&root)?;

    if env::args().nth(1).as_deref() == Some("--list-scenarios") {
        for scenario in scenarios {
            println!("{}", scenario.label());
        }
        return Ok(());
    }

    let mut terminal = setup_terminal()?;
    let result = run_app(&mut terminal, App::new(scenarios), &root);
    restore_terminal(&mut terminal)?;
    result
}

fn discover_scenarios(root: &Path) -> AppResult<Vec<SuiteSummary>> {
    let mut scenarios =
        fs::read_dir(root.join("tools_rust/contextforge_benchmark/assets/scenarios"))?
            .filter_map(|entry| {
                let path = entry.ok()?.path();
                if path.extension().and_then(|value| value.to_str()) != Some("toml") {
                    return None;
                }
                let file_stem = path.file_stem()?.to_str()?.to_string();
                let raw = fs::read_to_string(&path).ok()?;
                let parsed = toml::from_str::<TomlValue>(&raw).ok()?;
                let suite = parsed.get("suite")?.as_table()?;
                Some(SuiteSummary {
                    file_stem,
                    suite_name: suite
                        .get("name")
                        .and_then(TomlValue::as_str)
                        .unwrap_or_default()
                        .to_string(),
                    description: suite
                        .get("description")
                        .and_then(TomlValue::as_str)
                        .unwrap_or_default()
                        .to_string(),
                })
            })
            .collect::<Vec<_>>();
    scenarios.sort_by(|left, right| left.file_stem.cmp(&right.file_stem));
    Ok(scenarios)
}

fn load_selected_suite_doc(root: &Path, app: &App) -> AppResult<Option<TomlValue>> {
    let Some(selected) = app.selected_suite() else {
        return Ok(None);
    };
    let path = root
        .join("tools_rust/contextforge_benchmark/assets/scenarios")
        .join(format!("{}.toml", selected.label()));
    if !path.exists() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path)?;
    Ok(Some(toml::from_str::<TomlValue>(&raw)?))
}

fn build_preview_sections(app: &App, root: &Path) -> AppResult<PreviewSections> {
    let mut preview = PreviewSections::default();
    let selected_suite = app.selected_suite();

    if let Some(suite) = selected_suite {
        preview
            .run_plan
            .push(format!("Suite: {}", suite.suite_name()));
        preview
            .run_plan
            .push(format!("Focus: {}", suite.description()));
        if let Some(doc) = load_selected_suite_doc(root, app)? {
            if let Some(scenarios) = doc.get("scenario").and_then(TomlValue::as_array) {
                preview
                    .run_plan
                    .push(format!("Comparison set: {} scenario(s)", scenarios.len()));
                let scenario_names = scenarios
                    .iter()
                    .filter_map(|scenario| {
                        scenario
                            .get("name")
                            .and_then(TomlValue::as_str)
                            .map(ToString::to_string)
                    })
                    .collect::<Vec<_>>();
                if !scenario_names.is_empty() {
                    preview
                        .run_plan
                        .push(format!("Variants: {}", scenario_names.join(" vs ")));
                }
            }
        }
    } else {
        preview.run_plan.push("Suite: (none selected)".to_string());
    }

    match build_command(app, root) {
        Ok(command) => {
            preview.execution.push(format!(
                "Command: {}",
                format_command(&command.command, &command.args)
            ));
            preview.execution.push(format!(
                "Runtime env: {}={}",
                command.env[0].0, command.env[0].1
            ));
        }
        Err(error) => {
            preview.execution.push(format!("Command error: {error}"));
        }
    }

    if app.action().supports_all() && app.all {
        preview.checks.push(
            "Run-all is enabled, so the selected suite entry will only seed the preview context."
                .to_string(),
        );
    } else {
        preview
            .checks
            .push(format!("Selected suite will run as '{}'.", app.scenario()));
    }
    if app.action().supports_clean() && app.clean {
        preview
            .checks
            .push("Clean-first is enabled, so benchmark containers and report staging will be cleared before launch.".to_string());
    }
    if app.extra_args.trim().is_empty() {
        preview.checks.push("No extra args are set.".to_string());
    } else {
        preview.checks.push(format!(
            "Extra args will be appended exactly as typed: {}",
            app.extra_args.trim()
        ));
    }
    if app.action().needs_run_path() {
        if app.run_path.trim().is_empty() {
            preview.checks.push(
                "This action requires a run path. Press 'p' to set it before running.".to_string(),
            );
        } else {
            preview
                .checks
                .push(format!("Run path: {}", app.run_path.trim()));
        }
    } else {
        preview
            .checks
            .push("Run path is ignored for this action.".to_string());
    }
    if app.action() == Action::Smoke {
        preview
            .checks
            .push("Smoke mode cuts benchmark duration down to a fast validation run.".to_string());
    }

    Ok(preview)
}

fn build_selection_summary(app: &App) -> SelectionSummary {
    let action_label = app.action().label().to_string();
    let suite_label = if app.action().supports_scenario() {
        app.scenario().to_string()
    } else {
        "(not used)".to_string()
    };
    let clean_label = if app.action().supports_clean() {
        yes_no(app.clean).to_string()
    } else {
        "(not used)".to_string()
    };
    let run_mode_label = if app.action().supports_all() {
        if app.all {
            "all-scenarios"
        } else {
            "selected-suite"
        }
        .to_string()
    } else {
        "single-action".to_string()
    };
    let run_path_label = if app.action().needs_run_path() {
        if app.run_path.trim().is_empty() {
            "press 'p' to set".to_string()
        } else {
            app.run_path.trim().to_string()
        }
    } else {
        "(not used)".to_string()
    };
    let extra_args_label = if app.extra_args.trim().is_empty() {
        "press 'e' to edit".to_string()
    } else {
        app.extra_args.trim().to_string()
    };

    SelectionSummary {
        action_label,
        suite_label,
        clean_label,
        run_mode_label,
        run_path_label,
        extra_args_label,
    }
}

fn build_suite_inspector_summary(app: &App, root: &Path) -> AppResult<SuiteInspectorSummary> {
    let Some(suite) = app.selected_suite() else {
        return Ok(SuiteInspectorSummary {
            suite_name: "(none selected)".to_string(),
            suite_description: "Choose a suite to see its benchmark intent and comparison shape."
                .to_string(),
            scenario_count_label: "0 scenarios".to_string(),
            comparison_question: "No active suite".to_string(),
            scenario_cards: Vec::new(),
        });
    };

    let mut summary = SuiteInspectorSummary {
        suite_name: suite.suite_name().to_string(),
        suite_description: suite.description().to_string(),
        scenario_count_label: "0 scenarios".to_string(),
        comparison_question: suite.description().to_string(),
        scenario_cards: Vec::new(),
    };

    if let Some(doc) = load_selected_suite_doc(root, app)? {
        let defaults = doc.get("defaults");
        if let Some(scenarios) = doc.get("scenario").and_then(TomlValue::as_array) {
            summary.scenario_count_label = format!("{} scenario(s)", scenarios.len());
            for scenario in scenarios {
                summary
                    .scenario_cards
                    .push(build_scenario_card_summary(defaults, scenario));
            }
        }
    }

    Ok(summary)
}

fn build_scenario_card_summary(defaults: Option<&TomlValue>, scenario: &TomlValue) -> ScenarioCardSummary {
    let name = scenario
        .get("name")
        .and_then(TomlValue::as_str)
        .unwrap_or("(unnamed scenario)")
        .to_string();
    let description = scenario
        .get("description")
        .and_then(TomlValue::as_str)
        .unwrap_or("No scenario description is defined yet.")
        .to_string();
    let scenario_type = scenario
        .get("scenario_type")
        .and_then(TomlValue::as_str)
        .unwrap_or("(no type)")
        .to_string();
    let mut settings = Vec::new();

    if let Some(value) = merged_bool(defaults, scenario, "setup", "plugins_enabled") {
        settings.push(("plugins_enabled".to_string(), value.to_string()));
    }
    if let Some(value) = merged_bool(defaults, scenario, "build", "rust_plugins") {
        settings.push(("rust_plugins".to_string(), value.to_string()));
    }
    if let Some(value) = merged_string(defaults, scenario, "setup", "auth_mode") {
        settings.push(("auth_mode".to_string(), value));
    }
    if let Some(value) = merged_string(defaults, scenario, "runtime", "http_server") {
        settings.push(("http_server".to_string(), value));
    }
    if let Some(value) = merged_string(defaults, scenario, "build", "image_tag") {
        settings.push(("image_tag".to_string(), value));
    }
    if let Some(value) = merged_string(defaults, scenario, "load", "target_service") {
        settings.push(("target_service".to_string(), value));
    }
    for key in ["users", "spawn_rate", "run_time"] {
        if let Some(value) = merged_scalar_string(defaults, scenario, "load", key) {
            settings.push((key.to_string(), value));
        }
    }
    if let Some(value) = merged_bool(defaults, scenario, "profiling", "enabled") {
        settings.push(("profiling.enabled".to_string(), value.to_string()));
    }
    if let Some(value) = merged_bool(defaults, scenario, "execution", "retry_enabled") {
        settings.push(("retry_enabled".to_string(), value.to_string()));
    }
    for key in [
        "expected_mcp_runtime",
        "expected_mcp_runtime_mode",
        "expected_a2a_runtime",
    ] {
        if let Some(value) = merged_string(defaults, scenario, "setup", key) {
            settings.push((key.to_string(), value));
        }
    }
    for key in [
        "EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED",
        "RUST_MCP_MODE",
        "RUST_MCP_LOG",
    ] {
        if let Some(value) = merged_nested_string(defaults, scenario, "gateway", "environment", key)
        {
            settings.push((key.to_string(), value));
        }
    }

    ScenarioCardSummary {
        name,
        description,
        scenario_type,
        settings,
    }
}

fn merged_bool(defaults: Option<&TomlValue>, scenario: &TomlValue, section: &str, key: &str) -> Option<bool> {
    scenario
        .get(section)
        .and_then(|value| value.get(key))
        .and_then(TomlValue::as_bool)
        .or_else(|| {
            defaults
                .and_then(|value| value.get(section))
                .and_then(|value| value.get(key))
                .and_then(TomlValue::as_bool)
        })
}

fn merged_string(
    defaults: Option<&TomlValue>,
    scenario: &TomlValue,
    section: &str,
    key: &str,
) -> Option<String> {
    scenario
        .get(section)
        .and_then(|value| value.get(key))
        .and_then(TomlValue::as_str)
        .map(ToString::to_string)
        .or_else(|| {
            defaults
                .and_then(|value| value.get(section))
                .and_then(|value| value.get(key))
                .and_then(TomlValue::as_str)
                .map(ToString::to_string)
        })
}

fn merged_nested_string(
    defaults: Option<&TomlValue>,
    scenario: &TomlValue,
    section: &str,
    nested: &str,
    key: &str,
) -> Option<String> {
    scenario
        .get(section)
        .and_then(|value| value.get(nested))
        .and_then(|value| value.get(key))
        .and_then(TomlValue::as_str)
        .map(ToString::to_string)
        .or_else(|| {
            defaults
                .and_then(|value| value.get(section))
                .and_then(|value| value.get(nested))
                .and_then(|value| value.get(key))
                .and_then(TomlValue::as_str)
                .map(ToString::to_string)
        })
}

fn merged_scalar_string(
    defaults: Option<&TomlValue>,
    scenario: &TomlValue,
    section: &str,
    key: &str,
) -> Option<String> {
    fn format_value(value: &TomlValue) -> Option<String> {
        value
            .as_str()
            .map(ToString::to_string)
            .or_else(|| value.as_integer().map(|v| v.to_string()))
            .or_else(|| value.as_float().map(|v| v.to_string()))
            .or_else(|| value.as_bool().map(|v| v.to_string()))
    }

    scenario
        .get(section)
        .and_then(|value| value.get(key))
        .and_then(format_value)
        .or_else(|| {
            defaults
                .and_then(|value| value.get(section))
                .and_then(|value| value.get(key))
                .and_then(format_value)
        })
}

fn build_generator_focus_summary(app: &App) -> GeneratorFocusSummary {
    let field = app.generator.selected_field();
    let kind = match field.kind {
        GeneratorFieldKind::Text => "text",
        GeneratorFieldKind::Bool => "bool",
        GeneratorFieldKind::Choice(_) => "choice",
    };
    GeneratorFocusSummary {
        section_filter: app.generator.selected_section_name().to_string(),
        field_label: field.label.to_string(),
        config_key: generator_config_path(field.key).to_string(),
        value: field.value.clone(),
        kind: kind.to_string(),
        schema: field.help.to_string(),
        format_hint: generator_format_hint(field.key).to_string(),
        visibility: generator_visibility_note(field.key).to_string(),
        purpose: generator_explanation(field.key).to_string(),
        effect: generator_change_reason(field.key).to_string(),
        example: generator_example(field.key).to_string(),
    }
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
        drain_running_command(&mut app)?;
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
    if app.active_view == AppView::Generator {
        return handle_generate_mode(app, key, root);
    }

    match key.code {
        KeyCode::Char('q') | KeyCode::Esc => app.should_quit = true,
        KeyCode::Tab => app.cycle_view(1),
        KeyCode::BackTab => app.cycle_view(-1),
        KeyCode::Left => app.move_action(-1),
        KeyCode::Right => app.move_action(1),
        KeyCode::Up | KeyCode::Char('k') if app.active_view.supports_suite_navigation() => {
            app.move_scenario(-1)
        }
        KeyCode::Down | KeyCode::Char('j') if app.active_view.supports_suite_navigation() => {
            app.move_scenario(1)
        }
        KeyCode::Char('1') => app.set_action_index(0),
        KeyCode::Char('2') => app.set_action_index(1),
        KeyCode::Char('3') => app.set_action_index(2),
        KeyCode::Char('4') => app.set_action_index(3),
        KeyCode::Char('5') => app.set_action_index(4),
        KeyCode::Char('6') => app.set_action_index(5),
        KeyCode::Char('7') => app.set_action_index(6),
        KeyCode::Char('8') => app.set_action_index(7),
        KeyCode::Char('i') => app.set_view(AppView::SuiteInspector),
        KeyCode::Char('l') => app.set_view(AppView::Launcher),
        KeyCode::Char('m') => app.set_view(AppView::RunMonitor),
        KeyCode::PageUp | KeyCode::Char('[') if app.active_view == AppView::RunMonitor => {
            app.log_scroll = app
                .log_scroll
                .saturating_add(10)
                .min(app.log_lines.len().saturating_sub(1));
            app.status = format!("Log scroll offset: {}", app.log_scroll);
        }
        KeyCode::PageDown | KeyCode::Char(']') if app.active_view == AppView::RunMonitor => {
            app.log_scroll = app.log_scroll.saturating_sub(10);
            app.status = format!("Log scroll offset: {}", app.log_scroll);
        }
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
                app.status =
                    "Editing run path. Type, Backspace to delete, Enter to finish.".to_string();
            } else {
                app.status = "Run path is only used for Report and Compare.".to_string();
            }
        }
        KeyCode::Char('e') => {
            app.mode = InputMode::EditExtraArgs;
            app.status =
                "Editing extra args. Type, Backspace to delete, Enter to finish.".to_string();
        }
        KeyCode::Enter | KeyCode::Char('r') => launch_action(app, root, terminal)?,
        _ => {}
    }
    Ok(())
}

fn handle_generate_mode(app: &mut App, key: KeyEvent, root: &Path) -> AppResult<()> {
    match key.code {
        KeyCode::Char('q') | KeyCode::Esc => app.should_quit = true,
        KeyCode::Tab => app.cycle_view(1),
        KeyCode::BackTab => app.cycle_view(-1),
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
    _terminal: &mut Terminal<CrosstermBackend<Stdout>>,
) -> AppResult<()> {
    let command_spec = build_command(app, root)?;
    if app.running_command.is_some() {
        app.status = "A benchmark command is already running.".to_string();
        return Ok(());
    }
    if app.clean && app.action().supports_clean() {
        app.push_log_line(
            LogSource::System,
            "Cleanup: removing prior benchmark containers and staging artifacts.".to_string(),
        );
        let cleanup_status = run_cleanup()?;
        app.push_log_line(
            LogSource::System,
            format!("Cleanup finished with status: {cleanup_status}"),
        );
    }
    start_command_capture(app, command_spec, root)?;
    Ok(())
}

struct CommandSpec {
    command: String,
    args: Vec<String>,
    env: Vec<(String, String)>,
}

fn build_command(app: &App, _root: &Path) -> AppResult<CommandSpec> {
    let action = app.action();
    let mut args = vec![
        "cargo".to_string(),
        "run".to_string(),
        "--manifest-path".to_string(),
        "tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml".to_string(),
        "--quiet".to_string(),
        "--".to_string(),
    ];

    match action {
        Action::List => args.push("list".to_string()),
        Action::Run | Action::Validate | Action::Smoke | Action::CheckRuntime => {
            args.push(
                match action {
                    Action::Run | Action::Smoke => {
                        if app.all && action.supports_all() {
                            "run-all"
                        } else {
                            "run"
                        }
                    }
                    Action::Validate => "validate",
                    Action::CheckRuntime => "check-runtime",
                    _ => unreachable!(),
                }
                .to_string(),
            );
            if !app.all || !action.supports_all() || !matches!(action, Action::Run | Action::Smoke)
            {
                args.push("--scenario".to_string());
                args.push(app.scenario().to_string());
            }
            match action {
                Action::Smoke | Action::Validate | Action::CheckRuntime
                    if app.all && matches!(action, Action::Validate | Action::CheckRuntime) =>
                {
                    args.push("--scenario".to_string());
                    args.push(app.scenario().to_string());
                    if matches!(action, Action::Smoke) {
                        args.push("--smoke".to_string());
                    }
                }
                Action::Smoke => args.push("--smoke".to_string()),
                _ => {}
            }
        }
        Action::Report => {
            if app.run_path.trim().is_empty() {
                return Err("Report needs a run path. Press 'p' to edit it.".into());
            }
            args.push("regenerate-report".to_string());
            args.push("--run-dir".to_string());
            args.push(app.run_path.trim().to_string());
        }
        Action::Compare => {
            if app.run_path.trim().is_empty() {
                return Err("Compare needs a run path. Press 'p' to edit it.".into());
            }
            args.push("compare-run".to_string());
            args.push("--run-dir".to_string());
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

fn run_cleanup() -> AppResult<std::process::ExitStatus> {
    let engine = env::var("CONTAINER_RUNTIME").unwrap_or_else(|_| "podman".to_string());
    let chosen_engine = if Command::new(&engine)
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
    {
        engine
    } else {
        "docker".to_string()
    };

    if chosen_engine == "podman" {
        if let Ok(output) = Command::new("podman")
            .args(["pod", "ps", "-a", "--format", "{{.Name}}"])
            .output()
        {
            for pod in String::from_utf8_lossy(&output.stdout)
                .lines()
                .map(str::trim)
                .filter(|name| name.starts_with("bench-"))
            {
                let _ = Command::new("podman")
                    .args(["pod", "rm", "-f", pod])
                    .status();
            }
        }
    }

    if let Ok(output) = Command::new(&chosen_engine)
        .args(["ps", "-a", "--format", "{{.Names}}"])
        .output()
    {
        for container in String::from_utf8_lossy(&output.stdout)
            .lines()
            .map(str::trim)
            .filter(|name| name.starts_with("bench-"))
        {
            let _ = Command::new(&chosen_engine)
                .args(["rm", "-f", container])
                .status();
        }
    }

    let reports_dir = Path::new("reports/benchmarks");
    if reports_dir.exists() {
        for entry in fs::read_dir(&reports_dir)? {
            let path = entry?.path();
            let name = path
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("");
            if name.starts_with("all-scenarios_")
                || name.starts_with("rust-mcp-runtime-300_")
                || name.starts_with("a2a-invoke-300_")
                || name == "_runtime_staging"
            {
                if path.is_dir() {
                    let _ = fs::remove_dir_all(&path);
                } else {
                    let _ = fs::remove_file(&path);
                }
            }
        }
    }

    Command::new("true").status().map_err(Into::into)
}

fn save_generated_template(
    root: &Path,
    scenarios: &mut Vec<SuiteSummary>,
    generator: &GeneratorState,
) -> AppResult<PathBuf> {
    let file_stem = sanitize_file_stem(generator.get("file_stem"));
    let target = root
        .join("tools_rust/contextforge_benchmark/assets/scenarios")
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
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '-'
            }
        })
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
    lines.push(format!(
        "{key} = {}",
        if value == "true" { "true" } else { "false" }
    ));
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

fn append_runtime_block_from_fields(
    lines: &mut Vec<String>,
    title: &str,
    fields: &[(&str, &str, &str)],
) {
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

fn escape_toml(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

fn format_command(command: &str, args: &[String]) -> String {
    std::iter::once(command.to_string())
        .chain(args.iter().cloned())
        .collect::<Vec<_>>()
        .join(" ")
}

fn start_command_capture(app: &mut App, command_spec: CommandSpec, root: &Path) -> AppResult<()> {
    let command_label = format_command(&command_spec.command, &command_spec.args);
    let mut child = Command::new(&command_spec.command)
        .args(&command_spec.args)
        .envs(command_spec.env.clone())
        .current_dir(root)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let stdout = child.stdout.take().ok_or("Could not capture child stdout")?;
    let stderr = child.stderr.take().ok_or("Could not capture child stderr")?;
    let (sender, receiver) = mpsc::channel::<LogLine>();
    spawn_log_reader(stdout, LogSource::Stdout, sender.clone());
    spawn_log_reader(stderr, LogSource::Stderr, sender);
    app.run_scenarios.clear();
    app.current_run_scenario = None;
    app.last_run_dir = None;
    app.last_run_outcome = None;
    app.log_lines.clear();
    app.dropped_log_lines = 0;
    app.log_scroll = 0;
    app.last_command_label = Some(command_label.clone());
    app.push_log_line(
        LogSource::System,
        format!("Started command inside console: {command_label}"),
    );
    app.running_command = Some(RunningCommand {
        child,
        receiver,
        command_label,
    });
    app.active_view = AppView::RunMonitor;
    Ok(())
}

fn spawn_log_reader<R>(reader: R, source: LogSource, sender: mpsc::Sender<LogLine>)
where
    R: std::io::Read + Send + 'static,
{
    thread::spawn(move || {
        let reader = BufReader::new(reader);
        for line in reader.lines() {
            match line {
                Ok(text) => {
                    let _ = sender.send(LogLine { source, text });
                }
                Err(error) => {
                    let _ = sender.send(LogLine {
                        source: LogSource::System,
                        text: format!("Log capture error: {error}"),
                    });
                    break;
                }
            }
        }
    });
}

fn drain_running_command(app: &mut App) -> AppResult<()> {
    let Some(mut running) = app.running_command.take() else {
        return Ok(());
    };

    while let Ok(line) = running.receiver.try_recv() {
        app.push_log_line(line.source, line.text);
    }

    match running.child.try_wait()? {
        Some(status) => {
            while let Ok(line) = running.receiver.try_recv() {
                app.push_log_line(line.source, line.text);
            }
            let outcome = if status.success() { "finished" } else { "failed" };
            app.push_log_line(
                LogSource::System,
                format!("Command {outcome} with status {status}: {}", running.command_label),
            );
        }
        None => {
            app.running_command = Some(running);
        }
    }

    Ok(())
}

fn parse_scenario_start(text: &str) -> Option<String> {
    text.split("starting: ")
        .nth(1)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
}

fn parse_scenario_completion(text: &str) -> Option<(String, String)> {
    let prefix = "Scenario '";
    let rest = text.strip_prefix("[benchmark] ").unwrap_or(text);
    let rest = rest.strip_prefix(prefix)?;
    if let Some((name, suffix)) = rest.split_once("' completed with status ") {
        return Some((name.to_string(), suffix.trim().to_string()));
    }
    if let Some((name, _)) = rest.split_once("' failed:") {
        return Some((name.to_string(), "failed".to_string()));
    }
    None
}

fn parse_run_dir(text: &str) -> Option<String> {
    if text.contains("reports/benchmarks/") {
        return text
            .split_whitespace()
            .find(|part| part.contains("reports/benchmarks/"))
            .map(|value| value.trim().to_string());
    }
    None
}

fn parse_run_outcome(text: &str) -> Option<String> {
    let rest = text.strip_prefix("[benchmark] ").unwrap_or(text);
    if rest.starts_with("Benchmark run completed successfully") {
        return Some("ok".to_string());
    }
    if rest.starts_with("Benchmark run completed with failed scenarios") {
        return Some("failed".to_string());
    }
    None
}

fn yes_no(value: bool) -> &'static str {
    if value { "yes" } else { "no" }
}

fn draw(frame: &mut ratatui::Frame<'_>, app: &App) {
    let chunks = if app.active_view == AppView::Generator {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(5),
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
                Constraint::Length(5),
                Constraint::Min(10),
                Constraint::Length(4),
            ])
            .split(frame.area())
    };

    let header = Paragraph::new(vec![
        Line::from(Span::styled(
            "ContextForge Benchmark Console",
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        )),
        Line::from(format!("Mode: {}", app.mode.label())),
    ])
    .block(Block::default().borders(Borders::ALL).title("Console"));
    frame.render_widget(header, chunks[0]);

    let view_tabs = Tabs::new(
        AppView::ALL
            .iter()
            .map(|view| Line::from(view.label().to_string()))
            .collect::<Vec<_>>(),
    )
    .select(
        AppView::ALL
            .iter()
            .position(|view| *view == app.active_view)
            .unwrap_or(0),
    )
    .block(Block::default().borders(Borders::ALL).title("Views"))
    .highlight_style(
        Style::default()
            .fg(Color::Black)
            .bg(Color::Green)
            .add_modifier(Modifier::BOLD),
    );
    frame.render_widget(view_tabs, chunks[1]);

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
    frame.render_widget(tabs, chunks[2]);

    draw_status_banner(frame, chunks[3], app);

    if app.active_view == AppView::Generator {
        draw_generator_sections(frame, chunks[2], app);
        let body = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(56), Constraint::Percentage(44)])
            .split(chunks[4]);
        let left = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(10), Constraint::Length(11)])
            .split(body[0]);
        draw_generator_fields(frame, left[0], app);
        draw_generator_selection(frame, left[1], app);
        draw_generator_reference(frame, body[1], app);
    } else {
        match app.active_view {
            AppView::Launcher => draw_launcher_view(frame, chunks[4], app),
            AppView::SuiteInspector => draw_suite_inspector_view(frame, chunks[4], app),
            AppView::RunMonitor => draw_run_monitor_view(frame, chunks[4], app),
            AppView::Generator => {}
        }
    }
    draw_help(frame, chunks[5], app);
}

fn draw_status_banner(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let selected_suite = app
        .selected_suite()
        .map(SuiteSummary::label)
        .unwrap_or("(none)");
    let status_lines = vec![
        Line::from(vec![
            Span::styled("Action ", Style::default().fg(Color::Gray)),
            Span::styled(
                app.action().label(),
                Style::default()
                    .fg(Color::Cyan)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::raw("   "),
            Span::styled("View ", Style::default().fg(Color::Gray)),
            Span::styled(
                app.active_view.label(),
                Style::default()
                    .fg(Color::Green)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::raw("   "),
            Span::styled("Suite ", Style::default().fg(Color::Gray)),
            Span::styled(
                selected_suite,
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::BOLD),
            ),
        ]),
        Line::from(vec![
            Span::styled("Status ", Style::default().fg(Color::Gray)),
            Span::styled(
                app.status.as_str(),
                Style::default().fg(if app.running_command.is_some() {
                    Color::Yellow
                } else {
                    Color::Green
                })
                .add_modifier(Modifier::BOLD),
            ),
        ]),
        Line::from(vec![
            Span::styled("Live Run ", Style::default().fg(Color::Gray)),
            Span::styled(
                if app.running_command.is_some() {
                    "active"
                } else {
                    "idle"
                },
                Style::default()
                    .fg(if app.running_command.is_some() {
                        Color::LightYellow
                    } else {
                        Color::DarkGray
                    })
                    .add_modifier(Modifier::BOLD),
            ),
        ]),
    ];
    let widget = Paragraph::new(status_lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Operator Status"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_generator_sections(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let tabs = Tabs::new(
        GeneratorState::sections()
            .iter()
            .map(|section| Line::from((*section).to_string()))
            .collect::<Vec<_>>(),
    )
    .select(app.generator.selected_section)
    .block(
        Block::default()
            .borders(Borders::ALL)
            .title("Generator Sections"),
    )
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
        .map(|scenario| {
            ListItem::new(vec![
                Line::from(Span::styled(
                    scenario.label().to_string(),
                    Style::default().add_modifier(Modifier::BOLD),
                )),
                Line::from(Span::styled(
                    scenario.suite_name().to_string(),
                    Style::default().fg(Color::Gray),
                )),
            ])
        })
        .collect::<Vec<_>>();
    let list = List::new(items)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Benchmark Suites"),
        )
        .highlight_style(
            Style::default()
                .fg(Color::Black)
                .bg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )
        .highlight_symbol(">> ")
        .highlight_spacing(ratatui::widgets::HighlightSpacing::Always);
    let mut state = ListState::default();
    state.select(Some(app.scenario_index));
    frame.render_stateful_widget(list, area, &mut state);
}

fn draw_launcher_view(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let body = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(36), Constraint::Percentage(64)])
        .split(area);
    draw_scenarios(frame, body[0], app);
    let right = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(12), Constraint::Min(10)])
        .split(body[1]);
    let top = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(42), Constraint::Percentage(58)])
        .split(right[0]);
    draw_selection(frame, top[0], app);
    draw_launcher_summary(frame, top[1], app);
    draw_preview(frame, right[1], app);
}

fn draw_suite_inspector_view(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let body = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(8), Constraint::Min(14)])
        .split(area);
    draw_inspector_header(frame, body[0], app);
    draw_scenario_cards(frame, body[1], app);
}

fn draw_run_monitor_view(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let body = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(10), Constraint::Min(14)])
        .split(area);
    draw_run_monitor_summary(frame, body[0], app);
    draw_live_logs(frame, body[1], app);
}

fn draw_selection(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_selection_summary(app);
    let lines = vec![
        line_pair("Action", &summary.action_label),
        line_pair("Suite", &summary.suite_label),
        line_pair("Run Mode", &summary.run_mode_label),
        line_pair("Clean First", &summary.clean_label),
        line_pair("Run Path", &summary.run_path_label),
        line_pair("Extra Args", &summary.extra_args_label),
    ];
    let widget = Paragraph::new(lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Selection State"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_launcher_summary(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_suite_inspector_summary(app, Path::new(".")).unwrap_or_default();
    let lines = vec![
        Line::from(Span::styled(
            summary.suite_name,
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        line_pair("Intent", &summary.suite_description),
        line_pair("Comparison Set", &summary.scenario_count_label),
        line_pair(
            "Inspector",
            "Press 'i' or Tab to open full scenario comparison cards",
        ),
    ];
    let widget = Paragraph::new(lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Suite Summary"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_inspector_header(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_suite_inspector_summary(app, Path::new(".")).unwrap_or_default();
    let lines = vec![
        Line::from(Span::styled(
            summary.suite_name,
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        )),
        Line::from(summary.suite_description),
        Line::from(""),
        line_pair("Comparison Set", &summary.scenario_count_label),
        line_pair("Question", &summary.comparison_question),
    ];
    let widget = Paragraph::new(lines)
        .block(Block::default().borders(Borders::ALL).title("Suite Inspector"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_scenario_cards(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_suite_inspector_summary(app, Path::new(".")).unwrap_or_default();
    if summary.scenario_cards.is_empty() {
        let widget = Paragraph::new("No scenarios found for the selected suite.")
            .block(Block::default().borders(Borders::ALL).title("Scenario Comparison"));
        frame.render_widget(widget, area);
        return;
    }

    let constraints = vec![Constraint::Ratio(1, summary.scenario_cards.len() as u32); summary.scenario_cards.len()];
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints(constraints)
        .split(area);

    for (index, card) in summary.scenario_cards.iter().enumerate() {
        let is_active = app.current_run_scenario.as_deref() == Some(card.name.as_str());
        let mut lines = vec![
            Line::from(Span::styled(
                card.name.clone(),
                Style::default()
                    .fg(if is_active { Color::Yellow } else { Color::White })
                    .add_modifier(Modifier::BOLD),
            )),
            Line::from(card.description.clone()),
            Line::from(format!("Type: {}", card.scenario_type)),
        ];
        if card.settings.is_empty() {
            lines.push(Line::from("Settings: inherits suite defaults"));
        } else {
            lines.push(Line::from("Settings:"));
            lines.extend(card.settings.iter().map(|(key, value)| {
                Line::from(format!("  {} = {}", key, value))
            }));
        }
        let title = if is_active {
            format!("Scenario {} (active)", index + 1)
        } else {
            format!("Scenario {}", index + 1)
        };
        let widget = Paragraph::new(lines)
            .block(Block::default().borders(Borders::ALL).title(title))
            .wrap(Wrap { trim: false });
        frame.render_widget(widget, chunks[index]);
    }
}

fn draw_run_monitor_summary(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let selected_suite = app
        .selected_suite()
        .map(SuiteSummary::suite_name)
        .unwrap_or("(none)");
    let current = app.current_run_scenario.as_deref().unwrap_or("(idle)");
    let buffered_logs = app.log_lines.len().to_string();
    let dropped_logs = app.dropped_log_lines.to_string();
    let statuses = if app.run_scenarios.is_empty() {
        vec![Line::from("No run scenarios recorded yet.")]
    } else {
        app.run_scenarios
            .iter()
            .map(|item| Line::from(format!("{} -> {}", item.name, item.status)))
            .collect::<Vec<_>>()
    };
    let mut lines = vec![
        line_pair("Suite", selected_suite),
        line_pair(
            "Command",
            app.last_command_label.as_deref().unwrap_or("(no command launched)"),
        ),
        line_pair("Current Scenario", current),
        line_pair(
            "Run Dir",
            app.last_run_dir.as_deref().unwrap_or("(pending)"),
        ),
        line_pair(
            "Outcome",
            app.last_run_outcome.as_deref().unwrap_or("(running or pending)"),
        ),
        line_pair("Buffered Logs", &buffered_logs),
        line_pair("Dropped Logs", &dropped_logs),
        Line::from(""),
        Line::from(Span::styled(
            "Scenario Status",
            Style::default().add_modifier(Modifier::BOLD),
        )),
    ];
    lines.extend(statuses);
    let widget = Paragraph::new(lines)
        .block(Block::default().borders(Borders::ALL).title("Run Monitor"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_preview(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let preview = build_preview_sections(app, Path::new(".")).unwrap_or_else(|error| {
        let mut fallback = PreviewSections::default();
        fallback.execution.push(format!(
            "Command error: failed to build preview sections: {error}"
        ));
        fallback
    });
    let mut lines = vec![Line::from(Span::styled(
        app.action().help(),
        Style::default().fg(Color::Cyan),
    ))];
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Run Plan",
        Style::default().add_modifier(Modifier::BOLD),
    )));
    lines.extend(preview.run_plan.iter().map(|line| Line::from(line.clone())));
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Execution",
        Style::default().add_modifier(Modifier::BOLD),
    )));
    lines.extend(preview.execution.iter().map(|line| {
        if line.starts_with("Command error:") {
            Line::from(Span::styled(line.clone(), Style::default().fg(Color::Red)))
        } else {
            Line::from(line.clone())
        }
    }));
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Checks",
        Style::default().add_modifier(Modifier::BOLD),
    )));
    lines.extend(preview.checks.iter().map(|line| Line::from(line.clone())));
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        format!("Status: {}", app.status),
        Style::default().fg(Color::Magenta),
    )));
    let widget = Paragraph::new(lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Execution Dashboard"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_live_logs(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let visible_height = area.height.saturating_sub(2) as usize;
    let total = app.log_lines.len();
    let end = total.saturating_sub(app.log_scroll);
    let start = end.saturating_sub(visible_height);
    let lines = app.log_lines[start..end]
        .iter()
        .map(|line| {
            let prefix = match line.source {
                LogSource::Stdout => ("OUT", Color::Green),
                LogSource::Stderr => ("ERR", Color::Red),
                LogSource::System => ("SYS", Color::Cyan),
            };
            Line::from(vec![
                Span::styled(
                    format!("[{}] ", prefix.0),
                    Style::default().fg(prefix.1).add_modifier(Modifier::BOLD),
                ),
                Span::raw(line.text.clone()),
            ])
        })
        .collect::<Vec<_>>();
    let empty = vec![Line::from(Span::styled(
        "Run a benchmark action to see live logs here.",
        Style::default().fg(Color::DarkGray),
    ))];
    let widget = Paragraph::new(if lines.is_empty() { empty } else { lines })
        .block(
            Block::default().borders(Borders::ALL).title(format!(
                "Live Logs ({}/{}, scroll {}, dropped {})",
                end.saturating_sub(start),
                total,
                app.log_scroll,
                app.dropped_log_lines
            )),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_generator_fields(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let visible = app.generator.visible_indices();
    let items = visible
        .iter()
        .map(|index| {
            let field = &app.generator.fields[*index];
            ListItem::new(vec![
                Line::from(vec![
                    Span::styled(
                        format!("{}{}", generator_indent(field.key), field.label),
                        Style::default().add_modifier(Modifier::BOLD),
                    ),
                    Span::raw("  "),
                    Span::styled(
                        generator_section(field.key),
                        Style::default().fg(Color::Blue),
                    ),
                ]),
                Line::from(Span::styled(
                    field.value.clone(),
                    Style::default().fg(Color::Green),
                )),
            ])
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
        .highlight_symbol(">> ")
        .highlight_spacing(ratatui::widgets::HighlightSpacing::Always);
    let mut state = ListState::default();
    state.select(Some(visible_pos));
    frame.render_stateful_widget(list, area, &mut state);
}

fn draw_generator_selection(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_generator_focus_summary(app);
    let lines = vec![
        line_pair("Section Filter", &summary.section_filter),
        line_pair("Field", &summary.field_label),
        line_pair("Config Key", &summary.config_key),
        line_pair("Value", &summary.value),
        line_pair("Kind", &summary.kind),
        line_pair("Schema", &summary.schema),
        line_pair("Format", &summary.format_hint),
        line_pair("Visibility", &summary.visibility),
        line_pair("Edit", "Enter/e edits, t toggles bool or choice"),
        line_pair("Save", "g or s writes the scenario file"),
    ];
    let widget = Paragraph::new(lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Current Field"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_generator_reference(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_generator_focus_summary(app);
    let detail = format!(
        "What it is for:\n{}\n\nWhat it does:\n{}\n\nAccepted values:\n{}\n\nVisibility:\n{}\n\nExample:\n{}",
        summary.purpose, summary.effect, summary.format_hint, summary.visibility, summary.example
    );
    let widget = Paragraph::new(detail)
        .block(Block::default().borders(Borders::ALL).title("Field Guide"))
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

fn generator_format_hint(key: &str) -> &'static str {
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

fn generator_explanation(key: &str) -> &'static str {
    match key {
        "file_stem" => "Sets the filename stem used when the generator saves a scenario TOML.",
        "template_kind" => "Chooses which starter benchmark shape the generator should prefill.",
        "suite_name" => "Sets the suite title stored in `[suite].name`.",
        "suite_description" => {
            "Sets the operator-facing explanation stored in `[suite].description`."
        }
        "output_root" => "Sets the root directory where this suite writes reports and artifacts.",
        "continue_on_failure" => {
            "Controls whether the suite continues running after one scenario fails."
        }
        "save_intermediate_artifacts" => {
            "Controls whether intermediate raw outputs are kept between stages."
        }
        "flamegraph_enabled" => {
            "Marks the suite as able to produce flamegraph-style profiling artifacts."
        }
        "baseline_run" => {
            "Points the suite at a previously saved run summary that should act as the comparison baseline."
        }
        "baseline_rps_drop_pct" => {
            "Sets the allowed throughput drop threshold when comparing the current run against the baseline run."
        }
        "baseline_p95_regression_pct" => {
            "Sets the allowed p95 latency regression threshold when comparing the current run against the baseline run."
        }
        "baseline_failure_increase" => {
            "Sets the allowed increase in failure rate when comparing the current run against the baseline run."
        }
        "scenario_name" => "Sets the scenario name stored in the first `[[scenario]]` entry.",
        "scenario_description" => {
            "Sets the scenario description stored in the first `[[scenario]]` entry."
        }
        "scenario_type" => "Sets the scenario classification label used in reports.",
        "target_kind" => "Defines whether the benchmark is aimed at gateway or agent behavior.",
        "auth_mode" => "Defines which authentication mode the generated scenario expects.",
        "plugins_enabled" => "Defines whether plugin-aware setup is enabled by default.",
        "expected_mcp_runtime" => "Defines the MCP runtime expectation stored in scenario setup.",
        "expected_mcp_runtime_mode" => {
            "Defines the expected MCP runtime mode when MCP runtime assertions are active."
        }
        "expected_a2a_runtime" => "Defines the A2A runtime expectation stored in scenario setup.",
        "rust_plugins" => {
            "Defines whether the benchmark image should include Rust plugin artifacts."
        }
        "profiling_image" => {
            "Defines whether the benchmark image should contain profiling tooling."
        }
        "container_file" => "Defines which Containerfile the benchmark image build should use.",
        "image_name" => "Defines the container image repository name for the benchmark image.",
        "image_tag" => "Defines the container image tag used for this generated suite.",
        "rebuild_policy" => "Defines when the runner is allowed to rebuild the benchmark image.",
        "build_args" => "Defines additional build arguments passed into the benchmark image build.",
        "http_server" => {
            "Defines which application server implementation the benchmark image should run."
        }
        "runtime_host" => {
            "Defines which host address the app binds to inside the benchmark container."
        }
        "transport_type" => {
            "Defines which gateway transport path the benchmark traffic should exercise."
        }
        "gunicorn_workers" => "Defines how many Gunicorn worker processes should be launched.",
        "gunicorn_timeout" => "Defines Gunicorn's timeout for slow requests and worker startup.",
        "gunicorn_graceful_timeout" => "Defines Gunicorn's graceful shutdown timeout.",
        "gunicorn_keep_alive" => "Defines how long Gunicorn keeps idle connections open.",
        "gunicorn_max_requests" => "Defines Gunicorn's worker recycling request limit.",
        "gunicorn_max_requests_jitter" => {
            "Defines the jitter applied to Gunicorn worker recycling."
        }
        "gunicorn_backlog" => "Defines the Gunicorn listen backlog size.",
        "gunicorn_preload_app" => {
            "Defines whether Gunicorn preloads the application before forking."
        }
        "gunicorn_dev_mode" => "Defines whether Gunicorn should use development-friendly behavior.",
        "granian_workers" => "Defines how many Granian worker processes should be launched.",
        "granian_runtime_mode" => "Defines Granian's runtime execution mode.",
        "granian_runtime_threads" => "Defines how many runtime threads each Granian worker uses.",
        "granian_blocking_threads" => "Defines how many blocking helper threads Granian can use.",
        "granian_http" => "Defines which Granian HTTP stack should be used.",
        "granian_loop" => "Defines which event loop implementation Granian should use.",
        "granian_task_impl" => "Defines which async task runtime Granian should use internally.",
        "granian_http1_pipeline_flush" => {
            "Defines whether Granian flushes pipelined HTTP/1 responses aggressively."
        }
        "granian_http1_buffer_size" => "Defines the Granian HTTP/1 input buffer size.",
        "granian_backlog" => "Defines the Granian listen backlog size.",
        "granian_backpressure" => "Defines Granian's in-flight backpressure threshold.",
        "granian_respawn_failed" => {
            "Defines whether failed Granian workers are restarted automatically."
        }
        "granian_workers_lifetime" => "Defines a maximum lifetime for Granian workers.",
        "granian_workers_max_rss" => "Defines an RSS threshold for Granian worker recycling.",
        "granian_dev_mode" => "Defines whether Granian should use development-friendly behavior.",
        "granian_log_level" => "Defines Granian's server log level.",
        "uvicorn_workers" => "Defines how many Uvicorn worker processes should be launched.",
        "uvicorn_loop" => "Defines which event loop implementation Uvicorn should use.",
        "uvicorn_http" => "Defines which HTTP parser Uvicorn should use.",
        "uvicorn_backlog" => "Defines the Uvicorn listen backlog size.",
        "uvicorn_timeout_keep_alive" => "Defines Uvicorn's keep-alive timeout.",
        "uvicorn_limit_max_requests" => "Defines Uvicorn's worker recycling request limit.",
        "uvicorn_log_level" => "Defines Uvicorn's server log level.",
        "uvicorn_dev_mode" => "Defines whether Uvicorn should use development-friendly behavior.",
        "trust_proxy_auth" => {
            "Defines whether proxy-provided auth headers are trusted by the gateway."
        }
        "disable_access_log" => {
            "Defines whether request access logging is disabled during the run."
        }
        "templates_auto_reload" => {
            "Defines whether templates auto-reload during the benchmark run."
        }
        "structured_logging_database_enabled" => {
            "Defines whether structured database logging is enabled."
        }
        "sqlalchemy_echo" => "Defines whether SQLAlchemy emits SQL statements to logs.",
        "gateway_log_level" => "Defines the gateway application's log verbosity.",
        "gateway_environment" => {
            "Defines extra environment variables injected into the gateway container."
        }
        "target_service" => "Defines which compose service receives benchmark traffic.",
        "driver" => "Defines which Rust benchmark driver binary is invoked for load generation.",
        "headless" => "Defines whether the load driver should minimize interactive output.",
        "only_summary" => {
            "Defines whether the load driver should prefer summary output over verbose logs."
        }
        "html_report" => "Defines whether the run should emit an HTML report artifact.",
        "users" => "Defines the target number of concurrent simulated users.",
        "spawn_rate" => "Defines how quickly those simulated users are started.",
        "run_time" => "Defines the total wall-clock duration of the benchmark run.",
        "request_count" => "Defines an explicit request-count stop condition for the run.",
        "load_host" => "Defines an explicit host URL override for the load driver.",
        "seed" => "Defines the random seed used when workload selection is randomized.",
        "tags" => "Defines which tagged request-catalog entries should stay eligible.",
        "exclude_tags" => "Defines which tagged request-catalog entries should be excluded.",
        "load_extra_args" => "Defines raw CLI flags appended to the load driver invocation.",
        "load_env" => "Defines extra environment variables passed to the load driver.",
        "workload_selection" => "Defines how workload endpoints are selected or mixed.",
        "fallback_endpoint" => "Defines the endpoint used when no other workload target is chosen.",
        "workload_endpoints" => {
            "Defines explicit endpoint weights and enablement for the workload mix."
        }
        "warmup_seconds" => "Defines how long the suite warms up before measuring.",
        "measure_seconds" => "Defines how long the primary metrics window lasts.",
        "profile_seconds" => "Defines how long the dedicated profiling window lasts.",
        "cooldown_seconds" => "Defines how long the suite cools down after measurement ends.",
        "enabled_groups" => "Defines which request-catalog groups are explicitly kept.",
        "disabled_groups" => "Defines which request-catalog groups are explicitly removed.",
        "enabled_endpoints" => "Defines which request-catalog endpoints are explicitly kept.",
        "disabled_endpoints" => "Defines which request-catalog endpoints are explicitly removed.",
        "enabled_tags" => "Defines which request-catalog tags are explicitly kept.",
        "disabled_tags" => "Defines which request-catalog tags are explicitly removed.",
        "include_admin_endpoints" => {
            "Defines whether admin endpoints remain eligible in request selection."
        }
        "include_mcp_endpoints" => {
            "Defines whether MCP endpoints remain eligible in request selection."
        }
        "include_resource_endpoints" => {
            "Defines whether resource endpoints remain eligible in request selection."
        }
        "include_prompt_endpoints" => {
            "Defines whether prompt endpoints remain eligible in request selection."
        }
        "include_tool_endpoints" => {
            "Defines whether tool endpoints remain eligible in request selection."
        }
        "profiling_enabled" => {
            "Defines whether profiling behavior is active for the generated suite."
        }
        "profiling_tools" => "Defines which profiling tools the suite should request.",
        "profiling_duration_seconds" => "Defines how long profiling should run when enabled.",
        "profiling_required" => {
            "Defines whether missing profiling artifacts should fail the scenario."
        }
        "retry_enabled" => "Defines whether failed scenarios should be retried automatically.",
        "max_attempts" => "Defines the maximum number of attempts allowed for a scenario.",
        "capture_logs" => "Defines whether logs are captured into benchmark artifacts.",
        "save_raw_results" => "Defines whether raw result files are preserved after a run.",
        "reuse_stack" => "Defines whether scenarios are allowed to reuse the same running stack.",
        "defaults_plugins_snippet" => {
            "Defines a raw plugin configuration snippet under the defaults block."
        }
        "scenario_setup_snippet" => "Defines a raw setup override for the generated scenario.",
        "scenario_build_snippet" => "Defines a raw build override for the generated scenario.",
        "scenario_runtime_snippet" => "Defines a raw runtime override for the generated scenario.",
        "scenario_gateway_snippet" => "Defines a raw gateway override for the generated scenario.",
        "scenario_load_snippet" => "Defines a raw load override for the generated scenario.",
        "scenario_measurement_snippet" => {
            "Defines a raw measurement override for the generated scenario."
        }
        "scenario_requests_snippet" => {
            "Defines a raw request-selection override for the generated scenario."
        }
        "scenario_profiling_snippet" => {
            "Defines a raw profiling override for the generated scenario."
        }
        "scenario_execution_snippet" => {
            "Defines a raw execution override for the generated scenario."
        }
        "scenario_plugins_snippet" => "Defines a raw plugin override for the generated scenario.",
        _ => "Defines a generator field.",
    }
}

fn generator_change_reason(key: &str) -> &'static str {
    match key {
        "file_stem" => "Changing it changes which scenario file is created or overwritten.",
        "template_kind" => {
            "Changing it swaps in a different preset workload shape and default values."
        }
        "suite_name" => "Changing it changes the suite title shown in metadata and reports.",
        "suite_description" => {
            "Changing it changes the explanation operators read in the console and TOML."
        }
        "output_root" => "Changing it moves where reports and artifacts are written.",
        "continue_on_failure" => {
            "Changing it changes whether later scenarios still run after an earlier failure."
        }
        "save_intermediate_artifacts" => {
            "Changing it changes whether transient artifacts are preserved."
        }
        "flamegraph_enabled" => {
            "Changing it changes whether flamegraph-oriented suite behavior is expected."
        }
        "baseline_run" => {
            "Changing it points the suite at a different saved run to treat as the benchmark baseline."
        }
        "baseline_rps_drop_pct" => {
            "Changing it makes the suite more or less strict about tolerated throughput loss."
        }
        "baseline_p95_regression_pct" => {
            "Changing it makes the suite more or less strict about tolerated p95 latency regression."
        }
        "baseline_failure_increase" => {
            "Changing it makes the suite more or less strict about tolerated failure-rate increase."
        }
        "scenario_name" => "Changing it renames the generated scenario in reports and logs.",
        "scenario_description" => "Changing it changes how the scenario is explained to operators.",
        "scenario_type" => "Changing it changes how the scenario is categorized downstream.",
        "target_kind" => {
            "Changing it changes whether the generated scenario targets gateway or agent behavior."
        }
        "auth_mode" => "Changing it changes which auth path the scenario is configured to use.",
        "plugins_enabled" => {
            "Changing it changes whether plugin-specific fields and setup matter in the template."
        }
        "expected_mcp_runtime" => {
            "Changing it changes the MCP runtime assertion recorded in the scenario."
        }
        "expected_mcp_runtime_mode" => "Changing it changes the asserted MCP runtime mode.",
        "expected_a2a_runtime" => {
            "Changing it changes the A2A runtime assertion recorded in the scenario."
        }
        "rust_plugins" => {
            "Changing it changes whether Rust plugin artifacts are built into the benchmark image."
        }
        "profiling_image" => {
            "Changing it changes whether profiling tooling is installed into the benchmark image."
        }
        "container_file" => "Changing it changes which image definition file the build uses.",
        "image_name" => "Changing it changes the image repository name used during build and run.",
        "image_tag" => "Changing it changes which benchmark image tag is built or reused.",
        "rebuild_policy" => "Changing it changes when the runner rebuilds the benchmark image.",
        "build_args" => {
            "Changing it changes the build-time feature flags or values passed into the image build."
        }
        "http_server" => "Changing it switches the server implementation under the same workload.",
        "runtime_host" => {
            "Changing it changes which interface the app binds to inside the container."
        }
        "transport_type" => {
            "Changing it changes which gateway transport path the load test exercises."
        }
        "gunicorn_workers" => "Changing it changes Gunicorn process concurrency.",
        "gunicorn_timeout" => {
            "Changing it changes how long Gunicorn waits before timing out slow work."
        }
        "gunicorn_graceful_timeout" => "Changing it changes Gunicorn shutdown grace periods.",
        "gunicorn_keep_alive" => "Changing it changes Gunicorn keep-alive behavior.",
        "gunicorn_max_requests" => "Changing it changes Gunicorn worker recycling frequency.",
        "gunicorn_max_requests_jitter" => {
            "Changing it changes how staggered Gunicorn worker recycling is."
        }
        "gunicorn_backlog" => {
            "Changing it changes how many pending connections Gunicorn can queue."
        }
        "gunicorn_preload_app" => {
            "Changing it changes whether the app is loaded once before workers fork."
        }
        "gunicorn_dev_mode" => {
            "Changing it changes whether Gunicorn behaves more like development mode."
        }
        "granian_workers" => "Changing it changes Granian process concurrency.",
        "granian_runtime_mode" => "Changing it changes how Granian executes async work.",
        "granian_runtime_threads" => {
            "Changing it changes how many runtime threads each Granian worker gets."
        }
        "granian_blocking_threads" => {
            "Changing it changes how much blocking work Granian can offload."
        }
        "granian_http" => "Changing it changes the Granian HTTP protocol stack.",
        "granian_loop" => "Changing it changes the event loop implementation Granian uses.",
        "granian_task_impl" => "Changing it changes the async runtime Granian uses internally.",
        "granian_http1_pipeline_flush" => "Changing it changes Granian's HTTP/1 flush behavior.",
        "granian_http1_buffer_size" => "Changing it changes Granian's HTTP/1 buffering behavior.",
        "granian_backlog" => "Changing it changes how many pending connections Granian can queue.",
        "granian_backpressure" => "Changing it changes when Granian starts applying backpressure.",
        "granian_respawn_failed" => {
            "Changing it changes whether failed Granian workers come back automatically."
        }
        "granian_workers_lifetime" => {
            "Changing it changes how often Granian workers recycle by age."
        }
        "granian_workers_max_rss" => {
            "Changing it changes when Granian workers recycle for memory growth."
        }
        "granian_dev_mode" => {
            "Changing it changes whether Granian behaves more like development mode."
        }
        "granian_log_level" => "Changing it changes Granian's server log verbosity.",
        "uvicorn_workers" => "Changing it changes Uvicorn process concurrency.",
        "uvicorn_loop" => "Changing it changes the event loop implementation Uvicorn uses.",
        "uvicorn_http" => "Changing it changes the HTTP parser Uvicorn uses.",
        "uvicorn_backlog" => "Changing it changes how many pending connections Uvicorn can queue.",
        "uvicorn_timeout_keep_alive" => "Changing it changes Uvicorn keep-alive behavior.",
        "uvicorn_limit_max_requests" => "Changing it changes Uvicorn worker recycling frequency.",
        "uvicorn_log_level" => "Changing it changes Uvicorn's server log verbosity.",
        "uvicorn_dev_mode" => {
            "Changing it changes whether Uvicorn behaves more like development mode."
        }
        "trust_proxy_auth" => {
            "Changing it changes whether proxy auth headers are accepted as authoritative."
        }
        "disable_access_log" => {
            "Changing it changes whether access logs are emitted during the run."
        }
        "templates_auto_reload" => "Changing it changes whether template files auto-reload.",
        "structured_logging_database_enabled" => {
            "Changing it changes whether structured logs are written to the database."
        }
        "sqlalchemy_echo" => "Changing it changes whether SQL statements appear in logs.",
        "gateway_log_level" => "Changing it changes gateway log volume.",
        "gateway_environment" => {
            "Changing it changes which environment variables are injected into the gateway container."
        }
        "target_service" => "Changing it changes which service the load generator targets.",
        "driver" => "Changing it changes which benchmark driver binary is executed.",
        "headless" => "Changing it changes how interactive the load output is.",
        "only_summary" => "Changing it changes how much output the load run prints.",
        "html_report" => "Changing it changes whether an HTML report is requested.",
        "users" => "Changing it changes target concurrency.",
        "spawn_rate" => "Changing it changes ramp-up speed.",
        "run_time" => "Changing it changes total benchmark duration.",
        "request_count" => "Changing it changes whether the run stops after a fixed request total.",
        "load_host" => "Changing it changes which host URL the load driver calls.",
        "seed" => "Changing it changes the workload randomization sequence.",
        "tags" => "Changing it changes which tagged requests remain active.",
        "exclude_tags" => "Changing it changes which tagged requests are filtered out.",
        "load_extra_args" => "Changing it changes the raw flags appended to the driver command.",
        "load_env" => "Changing it changes the environment passed to the load driver.",
        "workload_selection" => "Changing it changes how request targets are selected or weighted.",
        "fallback_endpoint" => "Changing it changes the default endpoint used by the workload.",
        "workload_endpoints" => "Changing it changes explicit endpoint weighting and enablement.",
        "warmup_seconds" => {
            "Changing it changes how long the run warms up before measurement starts."
        }
        "measure_seconds" => "Changing it changes how long the primary metrics window lasts.",
        "profile_seconds" => "Changing it changes how long profiling stays active.",
        "cooldown_seconds" => "Changing it changes how long the run cools down before teardown.",
        "enabled_groups" => {
            "Changing it changes which request groups are allowed into the workload."
        }
        "disabled_groups" => {
            "Changing it changes which request groups are removed from the workload."
        }
        "enabled_endpoints" => "Changing it changes which endpoints are kept in the workload.",
        "disabled_endpoints" => {
            "Changing it changes which endpoints are removed from the workload."
        }
        "enabled_tags" => "Changing it changes which tagged endpoints remain active.",
        "disabled_tags" => "Changing it changes which tagged endpoints are removed.",
        "include_admin_endpoints" => "Changing it changes whether admin endpoints remain eligible.",
        "include_mcp_endpoints" => "Changing it changes whether MCP endpoints remain eligible.",
        "include_resource_endpoints" => {
            "Changing it changes whether resource endpoints remain eligible."
        }
        "include_prompt_endpoints" => {
            "Changing it changes whether prompt endpoints remain eligible."
        }
        "include_tool_endpoints" => "Changing it changes whether tool endpoints remain eligible.",
        "profiling_enabled" => "Changing it turns profiling behavior on or off.",
        "profiling_tools" => "Changing it changes which profiling tools the suite requests.",
        "profiling_duration_seconds" => "Changing it changes requested profiling duration.",
        "profiling_required" => "Changing it changes whether missing profiles fail the scenario.",
        "retry_enabled" => "Changing it changes whether failed scenarios are retried.",
        "max_attempts" => "Changing it changes how many attempts the runner may make.",
        "capture_logs" => "Changing it changes whether logs are captured into artifacts.",
        "save_raw_results" => "Changing it changes whether raw result files are preserved.",
        "reuse_stack" => "Changing it changes whether scenarios can reuse the same running stack.",
        "defaults_plugins_snippet" => {
            "Changing it changes the raw plugin configuration written into the defaults block."
        }
        "scenario_setup_snippet" => {
            "Changing it changes only the scenario-specific setup override."
        }
        "scenario_build_snippet" => {
            "Changing it changes only the scenario-specific build override."
        }
        "scenario_runtime_snippet" => {
            "Changing it changes only the scenario-specific runtime override."
        }
        "scenario_gateway_snippet" => {
            "Changing it changes only the scenario-specific gateway override."
        }
        "scenario_load_snippet" => "Changing it changes only the scenario-specific load override.",
        "scenario_measurement_snippet" => {
            "Changing it changes only the scenario-specific measurement override."
        }
        "scenario_requests_snippet" => {
            "Changing it changes only the scenario-specific request-selection override."
        }
        "scenario_profiling_snippet" => {
            "Changing it changes only the scenario-specific profiling override."
        }
        "scenario_execution_snippet" => {
            "Changing it changes only the scenario-specific execution override."
        }
        "scenario_plugins_snippet" => {
            "Changing it changes only the scenario-specific plugin override."
        }
        _ => "Changing it changes the generated benchmark template.",
    }
}

fn generator_visibility_note(key: &str) -> &'static str {
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

fn generator_example(key: &str) -> &'static str {
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
        "container_file" => "tools_rust/contextforge_benchmark/assets/Containerfile",
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

fn draw_help(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let help = match app.mode {
        InputMode::EditRunPath | InputMode::EditExtraArgs | InputMode::EditGeneratorField => {
            "Type text, Backspace deletes, Enter saves, Esc cancels"
        }
        InputMode::Normal if app.active_view == AppView::Generator => {
            "Tab/BackTab: switch view  1-8/left-right: action  [ ] or PgUp/PgDn: section  j/k: field  e/Enter: edit  t: toggle/cycle  g or s: save template  q: quit"
        }
        _ => {
            "Tab/BackTab: switch view  1-8/left-right: action  j/k: suite (launcher/inspector)  i: inspector  m: monitor  l: launcher  a: all  c: clean  p: run path  e: extra args  PgUp/PgDn or [ ]: scroll logs in monitor  Enter/r: run  q: quit"
        }
    };
    let widget = Paragraph::new(help)
        .block(Block::default().borders(Borders::ALL).title("Keys"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn discovers_suite_metadata_with_description() {
        let tempdir = std::env::temp_dir().join("benchmark-console-suite-metadata");
        let _ = std::fs::remove_dir_all(&tempdir);
        std::fs::create_dir_all(tempdir.join("tools_rust/contextforge_benchmark/assets/scenarios"))
            .unwrap();
        std::fs::write(
            tempdir.join("tools_rust/contextforge_benchmark/assets/scenarios/example-suite.toml"),
            r#"
[suite]
name = "benchmark-example-suite"
description = "Explains what this benchmark covers and what comparison it is meant to answer."
"#,
        )
        .unwrap();

        let suites = discover_scenarios(&tempdir).unwrap();
        assert_eq!(suites.len(), 1);
        assert_eq!(suites[0].file_stem, "example-suite");
        assert_eq!(suites[0].suite_name, "benchmark-example-suite");
        assert!(suites[0].description.contains("what this benchmark covers"));

        let _ = std::fs::remove_dir_all(&tempdir);
    }

    #[test]
    fn preview_summary_includes_run_plan_execution_and_checks() {
        let tempdir = std::env::temp_dir().join("benchmark-console-preview-summary");
        let _ = std::fs::remove_dir_all(&tempdir);
        std::fs::create_dir_all(tempdir.join("tools_rust/contextforge_benchmark/assets/scenarios"))
            .unwrap();
        std::fs::write(
            tempdir.join("tools_rust/contextforge_benchmark/assets/scenarios/example-suite.toml"),
            r#"
[suite]
name = "benchmark-example-suite"
description = "Exercises a representative benchmark flow."

[[scenario]]
name = "baseline-scenario"

[[scenario]]
name = "variant-scenario"
"#,
        )
        .unwrap();

        let mut app = App::new(discover_scenarios(&tempdir).unwrap());
        app.action_index = 0;
        app.clean = true;
        app.extra_args = "--smoke-note enabled".to_string();

        let preview = build_preview_sections(&app, &tempdir).unwrap();

        assert!(
            preview
                .run_plan
                .iter()
                .any(|line| line.contains("benchmark-example-suite"))
        );
        assert!(
            preview
                .run_plan
                .iter()
                .any(|line| line.contains("2 scenario(s)"))
        );
        assert!(
            preview
                .run_plan
                .iter()
                .any(|line| line.contains("baseline-scenario vs variant-scenario"))
        );
        assert!(
            preview
                .execution
                .iter()
                .any(|line| line.contains("cargo run --manifest-path"))
        );
        assert!(
            preview
                .checks
                .iter()
                .any(|line| line.contains("Clean-first is enabled"))
        );
        assert!(
            preview
                .checks
                .iter()
                .any(|line| line.contains("Extra args will be appended"))
        );

        let _ = std::fs::remove_dir_all(&tempdir);
    }

    #[test]
    fn selection_summary_tracks_toggle_state_and_inputs() {
        let mut app = App::new(vec![SuiteSummary {
            file_stem: "rest-discovery-300".to_string(),
            suite_name: "benchmark-rest-discovery".to_string(),
            description: "Exercises discovery endpoints.".to_string(),
        }]);
        app.all = true;
        app.clean = true;
        app.extra_args = "--profile brief".to_string();

        let summary = build_selection_summary(&app);

        assert_eq!(summary.action_label, "Run");
        assert_eq!(summary.suite_label, "rest-discovery-300");
        assert_eq!(summary.run_mode_label, "all-scenarios");
        assert_eq!(summary.clean_label, "yes");
        assert_eq!(summary.extra_args_label, "--profile brief");
    }

    #[test]
    fn app_view_switching_tracks_generator_and_monitor_modes() {
        let mut app = App::new(Vec::new());
        assert_eq!(app.active_view, AppView::Launcher);

        app.set_view(AppView::SuiteInspector);
        assert_eq!(app.active_view, AppView::SuiteInspector);

        app.set_view(AppView::Generator);
        assert_eq!(app.active_view, AppView::Generator);
        assert_eq!(app.action(), Action::Generate);

        app.set_view(AppView::Launcher);
        assert_eq!(app.active_view, AppView::Launcher);
        assert_ne!(app.action(), Action::Generate);
    }

    #[test]
    fn suite_navigation_is_blocked_outside_suite_focused_views() {
        let mut app = App::new(vec![
            SuiteSummary {
                file_stem: "suite-one".to_string(),
                suite_name: "suite-one".to_string(),
                description: "First suite".to_string(),
            },
            SuiteSummary {
                file_stem: "suite-two".to_string(),
                suite_name: "suite-two".to_string(),
                description: "Second suite".to_string(),
            },
        ]);
        let root = std::env::temp_dir();
        let mut terminal = Terminal::new(CrosstermBackend::new(std::io::stdout())).unwrap();

        app.set_view(AppView::RunMonitor);
        handle_normal_mode(
            &mut app,
            KeyEvent::from(KeyCode::Char('j')),
            &root,
            &mut terminal,
        )
        .unwrap();
        assert_eq!(app.scenario_index, 0);

        app.set_view(AppView::SuiteInspector);
        handle_normal_mode(
            &mut app,
            KeyEvent::from(KeyCode::Char('j')),
            &root,
            &mut terminal,
        )
        .unwrap();
        assert_eq!(app.scenario_index, 1);

        let _ = terminal.show_cursor();
    }

    #[test]
    fn suite_inspector_summary_builds_scenario_cards_with_settings() {
        let tempdir = std::env::temp_dir().join("benchmark-console-suite-inspector");
        let _ = std::fs::remove_dir_all(&tempdir);
        std::fs::create_dir_all(tempdir.join("tools_rust/contextforge_benchmark/assets/scenarios"))
            .unwrap();
        std::fs::write(
            tempdir.join("tools_rust/contextforge_benchmark/assets/scenarios/example-suite.toml"),
            r#"
[suite]
name = "benchmark-example-suite"
description = "Compare Python and Rust runtime paths."

[defaults.setup]
plugins_enabled = false

[defaults.build]
rust_plugins = false

[[scenario]]
name = "baseline-scenario"
description = "Python baseline"
scenario_type = "baseline"

[[scenario]]
name = "rust-scenario"
description = "Rust comparison"
scenario_type = "compare"

[scenario.setup]
expected_mcp_runtime = "rust"
expected_mcp_runtime_mode = "rust-managed"

[scenario.build]
rust_plugins = true

[scenario.gateway.environment]
EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED = "true"
RUST_MCP_MODE = "edge"
"#,
        )
        .unwrap();

        let app = App::new(discover_scenarios(&tempdir).unwrap());
        let summary = build_suite_inspector_summary(&app, &tempdir).unwrap();

        assert_eq!(summary.scenario_cards.len(), 2);
        assert_eq!(summary.scenario_cards[0].name, "baseline-scenario");
        assert!(
            summary.scenario_cards[1]
                .settings
                .iter()
                .any(|(key, value)| key == "expected_mcp_runtime" && value == "rust")
        );
        assert!(
            summary.scenario_cards[0]
                .settings
                .iter()
                .any(|(key, value)| key == "rust_plugins" && value == "false")
        );
        assert!(
            summary.scenario_cards[1]
                .settings
                .iter()
                .any(|(key, value)| key == "RUST_MCP_MODE" && value == "edge")
        );

        let _ = std::fs::remove_dir_all(&tempdir);
    }

    #[test]
    fn generator_focus_summary_exposes_field_guidance() {
        let app = App::new(Vec::new());
        let summary = build_generator_focus_summary(&app);

        assert_eq!(summary.section_filter, "All");
        assert_eq!(summary.field_label, "File Stem");
        assert_eq!(summary.config_key, "output file name");
        assert!(summary.purpose.contains("filename"));
        assert!(summary.effect.contains("scenario file"));
        assert!(summary.example.contains("a2a-invoke-300"));
    }

    #[test]
    fn every_generator_field_has_specific_purpose_and_effect_copy() {
        let generator = GeneratorState::new();
        for field in &generator.fields {
            let purpose = generator_explanation(field.key);
            let effect = generator_change_reason(field.key);
            assert!(
                !purpose.contains("maps directly to the benchmark scenario schema"),
                "generic purpose for {}",
                field.key
            );
            assert_ne!(
                purpose, "Defines a generator field.",
                "fallback purpose for {}",
                field.key
            );
            assert!(
                !effect.contains("default generated value does not match"),
                "generic effect for {}",
                field.key
            );
            assert_ne!(
                effect, "Changing it changes the generated benchmark template.",
                "fallback effect for {}",
                field.key
            );
        }
    }

    #[test]
    fn generator_template_uses_rust_only_defaults() {
        let generator = GeneratorState::new();
        let template = generate_template_toml(&generator);

        assert!(template.contains("driver = "));
        assert!(template.contains("tools = [\"perf\", \"flamegraph\"]"));
        assert!(!template.contains("repo_url = "));
        assert!(!template.contains("git_ref = "));
        assert!(!template.contains("git_commit = "));
    }

    #[test]
    fn generator_metadata_uses_rust_profiling_field_names() {
        assert_eq!(generator_section("driver"), "Load");
        assert_eq!(generator_config_path("driver"), "defaults.load.driver");
        assert!(generator_example("driver").contains("contextforge_goose"));
        assert!(generator_example("profiling_tools").contains("perf,flamegraph"));
        assert!(generator_example("scenario_profiling_snippet").contains("perf"));
    }

    #[test]
    fn app_log_buffer_keeps_recent_entries_and_updates_status() {
        let mut app = App::new(Vec::new());
        app.push_log_line(LogSource::Stdout, "first line".to_string());
        for index in 0..520 {
            app.push_log_line(LogSource::Stdout, format!("line {index}"));
        }

        assert_eq!(app.log_lines.len(), MAX_LOG_LINES);
        assert!(
            app.log_lines
                .last()
                .map(|line| line.text.as_str())
                .unwrap_or_default()
                .contains("line 519")
        );
        assert_eq!(app.dropped_log_lines, 21);
        assert!(app.status.contains("line 519"));
    }

    #[test]
    fn progress_parsing_tracks_failed_scenarios_and_run_outcome() {
        let mut app = App::new(Vec::new());
        app.push_log_line(
            LogSource::System,
            "[benchmark] Scenario 2/4 starting: gunicorn-rest-discovery-rust-runtime".to_string(),
        );
        app.push_log_line(
            LogSource::System,
            "[benchmark] Scenario 'gunicorn-rest-discovery-rust-runtime' failed: compose command failed".to_string(),
        );
        app.push_log_line(
            LogSource::System,
            "[benchmark] Benchmark run completed with failed scenarios [gunicorn-rest-discovery-rust-runtime]: reports/benchmarks/example".to_string(),
        );

        assert_eq!(app.current_run_scenario, None);
        assert_eq!(
            app.run_scenarios,
            vec![RunScenarioSummary {
                name: "gunicorn-rest-discovery-rust-runtime".to_string(),
                status: "failed".to_string(),
            }]
        );
        assert_eq!(app.last_run_outcome.as_deref(), Some("failed"));
        assert_eq!(
            app.last_run_dir.as_deref(),
            Some("reports/benchmarks/example")
        );
    }

    #[test]
    fn launcher_command_runs_inside_console_capture() {
        let mut app = App::new(vec![SuiteSummary {
            file_stem: "rest-discovery-300".to_string(),
            suite_name: "benchmark-rest-discovery".to_string(),
            description: "Exercises discovery endpoints.".to_string(),
        }]);
        let command = CommandSpec {
            command: "sh".to_string(),
            args: vec![
                "-c".to_string(),
                "printf 'hello from stdout\\n'; printf 'hello from stderr\\n' >&2".to_string(),
            ],
            env: vec![],
        };

        start_command_capture(&mut app, command, Path::new(".")).unwrap();
        for _ in 0..40 {
            drain_running_command(&mut app).unwrap();
            if app.running_command.is_none() {
                break;
            }
            std::thread::sleep(Duration::from_millis(25));
        }

        assert!(app.running_command.is_none());
        assert_eq!(app.active_view, AppView::RunMonitor);
        let combined = app
            .log_lines
            .iter()
            .map(|line| line.text.as_str())
            .collect::<Vec<_>>()
            .join("\n");
        assert!(combined.contains("hello from stdout"));
        assert!(combined.contains("hello from stderr"));
        assert!(app.status.contains("finished"));
    }

    #[test]
    fn start_command_capture_resets_run_monitor_state() {
        let mut app = App::new(vec![SuiteSummary {
            file_stem: "rest-discovery-300".to_string(),
            suite_name: "benchmark-rest-discovery".to_string(),
            description: "Exercises discovery endpoints.".to_string(),
        }]);
        app.log_lines.push(LogLine {
            source: LogSource::System,
            text: "old log".to_string(),
        });
        app.dropped_log_lines = 9;
        app.last_run_outcome = Some("failed".to_string());
        app.last_run_dir = Some("reports/benchmarks/old".to_string());
        app.run_scenarios.push(RunScenarioSummary {
            name: "old-scenario".to_string(),
            status: "failed".to_string(),
        });

        let command = CommandSpec {
            command: "sh".to_string(),
            args: vec!["-c".to_string(), "printf 'hello\\n'".to_string()],
            env: vec![],
        };

        start_command_capture(&mut app, command, Path::new(".")).unwrap();

        assert_eq!(app.dropped_log_lines, 0);
        assert_eq!(app.last_run_outcome, None);
        assert_eq!(app.last_run_dir, None);
        assert!(app.run_scenarios.is_empty());
        assert_eq!(app.log_scroll, 0);
        assert_eq!(app.log_lines.len(), 1);
        assert!(app.log_lines[0].text.contains("Started command inside console"));
    }
}
