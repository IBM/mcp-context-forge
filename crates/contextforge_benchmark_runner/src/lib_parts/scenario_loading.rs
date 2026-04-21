use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use toml::Value as TomlValue;

use crate::lib_parts::benchmark_request_names;
use crate::{
    BuildConfig, DEFAULT_GOSE_BIN, DEFAULT_SCENARIO_DIR, ExecutionConfig, GatewayConfig,
    GatewayNodeOverride, LoadConfig, MeasurementConfig, ProfilingConfig, RequestsConfig,
    ResolvedScenario, ResolvedSuite, RuntimeConfig, ScenarioEntry, ScenarioTemplate, SetupConfig,
    SuiteDocument, TopologyConfig,
};

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
    let mut topology = defaults.topology.clone();
    merge_topology(&mut topology, &scenario.topology);
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
        topology,
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
    base.trust_proxy_auth = overlay.trust_proxy_auth || base.trust_proxy_auth; // pragma: allowlist secret
    if !overlay.log_level.is_empty() {
        base.log_level = overlay.log_level.clone();
    }
    base.environment.extend(overlay.environment.clone());
}

fn merge_topology(base: &mut TopologyConfig, overlay: &TopologyConfig) {
    if overlay.mode != TopologyConfig::default().mode {
        base.mode = overlay.mode.clone();
    }
    if overlay.gateway_count != TopologyConfig::default().gateway_count {
        base.gateway_count = overlay.gateway_count;
    }
    if overlay.ingress_enabled {
        base.ingress_enabled = true;
    }
    if overlay.ingress_service != TopologyConfig::default().ingress_service {
        base.ingress_service = overlay.ingress_service.clone();
    }
    if overlay.shared_services != TopologyConfig::default().shared_services {
        base.shared_services = overlay.shared_services.clone();
    }
    if overlay.gateway_base_service != TopologyConfig::default().gateway_base_service {
        base.gateway_base_service = overlay.gateway_base_service.clone();
    }
    if overlay.gateway_name_prefix != TopologyConfig::default().gateway_name_prefix {
        base.gateway_name_prefix = overlay.gateway_name_prefix.clone();
    }
    if !overlay.gateway_override.is_empty() {
        base.gateway_override = overlay.gateway_override.clone();
    }
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
    validate_topology(scenario)?;
    Ok(())
}

fn validate_topology(scenario: &ResolvedScenario) -> Result<()> {
    match scenario.topology.mode.as_str() {
        "single_gateway" => {}
        "multi_gateway" => {
            if scenario.topology.gateway_count < 2 {
                bail!(
                    "scenario '{}' must set topology.gateway_count >= 2 for multi_gateway mode",
                    scenario.name
                );
            }
            if !scenario.topology.ingress_enabled {
                bail!(
                    "scenario '{}' must enable topology.ingress_enabled for multi_gateway mode",
                    scenario.name
                );
            }
            if scenario.load.target_service != scenario.ingress_service_name() {
                bail!(
                    "scenario '{}' must target ingress service '{}' in multi_gateway mode; direct gateway targeting is not supported",
                    scenario.name,
                    scenario.ingress_service_name()
                );
            }
        }
        other => {
            bail!(
                "scenario '{}' uses unsupported topology.mode '{}'",
                scenario.name,
                other
            );
        }
    }

    let expected_shared = ["postgres", "redis", "pgbouncer"];
    if scenario.shared_service_names() != expected_shared {
        bail!(
            "scenario '{}' uses unsupported topology.shared_services; v1 supports only {:?}",
            scenario.name,
            expected_shared
        );
    }
    if scenario.topology.gateway_base_service.trim().is_empty() {
        bail!(
            "scenario '{}' must define topology.gateway_base_service",
            scenario.name
        );
    }
    if scenario.topology.ingress_service.trim().is_empty() {
        bail!(
            "scenario '{}' must define topology.ingress_service",
            scenario.name
        );
    }
    validate_gateway_overrides(scenario, &scenario.topology.gateway_override)?;
    Ok(())
}

fn validate_gateway_overrides(
    scenario: &ResolvedScenario,
    overrides: &[GatewayNodeOverride],
) -> Result<()> {
    let gateway_names = scenario.gateway_service_names();
    for item in overrides {
        let resolved_name = if !item.name.trim().is_empty() {
            item.name.clone()
        } else if let Some(index) = item.index {
            if index == 0 || index > gateway_names.len() as u32 {
                bail!(
                    "scenario '{}' topology.gateway_override index {} is out of range",
                    scenario.name,
                    index
                );
            }
            gateway_names[index as usize - 1].clone()
        } else {
            bail!(
                "scenario '{}' topology.gateway_override entries must set name or index",
                scenario.name
            );
        };
        if !gateway_names.contains(&resolved_name) {
            bail!(
                "scenario '{}' topology.gateway_override targets unknown gateway '{}'",
                scenario.name,
                resolved_name
            );
        }
        if let Some(index) = item.index {
            let expected = &gateway_names[index as usize - 1];
            if !item.name.trim().is_empty() && item.name != *expected {
                bail!(
                    "scenario '{}' topology.gateway_override name '{}' does not match index {} ('{}')",
                    scenario.name,
                    item.name,
                    index,
                    expected
                );
            }
        }
    }
    Ok(())
}
