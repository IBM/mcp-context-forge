# Phoenix Observability Quick Start

## 1. Install Dependencies

```bash
# Install observability dependencies
pip install -e ".[observability]"

# Or directly:
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

## 2. Start Phoenix + MCP Gateway

```bash
# Start both services with observability enabled
docker-compose -f docker-compose.yml -f docker-compose.with-phoenix.yml up -d

# Check they're running
docker ps
curl http://localhost:6006/health  # Phoenix
curl http://localhost:4444/health  # MCP Gateway
```

## 3. Test the Integration

```bash
# Run the test script to send sample traces
python test_phoenix_integration.py
```

## 4. View Traces in Phoenix

1. Open Phoenix UI: http://localhost:6006
2. You should see traces appearing in real-time
3. Click on any trace to see details

## 5. Add Observability to Your Code

### Simple Example

```python
from mcpgateway.observability_simple import init_telemetry, create_span

# Initialize once at startup
tracer = init_telemetry()

# Use in your code
async def my_function():
    with create_span("my.operation", {"user": "alice", "action": "query"}):
        # Your code here
        result = await do_something()
        return result
```

### In Tool Service

```python
from mcpgateway.observability_simple import trace_operation

class ToolService:
    @trace_operation("tool.invoke", {"tool.type": "mcp"})
    async def invoke_tool(self, tool_name: str, args: dict):
        # Automatically traced!
        return await self._invoke_impl(tool_name, args)
```

## 6. Environment Variables

These are automatically set when using `docker-compose.with-phoenix.yml`:

```bash
PHOENIX_ENDPOINT=http://phoenix:6006
OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix:4317
OTEL_SERVICE_NAME=mcp-gateway
OTEL_TRACES_EXPORTER=otlp
```

## 7. What Gets Traced?

With the simple implementation, you can trace:
- Tool invocations
- Prompt rendering
- Resource fetching
- Gateway federation calls
- Any custom operations you add

## 8. Troubleshooting

### No traces appearing?

1. Check Phoenix is running:
   ```bash
   docker logs phoenix
   ```

2. Check environment variables:
   ```bash
   docker exec gateway env | grep OTEL
   ```

3. Run test script:
   ```bash
   python test_phoenix_integration.py
   ```

### Port conflicts?

Phoenix uses ports 6006 and 4317. If they're in use:
```bash
# Stop conflicting services or change ports in docker-compose.with-phoenix.yml
lsof -i :6006
lsof -i :4317
```

## Next Steps

1. **Add more spans**: Instrument critical code paths
2. **Add attributes**: Include useful metadata in spans
3. **Error tracking**: Record exceptions in spans
4. **Performance**: Monitor slow operations
5. **Distributed tracing**: Connect traces across services

## Minimal Code Changes Required

The beauty of this approach is you only need to:

1. Import the observability module
2. Call `init_telemetry()` once at startup
3. Use `@trace_operation` decorator or `create_span()` context manager

That's it! Phoenix handles all the visualization and analysis.
