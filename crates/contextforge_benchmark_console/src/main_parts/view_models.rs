pub(crate) fn discover_scenarios(root: &Path) -> AppResult<Vec<SuiteSummary>> {
    let mut scenarios =
        fs::read_dir(root.join("crates/contextforge_benchmark_runner/assets/scenarios"))?
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
        .join("crates/contextforge_benchmark_runner/assets/scenarios")
        .join(format!("{}.toml", selected.label()));
    if !path.exists() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path)?;
    Ok(Some(toml::from_str::<TomlValue>(&raw)?))
}

pub(crate) fn build_preview_sections(app: &App, root: &Path) -> AppResult<PreviewSections> {
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

pub(crate) fn build_selection_summary(app: &App) -> SelectionSummary {
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

pub(crate) fn build_suite_inspector_summary(app: &App, root: &Path) -> AppResult<SuiteInspectorSummary> {
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

pub(crate) fn build_generator_focus_summary(app: &App) -> GeneratorFocusSummary {
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
use crate::*;
use crate::main_parts::*;
