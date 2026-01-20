# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_observability_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for observability middleware.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.requests import Request
from starlette.responses import Response
from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware


@pytest.fixture
def mock_request():
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/api/test"
    request.url.query = "param=value"
    request.url.__str__.return_value = "http://testserver/api/test?param=value"
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {"user-agent": "pytest", "traceparent": "00-abc123-def456-01"}
    request.state = MagicMock()
    return request


@pytest.fixture
def mock_call_next():
    async def _call_next(request):
        return Response("OK", status_code=200)
    return _call_next


@pytest.mark.asyncio
async def test_dispatch_disabled(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=False)
    response = await middleware.dispatch(mock_request, mock_call_next)
    assert response.status_code == 200
    # Since mock_request.state is a MagicMock, trace_id may exist implicitly
    # Ensure middleware did not modify it explicitly
    # Ensure middleware did not set trace_id explicitly
    assert "trace_id" not in mock_request.state.__dict__


@pytest.mark.asyncio
async def test_dispatch_health_check_skipped(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    mock_request.url.path = "/health"
    response = await middleware.dispatch(mock_request, mock_call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_trace_setup_success(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=MagicMock()) as mock_session, \
         patch.object(middleware.service, "start_trace", return_value="trace123") as mock_start_trace, \
         patch.object(middleware.service, "start_span", return_value="span123") as mock_start_span, \
         patch.object(middleware.service, "end_span") as mock_end_span, \
         patch.object(middleware.service, "end_trace") as mock_end_trace, \
         patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session") as mock_attach, \
         patch("mcpgateway.middleware.observability_middleware.parse_traceparent", return_value=("traceX", "spanY", "flags")):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_start_trace.assert_called_once()
        mock_start_span.assert_called_once()
        mock_end_span.assert_called_once()
        mock_end_trace.assert_called_once()
        mock_attach.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_trace_setup_failure(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", side_effect=Exception("DB fail")):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_exception_during_request(mock_request):
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span") as mock_end_span, \
         patch.object(middleware.service, "add_event") as mock_add_event, \
         patch.object(middleware.service, "end_trace") as mock_end_trace:
        with pytest.raises(RuntimeError):
            await middleware.dispatch(mock_request, failing_call_next)
        mock_end_span.assert_called()
        mock_add_event.assert_called()
        mock_end_trace.assert_called()


@pytest.mark.asyncio
async def test_dispatch_close_db_failure(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.close.side_effect = Exception("close fail")
    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "end_trace"):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
