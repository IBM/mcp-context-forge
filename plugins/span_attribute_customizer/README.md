# Span Attribute Customizer Plugin

Customizes OpenTelemetry span attributes for enhanced observability and compliance.

## Overview

This plugin allows you to customize span attributes at various lifecycle points in the request flow. It supports global attributes, per-tool overrides, attribute transformations, conditional attributes, and attribute removal for privacy/compliance requirements.

## Features

- **Attribute Name Mapping**: Rename span attribute keys for compliance/organizational standards
- **Global Attributes**: Add attributes to all spans
- **Per-Tool Overrides**: Customize attributes for specific tools
- **Attribute Transformations**: Hash, uppercase, lowercase, or truncate attribute values
- **Conditional Attributes**: Add attributes based on runtime conditions
- **Attribute Removal**: Remove sensitive attributes for privacy/compliance

## Configuration

Add to `plugins/config.yaml`:

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

      # Per-tool overrides
      tool_overrides:
        weather_api:
          attributes:
            service: "weather"
            cost_center: "engineering"
        database_query:
          remove_attributes: ["tool.arguments"]

      # Attribute transformations
      transformations:
        - field: "user.email"
          operation: "hash"
        - field: "team_id"
          operation: "uppercase"

      # Conditional attributes
      conditions:
        - when: "tool.name == \"sensitive_operation\""
          add:
            audit_required: true
            compliance_level: "high"

      # Global removal list
      remove_attributes:
        - "internal_debug_info"
```

## Configuration Options

### Attribute Name Mapping

Rename span attribute keys to match your compliance or organizational naming standards:

```yaml
attribute_mapping:
  # Rename plugin span attributes
  "plugin.name": "controls.artifact.name"
  "plugin.uuid": "controls.artifact.id"
  "plugin.mode": "controls.enforcement.mode"
  "plugin.priority": "controls.execution.priority"

  # Rename tool span attributes
  "tool.name": "service.component.name"
  "tool.arguments": "service.component.inputs"
```

**Key Points:**
- Applies to ALL spans (tools, resources, plugins)
- Original names are replaced with mapped names
- Unmapped attributes keep their original names
- Works alongside all other features

**Example:**
```yaml
# Before mapping
{
  "plugin.name": "PIIFilter",
  "plugin.mode": "enforce"
}

# After mapping
{
  "controls.artifact.name": "PIIFilter",
  "controls.enforcement.mode": "enforce"
}
```

### Global Attributes

Add attributes that will be included in all spans:

```yaml
global_attributes:
  environment: "production"
  region: "us-east-1"
  deployment: "k8s-cluster-1"
```

### Tool Overrides

Customize attributes for specific tools:

```yaml
tool_overrides:
  weather_api:
    attributes:
      service: "weather"
      cost_center: "engineering"
    remove_attributes: ["sensitive_field"]
```

### Transformations

Transform attribute values:

```yaml
transformations:
  - field: "user.email"
    operation: "hash"  # Hash PII
  - field: "team_id"
    operation: "uppercase"
  - field: "description"
    operation: "truncate"
    params:
      max_length: 100
```

Supported operations:
- `hash`: SHA-256 hash (truncated to 16 chars)
- `uppercase`: Convert to uppercase
- `lowercase`: Convert to lowercase
- `truncate`: Truncate to max length

### Conditional Attributes

Add attributes based on conditions:

```yaml
conditions:
  - when: "tool.name == \"sensitive_operation\""
    add:
      audit_required: true
      compliance_level: "high"
```

### Attribute Removal

Remove attributes globally or per-tool:

```yaml
remove_attributes:
  - "internal_debug_info"
  - "temporary_data"
```

## Use Cases

### Cost Attribution

Track billing per tenant or team:

```yaml
global_attributes:
  tenant_id: "{{ tenant_id }}"
  cost_center: "engineering"
```

### Compliance

Add regulatory attributes:

```yaml
global_attributes:
  gdpr_compliant: true
  data_classification: "confidential"
```

### Privacy

Remove PII from spans:

```yaml
transformations:
  - field: "user.email"
    operation: "hash"
remove_attributes:
  - "user.ssn"
  - "credit_card"
```

### Multi-Region Tracking

Track deployment regions:

```yaml
global_attributes:
  region: "us-east-1"
  availability_zone: "us-east-1a"
```

## Usage

1. Enable the plugin in `plugins/config.yaml`
2. Configure attributes as needed
3. Restart the gateway or hot-reload plugins
4. Verify attributes in observability backend (Jaeger, Zipkin, etc.)

## Performance

- Overhead: < 5ms per span
- Zero overhead when plugin is disabled
- Attributes are computed once per tool invocation

## Security

- Hash transformation uses SHA-256
- Attribute removal happens before database persistence
- No sensitive data is logged

## Related

- Issue #4274: Customizable OpenTelemetry Span Attributes
- Documentation: `docs/docs/architecture/span-attribute-customization.md`
