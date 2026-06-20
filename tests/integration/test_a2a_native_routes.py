# -*- coding: utf-8 -*-
"""Integration tests for native A2A 1.0.0 passthrough routes (Plan Wave 3).

Location: ./tests/integration/test_a2a_native_routes.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Wave 3 scope: T11 per-agent agent-card route handler glue.

The card synthesizer's behavior matrix (visibility, v-server membership,
URL rewriting, field-name correctness) is exhaustively covered by
:mod:`tests.unit.mcpgateway.services.test_a2a_service_native` (Wave 1
T2 acceptance, 14 cases). These integration tests cover JUST the FastAPI
handler glue:

- The route exists at ``GET /a2a/{agent_name}/.well-known/agent-card.json``.
- It calls :py:meth:`A2AAgentService.synthesize_agent_card` with the
  correct kwargs (``user_email=None``, ``token_teams=[]``, ``server_id``
  from ``request.scope``, ``public_base_url`` from settings).
- It serializes the returned AgentCard with ``by_alias=True`` +
  ``exclude_none=True`` so wire-level fields like ``protocolBinding``
  (NOT ``protocol_binding``) reach clients.
- ``None`` from the synthesizer collapses to HTTP 404 (D14).
- Missing ``a2a_service`` (A2A disabled at startup) yields HTTP 503.
- NO ``Authorization`` header is required (D11 — public discovery).

These tests use mocked ``synthesize_agent_card`` so they stay fast and
hermetic; the broader end-to-end shape is exercised by the Wave 2
compliance harness in ``tests/live_gateway/a2a_compliance/`` against a
running gateway + echo agent.
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
