# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_observability_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for observability middleware.
"""

import base64
import json
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.requests import Request
from starlette.responses import Response
from mcpgateway.middleware.observability_middleware import (
    ObservabilityMiddleware,
    _get_safe_token_claims_from_request,
)


@pytest.fixture
def mock_request():
    request = MagicMock(spec=Request)
    request.method = "GET"
    request.url.path = "/rpc"
    request.url.query = "param=value"
    request.url.__str__.return_value = "http://testserver/rpc?param=value"
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


@pytest.mark.asyncio
async def test_dispatch_trace_setup_failure_rolls_back_and_closes_db(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", side_effect=Exception("trace fail")):
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200

    db_mock.rollback.assert_called()
    db_mock.close.assert_called()


@pytest.mark.asyncio
async def test_dispatch_trace_setup_cleanup_close_failure_logs_debug(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()
    db_mock.close.side_effect = Exception("close fail")

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", side_effect=Exception("trace fail")), \
         patch("mcpgateway.middleware.observability_middleware.logger.debug") as mock_debug:
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_debug.assert_called()


@pytest.mark.asyncio
async def test_dispatch_end_span_failure_logs_warning(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span", side_effect=Exception("end span fail")), \
         patch.object(middleware.service, "end_trace"), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning:
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_warning.assert_called()


@pytest.mark.asyncio
async def test_dispatch_end_trace_failure_logs_warning(mock_request, mock_call_next):
    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "end_trace", side_effect=Exception("end trace fail")), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning:
        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response.status_code == 200
        mock_warning.assert_called()


@pytest.mark.asyncio
async def test_dispatch_exception_logging_failure_logs_warning(mock_request):
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "add_event", side_effect=Exception("add event fail")), \
         patch.object(middleware.service, "end_trace"), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning:
        with pytest.raises(RuntimeError):
            await middleware.dispatch(mock_request, failing_call_next)
        mock_warning.assert_called()


@pytest.mark.asyncio
async def test_dispatch_end_trace_error_failure_logs_warning(mock_request):
    async def failing_call_next(request):
        raise RuntimeError("Request failed")

    middleware = ObservabilityMiddleware(app=None, enabled=True)
    db_mock = MagicMock()

    with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=db_mock), \
         patch.object(middleware.service, "start_trace", return_value="trace123"), \
         patch.object(middleware.service, "start_span", return_value="span123"), \
         patch.object(middleware.service, "end_span"), \
         patch.object(middleware.service, "add_event"), \
         patch.object(middleware.service, "end_trace", side_effect=Exception("end trace fail")), \
         patch("mcpgateway.middleware.observability_middleware.logger.warning") as mock_warning:
        with pytest.raises(RuntimeError):
            await middleware.dispatch(mock_request, failing_call_next)
        mock_warning.assert_called()


# --- Token claims extraction (_get_safe_token_claims_from_request) ---


def test_get_safe_token_claims_from_request_no_auth():
    """When no Authorization header, returns None."""
    request = MagicMock(spec=Request)
    request.headers = {}
    request.state = MagicMock()
    assert not hasattr(request.state, "token_claims")
    assert _get_safe_token_claims_from_request(request) is None


def test_get_safe_token_claims_from_request_prefers_state():
    """When request.state.token_claims is set, returns only safe keys from it."""
    request = MagicMock(spec=Request)
    request.headers = {}
    request.state = MagicMock()
    request.state.token_claims = {"sub": "user-42", "iss": "https://issuer", "custom_secret": "do-not-store"}
    result = _get_safe_token_claims_from_request(request)
    assert result == {"sub": "user-42", "iss": "https://issuer"}
    assert "custom_secret" not in result


def test_get_safe_token_claims_from_request_bearer_valid():
    """When Bearer token has valid payload, returns safe claims."""
    payload = {"sub": "user-123", "iss": "https://auth.example.com", "iat": 1700000000, "exp": 1700086400}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    # header.payload.signature (minimal valid JWT shape)
    header_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(b"signature").decode().rstrip("=")
    token = f"{header_b64}.{payload_b64}.{sig_b64}"

    request = MagicMock(spec=Request)
    request.headers = {"Authorization": f"Bearer {token}"}
    request.state = MagicMock()
    assert not hasattr(request.state, "token_claims") or not isinstance(getattr(request.state, "token_claims", None), dict)

    result = _get_safe_token_claims_from_request(request)
    assert result is not None
    assert result.get("sub") == "user-123"
    assert result.get("iss") == "https://auth.example.com"
    assert result.get("iat") == 1700000000
    assert result.get("exp") == 1700086400


def test_get_safe_token_claims_from_request_bearer_invalid_returns_none():
    """When Bearer token is malformed, returns None."""
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer not.three.parts"}
    request.state = MagicMock()
    assert _get_safe_token_claims_from_request(request) is None

    request.headers = {"Authorization": "Bearer a.b"}  # only 2 parts
    assert _get_safe_token_claims_from_request(request) is None

    request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}  # not Bearer
    assert _get_safe_token_claims_from_request(request) is None


def test_get_safe_token_claims_from_request_state_not_dict_ignored():
    """When request.state.token_claims is not a dict, fall back to header (or None)."""
    request = MagicMock(spec=Request)
    request.headers = {}
    request.state = MagicMock()
    request.state.token_claims = "not-a-dict"
    result = _get_safe_token_claims_from_request(request)
    assert result is None


@pytest.mark.asyncio
async def test_dispatch_token_claims_disabled_no_token_claims_passed(mock_request, mock_call_next):
    """When observability_store_token_claims is False, start_trace is called with token_claims=None."""
    from mcpgateway.middleware import observability_middleware
    with patch.object(observability_middleware, "settings") as mock_settings:
        mock_settings.observability_store_token_claims = False
        mock_settings.version = "test"
        middleware = ObservabilityMiddleware(app=None, enabled=True)
        with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=MagicMock()), \
             patch.object(middleware.service, "start_trace", return_value="trace123") as mock_start_trace, \
             patch.object(middleware.service, "start_span", return_value="span123"), \
             patch.object(middleware.service, "end_span"), \
             patch.object(middleware.service, "end_trace"), \
             patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session"), \
             patch("mcpgateway.middleware.observability_middleware.parse_traceparent", return_value=(None, None, None)), \
             patch("mcpgateway.middleware.observability_middleware.plugins_trace_id"):
            await middleware.dispatch(mock_request, mock_call_next)
        call_kwargs = mock_start_trace.call_args[1]
        assert call_kwargs.get("token_claims") is None


@pytest.mark.asyncio
async def test_dispatch_token_claims_enabled_passes_claims_and_sets_context(mock_request, mock_call_next):
    """When observability_store_token_claims is True and request has token, start_trace gets token_claims and context is set."""
    payload = {"sub": "user-99", "iss": "https://issuer"}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    header_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip("=")
    token = f"{header_b64}.{payload_b64}.e30"
    mock_request.headers = {"user-agent": "pytest", "traceparent": "00-abc-def-01", "Authorization": f"Bearer {token}"}

    from mcpgateway.middleware import observability_middleware
    from mcpgateway.services.observability_service import current_token_claims
    with patch.object(observability_middleware, "settings") as mock_settings:
        mock_settings.observability_store_token_claims = True
        mock_settings.version = "test"
        middleware = ObservabilityMiddleware(app=None, enabled=True)
        with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=MagicMock()), \
             patch.object(middleware.service, "start_trace", return_value="trace123") as mock_start_trace, \
             patch.object(middleware.service, "start_span", return_value="span123"), \
             patch.object(middleware.service, "end_span"), \
             patch.object(middleware.service, "end_trace"), \
             patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session"), \
             patch("mcpgateway.middleware.observability_middleware.parse_traceparent", return_value=(None, None, None)), \
             patch("mcpgateway.middleware.observability_middleware.plugins_trace_id"):
            await middleware.dispatch(mock_request, mock_call_next)
        call_kwargs = mock_start_trace.call_args[1]
        assert call_kwargs.get("token_claims") is not None
        assert call_kwargs["token_claims"].get("sub") == "user-99"
        assert call_kwargs["token_claims"].get("iss") == "https://issuer"
    # Middleware clears current_token_claims in finally
    assert current_token_claims.get() is None


@pytest.mark.asyncio
async def test_dispatch_token_claims_enabled_no_bearer_passes_none(mock_request, mock_call_next):
    """When observability_store_token_claims is True but no Bearer token, start_trace gets token_claims=None."""
    mock_request.headers = {"user-agent": "pytest", "traceparent": "00-abc-def-01"}  # no Authorization
    from mcpgateway.middleware import observability_middleware
    with patch.object(observability_middleware, "settings") as mock_settings:
        mock_settings.observability_store_token_claims = True
        mock_settings.version = "test"
        middleware = ObservabilityMiddleware(app=None, enabled=True)
        with patch("mcpgateway.middleware.observability_middleware.SessionLocal", return_value=MagicMock()), \
             patch.object(middleware.service, "start_trace", return_value="trace123") as mock_start_trace, \
             patch.object(middleware.service, "start_span", return_value="span123"), \
             patch.object(middleware.service, "end_span"), \
             patch.object(middleware.service, "end_trace"), \
             patch("mcpgateway.middleware.observability_middleware.attach_trace_to_session"), \
             patch("mcpgateway.middleware.observability_middleware.parse_traceparent", return_value=(None, None, None)), \
             patch("mcpgateway.middleware.observability_middleware.plugins_trace_id"):
            await middleware.dispatch(mock_request, mock_call_next)
        call_kwargs = mock_start_trace.call_args[1]
        assert call_kwargs.get("token_claims") is None
