# -*- coding: utf-8 -*-
"""Sensitive query-value redaction at the request logging boundary."""

import logging
import traceback
from urllib.parse import urlencode
from unittest.mock import MagicMock

from fastapi import HTTPException
import orjson
import pytest
from starlette.requests import Request

from mcpgateway.middleware import request_logging_middleware
from mcpgateway.middleware.request_logging_middleware import RequestLoggingMiddleware


@pytest.mark.asyncio
async def test_detailed_and_structured_logs_redact_query_secrets_before_denial(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_query = {
        "token": "query-token-sentinel",
        "access_token": "access-token-sentinel",
        "api_key": "api-underscore-sentinel",  # pragma: allowlist secret
        "api-key": "api-hyphen-sentinel",  # pragma: allowlist secret
        "authorization": "authorization-sentinel",
        "credential": "credential-sentinel",
        "secret": "secret-sentinel",  # pragma: allowlist secret
        "password": "password-sentinel",  # pragma: allowlist secret
        "apikey": "apikey-sentinel",  # pragma: allowlist secret
        "auth_token": "auth-token-sentinel",
        "key": "key-sentinel",
        "pwd": "pwd-sentinel",
    }
    structured_logger = MagicMock()
    monkeypatch.setattr(request_logging_middleware, "structured_logger", structured_logger)
    caplog.set_level(logging.INFO, logger=request_logging_middleware.logger.name)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/machine",
            "scheme": "https",
            "server": ("gateway.test", 443),
            "client": ("127.0.0.1", 1234),
            "headers": [],
            "query_string": urlencode({**secret_query, "q": "safe"}).encode(),
        },
        receive=receive,
    )

    async def deny(_request: Request):
        raise HTTPException(status_code=401, detail="Access denied")

    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=True, log_detailed_requests=True, log_request_start=True)
    with pytest.raises(HTTPException) as denied:
        await middleware.dispatch(request, deny)

    structured_fields = [call.kwargs for call in structured_logger.log.call_args_list]
    serialized_fields = orjson.dumps(
        [{key: str(value) if key == "error" else value for key, value in fields.items()} for fields in structured_fields]
    ).decode()
    representations = [
        caplog.text,
        repr([record.getMessage() for record in caplog.records]),
        repr([vars(record) for record in caplog.records]),
        repr(structured_fields),
        serialized_fields,
        "".join(traceback.format_exception(denied.type, denied.value, denied.tb)),
    ]
    for value in secret_query.values():
        assert all(value not in representation for representation in representations)
    assert "******" in caplog.text
    assert "******" in repr(structured_fields)
