"""
Policy Engine Plugin - Admin Backend

This module provides FastAPI routes for the policy engine admin backend.
It includes:
- Policy management (CRUD operations)
- Waiver management (approval/rejection workflow)
- Compliance monitoring and reporting
- Dashboard statistics and timeline data
"""

# Local
from .admin import router as admin_router
from .api import router as api_router

__all__ = ["api_router", "admin_router"]
