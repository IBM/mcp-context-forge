# -*- coding: utf-8 -*-
"""Root conftest.py for pytest configuration.

This file handles conditional test collection based on optional dependencies.
"""

# Third-Party
from packaging.version import Version
import pytest

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


# Upstream workaround for pytest 9.1.0 and 9.1.1 (pytest-dev/pytest#14635).
# These versions bind conftest fixtures to the first Directory node of a path.
# Interleaved file arguments make pytest collect that path again as a new node.
# The new node gets no conftest fixtures, so autouse fixtures do not run.
# Example: `pytest a/sub/test_x.py a/test_y.py a/sub/test_z.py`.
# pytest-dev/pytest#14645 fixes this. Remove this hook when the minimum pytest version includes it.
_PYTEST_DUPLICATE_DIRECTORY_BUG = Version("9.1.0") <= Version(pytest.__version__) <= Version("9.1.1")
_first_directory_nodes: dict = {}


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):
    """Register a conftest's fixtures on re-collected duplicate Directory nodes (pytest 9.1.0-9.1.1)."""
    report = yield
    if not _PYTEST_DUPLICATE_DIRECTORY_BUG or not isinstance(collector, pytest.Directory):
        return report

    first = _first_directory_nodes.setdefault(collector.path, collector)
    if first is not collector:
        conftest = collector.config.pluginmanager.get_plugin(str(collector.path / "conftest.py"))
        if conftest is not None:
            collector.session._fixturemanager.parsefactories(holder=conftest, node=collector)  # pylint: disable=protected-access
    return report
