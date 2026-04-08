pub(crate) fn launch_action(
    app: &mut App,
    root: &Path,
    _terminal: &mut Terminal<CrosstermBackend<Stdout>>,
) -> AppResult<()> {
    let command_spec = build_command(app, root)?;
    if app.running_command.is_some() {
        app.status = "A benchmark command is already running.".to_string();
        return Ok(());
    }
    if app.clean && app.action().supports_clean() {
        app.push_log_line(
            LogSource::System,
            "Cleanup: removing prior benchmark containers and staging artifacts.".to_string(),
        );
        let cleanup_status = run_cleanup()?;
        app.push_log_line(
            LogSource::System,
            format!("Cleanup finished with status: {cleanup_status}"),
        );
    }
    start_command_capture(app, command_spec, root)?;
    Ok(())
}

pub(crate) struct CommandSpec {
    pub(crate) command: String,
    pub(crate) args: Vec<String>,
    pub(crate) env: Vec<(String, String)>,
}

pub(crate) fn build_command(app: &App, _root: &Path) -> AppResult<CommandSpec> {
    let action = app.action();
    let mut args = vec![
        "cargo".to_string(),
        "run".to_string(),
        "--manifest-path".to_string(),
        "tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml".to_string(),
        "--quiet".to_string(),
        "--".to_string(),
    ];

    match action {
        Action::List => args.push("list".to_string()),
        Action::Run | Action::Validate | Action::Smoke | Action::CheckRuntime => {
            args.push(
                match action {
                    Action::Run | Action::Smoke => {
                        if app.all && action.supports_all() {
                            "run-all"
                        } else {
                            "run"
                        }
                    }
                    Action::Validate => "validate",
                    Action::CheckRuntime => "check-runtime",
                    _ => unreachable!(),
                }
                .to_string(),
            );
            if !app.all || !action.supports_all() || !matches!(action, Action::Run | Action::Smoke)
            {
                args.push("--scenario".to_string());
                args.push(app.scenario().to_string());
            }
            match action {
                Action::Smoke | Action::Validate | Action::CheckRuntime
                    if app.all && matches!(action, Action::Validate | Action::CheckRuntime) =>
                {
                    args.push("--scenario".to_string());
                    args.push(app.scenario().to_string());
                    if matches!(action, Action::Smoke) {
                        args.push("--smoke".to_string());
                    }
                }
                Action::Smoke => args.push("--smoke".to_string()),
                _ => {}
            }
        }
        Action::Report => {
            if app.run_path.trim().is_empty() {
                return Err("Report needs a run path. Press 'p' to edit it.".into());
            }
            args.push("regenerate-report".to_string());
            args.push("--run-dir".to_string());
            args.push(app.run_path.trim().to_string());
        }
        Action::Compare => {
            if app.run_path.trim().is_empty() {
                return Err("Compare needs a run path. Press 'p' to edit it.".into());
            }
            args.push("compare-run".to_string());
            args.push("--run-dir".to_string());
            args.push(app.run_path.trim().to_string());
        }
        Action::Generate => {
            return Err("Generate uses 'g' to save a scenario file, not Enter to run.".into());
        }
    }

    if !app.extra_args.trim().is_empty() {
        args.extend(shlex::split(&app.extra_args).ok_or("Could not parse extra args.")?);
    }

    Ok(CommandSpec {
        command: args.remove(0),
        args,
        env: vec![(
            "CONTAINER_RUNTIME".to_string(),
            env::var("CONTAINER_RUNTIME").unwrap_or_else(|_| "podman".to_string()),
        )],
    })
}
use crate::*;
use crate::main_parts::*;
