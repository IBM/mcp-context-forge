# LLMGuard Grafana Dashboard

This document describes the Grafana dashboard for monitoring LLMGuard plugin metrics.

## Overview

The LLMGuard Grafana dashboard provides comprehensive monitoring and visualization of the LLMGuard plugin's performance, cache efficiency, and scanner operations.

## Metrics Collected

The dashboard visualizes the following Prometheus metrics from `llmguardplugin/llmguard.py`:

### 1. Scan Duration Metrics
- **Metric**: `llm_guard_scan_duration_seconds`
- **Type**: Histogram
- **Labels**: 
  - `scan_type`: "input" or "output"
  - `scanner_category`: "filters" or "sanitizers"
- **Buckets**: 0.005s to 10s
- **Description**: Tracks the duration of LLM Guard scans

### 2. Levenshtein Distance Calculation
- **Metric**: `llm_guard_levenshtein_duration_seconds`
- **Type**: Histogram
- **Labels**: 
  - `comparison_type`: "input_anonymize" or "input_deanonymize"
- **Buckets**: 0.001s to 5s
- **Description**: Measures time spent calculating Levenshtein distance for vault leak detection

### 3. Cache Hit Rate
- **Metric**: `llm_guard_cache_hits`
- **Type**: Histogram
- **Labels**: 
  - `scan_type`: "input_filters" or "output_filters"
- **Values**: 0 (miss) or 1 (hit)
- **Description**: Tracks cache hit/miss events

### 4. Cache Size
- **Metric**: `llm_guard_cache_size`
- **Type**: Histogram
- **Labels**: 
  - `scan_type`: Type of scan being cached
- **Buckets**: 0 to 10,000 entries
- **Description**: Current number of entries in the result cache

### 5. Cache Misses
- **Metric**: `llm_guard_cache_misses_total`
- **Type**: Counter
- **Labels**: 
  - `scan_type`: Type of scan
- **Description**: Total count of cache misses

## Dashboard Panels

### 1. Average Scan Duration by Type
- **Type**: Time series
- **Description**: Shows average scan duration for input/output filters and sanitizers
- **Query**: `rate(llm_guard_scan_duration_seconds_sum[5m]) / rate(llm_guard_scan_duration_seconds_count[5m])`

### 2. P95 Scan Duration
- **Type**: Gauge
- **Description**: 95th percentile of scan duration (performance SLA indicator)
- **Query**: `histogram_quantile(0.95, rate(llm_guard_scan_duration_seconds_bucket[5m]))`
- **Thresholds**: 
  - Green: < 0.5s
  - Yellow: 0.5s - 1s
  - Red: > 1s

### 3. Scan Throughput
- **Type**: Gauge
- **Description**: Total scan operations per second
- **Query**: `sum(rate(llm_guard_scan_duration_seconds_count[5m]))`

### 4. Cache Hit Rate
- **Type**: Time series
- **Description**: Percentage of cache hits for input and output filters
- **Query**: `rate(llm_guard_cache_hits_sum[5m]) / (rate(llm_guard_cache_hits_count[5m]) + rate(llm_guard_cache_misses_total[5m]))`

### 5. Cache Size
- **Type**: Time series
- **Description**: Current size of the result cache
- **Query**: `llm_guard_cache_size_sum / llm_guard_cache_size_count`

### 6. Cache Misses Rate
- **Type**: Time series
- **Description**: Rate of cache misses per second
- **Query**: `rate(llm_guard_cache_misses_total[5m])`

### 7. Levenshtein Distance Calculation Duration
- **Type**: Time series
- **Description**: Time spent on Levenshtein distance calculations for vault leak detection
- **Query**: `rate(llm_guard_levenshtein_duration_seconds_sum[5m]) / rate(llm_guard_levenshtein_duration_seconds_count[5m])`

### 8. Scanner Performance Summary
- **Type**: Table
- **Description**: Comprehensive table showing count, average, P95, and P99 durations for each scanner
- **Columns**:
  - Scan Type
  - Scanner Category
  - Count (ops/s)
  - Avg Duration
  - P95 Duration
  - P99 Duration

### 9. Scanner Usage Distribution
- **Type**: Pie chart
- **Description**: Distribution of scanner usage by category
- **Query**: `sum by (scanner_category) (rate(llm_guard_scan_duration_seconds_count[5m]))`

### 10. Scan Duration Percentiles
- **Type**: Bar chart
- **Description**: P50, P90, P95, and P99 percentiles for scan duration
- **Queries**: `histogram_quantile(0.50|0.90|0.95|0.99, sum by (le) (rate(llm_guard_scan_duration_seconds_bucket[5m])))`

## Installation

### Prerequisites
- Grafana 10.0.0 or later
- Prometheus data source configured
- LLMGuard plugin running with metrics exposed

### Import Dashboard

1. **Via Grafana UI**:
   ```bash
   # Navigate to Grafana
   # Go to Dashboards → Import
   # Upload grafana-dashboard.json
   ```

2. **Via API**:
   ```bash
   curl -X POST \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d @grafana-dashboard.json \
     http://your-grafana-instance/api/dashboards/db
   ```

3. **Via Provisioning**:
   ```yaml
   # /etc/grafana/provisioning/dashboards/llmguard.yaml
   apiVersion: 1
   providers:
     - name: 'LLMGuard'
       orgId: 1
       folder: 'Security'
       type: file
       disableDeletion: false
       updateIntervalSeconds: 10
       allowUiUpdates: true
       options:
         path: /path/to/grafana-dashboard.json
   ```

### Configure Prometheus Data Source

1. In Grafana, go to **Configuration → Data Sources**
2. Add a Prometheus data source
3. Set the URL to your Prometheus instance (e.g., `http://localhost:9090`)
4. Click **Save & Test**

## Metrics Endpoint

The LLMGuard plugin exposes metrics via the LLMGuardPlugin's metrics endpoint:

```bash
# Default metrics endpoint
curl http://localhost:8001/metrics/prometheus

# With authentication
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8001/metrics/prometheus
```

## Configuration

### Enable Metrics in LLMGuard

Metrics are automatically collected when the plugin is running. No additional configuration is required.

### Cache Configuration

The cache behavior can be configured in the plugin config:

```yaml
input:
  filters:
    # ... filter configuration
  sanitizers:
    # ... sanitizer configuration

# Cache configuration
cache_enabled: true
cache_ttl: 300  # seconds (5 minutes)
```

### Prometheus Scrape Configuration

Add the MCP Gateway to your Prometheus scrape config:

```yaml
scrape_configs:
  # The job name is added as a label `job=<job_name>` to any timeseries scraped from this config.
  - job_name: 'prometheus'

    # Override the global default and scrape targets from this job every 15 seconds.
    scrape_interval: 15s
    metrics_path: '/metrics/prometheus'
    static_configs:
      - targets: ['192.168.1.92:8001']
        labels:
          group: 'llmguard'
      - targets: ['192.168.1.92:8000']
        labels:
          group: 'context-forge'```

## Interpreting the Dashboard

### Performance Indicators

1. **Scan Duration < 100ms**: Excellent performance
2. **Scan Duration 100-500ms**: Good performance
3. **Scan Duration > 500ms**: May need optimization

### Cache Efficiency

1. **Cache Hit Rate > 80%**: Excellent cache efficiency
2. **Cache Hit Rate 50-80%**: Good cache efficiency
3. **Cache Hit Rate < 50%**: Consider increasing cache TTL or size

### Alerts

Consider setting up alerts for:

1. **High P95 Latency**: `histogram_quantile(0.95, rate(llm_guard_scan_duration_seconds_bucket[5m])) > 1`
2. **Low Cache Hit Rate**: `rate(llm_guard_cache_hits_sum[5m]) / (rate(llm_guard_cache_hits_count[5m]) + rate(llm_guard_cache_misses_total[5m])) < 0.5`
3. **High Error Rate**: Monitor for scanner failures in logs

## Troubleshooting

### No Data Showing

1. Verify Prometheus is scraping the metrics endpoint:
   ```bash
   curl http://localhost:9090/api/v1/targets
   ```

2. Check if metrics are being exposed:
   ```bash
   curl http://localhost:8001/metrics/prometheus | grep llm_guard
   ```

3. Verify the data source is configured correctly in Grafana

### Incorrect Values

1. Check the time range in Grafana (default: last 1 hour)
2. Verify the `rate()` interval matches your scrape interval
3. Ensure the LLMGuard plugin is actively processing requests

### Performance Issues

1. Reduce the dashboard refresh rate (default: 10s)
2. Increase the query interval (e.g., from `[5m]` to `[15m]`)
3. Use recording rules in Prometheus for expensive queries

## Advanced Queries

### Custom Queries

You can create custom panels with these example queries:

```promql
# Average scan duration by scanner type
avg by (scanner_category) (rate(llm_guard_scan_duration_seconds_sum[5m]) / rate(llm_guard_scan_duration_seconds_count[5m]))

# Total scans per minute
sum(rate(llm_guard_scan_duration_seconds_count[5m])) * 60

# Cache efficiency percentage
100 * (rate(llm_guard_cache_hits_sum[5m]) / (rate(llm_guard_cache_hits_count[5m]) + rate(llm_guard_cache_misses_total[5m])))

# Slowest scanner category
topk(1, avg by (scanner_category) (rate(llm_guard_scan_duration_seconds_sum[5m]) / rate(llm_guard_scan_duration_seconds_count[5m])))
```

## Support

For issues or questions:
- Check the MCP Gateway documentation: `docs/docs/manage/observability.md`
- Review the LLMGuard plugin README: `plugins/external/llmguard/README.md`
- Open an issue on the project repository

## License

Apache-2.0