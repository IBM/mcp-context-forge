# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_rest_tool_sigv4.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

SigV4 signing of REST tool invocations through ``ToolService.invoke_tool``.

DNS is faked and the outbound client is an ``httpx.AsyncClient`` on a mock transport, so
the real signing auth runs against the exact bytes httpx sends.
"""

# Standard
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.services.encryption_service import protect_sigv4_config_sync
from mcpgateway.services.tool_service import ToolInvocationError, ToolService
from mcpgateway.utils.services_auth import encode_auth
from mcpgateway.utils.sigv4 import build_stored_sigv4_auth, build_stored_sigv4_httpx_auth, SigV4Auth, SigV4HttpxAuth

# Local
# Reuse the REST-path fixtures of the main tool service tests.
from tests.unit.mcpgateway.services.test_tool_service import (  # noqa: F401  pylint: disable=unused-import
    mock_fresh_db_session,
    mock_gateway,
    mock_global_config_obj,
    mock_logging_services,
    mock_tool,
    reset_tool_lookup_cache,
    setup_db_execute_mock,
)

URL = "https://api.example.com/v1/users/{id}/orders"
ACCESS_KEY = "AKIDEXAMPLE0000000"  # pragma: allowlist secret
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
SESSION_TOKEN = "example-session-token"  # pragma: allowlist secret
SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "note": {"type": "string"}, "q": {"type": "string"}}}
CT_JSON = {"Content-Type": "application/json"}


def plain_config(**overrides):
    """Return a plaintext ``sigv4_config``."""
    config = {"access_key_id": ACCESS_KEY, "secret_access_key": SECRET_KEY, "region": "us-east-1", "service": "execute-api"}
    config.update(overrides)
    return config


def stored_config(**overrides):
    """Return a ``sigv4_config`` as persisted, with encrypted secrets."""
    return protect_sigv4_config_sync(plain_config(**overrides))


class Upstream:
    """Mock upstream that records every request and replies with queued status codes."""

    def __init__(self, statuses=None):
        """Create the upstream.

        Args:
            statuses: Status codes to answer with, in order. Defaults to one 200.
        """
        self.requests = []
        self.statuses = list(statuses or [200])

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Record ``request`` and answer it.

        Args:
            request: The request httpx would send.

        Returns:
            httpx.Response: The queued reply.
        """
        self.requests.append(request)
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return httpx.Response(status, json={"ok": status == 200})


@pytest.fixture
def test_db():
    """Mocked DB session."""
    return Mock()


@pytest.fixture
def service(monkeypatch):
    """ToolService with the real URL validator; only DNS is faked (to a public IP)."""
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.ssrf_protection_enabled", True)
    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    svc = ToolService()
    svc._http_client = AsyncMock()
    svc.get_plugin_manager = AsyncMock()
    return svc


@pytest.fixture
def upstream():
    """Mock upstream with one 200 reply."""
    return Upstream()


@pytest.fixture
def builder(upstream):
    """Patch the isolated client builder so it returns a real httpx client on the mock transport."""
    built = []

    def _build(auth=None):
        client = httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler), auth=auth)
        built.append(SimpleNamespace(client=client, auth=auth))
        return client

    with (
        patch("mcpgateway.services.tool_service.metrics_buffer", Mock(record_tool_metric=Mock())),
        patch("mcpgateway.services.tool_service._build_pinned_rest_http_client", side_effect=_build) as mocked,
    ):
        yield SimpleNamespace(mock=mocked, built=built)


@pytest.fixture
def invoke(service, mock_tool, mock_gateway, test_db, mock_global_config_obj, builder):  # noqa: F811
    """Return a coroutine function that invokes a REST tool through the real ``invoke_tool`` path."""

    async def _invoke(
        arguments,
        *,
        method="POST",
        url=URL,
        tool_sigv4=None,
        tool_auth_type="sigv4",
        gateway_sigv4=None,
        has_gateway=False,
        query_mapping=None,
        header_mapping=None,
        headers=None,
        request_headers=None,
        tool_auth_value=None,
    ):
        """Invoke the REST tool; return the response of ``invoke_tool``."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = method
        mock_tool.url = url
        mock_tool.headers = headers or dict(CT_JSON)
        mock_tool.jsonpath_filter = ""
        mock_tool.input_schema = SCHEMA
        mock_tool.auth_type = tool_auth_type
        mock_tool.auth_value = tool_auth_value
        mock_tool.sigv4_config = tool_sigv4
        mock_tool.query_mapping = query_mapping
        mock_tool.header_mapping = header_mapping
        if has_gateway:
            mock_gateway.auth_type = "sigv4" if gateway_sigv4 else None
            mock_gateway.sigv4_config = gateway_sigv4
        else:
            mock_tool.gateway_id = None
            mock_tool.gateway = None
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)
        return await service.invoke_tool(test_db, "test_tool", arguments, request_headers=request_headers)

    return _invoke


def body_hash(request: httpx.Request) -> str:
    """Return the hex SHA-256 of the exact bytes httpx sent."""
    return hashlib.sha256(request.content).hexdigest()


def reference_signature(auth: SigV4HttpxAuth, request: httpx.Request) -> str:
    """Recompute the signature of ``request`` from the headers the upstream received."""
    received = {name.lower(): value for name, value in request.headers.items() if name.lower() != "authorization"}
    header = auth.signer.authorization_header(request.method, str(request.url), received, received["x-amz-content-sha256"], received["x-amz-date"])
    return header.rsplit("Signature=", 1)[1]


def received_signature(request: httpx.Request) -> str:
    """Return the signature the upstream received."""
    return request.headers["authorization"].rsplit("Signature=", 1)[1]


@pytest.mark.asyncio
async def test_json_body_hash_covers_exact_bytes(invoke, upstream):
    """Scenario 1: ``x-amz-content-sha256`` is the SHA-256 of the exact JSON bytes, including non-ASCII text."""
    await invoke({"id": "42", "note": 'caf\u00e9 \u2603 {"nested": [1, 2, {"a": "b"}]}'}, tool_sigv4=stored_config())

    request = upstream.requests[0]
    assert request.headers["x-amz-content-sha256"] == body_hash(request)
    assert json.loads(request.content)["note"].startswith("caf\u00e9")
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=" + ACCESS_KEY + "/")
    assert received_signature(request) == reference_signature(build_stored_sigv4_httpx_auth(stored_config()), request)


@pytest.mark.asyncio
async def test_url_template_is_signed_after_substitution(invoke, upstream):
    """Scenario 2: the signature covers the substituted path, not the template."""
    await invoke({"id": "a b/c", "note": "x"}, tool_sigv4=stored_config())

    request = upstream.requests[0]
    assert request.url.raw_path.decode().startswith("/v1/users/a%20b%2Fc/orders")
    assert "{id}" not in str(request.url)
    assert received_signature(request) == reference_signature(build_stored_sigv4_httpx_auth(stored_config()), request)


@pytest.mark.asyncio
async def test_get_query_is_signed(invoke, upstream):
    """GET arguments become the query string before signing; reserved characters stay signed."""
    await invoke({"q": "a b+c~d/e\u00e9", "id": "7"}, method="GET", tool_sigv4=stored_config())

    request = upstream.requests[0]
    assert request.url.query
    assert received_signature(request) == reference_signature(build_stored_sigv4_httpx_auth(stored_config()), request)


@pytest.mark.asyncio
async def test_unsigned_payload_is_opt_in(invoke, upstream):
    """Scenario 4: ``unsigned_payload`` sends ``UNSIGNED-PAYLOAD``; the default hashes the body."""
    await invoke({"id": "1", "note": "x"}, tool_sigv4=stored_config(unsigned_payload=True))
    await invoke({"id": "1", "note": "x"}, tool_sigv4=stored_config())

    opted_in, default = upstream.requests
    assert opted_in.headers["x-amz-content-sha256"] == "UNSIGNED-PAYLOAD"
    assert default.headers["x-amz-content-sha256"] == body_hash(default)


@pytest.mark.asyncio
async def test_401_retry_resigns_with_fresh_timestamp(invoke, upstream, builder):
    """Scenario 3: one retry after a 401 carries a new ``x-amz-date`` and a new signature."""
    upstream.statuses = [401, 200]
    clock = iter(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=step) for step in range(1, 10))
    real_build = build_stored_sigv4_httpx_auth

    with patch("mcpgateway.services.tool_service.build_stored_sigv4_httpx_auth", side_effect=lambda stored: real_build(stored, clock=lambda: next(clock))):
        await invoke({"id": "1", "note": "x"}, tool_sigv4=stored_config())

    first, second = upstream.requests
    assert len(upstream.requests) == 2
    assert first.headers["x-amz-date"] != second.headers["x-amz-date"]
    assert received_signature(first) != received_signature(second)
    assert first.headers["x-amz-content-sha256"] == second.headers["x-amz-content-sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize("statuses", [[401, 401, 200], [403, 200]])
async def test_retry_runs_once_and_never_on_403(invoke, upstream, statuses):
    """The retry runs once on 401 and never on 403."""
    first_status = statuses[0]
    upstream.statuses = list(statuses)
    await invoke({"id": "1", "note": "x"}, tool_sigv4=stored_config())

    assert len(upstream.requests) == (2 if first_status == 401 else 1)


@pytest.mark.asyncio
async def test_sigv4_call_uses_isolated_client_without_ssrf_pinning(invoke, upstream, builder, service, monkeypatch):
    """Scenario 6: with SSRF protection off, the call still avoids the shared client and carries the signer."""
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.ssrf_protection_enabled", False)
    await invoke({"id": "1", "note": "x"}, tool_sigv4=stored_config())

    builder.mock.assert_called_once()
    assert isinstance(builder.built[0].auth, SigV4HttpxAuth)
    service._http_client.request.assert_not_called()
    service._http_client.get.assert_not_called()
    assert "authorization" in upstream.requests[0].headers


@pytest.mark.asyncio
async def test_pinned_request_signs_original_host(invoke, upstream):
    """The pinned URL holds an IP, and the signature covers the original ``Host``."""
    await invoke({"id": "1", "note": "x"}, tool_sigv4=stored_config())

    request = upstream.requests[0]
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "api.example.com"
    assert received_signature(request) == reference_signature(build_stored_sigv4_httpx_auth(stored_config()), request)
    names = request.headers["authorization"].split("SignedHeaders=")[1].split(",")[0].split(";")
    assert "host" in names


@pytest.mark.asyncio
async def test_tool_config_overrides_gateway_config(invoke, upstream):
    """Scenario 7: the tool credentials win; a tool without its own config uses the gateway credentials."""
    tool_cfg = stored_config(access_key_id="AKIATOOLEXAMPLE0000")  # pragma: allowlist secret
    gateway_cfg = stored_config(access_key_id="AKIAGATEWAYEXAMPLE0")  # pragma: allowlist secret

    await invoke({"id": "1", "note": "x"}, tool_sigv4=tool_cfg, gateway_sigv4=gateway_cfg, has_gateway=True)
    await invoke({"id": "1", "note": "x"}, tool_sigv4=None, gateway_sigv4=gateway_cfg, has_gateway=True)

    with_tool, with_gateway = upstream.requests
    assert "Credential=AKIATOOLEXAMPLE0000/" in with_tool.headers["authorization"]
    assert "Credential=AKIAGATEWAYEXAMPLE0/" in with_gateway.headers["authorization"]


@pytest.mark.asyncio
async def test_standalone_tool_signs(invoke, upstream):
    """Scenario 8: a tool without a gateway signs with its own configuration."""
    await invoke({"id": "1", "note": "x"}, tool_sigv4=stored_config(session_token=SESSION_TOKEN), has_gateway=False)

    request = upstream.requests[0]
    assert request.headers["x-amz-security-token"] == SESSION_TOKEN
    assert "x-amz-date" in request.headers


@pytest.mark.asyncio
async def test_no_credential_reaches_upstream_as_header(invoke, upstream):
    """Scenario 11: only signature headers carry credential data, and the secret never appears."""
    await invoke(
        {"id": "1", "note": "x"},
        tool_sigv4=stored_config(),
        request_headers={"X-Upstream-Authorization": "Bearer attacker", "Authorization": "Bearer inbound"},
    )

    request = upstream.requests[0]
    wire = "\n".join(f"{name}: {value}" for name, value in request.headers.items())
    assert SECRET_KEY not in wire
    assert "Bearer" not in wire
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert "region" not in {name.lower() for name in request.headers}
    assert "secret_access_key" not in {name.lower() for name in request.headers}


@pytest.mark.asyncio
async def test_stale_auth_value_is_never_decoded_for_sigv4(invoke, upstream):
    """A SigV4 tool skips the static ``auth_value`` header path."""
    with patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer leaked"}) as decode:
        await invoke({"id": "1", "note": "x"}, tool_sigv4=stored_config(), tool_auth_value="opaque")

    decode.assert_not_called()
    assert "leaked" not in upstream.requests[0].headers["authorization"]


@pytest.mark.asyncio
async def test_sigv4_tool_without_credentials_fails_closed(invoke, upstream):
    """A SigV4 tool with no tool config and no SigV4 gateway never sends an unsigned request."""
    with pytest.raises(ToolInvocationError, match="no stored credentials"):
        await invoke({"id": "1", "note": "x"}, tool_sigv4=None, has_gateway=False)

    assert upstream.requests == []


@pytest.mark.asyncio
async def test_undecryptable_credentials_fail_closed(invoke, upstream):
    """A stored secret that cannot be decrypted raises and sends nothing."""
    broken = plain_config()
    broken["secret_access_key"] = "not-encrypted"  # pragma: allowlist secret

    with pytest.raises(ToolInvocationError, match="could not be loaded"):
        await invoke({"id": "1", "note": "x"}, tool_sigv4=broken)

    assert upstream.requests == []


@pytest.mark.asyncio
async def test_tool_without_sigv4_auth_type_never_borrows_the_gateway_credential(invoke, upstream):
    """Deny path: a REST tool that did not opt in to sigv4 is not signed with the gateway credential."""
    await invoke({"id": "1", "note": "x"}, tool_auth_type=None, tool_sigv4=None, gateway_sigv4=stored_config(), has_gateway=True)

    request = upstream.requests[0]
    assert "authorization" not in request.headers
    assert "x-amz-date" not in request.headers
    assert "x-amz-content-sha256" not in request.headers


@pytest.mark.asyncio
async def test_bearer_tool_under_a_sigv4_gateway_keeps_its_own_credential(invoke, upstream):
    """A REST tool with its own static auth keeps it; the SigV4 gateway never replaces it."""
    bearer = encode_auth({"Authorization": "Bearer tool-token"})

    await invoke({"id": "1", "note": "x"}, tool_auth_type="bearer", tool_auth_value=bearer, tool_sigv4=None, gateway_sigv4=stored_config(), has_gateway=True)

    request = upstream.requests[0]
    assert request.headers["authorization"] == "Bearer tool-token"
    assert "x-amz-date" not in request.headers


@pytest.mark.asyncio
async def test_tool_sigv4_config_is_ignored_without_the_sigv4_auth_type(invoke, upstream):
    """A leftover tool sigv4_config does not sign a tool whose auth_type is not sigv4."""
    await invoke({"id": "1", "note": "x"}, tool_auth_type=None, tool_sigv4=stored_config())

    request = upstream.requests[0]
    assert "authorization" not in request.headers
    assert "x-amz-date" not in request.headers


@pytest.mark.asyncio
async def test_presigned_url_without_sigv4_keeps_its_query(invoke, upstream, service):
    """Scenario 5: a REST tool with no SigV4 configuration keeps a presigned query as before."""
    presigned = "https://api.example.com/file?X-Amz-Signature=abc123&X-Amz-Expires=60"

    await invoke({"note": "x"}, method="POST", url=presigned, tool_auth_type=None, tool_sigv4=None)

    request = upstream.requests[0]
    assert request.url.query == b"X-Amz-Signature=abc123&X-Amz-Expires=60"
    assert "authorization" not in request.headers
    assert "x-amz-date" not in request.headers


def test_httpx2_builders_ignore_unsigned_payload():
    """The MCP transport signer keeps hashing the body when ``unsigned_payload`` is set."""
    stored = stored_config(unsigned_payload=True)

    mcp_auth = build_stored_sigv4_auth(stored)
    rest_auth = build_stored_sigv4_httpx_auth(stored)

    assert isinstance(mcp_auth, SigV4Auth)
    assert mcp_auth.signer.unsigned_payload is False
    assert rest_auth.signer.unsigned_payload is True
