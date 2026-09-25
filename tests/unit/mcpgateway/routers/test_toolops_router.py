# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_toolops_router.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for toolops router XSS mitigation.

Verifies that tool_id is sanitized via SecurityValidator.sanitize_display_text()
before being passed to service functions or included in responses.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException

# First-Party
from mcpgateway.routers.toolops_router import (
    enrich_a_tool,
    generate_testcases_for_tool,
)


@pytest.fixture
def allow_permission(monkeypatch):
    """Allow permission checks in require_permission wrapper."""

    class DummyPermissionService:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return True

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", DummyPermissionService)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))


class TestToolopsXSSMitigation:
    """Tests for XSS mitigation in toolops router endpoints."""

    @pytest.mark.asyncio
    async def test_generate_testcases_rejects_xss_payload(self, allow_permission):
        """XSS in tool_id raises ValueError (propagates since only JSONDecodeError is caught)."""
        xss_payload = "<script>alert(1)</script>tool123"

        with pytest.raises(ValueError):
            await generate_testcases_for_tool(
                tool_id=xss_payload,
                number_of_test_cases=2,
                number_of_nl_variations=1,
                mode="generate",
                db=MagicMock(),
                _user={"email": "admin", "db": MagicMock()},
            )

    @pytest.mark.asyncio
    async def test_enrich_tool_rejects_xss_payload(self, allow_permission):
        """tool_id with XSS payload raises HTTP 400 (deny-path)."""
        xss_payload = "<img src=x onerror=alert(1)>tool456"

        with pytest.raises(HTTPException) as exc_info:
            await enrich_a_tool(
                tool_id=xss_payload,
                db=MagicMock(),
                _user={"email": "admin", "db": MagicMock()},
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_enrich_tool_rejects_script_pattern(self, allow_permission):
        """tool_id with javascript: pattern raises HTTP 400 (deny-path)."""
        js_payload = "javascript:alert(1)"

        with pytest.raises(HTTPException) as exc_info:
            await enrich_a_tool(
                tool_id=js_payload,
                db=MagicMock(),
                _user={"email": "admin", "db": MagicMock()},
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_generate_testcases_accepts_valid_tool_id(self, allow_permission):
        """Valid tool_id is passed through without sanitization raising error."""
        valid_tool_id = "my-test-tool-123"

        with patch(
            "mcpgateway.routers.toolops_router.validation_generate_test_cases",
            new_callable=AsyncMock,
        ) as mock_generate:
            mock_generate.return_value = []
            await generate_testcases_for_tool(
                tool_id=valid_tool_id,
                number_of_test_cases=2,
                number_of_nl_variations=1,
                mode="generate",
                db=MagicMock(),
                _user={"email": "admin", "db": MagicMock()},
            )

            call_args = mock_generate.call_args
            actual_tool_id = call_args[0][0] if call_args[0] else call_args[1].get("tool_id")
            assert actual_tool_id == valid_tool_id

    @pytest.mark.asyncio
    async def test_enrich_tool_accepts_valid_tool_id(self, allow_permission):
        """Valid tool_id is passed through without sanitization raising error."""
        valid_tool_id = "my-test-tool-456"

        mock_tool_schema = MagicMock()
        mock_tool_schema.name = "test-tool"
        mock_tool_schema.description = "A test tool"

        with patch(
            "mcpgateway.routers.toolops_router.enrich_tool",
            new_callable=AsyncMock,
        ) as mock_enrich:
            mock_enrich.return_value = ("Enriched description", mock_tool_schema)
            result = await enrich_a_tool(
                tool_id=valid_tool_id,
                db=MagicMock(),
                _user={"email": "admin", "db": MagicMock()},
            )

            assert result["tool_id"] == valid_tool_id
            assert result["tool_name"] == "test-tool"

    @pytest.mark.asyncio
    async def test_generate_testcases_handles_none_tool_id(self, allow_permission):
        """None tool_id is handled gracefully (does not crash)."""
        with patch(
            "mcpgateway.routers.toolops_router.validation_generate_test_cases",
            new_callable=AsyncMock,
        ) as mock_generate:
            mock_generate.return_value = []
            result = await generate_testcases_for_tool(
                tool_id=None,
                number_of_test_cases=2,
                number_of_nl_variations=1,
                mode="generate",
                db=MagicMock(),
                _user={"email": "admin", "db": MagicMock()},
            )

            assert result == []

    @pytest.mark.asyncio
    async def test_enrich_tool_handles_none_tool_id(self, allow_permission):
        """None tool_id raises HTTP 400 due to str concatenation with None."""
        mock_tool_schema = MagicMock()
        mock_tool_schema.name = "test-tool"
        mock_tool_schema.description = "A test tool"

        with patch(
            "mcpgateway.routers.toolops_router.enrich_tool",
            new_callable=AsyncMock,
        ) as mock_enrich:
            mock_enrich.return_value = ("Enriched description", mock_tool_schema)
            with pytest.raises(HTTPException) as exc_info:
                await enrich_a_tool(
                    tool_id=None,
                    db=MagicMock(),
                    _user={"email": "admin", "db": MagicMock()},
                )

            assert exc_info.value.status_code == 400
