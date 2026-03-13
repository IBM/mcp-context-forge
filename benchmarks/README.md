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
| Rust vs Python A2A | `crates/gateway_rs/services/a2a_service/compare_performance.py` | real A2A invoke comparison: production Rust queue vs current Python fallback, including larger I/O-heavy scenarios and `>=2x` / `>=5x` / `>=10x` speedup tiers |

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

# A2A-specific comparison
make benchmark-a2a

# A2A full/custom comparison including JSON report
uv run python3 crates/gateway_rs/services/a2a_service/compare_performance.py \
  --output benchmarks/reports/a2a_service_compare.json
```

Latency assumptions used by the A2A comparison:

| Scenario type | Typical latency |
| --- | --- |
| Fast synchronous tool-like agent | ~50-200 ms |
| Typical production A2A request | ~100-800 ms |
| Agent calling an LLM or complex pipeline | 1-5+ seconds |
| Long-running task (async with streaming/polling) | seconds to minutes |

`single` intentionally stays near-zero-latency to measure fixed invoke overhead. The multi-request scenarios are latency-bearing and map to the assumptions above.

## A2A comparison

Use the dedicated A2A benchmark command for the supported default suite:

- Run `make benchmark-a2a` for the curated production-shaped A2A Rust vs Python comparison.
- Run the script directly when you need custom `--scenario` flags or `--output benchmarks/reports/a2a_service_compare.json`.
- The suite includes both pre-batched requests and a `singles_128_typical` scenario to verify how the Rust queue behaves when 128 requests arrive as separate single invokes.
