use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;

use anyhow::{Result, anyhow, bail};
use chrono::Utc;
use serde_json::{Value, json};

use crate::lib_parts::{
    build_goose_command, ensure_benchmark_image, run_compose, slug, wait_for_gateway_health,
    wait_for_service, write_compose_override,
};
use crate::{CommandSpec, ResolvedScenario, RuntimeChoice, log_progress};

#[derive(Debug)]
pub(crate) struct RunOutput {
    pub(crate) success: bool,
    pub(crate) stdout: String,
    pub(crate) stderr: String,
}

pub(crate) fn run_command_spec(
    root: &Path,
    spec: &CommandSpec,
    token: Option<&str>,
) -> Result<RunOutput> {
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

pub(crate) fn run_command_streaming<F>(command: &mut Command, mut on_line: F) -> Result<RunOutput>
where
    F: FnMut(&str, &str),
{
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn()?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| anyhow!("missing child stdout"))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| anyhow!("missing child stderr"))?;
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

pub(crate) fn run_flamegraph(
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

pub(crate) fn start_stack(
    root: &Path,
    runtime: &RuntimeChoice,
    scenario: &ResolvedScenario,
    scenario_dir: &Path,
) -> Result<(Vec<String>, String)> {
    let image_name = ensure_benchmark_image(root, runtime, scenario)?;
    let project = format!("bench-{}-{}", slug(&scenario.name), Utc::now().timestamp());
    let override_path = write_compose_override(root, scenario, scenario_dir, &image_name)?;
    let compose = compose_args(runtime, &project, &override_path);
    let shared_services = scenario.shared_service_names();
    let gateway_services = scenario.gateway_service_names();
    if uses_fast_time_fixture(scenario) {
        // handled below
    }
    if uses_a2a_fixture(scenario) {
        // handled below
    }
    for service in &shared_services {
        log_progress(format!("Compose up: {service}"));
        run_compose(
            root,
            &compose,
            &["up", "-d", "--no-build", service.as_str()],
        )?;
        log_progress(format!("Waiting for service health: {service}"));
        wait_for_service(runtime, &compose, service, 120)?;
    }
    for service in &gateway_services {
        log_progress(format!("Compose up: {service}"));
        run_compose(
            root,
            &compose,
            &["up", "-d", "--no-build", service.as_str()],
        )?;
        log_progress(format!("Waiting for service health: {service}"));
        wait_for_service(runtime, &compose, service, 120)?;
    }
    for service in &gateway_services {
        if !wait_for_gateway_health(&compose, service, 120)? {
            bail!(
                "gateway health check failed for scenario '{}' on service '{}'",
                scenario.name,
                service
            );
        }
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
    if scenario.uses_ingress() {
        let ingress = scenario.ingress_service_name();
        log_progress(format!("Compose up: {ingress}"));
        run_compose(
            root,
            &compose,
            &["up", "-d", "--no-build", ingress.as_str()],
        )?;
        log_progress(format!("Waiting for service health: {ingress}"));
        wait_for_service(runtime, &compose, &ingress, 60)?;
    }
    Ok((compose, project))
}

pub(crate) fn stop_stack(compose_args: &[String]) {
    let _ = Command::new(&compose_args[0])
        .args(&compose_args[1..])
        .args(["down", "--remove-orphans"])
        .status();
}

pub(crate) fn uses_fast_time_fixture(scenario: &ResolvedScenario) -> bool {
    scenario
        .load
        .workload
        .endpoints
        .keys()
        .any(|name| name.contains("fast-time") || name.contains("/mcp "))
}

pub(crate) fn uses_a2a_fixture(scenario: &ResolvedScenario) -> bool {
    scenario
        .load
        .workload
        .endpoints
        .keys()
        .any(|name| name.contains("/a2a"))
}
