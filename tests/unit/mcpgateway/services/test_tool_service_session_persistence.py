# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service_session_persistence.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Regression tests for Issue #4697: Upstream MCP session persistence.

Tests verify that request_headers_var ContextVar is properly set during
tool invocation to enable session ID propagation for stateful MCP servers.
"""

import pytest
from unittest.mock import MagicMock

from mcpgateway.transports.context import request_headers_var


class TestUpstreamSessionPersistence:
    """
    Test suite for upstream session persistence (Issue #4697).

    Verifies that invoke_tool properly sets request_headers_var ContextVar
    to enable downstream_session_id_from_request_context() to access session IDs.
    """

    @pytest.mark.asyncio
    async def test_invoke_tool_sets_request_headers_var_for_session_persistence(self):
        """
        Verify that invoke_tool sets request_headers_var ContextVar in PHASE 0.

        This ensures downstream_session_id_from_request_context() can access
        the session ID for upstream session registry binding.

        Regression test for Issue #4697: Without this, multi-step stateful
        workflows (e.g., Playwright) fail because element references become
        invalid across tool calls.
        """
        from mcpgateway.services.tool_service import ToolService

        # Request headers with session ID (simulating a stateful workflow)
        request_headers = {
            "x-mcp-session-id": "downstream-session-abc123",
            "authorization": "Bearer test-token",
        }

        # Create a mock that will raise an exception after PHASE 0
        # This allows us to test just the ContextVar setting without
        # needing to mock the entire tool invocation flow
        tool_service = ToolService()
        mock_db = MagicMock()

        # Make the database query fail immediately after PHASE 0
        mock_db.execute.side_effect = RuntimeError("Test exception after PHASE 0")

        try:
            await tool_service.invoke_tool(
                mock_db,
                "test-tool",
                {"param": "value"},
                request_headers=request_headers,
            )
        except RuntimeError:
            # Expected - we're testing PHASE 0 which happens before the DB query
            pass

        # Verify: Check that request_headers_var was set during PHASE 0
        try:
            current_headers = request_headers_var.get()
            assert current_headers is not None, "request_headers_var was not set during invoke_tool. " "This breaks session persistence for stateful MCP servers (Issue #4697)."
            assert current_headers == request_headers, f"request_headers_var was set to {current_headers}, " f"but expected {request_headers}"
        except LookupError:
            pytest.fail("request_headers_var was not set during invoke_tool. " "PHASE 0 in tool_service.py should set this ContextVar " "to enable session ID propagation (Issue #4697).")

    @pytest.mark.asyncio
    async def test_invoke_tool_skips_setting_request_headers_var_when_none(self):
        """
        Verify that invoke_tool does NOT set request_headers_var when headers are None.

        This prevents polluting the ContextVar with None values when no headers
        are provided (e.g., internal tool calls without HTTP context).
        """
        from mcpgateway.services.tool_service import ToolService

        tool_service = ToolService()
        mock_db = MagicMock()

        # Make the database query fail immediately after PHASE 0
        mock_db.execute.side_effect = RuntimeError("Test exception after PHASE 0")

        # Record the state before the call
        had_value_before = False
        value_before = None
        try:
            value_before = request_headers_var.get()
            had_value_before = True
        except LookupError:
            # No value set before - this is fine
            pass

        try:
            await tool_service.invoke_tool(
                mock_db,
                "test-tool-no-headers",
                {"param": "value"},
                request_headers=None,  # Explicitly None
            )
        except RuntimeError:
            # Expected - we're testing PHASE 0 which happens before the DB query
            pass

        # Verify: request_headers_var should NOT have been modified
        # It should either remain unset or retain its previous value
        try:
            current_headers = request_headers_var.get()
            if had_value_before:
                # If there was a value before, it should be unchanged
                assert current_headers == value_before, (
                    f"request_headers_var was modified from {value_before} to {current_headers}. " "PHASE 0 should skip setting the ContextVar when request_headers is None."
                )
            else:
                # If there was no value before, there still shouldn't be one
                # (or if there is, it shouldn't be None)
                assert current_headers is not None, "request_headers_var was set to None. " "PHASE 0 should skip setting the ContextVar when request_headers is None."
        except LookupError:
            # This is the expected behavior - ContextVar was never set
            # This is correct when request_headers is None
            pass
