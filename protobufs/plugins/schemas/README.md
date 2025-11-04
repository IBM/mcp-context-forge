# ContextForge Protobuf Schemas

Language-agnostic schema definitions for the ContextForge plugin framework.

## Why Protobuf?

Enable plugin development in **multiple languages** (Python, Rust, Go, Java) while maintaining a single source of truth for data structures. Protobuf provides:

- **Cross-language compatibility** - Write plugins in Rust/Go, integrate with Python gateway
- **Wire protocol** - Efficient serialization for external plugin communication
- **Schema documentation** - Single canonical definition with field requirements
- **Type safety** - Generated code with strong typing for all languages

## Quick Start

```bash
# Generate protobuf Python classes
cd protobufs/plugins/schemas
./generate_python.sh

# Run tests
pytest tests/unit/mcpgateway/plugins/framework/generated/
```

## Architecture

**Pydantic models** (`mcpgateway/plugins/framework/models.py`) are the canonical Python implementation.

**Protobuf schemas** (`protobufs/plugins/schemas/`) enable cross-language support (Rust, Go, etc.).

**Conversion methods** bridge the two:
```python
# Pydantic → Protobuf
proto_msg = pydantic_model.model_dump_pb()

# Protobuf → Pydantic
pydantic_model = GlobalContext.model_validate_pb(proto_msg)
```

## Schema Structure

```
protobufs/plugins/schemas/mcpgateway/plugins/framework/generated/
├── types.proto       # Shared types (GlobalContext, PluginViolation, etc.)
├── tools.proto          # Tool hook payloads
├── prompts.proto        # Prompt hook payloads
├── resources.proto      # Resource hook payloads
└── agents.proto         # Agent hook payloads
```

## Field Requirements

Protos document field requirements with comments:
- `// REQUIRED` - Must be set
- `// OPTIONAL` - Can be omitted
- `// OPTIONAL - defaults to X` - Default value specified

## Usage

**Python (Pydantic)**:
```python
from mcpgateway.plugins.framework.models import GlobalContext

ctx = GlobalContext(request_id="req-123", user="alice")
```

**Cross-language (Protobuf)**:
```python
# Serialize for external plugin
proto_ctx = ctx.model_dump_pb()
serialized = proto_ctx.SerializeToString()

# Send over wire, receive response...

# Deserialize
from contextforge.plugins.common import types_pb2
proto_ctx = types_pb2.GlobalContext()
proto_ctx.ParseFromString(serialized)
ctx = GlobalContext.model_validate_pb(proto_ctx)
```

**Other languages**: Generate code from protos using standard tools:
```bash
# Rust
protoc --rust_out=. protobufs/plugins/schemas/mcpgateway/plugins/framework/generated/types.proto

# Go
protoc --go_out=. protobufs/plugins/schemas/mcpgateway/plugins/framework/generated/types.proto
```

## Key Features

✅ Pydantic models remain canonical (validation, type safety, Python-native)
✅ Protobuf for wire protocol and cross-language serialization
✅ Lazy loading - protobuf only imported when needed
✅ Follows Pydantic conventions (`model_dump_pb()`, `model_validate_pb()`)