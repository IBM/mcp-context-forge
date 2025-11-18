# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/instrumentation/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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
