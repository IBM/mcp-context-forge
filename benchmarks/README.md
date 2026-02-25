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
