# Observability

MCP Gateway includes production-grade OpenTelemetry instrumentation for distributed tracing, enabling you to monitor performance, debug issues, and understand request flows across your gateway instances.

## Overview

The observability implementation is **vendor-agnostic** and works with any OTLP-compatible backend. MCP Gateway supports multiple observability backends, each optimized for different use cases.

## Recommended Backend Options

### Arize Phoenix - AI/LLM-Focused Observability

**Best for**: AI applications, LLM debugging, and prompt optimization

[Arize Phoenix](https://github.com/Arize-ai/phoenix) is an open-source AI observability platform specifically designed for LLM applications and AI systems. Built on OpenTelemetry, it provides specialized features for understanding AI application behavior.

**Key Features**:

- **LLM Tracing**: Purpose-built for tracking LLM calls, token usage, and model performance
- **Evaluation Tools**: Built-in evaluators for response quality, retrieval accuracy, and hallucination detection
- **Prompt Playground**: Interactive environment for optimizing prompts with version control and experimentation
- **Framework Support**: Native integrations with LlamaIndex, LangChain, Haystack, DSPy, and major LLM providers
- **Cost Tracking**: Monitor token usage and API costs across different providers
- **Zero Lock-in**: Fully open source and self-hostable with no feature gates

**Ideal Use Cases**:

- Debugging RAG (Retrieval-Augmented Generation) pipelines
- Optimizing prompt templates and model parameters
- Tracking LLM performance metrics and costs
- Evaluating response quality and accuracy

**Transport**: Uses OTLP (OpenTelemetry Protocol) via gRPC

### Jaeger - Production-Grade Distributed Tracing

**Best for**: Microservices architectures, production deployments, and general-purpose tracing

[Jaeger](https://www.jaegertracing.io/) is a mature, battle-tested distributed tracing platform originally created by Uber and now a CNCF graduated project. It excels at monitoring complex distributed systems.

**Key Features**:

- **Proven Scale**: Handles high-volume production environments with battle-tested reliability
- **Full Observability**: Comprehensive request flow visualization across microservices
- **Multiple Storage Backends**: Supports Elasticsearch, Cassandra, and other scalable storage solutions
- **Kubernetes Native**: Deep integration with cloud-native environments
- **Advanced Sampling**: Configurable sampling strategies (constant, probabilistic, rate-limiting)
- **OpenTelemetry Integration**: Full OTLP support in v2 with native OpenTelemetry data model

**Ideal Use Cases**:

- Large-scale microservices deployments
- Performance bottleneck identification
- Service dependency mapping
- Root cause analysis of distributed failures

**Transport**: Supports both native Jaeger protocol and OTLP

### Grafana Tempo - Cost-Efficient High-Scale Tracing

**Best for**: High-volume environments, cost-conscious deployments, and Grafana ecosystem users

[Grafana Tempo](https://grafana.com/oss/tempo/) is a high-scale, low-cost distributed tracing backend that eliminates expensive indexing by leveraging object storage (S3, GCS, Azure Blob).

**Key Features**:

- **Extreme Cost Efficiency**: Uses cheap object storage instead of expensive databases (Elasticsearch/Cassandra)
- **Massive Scale**: Designed to handle 100% trace capture without prohibitive costs
- **No Heavy Indexing**: Lightweight bloom filters instead of full-text indexes reduce storage costs dramatically
- **TraceQL Query Language**: Powerful query language inspired by PromQL and LogQL
- **Grafana Ecosystem Integration**: Deep integration with Grafana, Prometheus, Loki, and Mimir
- **Multi-Protocol Support**: Compatible with Jaeger, Zipkin, OpenCensus, and OpenTelemetry

**Ideal Use Cases**:

- High-volume microservices (170k+ spans/second proven in production)
- Cost-sensitive environments requiring long trace retention
- Organizations already using Grafana stack
- Teams wanting 100% trace capture without sampling

**Transport**: Uses OTLP (OpenTelemetry Protocol) via gRPC

### Other Compatible Backends

The OTLP exporter also works with commercial APM solutions:

- **Datadog APM** - Full-featured commercial observability platform
- **New Relic** - Cloud-based application performance monitoring
- **Honeycomb** - Observability for production systems
- **Zipkin** - Lightweight distributed tracing (legacy but widely supported)

## What Gets Traced

- **Tool invocations** - Full lifecycle with arguments, results, and timing
- **Prompt rendering** - Template processing and message generation
- **Resource fetching** - URI resolution, caching, and content retrieval
- **Gateway federation** - Cross-gateway requests and health checks
- **Plugin execution** - Pre/post hooks if plugins are enabled
- **Errors and exceptions** - Full stack traces and error context

## Quick Start

### 1. Install Dependencies

The observability packages are included in the Docker containers by default. For local development:

```bash
# Install base gateway with core observability support
pip install mcp-contextforge-gateway[observability]
```

**Important**: Only one exporter backend should be installed at a time - they are mutually exclusive. Install the specific backend package based on your chosen observability platform (see backend-specific instructions in the "Start Your Backend" section below).

### 2. Configure Environment

Set these environment variables (or add to `.env`):

```bash
# Enable observability (default: false)
export OTEL_ENABLE_OBSERVABILITY=true

# Service identification
export OTEL_SERVICE_NAME=mcp-gateway
export OTEL_SERVICE_VERSION=0.9.0
export OTEL_DEPLOYMENT_ENVIRONMENT=development

# Choose your backend (otlp, jaeger, zipkin, console, none)
export OTEL_TRACES_EXPORTER=otlp

# OTLP Configuration (for Phoenix, Tempo, etc.)
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_INSECURE=true
```

### 3. Start Your Backend

Choose your preferred observability backend:

#### Phoenix (AI/LLM Focus)

```bash
# Install Phoenix exporter backend
pip install opentelemetry-exporter-otlp-proto-grpc

# Start Phoenix
docker run -d \
  --name phoenix \
  -p 6006:6006 \
  -p 4317:4317 \
  arizephoenix/phoenix:latest

# Configure environment
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=mcp-gateway

# View UI at http://localhost:6006
```

#### Jaeger

```bash
# Install Jaeger exporter backend
pip install opentelemetry-exporter-jaeger

# Start Jaeger
docker run -d \
  --name jaeger \
  -p 16686:16686 \
  -p 14268:14268 \
  jaegertracing/all-in-one

# Configure environment
export OTEL_TRACES_EXPORTER=jaeger
export OTEL_EXPORTER_JAEGER_ENDPOINT=http://localhost:14268/api/traces
export OTEL_SERVICE_NAME=mcp-gateway

# View UI at http://localhost:16686
```

#### Zipkin

```bash
# Install Zipkin exporter backend
pip install opentelemetry-exporter-zipkin

# Start Zipkin
docker run -d \
  --name zipkin \
  -p 9411:9411 \
  openzipkin/zipkin

# Configure environment
export OTEL_TRACES_EXPORTER=zipkin
export OTEL_EXPORTER_ZIPKIN_ENDPOINT=http://localhost:9411/api/v2/spans
export OTEL_SERVICE_NAME=mcp-gateway

# View UI at http://localhost:9411
```

#### Grafana Tempo

```bash
# Install OTLP exporter backend (Tempo uses OTLP)
pip install opentelemetry-exporter-otlp-proto-grpc

# Start Tempo
docker run -d \
  --name tempo \
  -p 4317:4317 \
  -p 3200:3200 \
  grafana/tempo:latest

# Configure environment (uses OTLP)
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=mcp-gateway
```

#### Console (Development)

```bash
# For debugging - prints traces to stdout
export OTEL_TRACES_EXPORTER=console
export OTEL_SERVICE_NAME=mcp-gateway
```

### 4. Run MCP Gateway

```bash
# Start the gateway (observability is disabled by default)
mcpgateway

# Or with Docker
docker run -e OTEL_ENABLE_OBSERVABILITY=true \
           -e OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4317 \
           ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
```

## Configuration Reference

### Core Settings

| Variable | Description | Default | Options |
|----------|-------------|---------|---------|
| `OTEL_ENABLE_OBSERVABILITY` | Master switch | `false` | `true`, `false` |
| `OTEL_SERVICE_NAME` | Service identifier | `mcp-gateway` | Any string |
| `OTEL_SERVICE_VERSION` | Service version | `0.9.0` | Any string |
| `OTEL_DEPLOYMENT_ENVIRONMENT` | Environment tag | `development` | `development`, `staging`, `production` |
| `OTEL_TRACES_EXPORTER` | Export backend | `otlp` | `otlp`, `jaeger`, `zipkin`, `console`, `none` |
| `OTEL_RESOURCE_ATTRIBUTES` | Custom attributes | - | `key=value,key2=value2` |

### OTLP Configuration

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Collector endpoint | - | `http://localhost:4317` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Protocol | `grpc` | `grpc`, `http/protobuf` |
| `OTEL_EXPORTER_OTLP_HEADERS` | Auth headers | - | `api-key=secret,x-auth=token` |
| `OTEL_EXPORTER_OTLP_INSECURE` | Skip TLS verify | `true` | `true`, `false` |

### Alternative Backends

| Variable | Description | Default |
|----------|-------------|---------|
| `OTEL_EXPORTER_JAEGER_ENDPOINT` | Jaeger collector | `http://localhost:14268/api/traces` |
| `OTEL_EXPORTER_ZIPKIN_ENDPOINT` | Zipkin collector | `http://localhost:9411/api/v2/spans` |

### Performance Tuning

| Variable | Description | Default |
|----------|-------------|---------|
| `OTEL_TRACES_SAMPLER` | Sampling strategy | `parentbased_traceidratio` |
| `OTEL_TRACES_SAMPLER_ARG` | Sample rate (0.0-1.0) | `0.1` (10%) |
| `OTEL_BSP_MAX_QUEUE_SIZE` | Max queued spans | `2048` |
| `OTEL_BSP_MAX_EXPORT_BATCH_SIZE` | Batch size | `512` |
| `OTEL_BSP_SCHEDULE_DELAY` | Export interval (ms) | `5000` |

## Understanding Traces

### Span Attributes

Each span includes standard attributes:

- **Operation name** - e.g., `tool.invoke`, `prompt.render`, `resource.read`
- **Service info** - Service name, version, environment
- **User context** - User ID, tenant ID, request ID
- **Timing** - Start time, duration, end time
- **Status** - Success/error status with error details

### Tool Invocation Spans

```json
{
  "name": "tool.invoke",
  "attributes": {
    "tool.name": "github_search",
    "tool.id": "550e8400-e29b-41d4-a716",
    "tool.integration_type": "REST",
    "arguments_count": 3,
    "success": true,
    "duration.ms": 234.5,
    "http.status_code": 200
  }
}
```

### Error Tracking

Failed operations include:

- `error`: `true`
- `error.type`: Exception class name
- `error.message`: Error description
- Full stack trace via `span.record_exception()`

## Production Deployment

### Docker Compose

Use the provided compose files:

```bash
# Start MCP Gateway with Phoenix observability
docker-compose -f docker-compose.yml \
               -f docker-compose.with-phoenix.yml up -d
```

### Kubernetes

Add environment variables to your deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-gateway
spec:
  template:
    spec:
      containers:

      - name: gateway
        image: ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
        env:

        - name: OTEL_ENABLE_OBSERVABILITY
          value: "true"

        - name: OTEL_TRACES_EXPORTER
          value: "otlp"

        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://otel-collector:4317"

        - name: OTEL_SERVICE_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['app.kubernetes.io/name']
```

### Sampling Strategies

For production, adjust sampling to balance visibility and performance:

```bash
# Sample 1% of traces
export OTEL_TRACES_SAMPLER=parentbased_traceidratio
export OTEL_TRACES_SAMPLER_ARG=0.01

# Always sample errors (coming in future update)
# export OTEL_TRACES_SAMPLER=parentbased_always_on_errors
```

## Testing Your Setup

### Generate Test Traces

Use the trace generator helper to verify your observability backend is working:

```bash
# Activate virtual environment if needed
. /home/cmihai/.venv/mcpgateway/bin/activate

# Run the trace generator
python tests/integration/helpers/trace_generator.py
```

This will send sample traces for:

- Tool invocations
- Prompt rendering
- Resource fetching
- Gateway federation
- Complex workflows with nested spans

## Troubleshooting

### No Traces Appearing

1. Check observability is enabled:

   ```bash
   echo $OTEL_ENABLE_OBSERVABILITY  # Should be "true"
   ```

2. Verify endpoint is reachable:

   ```bash
   curl -v http://localhost:4317  # Should connect
   ```

3. Use console exporter for debugging:

   ```bash
   export OTEL_TRACES_EXPORTER=console
   mcpgateway  # Traces will print to stdout
   ```

### High Memory Usage

Reduce batch size and queue limits:

```bash
export OTEL_BSP_MAX_QUEUE_SIZE=512
export OTEL_BSP_MAX_EXPORT_BATCH_SIZE=128
```

### Missing Spans

Check sampling rate:

```bash
# Temporarily disable sampling
export OTEL_TRACES_SAMPLER=always_on
```

## Performance Impact

- **When disabled**: Zero overhead (no-op context managers)
- **When enabled**: ~0.1-0.5ms per span
- **Memory**: ~50MB for typical workload
- **Network**: Batched exports every 5 seconds

## Next Steps

- See [Phoenix Integration Guide](phoenix.md) for AI/LLM-specific features
- Review [OpenTelemetry Best Practices](https://opentelemetry.io/docs/best-practices/)
- Configure dashboards in your APM solution
- Set up alerting based on error rates and latencies
