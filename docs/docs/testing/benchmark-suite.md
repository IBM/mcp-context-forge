# Benchmark Suite

Use the benchmark suite when you want repeatable, scenario-driven benchmark runs
against the Docker/Compose stack instead of ad hoc Locust commands.

The suite now distinguishes three lanes:

- `benchmark_smoke`
  Fast sanity validation only. Do not use its numbers for performance claims.
- `benchmark_runtime_baseline`
  Authenticated end-to-end runtime comparisons through `nginx`.
- `benchmark_plugin_sensitivity`
  Prompt/resource/tool-heavy comparisons that exercise plugin hooks through `/rpc`.

## What It Runs

Each scenario runs against the real containerized testing stack:

- PostgreSQL
- Redis
- PgBouncer
- gateway
- nginx
- Locust as the load driver
- optional `py-spy` and `memray` in a separate profiling pass

The runner is:

```bash
python3 -m benchmarks.contextforge
```

Committed scenarios now live in:

```bash
benchmarks/contextforge/scenarios/
```

The benchmark launcher now lives in:

```bash
tools_rust/benchmark_console/
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
under `benchmarks/contextforge/scenarios/`. It fills in the important fields in
the UI and writes a full TOML template containing all supported sections and
keys, including commented optional settings for advanced tuning.

Build the benchmark image expected by scenarios with `rebuild_policy = "never"`:

```bash
make container-build CONTAINER_FILE=benchmarks/contextforge/Containerfile ENABLE_RUST_BUILD=1 ENABLE_PROFILING_BUILD=1 CONTAINER_RUNTIME=podman
```

Validate the suite:

```bash
python3 -m benchmarks.contextforge --scenario modular-design-300 --validate
```

Run the smoke suite:

```bash
python3 -m benchmarks.contextforge --scenario a2a-invoke-300 --smoke
```

Run the suite:

```bash
python3 -m benchmarks.contextforge --scenario modular-design-300
```

The TUI discovers committed scenarios automatically from
`benchmarks/contextforge/scenarios/`.

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
- `[defaults.plugins]`
- `[defaults.execution]`
- `[[scenario]]`
- `[scenario.runtime]`
- `[scenario.load]`
- `[scenario.requests]`
- `[scenario.plugins]`
- `[scenario.execution]`

Unsupported keys now fail validation instead of being silently accepted.

## Important Fields

- `load.target_service = "nginx" | "gateway"`
  Use `nginx` for realistic end-to-end benchmarking. Use `gateway` only for
  direct app-path microbenchmarks.
- `execution.retry_enabled`, `execution.max_attempts`
  Control per-scenario retries.
- `execution.capture_logs`
  Persist service logs on failed runs.
- `measurement.*`
  Warmup, measurement, and cooldown are applied to Locust history when building
  the aggregated summary.
- `suite.baseline_run`
  Optional path to a prior `run_summary.json` used for threshold-based
  comparison output.

## Request Mixes

The benchmark-aware Locust file at
`benchmarks/contextforge/locust/locustfile_benchmark_ab.py` uses real request families:

- health checks
- admin plugin UI
- REST discovery (`/tools`, `/resources`, `/prompts`)
- JSON-RPC discovery (`tools/list`, `resources/list`, `prompts/list`)
- JSON-RPC prompt/resource/tool calls from payload fixtures in
  `benchmarks/contextforge/payloads/`

This means plugin-heavy profiles now hit real prompt/resource/tool code paths,
not just health or admin endpoints.

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
python3 -m benchmarks.contextforge --report-run reports/benchmarks/<run-dir>
```

Rebuild comparisons for a saved run:

```bash
python3 -m benchmarks.contextforge --compare-run reports/benchmarks/<run-dir>
```
