pub(crate) fn escape_toml(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

pub(crate) fn format_command(command: &str, args: &[String]) -> String {
    std::iter::once(command.to_string())
        .chain(args.iter().cloned())
        .collect::<Vec<_>>()
        .join(" ")
}

pub(crate) fn start_command_capture(
    app: &mut App,
    command_spec: CommandSpec,
    root: &Path,
) -> AppResult<()> {
    let command_label = format_command(&command_spec.command, &command_spec.args);
    let mut child = Command::new(&command_spec.command)
        .args(&command_spec.args)
        .envs(command_spec.env.clone())
        .current_dir(root)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let stdout = child
        .stdout
        .take()
        .ok_or("Could not capture child stdout")?;
    let stderr = child
        .stderr
        .take()
        .ok_or("Could not capture child stderr")?;
    let (sender, receiver) = mpsc::channel::<LogLine>();
    spawn_log_reader(stdout, LogSource::Stdout, sender.clone());
    spawn_log_reader(stderr, LogSource::Stderr, sender);
    app.run_scenarios.clear();
    app.current_run_scenario = None;
    app.last_run_dir = None;
    app.last_run_outcome = None;
    app.log_lines.clear();
    app.dropped_log_lines = 0;
    app.log_scroll = 0;
    app.last_command_label = Some(command_label.clone());
    app.push_log_line(
        LogSource::System,
        format!("Started command inside console: {command_label}"),
    );
    app.running_command = Some(RunningCommand {
        child,
        receiver,
        command_label,
    });
    app.active_view = AppView::RunMonitor;
    Ok(())
}

fn spawn_log_reader<R>(reader: R, source: LogSource, sender: mpsc::Sender<LogLine>)
where
    R: std::io::Read + Send + 'static,
{
    thread::spawn(move || {
        let reader = BufReader::new(reader);
        for line in reader.lines() {
            match line {
                Ok(text) => {
                    let _ = sender.send(LogLine { source, text });
                }
                Err(error) => {
                    let _ = sender.send(LogLine {
                        source: LogSource::System,
                        text: format!("Log capture error: {error}"),
                    });
                    break;
                }
            }
        }
    });
}

pub(crate) fn drain_running_command(app: &mut App) -> AppResult<()> {
    let Some(mut running) = app.running_command.take() else {
        return Ok(());
    };

    while let Ok(line) = running.receiver.try_recv() {
        app.push_log_line(line.source, line.text);
    }

    match running.child.try_wait()? {
        Some(status) => {
            while let Ok(line) = running.receiver.try_recv() {
                app.push_log_line(line.source, line.text);
            }
            let outcome = if status.success() {
                "finished"
            } else {
                "failed"
            };
            app.push_log_line(
                LogSource::System,
                format!(
                    "Command {outcome} with status {status}: {}",
                    running.command_label
                ),
            );
        }
        None => {
            app.running_command = Some(running);
        }
    }

    Ok(())
}

pub(crate) fn parse_scenario_start(text: &str) -> Option<String> {
    text.split("starting: ")
        .nth(1)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
}

pub(crate) fn parse_scenario_completion(text: &str) -> Option<(String, String)> {
    let prefix = "Scenario '";
    let rest = text.strip_prefix("[benchmark] ").unwrap_or(text);
    let rest = rest.strip_prefix(prefix)?;
    if let Some((name, suffix)) = rest.split_once("' completed with status ") {
        return Some((name.to_string(), suffix.trim().to_string()));
    }
    if let Some((name, _)) = rest.split_once("' failed:") {
        return Some((name.to_string(), "failed".to_string()));
    }
    None
}

pub(crate) fn parse_run_dir(text: &str) -> Option<String> {
    if text.contains("reports/benchmarks/") {
        return text
            .split_whitespace()
            .find(|part| part.contains("reports/benchmarks/"))
            .map(|value| value.trim().to_string());
    }
    None
}

pub(crate) fn parse_run_outcome(text: &str) -> Option<String> {
    let rest = text.strip_prefix("[benchmark] ").unwrap_or(text);
    if rest.starts_with("Benchmark run completed successfully") {
        return Some("ok".to_string());
    }
    if rest.starts_with("Benchmark run completed with failed scenarios") {
        return Some("failed".to_string());
    }
    None
}

pub(crate) fn yes_no(value: bool) -> &'static str {
    if value { "yes" } else { "no" }
}
use crate::main_parts::*;
use crate::*;
