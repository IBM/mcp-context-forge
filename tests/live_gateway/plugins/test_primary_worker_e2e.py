# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_primary_worker_e2e.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

End-to-end test for primary-worker election.

Run via ``make test-primary-worker-e2e``, which boots a local >=2 worker gateway
with the marker plugin. The gated side effect must run once, so the marker file
has a single line.
"""

# Standard
import os

# Third-Party
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import skip_no_gateway

MARKER_FILE = os.environ.get("MCPGW_PRIMARY_WORKER_E2E_MARKER", "/tmp/mcpgw_primary_worker_e2e.log")  # nosec B108 - test artifact

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


@skip_no_gateway
def test_side_effect_runs_on_exactly_one_worker():
    """The gated non-hook side effect runs once across all workers."""
    if not os.path.exists(MARKER_FILE):
        pytest.skip(f"marker file {MARKER_FILE} not found — start the gateway with the e2e plugin config (make test-primary-worker-e2e)")

    with open(MARKER_FILE, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]

    assert len(lines) == 1, f"expected exactly one primary worker to run the side effect, got {len(lines)}: {lines}"
