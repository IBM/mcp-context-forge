pub(crate) fn text_field(
    label: &'static str,
    key: &'static str,
    value: &'static str,
    help: &'static str,
) -> GeneratorField {
    GeneratorField {
        label,
        key,
        kind: GeneratorFieldKind::Text,
        value: value.to_string(),
        help,
    }
}

pub(crate) fn bool_field(
    label: &'static str,
    key: &'static str,
    value: bool,
    help: &'static str,
) -> GeneratorField {
    GeneratorField {
        label,
        key,
        kind: GeneratorFieldKind::Bool,
        value: if value { "true" } else { "false" }.to_string(),
        help,
    }
}

pub(crate) fn choice_field(
    label: &'static str,
    key: &'static str,
    options: &'static [&'static str],
    value: &'static str,
    help: &'static str,
) -> GeneratorField {
    GeneratorField {
        label,
        key,
        kind: GeneratorFieldKind::Choice(options),
        value: value.to_string(),
        help,
    }
}

pub(crate) fn generator_fields_suite() -> Vec<GeneratorField> {
    vec![
        text_field(
            "File Stem",
            "file_stem",
            "new-scenario",
            "Output file name under crates/contextforge_benchmark_runner/assets/scenarios/.",
        ),
        choice_field(
            "Template Kind",
            "template_kind",
            &["blank", "mcp", "a2a"],
            "blank",
            "Choose a starter workload shape.",
        ),
        text_field(
            "Suite Name",
            "suite_name",
            "benchmark-generated-suite",
            "The [suite].name value.",
        ),
        text_field(
            "Suite Desc",
            "suite_description",
            "Generated benchmark scenario template",
            "The [suite].description value.",
        ),
        text_field(
            "Output Root",
            "output_root",
            "reports/benchmarks",
            "Benchmark output directory.",
        ),
        bool_field(
            "Continue Fail",
            "continue_on_failure",
            false,
            "suite.continue_on_failure",
        ),
        bool_field(
            "Save Artifacts",
            "save_intermediate_artifacts",
            true,
            "suite.save_intermediate_artifacts",
        ),
        bool_field(
            "Flamegraphs",
            "flamegraph_enabled",
            false,
            "suite.flamegraph_enabled",
        ),
        text_field(
            "Baseline Run",
            "baseline_run",
            "",
            "Optional prior run_summary.json path.",
        ),
        text_field(
            "Baseline RPS%",
            "baseline_rps_drop_pct",
            "",
            "Optional allowed RPS drop percentage.",
        ),
        text_field(
            "Baseline P95%",
            "baseline_p95_regression_pct",
            "",
            "Optional allowed p95 regression percentage.",
        ),
        text_field(
            "Baseline Fail+",
            "baseline_failure_increase",
            "",
            "Optional allowed failure increase.",
        ),
        text_field(
            "Scenario Name",
            "scenario_name",
            "generated-scenario",
            "Name for the first [[scenario]] entry.",
        ),
        text_field(
            "Scenario Desc",
            "scenario_description",
            "Generated benchmark scenario",
            "Description for the first [[scenario]] entry.",
        ),
        text_field(
            "Scenario Type",
            "scenario_type",
            "custom",
            "Freeform scenario_type label.",
        ),
        choice_field(
            "Target Kind",
            "target_kind",
            &["gateway", "agent"],
            "gateway",
            "defaults.setup.target_kind",
        ),
        choice_field(
            "Auth Mode",
            "auth_mode",
            &["jwt", "basic", "none"],
            "jwt",
            "defaults.setup.auth_mode",
        ),
        bool_field(
            "Plugins",
            "plugins_enabled",
            false,
            "defaults.setup.plugins_enabled",
        ),
        text_field(
            "Expect MCP",
            "expected_mcp_runtime",
            "",
            "Optional defaults.setup.expected_mcp_runtime",
        ),
        text_field(
            "Expect MCP Mode",
            "expected_mcp_runtime_mode",
            "",
            "Optional defaults.setup.expected_mcp_runtime_mode",
        ),
        text_field(
            "Expect A2A",
            "expected_a2a_runtime",
            "",
            "Optional defaults.setup.expected_a2a_runtime",
        ),
        bool_field(
            "Rust Plugins",
            "rust_plugins",
            false,
            "defaults.build.rust_plugins",
        ),
        bool_field(
            "Profiling Img",
            "profiling_image",
            false,
            "defaults.build.profiling_image",
        ),
        text_field(
            "Container File",
            "container_file",
            "crates/contextforge_benchmark_runner/assets/Containerfile",
            "defaults.build.container_file",
        ),
        text_field(
            "Image Name",
            "image_name",
            "mcpgateway/mcpgateway",
            "defaults.build.image_name",
        ),
        text_field(
            "Image Tag",
            "image_tag",
            "benchmark-suite-generated",
            "defaults.build.image_tag",
        ),
        choice_field(
            "Rebuild",
            "rebuild_policy",
            &["never", "missing", "always"],
            "missing",
            "defaults.build.rebuild_policy",
        ),
        text_field(
            "Build Args",
            "build_args",
            "",
            "Optional build args. Use 'KEY = \"value\" | OTHER = \"x\"'.",
        ),
    ]
}
use crate::main_parts::*;
