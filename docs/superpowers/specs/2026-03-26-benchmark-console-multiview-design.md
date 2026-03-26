# Benchmark Console Multi-View Design

## Summary

Refactor the Rust benchmark console in `tools_rust/contextforge_benchmark/benchmark_console` from a single crowded dashboard into a tabbed operator workspace. The new UI should make three things immediately clear:

1. what suite is selected
2. what scenarios inside that suite are being compared
3. what the currently running benchmark is doing right now

The design keeps the existing keyboard-driven Ratatui approach, but separates browsing, comparison inspection, live execution, and generation into dedicated views.

## Goals

- Make suite-internal scenario comparisons visually explicit
- Give live logs a dedicated large workspace
- Reduce cognitive overload in the launcher
- Preserve the current Rust-only benchmark workflow and keybindings where practical
- Keep the implementation maintainable by separating navigation state from execution state

## Non-Goals

- Changing the benchmark runner CLI contract
- Changing scenario TOML schema beyond better display of existing metadata
- Replacing Ratatui with another UI framework
- Adding modal-heavy workflows or mouse-dependent interaction

## Information Architecture

The console becomes a tabbed workspace with four views:

### 1. Launcher

Purpose: choose a suite and an action quickly.

Content:

- suite list
- action tabs
- compact suite summary
- quick execution hints

Launcher should stay intentionally compact. It is no longer responsible for showing full per-scenario comparison detail or full live logs.

### 2. Suite Inspector

Purpose: explain what the selected suite compares.

Content:

- suite name
- suite description
- comparison question the suite answers
- one scenario card per scenario in the suite

Each scenario card should show:

- scenario name
- scenario description
- scenario type
- key differentiators only

Example differentiators:

- `rust_plugins`
- `plugins_enabled`
- `expected_mcp_runtime`
- `expected_mcp_runtime_mode`
- `expected_a2a_runtime`
- notable gateway environment toggles such as `RUST_MCP_MODE`

The cards should make baseline versus variant comparisons readable without opening the TOML.

### 3. Run Monitor

Purpose: monitor a benchmark while it is running.

Content:

- active command / active suite / active scenario
- per-scenario progress and final status list
- large live log panel as the primary content area
- final run directory and result summary when complete

This becomes the main execution workspace. Starting a run from Launcher should automatically switch to Run Monitor.

### 4. Generator

Purpose: author and save benchmark scenario templates.

The generator remains its own guided form view and should no longer share space with live run monitoring.

## Layout Guidance

### Global

- Top-level tabs should switch views cleanly
- Status should stay visible near the top
- Visual hierarchy should emphasize selected suite, active view, and active run state

### Suite Inspector

- Use stacked scenario cards or a two-column card grid depending on terminal width
- When a run is active, highlight the currently running scenario card
- Make descriptions and differentiators readable at standard terminal sizes

### Run Monitor

- Reserve most vertical space for logs
- Keep scenario progress summary above the logs
- Distinguish system, stdout, and stderr lines visually
- Do not leave the Ratatui UI while a command is running

## State Model

The current single-screen state should be split into clearer domains:

### Navigation State

- active top-level view
- selected suite
- selected action
- generator focus

### Suite Metadata State

- suite summary
- suite description
- parsed scenario summaries
- scenario differentiator fields for rendering cards

### Run Session State

- whether a command is active
- current command label
- current scenario name
- per-scenario status summary
- live log buffer
- final run directory
- final exit/result state

This separation should reduce rendering logic that currently reparses suite TOML ad hoc in widget code.

## Data Extraction

Add typed metadata for suite inspection so rendering code does not work directly on raw `toml::Value`.

Suggested types:

- `SuiteSummary`
- `ScenarioCardSummary`
- `SuiteInspectorSummary`
- `RunSessionSummary`

`ScenarioCardSummary` should normalize the small set of settings worth surfacing in the UI instead of dumping every field.

## Interaction Model

- `Launcher` remains the default landing view
- `Enter` on a runnable action starts the command and switches to `Run Monitor`
- an inspect shortcut should move from `Launcher` to `Suite Inspector`
- tabs or left/right view switching should move between top-level views
- `Run Monitor` should remain readable even after the run finishes

## Error Handling

- If a suite TOML cannot be parsed for inspector metadata, show an explicit inspector error card instead of leaving blank space
- If a benchmark command fails, keep the logs on screen and mark the affected scenario as failed
- If no run is active, `Run Monitor` should show an idle placeholder rather than an empty panel

## Testing

Add or update console tests for:

- suite inspector metadata parsing
- scenario card differentiation rendering inputs
- run session log buffering and status updates
- automatic transition into run monitor on launch
- view switching behavior

Keep existing runner and console tests passing.

## Implementation Notes

- Prefer incremental refactoring over one large render-function rewrite
- Start by introducing typed metadata and top-level view state
- Then move the existing launcher into the new tab structure
- Then add Suite Inspector cards
- Then promote live logs into the dedicated Run Monitor

## Acceptance Criteria

- A selected suite clearly shows all compared scenarios in Suite Inspector
- Live logs remain inside Ratatui and occupy most of Run Monitor
- Starting a run automatically moves the operator into Run Monitor
- The launcher feels lighter and less crowded than the previous single-view screen
- Operators can understand baseline versus variant settings without opening TOML files
