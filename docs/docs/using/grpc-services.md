# gRPC Services (Experimental)

!!! warning "Experimental Feature"
    gRPC support is an **experimental opt-in feature** that is disabled by default. It requires additional dependencies and explicit enablement.

MCP Gateway supports automatic translation of gRPC services into MCP tools via the gRPC Server Reflection Protocol. This enables seamless integration of gRPC microservices into your MCP ecosystem without manual schema definition.

## Installation & Setup

### 1. Install gRPC Dependencies

gRPC support requires additional dependencies that are not installed by default. Install them using the `[grpc]` extras:

```bash
# Using pip
pip install mcp-contextforge-gateway[grpc]

# Using uv
uv pip install mcp-contextforge-gateway[grpc]

# In requirements.txt
mcp-contextforge-gateway[grpc]>=0.9.0
```

This installs the following packages:
- `grpcio>=1.62.0,<1.68.0`
- `grpcio-reflection>=1.62.0,<1.68.0`
- `grpcio-tools>=1.62.0,<1.68.0`
- `protobuf>=4.25.0`

### 2. Enable the Feature

Set the environment variable to enable gRPC support:

```bash
# In .env file
MCPGATEWAY_GRPC_ENABLED=true

# Or export in shell
export MCPGATEWAY_GRPC_ENABLED=true

# Or set in docker-compose.yml
environment:
  - MCPGATEWAY_GRPC_ENABLED=true
```

### 3. Restart the Gateway

After installing dependencies and enabling the feature, restart MCP Gateway:

```bash
# Development mode
make dev

# Production mode
mcpgateway

# Or with Docker
docker restart mcpgateway
```

### 4. Verify Installation

Check that gRPC support is enabled:

1. Navigate to the Admin UI at `http://localhost:4444/admin`
2. Look for the **🔌 gRPC Services** tab (only visible when enabled)
3. Or check the API: `curl http://localhost:4444/grpc` (should not return 404)

## Overview

The gRPC-to-MCP translation feature allows you to:

- **Automatically discover** gRPC services via server reflection
- **Expose gRPC methods** as MCP tools with zero configuration
- **Translate protocols** between gRPC/Protobuf and MCP/JSON
- **Manage services** through the Admin UI or REST API
- **Support TLS** for secure gRPC connections
- **Track metadata** with comprehensive audit logging

## Quick Start

### 1. CLI: Expose a gRPC Service

The simplest way to expose a gRPC service is via the CLI:

```bash
# Basic usage - expose gRPC service via HTTP/SSE
python3 -m mcpgateway.translate --grpc localhost:50051 --port 9000

# With TLS
python3 -m mcpgateway.translate \
  --grpc myservice.example.com:443 \
  --grpc-tls \
  --grpc-cert /path/to/cert.pem \
  --grpc-key /path/to/key.pem \
  --port 9000

# With gRPC metadata headers
python3 -m mcpgateway.translate \
  --grpc localhost:50051 \
  --grpc-metadata "authorization=Bearer token123" \
  --grpc-metadata "x-tenant-id=customer-1" \
  --port 9000
```

### 2. Admin UI: Register a gRPC Service

1. Navigate to the **Admin UI** at `http://localhost:4444/admin`
2. Click the **🔌 gRPC Services** tab
3. Fill in the registration form:
   - **Service Name**: `my-grpc-service`
   - **Target**: `localhost:50051`
   - **Description**: Optional service description
   - **Enable Server Reflection**: ✓ (recommended)
   - **Enable TLS**: Optional for secure connections
4. Click **Register gRPC Service**

### 3. REST API: Register Programmatically

```bash
# Register a gRPC service
curl -X POST http://localhost:4444/grpc \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "name": "payment-service",
    "target": "payments.example.com:50051",
    "description": "Payment processing gRPC service",
    "reflection_enabled": true,
    "tls_enabled": true,
    "tls_cert_path": "/etc/certs/payment-service.pem",
    "tags": ["payments", "financial"]
  }'
```

## How It Works

### Service Discovery via Reflection

When you register a gRPC service with `reflection_enabled: true`, the gateway:

1. **Connects** to the gRPC server at the specified target
2. **Uses** the [gRPC Server Reflection Protocol](https://grpc.io/docs/guides/reflection/) to discover available services
3. **Parses** service descriptors to extract methods and message types
4. **Stores** discovered metadata in the database
5. **Exposes** each gRPC method as an MCP tool

### Protocol Translation

The gateway translates between protocols automatically:

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│  MCP Client │────────▶│  MCP Gateway │────────▶│ gRPC Server │
│  (JSON)     │  HTTP   │  (Translate) │  gRPC   │ (Protobuf)  │
└─────────────┘         └──────────────┘         └─────────────┘
                              │
                              ▼
                        [Reflection]
                        Discover services,
                        methods, schemas
```

**Request Flow:**
1. Client calls MCP tool: `payment-service.ProcessPayment`
2. Gateway looks up gRPC service and method
3. Gateway converts JSON request → Protobuf message
4. Gateway invokes gRPC method
5. Gateway converts Protobuf response → JSON
6. Gateway returns JSON to MCP client

## Configuration

### Environment Variables

```bash
# Enable/disable gRPC support globally
MCPGATEWAY_GRPC_ENABLED=true

# Enable server reflection by default
MCPGATEWAY_GRPC_REFLECTION_ENABLED=true

# Maximum message size (bytes)
MCPGATEWAY_GRPC_MAX_MESSAGE_SIZE=4194304  # 4MB

# Default timeout for gRPC calls (seconds)
MCPGATEWAY_GRPC_TIMEOUT=30

# Enable TLS by default
MCPGATEWAY_GRPC_TLS_ENABLED=false
```

### Service Configuration

Each gRPC service supports the following configuration:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique service identifier |
| `target` | string | Yes | gRPC server address (host:port) |
| `description` | string | No | Human-readable description |
| `reflection_enabled` | boolean | No | Enable automatic discovery (default: true) |
| `tls_enabled` | boolean | No | Use TLS connection (default: false) |
| `tls_cert_path` | string | No | Path to TLS certificate |
| `tls_key_path` | string | No | Path to TLS private key |
| `grpc_metadata` | object | No | gRPC metadata headers |
| `tags` | array | No | Tags for categorization |
| `team_id` | string | No | Team ownership |
| `visibility` | string | No | public/private/team (default: public) |

## Admin UI Operations

### View Registered Services

The gRPC Services tab displays:
- **Service name** and description
- **Status badges**: Active/Inactive, Reachable/Unreachable
- **Configuration**: TLS enabled, Reflection enabled
- **Discovery stats**: Number of services and methods discovered
- **Last reflection time**: When the service was last introspected

### Re-Reflect a Service

Click the **Re-Reflect** button to trigger a new discovery:
- Updates service and method counts
- Refreshes discovered service metadata
- Marks service as reachable/unreachable
- Updates `last_reflection` timestamp

### View Methods

Click **View Methods** to see all discovered gRPC methods:
- Full method name (e.g., `payment.PaymentService.ProcessPayment`)
- Input message type
- Output message type
- Streaming flags (client/server streaming)

### Toggle Service

Use **Activate/Deactivate** to enable/disable a service:
- Disabled services are not available for tool invocation
- Useful for maintenance or testing

### Delete Service

Click **Delete** to permanently remove a service:
- Removes service from database
- Does not affect the actual gRPC server
- Confirmation required

## REST API Reference

### List gRPC Services

```bash
GET /grpc?include_inactive=false&team_id=TEAM_ID
```

**Response:**
```json
[
  {
    "id": "abc123",
    "name": "payment-service",
    "target": "payments.example.com:50051",
    "enabled": true,
    "reachable": true,
    "service_count": 3,
    "method_count": 15,
    "last_reflection": "2025-10-05T10:30:00Z"
  }
]
```

### Get Service Details

```bash
GET /grpc/{service_id}
```

### Create Service

```bash
POST /grpc
Content-Type: application/json

{
  "name": "user-service",
  "target": "localhost:50052",
  "reflection_enabled": true
}
```

### Update Service

```bash
PUT /grpc/{service_id}
Content-Type: application/json

{
  "description": "Updated description",
  "enabled": true
}
```

### Toggle Service

```bash
POST /grpc/{service_id}/state
```

### Delete Service

```bash
POST /grpc/{service_id}/delete
```

### Trigger Reflection

```bash
POST /grpc/{service_id}/reflect
```

**Response:**
```json
{
  "id": "abc123",
  "name": "payment-service",
  "service_count": 3,
  "method_count": 15,
  "reachable": true,
  "last_reflection": "2025-10-05T10:35:00Z"
}
```

### Get Service Methods

```bash
GET /grpc/{service_id}/methods
```

**Response:**
```json
{
  "methods": [
    {
      "service": "payment.PaymentService",
      "method": "ProcessPayment",
      "full_name": "payment.PaymentService.ProcessPayment",
      "input_type": "payment.PaymentRequest",
      "output_type": "payment.PaymentResponse",
      "client_streaming": false,
      "server_streaming": false
    }
  ]
}
```

## Team Management

gRPC services support team-scoped access control:

```json
{
  "name": "internal-service",
  "target": "internal.corp:50051",
  "team_id": "team-123",
  "visibility": "team"
}
```

**Visibility options:**
- `public`: Accessible to all users
- `private`: Only accessible to owner
- `team`: Accessible to team members

## Security Considerations

### TLS Configuration

Always use TLS for production gRPC services:

```json
{
  "name": "secure-service",
  "target": "secure.example.com:443",
  "tls_enabled": true,
  "tls_cert_path": "/etc/ssl/certs/grpc-client.pem",
  "tls_key_path": "/etc/ssl/private/grpc-client.key"
}
```

### Metadata Headers

Use gRPC metadata for authentication:

```json
{
  "name": "auth-service",
  "target": "api.example.com:50051",
  "grpc_metadata": {
    "authorization": "Bearer secret-token",
    "x-api-key": "api-key-value"
  }
}
```

### Network Access

- Ensure the gateway can reach the gRPC server
- Configure firewall rules appropriately
- Use private networks for internal services

## Troubleshooting

### Service Not Reachable

**Problem:** Service shows as "Unreachable" after registration.

**Solutions:**
1. Verify the target address is correct: `telnet host port`
2. Check if server reflection is enabled on the gRPC server
3. Verify network connectivity and firewall rules
4. Check TLS configuration if enabled
5. Click **Re-Reflect** to retry connection

### Reflection Failed

**Problem:** Reflection returns zero services.

**Solutions:**
1. Ensure the gRPC server has reflection enabled
2. For Go servers: import `google.golang.org/grpc/reflection`
3. For Python servers: use `grpc_reflection.v1alpha.reflection`
4. Verify the server is running and accepting connections

### TLS Connection Errors

**Problem:** TLS connection fails.

**Solutions:**
1. Verify certificate paths are correct
2. Ensure certificates are readable by the gateway
3. Check certificate expiration dates
4. Verify the server's TLS configuration
5. Test with `openssl s_client -connect host:port`

### Method Not Found

**Problem:** Calling a gRPC method returns "method not found".

**Solutions:**
1. Click **Re-Reflect** to refresh service discovery
2. Verify the method name matches exactly (case-sensitive)
3. Check the service is enabled
4. Ensure the gRPC server hasn't changed

## Examples

### Example 1: Expose Local gRPC Service

```bash
# Start a test gRPC server on localhost:50051
# (Assuming it has reflection enabled)

# Expose via MCP Gateway CLI
python3 -m mcpgateway.translate \
  --grpc localhost:50051 \
  --port 9000

# Now accessible at:
# http://localhost:9000/sse
```

### Example 2: Register Cloud gRPC Service

```bash
# Register a production gRPC service with TLS
curl -X POST http://localhost:4444/grpc \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "prod-payment-service",
    "target": "payments.prod.example.com:443",
    "description": "Production payment processing",
    "reflection_enabled": true,
    "tls_enabled": true,
    "grpc_metadata": {
      "authorization": "Bearer prod-token"
    },
    "tags": ["production", "payments", "critical"]
  }'
```

### Example 3: Multi-Service Discovery

```python
# Python script to auto-register multiple gRPC services
import requests

services = [
    {"name": "users", "target": "users.svc.cluster.local:50051"},
    {"name": "orders", "target": "orders.svc.cluster.local:50051"},
    {"name": "inventory", "target": "inventory.svc.cluster.local:50051"},
]

for svc in services:
    response = requests.post(
        "http://localhost:4444/grpc",
        json={
            **svc,
            "reflection_enabled": True,
            "tags": ["microservices", "k8s"]
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    print(f"Registered {svc['name']}: {response.status_code}")
```

## Limitations

### Current Limitations

1. **Method Invocation**: Full protobuf message conversion is not yet implemented in `translate_grpc.py`
2. **Streaming**: Server-streaming methods are partially implemented
3. **Complex Types**: Nested protobuf messages may have limited support
4. **Custom Options**: Protobuf custom options are not preserved

### Planned Enhancements

- Full bidirectional streaming support
- Advanced protobuf type mapping
- Custom interceptors for authentication
- Metrics and observability integration
- Auto-reload on service changes

## Related Documentation

- [mcpgateway.translate CLI](mcpgateway-translate.md)
- [Features Overview](../overview/features.md)
- [REST API Reference](../api/rest-api.md)
- [gRPC Server Reflection Protocol](https://grpc.io/docs/guides/reflection/)
