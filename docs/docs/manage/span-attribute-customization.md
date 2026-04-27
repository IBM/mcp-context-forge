# Customizing OpenTelemetry Span Attributes

The SpanAttributeCustomizer plugin allows you to customize OpenTelemetry span attributes at runtime for enhanced observability, cost attribution, and compliance.

## Overview

The plugin provides six core capabilities:

1. **Attribute Name Mapping** - Rename span attribute keys for compliance/standards
2. **Global Attributes** - Add attributes to all spans
3. **Per-Tool Overrides** - Customize attributes for specific tools
4. **Attribute Transformations** - Hash, uppercase, lowercase, or truncate values
5. **Conditional Attributes** - Add attributes based on runtime conditions
6. **Attribute Removal** - Remove sensitive attributes for privacy/compliance

## Quick Start

### 1. Enable the Plugin

Add to `plugins/config.yaml`:

```yaml
plugins:
  - name: "SpanAttributeCustomizer"
    kind: "plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin"
    hooks: ["tool_pre_invoke", "tool_post_invoke", "resource_pre_fetch", "resource_post_fetch"]
    mode: "permissive"
    priority: 10
    config:
      global_attributes:
        environment: "production"
        region: "us-east-1"
```

### 2. Enable Plugins

In `.env`:

```bash
PLUGINS_ENABLED=true
PLUGINS_CONFIG_FILE=plugins/config.yaml
```

### 3. Restart Gateway

```bash
make serve
```

## Configuration Options

### Attribute Name Mapping

Rename span attribute keys to match compliance or organizational standards:

```yaml
config:
  attribute_mapping:
    # Rename plugin span attributes
    "plugin.name": "controls.artifact.name"
    "plugin.uuid": "controls.artifact.id"
    "plugin.mode": "controls.enforcement.mode"
    "plugin.priority": "controls.execution.priority"
    "plugin.timeout": "controls.execution.timeout"

    # Rename tool span attributes
    "tool.name": "service.component.name"
    "tool.arguments": "service.component.inputs"
```

**Use Cases:**
- **Compliance**: Match security/audit naming standards (e.g., NIST, ISO)
- **Organizational Standards**: Align with internal naming conventions
- **Multi-System Integration**: Normalize attributes across different observability platforms

**How It Works:**
1. Mapping is applied to ALL spans (tools, resources, plugins)
2. Original attribute names are replaced with mapped names
3. Unmapped attributes retain their original names
4. Works alongside other features (custom attributes, removals, transformations)

**Example Result:**

Before mapping:
```json
{
  "plugin.name": "PIIFilterPlugin",
  "plugin.mode": "enforce",
  "tool.name": "weather_api"
}
```

After mapping:
```json
{
  "controls.artifact.name": "PIIFilterPlugin",
  "controls.enforcement.mode": "enforce",
  "service.component.name": "weather_api"
}
```

### Global Attributes

Add attributes to all spans:

```yaml
config:
  global_attributes:
    environment: "production"
    region: "us-east-1"
    team: "platform"
    deployment: "k8s-cluster-1"
```

### Per-Tool Overrides

Customize attributes for specific tools:

```yaml
config:
  tool_overrides:
    weather_api:
      attributes:
        service: "weather"
        cost_center: "engineering"
        sla_tier: "gold"
    database_query:
      attributes:
        service: "database"
      remove_attributes:
        - "tool.arguments"  # Remove sensitive query parameters
```

### Attribute Transformations

Transform attribute values:

```yaml
config:
  transformations:
    - field: "user.email"
      operation: "hash"  # SHA-256 hash (16 chars) for PII masking
    - field: "team_id"
      operation: "uppercase"
    - field: "description"
      operation: "truncate"
      params:
        max_length: 100
```

**Supported Operations:**

- `hash` - SHA-256 hash (truncated to 16 characters)
- `uppercase` - Convert to uppercase
- `lowercase` - Convert to lowercase
- `truncate` - Truncate to max length (default: 50)

### Conditional Attributes

Add attributes based on conditions:

```yaml
config:
  conditions:
    - when: "tool.name == \"sensitive_operation\""
      add:
        audit_required: true
        compliance_level: "high"
    - when: "tool.name == \"payment_processing\""
      add:
        pci_dss_scope: true
        data_classification: "confidential"
```

**Condition Syntax:**

Currently supports simple equality checks:
- `tool.name == "value"` - Match tool name

### Attribute Removal

Remove attributes globally or per-tool:

```yaml
config:
  # Global removal
  remove_attributes:
    - "internal_debug_info"
    - "temporary_data"

  # Per-tool removal
  tool_overrides:
    sensitive_tool:
      remove_attributes:
        - "tool.arguments"
        - "user.email"
```

## Use Cases

### Cost Attribution

Track billing per tenant or team:

```yaml
config:
  global_attributes:
    tenant_id: "team-123"  # Static value - dynamic templating not supported
    cost_center: "engineering"
    billing_code: "PROJ-123"
```

### Compliance & Privacy

Add regulatory attributes and mask PII:

```yaml
config:
  global_attributes:
    gdpr_compliant: true
    data_classification: "confidential"
    retention_policy: "90_days"

  transformations:
    - field: "user.email"
      operation: "hash"
    - field: "user.phone"
      operation: "hash"

  remove_attributes:
    - "user.ssn"
    - "credit_card"
```

### Multi-Region Tracking

Track deployment regions and availability zones:

```yaml
config:
  global_attributes:
    region: "us-east-1"
    availability_zone: "us-east-1a"
    datacenter: "dc-01"
```

### Service Mesh Integration

Add service mesh metadata:

```yaml
config:
  global_attributes:
    service.name: "contextforge-gateway"
    service.version: "1.0.0"
    service.namespace: "production"
    k8s.cluster.name: "prod-cluster"
    k8s.pod.name: "gateway-pod-abc123"  # Static value - use environment variables for dynamic values
```

**Note:** Template syntax like `{{ POD_NAME }}` is shown for illustration only. The plugin does not support Jinja2 templating. Use static values or retrieve dynamic values from environment variables during plugin initialization.

### Audit & Security

Track security-sensitive operations:

```yaml
config:
  conditions:
    - when: "tool.name == \"admin_operation\""
      add:
        security_audit: true
        requires_approval: true
        audit_log_level: "high"
```

## Complete Example

```yaml
plugins:
  - name: "SpanAttributeCustomizer"
    kind: "plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin"
    hooks: ["tool_pre_invoke", "tool_post_invoke", "resource_pre_fetch", "resource_post_fetch"]
    mode: "permissive"
    priority: 10
    config:
      # Global attributes for all spans
      global_attributes:
        environment: "production"
        region: "us-east-1"
        team: "platform"
        deployment: "k8s-cluster-1"

      # Per-tool overrides
      tool_overrides:
        weather_api:
          attributes:
            service: "weather"
            cost_center: "engineering"
        database_query:
          attributes:
            service: "database"
          remove_attributes:
            - "tool.arguments"

      # Attribute transformations
      transformations:
        - field: "user.email"
          operation: "hash"
        - field: "team_id"
          operation: "uppercase"
        - field: "description"
          operation: "truncate"
          params:
            max_length: 100

      # Conditional attributes
      conditions:
        - when: "tool.name == \"sensitive_operation\""
          add:
            audit_required: true
            compliance_level: "high"

      # Global attribute removal
      remove_attributes:
        - "internal_debug_info"
        - "temporary_data"
```

## Verification

### View Attributes in Jaeger

1. Open Jaeger UI
2. Search for traces
3. Click on a trace
4. Expand span details
5. View "Tags" section for custom attributes

### Query by Custom Attributes

In Jaeger, you can filter traces by custom attributes:

```
tags.environment="production" AND tags.team="platform"
```

### Prometheus Metrics

Custom attributes are also available in Prometheus metrics:

```promql
http_requests_total{environment="production",region="us-east-1"}
```

## Performance

- **Overhead**: < 5ms per span
- **Zero overhead** when plugin is disabled
- Attributes are computed once per tool invocation
- Transformations are applied in-memory

## Security Considerations

- Hash transformation uses SHA-256
- Attribute removal happens before database persistence
- No sensitive data is logged by the plugin
- PII masking is applied before span creation

## Troubleshooting

### Plugin Not Loading

Check logs for initialization errors:

```bash
grep "SpanAttributeCustomizer" logs/gateway.log
```

### Attributes Not Appearing

1. Verify plugin is enabled: `PLUGINS_ENABLED=true`
2. Check plugin mode is not `disabled`
3. Verify hooks are configured correctly
4. Check observability is enabled: `OBSERVABILITY_ENABLED=true`

### Transformation Errors

Check logs for transformation warnings:

```bash
grep "Failed to apply transformation" logs/gateway.log
```

## Related Documentation

- [OpenTelemetry Span Attributes](../architecture/otel-span-attributes.md)
- [Plugin Framework](../architecture/plugins.md)
- [Observability Configuration](./observability.md)
- [Plugin README](../../plugins/span_attribute_customizer/README.md)
