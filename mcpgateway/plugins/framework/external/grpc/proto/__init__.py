# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/grpc/proto/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Protocol buffer generated modules for gRPC plugin transport.

This package contains the generated protobuf and gRPC stubs.
Run `make grpc-proto` to regenerate after modifying plugin_service.proto.
"""

try:
    from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2
    from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2_grpc

    __all__ = ["plugin_service_pb2", "plugin_service_pb2_grpc"]
except ImportError:
    # Generated files may not exist yet - run `make grpc-proto`
    pass
