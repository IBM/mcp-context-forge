pub(crate) fn draw(frame: &mut ratatui::Frame<'_>, app: &App) {
    let chunks = if app.active_view == AppView::Generator {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(5),
                Constraint::Min(16),
                Constraint::Length(4),
            ])
            .split(frame.area())
    } else {
        Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(14),
                Constraint::Length(5),
                Constraint::Min(10),
                Constraint::Length(4),
            ])
            .split(frame.area())
    };

    let header = Paragraph::new(vec![
        Line::from(Span::styled(
            "ContextForge Benchmark Console",
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        )),
        Line::from(format!("Mode: {}", app.mode.label())),
    ])
    .block(Block::default().borders(Borders::ALL).title("Console"));
    frame.render_widget(header, chunks[0]);

    let view_tabs = Tabs::new(
        AppView::ALL
            .iter()
            .map(|view| Line::from(view.label().to_string()))
            .collect::<Vec<_>>(),
    )
    .select(
        AppView::ALL
            .iter()
            .position(|view| *view == app.active_view)
            .unwrap_or(0),
    )
    .block(Block::default().borders(Borders::ALL).title("Views"))
    .highlight_style(
        Style::default()
            .fg(Color::Black)
            .bg(Color::Green)
            .add_modifier(Modifier::BOLD),
    );
    frame.render_widget(view_tabs, chunks[1]);

    let tabs = Tabs::new(
        Action::ALL
            .iter()
            .enumerate()
            .map(|(index, action)| Line::from(format!("{} {}", index + 1, action.label())))
            .collect::<Vec<_>>(),
    )
    .select(app.action_index)
    .block(Block::default().borders(Borders::ALL).title("Actions"))
    .highlight_style(
        Style::default()
            .fg(Color::Black)
            .bg(Color::Cyan)
            .add_modifier(Modifier::BOLD),
    );
    frame.render_widget(tabs, chunks[2]);

    draw_status_banner(frame, chunks[3], app);

    if app.active_view == AppView::Generator {
        draw_generator_sections(frame, chunks[2], app);
        let body = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(56), Constraint::Percentage(44)])
            .split(chunks[4]);
        let left = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(10), Constraint::Length(11)])
            .split(body[0]);
        draw_generator_fields(frame, left[0], app);
        draw_generator_selection(frame, left[1], app);
        draw_generator_reference(frame, body[1], app);
    } else {
        match app.active_view {
            AppView::Launcher => draw_launcher_view(frame, chunks[4], app),
            AppView::SuiteInspector => draw_suite_inspector_view(frame, chunks[4], app),
            AppView::RunMonitor => draw_run_monitor_view(frame, chunks[4], app),
            AppView::Generator => {}
        }
    }
    draw_help(frame, chunks[5], app);
}

fn draw_status_banner(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let selected_suite = app
        .selected_suite()
        .map(SuiteSummary::label)
        .unwrap_or("(none)");
    let status_lines = vec![
        Line::from(vec![
            Span::styled("Action ", Style::default().fg(Color::Gray)),
            Span::styled(
                app.action().label(),
                Style::default()
                    .fg(Color::Cyan)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::raw("   "),
            Span::styled("View ", Style::default().fg(Color::Gray)),
            Span::styled(
                app.active_view.label(),
                Style::default()
                    .fg(Color::Green)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::raw("   "),
            Span::styled("Suite ", Style::default().fg(Color::Gray)),
            Span::styled(
                selected_suite,
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::BOLD),
            ),
        ]),
        Line::from(vec![
            Span::styled("Status ", Style::default().fg(Color::Gray)),
            Span::styled(
                app.status.as_str(),
                Style::default().fg(if app.running_command.is_some() {
                    Color::Yellow
                } else {
                    Color::Green
                })
                .add_modifier(Modifier::BOLD),
            ),
        ]),
        Line::from(vec![
            Span::styled("Live Run ", Style::default().fg(Color::Gray)),
            Span::styled(
                if app.running_command.is_some() {
                    "active"
                } else {
                    "idle"
                },
                Style::default()
                    .fg(if app.running_command.is_some() {
                        Color::LightYellow
                    } else {
                        Color::DarkGray
                    })
                    .add_modifier(Modifier::BOLD),
            ),
        ]),
    ];
    let widget = Paragraph::new(status_lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Operator Status"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_generator_sections(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let tabs = Tabs::new(
        GeneratorState::sections()
            .iter()
            .map(|section| Line::from((*section).to_string()))
            .collect::<Vec<_>>(),
    )
    .select(app.generator.selected_section)
    .block(
        Block::default()
            .borders(Borders::ALL)
            .title("Generator Sections"),
    )
    .highlight_style(
        Style::default()
            .fg(Color::Black)
            .bg(Color::Green)
            .add_modifier(Modifier::BOLD),
    );
    frame.render_widget(tabs, area);
}

fn draw_scenarios(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let items = app
        .scenarios
        .iter()
        .map(|scenario| {
            ListItem::new(vec![
                Line::from(Span::styled(
                    scenario.label().to_string(),
                    Style::default().add_modifier(Modifier::BOLD),
                )),
                Line::from(Span::styled(
                    scenario.suite_name().to_string(),
                    Style::default().fg(Color::Gray),
                )),
            ])
        })
        .collect::<Vec<_>>();
    let list = List::new(items)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Benchmark Suites"),
        )
        .highlight_style(
            Style::default()
                .fg(Color::Black)
                .bg(Color::Yellow)
                .add_modifier(Modifier::BOLD),
        )
        .highlight_symbol(">> ")
        .highlight_spacing(ratatui::widgets::HighlightSpacing::Always);
    let mut state = ListState::default();
    state.select(Some(app.scenario_index));
    frame.render_stateful_widget(list, area, &mut state);
}

fn draw_launcher_view(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let body = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(36), Constraint::Percentage(64)])
        .split(area);
    draw_scenarios(frame, body[0], app);
    let right = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(12), Constraint::Min(10)])
        .split(body[1]);
    let top = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(42), Constraint::Percentage(58)])
        .split(right[0]);
    draw_selection(frame, top[0], app);
    draw_launcher_summary(frame, top[1], app);
    draw_preview(frame, right[1], app);
}

fn draw_suite_inspector_view(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let body = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(8), Constraint::Min(14)])
        .split(area);
    draw_inspector_header(frame, body[0], app);
    draw_scenario_cards(frame, body[1], app);
}

fn draw_run_monitor_view(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let body = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(10), Constraint::Min(14)])
        .split(area);
    draw_run_monitor_summary(frame, body[0], app);
    draw_live_logs(frame, body[1], app);
}

fn draw_selection(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_selection_summary(app);
    let lines = vec![
        line_pair("Action", &summary.action_label),
        line_pair("Suite", &summary.suite_label),
        line_pair("Run Mode", &summary.run_mode_label),
        line_pair("Clean First", &summary.clean_label),
        line_pair("Run Path", &summary.run_path_label),
        line_pair("Extra Args", &summary.extra_args_label),
    ];
    let widget = Paragraph::new(lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Selection State"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_launcher_summary(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_suite_inspector_summary(app, Path::new(".")).unwrap_or_default();
    let lines = vec![
        Line::from(Span::styled(
            summary.suite_name,
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        line_pair("Intent", &summary.suite_description),
        line_pair("Comparison Set", &summary.scenario_count_label),
        line_pair(
            "Inspector",
            "Press 'i' or Tab to open full scenario comparison cards",
        ),
    ];
    let widget = Paragraph::new(lines)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title("Suite Summary"),
        )
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_inspector_header(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_suite_inspector_summary(app, Path::new(".")).unwrap_or_default();
    let lines = vec![
        Line::from(Span::styled(
            summary.suite_name,
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        )),
        Line::from(summary.suite_description),
        Line::from(""),
        line_pair("Comparison Set", &summary.scenario_count_label),
        line_pair("Question", &summary.comparison_question),
    ];
    let widget = Paragraph::new(lines)
        .block(Block::default().borders(Borders::ALL).title("Suite Inspector"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}

fn draw_scenario_cards(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let summary = build_suite_inspector_summary(app, Path::new(".")).unwrap_or_default();
    if summary.scenario_cards.is_empty() {
        let widget = Paragraph::new("No scenarios found for the selected suite.")
            .block(Block::default().borders(Borders::ALL).title("Scenario Comparison"));
        frame.render_widget(widget, area);
        return;
    }

    let constraints = vec![Constraint::Ratio(1, summary.scenario_cards.len() as u32); summary.scenario_cards.len()];
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints(constraints)
        .split(area);

    for (index, card) in summary.scenario_cards.iter().enumerate() {
        let is_active = app.current_run_scenario.as_deref() == Some(card.name.as_str());
        let mut lines = vec![
            Line::from(Span::styled(
                card.name.clone(),
                Style::default()
                    .fg(if is_active { Color::Yellow } else { Color::White })
                    .add_modifier(Modifier::BOLD),
            )),
            Line::from(card.description.clone()),
            Line::from(format!("Type: {}", card.scenario_type)),
        ];
        if card.settings.is_empty() {
            lines.push(Line::from("Settings: inherits suite defaults"));
        } else {
            lines.push(Line::from("Settings:"));
            lines.extend(card.settings.iter().map(|(key, value)| {
                Line::from(format!("  {} = {}", key, value))
            }));
        }
        let title = if is_active {
            format!("Scenario {} (active)", index + 1)
        } else {
            format!("Scenario {}", index + 1)
        };
        let widget = Paragraph::new(lines)
            .block(Block::default().borders(Borders::ALL).title(title))
            .wrap(Wrap { trim: false });
        frame.render_widget(widget, chunks[index]);
    }
}

fn draw_run_monitor_summary(frame: &mut ratatui::Frame<'_>, area: Rect, app: &App) {
    let selected_suite = app
        .selected_suite()
        .map(SuiteSummary::suite_name)
        .unwrap_or("(none)");
    let current = app.current_run_scenario.as_deref().unwrap_or("(idle)");
    let buffered_logs = app.log_lines.len().to_string();
    let dropped_logs = app.dropped_log_lines.to_string();
    let statuses = if app.run_scenarios.is_empty() {
        vec![Line::from("No run scenarios recorded yet.")]
    } else {
        app.run_scenarios
            .iter()
            .map(|item| Line::from(format!("{} -> {}", item.name, item.status)))
            .collect::<Vec<_>>()
    };
    let mut lines = vec![
        line_pair("Suite", selected_suite),
        line_pair(
            "Command",
            app.last_command_label.as_deref().unwrap_or("(no command launched)"),
        ),
        line_pair("Current Scenario", current),
        line_pair(
            "Run Dir",
            app.last_run_dir.as_deref().unwrap_or("(pending)"),
        ),
        line_pair(
            "Outcome",
            app.last_run_outcome.as_deref().unwrap_or("(running or pending)"),
        ),
        line_pair("Buffered Logs", &buffered_logs),
        line_pair("Dropped Logs", &dropped_logs),
        Line::from(""),
        Line::from(Span::styled(
            "Scenario Status",
            Style::default().add_modifier(Modifier::BOLD),
        )),
    ];
    lines.extend(statuses);
    let widget = Paragraph::new(lines)
        .block(Block::default().borders(Borders::ALL).title("Run Monitor"))
        .wrap(Wrap { trim: false });
    frame.render_widget(widget, area);
}
use crate::*;
use crate::main_parts::*;
