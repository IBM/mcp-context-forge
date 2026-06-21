# -*- coding: utf-8 -*-
"""Integration tests for native A2A 1.0.0 passthrough routes (Plan Wave 3).

Location: ./tests/integration/test_a2a_native_routes.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Wave 3 scope: T11 per-agent agent-card route + T12 per-agent JSON-RPC
dispatch route + T14 SSE re-wrap helper handler glue.

The service-layer behavior matrix (synthesizer + dispatcher + version
negotiation + visibility + RBAC) is exhaustively covered by
:mod:`tests.unit.mcpgateway.services.test_a2a_service_native` (Wave 1
unit tests). These integration tests cover JUST the FastAPI handler
glue:

- T11 card route: synthesizer kwargs (``user_email=None``,
  ``token_teams=[]``), ``by_alias`` + ``exclude_none`` serialization,
  ``None``-to-404 collapse, ``a2a_service is None`` → 503.
- T12 dispatch route: body parse / envelope shape validation,
  per-method RBAC (``a2a.read`` vs ``a2a.invoke``), GetExtendedAgentCard
  short-circuit (never forwards upstream — D18), capability gating
  (``-32007``), streaming method routing to SSE.
- T14 SSE re-wrap: ``_sse_format`` emits exactly one
  ``data: {...}\\n\\n`` event per upstream chunk, compact JSON, no
  double-encoding.

Tests use mocked ``a2a_service`` methods + ``permission_service``
overrides so they stay fast and hermetic; the broader end-to-end shape
is exercised by the Wave 2 compliance harness in
``tests/live_gateway/a2a_compliance/`` against a running gateway +
echo agent.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mcpgateway import main as main_mod
from mcpgateway.schemas_a2a_native import AgentCapabilities, AgentCard, SupportedInterface

pytestmark = pytest.mark.integration


def _minimal_card() -> AgentCard:
    """Return a minimal valid A2A 1.0.0 AgentCard for handler-glue tests."""
    return AgentCard(
        name="echo",
        description="echo agent",
        version="1.0.0",
        capabilities=AgentCapabilities(),
        default_input_modes=["text"],
        default_output_modes=["text"],
        supported_interfaces=[
            SupportedInterface(
                url="http://gateway.example/a2a/echo",
                protocol_binding="JSONRPC",
                protocol_version="1.0.0",
            )
        ],
        skills=[],
    )


@pytest.fixture
def client() -> TestClient:
    """Yield a TestClient bound to the real ``mcpgateway.main.app``.

    The session-level conftest installs a stub for ``get_current_user``
    helpers and disables admin/UI surfaces, so this fixture is light
    weight — no app re-creation.
    """
    return TestClient(main_mod.app)


@pytest.fixture
def mock_a2a_service():
    """Patch ``main.a2a_service`` with a MagicMock exposing AsyncMock synth.

    Yields the AsyncMock for ``synthesize_agent_card`` so each test can
    set ``return_value`` per scenario and assert ``await_args`` to verify
    the handler called it with the documented kwargs (D11 public path).
    """
    fake_service = MagicMock()
    fake_service.synthesize_agent_card = AsyncMock()
    with patch.object(main_mod, "a2a_service", fake_service):
        yield fake_service.synthesize_agent_card


class TestPerAgentCardEndpoint:
    """T11 — ``GET /a2a/{agent_name}/.well-known/agent-card.json``."""

    def test_returns_serialized_card_with_alias_field_names(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """Happy path: 200 + JSON body using ``by_alias`` serialization.

        The wire shape MUST carry camelCase A2A 1.0.0 field names
        (``protocolBinding``, ``protocolVersion``, ``defaultInputModes``)
        and MUST NOT carry the Python snake_case attribute names.
        """
        mock_a2a_service.return_value = _minimal_card()
        response = client.get("/a2a/echo/.well-known/agent-card.json")
        assert response.status_code == 200, response.text[:200]
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["name"] == "echo"
        assert body["defaultInputModes"] == ["text"]
        assert "default_input_modes" not in body  # NOT python snake_case
        assert body["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
        assert body["supportedInterfaces"][0]["protocolVersion"] == "1.0.0"
        assert "protocol_binding" not in body["supportedInterfaces"][0]
        assert "transportProtocol" not in body["supportedInterfaces"][0]  # the wrong name

    def test_unknown_agent_returns_404(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """``None`` from synthesizer (unknown / hidden / not-in-server) → HTTP 404."""
        mock_a2a_service.return_value = None
        response = client.get("/a2a/unknown-agent/.well-known/agent-card.json")
        assert response.status_code == 404, response.text[:200]

    def test_a2a_service_disabled_returns_503(self, client: TestClient) -> None:
        """``a2a_service is None`` (A2A disabled) → HTTP 503."""
        with patch.object(main_mod, "a2a_service", None):
            response = client.get("/a2a/echo/.well-known/agent-card.json")
        assert response.status_code == 503, response.text[:200]

    def test_no_authorization_required(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """Discovery is PUBLIC (D11): no ``Authorization`` header required."""
        mock_a2a_service.return_value = _minimal_card()
        response = client.get("/a2a/echo/.well-known/agent-card.json")
        # No 401 / 403 — the route does NOT depend on auth.
        assert response.status_code == 200, response.text[:200]

    def test_synthesizer_called_with_public_visibility_kwargs(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """Handler MUST pass ``user_email=None`` + ``token_teams=[]`` (D11).

        ``token_teams=None`` would trigger admin bypass in
        ``_check_agent_access`` and leak hidden agents to anonymous
        callers — explicitly forbidden by the plan.
        """
        mock_a2a_service.return_value = _minimal_card()
        client.get("/a2a/echo/.well-known/agent-card.json")
        assert mock_a2a_service.await_count == 1
        kwargs = mock_a2a_service.await_args.kwargs
        assert kwargs["user_email"] is None
        assert kwargs["token_teams"] == []
        # token_teams MUST NOT be None (admin bypass leak guard).
        assert kwargs["token_teams"] is not None

    def test_synthesizer_called_with_server_id_none_when_not_in_scope(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """Direct ``/a2a/...`` route has no ``a2a_server_id`` in ASGI scope.

        Wave 4's path-rewrite middleware (T16) is what populates that
        scope key for ``/servers/{id}/a2a/...`` URLs; Wave 3 routes hit
        directly always pass ``server_id=None``.
        """
        mock_a2a_service.return_value = _minimal_card()
        client.get("/a2a/echo/.well-known/agent-card.json")
        kwargs = mock_a2a_service.await_args.kwargs
        assert kwargs["server_id"] is None

    def test_synthesizer_called_with_agent_name_from_path(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """The path's ``{agent_name}`` segment MUST reach the synthesizer."""
        mock_a2a_service.return_value = _minimal_card()
        client.get("/a2a/my-custom-agent/.well-known/agent-card.json")
        # Positional args: (db, agent_name, public_base_url)
        args = mock_a2a_service.await_args.args
        assert args[1] == "my-custom-agent"

    def test_response_excludes_none_optional_fields(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """``exclude_none=True`` keeps optional unset fields off the wire.

        Spec-compliant clients tolerate missing optional fields; emitting
        them as JSON ``null`` is a wire-noise smell that some strict
        parsers reject.
        """
        mock_a2a_service.return_value = _minimal_card()
        response = client.get("/a2a/echo/.well-known/agent-card.json")
        body = response.json()
        # AgentCard has many Optional[...] fields; assert at least one
        # known-unset field is absent rather than serialized as null.
        assert "documentationUrl" not in body
        assert "iconUrl" not in body
        assert "securitySchemes" not in body
        # And re-parse to confirm no key has value null.
        for key, value in body.items():
            assert value is not None, f"field {key!r} serialized as null despite exclude_none"


# ───────────────────────────────────────────────────────────────────────
# T12 + T14 — Per-agent JSON-RPC dispatch route + SSE re-wrap
# ───────────────────────────────────────────────────────────────────────


def _mock_agent(agent_id: str = "agt-123", team_id: str | None = None, capabilities: dict | None = None) -> MagicMock:
    """Build a MagicMock DbA2AAgent stub for dispatch handler tests."""
    agent = MagicMock()
    agent.id = agent_id
    agent.name = "echo"
    agent.team_id = team_id
    agent.capabilities = capabilities or {}
    return agent


@pytest.fixture
def dispatch_overrides():
    """Override auth + filter-context + permission deps for dispatch tests.

    Yields a dict that tests mutate to control behavior:

    - ``filter_context``: tuple returned by ``get_rpc_filter_context``.
    - ``permission_grant``: bool returned by ``check_permission``.

    Tear-down restores all overrides + the patched ``get_rpc_filter_context``.
    """
    state = {
        "filter_context": ("test_user@example.com", [], False),  # non-admin, public-only
        "permission_grant": True,
    }

    async def fake_get_current_user_with_permissions(request=None, credentials=None, jwt_token=None):
        return {"email": "test_user@example.com", "full_name": "Test User", "is_admin": False, "ip_address": "127.0.0.1", "user_agent": "test"}

    async def fake_check_permission(*args, **kwargs) -> bool:
        return state["permission_grant"]

    fake_permission_service = MagicMock()
    fake_permission_service.check_permission = fake_check_permission

    async def fake_get_permission_service(db=None):
        return fake_permission_service

    main_mod.app.dependency_overrides[main_mod.get_current_user_with_permissions] = fake_get_current_user_with_permissions
    main_mod.app.dependency_overrides[main_mod.get_permission_service] = fake_get_permission_service

    # Patch get_rpc_filter_context at the module-attribute level so the
    # handler sees our controlled tuple (the function consults JWT
    # claims via request.state, which TestClient does not populate).
    with patch.object(main_mod, "get_rpc_filter_context", lambda req, user: state["filter_context"]):
        yield state

    main_mod.app.dependency_overrides.pop(main_mod.get_current_user_with_permissions, None)
    main_mod.app.dependency_overrides.pop(main_mod.get_permission_service, None)


@pytest.fixture
def mock_dispatch_service():
    """Patch ``main.a2a_service`` with a MagicMock exposing dispatcher helpers.

    Yields the MagicMock so each test sets:

    - ``service.resolve_agent_for_dispatch`` (AsyncMock) → agent or raises.
    - ``service.dispatch_a2a_jsonrpc_unary`` (AsyncMock) → dict or tuple.
    - ``service.dispatch_a2a_jsonrpc_streaming`` (callable) → async gen.
    - ``service.synthesize_agent_card`` (AsyncMock) → AgentCard for
      GetExtendedAgentCard branch.
    """
    fake = MagicMock()
    fake.resolve_agent_for_dispatch = AsyncMock()
    fake.dispatch_a2a_jsonrpc_unary = AsyncMock()
    fake.synthesize_agent_card = AsyncMock()
    # streaming uses a callable returning async-gen, NOT AsyncMock
    fake.dispatch_a2a_jsonrpc_streaming = MagicMock()
    with patch.object(main_mod, "a2a_service", fake):
        yield fake


def _send_message_body(method: str = "SendMessage", request_id: str = "req-1") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {"message": {"role": "ROLE_USER", "messageId": "m1", "parts": [{"text": "hi"}]}},
    }


# Bearer token to bypass CSRF middleware (csrf_middleware.py:113-116 skips
# CSRF on bearer-authenticated requests since they are not browser-driven
# and thus not vulnerable to CSRF). The token VALUE is irrelevant because
# dependency overrides intercept auth before token validation runs.
_DISPATCH_HEADERS = {"A2A-Version": "1.0.0", "Authorization": "Bearer fake-test-token"}


class TestPerAgentDispatchEndpoint:
    """T12 — ``POST /a2a/{agent_name}``."""

    def test_a2a_service_disabled_returns_503(self, client: TestClient, dispatch_overrides) -> None:
        """``a2a_service is None`` → 503 transport-level (no JSON-RPC envelope)."""
        with patch.object(main_mod, "a2a_service", None):
            response = client.post(
                "/a2a/echo",
                json=_send_message_body(),
                headers=_DISPATCH_HEADERS,
            )
        assert response.status_code == 503, response.text[:200]

    def test_malformed_json_returns_32700(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """Invalid JSON → 200 + ``-32700 PARSE_ERROR``."""
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()
        response = client.post(
            "/a2a/echo",
            content=b"{this is not valid json",
            headers={"Content-Type": "application/json", **_DISPATCH_HEADERS},
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload["error"]["code"] == -32700, payload

    def test_non_dict_body_returns_32600(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``body=[]`` → 200 + ``-32600 INVALID_REQUEST`` (Oracle v2 #7)."""
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()
        response = client.post(
            "/a2a/echo",
            content=b"[]",
            headers={"Content-Type": "application/json", **_DISPATCH_HEADERS},
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload["error"]["code"] == -32600, payload

    def test_agent_not_found_returns_404(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``A2AAgentNotFoundError`` (unknown / visibility miss / wrong team) → HTTP 404."""
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError

        mock_dispatch_service.resolve_agent_for_dispatch.side_effect = A2AAgentNotFoundError("nope")
        response = client.post(
            "/a2a/unknown",
            json=_send_message_body(),
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 404, response.text[:200]

    def test_unsupported_version_returns_32009(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``A2A-Version: 99.0.0`` → 200 + ``-32009 VERSION_NOT_SUPPORTED``."""
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()
        response = client.post(
            "/a2a/echo",
            json=_send_message_body(),
            headers={**_DISPATCH_HEADERS, "A2A-Version": "99.0.0"},
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload["error"]["code"] == -32009, payload

    def test_invoke_without_permission_returns_403(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``check_permission("a2a.invoke")`` False → HTTP 403."""
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()
        dispatch_overrides["permission_grant"] = False
        response = client.post(
            "/a2a/echo",
            json=_send_message_body(),
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 403, response.text[:200]

    def test_invoke_success_returns_result_envelope(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """Successful unary dispatch → 200 + ``{"jsonrpc": "2.0", "result": ..., "id": ...}``."""
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()
        mock_dispatch_service.dispatch_a2a_jsonrpc_unary.return_value = {"task": "done"}
        response = client.post(
            "/a2a/echo",
            json=_send_message_body(request_id="abc"),
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload == {"jsonrpc": "2.0", "result": {"task": "done"}, "id": "abc"}

    def test_invoke_error_tuple_returns_error_envelope(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """Unary dispatch returns ``(code, msg, data)`` → 200 + ``make_jsonrpc_error`` envelope."""
        from mcpgateway.services.a2a_service import INVALID_PARAMS

        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()
        mock_dispatch_service.dispatch_a2a_jsonrpc_unary.return_value = (INVALID_PARAMS, "bad params", {"extra": "info"})
        response = client.post(
            "/a2a/echo",
            json=_send_message_body(request_id="x"),
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload["error"]["code"] == INVALID_PARAMS
        assert payload["error"]["message"] == "bad params"
        assert payload["error"]["data"] == {"extra": "info"}
        assert payload["id"] == "x"

    def test_invoke_upstream_result_envelope_passed_through_not_double_wrapped(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """Oracle F2 #1 (D14 fix): upstream JSON-RPC ``result`` envelope is passed through, not double-wrapped.

        Upstream A2A agents are themselves JSON-RPC endpoints (per spec) and
        return ``{"jsonrpc": "2.0", "result": ..., "id": ...}`` envelopes.
        Wrapping such an envelope a second time as ``{"result": <envelope>}``
        would put the upstream ``result`` two layers deep — a real spec
        violation. The fix detects the envelope shape and passes through
        with the inbound request id substituted in.
        """
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()
        upstream_envelope = {
            "jsonrpc": "2.0",
            "result": {"task": "completed", "id": "upstream-task-1"},
            "id": "upstream-original-id",
        }
        mock_dispatch_service.dispatch_a2a_jsonrpc_unary.return_value = upstream_envelope
        response = client.post(
            "/a2a/echo",
            json=_send_message_body(request_id="client-req-1"),
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload == {
            "jsonrpc": "2.0",
            "result": {"task": "completed", "id": "upstream-task-1"},
            "id": "client-req-1",
        }, "envelope must pass through with client request_id, not double-wrapped"
        # Regression guard: result must NOT be a nested JSON-RPC envelope.
        assert "jsonrpc" not in payload["result"], "result was double-wrapped"

    def test_invoke_upstream_error_envelope_passed_through_with_request_id(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """Oracle F2 #1 (D14 fix): upstream JSON-RPC ``error`` envelope passes through with client request_id.

        Without the fix, an upstream ``-32601 Method not found`` envelope
        becomes a successful response containing an error object (caller
        thinks the call succeeded with weird data). With the fix, the
        error surfaces at the top level where JSON-RPC clients expect it.
        """
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()
        upstream_envelope = {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": "Method not found"},
            "id": "upstream-id",
        }
        mock_dispatch_service.dispatch_a2a_jsonrpc_unary.return_value = upstream_envelope
        response = client.post(
            "/a2a/echo",
            json=_send_message_body(request_id="client-x"),
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload == {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": "Method not found"},
            "id": "client-x",
        }, "error envelope must surface at the top level"
        # Regression guard: no successful 'result' wrapping of the error.
        assert "result" not in payload, "upstream error was misclassified as result"

    def test_extended_card_without_read_permission_returns_403(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``GetExtendedAgentCard`` + ``a2a.read`` denied → 403."""
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent(capabilities={"extendedAgentCard": True})
        dispatch_overrides["permission_grant"] = False
        response = client.post(
            "/a2a/echo",
            json={"jsonrpc": "2.0", "id": "x", "method": "GetExtendedAgentCard", "params": {}},
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 403, response.text[:200]

    def test_extended_card_capability_disabled_returns_32007(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """Agent ``capabilities.extendedAgentCard=False`` → 200 + ``-32007``."""
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent(capabilities={"extendedAgentCard": False})
        response = client.post(
            "/a2a/echo",
            json={"jsonrpc": "2.0", "id": "y", "method": "GetExtendedAgentCard", "params": {}},
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload["error"]["code"] == -32007, payload

    def test_extended_card_returns_synthesized_card(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``GetExtendedAgentCard`` happy path → 200 + JSON-RPC ``result`` carrying the card.

        Crucially, this MUST NOT forward to upstream (D18): the
        synthesizer is the source of truth for the gateway's extended
        card view. Assertion below verifies the unary dispatcher was
        NEVER called.
        """
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent(capabilities={"extendedAgentCard": True})
        mock_dispatch_service.synthesize_agent_card.return_value = _minimal_card()
        response = client.post(
            "/a2a/echo",
            json={"jsonrpc": "2.0", "id": "z", "method": "GetExtendedAgentCard", "params": {}},
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload["id"] == "z"
        assert payload["jsonrpc"] == "2.0"
        assert payload["result"]["name"] == "echo"
        # Wire field naming: camelCase from by_alias serialization.
        assert payload["result"]["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
        # D18 guard: upstream dispatch MUST NOT have been called.
        mock_dispatch_service.dispatch_a2a_jsonrpc_unary.assert_not_called()

    def test_streaming_method_returns_sse_response(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``SendStreamingMessage`` → 200 + ``text/event-stream`` + parseable chunks.

        Covers T14 SSE re-wrap end-to-end: T5's parsed-dict yields →
        ``_sse_format`` → downstream ``data: ...\\n\\n`` events. Each
        event parses as a complete JSON-RPC envelope (no double-encoding).
        """
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()

        async def fake_stream(*args, **kwargs):
            yield {"jsonrpc": "2.0", "result": "chunk1", "id": "s1"}
            yield {"jsonrpc": "2.0", "result": "chunk2", "id": "s1"}

        mock_dispatch_service.dispatch_a2a_jsonrpc_streaming.side_effect = fake_stream

        with client.stream(
            "POST",
            "/a2a/echo",
            json={"jsonrpc": "2.0", "id": "s1", "method": "SendStreamingMessage", "params": {}},
            headers=_DISPATCH_HEADERS,
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            # Cache-Control: the handler sets "no-cache" but the gateway's
            # security middleware may strengthen it to "no-store, private".
            # The contract is "do not cache" — accept either form.
            cache_control = response.headers.get("cache-control", "")
            assert "no-cache" in cache_control or "no-store" in cache_control, f"Cache-Control={cache_control!r} should disable caching"
            chunks = []
            for line in response.iter_lines():
                stripped = line.strip()
                if not stripped.startswith("data:"):
                    continue
                payload = json.loads(stripped[len("data:") :].strip())
                chunks.append(payload)
        assert len(chunks) == 2, f"expected 2 SSE events, got {len(chunks)}: {chunks}"
        assert chunks[0] == {"jsonrpc": "2.0", "result": "chunk1", "id": "s1"}
        assert chunks[1] == {"jsonrpc": "2.0", "result": "chunk2", "id": "s1"}


class TestSseFormatHelper:
    """T14 — ``_sse_format`` SSE re-wrap helper."""

    @pytest.mark.asyncio
    async def test_emits_one_event_per_chunk(self) -> None:
        """One upstream dict → exactly one ``data: ...\\n\\n`` line."""

        async def gen():
            yield {"a": 1}
            yield {"a": 2}
            yield {"a": 3}

        events = [event async for event in main_mod._sse_format(gen())]
        assert len(events) == 3
        for event in events:
            assert event.startswith("data: ")
            assert event.endswith("\n\n")

    @pytest.mark.asyncio
    async def test_uses_compact_json_separators(self) -> None:
        """``separators=(',', ':')`` keeps wire bytes minimal."""

        async def gen():
            yield {"a": 1, "b": 2}

        event = [e async for e in main_mod._sse_format(gen())][0]
        # No whitespace inside the JSON payload.
        assert event == 'data: {"a":1,"b":2}\n\n'

    @pytest.mark.asyncio
    async def test_no_double_encoding_of_data_prefix(self) -> None:
        """Upstream dicts are already parsed; we add ONE ``data:`` prefix.

        Drives the T5 + T14 pairing fix (Oracle re-review #5).
        """

        async def gen():
            yield {"result": "hi"}

        event = [e async for e in main_mod._sse_format(gen())][0]
        # Exactly one `data:` prefix at the start.
        assert event.count("data:") == 1
        assert event.startswith("data: {")
        # And the payload re-parses cleanly as a dict (no nested data: token).
        body = event[len("data: ") :].strip()
        assert json.loads(body) == {"result": "hi"}


# ───────────────────────────────────────────────────────────────────────
# T17 + T18 — Virtual-server-scoped routes (same handlers via T16
# A2APathRewriteMiddleware rewriting /servers/{id}/a2a/{name}[/...] →
# /a2a/{name}[/...] and stamping scope["a2a_server_id"]).
# ───────────────────────────────────────────────────────────────────────


class TestVirtualServerCardEndpoint:
    """T17 — ``GET /servers/{server_id}/a2a/{agent_name}/.well-known/agent-card.json``.

    The route handler is the same as T11. The path-rewrite middleware
    populates ``request.scope["a2a_server_id"]`` so the handler passes
    it to ``synthesize_agent_card``, which then enforces the
    three-level conjunctive check via the centralized policy module.
    """

    def test_happy_path_serves_card_and_passes_server_id(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """Happy path: GET v-server URL → 200 + card + synthesizer called with server_id.

        Asserts the T16 middleware rewrote the path correctly and the
        T11 handler forwarded ``server_id`` from the scope.
        """
        mock_a2a_service.return_value = _minimal_card()
        response = client.get("/servers/srv-abc/a2a/echo/.well-known/agent-card.json")
        assert response.status_code == 200, response.text[:200]
        assert response.headers["content-type"].startswith("application/json")
        # Server id from the URL reached the synthesizer.
        kwargs = mock_a2a_service.await_args.kwargs
        assert kwargs["server_id"] == "srv-abc"
        # Anonymous public-only kwargs are still the contract on this
        # public discovery endpoint (D11) — even under v-server URL.
        assert kwargs["user_email"] is None
        assert kwargs["token_teams"] == []

    def test_denial_returns_404(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """Any denial (server-deny / membership-miss / agent-deny) → 404.

        The route does NOT distinguish between the three. All collapse
        to the same wire outcome per D14 so callers cannot enumerate
        v-server membership or hidden agents.
        """
        mock_a2a_service.return_value = None  # any denial path
        response = client.get("/servers/srv-1/a2a/missing-agent/.well-known/agent-card.json")
        assert response.status_code == 404, response.text[:200]
        # Synthesizer was still invoked with the v-server id (the
        # middleware ran), proving the rewrite happened.
        kwargs = mock_a2a_service.await_args.kwargs
        assert kwargs["server_id"] == "srv-1"

    def test_no_authorization_required(self, client: TestClient, mock_a2a_service: AsyncMock) -> None:
        """V-server card discovery stays PUBLIC (D11) just like the per-agent route."""
        mock_a2a_service.return_value = _minimal_card()
        response = client.get("/servers/srv-2/a2a/echo/.well-known/agent-card.json")
        assert response.status_code == 200, response.text[:200]


class TestVirtualServerDispatchEndpoint:
    """T18 — ``POST /servers/{server_id}/a2a/{agent_name}`` JSON-RPC dispatch."""

    def test_happy_send_message_resolves_with_server_id(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """Happy path: POST via v-server URL → 200 + result + resolver gets server_id."""
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()
        mock_dispatch_service.dispatch_a2a_jsonrpc_unary.return_value = {"task": "done"}

        response = client.post(
            "/servers/srv-x/a2a/echo",
            json=_send_message_body(request_id="abc"),
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload == {"jsonrpc": "2.0", "result": {"task": "done"}, "id": "abc"}
        # Resolver received the server id from the URL via middleware → scope.
        kwargs = mock_dispatch_service.resolve_agent_for_dispatch.await_args.kwargs
        assert kwargs["server_id"] == "srv-x"

    def test_agent_not_in_server_returns_404(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``AgentNotInServerError`` from the resolver → HTTP 404 (D14).

        The handler's existing ``A2AAgentNotFoundError`` branch covers
        this because :class:`AgentNotInServerError` derives from
        :class:`A2AAgentNotFoundError` (single error hierarchy, single
        wire outcome).
        """
        from mcpgateway.services.a2a_service import AgentNotInServerError

        mock_dispatch_service.resolve_agent_for_dispatch.side_effect = AgentNotInServerError("foreign", "srv-x")
        response = client.post(
            "/servers/srv-x/a2a/foreign",
            json=_send_message_body(),
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 404, response.text[:200]

    def test_streaming_via_vserver_url_returns_sse(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``SendStreamingMessage`` via v-server URL → 200 + text/event-stream.

        Confirms the T14 SSE wiring works through the rewritten path
        identically to the direct per-agent URL.
        """
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent()

        async def fake_stream(*args, **kwargs):
            yield {"jsonrpc": "2.0", "result": "chunk1", "id": "s1"}

        mock_dispatch_service.dispatch_a2a_jsonrpc_streaming.side_effect = fake_stream

        with client.stream(
            "POST",
            "/servers/srv-y/a2a/echo",
            json={"jsonrpc": "2.0", "id": "s1", "method": "SendStreamingMessage", "params": {}},
            headers=_DISPATCH_HEADERS,
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            # Resolver also received the server id on the streaming path.
            kwargs = mock_dispatch_service.resolve_agent_for_dispatch.await_args.kwargs
            assert kwargs["server_id"] == "srv-y"

    def test_extended_card_via_vserver_respects_a2a_read(self, client: TestClient, dispatch_overrides, mock_dispatch_service: MagicMock) -> None:
        """``GetExtendedAgentCard`` via v-server URL → 200 + card with a2a.read granted.

        The extended-card synthesis SHORT-CIRCUITS upstream (D18 — never
        forwards) and uses the same v-server-aware synthesizer that T17
        exercises. Permission check uses ``a2a.read``, not
        ``a2a.invoke``.
        """
        mock_dispatch_service.resolve_agent_for_dispatch.return_value = _mock_agent(capabilities={"extendedAgentCard": True})
        mock_dispatch_service.synthesize_agent_card.return_value = _minimal_card()

        response = client.post(
            "/servers/srv-z/a2a/echo",
            json={"jsonrpc": "2.0", "id": "ec", "method": "GetExtendedAgentCard", "params": {}},
            headers=_DISPATCH_HEADERS,
        )
        assert response.status_code == 200, response.text[:200]
        payload = response.json()
        assert payload["id"] == "ec"
        assert payload["result"]["name"] == "echo"
        # Synthesizer also got the server id.
        kwargs = mock_dispatch_service.synthesize_agent_card.await_args.kwargs
        assert kwargs["server_id"] == "srv-z"
        # NEVER forwarded upstream (D18).
        mock_dispatch_service.dispatch_a2a_jsonrpc_unary.assert_not_called()
