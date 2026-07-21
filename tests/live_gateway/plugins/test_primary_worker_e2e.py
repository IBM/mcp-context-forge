# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_primary_worker_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end test for primary-worker election.

Run via ``make test-primary-worker-e2e`` (set ``ELECTION_BACKEND=redis`` to
exercise the redis backend), which boots a local >=2 worker gateway with two
plugins:

- a gated non-hook plugin -> its side effect must run once (marker has 1 line).
- an ungated hook plugin -> election must NOT suppress it, so it loads on every
  worker (hook marker has one line per worker).
"""

# Standard
import os

# Third-Party
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import skip_no_gateway

MARKER_FILE = os.environ.get("MCPGW_PRIMARY_WORKER_E2E_MARKER", "/tmp/mcpgw_primary_worker_e2e.log")  # nosec B108 - test artifact
HOOK_MARKER_FILE = os.environ.get("MCPGW_PRIMARY_WORKER_E2E_HOOK_MARKER", "/tmp/mcpgw_primary_worker_e2e_hook.log")  # nosec B108 - test artifact
EXPECTED_WORKERS = int(os.environ.get("PRIMARY_WORKER_E2E_WORKERS", "2"))

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def _distinct_pids(path):
    """Return the set of distinct ``pid=`` values written to a marker file."""
    with open(path, encoding="utf-8") as fh:
        return {ln.split("pid=")[1].split()[0] for ln in fh.read().splitlines() if "pid=" in ln}


@skip_no_gateway
def test_gated_side_effect_runs_on_exactly_one_worker():
    """The gated non-hook side effect runs once across all workers."""
    if not os.path.exists(MARKER_FILE):
        pytest.skip(f"marker file {MARKER_FILE} not found — run via make test-primary-worker-e2e")

    with open(MARKER_FILE, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]

    assert len(lines) == 1, f"expected exactly one primary worker to run the side effect, got {len(lines)}: {lines}"


@skip_no_gateway
def test_hook_plugin_loads_on_every_worker():
    """Election must not suppress hook plugins: the ungated hook plugin loads on all workers."""
    if not os.path.exists(HOOK_MARKER_FILE):
        pytest.skip(f"hook marker file {HOOK_MARKER_FILE} not found — run via make test-primary-worker-e2e")

    pids = _distinct_pids(HOOK_MARKER_FILE)
    assert len(pids) == EXPECTED_WORKERS, f"hook plugin should initialize on all {EXPECTED_WORKERS} workers, got {len(pids)}: {pids}"
