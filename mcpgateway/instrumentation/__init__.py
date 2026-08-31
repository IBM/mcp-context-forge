# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/instrumentation/__init__.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Automatic instrumentation for observability.

This module provides automatic instrumentation for common libraries:
- SQLAlchemy database queries
- HTTP clients (future)
- Redis operations (future)
"""

# pylint: disable=cyclic-import
# Cyclic import is intentional and broken by lazy imports in sqlalchemy.py
from mcpgateway.instrumentation.sqlalchemy import instrument_sqlalchemy

__all__ = ["instrument_sqlalchemy"]
