use crate::main_parts::*;

pub(crate) fn generator_fields_execution() -> Vec<GeneratorField> {
    vec![
        bool_field("Profiling On", "profiling_enabled", false, "defaults.profiling.enabled"),
        text_field("Rust Profilers", "profiling_tools", "perf,flamegraph", "Comma-separated Rust-native profilers such as perf and flamegraph."),
        text_field("Profile Dur", "profiling_duration_seconds", "0", "defaults.profiling.duration_seconds"),
        bool_field("Profile Required", "profiling_required", false, "defaults.profiling.required"),
        bool_field("Retry Enabled", "retry_enabled", true, "defaults.execution.retry_enabled"),
        text_field("Max Attempts", "max_attempts", "2", "defaults.execution.max_attempts"),
        bool_field("Capture Logs", "capture_logs", true, "defaults.execution.capture_logs"),
        bool_field("Save Raw", "save_raw_results", true, "defaults.execution.save_raw_results"),
        bool_field("Reuse Stack", "reuse_stack", true, "defaults.execution.reuse_stack"),
        text_field("Defaults Plugins", "defaults_plugins_snippet", "", "Optional raw TOML lines with ' | ' separators for [defaults.plugins.<name>]."),
        text_field("Scenario Setup", "scenario_setup_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.setup]."),
        text_field("Scenario Build", "scenario_build_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.build]."),
        text_field("Scenario Runtime", "scenario_runtime_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.runtime]."),
        text_field("Scenario Gateway", "scenario_gateway_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.gateway]."),
        text_field("Scenario Load", "scenario_load_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.load]."),
        text_field("Scenario Measure", "scenario_measurement_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.measurement]."),
        text_field("Scenario Requests", "scenario_requests_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.requests]."),
        text_field("Scenario Profiling", "scenario_profiling_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.profiling], using Rust-native profiling settings."),
        text_field("Scenario Execution", "scenario_execution_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.execution]."),
        text_field("Scenario Plugins", "scenario_plugins_snippet", "", "Optional raw TOML lines with ' | ' separators for [scenario.plugins.<name>]."),
    ]
}
