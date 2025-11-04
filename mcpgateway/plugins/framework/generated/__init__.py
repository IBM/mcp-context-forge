# -*- coding: utf-8 -*-
"""Generated protobuf Python classes for ContextForge plugins.

This package contains standard protobuf Python classes (_pb2.py files) generated
from protobuf schemas. These are used for cross-language serialization.

The canonical Python implementation uses Pydantic models in mcpgateway.plugins.framework.models
which have model_dump_pb() and model_validate_pb() methods for conversion.

Generated using standard protoc from schemas in protobufs/plugins/schemas/
"""

# Import well-known types to ensure they're loaded into the descriptor pool
# This prevents "Depends on file 'google/protobuf/any.proto', but it has not been loaded" errors
try:
    # Third-Party
    from google.protobuf import any_pb2 as _  # noqa: F401
    from google.protobuf import struct_pb2 as _  # noqa: F401

    # Import types_pb2 first since other pb2 modules depend on it
    # First-Party
    from mcpgateway.plugins.framework.generated import types_pb2 as _  # noqa: F401
except ImportError:
    # Protobuf not installed, which is fine - these conversions are optional
    pass
