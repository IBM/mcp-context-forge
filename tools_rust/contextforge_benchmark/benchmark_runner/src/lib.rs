use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{Context, Result, anyhow, bail};
use chrono::Utc;
use csv::{ReaderBuilder, WriterBuilder};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use toml::Value as TomlValue;

pub const DEFAULT_SCENARIO_DIR: &str = "tools_rust/contextforge_benchmark/assets/scenarios";
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
    pub trust_proxy_auth: bool,
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
    pub auth: bool,
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

pub fn repo_root() -> Result<PathBuf> {
    let cwd = std::env::current_dir()?;
    Ok(cwd)
}

pub fn scenario_root(root: &Path) -> PathBuf {
    root.join(DEFAULT_SCENARIO_DIR)
}

pub fn discover_scenarios(root: &Path) -> Result<Vec<String>> {
    let mut scenarios = Vec::new();
    for entry in fs::read_dir(scenario_root(root))? {
        let path = entry?.path();
        if path.extension().and_then(|value| value.to_str()) == Some("toml") {
            if let Some(stem) = path.file_stem().and_then(|value| value.to_str()) {
                scenarios.push(stem.to_string());
            }
        }
    }
    scenarios.sort();
    Ok(scenarios)
}

pub fn resolve_profile_path(root: &Path, selection: &str) -> Result<PathBuf> {
    let candidate = Path::new(selection);
    if candidate.exists() {
        return Ok(candidate.to_path_buf());
    }
    let scenario_path = scenario_root(root).join(format!("{selection}.toml"));
    if scenario_path.exists() {
        return Ok(scenario_path);
    }
    bail!("Benchmark scenario not found: {selection}")
}

pub fn load_suite(root: &Path, selection: &str, smoke: bool) -> Result<ResolvedSuite> {
    let path = resolve_profile_path(root, selection)?;
    let raw =
        fs::read_to_string(&path).with_context(|| format!("failed to read {}", path.display()))?;
    let raw_value: TomlValue =
        toml::from_str(&raw).with_context(|| format!("failed to parse {}", path.display()))?;
    validate_rust_only_load_contract(&raw_value, &path)?;
    let document: SuiteDocument =
        toml::from_str(&raw).with_context(|| format!("failed to parse {}", path.display()))?;
    if document.scenario.is_empty() {
        bail!(
            "{} does not declare any [[scenario]] entries",
            path.display()
        );
    }
    let mut scenarios = Vec::new();
    for scenario in document.scenario {
        let merged = merge_scenario(&document.defaults, &scenario, smoke);
        validate_scenario(root, &merged)?;
        scenarios.push(merged);
    }
    Ok(ResolvedSuite {
        suite: document.suite,
        scenarios,
    })
}

fn merge_scenario(
    defaults: &ScenarioTemplate,
    scenario: &ScenarioEntry,
    smoke: bool,
) -> ResolvedScenario {
    let mut load = defaults.load.clone();
    merge_load(&mut load, &scenario.load);
    if smoke {
        load.users = Some(1);
        load.spawn_rate = Some(1);
        load.run_time = Some("10s".to_string());
        load.request_count = Some(5);
    }
    let mut setup = defaults.setup.clone();
    merge_setup(&mut setup, &scenario.setup);
    let mut build = defaults.build.clone();
    merge_build(&mut build, &scenario.build);
    let mut runtime = defaults.runtime.clone();
    merge_runtime(&mut runtime, &scenario.runtime);
    let mut gateway = defaults.gateway.clone();
    merge_gateway(&mut gateway, &scenario.gateway);
    let mut measurement = defaults.measurement.clone();
    merge_measurement(&mut measurement, &scenario.measurement);
    let mut profiling = defaults.profiling.clone();
    merge_profiling(&mut profiling, &scenario.profiling);
    let mut execution = defaults.execution.clone();
    merge_execution(&mut execution, &scenario.execution);
    let mut requests = defaults.requests.clone();
    merge_requests(&mut requests, &scenario.requests);

    ResolvedScenario {
        name: scenario.name.clone(),
        description: scenario.description.clone(),
        scenario_type: scenario.scenario_type.clone(),
        setup,
        build,
        runtime,
        gateway,
        load,
        measurement,
        profiling,
        execution,
        requests,
    }
}

fn merge_setup(base: &mut SetupConfig, overlay: &SetupConfig) {
    if !overlay.target_kind.is_empty() {
        base.target_kind = overlay.target_kind.clone();
    }
    if !overlay.auth_mode.is_empty() {
        base.auth_mode = overlay.auth_mode.clone();
    }
    base.plugins_enabled = overlay.plugins_enabled || base.plugins_enabled;
    if overlay.expected_mcp_runtime.is_some() {
        base.expected_mcp_runtime = overlay.expected_mcp_runtime.clone();
    }
    if overlay.expected_mcp_runtime_mode.is_some() {
        base.expected_mcp_runtime_mode = overlay.expected_mcp_runtime_mode.clone();
    }
    if overlay.expected_a2a_runtime.is_some() {
        base.expected_a2a_runtime = overlay.expected_a2a_runtime.clone();
    }
}

fn merge_build(base: &mut BuildConfig, overlay: &BuildConfig) {
    base.rust_plugins = overlay.rust_plugins || base.rust_plugins;
    base.profiling_image = overlay.profiling_image || base.profiling_image;
    if !overlay.container_file.is_empty() {
        base.container_file = overlay.container_file.clone();
    }
    if !overlay.image_name.is_empty() {
        base.image_name = overlay.image_name.clone();
    }
    if !overlay.image_tag.is_empty() {
        base.image_tag = overlay.image_tag.clone();
    }
    if !overlay.rebuild_policy.is_empty() {
        base.rebuild_policy = overlay.rebuild_policy.clone();
    }
    base.args.extend(overlay.args.clone());
}

fn merge_runtime(base: &mut RuntimeConfig, overlay: &RuntimeConfig) {
    if !overlay.http_server.is_empty() {
        base.http_server = overlay.http_server.clone();
    }
    if !overlay.host.is_empty() {
        base.host = overlay.host.clone();
    }
    if !overlay.transport_type.is_empty() {
        base.transport_type = overlay.transport_type.clone();
    }
    macro_rules! set_if_some {
        ($field:ident) => {
            if overlay.gunicorn.$field.is_some() {
                base.gunicorn.$field = overlay.gunicorn.$field;
            }
        };
    }
    set_if_some!(workers);
    set_if_some!(timeout);
    set_if_some!(graceful_timeout);
    set_if_some!(keep_alive);
    set_if_some!(max_requests);
    set_if_some!(max_requests_jitter);
    set_if_some!(backlog);
    set_if_some!(preload_app);
    set_if_some!(dev_mode);
}

fn merge_gateway(base: &mut GatewayConfig, overlay: &GatewayConfig) {
    base.disable_access_log = overlay.disable_access_log || base.disable_access_log;
    base.templates_auto_reload = overlay.templates_auto_reload || base.templates_auto_reload;
    base.structured_logging_database_enabled =
        overlay.structured_logging_database_enabled || base.structured_logging_database_enabled;
    base.sqlalchemy_echo = overlay.sqlalchemy_echo || base.sqlalchemy_echo;
    base.trust_proxy_auth = overlay.trust_proxy_auth || base.trust_proxy_auth;
    if !overlay.log_level.is_empty() {
        base.log_level = overlay.log_level.clone();
    }
    base.environment.extend(overlay.environment.clone());
}

fn merge_load(base: &mut LoadConfig, overlay: &LoadConfig) {
    if !overlay.driver.is_empty() {
        base.driver = overlay.driver.clone();
    }
    base.headless = overlay.headless || base.headless;
    base.only_summary = overlay.only_summary || base.only_summary;
    base.html_report = overlay.html_report || base.html_report;
    if overlay.users.is_some() {
        base.users = overlay.users;
    }
    if overlay.spawn_rate.is_some() {
        base.spawn_rate = overlay.spawn_rate;
    }
    if overlay.run_time.is_some() {
        base.run_time = overlay.run_time.clone();
    }
    if overlay.request_count.is_some() {
        base.request_count = overlay.request_count;
    }
    if overlay.seed.is_some() {
        base.seed = overlay.seed;
    }
    if !overlay.target_service.is_empty() {
        base.target_service = overlay.target_service.clone();
    }
    if overlay.host.is_some() {
        base.host = overlay.host.clone();
    }
    if !overlay.extra_args.is_empty() {
        base.extra_args = overlay.extra_args.clone();
    }
    base.env.extend(overlay.env.clone());
    if overlay.workload.fallback_endpoint.is_some() {
        base.workload.fallback_endpoint = overlay.workload.fallback_endpoint.clone();
    }
    base.workload
        .endpoints
        .extend(overlay.workload.endpoints.clone());
}

fn merge_measurement(base: &mut MeasurementConfig, overlay: &MeasurementConfig) {
    if overlay.warmup_seconds > 0 {
        base.warmup_seconds = overlay.warmup_seconds;
    }
    if overlay.measure_seconds > 0 {
        base.measure_seconds = overlay.measure_seconds;
    }
    if overlay.profile_seconds > 0 {
        base.profile_seconds = overlay.profile_seconds;
    }
    if overlay.cooldown_seconds > 0 {
        base.cooldown_seconds = overlay.cooldown_seconds;
    }
}

fn merge_profiling(base: &mut ProfilingConfig, overlay: &ProfilingConfig) {
    base.enabled = overlay.enabled || base.enabled;
    if !overlay.tools.is_empty() {
        base.tools = overlay.tools.clone();
    }
    if overlay.duration_seconds > 0 {
        base.duration_seconds = overlay.duration_seconds;
    }
    base.required = overlay.required || base.required;
}

fn merge_execution(base: &mut ExecutionConfig, overlay: &ExecutionConfig) {
    base.retry_enabled = overlay.retry_enabled || base.retry_enabled;
    if overlay.max_attempts > 0 {
        base.max_attempts = overlay.max_attempts;
    }
    base.capture_logs = overlay.capture_logs || base.capture_logs;
    base.save_raw_results = overlay.save_raw_results || base.save_raw_results;
    base.reuse_stack = overlay.reuse_stack || base.reuse_stack;
}

fn merge_requests(base: &mut RequestsConfig, overlay: &RequestsConfig) {
    if !overlay.enabled_groups.is_empty() {
        base.enabled_groups = overlay.enabled_groups.clone();
    }
    if !overlay.disabled_groups.is_empty() {
        base.disabled_groups = overlay.disabled_groups.clone();
    }
    if !overlay.enabled_endpoints.is_empty() {
        base.enabled_endpoints = overlay.enabled_endpoints.clone();
    }
    if !overlay.disabled_endpoints.is_empty() {
        base.disabled_endpoints = overlay.disabled_endpoints.clone();
    }
    if !overlay.enabled_tags.is_empty() {
        base.enabled_tags = overlay.enabled_tags.clone();
    }
    if !overlay.disabled_tags.is_empty() {
        base.disabled_tags = overlay.disabled_tags.clone();
    }
}

const LEGACY_LOAD_FIELDS: &[&str] = &[
    "goosefile",
    "locustfile",
    "repo_url",
    "git_ref",
    "git_commit",
];
const UNSUPPORTED_GOOSE_ARGS: &[&str] = &["--reset-stats"];

fn validate_rust_only_load_contract(raw: &TomlValue, path: &Path) -> Result<()> {
    let Some(table) = raw.as_table() else {
        return Ok(());
    };

    if let Some(defaults) = table.get("defaults").and_then(TomlValue::as_table) {
        if let Some(load) = defaults.get("load") {
            reject_legacy_load_fields(load, "defaults.load", path)?;
        }
    }

    if let Some(scenarios) = table.get("scenario").and_then(TomlValue::as_array) {
        for (index, scenario) in scenarios.iter().enumerate() {
            let Some(scenario_table) = scenario.as_table() else {
                continue;
            };
            if let Some(load) = scenario_table.get("load") {
                let scenario_name = scenario_table
                    .get("name")
                    .and_then(TomlValue::as_str)
                    .unwrap_or("<unnamed>");
                let context = format!("scenario[{index}] '{scenario_name}'.load");
                reject_legacy_load_fields(load, &context, path)?;
            }
        }
    }

    Ok(())
}

fn reject_legacy_load_fields(load: &TomlValue, context: &str, path: &Path) -> Result<()> {
    let Some(table) = load.as_table() else {
        return Ok(());
    };

    if let Some(field) = LEGACY_LOAD_FIELDS
        .iter()
        .find(|field| table.contains_key(**field))
    {
        bail!(
            "{} in {} uses legacy load.{}; the Rust-only benchmark contract supports only load.driver = \"{}\"",
            context,
            path.display(),
            field,
            DEFAULT_GOSE_BIN
        );
    }

    Ok(())
}

pub fn validate_scenario(root: &Path, scenario: &ResolvedScenario) -> Result<()> {
    if scenario.name.trim().is_empty() {
        bail!("scenario name must not be empty");
    }
    if scenario.load.driver.trim().is_empty() {
        bail!("scenario '{}' must define load.driver", scenario.name);
    }
    if scenario.load.driver != DEFAULT_GOSE_BIN {
        bail!(
            "scenario '{}' uses unsupported driver '{}'; only '{}' is supported",
            scenario.name,
            scenario.load.driver,
            DEFAULT_GOSE_BIN
        );
    }
    if let Some(arg) = scenario
        .load
        .extra_args
        .iter()
        .find(|arg| UNSUPPORTED_GOOSE_ARGS.contains(&arg.as_str()))
    {
        bail!(
            "scenario '{}' uses unsupported Goose extra arg '{}'; remove stale Locust-era flags from load.extra_args",
            scenario.name,
            arg
        );
    }
    if !scenario.build.container_file.is_empty()
        && !root.join(&scenario.build.container_file).exists()
    {
        bail!(
            "scenario '{}' container file does not exist: {}",
            scenario.name,
            root.join(&scenario.build.container_file).display()
        );
    }
    for endpoint in scenario.load.workload.endpoints.keys() {
        if !benchmark_request_names(root)?.contains(endpoint) {
            bail!(
                "scenario '{}' workload references unknown endpoint: {}",
                scenario.name,
                endpoint
            );
        }
    }
    Ok(())
}

fn payload_root(root: &Path) -> PathBuf {
    root.join("tools_rust/contextforge_benchmark/assets/payloads")
}

fn load_payload(root: &Path, group: &str, name: &str) -> Result<Value> {
    let path = payload_root(root).join(group).join(name);
    let raw =
        fs::read_to_string(&path).with_context(|| format!("failed to read {}", path.display()))?;
    Ok(
        serde_json::from_str(&raw)
            .with_context(|| format!("failed to parse {}", path.display()))?,
    )
}

pub fn benchmark_catalog(root: &Path) -> Result<Vec<RequestDefinition>> {
    let default_server = "9779b6698cbd4b4995ee04a4fab38737".to_string();
    Ok(vec![
        RequestDefinition {
            name: "/health".into(),
            group: "health".into(),
            tags: set(&["health"]),
            weight: 10,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/health".into()),
                payload: None,
                auth: false,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/ready".into(),
            group: "health".into(),
            tags: set(&["health"]),
            weight: 4,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/ready".into()),
                payload: None,
                auth: false,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/admin/plugins".into(),
            group: "admin".into(),
            tags: set(&["admin", "plugins"]),
            weight: 2,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/admin/plugins".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/servers".into(),
            group: "servers".into(),
            tags: set(&["servers", "rest", "discovery"]),
            weight: 5,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/servers".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: Some(1),
                expect_list_item_name: Some("Fast Time Server".into()),
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/a2a".into(),
            group: "a2a".into(),
            tags: set(&["a2a", "rest", "discovery"]),
            weight: 3,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/a2a".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: Some(1),
                expect_list_item_name: Some("a2a-echo-agent".into()),
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/a2a/a2a-echo-agent/invoke".into(),
            group: "a2a".into(),
            tags: set(&["a2a", "invoke", "echo"]),
            weight: 8,
            request: RequestSpec {
                kind: "post".into(),
                path: Some("/a2a/a2a-echo-agent/invoke".into()),
                payload: Some(
                    json!({"parameters":{"message":{"kind":"message","role":"user","messageId":"benchmark-a2a-invoke","parts":[{"kind":"text","text":"benchmark ping"}]}},"interaction_type":"query"}),
                ),
                auth: true,
                server_id: None,
                expect_result_key: Some("result".into()),
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp tools/list".into(),
            group: "mcp".into(),
            tags: set(&["mcp", "tools", "discovery"]),
            weight: 3,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "tools", "list_tools.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("tools".into()),
                expect_result_min_items: Some(2),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp tools/call fast-time-get-system-time".into(),
            group: "tools".into(),
            tags: set(&["tools", "mcp", "plugin-heavy"]),
            weight: 8,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "tools", "get_system_time.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(true),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp tools/call fast-time-convert-time".into(),
            group: "tools".into(),
            tags: set(&["tools", "mcp", "plugin-heavy"]),
            weight: 6,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "tools", "convert_time.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(true),
                name: None,
            },
        },
        RequestDefinition {
            name: "/resources".into(),
            group: "resources".into(),
            tags: set(&["resources", "rest"]),
            weight: 3,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/resources".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: Some(1),
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp resources/list".into(),
            group: "mcp".into(),
            tags: set(&["mcp", "resources"]),
            weight: 3,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "resources", "list_resources.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("resources".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp resources/read timezone://info".into(),
            group: "resources".into(),
            tags: set(&["resources", "mcp", "plugin-heavy"]),
            weight: 5,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "resources", "read_timezone_info.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("contents".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp resources/read time://current/world".into(),
            group: "resources".into(),
            tags: set(&["resources", "mcp", "plugin-heavy"]),
            weight: 4,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "resources", "read_world_times.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("contents".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/prompts".into(),
            group: "prompts".into(),
            tags: set(&["prompts", "rest"]),
            weight: 3,
            request: RequestSpec {
                kind: "get".into(),
                path: Some("/prompts".into()),
                payload: None,
                auth: true,
                server_id: None,
                expect_result_key: None,
                expect_result_min_items: None,
                expect_list_min_items: Some(1),
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp prompts/list".into(),
            group: "mcp".into(),
            tags: set(&["mcp", "prompts"]),
            weight: 3,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "prompts", "list_prompts.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("prompts".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp prompts/get fast-time-schedule-meeting".into(),
            group: "prompts".into(),
            tags: set(&["prompts", "mcp", "plugin-heavy"]),
            weight: 5,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "prompts", "get_schedule_meeting.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("messages".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
        RequestDefinition {
            name: "/mcp prompts/get fast-time-compare-timezones".into(),
            group: "prompts".into(),
            tags: set(&["prompts", "mcp", "plugin-heavy"]),
            weight: 4,
            request: RequestSpec {
                kind: "mcp".into(),
                path: None,
                payload: Some(load_payload(root, "prompts", "get_compare_timezones.json")?),
                auth: true,
                server_id: Some(default_server.clone()),
                expect_result_key: Some("messages".into()),
                expect_result_min_items: Some(1),
                expect_list_min_items: None,
                expect_list_item_name: None,
                expect_content_text: Some(false),
                name: None,
            },
        },
    ])
}

fn set(items: &[&str]) -> BTreeSet<String> {
    items.iter().map(|item| (*item).to_string()).collect()
}

pub fn benchmark_request_names(root: &Path) -> Result<BTreeSet<String>> {
    Ok(benchmark_catalog(root)?
        .into_iter()
        .map(|request| request.name)
        .collect())
}

pub fn resolve_requests_from_workload(
    root: &Path,
    workload: &WorkloadConfig,
) -> Result<Vec<RequestDefinition>> {
    let catalog = benchmark_catalog(root)?;
    if workload.endpoints.is_empty() {
        return Ok(catalog);
    }
    let mut requests = Vec::new();
    for request in catalog.iter() {
        if let Some(override_config) = workload.endpoints.get(&request.name) {
            let enabled = override_config.enabled.unwrap_or(true);
            let weight = override_config.weight.unwrap_or(request.weight);
            if enabled && weight > 0 {
                let mut resolved = request.clone();
                resolved.weight = weight;
                requests.push(resolved);
            }
        }
    }
    if !requests.is_empty() {
        return Ok(requests);
    }
    let fallback = workload.fallback_endpoint.as_deref().unwrap_or("/health");
    Ok(catalog
        .into_iter()
        .filter(|request| request.name == fallback)
        .collect())
}

pub fn detect_runtime() -> Result<RuntimeChoice> {
    let preferred = std::env::var("CONTAINER_RUNTIME").unwrap_or_else(|_| "docker".to_string());
    let candidates = if preferred == "podman" {
        vec![
            ("podman", vec!["podman".to_string(), "compose".to_string()]),
            ("docker", vec!["docker".to_string(), "compose".to_string()]),
        ]
    } else {
        vec![
            ("docker", vec!["docker".to_string(), "compose".to_string()]),
            ("podman", vec!["podman".to_string(), "compose".to_string()]),
        ]
    };
    for (engine, compose_cmd) in candidates {
        if command_ok(engine, &["--version"])
            && command_ok(
                &compose_cmd[0],
                &compose_cmd[1..]
                    .iter()
                    .map(String::as_str)
                    .chain(["version"])
                    .collect::<Vec<_>>(),
            )
        {
            return Ok(RuntimeChoice {
                engine: engine.to_string(),
                compose_cmd,
            });
        }
    }
    bail!("could not detect a working docker/podman runtime")
}

fn command_ok(command: &str, args: &[&str]) -> bool {
    Command::new(command)
        .args(args)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

pub fn build_goose_command(
    root: &Path,
    scenario: &ResolvedScenario,
    scenario_dir: &Path,
    artifact_prefix: &str,
    profiling_mode: bool,
) -> CommandSpec {
    let manifest = root.join("tools_rust/contextforge_benchmark/contextforge_goose/Cargo.toml");
    let request_log = scenario_dir.join(format!("{artifact_prefix}_requests.csv"));
    let transaction_log = scenario_dir.join(format!("{artifact_prefix}_transactions.csv"));
    let mut env = scenario_env(root, scenario).unwrap_or_default();
    let (command, args) = if profiling_mode {
        let mut args = vec![
            "flamegraph".to_string(),
            "--manifest-path".to_string(),
            manifest.display().to_string(),
            "--bin".to_string(),
            DEFAULT_GOSE_BIN.to_string(),
            "--output".to_string(),
            scenario_dir
                .join(format!("{artifact_prefix}_flamegraph.svg"))
                .display()
                .to_string(),
            "--root".to_string(),
            "--".to_string(),
            "--host".to_string(),
            target_host(&scenario.load),
            "--users".to_string(),
            scenario.load.users.unwrap_or(1).to_string(),
            "--hatch-rate".to_string(),
            scenario.load.spawn_rate.unwrap_or(1).to_string(),
            "--request-log".to_string(),
            request_log.display().to_string(),
            "--request-format".to_string(),
            "csv".to_string(),
            "--transaction-log".to_string(),
            transaction_log.display().to_string(),
            "--transaction-format".to_string(),
            "csv".to_string(),
        ];
        if let Some(run_time) = &scenario.load.run_time {
            args.push("--run-time".to_string());
            args.push(run_time.clone());
        }
        if scenario.load.html_report {
            args.push("--report-file".to_string());
            args.push(
                scenario_dir
                    .join(format!("{artifact_prefix}_report.html"))
                    .display()
                    .to_string(),
            );
        }
        args.extend(scenario.load.extra_args.clone());
        ("cargo".to_string(), args)
    } else {
        let mut args = vec![
            "run".to_string(),
            "--manifest-path".to_string(),
            manifest.display().to_string(),
            "--bin".to_string(),
            DEFAULT_GOSE_BIN.to_string(),
            "--release".to_string(),
            "--".to_string(),
            "--host".to_string(),
            target_host(&scenario.load),
            "--users".to_string(),
            scenario.load.users.unwrap_or(1).to_string(),
            "--hatch-rate".to_string(),
            scenario.load.spawn_rate.unwrap_or(1).to_string(),
            "--request-log".to_string(),
            request_log.display().to_string(),
            "--request-format".to_string(),
            "csv".to_string(),
            "--transaction-log".to_string(),
            transaction_log.display().to_string(),
            "--transaction-format".to_string(),
            "csv".to_string(),
        ];
        if let Some(run_time) = &scenario.load.run_time {
            args.push("--run-time".to_string());
            args.push(run_time.clone());
        }
        if scenario.load.html_report {
            args.push("--report-file".to_string());
            args.push(
                scenario_dir
                    .join(format!("{artifact_prefix}_report.html"))
                    .display()
                    .to_string(),
            );
        }
        args.extend(scenario.load.extra_args.clone());
        ("cargo".to_string(), args)
    };
    if let Some(seed) = scenario.load.seed {
        env.insert("BENCH_SEED".to_string(), seed.to_string());
    }
    CommandSpec { command, args, env }
}

fn target_host(load: &LoadConfig) -> String {
    if let Some(host) = &load.host {
        return host.clone();
    }
    if load.target_service == "gateway" {
        "http://127.0.0.1:14444".to_string()
    } else {
        "http://127.0.0.1:18080".to_string()
    }
}

pub fn scenario_env(root: &Path, scenario: &ResolvedScenario) -> Result<BTreeMap<String, String>> {
    let mut env = BTreeMap::new();
    env.insert("LOADTEST_HOST".to_string(), target_host(&scenario.load));
    env.insert(
        "LOADTEST_USERS".to_string(),
        scenario.load.users.unwrap_or(1).to_string(),
    );
    env.insert(
        "LOADTEST_SPAWN_RATE".to_string(),
        scenario.load.spawn_rate.unwrap_or(1).to_string(),
    );
    env.insert(
        "LOADTEST_RUN_TIME".to_string(),
        scenario
            .load
            .run_time
            .clone()
            .unwrap_or_else(|| "10s".to_string()),
    );
    env.insert(
        "LOADTEST_REQUEST_COUNT".to_string(),
        scenario.load.request_count.unwrap_or(0).to_string(),
    );
    env.insert(
        "BENCH_REQUEST_COUNT".to_string(),
        scenario.load.request_count.unwrap_or(0).to_string(),
    );
    env.insert(
        "BENCH_TARGET_SERVICE".to_string(),
        scenario.load.target_service.clone(),
    );
    env.insert(
        "BENCH_REQUEST_PLAN".to_string(),
        serde_json::to_string(&resolve_requests_from_workload(
            root,
            &scenario.load.workload,
        )?)?,
    );
    for (key, value) in &scenario.load.env {
        env.insert(key.clone(), value.clone());
    }
    Ok(env)
}

pub fn run_benchmark(
    root: &Path,
    selection: &str,
    run_all: bool,
    validate_only: bool,
    smoke: bool,
    check_runtime_only: bool,
) -> Result<PathBuf> {
    let runtime = detect_runtime()?;
    log_progress(format!(
        "Runtime detected: {} via {}",
        runtime.engine,
        runtime.compose_cmd.join(" ")
    ));
    let scenarios = if run_all {
        discover_scenarios(root)?
    } else {
        vec![selection.to_string()]
    };
    let resolved = scenarios
        .into_iter()
        .map(|name| load_suite(root, &name, smoke))
        .collect::<Result<Vec<_>>>()?;
    let suite = if resolved.len() == 1 {
        resolved.into_iter().next().unwrap()
    } else {
        let mut all = Vec::new();
        let mut suite_meta = SuiteMeta::default();
        for item in resolved {
            if suite_meta.name.is_empty() {
                suite_meta = item.suite.clone();
            }
            all.extend(item.scenarios);
        }
        ResolvedSuite {
            suite: suite_meta,
            scenarios: all,
        }
    };
    let run_dir = PathBuf::from(&suite.suite.output_root).join(format!(
        "{}_{}",
        if run_all { "all-scenarios" } else { selection },
        Utc::now().format("%Y%m%d_%H%M%S")
    ));
    fs::create_dir_all(&run_dir)?;
    log_progress(format!("Writing benchmark artifacts to {}", run_dir.display()));

    let mut summaries = Vec::new();
    let mut failed_scenarios = Vec::new();
    for (index, scenario) in suite.scenarios.iter().enumerate() {
        log_progress(format!(
            "Scenario {}/{} starting: {}",
            index + 1,
            suite.scenarios.len(),
            scenario.name
        ));
        let scenario_dir = run_dir.join("scenarios").join(&scenario.name);
        fs::create_dir_all(&scenario_dir)?;
        let result = if check_runtime_only {
            run_runtime_check(root, &runtime, scenario, &scenario_dir)
        } else if validate_only {
            Ok(build_validation_summary(scenario))
        } else {
            execute_scenario(root, &runtime, scenario, &scenario_dir)
        };

        match result {
            Ok(summary) => {
                log_progress(format!(
                    "Scenario '{}' completed with status {}",
                    scenario.name, summary.status
                ));
                if summary.status != "ok" && summary.status != "validated" {
                    failed_scenarios.push(scenario.name.clone());
                }
                write_json(&scenario_dir.join("summary.json"), &summary)?;
                summaries.push(summary);
            }
            Err(error) => {
                log_progress(format!("Scenario '{}' failed: {error}", scenario.name));
                failed_scenarios.push(scenario.name.clone());
                let summary = build_error_summary(scenario, &error);
                write_json(&scenario_dir.join("summary.json"), &summary)?;
                summaries.push(summary);
            }
        }
    }
    let run_summary = build_run_summary(&suite.suite, &summaries);
    write_json(&run_dir.join("run_summary.json"), &run_summary)?;
    write_text(
        &run_dir.join("run_summary.md"),
        &render_run_summary_markdown(&run_summary),
    )?;
    let comparison = build_comparison_report(&summaries);
    write_json(
        &run_dir.join("scenario_comparison_report.json"),
        &comparison,
    )?;
    write_text(
        &run_dir.join("scenario_comparison_report.md"),
        &render_comparison_markdown(&comparison),
    )?;
    write_text(
        &run_dir.join("scenario_comparison_report.html"),
        &render_comparison_html(&comparison),
    )?;
    if failed_scenarios.is_empty() {
        log_progress(format!("Benchmark run completed successfully: {}", run_dir.display()));
    } else {
        log_progress(format!(
            "Benchmark run completed with failed scenarios [{}]: {}",
            failed_scenarios.join(", "),
            run_dir.display()
        ));
    }
    Ok(run_dir)
}

fn build_validation_summary(scenario: &ResolvedScenario) -> ScenarioSummary {
    ScenarioSummary {
        scenario: scenario.name.clone(),
        status: "validated".to_string(),
        setup: scenario.setup.clone(),
        runtime: scenario.runtime.clone(),
        load: scenario.load.clone(),
        measurement: scenario.measurement.clone(),
        profiling: scenario.profiling.clone(),
        goose: json!({"status":"omitted","reason":"Validation mode"}),
        endpoint_metrics: json!({"status":"omitted","reason":"Validation mode"}),
        flamegraph_run: json!({"status":"omitted","reason":"Validation mode"}),
        log_paths: Vec::new(),
        artifacts: BTreeMap::new(),
    }
}

fn build_error_summary(scenario: &ResolvedScenario, error: &anyhow::Error) -> ScenarioSummary {
    ScenarioSummary {
        scenario: scenario.name.clone(),
        status: "failed".to_string(),
        setup: scenario.setup.clone(),
        runtime: scenario.runtime.clone(),
        load: scenario.load.clone(),
        measurement: scenario.measurement.clone(),
        profiling: scenario.profiling.clone(),
        goose: json!({
            "status":"failed",
            "error": error.to_string(),
        }),
        endpoint_metrics: json!({"status":"unavailable","reason":"scenario failed before metrics collection"}),
        flamegraph_run: json!({"status":"omitted","reason":"scenario failed"}),
        log_paths: Vec::new(),
        artifacts: BTreeMap::new(),
    }
}

fn run_runtime_check(
    root: &Path,
    runtime: &RuntimeChoice,
    scenario: &ResolvedScenario,
    scenario_dir: &Path,
) -> Result<ScenarioSummary> {
    let (compose_args, _project) = start_stack(root, runtime, scenario, scenario_dir)?;
    let health_ok = wait_for_gateway_health(&compose_args, 120)?;
    stop_stack(&compose_args);
    Ok(ScenarioSummary {
        scenario: scenario.name.clone(),
        status: if health_ok {
            "ok".to_string()
        } else {
            "failed".to_string()
        },
        setup: scenario.setup.clone(),
        runtime: scenario.runtime.clone(),
        load: scenario.load.clone(),
        measurement: scenario.measurement.clone(),
        profiling: scenario.profiling.clone(),
        goose: json!({"status":"omitted","reason":"check-runtime"}),
        endpoint_metrics: json!({"status":"omitted","reason":"check-runtime"}),
        flamegraph_run: json!({"status":"omitted","reason":"check-runtime"}),
        log_paths: Vec::new(),
        artifacts: BTreeMap::new(),
    })
}

fn execute_scenario(
    root: &Path,
    runtime: &RuntimeChoice,
    scenario: &ResolvedScenario,
    scenario_dir: &Path,
) -> Result<ScenarioSummary> {
    log_progress(format!("Starting stack for scenario '{}'", scenario.name));
    let (compose_args, _project) = start_stack(root, runtime, scenario, scenario_dir)?;
    let result = (|| -> Result<ScenarioSummary> {
        let token = benchmark_token(&compose_args).ok();
        let artifact_prefix = "goose";
        let command = build_goose_command(root, scenario, scenario_dir, artifact_prefix, false);
        log_progress(format!(
            "Launching Goose for scenario '{}': {} {}",
            scenario.name, command.command, command.args.join(" ")
        ));
        let goose_result = run_command_spec(root, &command, token.as_deref())?;
        let request_log = scenario_dir.join("goose_requests.csv");
        let csv_prefix = scenario_dir.join("goose");
        write_goose_stats_csv(&request_log, &csv_prefix)?;
        let endpoint_metrics = collect_endpoint_metrics(&csv_prefix, &scenario.measurement)?;
        let scenario_success = determine_scenario_success(goose_result.success, &endpoint_metrics);
        let mut flamegraph_run = json!({"status":"omitted","reason":"profiling disabled"});
        let mut artifacts = BTreeMap::new();
        if scenario.load.html_report {
            artifacts.insert(
                "goose_html".to_string(),
                scenario_dir.join("goose_report.html").display().to_string(),
            );
        }
        if scenario.profiling.enabled {
            log_progress(format!("Collecting flamegraph for scenario '{}'", scenario.name));
            flamegraph_run = run_flamegraph(root, scenario, scenario_dir, token.as_deref())?;
            if let Some(path) = flamegraph_run.get("svg").and_then(Value::as_str) {
                if Path::new(path).exists() {
                    artifacts.insert("goose_flamegraph".to_string(), path.to_string());
                }
            }
        }
        Ok(ScenarioSummary {
            scenario: scenario.name.clone(),
            status: if scenario_success {
                "ok".to_string()
            } else {
                "failed".to_string()
            },
            setup: scenario.setup.clone(),
            runtime: scenario.runtime.clone(),
            load: scenario.load.clone(),
            measurement: scenario.measurement.clone(),
            profiling: scenario.profiling.clone(),
            goose: json!({
                "status": if scenario_success { "ok" } else { "failed" },
                "stdout": goose_result.stdout,
                "stderr": goose_result.stderr,
                "html_report": scenario_dir.join("goose_report.html").display().to_string(),
                "csv_prefix": csv_prefix.display().to_string(),
            }),
            endpoint_metrics,
            flamegraph_run,
            log_paths: Vec::new(),
            artifacts,
        })
    })();
    log_progress(format!("Stopping stack for scenario '{}'", scenario.name));
    stop_stack(&compose_args);
    result
}

fn determine_scenario_success(process_success: bool, endpoint_metrics: &Value) -> bool {
    process_success && !has_endpoint_failures(endpoint_metrics)
}

fn has_endpoint_failures(endpoint_metrics: &Value) -> bool {
    endpoint_metrics
        .get("aggregated")
        .and_then(|value| value.get("Failure Count"))
        .and_then(Value::as_str)
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(0)
        > 0
}

#[derive(Debug)]
struct RunOutput {
    success: bool,
    stdout: String,
    stderr: String,
}

fn run_command_spec(root: &Path, spec: &CommandSpec, token: Option<&str>) -> Result<RunOutput> {
    let mut command = Command::new(&spec.command);
    command
        .args(&spec.args)
        .current_dir(root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in &spec.env {
        command.env(key, value);
    }
    if let Some(token) = token {
        command.env("MCPGATEWAY_BEARER_TOKEN", token);
    }
    run_command_streaming(&mut command, |stream, line| {
        log_progress(format!("{stream}: {line}"));
    })
}

fn run_command_streaming<F>(command: &mut Command, mut on_line: F) -> Result<RunOutput>
where
    F: FnMut(&str, &str),
{
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn()?;
    let stdout = child.stdout.take().ok_or_else(|| anyhow!("missing child stdout"))?;
    let stderr = child.stderr.take().ok_or_else(|| anyhow!("missing child stderr"))?;
    let (sender, receiver) = mpsc::channel::<(&'static str, String)>();

    let stdout_sender = sender.clone();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(value) => {
                    let _ = stdout_sender.send(("stdout", value));
                }
                Err(error) => {
                    let _ = stdout_sender.send(("stderr", format!("stdout read error: {error}")));
                    break;
                }
            }
        }
    });

    let stderr_sender = sender.clone();
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines() {
            match line {
                Ok(value) => {
                    let _ = stderr_sender.send(("stderr", value));
                }
                Err(error) => {
                    let _ = stderr_sender.send(("stderr", format!("stderr read error: {error}")));
                    break;
                }
            }
        }
    });
    drop(sender);

    let mut stdout_log = String::new();
    let mut stderr_log = String::new();
    for (stream, line) in receiver {
        on_line(stream, &line);
        match stream {
            "stdout" => {
                stdout_log.push_str(&line);
                stdout_log.push('\n');
            }
            "stderr" => {
                stderr_log.push_str(&line);
                stderr_log.push('\n');
            }
            _ => {}
        }
    }

    let status = child.wait()?;
    Ok(RunOutput {
        success: status.success(),
        stdout: stdout_log,
        stderr: stderr_log,
    })
}

fn run_flamegraph(
    root: &Path,
    scenario: &ResolvedScenario,
    scenario_dir: &Path,
    token: Option<&str>,
) -> Result<Value> {
    let svg = scenario_dir.join("goose_flamegraph_flamegraph.svg");
    let spec = build_goose_command(root, scenario, scenario_dir, "goose_flamegraph", true);
    let output = run_command_spec(root, &spec, token)?;
    Ok(json!({
        "status": if output.success { "ok" } else { "failed" },
        "stdout": output.stdout,
        "stderr": output.stderr,
        "svg": svg.display().to_string(),
        "html_report": scenario_dir.join("goose_flamegraph_report.html").display().to_string(),
    }))
}

fn compose_args(runtime: &RuntimeChoice, project_name: &str, override_path: &Path) -> Vec<String> {
    let mut args = runtime.compose_cmd.clone();
    args.push("-p".to_string());
    args.push(project_name.to_string());
    args.push("-f".to_string());
    args.push(override_path.display().to_string());
    args
}

fn start_stack(
    root: &Path,
    runtime: &RuntimeChoice,
    scenario: &ResolvedScenario,
    scenario_dir: &Path,
) -> Result<(Vec<String>, String)> {
    let image_name = ensure_benchmark_image(root, runtime, scenario)?;
    let project = format!("bench-{}-{}", slug(&scenario.name), Utc::now().timestamp());
    let override_path = write_compose_override(root, scenario, scenario_dir, &image_name)?;
    let compose = compose_args(runtime, &project, &override_path);
    let mut services = vec!["postgres", "redis", "pgbouncer", "gateway"];
    if uses_fast_time_fixture(scenario) {
        services.push("fast_time_server");
        services.push("register_fast_time");
    }
    if uses_a2a_fixture(scenario) {
        services.push("a2a_echo_agent");
        services.push("register_a2a_echo");
    }
    if scenario.load.target_service != "gateway" {
        services.push("nginx");
    }
    for service in ["postgres", "redis", "pgbouncer", "gateway"] {
        log_progress(format!("Compose up: {service}"));
        run_compose(root, &compose, &["up", "-d", "--no-build", service])?;
        log_progress(format!("Waiting for service health: {service}"));
        wait_for_service(runtime, &compose, service, 120)?;
    }
    if !wait_for_gateway_health(&compose, 120)? {
        bail!(
            "gateway health check failed for scenario '{}'",
            scenario.name
        );
    }
    if uses_fast_time_fixture(scenario) {
        log_progress("Compose up: fast_time_server");
        run_compose(
            root,
            &compose,
            &["up", "-d", "--no-build", "fast_time_server"],
        )?;
        log_progress("Waiting for service health: fast_time_server");
        wait_for_service(runtime, &compose, "fast_time_server", 60)?;
        log_progress("Compose up: register_fast_time");
        run_compose(
            root,
            &compose,
            &["up", "-d", "--no-build", "register_fast_time"],
        )?;
    }
    if uses_a2a_fixture(scenario) {
        log_progress("Compose up: a2a_echo_agent");
        run_compose(
            root,
            &compose,
            &["up", "-d", "--no-build", "a2a_echo_agent"],
        )?;
        log_progress("Waiting for service health: a2a_echo_agent");
        wait_for_service(runtime, &compose, "a2a_echo_agent", 60)?;
        log_progress("Compose up: register_a2a_echo");
        run_compose(
            root,
            &compose,
            &["up", "-d", "--no-build", "register_a2a_echo"],
        )?;
    }
    if scenario.load.target_service != "gateway" {
        log_progress("Compose up: nginx");
        run_compose(root, &compose, &["up", "-d", "--no-build", "nginx"])?;
        log_progress("Waiting for service health: nginx");
        wait_for_service(runtime, &compose, "nginx", 60)?;
    }
    Ok((compose, project))
}

fn stop_stack(compose_args: &[String]) {
    let _ = Command::new(&compose_args[0])
        .args(&compose_args[1..])
        .args(["down", "--remove-orphans"])
        .status();
}

fn uses_fast_time_fixture(scenario: &ResolvedScenario) -> bool {
    scenario
        .load
        .workload
        .endpoints
        .keys()
        .any(|name| name.contains("fast-time") || name.contains("/mcp "))
}

fn uses_a2a_fixture(scenario: &ResolvedScenario) -> bool {
    scenario
        .load
        .workload
        .endpoints
        .keys()
        .any(|name| name.contains("/a2a"))
}

fn ensure_benchmark_image(
    root: &Path,
    runtime: &RuntimeChoice,
    scenario: &ResolvedScenario,
) -> Result<String> {
    let image_name = format!(
        "{}:{}",
        if scenario.build.image_name.is_empty() {
            "mcpgateway/mcpgateway"
        } else {
            &scenario.build.image_name
        },
        if scenario.build.image_tag.is_empty() {
            "benchmark-suite-rust"
        } else {
            &scenario.build.image_tag
        }
    );
    if scenario.build.rebuild_policy == "missing"
        && Command::new(&runtime.engine)
            .args(["image", "inspect", &image_name])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    {
        log_progress(format!("Using existing benchmark image {image_name}"));
        return Ok(image_name);
    }
    let container_file = if scenario.build.container_file.is_empty() {
        "tools_rust/contextforge_benchmark/assets/Containerfile".to_string()
    } else {
        scenario.build.container_file.clone()
    };
    let mut command = Command::new(&runtime.engine);
    command
        .current_dir(root)
        .arg("build")
        .arg("-f")
        .arg(container_file)
        .arg("-t")
        .arg(&image_name)
        .arg("--build-arg")
        .arg(format!(
            "ENABLE_RUST={}",
            if scenario.build.rust_plugins {
                "true"
            } else {
                "false"
            }
        ))
        .arg("--build-arg")
        .arg(format!(
            "ENABLE_PROFILING={}",
            if scenario.profiling.enabled || scenario.build.profiling_image {
                "true"
            } else {
                "false"
            }
        ));
    for (key, value) in &scenario.build.args {
        command.arg("--build-arg").arg(format!("{key}={value}"));
    }
    command.arg(".");
    log_progress(format!("Building benchmark image {image_name}"));
    let status = command.status()?;
    if !status.success() {
        bail!(
            "failed to build benchmark image for scenario '{}'",
            scenario.name
        );
    }
    Ok(image_name)
}

fn write_compose_override(
    root: &Path,
    scenario: &ResolvedScenario,
    scenario_dir: &Path,
    image_name: &str,
) -> Result<PathBuf> {
    let compose_path = root.join("docker-compose.yml");
    let base_raw = fs::read_to_string(&compose_path)?;
    let mut base: serde_yaml::Value = serde_yaml::from_str(&base_raw)?;
    let base_map = base
        .as_mapping_mut()
        .ok_or_else(|| anyhow!("docker-compose.yml must be a mapping"))?;
    let base_services = base_map
        .get(&yaml_key("services"))
        .and_then(serde_yaml::Value::as_mapping)
        .cloned()
        .ok_or_else(|| anyhow!("docker-compose.yml must define services"))?;
    let networks = base_map
        .get(&yaml_key("networks"))
        .cloned()
        .unwrap_or_else(|| serde_yaml::Value::Mapping(serde_yaml::Mapping::new()));
    let volumes = base_map
        .get(&yaml_key("volumes"))
        .cloned()
        .unwrap_or_else(|| serde_yaml::Value::Mapping(serde_yaml::Mapping::new()));

    let mut selected = vec!["postgres", "redis", "pgbouncer", "gateway"];
    if scenario.load.target_service != "gateway" {
        selected.push("nginx");
    }
    if uses_fast_time_fixture(scenario) {
        selected.push("fast_time_server");
        selected.push("register_fast_time");
    }
    if uses_a2a_fixture(scenario) {
        selected.push("a2a_echo_agent");
        selected.push("register_a2a_echo");
    }

    let mut services = serde_yaml::Mapping::new();
    for name in selected {
        let mut service = base_services
            .get(&yaml_key(name))
            .and_then(serde_yaml::Value::as_mapping)
            .cloned()
            .ok_or_else(|| anyhow!("missing compose service '{name}'"))?;
        service.remove(&yaml_key("profiles"));
        service.remove(&yaml_key("build"));
        service.insert(
            yaml_key("deploy"),
            serde_yaml::to_value(json!({
                "resources": {
                    "limits": {"cpus": "1"},
                    "reservations": {"cpus": "0.25"}
                }
            }))?,
        );
        if !matches!(name, "gateway" | "nginx") {
            service.remove(&yaml_key("ports"));
        }
        if let Some(volumes) = service.get(&yaml_key("volumes")).cloned() {
            let normalized = yaml_strings(Some(&volumes))
                .into_iter()
                .map(|entry| normalize_volume_entry(root, &entry))
                .collect::<Vec<_>>();
            service.insert(yaml_key("volumes"), serde_yaml::to_value(normalized)?);
        }
        if name == "gateway" {
            service.insert(
                yaml_key("image"),
                serde_yaml::Value::String(image_name.to_string()),
            );
            if scenario.load.target_service == "gateway" {
                service.insert(yaml_key("ports"), serde_yaml::to_value(vec!["14444:4444"])?);
            } else {
                service.remove(&yaml_key("ports"));
            }
            service.insert(
                yaml_key("cap_add"),
                serde_yaml::to_value(vec!["SYS_PTRACE"])?,
            );
            service.insert(
                yaml_key("security_opt"),
                serde_yaml::to_value(vec!["seccomp:unconfined"])?,
            );
            let mut volumes_list = yaml_strings(service.get(&yaml_key("volumes")));
            volumes_list.push(format!(
                "{}:/mnt/bench",
                scenario_dir
                    .canonicalize()
                    .unwrap_or_else(|_| scenario_dir.to_path_buf())
                    .display()
            ));
            service.insert(yaml_key("volumes"), serde_yaml::to_value(volumes_list)?);
            service.insert(
                yaml_key("environment"),
                serde_yaml::to_value(merge_environment(
                    service.get(&yaml_key("environment")),
                    &gateway_environment(scenario),
                ))?,
            );
        }
        if name == "nginx" {
            service.insert(yaml_key("ports"), serde_yaml::to_value(vec!["18080:80"])?);
        }
        services.insert(yaml_key(name), serde_yaml::Value::Mapping(service));
    }

    let mut root_map = serde_yaml::Mapping::new();
    root_map.insert(yaml_key("services"), serde_yaml::Value::Mapping(services));
    root_map.insert(yaml_key("networks"), networks);
    root_map.insert(yaml_key("volumes"), volumes);
    let path = root.join(DEFAULT_OUTPUT_ROOT).join("_runtime_staging");
    fs::create_dir_all(&path)?;
    let override_path = path.join(format!("{}_compose.yml", slug(&scenario.name)));
    write_text(&override_path, &serde_yaml::to_string(&root_map)?)?;
    Ok(override_path)
}

fn yaml_strings(value: Option<&serde_yaml::Value>) -> Vec<String> {
    value
        .and_then(serde_yaml::Value::as_sequence)
        .map(|items| {
            items
                .iter()
                .filter_map(serde_yaml::Value::as_str)
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn merge_environment(
    existing: Option<&serde_yaml::Value>,
    overrides: &BTreeMap<String, String>,
) -> Vec<String> {
    let mut merged = BTreeMap::new();
    for item in yaml_strings(existing) {
        if let Some((key, value)) = item.split_once('=') {
            merged.insert(key.trim().to_string(), value.trim().to_string());
        }
    }
    for (key, value) in overrides {
        merged.insert(key.clone(), value.clone());
    }
    merged
        .into_iter()
        .map(|(key, value)| format!("{key}={value}"))
        .collect()
}

fn normalize_volume_entry(root: &Path, entry: &str) -> String {
    let mut parts = entry
        .split(':')
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    if parts.is_empty() {
        return entry.to_string();
    }
    let source = parts[0].clone();
    if source.starts_with('/') || source.starts_with("${") || source.is_empty() {
        return entry.to_string();
    }
    if source == "." || source.starts_with("./") || source.contains('/') {
        parts[0] = root.join(source).display().to_string();
        return parts.join(":");
    }
    entry.to_string()
}

fn gateway_environment(scenario: &ResolvedScenario) -> BTreeMap<String, String> {
    let mut env = BTreeMap::new();
    env.insert("IMAGE_LOCAL".to_string(), scenario.build.image_name.clone());
    env.insert(
        "HTTP_SERVER".to_string(),
        scenario.runtime.http_server.clone(),
    );
    env.insert(
        "TRANSPORT_TYPE".to_string(),
        scenario.runtime.transport_type.clone(),
    );
    env.insert(
        "PLUGINS_ENABLED".to_string(),
        if scenario.setup.plugins_enabled {
            "true"
        } else {
            "false"
        }
        .to_string(),
    );
    env.insert(
        "AUTH_REQUIRED".to_string(),
        if scenario.setup.auth_mode == "none" {
            "false"
        } else {
            "true"
        }
        .to_string(),
    );
    env.insert(
        "MCP_REQUIRE_AUTH".to_string(),
        if scenario.setup.auth_mode == "none" {
            "false"
        } else {
            "true"
        }
        .to_string(),
    );
    env.insert(
        "DISABLE_ACCESS_LOG".to_string(),
        scenario.gateway.disable_access_log.to_string(),
    );
    env.insert(
        "TEMPLATES_AUTO_RELOAD".to_string(),
        scenario.gateway.templates_auto_reload.to_string(),
    );
    env.insert(
        "STRUCTURED_LOGGING_DATABASE_ENABLED".to_string(),
        scenario
            .gateway
            .structured_logging_database_enabled
            .to_string(),
    );
    env.insert(
        "SQLALCHEMY_ECHO".to_string(),
        scenario.gateway.sqlalchemy_echo.to_string(),
    );
    if !scenario.gateway.log_level.is_empty() {
        env.insert("LOG_LEVEL".to_string(), scenario.gateway.log_level.clone());
    }
    if let Some(workers) = scenario.runtime.gunicorn.workers {
        env.insert("GUNICORN_WORKERS".to_string(), workers.to_string());
    }
    if let Some(timeout) = scenario.runtime.gunicorn.timeout {
        env.insert("GUNICORN_TIMEOUT".to_string(), timeout.to_string());
    }
    if let Some(backlog) = scenario.runtime.gunicorn.backlog {
        env.insert("GUNICORN_BACKLOG".to_string(), backlog.to_string());
    }
    if let Some(preload_app) = scenario.runtime.gunicorn.preload_app {
        env.insert("GUNICORN_PRELOAD_APP".to_string(), preload_app.to_string());
    }
    for key in [
        "EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED",
        "EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED",
        "EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED",
        "EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED",
        "EXPERIMENTAL_RUST_MCP_LIVE_STREAM_CORE_ENABLED",
        "EXPERIMENTAL_RUST_MCP_AFFINITY_CORE_ENABLED",
        "EXPERIMENTAL_RUST_MCP_SESSION_AUTH_REUSE_ENABLED",
    ] {
        env.entry(key.to_string())
            .or_insert_with(|| "false".to_string());
    }
    env.extend(scenario.gateway.environment.clone());
    env
}

fn yaml_key(value: &str) -> serde_yaml::Value {
    serde_yaml::Value::String(value.to_string())
}

fn run_compose(root: &Path, compose_args: &[String], extra_args: &[&str]) -> Result<()> {
    let status = Command::new(&compose_args[0])
        .current_dir(root)
        .args(&compose_args[1..])
        .args(extra_args)
        .stdin(Stdio::null())
        .status()?;
    if !status.success() {
        bail!(
            "compose command failed: {} {:?}",
            compose_args[0],
            extra_args
        );
    }
    Ok(())
}

fn service_container_id(compose_args: &[String], service: &str) -> Result<String> {
    let output = Command::new(&compose_args[0])
        .args(&compose_args[1..])
        .args(["ps", "-q", service])
        .output()?;
    if !output.status.success() {
        bail!("could not resolve compose service '{service}'");
    }
    let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if value.is_empty() {
        bail!("compose service '{service}' has no container id")
    }
    Ok(value)
}

fn wait_for_service(
    runtime: &RuntimeChoice,
    compose_args: &[String],
    service: &str,
    timeout_secs: u64,
) -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    while Instant::now() < deadline {
        if let Ok(container_id) = service_container_id(compose_args, service) {
            let output = Command::new(&runtime.engine)
                .args(["inspect", &container_id, "--format", "{{json .State}}"])
                .output()?;
            if output.status.success() {
                let payload: Value =
                    serde_json::from_slice(&output.stdout).unwrap_or_else(|_| json!({}));
                if payload
                    .get("Health")
                    .and_then(|health| health.get("Status"))
                    .and_then(Value::as_str)
                    == Some("healthy")
                    || payload.get("Running").and_then(Value::as_bool) == Some(true)
                {
                    return Ok(());
                }
            }
        }
        thread::sleep(Duration::from_secs(1));
    }
    bail!("timed out waiting for compose service '{service}'")
}

fn wait_for_gateway_health(compose_args: &[String], timeout_secs: u64) -> Result<bool> {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    let script = "python3 - <<'PY'\nimport json, sys, urllib.request\ntry:\n resp=urllib.request.urlopen('http://127.0.0.1:4444/health',timeout=2)\n payload=json.loads(resp.read())\n sys.exit(0 if payload.get('status')=='healthy' else 1)\nexcept Exception:\n sys.exit(1)\nPY";
    while Instant::now() < deadline {
        let output = Command::new(&compose_args[0])
            .args(&compose_args[1..])
            .args(["exec", "-T", "gateway", "sh", "-lc", script])
            .output()?;
        if output.status.success() {
            return Ok(true);
        }
        thread::sleep(Duration::from_secs(1));
    }
    Ok(false)
}

fn benchmark_token_command() -> String {
    "python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --admin --full-name 'Benchmark Admin' --exp 10080 --secret \"${JWT_SECRET_KEY}\" --algo HS256".to_string()
}

fn benchmark_token(compose_args: &[String]) -> Result<String> {
    let command = benchmark_token_command();
    let output = Command::new(&compose_args[0])
        .args(&compose_args[1..])
        .args(["exec", "-T", "gateway", "sh", "-lc", &command])
        .output()?;
    if !output.status.success() {
        bail!("failed to mint benchmark token");
    }
    let combined = format!(
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    for token in combined.split_whitespace() {
        if token.starts_with("eyJ") && token.matches('.').count() == 2 {
            return Ok(token.to_string());
        }
    }
    bail!("gateway token generation did not emit a jwt")
}

pub fn write_goose_stats_csv(request_log_path: &Path, csv_prefix: &Path) -> Result<()> {
    if !request_log_path.exists() {
        return Ok(());
    }
    let mut rows = Vec::new();
    let mut reader = ReaderBuilder::new().from_path(request_log_path)?;
    for row in reader.deserialize::<BTreeMap<String, String>>() {
        rows.push(row?);
    }
    let mut groups: BTreeMap<String, Vec<BTreeMap<String, String>>> = BTreeMap::new();
    for row in rows.iter() {
        let name = row
            .get("name")
            .cloned()
            .unwrap_or_else(|| "unknown".to_string());
        groups.entry(name).or_default().push(row.clone());
    }
    let stats_path = PathBuf::from(format!("{}_stats.csv", csv_prefix.display()));
    let mut writer = WriterBuilder::new().from_path(stats_path)?;
    writer.write_record([
        "Name",
        "Request Count",
        "Failure Count",
        "Average Response Time",
        "Min Response Time",
        "Max Response Time",
        "50%",
        "95%",
        "99%",
    ])?;
    let aggregate = aggregate_rows("Aggregated", &rows);
    writer.serialize(&aggregate)?;
    for (name, group) in groups {
        writer.serialize(&aggregate_rows(&name, &group))?;
    }
    writer.flush()?;

    let mut by_second: BTreeMap<i64, Vec<BTreeMap<String, String>>> = BTreeMap::new();
    for row in rows.iter() {
        let second = row
            .get("elapsed")
            .and_then(|value| value.parse::<f64>().ok())
            .unwrap_or(0.0) as i64;
        by_second.entry(second).or_default().push(row.clone());
    }
    let history_path = PathBuf::from(format!("{}_stats_history.csv", csv_prefix.display()));
    let mut history = WriterBuilder::new().from_path(history_path)?;
    history.write_record([
        "Timestamp",
        "Requests/s",
        "95%",
        "99%",
        "Total Request Count",
        "Total Failure Count",
        "Total Median Response Time",
        "Total Average Response Time",
    ])?;
    let mut cumulative = Vec::new();
    let mut cumulative_failures = 0u64;
    for (second, batch) in by_second {
        cumulative.extend(batch.clone());
        cumulative_failures += batch
            .iter()
            .filter(|row| {
                row.get("success")
                    .map(|value| value != "true")
                    .unwrap_or(false)
            })
            .count() as u64;
        let response_times = batch.iter().map(response_time).collect::<Vec<_>>();
        let cumulative_times = cumulative.iter().map(response_time).collect::<Vec<_>>();
        history.write_record(&[
            second.to_string(),
            batch.len().to_string(),
            percentile(&response_times, 0.95).to_string(),
            percentile(&response_times, 0.99).to_string(),
            cumulative.len().to_string(),
            cumulative_failures.to_string(),
            percentile(&cumulative_times, 0.50).to_string(),
            average(&cumulative_times).to_string(),
        ])?;
    }
    history.flush()?;
    Ok(())
}

#[derive(Serialize)]
struct GooseStatsRow {
    #[serde(rename = "Name")]
    name: String,
    #[serde(rename = "Request Count")]
    request_count: String,
    #[serde(rename = "Failure Count")]
    failure_count: String,
    #[serde(rename = "Average Response Time")]
    average_response_time: String,
    #[serde(rename = "Min Response Time")]
    min_response_time: String,
    #[serde(rename = "Max Response Time")]
    max_response_time: String,
    #[serde(rename = "50%")]
    p50: String,
    #[serde(rename = "95%")]
    p95: String,
    #[serde(rename = "99%")]
    p99: String,
}

fn aggregate_rows(name: &str, rows: &[BTreeMap<String, String>]) -> GooseStatsRow {
    let response_times = rows.iter().map(response_time).collect::<Vec<_>>();
    let failures = rows
        .iter()
        .filter(|row| {
            row.get("success")
                .map(|value| value != "true")
                .unwrap_or(false)
        })
        .count();
    GooseStatsRow {
        name: name.to_string(),
        request_count: rows.len().to_string(),
        failure_count: failures.to_string(),
        average_response_time: average(&response_times).to_string(),
        min_response_time: response_times
            .iter()
            .cloned()
            .fold(0.0_f64, f64::min)
            .to_string(),
        max_response_time: response_times
            .iter()
            .cloned()
            .fold(0.0_f64, f64::max)
            .to_string(),
        p50: percentile(&response_times, 0.50).to_string(),
        p95: percentile(&response_times, 0.95).to_string(),
        p99: percentile(&response_times, 0.99).to_string(),
    }
}

fn response_time(row: &BTreeMap<String, String>) -> f64 {
    row.get("response_time")
        .and_then(|value| value.parse::<f64>().ok())
        .unwrap_or(0.0)
}

fn average(values: &[f64]) -> f64 {
    if values.is_empty() {
        0.0
    } else {
        values.iter().sum::<f64>() / values.len() as f64
    }
}

fn percentile(values: &[f64], pct: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    let index = ((sorted.len().saturating_sub(1)) as f64 * pct).round() as usize;
    sorted[index.min(sorted.len().saturating_sub(1))]
}

pub fn collect_endpoint_metrics(
    csv_prefix: &Path,
    measurement: &MeasurementConfig,
) -> Result<Value> {
    let path = PathBuf::from(format!("{}_stats.csv", csv_prefix.display()));
    if !path.exists() {
        return Ok(json!({"status":"unavailable","reason":"Goose stats CSV not found"}));
    }
    let mut reader = ReaderBuilder::new().from_path(path)?;
    let rows = reader
        .deserialize::<BTreeMap<String, String>>()
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let aggregate = rows
        .iter()
        .find(|row| {
            row.get("Name")
                .map(|value| value == "Aggregated")
                .unwrap_or(false)
        })
        .cloned()
        .unwrap_or_default();
    let endpoints = rows
        .into_iter()
        .filter(|row| {
            row.get("Name")
                .map(|value| value != "Aggregated")
                .unwrap_or(false)
        })
        .collect::<Vec<_>>();
    let window = measurement_window_summary(csv_prefix, measurement)?;
    Ok(json!({
        "status":"ok",
        "aggregated": aggregate,
        "measurement_window": window,
        "endpoints": endpoints,
    }))
}

fn measurement_window_summary(csv_prefix: &Path, measurement: &MeasurementConfig) -> Result<Value> {
    let path = PathBuf::from(format!("{}_stats_history.csv", csv_prefix.display()));
    if !path.exists() {
        return Ok(json!({"status":"unavailable","reason":"Goose stats history CSV not found"}));
    }
    let mut reader = ReaderBuilder::new().from_path(path)?;
    let rows = reader
        .deserialize::<BTreeMap<String, String>>()
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if rows.is_empty() {
        return Ok(json!({"status":"unavailable","reason":"Goose stats history CSV was empty"}));
    }
    let warmup = measurement.warmup_seconds as i64;
    let cooldown = measurement.cooldown_seconds as i64;
    let max_timestamp = rows
        .iter()
        .filter_map(|row| {
            row.get("Timestamp")
                .and_then(|value| value.parse::<i64>().ok())
        })
        .max()
        .unwrap_or(0);
    let window = rows
        .iter()
        .filter(|row| {
            let ts = row
                .get("Timestamp")
                .and_then(|value| value.parse::<i64>().ok())
                .unwrap_or(0);
            ts >= warmup && ts <= (max_timestamp - cooldown)
        })
        .cloned()
        .collect::<Vec<_>>();
    if window.is_empty() {
        return Ok(
            json!({"status":"unavailable","reason":"Measurement window did not overlap with Goose stats history"}),
        );
    }
    Ok(json!({
        "status":"ok",
        "source":"goose_stats_history_window",
        "warmup_seconds": measurement.warmup_seconds,
        "measure_seconds": measurement.measure_seconds,
        "cooldown_seconds": measurement.cooldown_seconds,
        "samples": window.len(),
        "aggregated": {
            "Request Count": window.last().and_then(|row| row.get("Total Request Count")).cloned().unwrap_or_else(|| "0".to_string()),
            "Failure Count": window.last().and_then(|row| row.get("Total Failure Count")).cloned().unwrap_or_else(|| "0".to_string()),
            "Requests/s": average(&window.iter().filter_map(|row| row.get("Requests/s").and_then(|value| value.parse::<f64>().ok())).collect::<Vec<_>>()),
            "95%": window.iter().filter_map(|row| row.get("95%").and_then(|value| value.parse::<f64>().ok())).fold(0.0_f64, f64::max),
            "99%": window.iter().filter_map(|row| row.get("99%").and_then(|value| value.parse::<f64>().ok())).fold(0.0_f64, f64::max),
        }
    }))
}

pub fn build_run_summary(suite: &SuiteMeta, summaries: &[ScenarioSummary]) -> Value {
    json!({
        "suite_name": suite.name,
        "scenario_count": summaries.len(),
        "scenarios": summaries.iter().map(|summary| json!({
            "scenario": summary.scenario,
            "status": summary.status,
            "runtime": summary.runtime.http_server,
            "auth_mode": summary.setup.auth_mode,
        })).collect::<Vec<_>>()
    })
}

pub fn build_comparison_report(summaries: &[ScenarioSummary]) -> Value {
    let mut comparisons = Vec::new();
    for pair in summaries.windows(2) {
        let left = &pair[0];
        let right = &pair[1];
        let left_rps = metric_value(&left.endpoint_metrics, "Requests/s");
        let right_rps = metric_value(&right.endpoint_metrics, "Requests/s");
        let left_p95 = metric_value(&left.endpoint_metrics, "95%");
        let right_p95 = metric_value(&right.endpoint_metrics, "95%");
        comparisons.push(json!({
            "left": left.scenario,
            "right": right.scenario,
            "rps_delta": right_rps - left_rps,
            "p95_delta": right_p95 - left_p95,
            "changed_dimensions": changed_dimensions(left, right),
        }));
    }
    json!({ "comparisons": comparisons })
}

fn metric_value(metrics: &Value, key: &str) -> f64 {
    metrics
        .get("measurement_window")
        .and_then(|window| window.get("aggregated"))
        .and_then(|aggregated| aggregated.get(key))
        .and_then(|value| {
            value
                .as_f64()
                .or_else(|| value.as_str().and_then(|inner| inner.parse::<f64>().ok()))
        })
        .unwrap_or(0.0)
}

fn changed_dimensions(left: &ScenarioSummary, right: &ScenarioSummary) -> Vec<String> {
    let mut dimensions = Vec::new();
    if left.runtime.http_server != right.runtime.http_server {
        dimensions.push("runtime.http_server".to_string());
    }
    if left.setup.auth_mode != right.setup.auth_mode {
        dimensions.push("setup.auth_mode".to_string());
    }
    if left.load.driver != right.load.driver {
        dimensions.push("load.driver".to_string());
    }
    dimensions
}

pub fn regenerate_reports(run_dir: &Path) -> Result<PathBuf> {
    let mut summaries = Vec::new();
    let scenarios_dir = run_dir.join("scenarios");
    for entry in fs::read_dir(&scenarios_dir)? {
        let path = entry?.path().join("summary.json");
        if path.exists() {
            let raw = fs::read_to_string(&path)?;
            summaries.push(serde_json::from_str::<ScenarioSummary>(&raw)?);
        }
    }
    let suite = SuiteMeta {
        name: run_dir
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("benchmark-run")
            .to_string(),
        ..SuiteMeta::default()
    };
    let run_summary = build_run_summary(&suite, &summaries);
    write_json(&run_dir.join("run_summary.json"), &run_summary)?;
    write_text(
        &run_dir.join("run_summary.md"),
        &render_run_summary_markdown(&run_summary),
    )?;
    let comparison = build_comparison_report(&summaries);
    write_json(
        &run_dir.join("scenario_comparison_report.json"),
        &comparison,
    )?;
    write_text(
        &run_dir.join("scenario_comparison_report.md"),
        &render_comparison_markdown(&comparison),
    )?;
    write_text(
        &run_dir.join("scenario_comparison_report.html"),
        &render_comparison_html(&comparison),
    )?;
    Ok(run_dir.to_path_buf())
}

fn render_run_summary_markdown(summary: &Value) -> String {
    let mut lines = vec![
        "# Benchmark Run Summary".to_string(),
        String::new(),
        format!(
            "- Suite: `{}`",
            summary
                .get("suite_name")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
        ),
        format!(
            "- Scenario count: `{}`",
            summary
                .get("scenario_count")
                .and_then(Value::as_u64)
                .unwrap_or(0)
        ),
        String::new(),
    ];
    if let Some(items) = summary.get("scenarios").and_then(Value::as_array) {
        for item in items {
            lines.push(format!(
                "- `{}`: status=`{}` runtime=`{}` auth=`{}`",
                item.get("scenario")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                item.get("status")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                item.get("runtime")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                item.get("auth_mode")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
            ));
        }
    }
    lines.join("\n")
}

fn render_comparison_markdown(report: &Value) -> String {
    let mut lines = vec!["# Scenario Comparison Report".to_string(), String::new()];
    if let Some(items) = report.get("comparisons").and_then(Value::as_array) {
        for item in items {
            lines.push(format!(
                "- `{}` vs `{}`: rps_delta=`{:.2}` p95_delta=`{:.2}`",
                item.get("left").and_then(Value::as_str).unwrap_or("left"),
                item.get("right").and_then(Value::as_str).unwrap_or("right"),
                item.get("rps_delta").and_then(Value::as_f64).unwrap_or(0.0),
                item.get("p95_delta").and_then(Value::as_f64).unwrap_or(0.0)
            ));
        }
    }
    lines.join("\n")
}

fn render_comparison_html(report: &Value) -> String {
    let mut rows = String::new();
    if let Some(items) = report.get("comparisons").and_then(Value::as_array) {
        for item in items {
            rows.push_str(&format!(
                "<tr><td>{}</td><td>{}</td><td>{:.2}</td><td>{:.2}</td></tr>",
                html_escape(item.get("left").and_then(Value::as_str).unwrap_or("left")),
                html_escape(item.get("right").and_then(Value::as_str).unwrap_or("right")),
                item.get("rps_delta").and_then(Value::as_f64).unwrap_or(0.0),
                item.get("p95_delta").and_then(Value::as_f64).unwrap_or(0.0),
            ));
        }
    }
    format!(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Scenario Comparison Report</title></head><body><h1>Scenario Comparison Report</h1><table border=\"1\"><thead><tr><th>Left</th><th>Right</th><th>RPS Delta</th><th>P95 Delta</th></tr></thead><tbody>{rows}</tbody></table></body></html>"
    )
}

fn html_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn write_json<T: Serialize>(path: &Path, payload: &T) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, serde_json::to_vec_pretty(payload)?)?;
    Ok(())
}

fn write_text(path: &Path, payload: &str) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, payload)?;
    Ok(())
}

fn slug(value: &str) -> String {
    value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>()
        .split('-')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("-")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_repo_root() -> &'static Path {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .parent()
            .unwrap()
    }

    #[test]
    fn resolves_suite_with_driver_contract() {
        let root = fixture_repo_root();
        let suite = load_suite(root, "rust-mcp-runtime-300", false).unwrap();
        assert_eq!(suite.scenarios.len(), 2);
        assert_eq!(suite.scenarios[0].load.driver, DEFAULT_GOSE_BIN);
    }

    #[test]
    fn builds_goose_command_for_local_driver() {
        let root = fixture_repo_root();
        let scenario = load_suite(root, "rust-mcp-runtime-300", true)
            .unwrap()
            .scenarios
            .remove(0);
        let temp = std::env::temp_dir().join("benchmark-runner-tests");
        let spec = build_goose_command(root, &scenario, &temp, "goose_metrics", false);
        assert_eq!(spec.command, "cargo");
        assert!(spec.args.iter().any(|part| {
            part.ends_with("tools_rust/contextforge_benchmark/contextforge_goose/Cargo.toml")
        }));
        assert!(
            spec.args
                .iter()
                .any(|part| part.ends_with("goose_metrics_requests.csv"))
        );
    }

    #[test]
    fn rejects_legacy_goosefile_field() {
        let tempdir = std::env::temp_dir().join("benchmark-runner-legacy-goosefile");
        let _ = std::fs::remove_dir_all(&tempdir);
        std::fs::create_dir_all(&tempdir).unwrap();
        let path = tempdir.join("legacy-goosefile.toml");
        std::fs::write(
            &path,
            r#"
[suite]
name = "legacy"

[defaults.load]
goosefile = "legacy/goosefile_benchmark.rs"

[[scenario]]
name = "legacy-scenario"
"#,
        )
        .unwrap();

        let error = load_suite(&tempdir, path.to_str().unwrap(), false)
            .unwrap_err()
            .to_string();
        assert!(error.contains("legacy load.goosefile"));
        assert!(error.contains("contextforge_goose"));
        let _ = std::fs::remove_dir_all(&tempdir);
    }

    #[test]
    fn rejects_legacy_locust_fields() {
        let tempdir = std::env::temp_dir().join("benchmark-runner-legacy-locust");
        let _ = std::fs::remove_dir_all(&tempdir);
        std::fs::create_dir_all(&tempdir).unwrap();
        let path = tempdir.join("legacy-locust.toml");
        std::fs::write(
            &path,
            r#"
[suite]
name = "legacy"

[defaults.load]
driver = "contextforge_goose"

[[scenario]]
name = "legacy-scenario"

[scenario.load]
driver = "contextforge_goose"
locustfile = "loadtests/old_locust.py"
repo_url = "https://example.invalid/repo.git"
git_ref = "main"
git_commit = "deadbeef"
"#,
        )
        .unwrap();

        let error = load_suite(&tempdir, path.to_str().unwrap(), false)
            .unwrap_err()
            .to_string();
        assert!(error.contains("legacy load.locustfile") || error.contains("legacy load.repo_url"));
        assert!(error.contains("contextforge_goose"));
        let _ = std::fs::remove_dir_all(&tempdir);
    }

    #[test]
    fn rejects_non_rust_driver() {
        let tempdir = std::env::temp_dir().join("benchmark-runner-wrong-driver");
        let _ = std::fs::remove_dir_all(&tempdir);
        std::fs::create_dir_all(&tempdir).unwrap();
        let path = tempdir.join("wrong-driver.toml");
        std::fs::write(
            &path,
            r#"
[suite]
name = "legacy"

[defaults.load]
driver = "goosefile"

[[scenario]]
name = "legacy-scenario"
"#,
        )
        .unwrap();

        let error = load_suite(&tempdir, path.to_str().unwrap(), false)
            .unwrap_err()
            .to_string();
        assert!(error.contains("unsupported driver"));
        assert!(error.contains("contextforge_goose"));
        let _ = std::fs::remove_dir_all(&tempdir);
    }

    #[test]
    fn rejects_locust_only_goose_extra_args() {
        let tempdir = std::env::temp_dir().join("benchmark-runner-legacy-extra-args");
        let _ = std::fs::remove_dir_all(&tempdir);
        std::fs::create_dir_all(tempdir.join("tools_rust/contextforge_benchmark/assets")).unwrap();
        let path = tempdir.join("suite.toml");
        std::fs::write(
            tempdir.join("tools_rust/contextforge_benchmark/assets/Containerfile"),
            "FROM scratch\n",
        )
        .unwrap();
        std::fs::write(
            &path,
            r#"
[suite]
name = "legacy-extra-args"

[defaults.build]
container_file = "tools_rust/contextforge_benchmark/assets/Containerfile"

[defaults.load]
driver = "contextforge_goose"
extra_args = ["--reset-stats"]

[[scenario]]
name = "legacy-extra-args-scenario"
"#,
        )
        .unwrap();

        let error = load_suite(&tempdir, path.to_str().unwrap(), false)
            .unwrap_err()
            .to_string();
        assert!(error.contains("--reset-stats"));
        assert!(error.contains("Goose"));
        let _ = std::fs::remove_dir_all(&tempdir);
    }

    #[test]
    fn writes_goose_stats_csv_without_map_serialization_errors() {
        let tempdir = std::env::temp_dir().join("benchmark-runner-goose-csv");
        let _ = std::fs::remove_dir_all(&tempdir);
        std::fs::create_dir_all(&tempdir).unwrap();
        let request_log = tempdir.join("requests.csv");
        std::fs::write(
            &request_log,
            "name,elapsed,response_time,success\n/mcp tools/list,1,12.0,true\n/mcp tools/list,2,18.0,true\n",
        )
        .unwrap();

        let csv_prefix = tempdir.join("goose");
        write_goose_stats_csv(&request_log, &csv_prefix).unwrap();

        let stats = std::fs::read_to_string(tempdir.join("goose_stats.csv")).unwrap();
        assert!(stats.contains("Aggregated"));
        assert!(stats.contains("/mcp tools/list"));
        let _ = std::fs::remove_dir_all(&tempdir);
    }

    #[test]
    fn resolves_new_uncharted_surface_suites() {
        let root = fixture_repo_root();
        for suite in [
            "admin-plugins-300",
            "rest-discovery-300",
            "mcp-resources-300",
            "mcp-prompts-300",
        ] {
            let resolved = load_suite(root, suite, false).unwrap();
            assert_eq!(resolved.scenarios.len(), 2, "{suite}");
        }
    }

    #[test]
    fn mcp_focused_suites_compare_python_and_rust_runtime() {
        let root = fixture_repo_root();
        for suite in [
            "rust-mcp-runtime-300",
            "rest-discovery-300",
            "mcp-resources-300",
            "mcp-prompts-300",
        ] {
            let resolved = load_suite(root, suite, false).unwrap();
            let baseline = &resolved.scenarios[0];
            let variant = &resolved.scenarios[1];

            assert_eq!(baseline.setup.expected_mcp_runtime.as_deref(), None, "{suite}");
            assert_eq!(
                variant.setup.expected_mcp_runtime.as_deref(),
                Some("rust"),
                "{suite}"
            );
            assert_eq!(
                variant.setup.expected_mcp_runtime_mode.as_deref(),
                Some("rust-managed"),
                "{suite}"
            );
            assert_eq!(
                variant
                    .gateway
                    .environment
                    .get("EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED")
                    .map(String::as_str),
                Some("true"),
                "{suite}"
            );
            assert_eq!(
                variant
                    .gateway
                    .environment
                    .get("RUST_MCP_MODE")
                    .map(String::as_str),
                Some("edge"),
                "{suite}"
            );
        }
    }

    #[test]
    fn streaming_command_reports_live_stdout_and_stderr_lines() {
        let mut command = Command::new("sh");
        command.args([
            "-c",
            "printf 'alpha\\n'; sleep 0.1; printf 'beta\\n' >&2; sleep 0.1; printf 'gamma\\n'",
        ]);
        let mut events = Vec::new();

        let result = run_command_streaming(&mut command, |stream, line| {
            events.push(format!("{stream}:{line}"));
        })
        .unwrap();

        assert!(result.success);
        assert_eq!(
            events,
            vec![
                "stdout:alpha".to_string(),
                "stderr:beta".to_string(),
                "stdout:gamma".to_string()
            ]
        );
        assert!(result.stdout.contains("alpha"));
        assert!(result.stdout.contains("gamma"));
        assert!(result.stderr.contains("beta"));
    }

    #[test]
    fn scenario_status_fails_when_endpoint_metrics_report_failures() {
        let metrics = json!({
            "aggregated": {
                "Failure Count": "5"
            }
        });

        assert!(has_endpoint_failures(&metrics));
        assert!(!determine_scenario_success(true, &metrics));
    }

    #[test]
    fn benchmark_token_command_uses_gateway_jwt_secret_env() {
        let command = benchmark_token_command();
        assert!(command.contains("JWT_SECRET_KEY"));
        assert!(!command.contains("my-test-key"));
    }

    #[test]
    fn nginx_targeted_override_does_not_bind_gateway_host_port() {
        let tempdir = std::env::temp_dir().join("benchmark-runner-compose-ports");
        let _ = std::fs::remove_dir_all(&tempdir);
        std::fs::create_dir_all(tempdir.join("reports/benchmarks/test-scenario")).unwrap();
        std::fs::write(
            tempdir.join("docker-compose.yml"),
            r#"
services:
  postgres:
    image: postgres:16
    ports: ["5432:5432"]
  redis:
    image: redis:7
    ports: ["6379:6379"]
  pgbouncer:
    image: edoburu/pgbouncer
    ports: ["6432:6432"]
  gateway:
    image: mcpgateway/test:latest
    environment:
      - JWT_SECRET_KEY=my-test-key-but-now-longer-than-32-bytes
    ports: ["4444:4444"]
  nginx:
    image: nginx:latest
    ports: ["8080:80"]
networks: {}
volumes: {}
"#,
        )
        .unwrap();

        let scenario_dir = tempdir.join("reports/benchmarks/test-scenario");
        let scenario = ResolvedScenario {
            name: "nginx-target".to_string(),
            description: String::new(),
            scenario_type: String::new(),
            setup: SetupConfig::default(),
            build: BuildConfig::default(),
            runtime: RuntimeConfig::default(),
            gateway: GatewayConfig::default(),
            load: LoadConfig {
                target_service: "nginx".to_string(),
                ..LoadConfig::default()
            },
            measurement: MeasurementConfig::default(),
            profiling: ProfilingConfig::default(),
            execution: ExecutionConfig::default(),
            requests: RequestsConfig::default(),
        };

        let override_path =
            write_compose_override(&tempdir, &scenario, &scenario_dir, "mcpgateway/test:latest")
                .unwrap();
        let raw = std::fs::read_to_string(override_path).unwrap();
        let parsed: serde_yaml::Value = serde_yaml::from_str(&raw).unwrap();
        let services = parsed
            .get("services")
            .and_then(serde_yaml::Value::as_mapping)
            .unwrap();
        let gateway = services
            .get(serde_yaml::Value::String("gateway".to_string()))
            .and_then(serde_yaml::Value::as_mapping)
            .unwrap();
        let nginx = services
            .get(serde_yaml::Value::String("nginx".to_string()))
            .and_then(serde_yaml::Value::as_mapping)
            .unwrap();

        assert!(gateway.get("ports").is_none());
        assert_eq!(
            yaml_strings(nginx.get("ports")),
            vec!["18080:80".to_string()]
        );

        let _ = std::fs::remove_dir_all(&tempdir);
    }

    #[test]
    fn comparison_report_tracks_changed_dimensions() {
        let left = ScenarioSummary {
            scenario: "left".to_string(),
            status: "ok".to_string(),
            runtime: RuntimeConfig {
                http_server: "gunicorn".to_string(),
                ..RuntimeConfig::default()
            },
            setup: SetupConfig {
                auth_mode: "jwt".to_string(),
                ..SetupConfig::default()
            },
            load: LoadConfig {
                driver: DEFAULT_GOSE_BIN.to_string(),
                ..LoadConfig::default()
            },
            endpoint_metrics: json!({"measurement_window":{"aggregated":{"Requests/s":5.0,"95%":10.0}}}),
            ..ScenarioSummary::default()
        };
        let right = ScenarioSummary {
            scenario: "right".to_string(),
            status: "ok".to_string(),
            runtime: RuntimeConfig {
                http_server: "granian".to_string(),
                ..RuntimeConfig::default()
            },
            setup: SetupConfig {
                auth_mode: "jwt".to_string(),
                ..SetupConfig::default()
            },
            load: LoadConfig {
                driver: DEFAULT_GOSE_BIN.to_string(),
                ..LoadConfig::default()
            },
            endpoint_metrics: json!({"measurement_window":{"aggregated":{"Requests/s":8.0,"95%":7.0}}}),
            ..ScenarioSummary::default()
        };
        let report = build_comparison_report(&[left, right]);
        let first = report
            .get("comparisons")
            .and_then(Value::as_array)
            .and_then(|items| items.first())
            .unwrap();
        assert_eq!(first.get("rps_delta").and_then(Value::as_f64).unwrap(), 3.0);
        assert!(
            first
                .get("changed_dimensions")
                .unwrap()
                .to_string()
                .contains("runtime.http_server")
        );
    }
}
