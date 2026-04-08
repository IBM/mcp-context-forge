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
use super::*;
use crate::main_parts::*;
