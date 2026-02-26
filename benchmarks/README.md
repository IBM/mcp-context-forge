# Benchmarks

Top-level benchmarks for ContextForge. Run everything with:

```bash
make benchmark
```

## What gets run

| Component | Location | Description |
|-----------|----------|-------------|
| Pytest benchmarks | `benchmarks/` | A2A differential and other pytest-benchmark suites (`--benchmark-only`) |
| Async benchmarks | `tests/async/benchmarks.py` | Async performance benchmarks; output in `benchmarks/reports/` |
| JSON serialization | `scripts/benchmark_json_serialization.py` | orjson vs stdlib json |
| Rust plugin benches | `plugins_rust/` | `cargo bench` (PII filter, secrets detection, etc.) |
| Rust vs Python | `plugins_rust/pii_filter/benchmarks/` | compare_pii_filter.py |

Optional (requires running server):

- `scripts/benchmark_middleware.py` — middleware chain performance (run after `make dev`).

## Selective runs

```bash
# Pytest benchmarks only (all)
make bench

# Pytest benchmarks matching a name: use BENCH= or second goal
make bench BENCH=<name>
make bench <name>

# Python pytest benchmarks only (requires [fuzz] extra for pytest-benchmark)
uv run --active --extra fuzz pytest benchmarks/ --benchmark-only -v

# Async benchmarks only
make async-benchmark

# Rust plugin benchmarks only
make rust-bench

# Rust vs Python comparison
make rust-bench-compare
```

## A2A invoke benchmark

Compares speed of `POST /a2a/{agent_name}/invoke` on the current branch to a **fixed legacy main** baseline so that after merge you still compare latest vs that baseline.

- **Prerequisite (branch with Rust A2A):** Install the gateway Rust extension so `gateway_rs` is available: `make gateway-rs-install` (or `make rust-install`). Without this, the benchmark fails with `ModuleNotFoundError: No module named 'gateway_rs'`.
- **Run:** `make bench a2a_invoke` or `make bench BENCH=a2a_invoke`
- **Baseline:** Stored in `benchmarks/a2a_invoke_baseline_main.json`. The commit used as baseline is hardcoded in `test_a2a_invoke_benchmark.py` (`A2A_INVOKE_MAIN_BASELINE_COMMIT`) so it does not change when main moves.
- **Refresh baseline from main:** Stash your changes, checkout main (or the baseline commit), pop the benchmark files, run `SAVE_A2A_INVOKE_BASELINE=1 make bench a2a_invoke`, then checkout back and restore. Commit the updated `benchmarks/a2a_invoke_baseline_main.json`.
