# -*- coding: utf-8 -*-
"""Location: ./tests/populate/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

REST API data population framework.

This module populates ContextForge with realistic test data by calling
the actual REST API endpoints, exercising the full write path including
Pydantic validation, auth middleware, RBAC, and side effects.
"""

__version__ = "1.0.0"
