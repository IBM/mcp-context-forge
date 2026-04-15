pub(crate) mod app_state;
pub(crate) mod generator_copy;
pub(crate) mod generator_examples;
pub(crate) mod generator_fields_execution;
pub(crate) mod generator_fields_runtime;
pub(crate) mod generator_fields_suite;
pub(crate) mod generator_fields_workload;
pub(crate) mod generator_metadata;
pub(crate) mod generator_state;
pub(crate) mod interaction;
pub(crate) mod run_actions;
pub(crate) mod run_cleanup;
pub(crate) mod runtime_helpers;
pub(crate) mod template_endpoints;
pub(crate) mod template_helpers;
pub(crate) mod template_writer;
pub(crate) mod ui_layout;
pub(crate) mod ui_panels;
pub(crate) mod view_models;

pub(crate) use app_state::App;
pub(crate) use generator_copy::{generator_change_reason, generator_explanation};
pub(crate) use generator_examples::{generator_example, generator_visibility_note};
pub(crate) use generator_fields_execution::generator_fields_execution;
pub(crate) use generator_fields_runtime::generator_fields_runtime;
pub(crate) use generator_fields_suite::{
    bool_field, choice_field, generator_fields_suite, text_field,
};
pub(crate) use generator_fields_workload::generator_fields_workload;
pub(crate) use generator_metadata::{
    generator_config_path, generator_format_hint, generator_section,
};
pub(crate) use generator_state::{GeneratorField, GeneratorFieldKind, GeneratorState};
pub(crate) use interaction::{handle_normal_mode, restore_terminal, run_app, setup_terminal};
pub(crate) use run_actions::{CommandSpec, build_command, launch_action};
pub(crate) use run_cleanup::run_cleanup;
pub(crate) use runtime_helpers::{
    drain_running_command, escape_toml, format_command, parse_run_dir, parse_run_outcome,
    parse_scenario_completion, parse_scenario_start, start_command_capture, yes_no,
};
pub(crate) use template_endpoints::template_endpoints;
pub(crate) use template_helpers::{
    append_optional_block, append_runtime_block_from_fields, parse_pipe_lines, push_bool_line,
    push_optional_array_line, push_optional_scalar_line, push_optional_string_line,
    push_scalar_line, push_string_line, quoted_csv, save_generated_template,
};
pub(crate) use template_writer::generate_template_toml;
pub(crate) use ui_layout::draw;
pub(crate) use ui_panels::{
    draw_generator_fields, draw_generator_reference, draw_generator_selection, draw_help,
    draw_live_logs, draw_preview, line_pair,
};
pub(crate) use view_models::{
    build_generator_focus_summary, build_preview_sections, build_selection_summary,
    build_suite_inspector_summary, discover_scenarios,
};
