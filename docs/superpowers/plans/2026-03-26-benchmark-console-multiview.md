# Benchmark Console Multi-View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Rust benchmark console into a tabbed multi-view workspace with a clear suite inspector, a dedicated run monitor, and live in-UI logs.

**Architecture:** Keep the existing Ratatui application but split the UI into explicit views: Launcher, Suite Inspector, Run Monitor, and Generator. Introduce typed suite/scenario inspector metadata and a dedicated run session model so rendering code can show per-scenario comparison cards and live execution state without reparsing raw TOML or overloading the launcher.

**Tech Stack:** Rust, Ratatui, Crossterm, std process management, std mpsc channels, TOML metadata parsing

---

### Task 1: Introduce Multi-View App State

**Files:**
- Modify: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`
- Test: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`

- [ ] **Step 1: Write the failing test**

Add tests that assert:
- top-level view state defaults to Launcher
- view switching updates the active tab cleanly
- starting a captured command moves the app to Run Monitor

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: FAIL with missing multi-view state / switching behavior

- [ ] **Step 3: Write minimal implementation**

Add:
- `enum AppView { Launcher, SuiteInspector, RunMonitor, Generator }`
- app state for `active_view`
- helper methods to switch views and auto-route Generate to Generator and active runs to Run Monitor

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs
git commit -s -m "feat: add benchmark console multiview state"
```

### Task 2: Add Typed Suite Inspector Metadata

**Files:**
- Modify: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`
- Test: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`

- [ ] **Step 1: Write the failing test**

Add tests that assert suite parsing produces per-scenario card metadata with:
- scenario name
- scenario description
- scenario type
- key differentiators like runtime expectations, plugin flags, and important gateway env toggles

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: FAIL because suite inspector summaries do not yet exist

- [ ] **Step 3: Write minimal implementation**

Add typed summaries such as:
- `ScenarioCardSummary`
- `SuiteInspectorSummary`

Build them from the selected suite TOML using only the fields worth surfacing in the UI.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs
git commit -s -m "feat: add benchmark suite inspector metadata"
```

### Task 3: Refactor Launcher Into A Lightweight Workspace

**Files:**
- Modify: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`
- Test: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`

- [ ] **Step 1: Write the failing test**

Add a test that verifies launcher summaries stay compact and no longer rely on the detailed per-scenario comparison string previously shown in Suite Context.

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: FAIL because launcher still exposes the old single-screen layout assumptions

- [ ] **Step 3: Write minimal implementation**

Adjust the render flow so Launcher contains:
- suite list
- action selection
- compact suite summary
- quick execution hints

Remove crowded scenario-detail rendering from Launcher.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs
git commit -s -m "refactor: simplify benchmark console launcher"
```

### Task 4: Build The Suite Inspector View

**Files:**
- Modify: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`
- Test: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`

- [ ] **Step 1: Write the failing test**

Add tests that assert the suite inspector summary includes:
- suite description
- comparison question
- one card summary per scenario
- differentiator labels for baseline vs variant

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: FAIL because the inspector view and card summaries are not rendered yet

- [ ] **Step 3: Write minimal implementation**

Add a dedicated `Suite Inspector` view and render:
- suite header
- scenario cards
- selected or active scenario highlighting

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs
git commit -s -m "feat: add benchmark suite inspector view"
```

### Task 5: Promote Live Logs Into Run Monitor

**Files:**
- Modify: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`
- Test: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`

- [ ] **Step 1: Write the failing test**

Add tests that assert:
- command launch switches to Run Monitor
- log lines remain buffered in the run session
- per-scenario progress state can be displayed separately from the raw logs

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: FAIL because Run Monitor-specific state is incomplete

- [ ] **Step 3: Write minimal implementation**

Create a dedicated `Run Monitor` view with:
- current command
- active scenario
- per-scenario status list
- large live log panel

Keep the existing child-process capture model inside Ratatui.

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs
git commit -s -m "feat: add benchmark run monitor view"
```

### Task 6: Connect Run Progress To UI Status

**Files:**
- Modify: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`
- Modify: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/src/lib.rs`
- Test: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs`
- Test: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/src/lib.rs`

- [ ] **Step 1: Write the failing test**

Add tests that assert:
- runner progress lines identify scenario boundaries clearly enough for the console to classify them
- console updates the active scenario and per-scenario status list from those progress lines

- [ ] **Step 2: Run test to verify it fails**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml --quiet`
Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: FAIL because structured progress interpretation is not complete yet

- [ ] **Step 3: Write minimal implementation**

Standardize runner progress messages and teach the console to derive:
- current scenario
- completed scenario statuses
- final run outcome

- [ ] **Step 4: Run test to verify it passes**

Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml --quiet`
Run: `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/src/lib.rs
git commit -s -m "feat: surface benchmark run progress in console views"
```

### Task 7: Verify End-To-End Behavior

**Files:**
- Modify: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs` (only if fixes are needed)
- Modify: `/Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/src/lib.rs` (only if fixes are needed)

- [ ] **Step 1: Run the full Rust test suite for the benchmark bundle**

Run:
- `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/Cargo.toml --quiet`
- `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml --quiet`
- `cargo test --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/contextforge_goose/Cargo.toml --quiet`

Expected: PASS

- [ ] **Step 2: Validate a representative suite**

Run: `cargo run --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml -- validate --scenario rust-mcp-runtime-300`
Expected: PASS and prints a run directory

- [ ] **Step 3: Run a smoke benchmark**

Run: `cargo run --manifest-path /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml -- run --scenario rest-discovery-300 --smoke`
Expected: completes both scenarios and keeps streaming progress visible throughout

- [ ] **Step 4: Fix any issues revealed by verification**

If the smoke run exposes auth, status, or logging issues, make the minimal fix and rerun the affected verification.

- [ ] **Step 5: Commit**

```bash
git add /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_console/src/main.rs /Users/luca/dev/mcp-context-forge/tools_rust/contextforge_benchmark/benchmark_runner/src/lib.rs
git commit -s -m "fix: polish benchmark console multiview execution flow"
```
