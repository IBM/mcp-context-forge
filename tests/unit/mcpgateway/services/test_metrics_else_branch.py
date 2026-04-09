# -*- coding: utf-8 -*-
"""Test for metrics.py else branch (line 84) coverage.

This test covers line 84 of metrics.py which executes when
prometheus_server_scoped_metrics is False.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import subprocess
import sys


def test_metrics_module_with_feature_disabled():
    """Test metrics.py line 84 by importing module with feature disabled.

    This test runs in a subprocess with PROMETHEUS_SERVER_SCOPED_METRICS=false
    to execute the else branch (line 84) of the module-level conditional.
    """
    test_script = """
import os
os.environ['PROMETHEUS_SERVER_SCOPED_METRICS'] = 'false'

# Now import metrics - this should execute line 84 (else branch)
from mcpgateway.services import metrics
from mcpgateway.config import settings

# Verify feature is disabled
assert settings.prometheus_server_scoped_metrics is False, "Feature should be disabled"

# Verify _tool_labels was set to only tool_name (line 84 path)
assert hasattr(metrics, '_tool_labels'), "_tool_labels should exist"
assert metrics._tool_labels == ["tool_name"], f"Expected ['tool_name'], got {metrics._tool_labels}"

# Verify counter was created with only tool_name label
assert hasattr(metrics, 'tool_timeout_counter'), "tool_timeout_counter should exist"

print("SUCCESS: Line 84 was executed (feature disabled path)")
"""

    result = subprocess.run(
        [sys.executable, "-c", test_script],
        capture_output=True,
        text=True,
        env={
            **subprocess.os.environ,
            "PROMETHEUS_SERVER_SCOPED_METRICS": "false",
        },
    )

    assert result.returncode == 0, f"Subprocess failed: {result.stderr}"
    assert "SUCCESS" in result.stdout, f"Test logic failed: {result.stdout}"
