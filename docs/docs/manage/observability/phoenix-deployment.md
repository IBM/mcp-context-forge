# Phoenix Observability Deployment Guide

This guide explains how to deploy Arize Phoenix observability with MCP Gateway.

## Quick Start

### Option 1: Standalone Phoenix (Testing)

```bash
# Start Phoenix standalone with SQLite backend
docker-compose -f docker-compose.phoenix-simple.yml up -d

# View logs
docker-compose -f docker-compose.phoenix-simple.yml logs -f phoenix

# Access Phoenix UI
open http://localhost:6006

# Stop Phoenix
docker-compose -f docker-compose.phoenix-simple.yml down
```

### Option 2: Integrated with MCP Gateway (Recommended)

```bash
# Start MCP Gateway with Phoenix observability
docker-compose -f docker-compose.yml -f docker-compose.with-phoenix.yml up -d

# This automatically:
# - Starts Phoenix with SQLite storage
# - Configures MCP Gateway to send traces to Phoenix
# - Sets up OTLP endpoints on ports 4317 (gRPC) and 6006 (HTTP)

# Check health
curl http://localhost:6006/health  # Phoenix
curl http://localhost:4444/health  # MCP Gateway

# View combined logs
docker-compose -f docker-compose.yml -f docker-compose.with-phoenix.yml logs -f

# Stop everything
docker-compose -f docker-compose.yml -f docker-compose.with-phoenix.yml down
```

## Architecture

```
┌─────────────────┐         ┌──────────────────┐
│   MCP Gateway   │────────▶│     Phoenix      │
│                 │  OTLP   │                  │
│  - Tools        │         │  - Traces        │
│  - Prompts      │         │  - Metrics       │  
│  - Resources    │         │  - LLM Analytics │
└─────────────────┘         └──────────────────┘
     Port 4444                   Port 6006
                                 Port 4317
```

## Configuration

### Environment Variables for MCP Gateway

When Phoenix is deployed, MCP Gateway automatically receives these environment variables:

```bash
PHOENIX_ENDPOINT=http://phoenix:6006
OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix:4317
OTEL_SERVICE_NAME=mcp-gateway
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=docker,service.namespace=mcp
```

### Custom Configuration

To customize Phoenix or MCP Gateway settings, create a `.env` file:

```bash
# .env
# Phoenix settings
PHOENIX_LOG_LEVEL=debug
PHOENIX_ENABLE_AUTH=false

# MCP Gateway observability
OTEL_SERVICE_NAME=my-mcp-gateway
OTEL_TRACES_SAMPLER_ARG=0.1  # Sample 10% of traces
```

## Using Phoenix UI

### Access the Dashboard

1. Navigate to http://localhost:6006
2. You'll see the Phoenix dashboard with:
   - **Traces**: View all MCP Gateway operations
   - **Metrics**: Monitor performance and usage
   - **LLM Analytics**: Token usage and costs (when configured)

### Viewing Traces

Traces are automatically sent when MCP Gateway processes:
- Tool invocations
- Prompt rendering
- Resource fetching
- Federation calls

### Example: Sending Manual Traces

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Configure OTLP exporter to Phoenix
otlp_exporter = OTLPSpanExporter(
    endpoint="localhost:4317",
    insecure=True
)

# Set up tracer
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer("mcp-custom")
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)

# Create a trace
with tracer.start_as_current_span("custom.operation"):
    # Your code here
    pass
```

## Monitoring

### Health Checks

```bash
# Check Phoenix health
curl http://localhost:6006/health

# Check if Phoenix is receiving traces
curl http://localhost:6006/v1/traces

# View Phoenix metrics
curl http://localhost:6006/metrics
```

### Viewing Logs

```bash
# Phoenix logs only
docker logs phoenix

# Follow logs
docker logs -f phoenix

# Combined MCP Gateway + Phoenix logs
docker-compose -f docker-compose.yml -f docker-compose.with-phoenix.yml logs -f
```

## Troubleshooting

### Phoenix Not Receiving Traces

1. Check Phoenix is running:
   ```bash
   docker ps | grep phoenix
   ```

2. Verify environment variables in MCP Gateway:
   ```bash
   docker exec gateway env | grep -E "PHOENIX|OTEL"
   ```

3. Check Phoenix logs for errors:
   ```bash
   docker logs phoenix --tail 50
   ```

### Port Conflicts

If ports 6006 or 4317 are already in use:

1. Stop conflicting services, or
2. Change Phoenix ports in `docker-compose.with-phoenix.yml`:
   ```yaml
   ports:
     - "7006:6006"  # Change host port
     - "5317:4317"  # Change host port
   ```

### Storage Issues

Phoenix uses SQLite by default, storing data in a Docker volume:

```bash
# View volume info
docker volume inspect mcp-context-forge_phoenix-data

# Clear Phoenix data (warning: deletes all traces)
docker-compose -f docker-compose.with-phoenix.yml down -v
```

## Performance Tuning

### Sampling

To reduce overhead in production, configure sampling:

```yaml
# In docker-compose.with-phoenix.yml, add to gateway environment:
- OTEL_TRACES_SAMPLER=traceidratio
- OTEL_TRACES_SAMPLER_ARG=0.1  # Sample 10% of traces
```

### Resource Limits

Add resource limits to Phoenix container:

```yaml
phoenix:
  # ... other config ...
  deploy:
    resources:
      limits:
        memory: 2G
        cpus: '1.0'
      reservations:
        memory: 512M
        cpus: '0.5'
```

## Maintenance

### Backup Phoenix Data

```bash
# Create backup of SQLite database
docker run --rm -v mcp-context-forge_phoenix-data:/data \
  -v $(pwd):/backup alpine \
  tar czf /backup/phoenix-backup-$(date +%Y%m%d).tar.gz /data
```

### Upgrade Phoenix

```bash
# Pull latest image
docker pull arizephoenix/phoenix:latest

# Restart with new image
docker-compose -f docker-compose.with-phoenix.yml up -d phoenix
```

### Clean Up

```bash
# Stop Phoenix but keep data
docker-compose -f docker-compose.with-phoenix.yml stop phoenix

# Remove Phoenix and its data
docker-compose -f docker-compose.with-phoenix.yml down -v
```

## Production Considerations

For production deployments:

1. **Enable Authentication**: Set `PHOENIX_ENABLE_AUTH=true`
2. **Use PostgreSQL**: For better performance with large trace volumes
3. **Configure TLS**: Secure OTLP endpoints with certificates
4. **Set Resource Limits**: Prevent resource exhaustion
5. **Enable Sampling**: Reduce overhead with trace sampling
6. **Regular Backups**: Schedule automated backups of Phoenix data

## Next Steps

1. **Install OpenLLMetry Plugin**: See `todo/openllmetry.md` for LLM-specific instrumentation
2. **Configure Token Pricing**: Add cost tracking for LLM operations
3. **Set Up Dashboards**: Create custom views in Phoenix UI
4. **Enable Distributed Tracing**: Connect federated gateways

## References

- [Phoenix Documentation](https://docs.arize.com/phoenix)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
- [MCP Gateway Docs](https://ibm.github.io/mcp-context-forge/)