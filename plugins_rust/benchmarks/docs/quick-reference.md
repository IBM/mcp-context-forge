# Benchmark Quick Reference Card

Quick command reference for running and interpreting PII filter benchmarks.

## Quick Commands

```bash
# Basic benchmark (default settings)
python benchmarks/compare_pii_filter.py

# Detailed latency statistics
python benchmarks/compare_pii_filter.py --detailed

# Custom dataset sizes
python benchmarks/compare_pii_filter.py --sizes 100 500 1000

# Save JSON results
python benchmarks/compare_pii_filter.py --output results.json

# Complete run with all options
python benchmarks/compare_pii_filter.py --sizes 100 500 1000 --detailed --output results.json
```

## Understanding Output

### Latency Metrics Explained

```
Python:
  Avg:    0.008 ms | Median: 0.008 ms     ← Mean vs typical value
  p95:    0.008 ms | p99:    0.015 ms     ← 95% and 99% of requests faster
  Min:    0.008 ms | Max:    0.027 ms     ← Best and worst case
  StdDev: 0.001 ms                        ← Consistency (lower = better)
  Throughput: 2.52 MB/s | 124,098 ops/sec ← Data rate and capacity
```

### What to Look For

✅ **Good Performance**:
- Low average latency
- Median ≈ Average (consistent performance)
- p99 < 2x median (good tail latency)
- Low standard deviation (predictable)
- High ops/sec (high capacity)

⚠️ **Issues to Investigate**:
- High standard deviation (>50% of average)
- p99 > 5x median (tail latency problems)
- Large gap between min and max
- Declining ops/sec with larger datasets

### Performance Ratings

| Speedup | Rating | Meaning |
|---------|--------|---------|
| >10x | 🚀 EXCELLENT | Production-critical upgrade |
| 5-10x | ✓ GREAT | Highly recommended |
| 3-5x | ✓ GOOD | Worthwhile improvement |
| 2-3x | ✓ MODERATE | Consider for scale |
| <2x | ⚠ MINIMAL | Evaluate ROI |

## Percentile Interpretation

### p95 (95th Percentile)
- **Meaning**: 95% of requests complete faster
- **SLA Use**: Common target (e.g., "p95 < 100ms")
- **Scale**: At 1M requests/day, 50,000 requests exceed p95

### p99 (99th Percentile)
- **Meaning**: 99% of requests complete faster
- **SLA Use**: User experience target
- **Scale**: At 1M requests/day, 10,000 requests exceed p99

### Tail Latency Ratio (p99/p50)
- **1.0-1.5x**: Excellent consistency
- **1.5-2.0x**: Good, acceptable variation
- **2.0-5.0x**: Moderate, monitor for issues
- **>5.0x**: Poor, investigate causes

## Typical Results

### Single Item Detection
- **Python**: ~0.008-0.025 ms
- **Rust**: ~0.001-0.004 ms
- **Speedup**: 7-18x
- **Use Case**: Real-time API filtering

### Large Dataset (1000 items)
- **Python**: ~900-1000 ms
- **Rust**: ~10-15 ms
- **Speedup**: 70-80x
- **Use Case**: Batch processing

### No PII (Best Case)
- **Python**: ~0.060 ms
- **Rust**: ~0.001 ms
- **Speedup**: 90-100x
- **Use Case**: Clean text scanning

## Production Capacity Estimation

### Single Core Capacity

**Python Implementation** (~40K ops/sec):
```
40,000 ops/sec × 86,400 sec/day = 3.5 billion ops/day
At 1KB per request: 3.5 TB/day
```

**Rust Implementation** (~300K ops/sec):
```
300,000 ops/sec × 86,400 sec/day = 26 billion ops/day
At 1KB per request: 26 TB/day
```

### Multi-Core Server (16 cores)

**Python** (with 50% utilization headroom):
- Capacity: 28 billion ops/day
- Throughput: 28 TB/day

**Rust** (with 50% utilization headroom):
- Capacity: 207 billion ops/day
- Throughput: 207 TB/day

## Cost Savings Example

**Workload**: 100 million requests/day

**Python Infrastructure**:
- Cores needed: 100M / (40K × 86,400) ≈ 29 cores
- Servers (16-core): 2 servers
- AWS c5.4xlarge cost: $1,200/month

**Rust Infrastructure**:
- Cores needed: 100M / (300K × 86,400) ≈ 4 cores
- Servers (16-core): 1 server
- AWS c5.4xlarge cost: $600/month

**Annual Savings**: $7,200 per 100M requests/day

## Troubleshooting

### "Rust implementation not available"
```bash
# Check installation
python -c "from plugins_rust import PIIDetectorRust; print('✓ OK')"

# Reinstall if needed
cd plugins_rust && make clean && make build
```

### High variance in results
```bash
# Increase warmup iterations (edit benchmark script)
# Pin to specific CPU cores
taskset -c 0-3 python benchmarks/compare_pii_filter.py

# Disable CPU frequency scaling (requires root)
sudo cpupower frequency-set -g performance
```

### Benchmark takes too long
```bash
# Reduce dataset sizes
python benchmarks/compare_pii_filter.py --sizes 100 500

# Reduce iterations (edit script)
# Default: 1000 iterations for small tests, 100 for large
```

## JSON Output Schema

```json
{
  "name": "benchmark_name_python",
  "implementation": "Python",
  "duration_ms": 0.008,           // Average latency
  "throughput_mb_s": 2.52,        // Megabytes per second
  "operations": 1000,              // Number of iterations
  "text_size_bytes": 21,          // Input size
  "min_ms": 0.007,                // Fastest execution
  "max_ms": 0.027,                // Slowest execution
  "median_ms": 0.008,             // 50th percentile (p50)
  "p95_ms": 0.008,                // 95th percentile
  "p99_ms": 0.015,                // 99th percentile
  "stddev_ms": 0.001,             // Standard deviation
  "ops_per_sec": 124098.0         // Operations per second
}
```

## Comparing with Baseline

```bash
# Create baseline
python benchmarks/compare_pii_filter.py --output baseline.json

# After changes
python benchmarks/compare_pii_filter.py --output current.json

# Quick comparison
python -c "
import json
with open('baseline.json') as f: baseline = json.load(f)
with open('current.json') as f: current = json.load(f)

for b, c in zip(baseline, current):
    if b['name'] == c['name']:
        ratio = c['duration_ms'] / b['duration_ms']
        change = ((ratio - 1.0) * 100)
        status = '⚠️ SLOWER' if ratio > 1.1 else '✓ OK' if ratio > 0.9 else '🚀 FASTER'
        print(f'{b[\"name\"]}: {change:+.1f}% {status}')
"
```

## SLA Planning

### Define Requirements
```
Target: p95 < 50ms, p99 < 100ms
Budget: 50ms total (network + processing)
```

### Calculate Processing Budget
```
Network latency: 10-30ms typical
Processing budget: 50ms - 30ms = 20ms

Python p95: 0.008ms → fits easily
Rust p95: 0.001ms → fits easily, leaves more headroom
```

### Scale Calculation
```
At 10,000 requests/sec:
- 500 requests/sec exceed p95 (5%)
- 100 requests/sec exceed p99 (1%)

With Rust p99=0.015ms:
- 99.9% meet 50ms SLA even with 30ms network latency
```

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Performance Benchmark
on: [push, pull_request]
jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: make venv install-dev
      - run: cd plugins_rust && make build
      - run: python benchmarks/compare_pii_filter.py --output results.json
      - uses: actions/upload-artifact@v3
        with:
          name: benchmark-results
          path: results.json
```

## See Also

- **Full Guide**: [BENCHMARKING.md](BENCHMARKING.md)
- **Detailed Results**: [DETAILED_RESULTS.md](DETAILED_RESULTS.md)
- **Rust Plugins**: [../docs/docs/using/plugins/rust-plugins.md](../docs/docs/using/plugins/rust-plugins.md)
- **Quickstart**: [../plugins_rust/QUICKSTART.md](../plugins_rust/QUICKSTART.md)
