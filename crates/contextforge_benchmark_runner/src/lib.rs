use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const DEFAULT_SCENARIO_DIR: &str = "crates/contextforge_benchmark_runner/assets/scenarios";
pub const DEFAULT_OUTPUT_ROOT: &str = "reports/benchmarks";
pub const DEFAULT_GOSE_BIN: &str = "contextforge_goose";

fn log_progress(message: impl AsRef<str>) {
    println!("[benchmark] {}", message.as_ref());
    let _ = std::io::stdout().flush();
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SuiteDocument {
    pub suite: SuiteMeta,
    #[serde(default)]
    pub defaults: ScenarioTemplate,
    #[serde(default)]
    pub scenario: Vec<ScenarioEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SuiteMeta {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default = "default_output_root")]
    pub output_root: String,
    #[serde(default)]
    pub continue_on_failure: bool,
    #[serde(default)]
    pub save_intermediate_artifacts: bool,
    #[serde(default)]
    pub flamegraph_enabled: bool,
    #[serde(default)]
    pub baseline_run: Option<String>,
    #[serde(default)]
    pub baseline_rps_drop_pct: Option<f64>,
    #[serde(default)]
    pub baseline_p95_regression_pct: Option<f64>,
    #[serde(default)]
    pub baseline_failure_increase: Option<f64>,
}

fn default_output_root() -> String {
    DEFAULT_OUTPUT_ROOT.to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ScenarioTemplate {
    #[serde(default)]
    pub setup: SetupConfig,
    #[serde(default)]
    pub build: BuildConfig,
    #[serde(default)]
    pub runtime: RuntimeConfig,
    #[serde(default)]
    pub gateway: GatewayConfig,
    #[serde(default)]
    pub load: LoadConfig,
    #[serde(default)]
    pub measurement: MeasurementConfig,
    #[serde(default)]
    pub profiling: ProfilingConfig,
    #[serde(default)]
    pub execution: ExecutionConfig,
    #[serde(default)]
    pub requests: RequestsConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ScenarioEntry {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub scenario_type: String,
    #[serde(default)]
    pub setup: SetupConfig,
    #[serde(default)]
    pub build: BuildConfig,
    #[serde(default)]
    pub runtime: RuntimeConfig,
    #[serde(default)]
    pub gateway: GatewayConfig,
    #[serde(default)]
    pub load: LoadConfig,
    #[serde(default)]
    pub measurement: MeasurementConfig,
    #[serde(default)]
    pub profiling: ProfilingConfig,
    #[serde(default)]
    pub execution: ExecutionConfig,
    #[serde(default)]
    pub requests: RequestsConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SetupConfig {
    #[serde(default)]
    pub target_kind: String,
    #[serde(default)]
    pub auth_mode: String,
    #[serde(default)]
    pub plugins_enabled: bool,
    #[serde(default)]
    pub expected_mcp_runtime: Option<String>,
    #[serde(default)]
    pub expected_mcp_runtime_mode: Option<String>,
    #[serde(default)]
    pub expected_a2a_runtime: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct BuildConfig {
    #[serde(default)]
    pub rust_plugins: bool,
    #[serde(default)]
    pub profiling_image: bool,
    #[serde(default)]
    pub container_file: String,
    #[serde(default)]
    pub image_name: String,
    #[serde(default)]
    pub image_tag: String,
    #[serde(default)]
    pub rebuild_policy: String,
    #[serde(default)]
    pub args: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RuntimeConfig {
    #[serde(default)]
    pub http_server: String,
    #[serde(default)]
    pub host: String,
    #[serde(default)]
    pub transport_type: String,
    #[serde(default)]
    pub gunicorn: GunicornConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GunicornConfig {
    #[serde(default)]
    pub workers: Option<i64>,
    #[serde(default)]
    pub timeout: Option<i64>,
    #[serde(default)]
    pub graceful_timeout: Option<i64>,
    #[serde(default)]
    pub keep_alive: Option<i64>,
    #[serde(default)]
    pub max_requests: Option<i64>,
    #[serde(default)]
    pub max_requests_jitter: Option<i64>,
    #[serde(default)]
    pub backlog: Option<i64>,
    #[serde(default)]
    pub preload_app: Option<bool>,
    #[serde(default)]
    pub dev_mode: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GatewayConfig {
    #[serde(default)]
    pub disable_access_log: bool,
    #[serde(default)]
    pub templates_auto_reload: bool,
    #[serde(default)]
    pub structured_logging_database_enabled: bool,
    #[serde(default)]
    pub sqlalchemy_echo: bool,
    #[serde(default)]
    pub log_level: String,
    #[serde(default)]
    pub trust_proxy_auth: bool, // pragma: allowlist secret
    #[serde(default)]
    pub environment: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LoadConfig {
    #[serde(default = "default_driver")]
    pub driver: String,
    #[serde(default)]
    pub headless: bool,
    #[serde(default)]
    pub only_summary: bool,
    #[serde(default)]
    pub html_report: bool,
    #[serde(default)]
    pub users: Option<u32>,
    #[serde(default)]
    pub spawn_rate: Option<u32>,
    #[serde(default)]
    pub run_time: Option<String>,
    #[serde(default)]
    pub request_count: Option<u32>,
    #[serde(default)]
    pub seed: Option<u64>,
    #[serde(default)]
    pub target_service: String,
    #[serde(default)]
    pub host: Option<String>,
    #[serde(default)]
    pub extra_args: Vec<String>,
    #[serde(default)]
    pub env: BTreeMap<String, String>,
    #[serde(default)]
    pub workload: WorkloadConfig,
}

fn default_driver() -> String {
    DEFAULT_GOSE_BIN.to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct WorkloadConfig {
    #[serde(default)]
    pub fallback_endpoint: Option<String>,
    #[serde(default)]
    pub endpoints: BTreeMap<String, EndpointOverride>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct EndpointOverride {
    #[serde(default)]
    pub enabled: Option<bool>,
    #[serde(default)]
    pub weight: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct MeasurementConfig {
    #[serde(default)]
    pub warmup_seconds: u32,
    #[serde(default)]
    pub measure_seconds: u32,
    #[serde(default)]
    pub profile_seconds: u32,
    #[serde(default)]
    pub cooldown_seconds: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ProfilingConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub tools: Vec<String>,
    #[serde(default)]
    pub duration_seconds: u32,
    #[serde(default)]
    pub required: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ExecutionConfig {
    #[serde(default)]
    pub retry_enabled: bool,
    #[serde(default)]
    pub max_attempts: u32,
    #[serde(default)]
    pub capture_logs: bool,
    #[serde(default)]
    pub save_raw_results: bool,
    #[serde(default)]
    pub reuse_stack: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RequestsConfig {
    #[serde(default)]
    pub enabled_groups: Vec<String>,
    #[serde(default)]
    pub disabled_groups: Vec<String>,
    #[serde(default)]
    pub enabled_endpoints: Vec<String>,
    #[serde(default)]
    pub disabled_endpoints: Vec<String>,
    #[serde(default)]
    pub enabled_tags: Vec<String>,
    #[serde(default)]
    pub disabled_tags: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolvedSuite {
    pub suite: SuiteMeta,
    pub scenarios: Vec<ResolvedScenario>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolvedScenario {
    pub name: String,
    pub description: String,
    pub scenario_type: String,
    pub setup: SetupConfig,
    pub build: BuildConfig,
    pub runtime: RuntimeConfig,
    pub gateway: GatewayConfig,
    pub load: LoadConfig,
    pub measurement: MeasurementConfig,
    pub profiling: ProfilingConfig,
    pub execution: ExecutionConfig,
    pub requests: RequestsConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RequestDefinition {
    pub name: String,
    pub group: String,
    pub tags: BTreeSet<String>,
    pub weight: u32,
    pub request: RequestSpec,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RequestSpec {
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub payload: Option<Value>,
    #[serde(default)]
    pub auth: bool, // pragma: allowlist secret
    #[serde(skip_serializing_if = "Option::is_none")]
    pub server_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expect_result_key: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expect_result_min_items: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expect_list_min_items: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expect_list_item_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expect_content_text: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandSpec {
    pub command: String,
    pub args: Vec<String>,
    pub env: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeChoice {
    pub engine: String,
    pub compose_cmd: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ScenarioSummary {
    pub scenario: String,
    pub status: String,
    pub setup: SetupConfig,
    pub runtime: RuntimeConfig,
    pub load: LoadConfig,
    pub measurement: MeasurementConfig,
    pub profiling: ProfilingConfig,
    pub goose: Value,
    pub endpoint_metrics: Value,
    pub flamegraph_run: Value,
    pub log_paths: Vec<String>,
    pub artifacts: BTreeMap<String, String>,
}

mod lib_parts;

pub use lib_parts::catalog::{
    benchmark_catalog, benchmark_request_names, resolve_requests_from_workload,
};
pub use lib_parts::reporting::{
    build_comparison_report, build_run_summary, collect_endpoint_metrics, regenerate_reports,
    write_goose_stats_csv,
};
pub use lib_parts::runtime::{build_goose_command, detect_runtime, run_benchmark, scenario_env};
pub use lib_parts::scenario_loading::{
    discover_scenarios, load_suite, repo_root, resolve_profile_path, scenario_root,
    validate_scenario,
};

#[cfg(test)]
use lib_parts::{
    benchmark_token,
    benchmark_token_command,
    determine_scenario_success,
    ensure_benchmark_image,
    has_endpoint_failures,
    run_command_streaming,
    write_compose_override,
    yaml_strings,
};

#[cfg(test)]
#[path = "lib_parts/tests.rs"]
mod tests;
