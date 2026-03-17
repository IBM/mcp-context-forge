# Module Descriptor

Every protocol module must expose a stable descriptor that the core can use for
discovery, compatibility checks, health integration, and release validation.

## Required Fields

| Field | Meaning |
|-------|---------|
| `moduleId` | Stable module identifier, for example `mcp-rust-runtime` |
| `protocolFamily` | One of `mcp`, `a2a`, `llm`, `rest-grpc`, or a future family |
| `implementationLanguage` | `python`, `rust`, `go`, or another language identifier |
| `moduleVersion` | Module build or release version |
| `spiVersions` | Supported core SPI versions |
| `runtimeModes` | Supported runtime modes such as `embedded`, `sidecar` |
| `ingressModes` | Whether the module can run behind core routing, direct public ingress, or both |
| `capabilities` | Declared protocol and runtime capabilities |
| `health` | How health and readiness are queried |
| `stats` | Optional runtime metrics surface |
| `pluginParity` | Which plugin-sensitive flows are fully supported, delegated, or not yet supported |
| `fallbackStrategy` | Whether rollback to legacy or embedded path exists |

## Example Descriptor

```json
{
  "moduleId": "a2a-rust-runtime",
  "protocolFamily": "a2a",
  "implementationLanguage": "rust",
  "moduleVersion": "0.1.0",
  "spiVersions": ["v1alpha1"],
  "runtimeModes": ["sidecar"],
  "ingressModes": ["core-routed"],
  "capabilities": {
    "discovery": true,
    "invoke": true,
    "taskState": true,
    "streaming": false,
    "pushNotifications": false
  },
  "health": {
    "readiness": "grpc",
    "liveness": "grpc"
  },
  "pluginParity": {
    "preInvoke": "delegate",
    "postInvoke": "delegate"
  },
  "fallbackStrategy": {
    "supportsRollback": true,
    "fallbackPath": "python-core"
  }
}
```

Second illustrative example for a Go LLM proxy module:

```json
{
  "moduleId": "llm-go-proxy",
  "protocolFamily": "llm",
  "implementationLanguage": "go",
  "moduleVersion": "0.1.0",
  "spiVersions": ["v1alpha1"],
  "runtimeModes": ["sidecar"],
  "ingressModes": ["core-routed"],
  "capabilities": {
    "chatCompletions": true,
    "streaming": true,
    "sessionChat": true,
    "providerRelay": true
  }
}
```

## Capability Taxonomy

Capabilities should be declarative, not inferred from language or module name.

Recommended categories:

- ingress
- transport
- request or response streaming
- session or task state
- replay or resume
- subscriptions
- prompt rendering
- resource reads
- tool or agent invocation
- provider relay
- plugin parity support

## Descriptor Rules

- The descriptor must be available before live traffic.
- Capabilities must be honest. Unsupported optional protocol surfaces must be
  declared as unsupported, not silently dropped.
- The descriptor must be sufficient for the core to decide:
  - whether the module can be started
  - whether a given deployment mode is valid
  - whether the module satisfies release policy for the protocol family

## Protocol-Specific Notes

- A Rust A2A module should declare task-state and invoke support explicitly.
- A Go LLM proxy module should declare both chat-completion and streaming
  support explicitly.
- A REST or gRPC module should declare whether it owns reflection, OpenAPI
  import, or only invocation relay.
