use super::*;
use std::path::Path;
use std::process::Command;

use serde_json::json;

fn fixture_repo_root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
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
    assert!(
        spec.args
            .iter()
            .any(|part| { part.ends_with("crates/contextforge_goose/Cargo.toml") })
    );
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
    std::fs::create_dir_all(tempdir.join("crates/contextforge_benchmark_runner/assets")).unwrap();
    let path = tempdir.join("suite.toml");
    std::fs::write(
        tempdir.join("crates/contextforge_benchmark_runner/assets/Containerfile"),
        "FROM scratch\n",
    )
    .unwrap();
    std::fs::write(
        &path,
        r#"
[suite]
name = "legacy-extra-args"

[defaults.build]
container_file = "crates/contextforge_benchmark_runner/assets/Containerfile"

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
fn benchmark_scenarios_cover_locust_workload_families() {
    let root = fixture_repo_root();
    let scenario_names = discover_scenarios(root).unwrap();
    let stems: std::collections::BTreeSet<String> = scenario_names
        .iter()
        .map(|name| name.trim_end_matches("-300").to_string())
        .collect();

    for required in [
        "agentgateway-mcp-server-time",
        "baseline",
        "echo-delay",
        "highthroughput",
        "mcp-isolation",
        "mcp-protocol",
        "rate-limiter",
        "rate-limiter-scale",
        "rate-limiter-redis-capacity",
        "secret-detection",
        "slow-time-server",
        "spin-detector",
    ] {
        assert!(
            stems.contains(required),
            "missing benchmark scenario suite `{required}`"
        );
    }

    for suite in scenario_names {
        load_suite(root, &suite, false).unwrap_or_else(|error| {
            panic!("failed to load suite `{suite}`: {error}");
        });
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

        assert_eq!(
            baseline.setup.expected_mcp_runtime.as_deref(),
            None,
            "{suite}"
        );
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
        topology: TopologyConfig::default(),
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
fn multi_gateway_override_generates_gateway_fleet_and_ingress_upstreams() {
    let tempdir = std::env::temp_dir().join("benchmark-runner-compose-multi-gateway");
    let _ = std::fs::remove_dir_all(&tempdir);
    std::fs::create_dir_all(tempdir.join("reports/benchmarks/test-scenario")).unwrap();
    std::fs::create_dir_all(tempdir.join("infra/nginx")).unwrap();
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
      - LOG_LEVEL=INFO
    ports: ["4444:4444"]
  nginx:
    image: nginx:latest
    depends_on:
      gateway:
        condition: service_healthy
    volumes:
      - ./infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    ports: ["8080:80"]
networks: {}
volumes: {}
"#,
    )
    .unwrap();
    std::fs::write(
        tempdir.join("infra/nginx/nginx.conf"),
        std::fs::read_to_string(fixture_repo_root().join("infra/nginx/nginx.conf")).unwrap(),
    )
    .unwrap();

    let scenario_dir = tempdir.join("reports/benchmarks/test-scenario");
    let scenario = ResolvedScenario {
        name: "multi-gateway".to_string(),
        description: String::new(),
        scenario_type: String::new(),
        setup: SetupConfig::default(),
        build: BuildConfig::default(),
        runtime: RuntimeConfig::default(),
        topology: TopologyConfig {
            mode: "multi_gateway".to_string(),
            gateway_count: 3,
            ingress_enabled: true,
            gateway_override: vec![GatewayNodeOverride {
                index: Some(2),
                environment: [("LOG_LEVEL".to_string(), "DEBUG".to_string())]
                    .into_iter()
                    .collect(),
                labels: [("bench.node".to_string(), "two".to_string())]
                    .into_iter()
                    .collect(),
                ..GatewayNodeOverride::default()
            }],
            ..TopologyConfig::default()
        },
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
    let raw = std::fs::read_to_string(&override_path).unwrap();
    let parsed: serde_yaml::Value = serde_yaml::from_str(&raw).unwrap();
    let services = parsed
        .get("services")
        .and_then(serde_yaml::Value::as_mapping)
        .unwrap();
    for service in [
        "postgres",
        "redis",
        "pgbouncer",
        "nginx",
        "gateway-1",
        "gateway-2",
        "gateway-3",
    ] {
        assert!(services.contains_key(&serde_yaml::Value::String(service.to_string())));
    }
    let gateway_1 = services
        .get(serde_yaml::Value::String("gateway-1".to_string()))
        .and_then(serde_yaml::Value::as_mapping)
        .unwrap();
    let gateway_2 = services
        .get(serde_yaml::Value::String("gateway-2".to_string()))
        .and_then(serde_yaml::Value::as_mapping)
        .unwrap();
    let nginx = services
        .get(serde_yaml::Value::String("nginx".to_string()))
        .and_then(serde_yaml::Value::as_mapping)
        .unwrap();

    assert!(gateway_1.get("ports").is_none());
    assert!(gateway_2.get("ports").is_none());
    assert_eq!(
        yaml_strings(nginx.get("ports")),
        vec!["18080:80".to_string()]
    );
    assert!(
        yaml_strings(gateway_2.get("environment"))
            .iter()
            .any(|value| value == "LOG_LEVEL=DEBUG")
    );
    assert_eq!(
        gateway_2
            .get("labels")
            .and_then(serde_yaml::Value::as_mapping)
            .and_then(|labels| labels.get(&serde_yaml::Value::String("bench.node".to_string())))
            .and_then(serde_yaml::Value::as_str),
        Some("two")
    );

    let nginx_mount = yaml_strings(nginx.get("volumes"))
        .into_iter()
        .find(|entry| entry.contains("/etc/nginx/nginx.conf"))
        .unwrap();
    let generated_config = Path::new(nginx_mount.split(':').next().unwrap());
    let config_raw = std::fs::read_to_string(generated_config).unwrap();
    assert!(config_raw.contains("upstream benchmark_gateway_backend"));
    assert!(config_raw.contains("server gateway-1:4444 max_fails=0;"));
    assert!(config_raw.contains("server gateway-2:4444 max_fails=0;"));
    assert!(config_raw.contains("server gateway-3:4444 max_fails=0;"));

    let _ = std::fs::remove_dir_all(&tempdir);
}

#[test]
fn load_suite_resolves_multi_gateway_defaults_and_validates_targeting() {
    let tempdir = std::env::temp_dir().join("benchmark-runner-topology-suite");
    let _ = std::fs::remove_dir_all(&tempdir);
    std::fs::create_dir_all(tempdir.join("crates/contextforge_benchmark_runner/assets/scenarios"))
        .unwrap();
    std::fs::write(
        tempdir.join("crates/contextforge_benchmark_runner/assets/scenarios/multi.toml"),
        r#"
[suite]
name = "multi"

[defaults.build]
container_file = "crates/contextforge_benchmark_runner/assets/Containerfile"

[defaults.load]
driver = "contextforge_goose"
target_service = "nginx"

[defaults.topology]
mode = "multi_gateway"
gateway_count = 2
ingress_enabled = true

[[scenario]]
name = "multi-gateway"
"#,
    )
    .unwrap();
    std::fs::create_dir_all(tempdir.join("crates/contextforge_benchmark_runner/assets")).unwrap();
    std::fs::write(
        tempdir.join("crates/contextforge_benchmark_runner/assets/Containerfile"),
        "FROM scratch\n",
    )
    .unwrap();

    let suite = load_suite(&tempdir, "multi", false).unwrap();
    let scenario = &suite.scenarios[0];
    assert_eq!(scenario.topology.mode, "multi_gateway");
    assert_eq!(scenario.topology.gateway_count, 2);
    assert_eq!(
        scenario.gateway_service_names(),
        vec!["gateway-1", "gateway-2"]
    );
    assert_eq!(scenario.bootstrap_gateway_service(), "gateway-1");

    let invalid = ResolvedScenario {
        load: LoadConfig {
            target_service: "gateway".to_string(),
            ..scenario.load.clone()
        },
        ..scenario.clone()
    };
    let error = validate_scenario(&tempdir, &invalid)
        .unwrap_err()
        .to_string();
    assert!(error.contains("must target ingress service"));

    let _ = std::fs::remove_dir_all(&tempdir);
}

#[test]
fn validate_scenario_rejects_invalid_multi_gateway_topology() {
    let scenario = ResolvedScenario {
        name: "bad".to_string(),
        description: String::new(),
        scenario_type: String::new(),
        setup: SetupConfig::default(),
        build: BuildConfig::default(),
        runtime: RuntimeConfig::default(),
        topology: TopologyConfig {
            mode: "multi_gateway".to_string(),
            gateway_count: 1,
            ingress_enabled: false,
            ..TopologyConfig::default()
        },
        gateway: GatewayConfig::default(),
        load: LoadConfig {
            driver: DEFAULT_GOSE_BIN.to_string(),
            target_service: "gateway".to_string(),
            ..LoadConfig::default()
        },
        measurement: MeasurementConfig::default(),
        profiling: ProfilingConfig::default(),
        execution: ExecutionConfig::default(),
        requests: RequestsConfig::default(),
    };
    let error = validate_scenario(fixture_repo_root(), &scenario)
        .unwrap_err()
        .to_string();
    assert!(error.contains("gateway_count >= 2") || error.contains("ingress_enabled"));
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
        topology: TopologyConfig {
            mode: "single_gateway".to_string(),
            gateway_count: 1,
            ..TopologyConfig::default()
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
        topology: TopologyConfig {
            mode: "multi_gateway".to_string(),
            gateway_count: 3,
            ingress_enabled: true,
            ..TopologyConfig::default()
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
    assert!(
        first
            .get("changed_dimensions")
            .unwrap()
            .to_string()
            .contains("topology.gateway_count")
    );
}
