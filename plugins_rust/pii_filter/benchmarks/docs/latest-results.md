# Rust PII Filter Performance Benchmark Results
================================================================================

**Date**: 2025-10-14
**Average Speedup**: 34.5x
**Rating**: 🚀 EXCELLENT (>10x speedup - Highly recommended)

## Detailed Results

### Single Ssn

| Metric | Python | Rust | Improvement |
|--------|--------|------|-------------|
| **Avg Latency** | 0.0081 ms | 0.0009 ms | **9.1x** |
| **Median (p50)** | 0.0079 ms | 0.0009 ms | 9.0x |
| **p95 Latency** | 0.0082 ms | 0.0009 ms | 9.0x |
| **p99 Latency** | 0.0149 ms | 0.0010 ms | 15.0x |
| **Min Latency** | 0.0077 ms | 0.0009 ms | 9.1x |
| **Max Latency** | 0.0373 ms | 0.0027 ms | 13.6x |
| **StdDev** | 0.0018 ms | 0.0001 ms | 23.9x |
| **Throughput** | 2.46 MB/s | 22.40 MB/s | 9.1x |
| **Ops/sec** | 122,831 | 1,118,465 | 9.1x |

### Single Email

| Metric | Python | Rust | Improvement |
|--------|--------|------|-------------|
| **Avg Latency** | 0.0126 ms | 0.0007 ms | **17.1x** |
| **Median (p50)** | 0.0124 ms | 0.0007 ms | 16.9x |
| **p95 Latency** | 0.0127 ms | 0.0008 ms | 16.8x |
| **p99 Latency** | 0.0247 ms | 0.0008 ms | 31.2x |
| **Min Latency** | 0.0121 ms | 0.0007 ms | 17.1x |
| **Max Latency** | 0.0490 ms | 0.0043 ms | 11.5x |
| **StdDev** | 0.0019 ms | 0.0001 ms | 17.1x |
| **Throughput** | 4.15 MB/s | 71.07 MB/s | 17.1x |
| **Ops/sec** | 79,121 | 1,354,916 | 17.1x |

### Multiple Types

| Metric | Python | Rust | Improvement |
|--------|--------|------|-------------|
| **Avg Latency** | 0.0246 ms | 0.0034 ms | **7.2x** |
| **Median (p50)** | 0.0240 ms | 0.0033 ms | 7.2x |
| **p95 Latency** | 0.0261 ms | 0.0034 ms | 7.6x |
| **p99 Latency** | 0.0408 ms | 0.0037 ms | 11.0x |
| **Min Latency** | 0.0235 ms | 0.0032 ms | 7.3x |
| **Max Latency** | 0.0843 ms | 0.0319 ms | 2.6x |
| **StdDev** | 0.0031 ms | 0.0012 ms | 2.7x |
| **Throughput** | 3.22 MB/s | 23.09 MB/s | 7.2x |
| **Ops/sec** | 40,698 | 291,695 | 7.2x |

### No Pii

| Metric | Python | Rust | Improvement |
|--------|--------|------|-------------|
| **Avg Latency** | 0.0598 ms | 0.0006 ms | **92.7x** |
| **Median (p50)** | 0.0590 ms | 0.0006 ms | 93.5x |
| **p95 Latency** | 0.0645 ms | 0.0006 ms | 100.4x |
| **p99 Latency** | 0.0759 ms | 0.0007 ms | 107.6x |
| **Min Latency** | 0.0580 ms | 0.0006 ms | 93.4x |
| **Max Latency** | 0.1000 ms | 0.0132 ms | 7.6x |
| **StdDev** | 0.0035 ms | 0.0004 ms | 8.8x |
| **Throughput** | 5.66 MB/s | 525.01 MB/s | 92.7x |
| **Ops/sec** | 16,721 | 1,550,750 | 92.7x |

### Full Workflow

| Metric | Python | Rust | Improvement |
|--------|--------|------|-------------|
| **Avg Latency** | 0.0266 ms | 0.0034 ms | **7.7x** |
| **Median (p50)** | 0.0261 ms | 0.0034 ms | 7.7x |
| **p95 Latency** | 0.0287 ms | 0.0035 ms | 8.3x |
| **p99 Latency** | 0.0473 ms | 0.0039 ms | 12.3x |
| **Min Latency** | 0.0252 ms | 0.0032 ms | 7.8x |
| **Max Latency** | 0.0518 ms | 0.0191 ms | 2.7x |
| **StdDev** | 0.0031 ms | 0.0008 ms | 3.6x |
| **Throughput** | 2.79 MB/s | 21.61 MB/s | 7.7x |
| **Ops/sec** | 37,561 | 290,559 | 7.7x |

### Large 100

| Metric | Python | Rust | Improvement |
|--------|--------|------|-------------|
| **Avg Latency** | 7.6942 ms | 0.2798 ms | **27.5x** |
| **Median (p50)** | 7.6553 ms | 0.2765 ms | 27.7x |
| **p95 Latency** | 7.7237 ms | 0.3072 ms | 25.1x |
| **p99 Latency** | 9.3897 ms | 0.3152 ms | 29.8x |
| **Min Latency** | 7.5973 ms | 0.2435 ms | 31.2x |
| **Max Latency** | 9.3897 ms | 0.3152 ms | 29.8x |
| **StdDev** | 0.2279 ms | 0.0159 ms | 14.3x |
| **Throughput** | 0.91 MB/s | 25.15 MB/s | 27.5x |
| **Ops/sec** | 130 | 3,574 | 27.5x |

### Large 500

| Metric | Python | Rust | Improvement |
|--------|--------|------|-------------|
| **Avg Latency** | 230.2317 ms | 3.7542 ms | **61.3x** |
| **Median (p50)** | 230.2783 ms | 3.5774 ms | 64.4x |
| **p95 Latency** | 231.5771 ms | 6.3628 ms | 36.4x |
| **p99 Latency** | 231.5771 ms | 6.3628 ms | 36.4x |
| **Min Latency** | 229.0035 ms | 2.8334 ms | 80.8x |
| **Max Latency** | 231.5771 ms | 6.3628 ms | 36.4x |
| **StdDev** | 0.8734 ms | 0.8030 ms | 1.1x |
| **Throughput** | 0.16 MB/s | 9.60 MB/s | 61.3x |
| **Ops/sec** | 4 | 266 | 61.3x |

### Large 1000

| Metric | Python | Rust | Improvement |
|--------|--------|------|-------------|
| **Avg Latency** | 958.4703 ms | 12.3620 ms | **77.5x** |
| **Median (p50)** | 963.5689 ms | 12.9657 ms | 74.3x |
| **p95 Latency** | 989.0099 ms | 14.2919 ms | 69.2x |
| **p99 Latency** | 989.0099 ms | 14.2919 ms | 69.2x |
| **Min Latency** | 937.0376 ms | 9.3450 ms | 100.3x |
| **Max Latency** | 989.0099 ms | 14.2919 ms | 69.2x |
| **StdDev** | 16.0311 ms | 1.7240 ms | 9.3x |
| **Throughput** | 0.08 MB/s | 5.85 MB/s | 77.5x |
| **Ops/sec** | 1 | 81 | 77.5x |

### Realistic Payload

| Metric | Python | Rust | Improvement |
|--------|--------|------|-------------|
| **Avg Latency** | 0.1062 ms | 0.0103 ms | **10.3x** |
| **Median (p50)** | 0.1038 ms | 0.0101 ms | 10.2x |
| **p95 Latency** | 0.1229 ms | 0.0104 ms | 11.8x |
| **p99 Latency** | 0.1327 ms | 0.0164 ms | 8.1x |
| **Min Latency** | 0.1007 ms | 0.0098 ms | 10.2x |
| **Max Latency** | 0.1406 ms | 0.0320 ms | 4.4x |
| **StdDev** | 0.0068 ms | 0.0017 ms | 4.0x |
| **Throughput** | 3.83 MB/s | 39.37 MB/s | 10.3x |
| **Ops/sec** | 9,420 | 96,907 | 10.3x |


## Key Insights

### Latency Consistency

Rust shows significantly lower standard deviation across all tests:

- **single_ssn**: Python CV=21.9%, Rust CV=8.3% (2.6x more consistent)
- **single_email**: Python CV=15.3%, Rust CV=15.3% (1.0x more consistent)
- **multiple_types**: Python CV=12.8%, Rust CV=33.9% (0.4x more consistent)

### Tail Latency (p99)

Rust maintains excellent p99 latency even under load:

- **single_ssn**: Python p99/p50=1.9x, Rust p99/p50=1.1x
- **single_email**: Python p99/p50=2.0x, Rust p99/p50=1.1x
- **multiple_types**: Python p99/p50=1.7x, Rust p99/p50=1.1x

### Throughput Scaling

Performance improvement increases with dataset size:

- **100 instances**: 27.5x speedup, 3,574 ops/sec
- **500 instances**: 61.3x speedup, 266 ops/sec
- **1000 instances**: 77.5x speedup, 81 ops/sec
