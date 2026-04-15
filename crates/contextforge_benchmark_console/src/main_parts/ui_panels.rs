pub(crate) fn draw_preview(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let preview = build_preview_sections(app, Path::new(".")).unwrap_or_else(|error| {
        let mut fallback = PreviewSections::default();
        fallback.execution.push(format!(
            "Command error: failed to build preview sections: {error}"
        ));
        fallback
    });
    let mut lines = vec![Line::from(Span::styled(
        app.action().help(),
        Style::default().fg(Color::Cyan),
    ))];
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Run Plan",
        Style::default().add_modifier(Modifier::BOLD),
    )));
    lines.extend(preview.run_plan.iter().map(|line| Line::from(line.clone())));
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Execution",
        Style::default().add_modifier(Modifier::BOLD),
    )));
    lines.extend(preview.execution.iter().map(|line| {
        if line.starts_with("Command error:") {
            Line::from(Span::styled(line.clone(), Style::default().fg(Color::Red)))
        } else {
            Line::from(line.clone())
        }
    }));
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        "Checks",
        Style::default().add_modifier(Modifier::BOLD),
    )));
    lines.extend(preview.checks.iter().map(|line| Line::from(line.clone())));
    lines.push(Line::from(""));
    lines.push(Line::from(Span::styled(
        format!("Status: {}", app.status),
        Style::default().fg(Color::Magenta),
    )));
    let widget = Paragraph::new(lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Execution Dashboard"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

pub(crate) fn draw_live_logs(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let visible_height = area.height.saturating_sub(2) as usize;
    let total = app.log_lines.len();
    let end = total.saturating_sub(app.log_scroll);
    let start = end.saturating_sub(visible_height);
    let lines = app.log_lines[start..end]
        .iter()
        .map(|line| {
            let prefix = match line.source {
                LogSource::Stdout => ("OUT", Color::Green),
                LogSource::Stderr => ("ERR", Color::Red),
                LogSource::System => ("SYS", Color::Cyan),
            };
            Line::from(vec![
                Span::styled(
                    format!("[{}] ", prefix.0),
                    Style::default().fg(prefix.1).add_modifier(Modifier::BOLD),
                ),
                Span::raw(line.text.clone()),
            ])
        })
        .collect::<Vec<_>>();
    let empty = vec![Line::from(Span::styled(
        "Run a benchmark action to see live logs here.",
        Style::default().fg(Color::DarkGray),
    ))];
    let widget = Paragraph::new(if lines.is_empty() { empty } else { lines })
        .block(
            Block::default().borders(Borders::ALL).title(format!(
                "Live Logs ({}/{}, scroll {}, dropped {})",
                end.saturating_sub(start),
                total,
                app.log_scroll,
                app.dropped_log_lines
            )),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

pub(crate) fn draw_generator_fields(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let visible = app.generator.visible_indices();
    let items = visible
        .iter()
        .map(|index| {
            let field = &app.generator.fields[*index];
            ListItem::new(vec![
                Line::from(vec![
                    Span::styled(
                        format!("{}{}", generator_indent(field.key), field.label),
                        Style::default().add_modifier(Modifier::BOLD),
                    ),
                    Span::raw("  "),
                    Span::styled(
                        generator_section(field.key),
                        Style::default().fg(Color::Blue),
                    ),
                ]),
                Line::from(Span::styled(
                    field.value.clone(),
                    Style::default().fg(Color::Green),
                )),
            ])
        })
        .collect::<Vec<_>>();
    let visible_pos = visible
        .iter()
        .position(|index| *index == app.generator.selected)
        .unwrap_or(0);
    let list = List::new(items)
        .block(Block::default().borders(Borders::ALL).title(format!(
            "{} Fields ({}/{} visible, {} total)",
            app.generator.selected_section_name(),
            visible_pos + 1,
            visible.len(),
            app.generator.fields.len()
        )))
        .highlight_style(
            Style::default()
                .fg(Color::Black)
                .bg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )
        .highlight_symbol(">> ")
        .highlight_spacing(ratatui::widgets::HighlightSpacing::Always);
    let mut state = ListState::default();
    state.select(Some(visible_pos));
    frame.render_stateful_widget(list, area, &mut state);
}

pub(crate) fn draw_generator_selection(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_generator_focus_summary(app);
    let lines = vec![
        line_pair("Section Filter", &summary.section_filter),
        line_pair("Field", &summary.field_label),
        line_pair("Config Key", &summary.config_key),
        line_pair("Value", &summary.value),
        line_pair("Kind", &summary.kind),
        line_pair("Schema", &summary.schema),
        line_pair("Format", &summary.format_hint),
        line_pair("Visibility", &summary.visibility),
        line_pair("Edit", "Enter/e edits, t toggles bool or choice"),
        line_pair("Save", "g or s writes the scenario file"),
    ];
    let widget = Paragraph::new(lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Current Field"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

pub(crate) fn draw_generator_reference(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_generator_focus_summary(app);
    let detail = format!(
        "What it is for:\n{}\n\nWhat it does:\n{}\n\nAccepted values:\n{}\n\nVisibility:\n{}\n\nExample:\n{}",
        summary.purpose, summary.effect, summary.format_hint, summary.visibility, summary.example
    );
    let widget = Paragraph::new(detail)
        .block(Block::default().borders(Borders::ALL).title("Field Guide"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn generator_indent(key: &str) -> &'static str {
    match key {
        "gunicorn_workers"
        | "gunicorn_timeout"
        | "gunicorn_graceful_timeout"
        | "gunicorn_keep_alive"
        | "gunicorn_max_requests"
        | "gunicorn_max_requests_jitter"
        | "gunicorn_backlog"
        | "gunicorn_preload_app"
        | "gunicorn_dev_mode"
        | "granian_workers"
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
        | "granian_log_level"
        | "uvicorn_workers"
        | "uvicorn_loop"
        | "uvicorn_http"
        | "uvicorn_backlog"
        | "uvicorn_timeout_keep_alive"
        | "uvicorn_limit_max_requests"
        | "uvicorn_log_level"
        | "uvicorn_dev_mode"
        | "profiling_tools"
        | "profiling_duration_seconds"
        | "profiling_required" => "  ",
        _ => "",
    }
}

pub(crate) fn line_pair<'a>(label: &'a str, value: &'a str) -> Line<'a> {
    Line::from(vec![
        Span::styled(format!("{label}: "), Style::default().fg(Color::White)),
        Span::styled(value.to_string(), Style::default().fg(Color::Green)),
    ])
}

pub(crate) fn draw_help(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let help = match app.mode {
        InputMode::EditRunPath | InputMode::EditExtraArgs | InputMode::EditGeneratorField => {
            "Type text, Backspace deletes, Enter saves, Esc cancels"
        }
        InputMode::Normal if app.active_view == AppView::Generator => {
            "Tab/BackTab: switch view  1-8/left-right: action  [ ] or PgUp/PgDn: section  j/k: field  e/Enter: edit  t: toggle/cycle  g or s: save template  q: quit"
        }
        _ => {
            "Tab/BackTab: switch view  1-8/left-right: action  j/k: suite (launcher/inspector)  i: inspector  m: monitor  l: launcher  a: all  c: clean  p: run path  e: extra args  PgUp/PgDn or [ ]: scroll logs in monitor  Enter/r: run  q: quit"
        }
    };
    let widget = Paragraph::new(help)
        .block(Block::default().borders(Borders::ALL).title("Keys"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}
use crate::*;
use crate::main_parts::*;
