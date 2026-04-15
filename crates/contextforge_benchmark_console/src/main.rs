use std::env;
use std::fs;
use std::io::{self, BufRead, BufReader, Stdout};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::thread;
use std::time::Duration;

use crossterm::cursor::{Hide, Show};
use crossterm::event::{self, Event, KeyCode, KeyEvent};
use crossterm::execute;
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
};
use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Tabs, Wrap};
use toml::Value as TomlValue;

type AppResult<T> = Result<T, Box<dyn std::error::Error>>;
const MAX_LOG_LINES: usize = 500;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LogSource {
    Stdout,
    Stderr,
    System,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct LogLine {
    source: LogSource,
    text: String,
}

#[derive(Debug)]
struct RunningCommand {
    child: Child,
    receiver: Receiver<LogLine>,
    command_label: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct SuiteSummary {
    file_stem: String,
    suite_name: String,
    description: String,
}

impl SuiteSummary {
    fn label(&self) -> &str {
        &self.file_stem
    }

    fn suite_name(&self) -> &str {
        if self.suite_name.is_empty() {
            &self.file_stem
        } else {
            &self.suite_name
        }
    }

    fn description(&self) -> &str {
        if self.description.is_empty() {
            "No suite description is defined in this scenario TOML yet."
        } else {
            &self.description
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct PreviewSections {
    run_plan: Vec<String>,
    execution: Vec<String>,
    checks: Vec<String>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct SelectionSummary {
    action_label: String,
    suite_label: String,
    clean_label: String,
    run_mode_label: String,
    run_path_label: String,
    extra_args_label: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AppView {
    Launcher,
    SuiteInspector,
    RunMonitor,
    Generator,
}

impl AppView {
    const ALL: [AppView; 4] = [
        AppView::Launcher,
        AppView::SuiteInspector,
        AppView::RunMonitor,
        AppView::Generator,
    ];

    fn label(self) -> &'static str {
        match self {
            AppView::Launcher => "Launcher",
            AppView::SuiteInspector => "Inspector",
            AppView::RunMonitor => "Run Monitor",
            AppView::Generator => "Generator",
        }
    }

    fn supports_suite_navigation(self) -> bool {
        matches!(self, AppView::Launcher | AppView::SuiteInspector)
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct ScenarioCardSummary {
    name: String,
    description: String,
    scenario_type: String,
    settings: Vec<(String, String)>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct SuiteInspectorSummary {
    suite_name: String,
    suite_description: String,
    scenario_count_label: String,
    comparison_question: String,
    scenario_cards: Vec<ScenarioCardSummary>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct RunScenarioSummary {
    name: String,
    status: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct GeneratorFocusSummary {
    section_filter: String,
    field_label: String,
    config_key: String,
    value: String,
    kind: String,
    schema: String,
    format_hint: String,
    visibility: String,
    purpose: String,
    effect: String,
    example: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Action {
    Run,
    Validate,
    Smoke,
    CheckRuntime,
    List,
    Report,
    Compare,
    Generate,
}

impl Action {
    const ALL: [Action; 8] = [
        Action::Run,
        Action::Validate,
        Action::Smoke,
        Action::CheckRuntime,
        Action::List,
        Action::Report,
        Action::Compare,
        Action::Generate,
    ];

    fn label(self) -> &'static str {
        match self {
            Action::Run => "Run",
            Action::Validate => "Validate",
            Action::Smoke => "Smoke",
            Action::CheckRuntime => "Check",
            Action::List => "List",
            Action::Report => "Report",
            Action::Compare => "Compare",
            Action::Generate => "Generate",
        }
    }

    fn help(self) -> &'static str {
        match self {
            Action::Run => "Execute the selected scenario end to end.",
            Action::Validate => "Resolve configs and generate reports without load.",
            Action::Smoke => "Run the selected scenario in smoke mode.",
            Action::CheckRuntime => "Check container runtime prerequisites only.",
            Action::List => "List committed scenarios and exit.",
            Action::Report => "Re-render a saved run summary.",
            Action::Compare => "Re-render comparison output for a saved run.",
            Action::Generate => {
                "Generate a fully Rust-native TOML scenario template with all supported sections."
            }
        }
    }

    fn supports_scenario(self) -> bool {
        !matches!(
            self,
            Action::List | Action::Report | Action::Compare | Action::Generate
        )
    }

    fn supports_all(self) -> bool {
        matches!(
            self,
            Action::Run | Action::Validate | Action::Smoke | Action::CheckRuntime
        )
    }

    fn supports_clean(self) -> bool {
        matches!(self, Action::Run | Action::Smoke)
    }

    fn needs_run_path(self) -> bool {
        matches!(self, Action::Report | Action::Compare)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum InputMode {
    Normal,
    EditRunPath,
    EditExtraArgs,
    EditGeneratorField,
}

impl InputMode {
    fn label(self) -> &'static str {
        match self {
            InputMode::Normal => "Normal",
            InputMode::EditRunPath => "Editing Run Path",
            InputMode::EditExtraArgs => "Editing Extra Args",
            InputMode::EditGeneratorField => "Editing Generator Field",
        }
    }
}

mod main_parts;

use main_parts::{App, discover_scenarios, restore_terminal, run_app, setup_terminal};

fn main() -> AppResult<()> {
    let root = env::current_dir()?;
    let scenarios = discover_scenarios(&root)?;

    if env::args().nth(1).as_deref() == Some("--list-scenarios") {
        for scenario in scenarios {
            println!("{}", scenario.label());
        }
        return Ok(());
    }

    let mut terminal = setup_terminal()?;
    let result = run_app(&mut terminal, App::new(scenarios), &root);
    restore_terminal(&mut terminal)?;
    result
}

#[cfg(test)]
#[path = "main_parts/tests.rs"]
mod tests;
