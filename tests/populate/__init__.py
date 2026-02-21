# -*- coding: utf-8 -*-
"""REST API data population framework.

This module populates ContextForge with realistic test data by calling
the actual REST API endpoints, exercising the full write path including
Pydantic validation, auth middleware, RBAC, and side effects.
"""

__version__ = "1.0.0"
