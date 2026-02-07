# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/unix/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Raw Unix socket transport for external plugins.

This transport provides high-performance IPC for local plugins using
length-prefixed protobuf messages over Unix domain sockets.
"""

from mcpgateway.plugins.framework.external.unix.client import UnixSocketExternalPlugin

__all__ = ["UnixSocketExternalPlugin"]
