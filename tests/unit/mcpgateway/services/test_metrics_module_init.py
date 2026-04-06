# -*- coding: utf-8 -*-
"""Test metrics.py module-level initialization with server_id feature enabled.

This test MUST run in a fresh subprocess to cover line 82 of metrics.py.
Line 82 only executes when the module is first imported with
prometheus_server_scoped_metrics=True, which requires setting the environment
variable BEFORE the module is imported.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import os
import subprocess
import sys


def test_metrics_module_imports_with_server_scoped_feature_enabled():
    """Test that metrics.py line 82 is executed when feature is enabled at import time."""
    # Create a subprocess that sets the env var BEFORE importing
    test_script = """
import os
os.environ['PROMETHEUS_SERVER_SCOPED_METRICS'] = 'true'

# Now import the metrics module - this will execute line 81-84
from mcpgateway.services import metrics

# Verify the feature was enabled
from mcpgateway.config import settings
assert settings.prometheus_server_scoped_metrics is True, "Feature should be enabled"

# Verify the _tool_labels was set correctly (line 82 path)
assert hasattr(metrics, '_tool_labels'), "_tool_labels should exist"
assert metrics._tool_labels == ["tool_name", "server_id"], "Line 82 should have been executed"

# Verify the counter was created with correct labels
assert hasattr(metrics, 'tool_timeout_counter'), "tool_timeout_counter should exist"

print("SUCCESS: Line 82 was executed with server_id in labels")
"""

    # Run in subprocess to get fresh module import
    result = subprocess.run(
        [sys.executable, "-c", test_script],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    # Check the subprocess succeeded
    assert result.returncode == 0, f"Subprocess failed: {result.stderr}"
    assert "SUCCESS" in result.stdout, f"Test logic failed: {result.stdout}"


def test_metrics_module_imports_with_server_scoped_feature_disabled():
    """Test that metrics.py line 84 is executed when feature is disabled at import time."""
    # Create a subprocess that explicitly sets the env var to false
    test_script = """
import os
os.environ['PROMETHEUS_SERVER_SCOPED_METRICS'] = 'false'

# Now import the metrics module - this will execute line 81-84
from mcpgateway.services import metrics

# Verify the feature was disabled
from mcpgateway.config import settings
assert settings.prometheus_server_scoped_metrics is False, "Feature should be disabled"

# Verify the _tool_labels was set correctly (line 84 path)
assert hasattr(metrics, '_tool_labels'), "_tool_labels should exist"
assert metrics._tool_labels == ["tool_name"], "Line 84 should have been executed (no server_id)"

# Verify the counter was created with correct labels
assert hasattr(metrics, 'tool_timeout_counter'), "tool_timeout_counter should exist"

print("SUCCESS: Line 84 was executed without server_id in labels")
"""

    # Run in subprocess to get fresh module import
    result = subprocess.run(
        [sys.executable, "-c", test_script],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    # Check the subprocess succeeded
    assert result.returncode == 0, f"Subprocess failed: {result.stderr}"
    assert "SUCCESS" in result.stdout, f"Test logic failed: {result.stdout}"
