# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_tool_preview_scoping.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for the REST preview restriction on server-scoped tokens.
"""

# Standard
from unittest.mock import MagicMock

# Third-Party
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
import pytest
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.middleware.token_scoping import TokenScopingMiddleware
from tests.helpers.auth import make_test_jwt


@pytest.mark.parametrize("path", ["/tools/preview/echo", "/v1/tools/preview/echo"])
@pytest.mark.parametrize("requested_server_id", ["server-own", "server-other"])
def test_server_scoped_token_is_rejected_before_preview(path, requested_server_id):
    """A signed server-scoped token cannot reach preview, even for its own server."""
    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=TokenScopingMiddleware())
    preview_handler = MagicMock(return_value={"validated": True})

    @app.post(path)
    def _preview():
        return preview_handler()

    body = {"server_id": requested_server_id, "arguments": {"message": "hello"}}
    token = make_test_jwt(
        email="scoped@example.com",
        teams=[],
        scopes={"server_id": "server-own", "permissions": ["tools.preview"]},
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        preview_handler.assert_not_called()

        unrestricted_token = make_test_jwt(email="scoped@example.com", teams=[], scopes={"permissions": ["tools.preview"]})
        control = client.post(path, json=body, headers={"Authorization": f"Bearer {unrestricted_token}"})

    assert control.status_code == status.HTTP_200_OK
    preview_handler.assert_called_once_with()
