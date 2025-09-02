"""
versioning.py

Middleware to handle API versioning for incoming requests.
"""

# Standard
from typing import List


# Fast-track versioning configuration
class VersioningConfig:
    """
    Configuration class for API versioning and experimental access control.
    This class centralizes settings for handling legacy API paths,
    deprecation warnings, and access to experimental features. It allows
    middleware and routers to enforce versioning rules consistently.

    Attributes:
        enable_legacy_support (bool): Whether legacy API paths should still
            be served (0.6.0 behavior). Default is True.
        enable_deprecation_headers (bool): Whether to include deprecation
            headers in responses for legacy routes. Default is True.
        legacy_removal_version (str): Version at which legacy routes are fully
            removed. Default is "0.7.0".
        legacy_support_removed (bool): Indicates that legacy routes are no
            longer available (0.7.0 behavior). Default is True.
        experimental_access_roles (List[str]): Roles allowed to access
            experimental features. Default is ["platform_admin", "developer"].

    Example:
        from versioning import VersioningConfig

        if VersioningConfig.enable_legacy_support:
            # Serve legacy route
            pass
    """

    # 0.6.0 settings
    enable_legacy_support: bool = True  # Still serve legacy in 0.6.0
    enable_deprecation_headers: bool = True  # Loud warnings
    legacy_removal_version: str = "0.7.0"  # Hard deadline

    # 0.7.0 settings
    legacy_support_removed: bool = True  # No more legacy paths

    # Experimental access
    experimental_access_roles: List[str] = ["platform_admin", "developer"]
