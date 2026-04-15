pub(crate) struct App {
    pub(crate) active_view: AppView,
    pub(crate) action_index: usize,
    pub(crate) last_standard_action_index: usize,
    pub(crate) scenario_index: usize,
    pub(crate) scenarios: Vec<SuiteSummary>,
    pub(crate) run_path: String,
    pub(crate) extra_args: String,
    pub(crate) all: bool,
    pub(crate) clean: bool,
    pub(crate) mode: InputMode,
    pub(crate) status: String,
    pub(crate) should_quit: bool,
    pub(crate) generator: GeneratorState,
    pub(crate) log_lines: Vec<LogLine>,
    pub(crate) dropped_log_lines: usize,
    pub(crate) log_scroll: usize,
    pub(crate) running_command: Option<RunningCommand>,
    pub(crate) current_run_scenario: Option<String>,
    pub(crate) run_scenarios: Vec<RunScenarioSummary>,
    pub(crate) last_command_label: Option<String>,
    pub(crate) last_run_dir: Option<String>,
    pub(crate) last_run_outcome: Option<String>,
}

impl App {
    pub(crate) fn new(scenarios: Vec<SuiteSummary>) -> Self {
        Self {
            active_view: AppView::Launcher,
            action_index: 0,
            last_standard_action_index: 0,
            scenario_index: 0,
            scenarios,
            run_path: String::new(),
            extra_args: String::new(),
            all: false,
            clean: true,
            mode: InputMode::Normal,
            status: "Use 1-8 or left/right for action, Enter to run, g=save template when Generate is selected.".to_string(),
            should_quit: false,
            generator: GeneratorState::new(),
            log_lines: Vec::new(),
            dropped_log_lines: 0,
            log_scroll: 0,
            running_command: None,
            current_run_scenario: None,
            run_scenarios: Vec::new(),
            last_command_label: None,
            last_run_dir: None,
            last_run_outcome: None,
        }
    }

    pub(crate) fn action(&self) -> Action {
        Action::ALL[self.action_index]
    }

    pub(crate) fn scenario(&self) -> &str {
        self.scenarios
            .get(self.scenario_index)
            .map(SuiteSummary::label)
            .unwrap_or("rust-mcp-runtime-300")
    }

    pub(crate) fn selected_suite(&self) -> Option<&SuiteSummary> {
        self.scenarios.get(self.scenario_index)
    }

    pub(crate) fn set_action_index(&mut self, index: usize) {
        self.action_index = index % Action::ALL.len();
        if self.action() != Action::Generate {
            self.last_standard_action_index = self.action_index;
        }
        if !self.action().supports_all() {
            self.all = false;
        }
        if !self.action().supports_clean() {
            self.clean = false;
        }
        if self.action() == Action::Generate {
            self.active_view = AppView::Generator;
        } else if self.active_view == AppView::Generator {
            self.active_view = AppView::Launcher;
        }
        self.status = self.action().help().to_string();
    }

    pub(crate) fn move_action(&mut self, delta: isize) {
        let len = Action::ALL.len() as isize;
        let next = (self.action_index as isize + delta).rem_euclid(len) as usize;
        self.set_action_index(next);
    }

    pub(crate) fn move_scenario(&mut self, delta: isize) {
        if self.scenarios.is_empty() {
            return;
        }
        let len = self.scenarios.len() as isize;
        self.scenario_index = (self.scenario_index as isize + delta).rem_euclid(len) as usize;
        self.status = format!("Selected scenario: {}", self.scenario());
    }

    pub(crate) fn set_view(&mut self, view: AppView) {
        self.active_view = view;
        match view {
            AppView::Generator => {
                if self.action() != Action::Generate {
                    self.last_standard_action_index = self.action_index;
                    self.action_index = Action::ALL
                        .iter()
                        .position(|action| *action == Action::Generate)
                        .unwrap_or(self.action_index);
                }
            }
            _ => {
                if self.action() == Action::Generate {
                    self.action_index = self.last_standard_action_index;
                }
            }
        }
        self.status = match self.active_view {
            AppView::Launcher => "Launcher view: choose a suite and action.".to_string(),
            AppView::SuiteInspector => {
                "Suite Inspector: compare scenario cards for the selected suite.".to_string()
            }
            AppView::RunMonitor => {
                "Run Monitor: follow live logs and per-scenario progress.".to_string()
            }
            AppView::Generator => "Generator: edit and save a benchmark template.".to_string(),
        };
    }

    pub(crate) fn cycle_view(&mut self, delta: isize) {
        let views = if self.running_command.is_some() {
            vec![
                AppView::Launcher,
                AppView::SuiteInspector,
                AppView::RunMonitor,
                AppView::Generator,
            ]
        } else {
            vec![
                AppView::Launcher,
                AppView::SuiteInspector,
                AppView::RunMonitor,
                AppView::Generator,
            ]
        };
        let current = views
            .iter()
            .position(|view| *view == self.active_view)
            .unwrap_or(0) as isize;
        let next = (current + delta).rem_euclid(views.len() as isize) as usize;
        self.set_view(views[next]);
    }

    pub(crate) fn push_log_line(&mut self, source: LogSource, text: String) {
        if text.trim().is_empty() {
            return;
        }
        self.apply_progress_line(&text);
        self.status = text.clone();
        self.log_lines.push(LogLine { source, text });
        self.log_scroll = 0;
        if self.log_lines.len() > MAX_LOG_LINES {
            let drop_count = self.log_lines.len() - MAX_LOG_LINES;
            self.log_lines.drain(0..drop_count);
            self.dropped_log_lines += drop_count;
        }
    }

    pub(crate) fn apply_progress_line(&mut self, text: &str) {
        if let Some(name) = parse_scenario_start(text) {
            self.current_run_scenario = Some(name.clone());
            self.upsert_run_scenario(&name, "running");
        }
        if let Some((name, status)) = parse_scenario_completion(text) {
            self.current_run_scenario = None;
            self.upsert_run_scenario(&name, &status);
        }
        if let Some(run_dir) = parse_run_dir(text) {
            self.last_run_dir = Some(run_dir);
        }
        if let Some(outcome) = parse_run_outcome(text) {
            self.last_run_outcome = Some(outcome);
        }
    }

    pub(crate) fn upsert_run_scenario(&mut self, name: &str, status: &str) {
        if let Some(item) = self.run_scenarios.iter_mut().find(|item| item.name == name) {
            item.status = status.to_string();
            return;
        }
        self.run_scenarios.push(RunScenarioSummary {
            name: name.to_string(),
            status: status.to_string(),
        });
    }
}
use crate::*;
use crate::main_parts::*;
