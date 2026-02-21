# -*- coding: utf-8 -*-
# pylint: disable=ungrouped-imports
"""Location: ./mcpgateway/plugins/framework/external/grpc/proto/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Protocol buffer generated modules for gRPC plugin transport.

This package contains the generated protobuf and gRPC stubs.
Run `make grpc-proto` to regenerate after modifying plugin_service.proto.
"""

try:
    # Import plugin framework stubs eagerly because plugin transport depends on
    # these at startup.
    from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2
    from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2_grpc
except (ImportError, RuntimeError):
    # Generated files may not exist yet - run `make grpc-proto`
    pass

# Resolve A2A stubs with SDK-first preference to avoid duplicate descriptor
# registration when both ContextForge stubs and official A2A SDK stubs coexist
# in the same process.
try:
    # Third-Party
    from a2a.grpc import a2a_pb2  # type: ignore
    from a2a.grpc import a2a_pb2_grpc  # type: ignore
except (ImportError, RuntimeError, TypeError):
    try:
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2
        from mcpgateway.plugins.framework.external.grpc.proto import a2a_pb2_grpc
    except (ImportError, RuntimeError, TypeError):
        pass

__all__ = ["a2a_pb2", "a2a_pb2_grpc", "plugin_service_pb2", "plugin_service_pb2_grpc"]
