use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{Result, anyhow, bail};
use serde_json::{Value, json};

use crate::{DEFAULT_OUTPUT_ROOT, ResolvedScenario, RuntimeChoice, log_progress};
use crate::lib_parts::{slug, uses_a2a_fixture, uses_fast_time_fixture, write_text};

pub(crate) fn ensure_benchmark_image(
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

pub(crate) fn write_compose_override(
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

pub(crate) fn yaml_strings(value: Option<&serde_yaml::Value>) -> Vec<String> {
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

pub(crate) fn run_compose(root: &Path, compose_args: &[String], extra_args: &[&str]) -> Result<()> {
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

pub(crate) fn service_container_id(compose_args: &[String], service: &str) -> Result<String> {
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

pub(crate) fn wait_for_service(
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

pub(crate) fn wait_for_gateway_health(compose_args: &[String], timeout_secs: u64) -> Result<bool> {
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

pub(crate) fn benchmark_token_command() -> String {
    "python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --admin --full-name 'Benchmark Admin' --exp 10080 --secret \"${JWT_SECRET_KEY}\" --algo HS256".to_string()
}

pub(crate) fn benchmark_token(compose_args: &[String]) -> Result<String> {
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
