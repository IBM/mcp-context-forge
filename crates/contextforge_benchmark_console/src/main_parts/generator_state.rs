#[derive(Clone, Copy)]
pub(crate) enum GeneratorFieldKind {
    Text,
    Bool,
    Choice(&'static [&'static str]),
}

pub(crate) struct GeneratorField {
    pub(crate) label: &'static str,
    pub(crate) key: &'static str,
    pub(crate) kind: GeneratorFieldKind,
    pub(crate) value: String,
    pub(crate) help: &'static str,
}

pub(crate) struct GeneratorState {
    pub(crate) fields: Vec<GeneratorField>,
    pub(crate) selected: usize,
    pub(crate) selected_section: usize,
}

impl GeneratorState {
    pub(crate) fn new() -> Self {
        let mut fields = Vec::new();
        fields.extend(generator_fields_suite());
        fields.extend(generator_fields_runtime());
        fields.extend(generator_fields_workload());
        fields.extend(generator_fields_execution());
        Self {
            fields,
            selected: 0,
            selected_section: 0,
        }
    }

    pub(crate) fn sections() -> &'static [&'static str] {
        &[
            "All",
            "Generator",
            "Suite",
            "Scenario",
            "Setup",
            "Build",
            "Runtime",
            "Gateway",
            "Load",
            "Measurement",
            "Requests",
            "Profiling",
            "Execution",
            "Plugins",
        ]
    }

    pub(crate) fn selected_section_name(&self) -> &'static str {
        Self::sections()[self.selected_section]
    }

    pub(crate) fn visible_indices(&self) -> Vec<usize> {
        self.fields
            .iter()
            .enumerate()
            .filter_map(|(index, field)| {
                let in_section = self.selected_section_name() == "All"
                    || generator_section(field.key) == self.selected_section_name();
                (in_section && self.is_visible(field.key)).then_some(index)
            })
            .collect()
    }

    pub(crate) fn ensure_visible_selection(&mut self) {
        let visible = self.visible_indices();
        if visible.is_empty() {
            self.selected = 0;
            return;
        }
        if visible.contains(&self.selected) {
            return;
        }
        self.selected = *visible
            .iter()
            .find(|index| **index > self.selected)
            .unwrap_or(&visible[0]);
    }

    pub(crate) fn selected_field(&self) -> &GeneratorField {
        &self.fields[self.selected]
    }

    pub(crate) fn selected_field_mut(&mut self) -> &mut GeneratorField {
        &mut self.fields[self.selected]
    }

    pub(crate) fn move_selected(&mut self, delta: isize) {
        let visible = self.visible_indices();
        if visible.is_empty() {
            return;
        }
        let current_pos = visible
            .iter()
            .position(|index| *index == self.selected)
            .unwrap_or(0) as isize;
        let len = visible.len() as isize;
        let next_pos = (current_pos + delta).rem_euclid(len) as usize;
        self.selected = visible[next_pos];
    }

    pub(crate) fn move_section(&mut self, delta: isize) {
        let len = Self::sections().len() as isize;
        self.selected_section = (self.selected_section as isize + delta).rem_euclid(len) as usize;
        self.ensure_visible_selection();
    }

    pub(crate) fn get(&self, key: &str) -> &str {
        self.fields
            .iter()
            .find(|field| field.key == key)
            .map(|field| field.value.as_str())
            .unwrap_or("")
    }

    pub(crate) fn toggle_or_cycle(&mut self) {
        let field = self.selected_field_mut();
        match field.kind {
            GeneratorFieldKind::Bool => {
                field.value = if field.value == "true" {
                    "false"
                } else {
                    "true"
                }
                .to_string();
            }
            GeneratorFieldKind::Choice(options) => {
                let current = options
                    .iter()
                    .position(|value| *value == field.value)
                    .unwrap_or(0);
                field.value = options[(current + 1) % options.len()].to_string();
            }
            GeneratorFieldKind::Text => {}
        }
        self.ensure_visible_selection();
    }

    pub(crate) fn is_visible(&self, key: &str) -> bool {
        let http_server = self.get("http_server");
        let profiling_enabled = self.get("profiling_enabled") == "true";
        let plugins_enabled = self.get("plugins_enabled") == "true";
        let workload_selection_present = !self.get("workload_selection").trim().is_empty()
            || self.get("template_kind") != "blank";

        match key {
            "expected_mcp_runtime_mode" => !self.get("expected_mcp_runtime").trim().is_empty(),
            "gunicorn_workers"
            | "gunicorn_timeout"
            | "gunicorn_graceful_timeout"
            | "gunicorn_keep_alive"
            | "gunicorn_max_requests"
            | "gunicorn_max_requests_jitter"
            | "gunicorn_backlog"
            | "gunicorn_preload_app"
            | "gunicorn_dev_mode" => http_server == "gunicorn",
            "granian_workers"
            | "granian_runtime_mode"
            | "granian_runtime_threads"
            | "granian_blocking_threads"
            | "granian_http"
            | "granian_loop"
            | "granian_task_impl"
            | "granian_http1_pipeline_flush"
            | "granian_http1_buffer_size"
            | "granian_backlog"
            | "granian_backpressure"
            | "granian_respawn_failed"
            | "granian_workers_lifetime"
            | "granian_workers_max_rss"
            | "granian_dev_mode"
            | "granian_log_level" => http_server == "granian",
            "uvicorn_workers"
            | "uvicorn_loop"
            | "uvicorn_http"
            | "uvicorn_backlog"
            | "uvicorn_timeout_keep_alive"
            | "uvicorn_limit_max_requests"
            | "uvicorn_log_level"
            | "uvicorn_dev_mode" => http_server == "uvicorn",
            "profiling_tools" | "profiling_duration_seconds" | "profiling_required" => {
                profiling_enabled
            }
            "defaults_plugins_snippet" | "scenario_plugins_snippet" => plugins_enabled,
            "workload_selection" | "fallback_endpoint" => true,
            "workload_endpoints" => workload_selection_present,
            _ => true,
        }
    }
}
use crate::*;
use crate::main_parts::*;
