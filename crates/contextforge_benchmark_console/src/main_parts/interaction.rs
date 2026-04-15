pub(crate) fn setup_terminal() -> AppResult<Terminal<CrosstermBackend<Stdout>>> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, Hide)?;
    Ok(Terminal::new(CrosstermBackend::new(stdout))?)
}

pub(crate) fn restore_terminal(terminal: &mut Terminal<CrosstermBackend<Stdout>>) -> AppResult<()> {
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), Show, LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    Ok(())
}

pub(crate) fn run_app(
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
    mut app: App,
    root: &Path,
) -> AppResult<()> {
    while !app.should_quit {
        drain_running_command(&mut app)?;
        terminal.draw(|frame| draw(frame, &app))?;
        if event::poll(Duration::from_millis(100))? {
            if let Event::Key(key) = event::read()? {
                handle_key_event(&mut app, key, root, terminal)?;
            }
        }
    }
    Ok(())
}

pub(crate) fn handle_key_event(
    app: &mut App,
    key: KeyEvent,
    root: &Path,
    _terminal: &mut Terminal<CrosstermBackend<Stdout>>,
) -> AppResult<()> {
    match app.mode {
        InputMode::Normal => handle_normal_mode(app, key, root),
        InputMode::EditRunPath => handle_text_input(app, key, InputMode::EditRunPath),
        InputMode::EditExtraArgs => handle_text_input(app, key, InputMode::EditExtraArgs),
        InputMode::EditGeneratorField => handle_text_input(app, key, InputMode::EditGeneratorField),
    }
}

pub(crate) fn handle_normal_mode(app: &mut App, key: KeyEvent, root: &Path) -> AppResult<()> {
    if app.active_view == AppView::Generator {
        return handle_generate_mode(app, key, root);
    }

    match key.code {
        KeyCode::Char('q') | KeyCode::Esc => app.should_quit = true,
        KeyCode::Tab => app.cycle_view(1),
        KeyCode::BackTab => app.cycle_view(-1),
        KeyCode::Left => app.move_action(-1),
        KeyCode::Right => app.move_action(1),
        KeyCode::Up | KeyCode::Char('k') if app.active_view.supports_suite_navigation() => {
            app.move_scenario(-1)
        }
        KeyCode::Down | KeyCode::Char('j') if app.active_view.supports_suite_navigation() => {
            app.move_scenario(1)
        }
        KeyCode::Char('1') => app.set_action_index(0),
        KeyCode::Char('2') => app.set_action_index(1),
        KeyCode::Char('3') => app.set_action_index(2),
        KeyCode::Char('4') => app.set_action_index(3),
        KeyCode::Char('5') => app.set_action_index(4),
        KeyCode::Char('6') => app.set_action_index(5),
        KeyCode::Char('7') => app.set_action_index(6),
        KeyCode::Char('8') => app.set_action_index(7),
        KeyCode::Char('i') => app.set_view(AppView::SuiteInspector),
        KeyCode::Char('l') => app.set_view(AppView::Launcher),
        KeyCode::Char('m') => app.set_view(AppView::RunMonitor),
        KeyCode::PageUp | KeyCode::Char('[') if app.active_view == AppView::RunMonitor => {
            app.log_scroll = app
                .log_scroll
                .saturating_add(10)
                .min(app.log_lines.len().saturating_sub(1));
            app.status = format!("Log scroll offset: {}", app.log_scroll);
        }
        KeyCode::PageDown | KeyCode::Char(']') if app.active_view == AppView::RunMonitor => {
            app.log_scroll = app.log_scroll.saturating_sub(10);
            app.status = format!("Log scroll offset: {}", app.log_scroll);
        }
        KeyCode::Char('a') => {
            if app.action().supports_all() {
                app.all = !app.all;
                app.status = format!("Run all scenarios: {}", yes_no(app.all));
            } else {
                app.status = "This action does not support all-scenario mode.".to_string();
            }
        }
        KeyCode::Char('c') => {
            if app.action().supports_clean() {
                app.clean = !app.clean;
                app.status = format!("Clean before launch: {}", yes_no(app.clean));
            } else {
                app.status = "This action does not use cleanup.".to_string();
            }
        }
        KeyCode::Char('p') => {
            if app.action().needs_run_path() {
                app.mode = InputMode::EditRunPath;
                app.status =
                    "Editing run path. Type, Backspace to delete, Enter to finish.".to_string();
            } else {
                app.status = "Run path is only used for Report and Compare.".to_string();
            }
        }
        KeyCode::Char('e') => {
            app.mode = InputMode::EditExtraArgs;
            app.status =
                "Editing extra args. Type, Backspace to delete, Enter to finish.".to_string();
        }
        KeyCode::Enter | KeyCode::Char('r') => launch_action(app, root)?,
        _ => {}
    }
    Ok(())
}

pub(crate) fn handle_generate_mode(app: &mut App, key: KeyEvent, root: &Path) -> AppResult<()> {
    match key.code {
        KeyCode::Char('q') | KeyCode::Esc => app.should_quit = true,
        KeyCode::Tab => app.cycle_view(1),
        KeyCode::BackTab => app.cycle_view(-1),
        KeyCode::Left => app.move_action(-1),
        KeyCode::Right => app.move_action(1),
        KeyCode::Char('[') | KeyCode::PageUp => {
            app.generator.move_section(-1);
            app.status = format!("Section: {}", app.generator.selected_section_name());
        }
        KeyCode::Char(']') | KeyCode::PageDown => {
            app.generator.move_section(1);
            app.status = format!("Section: {}", app.generator.selected_section_name());
        }
        KeyCode::Up | KeyCode::Char('k') => app.generator.move_selected(-1),
        KeyCode::Down | KeyCode::Char('j') => app.generator.move_selected(1),
        KeyCode::Char('1') => app.set_action_index(0),
        KeyCode::Char('2') => app.set_action_index(1),
        KeyCode::Char('3') => app.set_action_index(2),
        KeyCode::Char('4') => app.set_action_index(3),
        KeyCode::Char('5') => app.set_action_index(4),
        KeyCode::Char('6') => app.set_action_index(5),
        KeyCode::Char('7') => app.set_action_index(6),
        KeyCode::Char('8') => app.set_action_index(7),
        KeyCode::Char('t') => {
            app.generator.toggle_or_cycle();
            app.status = format!("Updated {}", app.generator.selected_field().label);
        }
        KeyCode::Enter | KeyCode::Char('e') => match app.generator.selected_field().kind {
            GeneratorFieldKind::Text => {
                app.mode = InputMode::EditGeneratorField;
                app.status = format!("Editing {}", app.generator.selected_field().label);
            }
            GeneratorFieldKind::Bool | GeneratorFieldKind::Choice(_) => {
                app.generator.toggle_or_cycle();
                app.status = format!("Updated {}", app.generator.selected_field().label);
            }
        },
        KeyCode::Char('g') | KeyCode::Char('s') => {
            let path = save_generated_template(root, &mut app.scenarios, &app.generator)?;
            app.status = format!("Saved scenario template to {}", path.display());
        }
        _ => {}
    }
    Ok(())
}

pub(crate) fn handle_text_input(app: &mut App, key: KeyEvent, mode: InputMode) -> AppResult<()> {
    let buffer: &mut String = match mode {
        InputMode::EditRunPath => &mut app.run_path,
        InputMode::EditExtraArgs => &mut app.extra_args,
        InputMode::EditGeneratorField => &mut app.generator.selected_field_mut().value,
        InputMode::Normal => return Ok(()),
    };

    match key.code {
        KeyCode::Esc => {
            app.mode = InputMode::Normal;
            app.status = "Cancelled edit.".to_string();
        }
        KeyCode::Enter => {
            app.mode = InputMode::Normal;
            if mode == InputMode::EditGeneratorField {
                app.generator.ensure_visible_selection();
            }
            app.status = "Saved input.".to_string();
        }
        KeyCode::Backspace => {
            buffer.pop();
        }
        KeyCode::Char(c) => {
            buffer.push(c);
        }
        _ => {}
    }
    Ok(())
}
use crate::main_parts::*;
use crate::*;
