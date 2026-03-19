# -*- coding: utf-8 -*-
"""Root conftest.py for pytest configuration.

This file handles conditional test collection based on optional dependencies.
"""

# Check if grpc is available for conditional doctest collection
try:
    import grpc  # noqa: F401

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

# Modules that require grpc - skip collection if grpc not installed
# These patterns are checked against the full path string
GRPC_DEPENDENT_PATHS = [
    "plugins/framework/external/grpc/",
    "plugins/framework/external/proto_convert.py",
    "plugins/framework/external/unix/",
]


def pytest_ignore_collect(collection_path, config):
    """Skip collecting grpc-dependent modules when grpc is not installed."""
    if HAS_GRPC:
        return None

    path_str = str(collection_path)
    for pattern in GRPC_DEPENDENT_PATHS:
        if pattern in path_str:
            return True

    return None
