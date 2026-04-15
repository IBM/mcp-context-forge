use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use anyhow::{Result, bail};
use chrono::Utc;
use serde_json::{Value, json};

use crate::lib_parts::scenario_loading::{discover_scenarios, load_suite};
use crate::lib_parts::{
    benchmark_token, build_comparison_report, build_run_summary, collect_endpoint_metrics,
    render_comparison_html, render_comparison_markdown, render_run_summary_markdown,
    resolve_requests_from_workload, run_command_spec, run_flamegraph, start_stack, stop_stack,
    wait_for_gateway_health, write_goose_stats_csv, write_json, write_text,
};
use crate::{
    CommandSpec, DEFAULT_GOSE_BIN, LoadConfig, ResolvedScenario, ResolvedSuite, RuntimeChoice,
    ScenarioSummary, SuiteMeta, log_progress,
};

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
    let manifest = root.join("crates/contextforge_goose/Cargo.toml");
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
    log_progress(format!(
        "Writing benchmark artifacts to {}",
        run_dir.display()
    ));

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
        log_progress(format!(
            "Benchmark run completed successfully: {}",
            run_dir.display()
        ));
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
            scenario.name,
            command.command,
            command.args.join(" ")
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
            log_progress(format!(
                "Collecting flamegraph for scenario '{}'",
                scenario.name
            ));
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

pub(crate) fn determine_scenario_success(process_success: bool, endpoint_metrics: &Value) -> bool {
    process_success && !has_endpoint_failures(endpoint_metrics)
}

pub(crate) fn has_endpoint_failures(endpoint_metrics: &Value) -> bool {
    endpoint_metrics
        .get("aggregated")
        .and_then(|value| value.get("Failure Count"))
        .and_then(Value::as_str)
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(0)
        > 0
}
