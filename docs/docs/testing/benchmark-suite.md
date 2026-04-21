# Benchmark Suite

The benchmark suite runs scenario-driven benchmarks against the real local
container stack. It covers validation, smoke runs, longer comparison runs,
report regeneration, and scenario generation from the TUI.

The suite is built from three Rust crates:

- `crates/contextforge_benchmark_runner/`: runner and report generation
- `crates/contextforge_benchmark_console/`: ratatui launcher and scenario generator
- `crates/contextforge_goose/`: load driver

Committed scenarios live in:

```text
crates/contextforge_benchmark_runner/assets/scenarios/
```

## What It Can Do

Current features in the suite:

- run against the real Compose stack with `PostgreSQL`, `Redis`, `PgBouncer`,
  `gateway`, and `nginx`
- run single-gateway and multi-gateway topologies
- route load through ingress with `nginx`
- enable plugins during setup
- build benchmark images with or without Rust plugin artifacts
- run Goose-driven request mixes against REST and MCP-style paths
- save per-scenario artifacts and aggregate comparison reports
- regenerate reports from a saved run directory
- compare a saved run again without rerunning the benchmark
- generate scenario templates from the TUI

## Requirements

Run the suite from the repository root.

You need:

- Docker with the Compose plugin available as `docker compose`
- a working Rust toolchain for `cargo run`
- permission to build local container images

The runner auto-detects Docker and builds the benchmark images it needs. You do
not need a separate manual image build step for the normal runner workflow.

## Fastest Start

Launch the TUI:

```bash
make benchmark
```

This opens the benchmark console. The current actions are:

- `Run`
- `Validate`
- `Smoke`
- `Check`
- `List`
- `Report`
- `Compare`
- `Generate`

`Generate` opens the built-in scenario template builder and writes a TOML file
under `crates/contextforge_benchmark_runner/assets/scenarios/`.

## CLI Workflow

The shortest entry points live in the repository `Makefile`.

### List Available Suites

```bash
make benchmark-list
```

This prints the committed scenario names, for example:

- `admin-plugins-300`
- `baseline-300`
- `multi-gateway-plugins-smoke`
- `multi-gateway-smoke`
- `rust-mcp-runtime-300`

### Validate a Scenario

Validation checks and renders the scenario without running load:

```bash
make benchmark-validate SCENARIO=multi-gateway-plugins-smoke
```

On the current branch this wrote:

```text
reports/benchmarks/multi-gateway-plugins-smoke_20260421_140002
```

Use validation first when you are editing a scenario and want a cheap check.

### Run a Smoke Benchmark

Smoke mode is the fastest real end-to-end path. It starts the stack and runs
the scenario with smoke settings:

```bash
make benchmark-smoke SCENARIO=multi-gateway-plugins-smoke
```

Use this before longer runs. It exercises the real stack and produces the same
artifact shape as a full run.

On the current branch this completed successfully and wrote:

```text
reports/benchmarks/multi-gateway-plugins-smoke_20260421_140004
```

### Run with the Scenario's Full Load

To use the scenario's committed load settings, run the same command without
smoke mode:

```bash
make benchmark-run SCENARIO=multi-gateway-plugins-smoke
```

This is the current real-world multi-gateway example: two gateway nodes behind
`nginx`, shared `postgres` + `redis` + `pgbouncer`, and plugins enabled.

On April 21, 2026, this command was also verified from a cold local Docker
state after deleting the benchmark image and ingress image first. That full run
completed successfully and wrote:

```text
reports/benchmarks/multi-gateway-plugins-smoke_20260421_140113
```

### Regenerate Reports from a Saved Run

```bash
make benchmark-report RUN_DIR=reports/benchmarks/multi-gateway-plugins-smoke_20260421_140113
```

### Rebuild the Comparison Output for a Saved Run

```bash
make benchmark-compare RUN_DIR=reports/benchmarks/multi-gateway-plugins-smoke_20260421_140113
```

### `check-runtime`

The runner has a `check-runtime` command for setup diagnostics:

```text
make benchmark-check-runtime SCENARIO=multi-gateway-plugins-smoke
```

On the current branch this completed successfully and wrote:

```text
reports/benchmarks/multi-gateway-plugins-smoke_20260421_140252
```

## Scenario File Structure

Each suite file is TOML with this top-level shape:

- `[suite]`: suite metadata and report settings
- `[defaults.*]`: shared defaults for all scenarios in the file
- `[[scenario]]`: one or more scenario entries
- `[scenario.*]`: per-scenario overrides

Main sections in use today:

- `[defaults.setup]`
- `[defaults.build]`
- `[defaults.runtime]`
- `[defaults.topology]`
- `[defaults.gateway]`
- `[defaults.load]`
- `[defaults.measurement]`
- `[defaults.profiling]`
- `[defaults.execution]`
- `[[scenario]]`
- `[scenario.build]`
- `[scenario.runtime]`
- `[scenario.topology]`
- `[scenario.load]`
- `[scenario.profiling]`
- `[scenario.execution]`

## Fields That Matter Most

### Setup and Build

- `setup.plugins_enabled`
  Turns plugin-aware setup on.
- `build.rust_plugins`
  Builds and installs Rust plugin artifacts into the benchmark image.
- `build.container_file`
  Containerfile used for the benchmark image build.
- `build.image_name`, `build.image_tag`
  Local image naming for the scenario.
- `build.rebuild_policy`
  Current supported values are `never`, `missing`, and `always`.

### Runtime and Gateway

- `runtime.http_server`
  Current scenarios use `gunicorn`.
- `runtime.transport_type`
  Current generator support is `streamablehttp`, `sse`, or `websocket`.
- `gateway.environment`
  Extra gateway env vars applied to the benchmark containers.

### Load and Measurement

- `load.users`, `load.spawn_rate`, `load.run_time`, `load.request_count`
  Main load shape controls.
- `load.target_service`
  Usually `nginx` for realistic end-to-end benchmarking.
- `load.workload.*`
  Endpoint mix, weights, and fallback endpoint.
- `measurement.warmup_seconds`, `measure_seconds`, `cooldown_seconds`
  Windows used when summarizing results.

### Execution and Profiling

- `execution.retry_enabled`, `max_attempts`
  Per-scenario retry behavior.
- `execution.capture_logs`
  Saves service logs on failures.
- `execution.save_raw_results`
  Keeps raw benchmark artifacts.
- `execution.reuse_stack`
  Reuses the stack across scenarios in the same suite when possible.
- `profiling.enabled`, `profiling.tools`, `profiling.duration_seconds`
  Controls the optional profiling pass.

### Baseline Comparison

- `suite.baseline_run`
  Optional path to an earlier run summary for threshold-based comparisons.

## Multi-Gateway Topology

The suite now supports real multi-gateway benchmark topologies with one ingress
and multiple gateway nodes behind it.

Current model:

- one ingress endpoint: `nginx`
- multiple synthesized gateway services: `gateway-1`, `gateway-2`, and so on
- one shared backing tier: `postgres`, `redis`, `pgbouncer`
- benchmark traffic goes through ingress

The smallest committed multi-gateway example is:

```text
crates/contextforge_benchmark_runner/assets/scenarios/multi-gateway-smoke.toml
```

The current plugin-enabled real-world example is:

```text
crates/contextforge_benchmark_runner/assets/scenarios/multi-gateway-plugins-smoke.toml
```

Core topology fields:

```toml
[defaults.topology]
mode = "multi_gateway"
gateway_count = 2
ingress_enabled = true
ingress_service = "nginx"
shared_services = ["postgres", "redis", "pgbouncer"]
gateway_base_service = "gateway"
gateway_name_prefix = "gateway"
```

Per-node overrides are supported with `[[scenario.topology.gateway_override]]`.
In v1 they are limited to env, labels, and ports.

Current limits:

- multi-gateway runs must use `ingress_service = "nginx"`
- multi-gateway runs must target ingress, not a direct gateway node
- `postgres`, `redis`, and `pgbouncer` are shared singleton services, not
  clustered services

## Reports and Artifacts

Runs write under:

```text
reports/benchmarks/<suite>_<timestamp>/
```

Important files:

- `run_summary.json`
- `run_summary.md`
- `scenario_comparison_report.json`
- `scenario_comparison_report.md`
- `scenario_comparison_report.html`
- `comparison_matrix.json`
- `scenarios/<scenario-name>/summary.json`

The reports include:

- per-scenario status and metrics
- pairwise comparisons
- changed-dimension reporting for fair comparisons
- topology metadata, including multi-gateway details
- links to captured artifacts when present

## Good Working Routine

Use this order:

1. `make benchmark` if you want the TUI or generator.
2. `make benchmark-list` to find the scenario name.
3. `make benchmark-validate SCENARIO=<name>` after editing a scenario.
4. `make benchmark-smoke SCENARIO=<name>` for a fast real run.
5. `make benchmark-run SCENARIO=<name>` when the smoke run looks good.
6. use `make benchmark-report ...` or `make benchmark-compare ...` on saved
   output instead of rerunning the stack when you only need report changes.
