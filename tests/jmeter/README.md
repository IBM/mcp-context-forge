# JMeter Performance Testing

This directory contains JMeter test plans for ContextForge performance testing, providing industry-standard baseline measurements and CI/CD integration capabilities.

## Prerequisites

### Install JMeter

**Recommended: Use the Makefile target** (installs JMeter 5.6.3 locally):
```bash
make jmeter-install
```

**Alternative: Manual installation**
```bash
# macOS
brew install jmeter

# Linux
wget https://dlcdn.apache.org/jmeter/binaries/apache-jmeter-5.6.3.tgz
tar -xzf apache-jmeter-5.6.3.tgz
export PATH=$PATH:$(pwd)/apache-jmeter-5.6.3/bin
```

**Verify installation** (requires JMeter 5.x+ for HTML reports):
```bash
make jmeter-check
```

### Optional Plugins

For WebSocket testing, install the JMeter WebSocket plugin:
```bash
jmeter -p plugins-manager.sh install jpgc-websocket
```

## Quick Start

Note: The Makefile targets render shared REST/MCP fragments into `.jmeter/rendered/` before running JMeter. Run tests via `make` to ensure the rendered plans are used.

```bash
# Set up environment
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 10080 --secret $JWT_SECRET_KEY)

# Run REST API baseline
make jmeter-rest-baseline

# Run MCP JSON-RPC baseline (requires server ID)
make jmeter-mcp-baseline JMETER_SERVER_ID=<your-server-id>

# Run load test
make jmeter-load JMETER_SERVER_ID=<your-server-id>
```

## Test Plans

| Test Plan | Description | Duration | Target |
|-----------|-------------|----------|--------|
| `rest_api_baseline.jmx` | REST API endpoints baseline | 10 min | 1,000 RPS |
| `mcp_jsonrpc_baseline.jmx` | MCP JSON-RPC protocol baseline | 15 min | 1,000 RPS |
| `mcp_test_servers_baseline.jmx` | Direct MCP server testing | 10 min | 2,000 RPS |
| `load_test.jmx` | Production load simulation | 30 min | 4,000 RPS |
| `stress_test.jmx` | Progressive stress to breaking point | 30 min | 10,000 RPS |
| `spike_test.jmx` | Traffic spike recovery test | 10 min | 1K→10K→1K |
| `soak_test.jmx` | Memory leak detection | 24 hrs | 2,000 RPS |
| `sse_streaming_baseline.jmx` | SSE connection stability | 10 min | 1,000 conn |
| `websocket_baseline.jmx` | WebSocket performance | 10 min | 500 conn |
| `admin_ui_baseline.jmx` | Admin UI user simulation | 5 min | 50 users |

## Directory Structure

```
tests/jmeter/
├── README.md                      # This file
├── rest_api_baseline.jmx          # REST API baseline test
├── mcp_jsonrpc_baseline.jmx       # MCP JSON-RPC baseline test
├── mcp_test_servers_baseline.jmx  # Direct MCP server testing
├── load_test.jmx                  # Production load test
├── stress_test.jmx                # Stress test (find breaking point)
├── spike_test.jmx                 # Traffic spike recovery test
├── soak_test.jmx                  # 24-hour memory leak detection
├── sse_streaming_baseline.jmx     # SSE streaming baseline
├── websocket_baseline.jmx         # WebSocket baseline
├── admin_ui_baseline.jmx          # Admin UI user simulation
├── properties/
│   ├── production.properties      # Production test settings
│   └── ci.properties              # CI/CD optimized settings
├── data/
│   ├── timezones.csv              # Timezone test data
│   ├── tool_names.csv             # MCP tool test data
│   └── test_messages.csv          # Message payloads
└── results/                       # Generated test results
```

## Command-Line Usage

### Basic Test Execution

```bash
# Run with default settings
jmeter -n -t rest_api_baseline.jmx \
  -JGATEWAY_URL=http://localhost:8080 \
  -JTOKEN=$MCPGATEWAY_BEARER_TOKEN \
  -l results/test.jtl \
  -e -o results/report/

# Run with properties file
jmeter -p properties/production.properties \
  -n -t load_test.jmx \
  -l results/load.jtl
```

### Common Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `GATEWAY_URL` | Gateway base URL (http or https) | http://localhost:8080 |
| `TOKEN` | JWT bearer token | (required) |
| `SERVER_ID` | Virtual server ID for MCP tests | (required for MCP) |
| `THREADS` | Number of concurrent users | Varies by test |
| `RAMP_UP` | Ramp-up time in seconds | 60 |
| `DURATION` | Test duration in seconds | Varies by test |

### HTTPS/TLS Testing

All test plans support HTTPS by passing an `https://` URL:

```bash
# HTTP (default port 8080)
make jmeter-rest-baseline JMETER_GATEWAY_URL=http://localhost:8080

# HTTPS/TLS (port 8443)
make jmeter-rest-baseline JMETER_GATEWAY_URL=https://localhost:8443
```

For self-signed certificates (common in development), you may need to:
1. Add the certificate to Java's truststore, or
2. Run with: `JAVA_OPTS="-Djavax.net.ssl.trustStore=/path/to/truststore.jks"`

## Makefile Targets

```bash
# Setup
make jmeter-install                # Download and install JMeter 5.6.3 locally
make jmeter-check                  # Verify JMeter 5.x+ is available
make jmeter-ui                     # Launch JMeter GUI for test editing

# Baseline Tests
make jmeter-rest-baseline          # REST API baseline (1,000 RPS, 10min)
make jmeter-mcp-baseline           # MCP JSON-RPC baseline (1,000 RPS, 15min)
make jmeter-mcp-servers-baseline   # MCP test servers baseline
make jmeter-sse                    # SSE streaming baseline
make jmeter-websocket              # WebSocket baseline
make jmeter-admin-ui               # Admin UI baseline

# Load Tests
make jmeter-load                   # Load test (4,000 RPS, 30min)
make jmeter-stress                 # Stress test (ramp to 10,000 RPS)
make jmeter-spike                  # Spike test (1K→10K→1K recovery)
make jmeter-soak                   # 24-hour soak test (2,000 RPS)

# Reporting
make jmeter-report                 # Generate HTML report from latest JTL
make jmeter-compare                # Compare current vs baseline results
```

## CI/CD Integration

### GitHub Actions Example

```yaml
- name: Run JMeter baseline
  run: |
    jmeter -n -t tests/jmeter/rest_api_baseline.jmx \
      -p tests/jmeter/properties/ci.properties \
      -JGATEWAY_URL=http://gateway:8080 \
      -JTOKEN=${{ secrets.JWT_TOKEN }} \
      -l results.jtl \
      -e -o report/

- name: Check performance thresholds
  run: |
    # Parse JTL and check P95 < 300ms
    P95=$(awk -F',' 'NR>1 {print $2}' results.jtl | sort -n | awk 'NR==int(ENVIRON["NR"]*0.95)')
    if [ "$P95" -gt 300 ]; then
      echo "P95 latency ($P95 ms) exceeds threshold (300ms)"
      exit 1
    fi
```

## Performance SLAs

| Metric | Baseline | Load | Stress |
|--------|----------|------|--------|
| P50 Latency | < 100ms | < 150ms | < 300ms |
| P95 Latency | < 200ms | < 300ms | < 500ms |
| P99 Latency | < 300ms | < 500ms | < 1000ms |
| Error Rate | < 0.1% | < 0.5% | < 1% |
| Throughput | 1,000 RPS | 4,000 RPS | 10,000 RPS |

## Interpreting Results

### JTL File Format

The JTL output contains CSV data with columns:
- `timeStamp`: Request timestamp
- `elapsed`: Response time in ms
- `label`: Request name
- `responseCode`: HTTP status code
- `responseMessage`: Status message
- `success`: true/false
- `bytes`: Response size
- `grpThreads`: Active threads
- `allThreads`: Total threads
- `latency`: Time to first byte
- `connect`: Connection time

### HTML Report Sections

1. **Dashboard**: Overview metrics and charts
2. **Statistics**: Per-request breakdowns
3. **Response Times**: Percentile distributions
4. **Throughput**: RPS over time
5. **Errors**: Error categorization

## Troubleshooting

### Common Issues

**JMeter not found**
```bash
# Add to PATH
export PATH=$PATH:/path/to/apache-jmeter-5.6.3/bin
```

**Connection refused errors**
- Verify gateway is running: `curl http://localhost:8080/health`
- Check token validity: `echo $MCPGATEWAY_BEARER_TOKEN | cut -d. -f2 | base64 -d`

**Out of memory**
```bash
# Increase JMeter heap
export HEAP="-Xms2g -Xmx4g"
jmeter -n -t test.jmx ...
```

**Too many open files**
```bash
# Increase ulimit for high connection tests
ulimit -n 65535
```

## Related Documentation

- [Locust Load Tests](../loadtest/README.md) - Python-based load testing
- [Performance Best Practices](../../docs/performance.md) - Optimization guide
- [Monitoring Setup](../../docker-compose.yml) - Prometheus/Grafana stack
