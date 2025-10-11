# Phoenix Integration Guide

[Arize Phoenix](https://github.com/Arize-ai/phoenix) provides AI/LLM-focused observability for MCP Gateway, offering specialized features for monitoring AI-powered applications.

## Why Phoenix?

Phoenix is optimized for AI/LLM workloads with features like:

- **Token usage tracking** - Monitor prompt and completion tokens
- **Cost analysis** - Track API costs across models
- **Evaluation metrics** - Measure response quality
- **Drift detection** - Identify model behavior changes
- **Conversation analysis** - Understand multi-turn interactions

## Quick Start

### Option 1: Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/IBM/mcp-context-forge
cd mcp-context-forge

# Start Phoenix with MCP Gateway
docker-compose -f docker-compose.yml \
               -f docker-compose.with-phoenix.yml up -d

# View Phoenix UI
open http://localhost:6006

# View traces flowing in
curl http://localhost:4444/health  # Generate a trace
```

### Option 2: Standalone Phoenix

```bash
# Start Phoenix
docker run -d \
  --name phoenix \
  -p 6006:6006 \
  -p 4317:4317 \
  -v phoenix-data:/phoenix/data \
  arizephoenix/phoenix:latest

# Configure MCP Gateway
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=mcp-gateway

# Start MCP Gateway
mcpgateway
```

### Option 3: Phoenix Cloud

For production deployments, use [Phoenix Cloud](https://app.phoenix.arize.com):

```bash
# Get your API key from Phoenix Cloud
export PHOENIX_API_KEY=your-api-key

# Configure MCP Gateway for Phoenix Cloud
export OTEL_EXPORTER_OTLP_ENDPOINT=https://app.phoenix.arize.com
export OTEL_EXPORTER_OTLP_HEADERS="api-key=$PHOENIX_API_KEY"
export OTEL_EXPORTER_OTLP_INSECURE=false
```

## Docker Compose Configuration

The provided `docker-compose.with-phoenix.yml` includes:

```yaml
services:
  phoenix:
    image: arizephoenix/phoenix:latest
    ports:

      - "6006:6006"  # Phoenix UI
      - "4317:4317"  # OTLP gRPC endpoint
    environment:

      - PHOENIX_GRPC_PORT=4317
      - PHOENIX_PORT=6006
      - PHOENIX_HOST=0.0.0.0
    volumes:

      - phoenix-data:/phoenix/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6006/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  mcpgateway:
    environment:

      - OTEL_ENABLE_OBSERVABILITY=true
      - OTEL_TRACES_EXPORTER=otlp
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix:4317
      - OTEL_SERVICE_NAME=mcp-gateway
    depends_on:
      phoenix:
        condition: service_healthy
```

## Using Phoenix UI

### Viewing Traces

1. Navigate to http://localhost:6006
2. Click on "Traces" in the left sidebar
3. You'll see:
   - Timeline view of all operations
   - Span details with attributes
   - Error rates and latencies
   - Service dependency graph

### Analyzing Tool Invocations

Phoenix provides specialized views for tool calls:

1. **Tool Performance**
   - Average latency per tool
   - Success/failure rates
   - Usage frequency

2. **Cost Analysis** (when token tracking is implemented)
   - Token usage per tool
   - Estimated costs by model
   - Cost trends over time

### Setting Up Evaluations

Phoenix can evaluate response quality:

```python
# Example: Set up Phoenix evaluations (Python)
from phoenix.evals import llm_eval
from phoenix.trace import trace

# Configure evaluations
evaluator = llm_eval.LLMEvaluator(
    model="gpt-4",
    eval_type="relevance"
)

# Traces from MCP Gateway will be evaluated
evaluator.evaluate(
    trace_dataset=phoenix.get_traces(),
    eval_name="response_quality"
)
```

## Production Deployment

### With PostgreSQL Backend

For production, use PostgreSQL for Phoenix storage:

```yaml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: phoenix
      POSTGRES_USER: phoenix
      POSTGRES_PASSWORD: phoenix_secret
    volumes:

      - postgres-data:/var/lib/postgresql/data

  phoenix:
    image: arizephoenix/phoenix:latest
    environment:

      - DATABASE_URL=postgresql://phoenix:phoenix_secret@postgres:5432/phoenix
      - PHOENIX_GRPC_PORT=4317
      - PHOENIX_PORT=6006
    depends_on:

      - postgres
```

### Kubernetes Deployment

Deploy Phoenix on Kubernetes:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: phoenix
spec:
  replicas: 1
  selector:
    matchLabels:
      app: phoenix
  template:
    metadata:
      labels:
        app: phoenix
    spec:
      containers:

      - name: phoenix
        image: arizephoenix/phoenix:latest
        ports:

        - containerPort: 6006
          name: ui

        - containerPort: 4317
          name: otlp
        env:

        - name: PHOENIX_GRPC_PORT
          value: "4317"

        - name: PHOENIX_PORT
          value: "6006"
        volumeMounts:

        - name: data
          mountPath: /phoenix/data
      volumes:

      - name: data
        persistentVolumeClaim:
          claimName: phoenix-data
---
apiVersion: v1
kind: Service
metadata:
  name: phoenix
spec:
  selector:
    app: phoenix
  ports:

  - port: 6006
    name: ui

  - port: 4317
    name: otlp
```

## Advanced Features

### Custom Span Attributes

Add Phoenix-specific attributes in your code:

```python
from mcpgateway.observability import create_span

# Add LLM-specific attributes
with create_span("tool.invoke", {
    "llm.model": "gpt-4",
    "llm.prompt_tokens": 150,
    "llm.completion_tokens": 50,
    "llm.temperature": 0.7,
    "llm.top_p": 0.9
}) as span:
    # Tool execution
    pass
```

### Integrating with Phoenix SDK

For advanced analysis, use the Phoenix SDK:

```python
import phoenix as px

# Connect to Phoenix
px.launch_app(trace_dataset=px.Client().get_traces())

# Analyze traces
traces_df = px.Client().get_traces_dataframe()
print(traces_df.describe())

# Export for further analysis
traces_df.to_csv("mcp_gateway_traces.csv")
```

## Monitoring Best Practices

### Key Metrics to Track

1. **Response Times**
   - P50, P95, P99 latencies
   - Slowest operations
   - Timeout rates

2. **Error Rates**
   - Error percentage by tool
   - Error types distribution
   - Error trends

3. **Usage Patterns**
   - Most used tools
   - Peak usage times
   - User distribution

### Setting Up Alerts

Configure alerts in Phoenix Cloud:

1. Go to Settings → Alerts
2. Create rules for:
   - High error rates (> 5%)
   - Slow responses (P95 > 2s)
   - Unusual token usage
   - Cost thresholds

## Troubleshooting

### Phoenix Not Receiving Traces

1. Check Phoenix is running:
   ```bash
   docker ps | grep phoenix
   curl http://localhost:6006/health
   ```

2. Verify OTLP endpoint:
   ```bash
   telnet localhost 4317
   ```

3. Check MCP Gateway logs:
   ```bash
   docker logs mcpgateway | grep -i phoenix
   ```

### High Memory Usage

Phoenix stores traces in memory by default. For production:

1. Use PostgreSQL backend
2. Configure retention policies
3. Set sampling rates appropriately

### Performance Optimization

1. **Reduce trace volume**:
   ```bash
   export OTEL_TRACES_SAMPLER_ARG=0.01  # Sample 1%
   ```

2. **Filter unnecessary spans**:
   ```python
   # In observability.py, add filtering
   if span_name in ["health_check", "metrics"]:
       return nullcontext()
   ```

## Next Steps

- [Configure Phoenix Evaluations](https://docs.arize.com/phoenix/evaluation)
- [Set up Phoenix Datasets](https://docs.arize.com/phoenix/datasets)
- [Integrate with Arize Platform](https://docs.arize.com/arize)
- [Join Phoenix Community](https://github.com/Arize-ai/phoenix/discussions)
