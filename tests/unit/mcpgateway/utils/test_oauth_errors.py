# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_oauth_errors.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for safe OAuth failure classification.
"""

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.utils.oauth_errors import oauth_failure, response_oauth_code


@pytest.mark.parametrize("code", [None, {}, [], "unsafe-provider-text"])
def test_unknown_failure_uses_fixed_guidance(code):
    """Unknown codes cannot expose provider text in guidance."""
    failure = oauth_failure(code)
    assert failure.code == "oauth_error"
    assert "unsafe-provider-text" not in failure.message
    assert not failure.reauthorization_required


@pytest.mark.parametrize(
    "payload,challenge,expected",
    [
        ({"error": {"data": {"error": "insufficient_scope"}}}, "", "insufficient_scope"),
        ({"error": {"data": "unsafe-provider-text"}}, "", None),
        ({"error": "invalid_scope"}, "", "insufficient_scope"),
        ({"error": "unsafe-provider-text"}, "", None),
        ({}, 'Bearer error="invalid_token", error_description="unsafe-provider-text"', "invalid_token"),
        ({}, 'bEaReR error="INSUFFICIENT_SCOPE"', "insufficient_scope"),
        ({}, 'Bearer error="unsafe-provider-text"', None),
        ({}, 'Basic error="invalid_token"', None),
    ],
)
def test_response_code_requires_explicit_allowlisted_evidence(payload, challenge, expected):
    """JSON errors and Bearer challenges preserve only allowlisted codes."""
    response = httpx.Response(403, json=payload, headers={"www-authenticate": challenge})
    assert response_oauth_code(response) == expected


def test_non_json_response_can_supply_bearer_challenge():
    """A Bearer challenge remains usable when JSON decoding fails."""
    response = httpx.Response(401, text="unsafe-provider-text", headers={"www-authenticate": 'Bearer error="invalid_token"'})
    assert response_oauth_code(response) == "invalid_token"
