# Benchmark Suite

Use the benchmark suite when you want repeatable, scenario-driven benchmark runs
against the Docker/Compose stack from a Rust-native runner, console, and load
driver.

The committed scenarios cover three main benchmark shapes:

- smoke-oriented validation runs
  Fast sanity validation only. Do not use their numbers for performance claims.
- end-to-end runtime comparisons through `nginx`
  Authenticated runs that measure gateway behavior under representative load.
- MCP prompt/resource/tool-heavy comparisons
  Scenarios that exercise MCP prompt, resource, and tool paths through
  `/servers/{server_id}/mcp`.

## What It Runs

Each scenario runs against the real containerized testing stack:

- PostgreSQL
- Redis
- PgBouncer
- gateway
- nginx
- `contextforge_goose` as the load driver
- optional `perf`, `flamegraph`, and other Rust-friendly profiling tools in a
  separate profiling pass

The runner is:

```bash
cargo run --manifest-path tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml --
```

Committed scenarios now live in:

```bash
tools_rust/contextforge_benchmark/assets/scenarios/
```

The benchmark launcher now lives in:

```bash
tools_rust/contextforge_benchmark/benchmark_console/
```

The Goose driver now lives in:

```bash
tools_rust/contextforge_benchmark/contextforge_goose/
```

## Quick Start

Open the interactive launcher:

```bash
make benchmark
```

Inside the launcher you can choose:

- `Run`
- `Validate`
- `Smoke`
- `Check Runtime`
- `List`
- `Report`
- `Compare`
- `Generate`

The `Generate` action opens a template builder that saves a new scenario file
under `tools_rust/contextforge_benchmark/assets/scenarios/`. It fills in the important fields in
the UI and writes a full TOML template containing all supported sections and
keys, including commented optional settings for advanced tuning.

Build the benchmark image expected by scenarios with `rebuild_policy = "never"`:

```bash
make container-build CONTAINER_FILE=tools_rust/contextforge_benchmark/assets/Containerfile ENABLE_RUST_BUILD=1 ENABLE_PROFILING_BUILD=1 CONTAINER_RUNTIME=podman
```

Validate the suite:

```bash
cargo run --manifest-path tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml -- validate --scenario rust-mcp-runtime-300
```

Run the smoke suite:

```bash
cargo run --manifest-path tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml -- run --scenario a2a-invoke-300 --smoke
```

Run the suite:

```bash
cargo run --manifest-path tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml -- run --scenario rust-mcp-runtime-300
```

The TUI discovers committed scenarios automatically from
`tools_rust/contextforge_benchmark/assets/scenarios/`.

## Scenario Contract

Supported sections are:

- `[suite]`
- `[defaults.setup]`
- `[defaults.build]`
- `[defaults.runtime]`
- `[defaults.gateway]`
- `[defaults.load]`
- `[defaults.load.env]`
- `[defaults.measurement]`
- `[defaults.requests]`
- `[defaults.profiling]`
- `[defaults.execution]`
- `[[scenario]]`
- `[scenario.runtime]`
- `[scenario.load]`
- `[scenario.requests]`
- `[scenario.execution]`

Unknown keys are currently ignored unless the runner checks them explicitly, so
scenario authors should treat validation as shape checking for supported fields
rather than strict unknown-key rejection.

## Important Fields

- `load.target_service = "nginx" | "gateway"`
  Use `nginx` for realistic end-to-end benchmarking. Use `gateway` only for
  direct app-path microbenchmarks.
- `execution.retry_enabled`, `execution.max_attempts`
  Control per-scenario retries.
- `execution.capture_logs`
  Persist service logs on failed runs.
- `measurement.*`
  Warmup, measurement, and cooldown are applied to Goose history when building
  the aggregated summary.
- `profiling.tools`
  Use Rust-native profiling tools such as `perf`, `flamegraph`, and
  `process_stats`.
- `suite.baseline_run`
  Optional path to a prior `run_summary.json` used for threshold-based
  comparison output.

## Request Mixes

The Rust Goose driver in `tools_rust/contextforge_benchmark/contextforge_goose/` uses real request
families:

- health checks
- admin plugin UI
- REST discovery (`/servers`, `/resources`, `/prompts`)
- MCP JSON-RPC discovery (`tools/list`, `resources/list`, `prompts/list`)
- MCP JSON-RPC prompt/resource/tool calls from payload fixtures in
  `tools_rust/contextforge_benchmark/assets/payloads/`

This means the committed scenario mixes now hit real prompt/resource/tool and
REST discovery code paths over the transports named in the scenario files, not
just health or admin endpoints.

## Reporting

Runs write to:

```text
reports/benchmarks/<profile>_<timestamp>/
```

Start here:

- `scenario_comparison_report.html`
- `scenario_comparison_report.json`
- `scenario_comparison_report.md`
- `run_summary.json`
- `run_summary.md`
- `comparison_matrix.json`
- `scenarios/<scenario>/summary.json`

Key reporting behaviors:

- unified report combines scenario metrics, pairwise deltas, fairness checks,
  recommendations, and artifact links when files exist
- validation mode marks metrics as omitted instead of emitting fake zero deltas
- comparison output shows `changed_dimensions` so intentional runtime changes do
  not look like fairness failures
- plugin timing is merged from per-process artifacts
- run metadata captures git SHA, runtime, compose version, and host facts
- optional `baseline_comparison.json` is written when `suite.baseline_run` is set

## Report Regeneration

Re-render a saved run:

```bash
cargo run --manifest-path tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml -- regenerate-report --run-dir reports/benchmarks/<run-dir>
```

Rebuild comparisons for a saved run:

```bash
cargo run --manifest-path tools_rust/contextforge_benchmark/benchmark_runner/Cargo.toml -- compare-run --run-dir reports/benchmarks/<run-dir>
```
