# PII Filter Benchmarking Guide

Comprehensive guide to benchmarking Python vs Rust PII filter implementations with detailed latency metrics.

## 📁 Directory Structure

```
benchmarks/
├── README.md                    # This file - Benchmarking guide
├── compare_pii_filter.py        # Main benchmark script
├── results/                     # Benchmark results (JSON)
│   ├── latest.json             # Most recent run
│   └── baseline.json           # Reference baseline
└── docs/                        # Additional documentation
    ├── quick-reference.md      # Quick command reference
    └── latest-results.md       # Latest benchmark results
```

## Quick Start

```bash
# Activate virtual environment
source ~/.venv/mcpgateway/bin/activate

# Run basic benchmark
python benchmarks/compare_pii_filter.py

# Run with detailed latency statistics
python benchmarks/compare_pii_filter.py --detailed

# Run with custom dataset sizes
python benchmarks/compare_pii_filter.py --sizes 100 500 1000 5000

# Save results to JSON
python benchmarks/compare_pii_filter.py --output results/latest.json

# Combined options
python benchmarks/compare_pii_filter.py --sizes 100 500 --detailed --output results/latest.json
```

## Understanding the Metrics

### Latency Metrics

The benchmark now provides comprehensive latency statistics beyond simple averages:

#### Average (Avg)
- **What**: Mean execution time across all iterations
- **Use**: General performance indicator
- **Example**: `0.008 ms` - Average time to process one request

#### Median (p50)
- **What**: 50th percentile - middle value when sorted
- **Use**: Better representation of "typical" performance than average
- **Why Important**: Not affected by outliers like average is
- **Example**: `0.008 ms` - Half of requests complete faster, half slower

#### p95 (95th Percentile)
- **What**: 95% of requests complete faster than this time
- **Use**: Understanding tail latency for SLA planning
- **Production Significance**: Common SLA target (e.g., "p95 < 100ms")
- **Example**: `0.008 ms` - Only 5% of requests are slower than this

#### p99 (99th Percentile)
- **What**: 99% of requests complete faster than this time
- **Use**: Understanding worst-case performance for most users
- **Production Significance**: Critical for user experience at scale
- **Example**: `0.015 ms` - Only 1% of requests are slower than this
- **At Scale**: At 1M requests/day, p99 affects 10,000 requests

#### Min/Max
- **What**: Fastest and slowest single execution
- **Use**: Understanding performance bounds
- **Min**: Best-case performance (often cached or optimized path)
- **Max**: Worst-case (cold start, GC pauses, OS scheduling)

#### Standard Deviation (StdDev)
- **What**: Measure of variation in execution times
- **Use**: Performance consistency indicator
- **Low StdDev**: Predictable, consistent performance
- **High StdDev**: Variable performance, potential issues
- **Example**: `0.001 ms` - Very consistent performance

### Throughput Metrics

#### MB/s (Megabytes per second)
- **What**: Data processing rate
- **Use**: Comparing bulk data processing efficiency
- **Example**: `21.04 MB/s` - Can process 21MB of text per second
- **Scale**: At this rate, process 1.8GB/day per core

#### ops/sec (Operations per second)
- **What**: Request handling capacity
- **Use**: Capacity planning and scalability estimation
- **Example**: `1,050,760 ops/sec` - Over 1 million operations per second
- **Scale**: At this rate, handle 90 billion requests/day per core

### Speedup Metrics

#### Overall Speedup
- **What**: Average time ratio (Python time / Rust time)
- **Use**: General performance improvement
- **Example**: `8.5x faster` - Rust is 8.5 times faster on average

#### Latency Improvement
- **What**: Median latency ratio
- **Use**: Better representation of user-perceived improvement
- **Why Different**: Uses median instead of average, less affected by outliers
- **Example**: `8.6x` - Typical request is 8.6 times faster

## Benchmark Scenarios

### 1. Single SSN Detection
**Test**: Detect one Social Security Number in minimal text
**Purpose**: Measure overhead of detection engine
**Typical Results**:
- Python: ~0.008 ms (125K ops/sec)
- Rust: ~0.001 ms (1M ops/sec)
- Speedup: ~8-10x

### 2. Single Email Detection
**Test**: Detect one email address in typical sentence
**Purpose**: Measure pattern matching efficiency
**Typical Results**:
- Python: ~0.013 ms (77K ops/sec)
- Rust: ~0.001 ms (1.4M ops/sec)
- Speedup: ~15-20x

### 3. Multiple PII Types
**Test**: Detect SSN, email, phone, IP in one text
**Purpose**: Measure multi-pattern performance
**Typical Results**:
- Python: ~0.025 ms (40K ops/sec)
- Rust: ~0.004 ms (280K ops/sec)
- Speedup: ~7-8x

### 4. No PII Detection (Best Case)
**Test**: Scan clean text without any PII
**Purpose**: Measure fast-path optimization
**Typical Results**:
- Python: ~0.060 ms (17K ops/sec)
- Rust: ~0.001 ms (1.6M ops/sec)
- Speedup: ~90-100x
**Note**: Rust's RegexSet enables O(M) instead of O(N×M) complexity

### 5. Detection + Masking (Full Workflow)
**Test**: Detect PII and apply masking
**Purpose**: Measure end-to-end pipeline performance
**Typical Results**:
- Python: ~0.027 ms (37K ops/sec)
- Rust: ~0.003 ms (287K ops/sec)
- Speedup: ~7-8x

### 6. Nested Data Structure
**Test**: Process nested JSON with multiple PII instances
**Purpose**: Measure recursive processing efficiency
**Note**: Python and Rust have different APIs for this

### 7. Large Text Performance
**Test**: Process 100, 500, 1000, 5000 PII instances
**Purpose**: Measure scaling characteristics
**Typical Results**:
- 100 instances: ~27x speedup
- 500 instances: ~65x speedup
- 1000 instances: ~77x speedup
- 5000 instances: ~80-90x speedup
**Observation**: Rust advantage increases with scale

### 8. Realistic API Payload
**Test**: Process typical API request with user data
**Purpose**: Simulate production workload
**Typical Results**:
- Python: ~0.104 ms (39K ops/sec)
- Rust: ~0.010 ms (400K ops/sec)
- Speedup: ~10x

## Interpreting Results

### Performance Categories

Based on average speedup:

- **🚀 EXCELLENT (>10x)**: Highly recommended for production
  - Dramatic performance improvement
  - Significant cost savings at scale
  - Reduced latency for user-facing APIs

- **✓ GREAT (5-10x)**: Recommended for production
  - Substantial performance gain
  - Worthwhile for high-volume services
  - Noticeable user experience improvement

- **✓ GOOD (3-5x)**: Noticeable improvement
  - Meaningful performance boost
  - Consider for performance-critical paths
  - Cost-effective at medium scale

- **✓ MODERATE (2-3x)**: Worthwhile upgrade
  - Measurable improvement
  - Useful for optimization efforts
  - Evaluate ROI based on scale

- **⚠ MINIMAL (<2x)**: May not justify complexity
  - Limited performance gain
  - Consider other optimizations first
  - May not offset integration costs

### Latency Analysis

#### Consistent Performance (Low StdDev)
```
StdDev: 0.001 ms (relative to avg: 0.008 ms = 12.5%)
```
- Performance is predictable
- Suitable for latency-sensitive applications
- Can confidently set SLAs

#### Variable Performance (High StdDev)
```
StdDev: 0.025 ms (relative to avg: 0.050 ms = 50%)
```
- Performance varies significantly
- May indicate:
  - GC pauses (Python)
  - OS scheduling variability
  - Cache effects
  - Thermal throttling
- Consider:
  - Increasing warmup iterations
  - Running on isolated CPU cores
  - Analyzing p99 for SLA planning

#### Tail Latency (p95/p99)
```
Avg:  1.0 ms
p95:  1.5 ms  (1.5x avg)
p99:  5.0 ms  (5x avg)
```
- **Good**: p99 < 2x average
- **Acceptable**: p99 < 5x average
- **Concerning**: p99 > 10x average

**What to do if p99 is high**:
1. Check for GC pauses (Python)
2. Increase warmup iterations
3. Use process pinning (`taskset`)
4. Disable CPU frequency scaling
5. Check system load during benchmark

## Production Implications

### Capacity Planning

Given benchmark results, calculate capacity:

**Example**: Rust PII filter at 1M ops/sec per core

```
Single Core Capacity:
- 1,000,000 ops/sec × 86,400 seconds/day = 86.4 billion ops/day
- At 1KB avg request: 86.4 TB/day throughput

16-Core Server Capacity:
- 16 × 86.4 billion = 1.4 trillion ops/day
- At 1KB avg request: 1.4 PB/day throughput

Realistic Capacity (50% utilization for headroom):
- 700 billion ops/day per 16-core server
- 700 TB/day throughput
```

### Cost Analysis

**Example**: Processing 100M requests/day

**Python Implementation**:
- Throughput: ~40K ops/sec per core
- Cores needed: 100M / (40K × 86400) ≈ 29 cores
- Servers needed (16-core): 2 servers
- Cloud cost (c5.4xlarge × 2): ~$1,200/month

**Rust Implementation**:
- Throughput: ~280K ops/sec per core
- Cores needed: 100M / (280K × 86400) ≈ 4 cores
- Servers needed (16-core): 1 server
- Cloud cost (c5.4xlarge × 1): ~$600/month

**Savings**: $600/month = $7,200/year per 100M requests/day

### Latency SLAs

Based on p95 latency metrics:

**Python**:
- p95: ~0.030 ms internal processing
- Network overhead: ~10-50 ms
- Total p95: ~10-50 ms realistic SLA

**Rust**:
- p95: ~0.004 ms internal processing
- Network overhead: ~10-50 ms
- Total p95: ~10-50 ms realistic SLA

**Advantage**: Rust leaves more latency budget for network/business logic

## Advanced Benchmarking

### Custom Iterations

Adjust iteration counts for different scenarios:

```python
# Quick smoke test
iterations = 100

# Standard benchmark (default)
iterations = 1000

# High-precision measurement
iterations = 10000

# Very large dataset (reduce iterations)
iterations = 10
```

### Profiling Integration

Combine with Python profilers:

```bash
# cProfile
python -m cProfile -o profile.stats benchmarks/compare_pii_filter.py

# py-spy (live profiling)
py-spy record -o profile.svg -- python benchmarks/compare_pii_filter.py

# memory_profiler
mprof run benchmarks/compare_pii_filter.py
mprof plot
```

### Continuous Benchmarking

Set up CI/CD benchmarking:

```yaml
# .github/workflows/benchmark.yml
name: Performance Benchmarks
on: [push, pull_request]
jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run benchmarks
        run: |
          make venv install-dev
          python benchmarks/compare_pii_filter.py --output results.json
      - name: Compare with baseline
        run: |
          python scripts/compare_benchmarks.py baseline.json results.json
```

### Regression Detection

Compare benchmark results over time:

```bash
# Baseline
python benchmarks/compare_pii_filter.py --output baseline.json

# After changes
python benchmarks/compare_pii_filter.py --output current.json

# Compare
python -c "
import json
with open('baseline.json') as f: baseline = json.load(f)
with open('current.json') as f: current = json.load(f)

for b, c in zip(baseline, current):
    if b['name'] == c['name']:
        ratio = c['duration_ms'] / b['duration_ms']
        status = '⚠️ SLOWER' if ratio > 1.1 else '✓ OK'
        print(f'{b[\"name\"]}: {ratio:.2f}x {status}')
"
```

## Troubleshooting

### Benchmark Shows No Speedup

**Check 1**: Verify Rust plugin is installed
```bash
python -c "from plugins_rust import PIIDetectorRust; print('✓ Rust available')"
```

**Check 2**: Check which implementation is being used
```bash
python -c "
from plugins.pii_filter.pii_filter import PIIFilterPlugin
from plugins.framework import PluginConfig
config = PluginConfig(name='test', kind='test', config={})
plugin = PIIFilterPlugin(config)
print(f'Using: {plugin.implementation}')
"
```

**Check 3**: Rebuild Rust plugin
```bash
cd plugins_rust && make clean && make build
```

### High Variance in Results

**Solution 1**: Increase warmup iterations
```python
# In measure_time() method, increase from 10 to 100
for _ in range(100):  # More warmup
    func(*args)
```

**Solution 2**: Run on isolated CPU
```bash
# Pin to specific cores
taskset -c 0-3 python benchmarks/compare_pii_filter.py
```

**Solution 3**: Disable CPU frequency scaling
```bash
# Requires root
sudo cpupower frequency-set -g performance
```

### Benchmark Takes Too Long

**Solution 1**: Reduce dataset sizes
```bash
python benchmarks/compare_pii_filter.py --sizes 100 500
```

**Solution 2**: Reduce iteration count
Edit the script to lower default iterations from 1000 to 100.

**Solution 3**: Skip specific tests
Modify `run_all_benchmarks()` to comment out tests you don't need.

## Best Practices

### 1. Run Multiple Times
```bash
for i in {1..5}; do
  python benchmarks/compare_pii_filter.py --output "run_$i.json"
done
```

### 2. Stable Environment
- Close other applications
- Disconnect from network (optional)
- Disable CPU frequency scaling
- Use dedicated benchmark machine

### 3. Version Control Results
```bash
git add benchmarks/results_$(date +%Y%m%d).json
git commit -m "benchmark: baseline for v0.9.0"
```

### 4. Document System Info
```bash
python benchmarks/compare_pii_filter.py --output results.json

# Add system info to results
python -c "
import json, platform, psutil
with open('results.json') as f: data = json.load(f)
metadata = {
  'system': {
    'platform': platform.platform(),
    'python': platform.python_version(),
    'cpu': platform.processor(),
    'cores': psutil.cpu_count(),
    'memory': psutil.virtual_memory().total,
  },
  'results': data
}
with open('results_annotated.json', 'w') as f:
  json.dump(metadata, f, indent=2)
"
```

## Reference

### Command-Line Options

```
usage: compare_pii_filter.py [-h] [--sizes SIZES [SIZES ...]]
                             [--output OUTPUT] [--detailed]

Compare Python vs Rust PII filter performance

optional arguments:
  -h, --help            show this help message and exit
  --sizes SIZES [SIZES ...]
                        Sizes for large text benchmark (default: [100, 500, 1000, 5000])
  --output OUTPUT       Save results to JSON file
  --detailed            Show detailed latency statistics (enables verbose output)
```

### Output JSON Schema

```json
{
  "name": "single_ssn_python",
  "implementation": "Python",
  "duration_ms": 0.008,
  "throughput_mb_s": 2.52,
  "operations": 1000,
  "text_size_bytes": 21,
  "min_ms": 0.007,
  "max_ms": 0.027,
  "median_ms": 0.008,
  "p95_ms": 0.008,
  "p99_ms": 0.015,
  "stddev_ms": 0.001,
  "ops_per_sec": 124098.0
}
```

## See Also

- [Quick Reference](docs/quick-reference.md) - Command cheat sheet
- [Latest Results](docs/latest-results.md) - Most recent benchmark results
- [Rust Plugins Documentation](../../docs/docs/using/plugins/rust-plugins.md) - User guide
- [Build and Test Results](../docs/build-and-test.md) - Test coverage
- [Quickstart Guide](../QUICKSTART.md) - Getting started
- [Plugin Framework](../../docs/docs/using/plugins/index.md) - Plugin system overview

## Support

For issues or questions about benchmarking:
- Open an issue: https://github.com/anthropics/mcp-context-forge/issues
- Check existing benchmarks in CI/CD
- Review build results in `../docs/build-and-test.md`
