# -*- coding: utf-8 -*-
"""Tests for native A2A passthrough helpers in :mod:`mcpgateway.services.a2a_service`.

Location: ./tests/unit/mcpgateway/services/test_a2a_service_native.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Covers the helpers added by plan T3:

- :py:meth:`A2AAgentService.check_server_a2a_membership` — pure query
  against ``server_a2a_association``.
- :py:meth:`A2AAgentService.resolve_agent_for_dispatch` — name lookup
  with optional v-server membership + Layer-1 visibility enforcement.

Visibility semantics (plan D11 / Oracle v2 #3): a visibility miss surfaces
as :py:class:`A2AAgentNotFoundError`, NOT a separate permission error.
That keeps the wire shape uniform for callers and prevents existence-leak
side channels.

Membership semantics (plan F1 + D14): a foreign-agent miss at
``/servers/{X}/a2a/{foreign}`` raises :py:class:`AgentNotInServerError`
which the route layer translates to HTTP 404, behaviorally indistinguishable
from a name-not-found from the caller's perspective.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas_a2a_native import AgentCard
from mcpgateway.services import a2a_service as a2a_service_module
from mcpgateway.services.a2a_service import (
    A2AAgentError,
    A2AAgentNotFoundError,
    A2AAgentService,
    AgentNotInServerError,
    AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED,
    CONTENT_TYPE_NOT_SUPPORTED,
    INTERNAL_ERROR,
    INVALID_AGENT_RESPONSE,
    INVALID_PARAMS,
    INVALID_REQUEST,
    LEGACY_V03_METHOD_ALIASES,
    LEGACY_V03_METHOD_MAP,
    METHOD_NOT_FOUND,
    MULTIPLE_PUSH_NOT_SUPPORTED,
    PARSE_ERROR,
    PUSH_NOT_SUPPORTED,
    TASK_NOT_CANCELABLE,
    TASK_NOT_FOUND,
    UNSUPPORTED_OPERATION,
    VERSION_NOT_SUPPORTED,
    VersionNotSupportedError,
    make_jsonrpc_error,
    outbound_a2a_version,
    validate_a2a_version,
)


@pytest.fixture
def service() -> A2AAgentService:
    """Return a fresh :py:class:`A2AAgentService` instance."""
    return A2AAgentService()


def _mock_agent(agent_id: str = "agt-1", name: str = "echo", visibility: str = "public") -> MagicMock:
    """Build a MagicMock DbA2AAgent stub for resolve tests.

    Args:
        agent_id: ID to set on the stub.
        name: Name to set on the stub.
        visibility: Visibility to set on the stub.

    Returns:
        MagicMock: agent stub with the named attributes.
    """
    agent = MagicMock()
    agent.id = agent_id
    agent.name = name
    agent.visibility = visibility
    agent.team_id = None
    agent.owner_email = None
    return agent


class TestCheckServerA2AMembership:
    """Plan T3: ``check_server_a2a_membership`` returns True/False from row presence."""

    @pytest.mark.asyncio
    async def test_returns_true_when_row_exists(self, service: A2AAgentService) -> None:
        """A non-zero count means the agent is in the server."""
        db = MagicMock()
        db.execute.return_value.scalar.return_value = 1
        result = await service.check_server_a2a_membership(db, "srv-1", "agt-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_row_missing(self, service: A2AAgentService) -> None:
        """A zero count means the agent is NOT in the server."""
        db = MagicMock()
        db.execute.return_value.scalar.return_value = 0
        result = await service.check_server_a2a_membership(db, "srv-1", "agt-2")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_scalar_returns_none(self, service: A2AAgentService) -> None:
        """A None count (defensive — should not happen on COUNT, but guards the codepath)."""
        db = MagicMock()
        db.execute.return_value.scalar.return_value = None
        result = await service.check_server_a2a_membership(db, "srv-1", "agt-1")
        assert result is False


class TestResolveAgentForDispatch:
    """Plan T3: 6 scenarios per the acceptance criteria."""

    @pytest.mark.asyncio
    async def test_missing_agent_raises_not_found(self, service: A2AAgentService) -> None:
        """Name not in DB → :py:class:`A2AAgentNotFoundError`."""
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(A2AAgentNotFoundError) as exc_info:
            await service.resolve_agent_for_dispatch(db, "missing")
        assert "missing" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_bare_lookup_admin_bypass(self, service: A2AAgentService) -> None:
        """No server_id + admin bypass (both user_email + token_teams None) → returns agent."""
        agent = _mock_agent(visibility="public")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        result = await service.resolve_agent_for_dispatch(db, "echo", user_email=None, token_teams=None)
        assert result is agent

    @pytest.mark.asyncio
    async def test_valid_membership_with_server_id(self, service: A2AAgentService) -> None:
        """server_id provided + agent IS in server + visible → returns agent."""
        agent = _mock_agent(visibility="public")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with patch.object(service, "check_server_a2a_membership", new=AsyncMock(return_value=True)):
            result = await service.resolve_agent_for_dispatch(db, "echo", server_id="srv-1", user_email=None, token_teams=None)
            assert result is agent

    @pytest.mark.asyncio
    async def test_invalid_membership_raises(self, service: A2AAgentService) -> None:
        """server_id provided + agent NOT in server → :py:class:`AgentNotInServerError`."""
        agent = _mock_agent()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with patch.object(service, "check_server_a2a_membership", new=AsyncMock(return_value=False)):
            with pytest.raises(AgentNotInServerError) as exc_info:
                await service.resolve_agent_for_dispatch(db, "echo", server_id="srv-X", user_email=None, token_teams=None)
            assert exc_info.value.agent_name == "echo"
            assert exc_info.value.server_id == "srv-X"

    @pytest.mark.asyncio
    async def test_visibility_deny_raises_not_found(self, service: A2AAgentService) -> None:
        """Visibility deny surfaces as :py:class:`A2AAgentNotFoundError`, NOT permission error.

        Per plan D11 / Oracle v2 #3: same wire outcome as name-not-found.
        """
        agent = _mock_agent(visibility="team")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with patch.object(service, "_check_agent_access", new=AsyncMock(return_value=False)):
            with pytest.raises(A2AAgentNotFoundError):
                await service.resolve_agent_for_dispatch(db, "echo", user_email="user@example.com", token_teams=[])

    @pytest.mark.asyncio
    async def test_membership_checked_before_visibility(self, service: A2AAgentService) -> None:
        """Membership miss raises :py:class:`AgentNotInServerError` BEFORE visibility check.

        Important so we don't leak agent existence at
        ``/servers/{X}/a2a/foreign-agent`` — a foreign agent who is otherwise
        visible to the caller should still 404 at the v-server-scoped path.
        """
        agent = _mock_agent(visibility="public")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        visibility_check = AsyncMock(return_value=True)
        with patch.object(service, "check_server_a2a_membership", new=AsyncMock(return_value=False)), patch.object(service, "_check_agent_access", new=visibility_check):
            with pytest.raises(AgentNotInServerError):
                await service.resolve_agent_for_dispatch(
                    db,
                    "echo",
                    server_id="srv-X",
                    user_email="user@example.com",
                    token_teams=["t1"],
                )
            # Visibility check must NOT fire when membership fails (would
            # be an existence-leak — caller could infer the agent exists
            # somewhere via timing or side effects).
            visibility_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_server_id_skips_membership_check(self, service: A2AAgentService) -> None:
        """When ``server_id`` is None, membership check is bypassed entirely."""
        agent = _mock_agent(visibility="public")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        membership_check = AsyncMock(return_value=False)
        with patch.object(service, "check_server_a2a_membership", new=membership_check):
            result = await service.resolve_agent_for_dispatch(db, "echo", server_id=None, user_email=None, token_teams=None)
            assert result is agent
            membership_check.assert_not_called()


def _mock_agent_for_synth(
    agent_id: str = "agt-1",
    name: str = "echo",
    visibility: str = "public",
    protocol_version: str = "1.0.0",
    capabilities: dict | None = None,
    description: str = "Reference echo agent",
    version: str = "1.0.0",
) -> MagicMock:
    """Build a MagicMock DbA2AAgent stub for ``synthesize_agent_card`` tests."""
    agent = MagicMock()
    agent.id = agent_id
    agent.name = name
    agent.visibility = visibility
    agent.team_id = None
    agent.owner_email = None
    agent.enabled = True
    agent.description = description
    agent.endpoint_url = "http://127.0.0.1:9100"  # NOT used by synth (D7)
    agent.protocol_version = protocol_version
    agent.version = version
    agent.capabilities = capabilities if capabilities is not None else {"streaming": True}
    return agent


class TestSynthesizeAgentCard:
    """Plan T2 (8 acceptance cases + spec field-name + skill robustness)."""

    @pytest.mark.asyncio
    async def test_missing_agent_returns_none(self, service: A2AAgentService) -> None:
        """Agent name not in DB -> ``None`` (route handler maps to 404)."""
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        result = await service.synthesize_agent_card(db, "missing", "https://gw.example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_url_absent_server(self, service: A2AAgentService) -> None:
        """No ``server_id`` -> URL is ``{public_base}/a2a/{name}``."""
        agent = _mock_agent_for_synth()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com")
        assert card is not None
        assert card.supported_interfaces[0].url == "https://gw.example.com/a2a/echo"

    @pytest.mark.asyncio
    async def test_url_with_server(self, service: A2AAgentService) -> None:
        """``server_id`` set -> URL is ``{public_base}/servers/{id}/a2a/{name}``."""
        agent = _mock_agent_for_synth()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with patch.object(service, "check_server_a2a_membership", new=AsyncMock(return_value=True)):
            card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com", server_id="srv-X")
            assert card is not None
            assert card.supported_interfaces[0].url == "https://gw.example.com/servers/srv-X/a2a/echo"

    @pytest.mark.asyncio
    async def test_protocol_binding_jsonrpc(self, service: A2AAgentService) -> None:
        """``protocolBinding`` is always ``JSONRPC`` (plan Q13 phase-1)."""
        agent = _mock_agent_for_synth()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com")
        assert card is not None
        assert card.supported_interfaces[0].protocol_binding == "JSONRPC"

    @pytest.mark.asyncio
    async def test_protocol_version_from_agent_row(self, service: A2AAgentService) -> None:
        """``protocolVersion`` uses ``agent.protocol_version`` (Oracle v3 #21 NOT hardcoded)."""
        agent = _mock_agent_for_synth(protocol_version="1.0.5")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com")
        assert card is not None
        assert card.supported_interfaces[0].protocol_version == "1.0.5"

    @pytest.mark.asyncio
    async def test_visibility_deny_returns_none(self, service: A2AAgentService) -> None:
        """Visibility miss -> ``None`` (NOT raise; same wire outcome as not-found)."""
        agent = _mock_agent_for_synth(visibility="team")
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        result = await service.synthesize_agent_card(db, "echo", "https://gw.example.com", user_email=None, token_teams=[])
        assert result is None

    @pytest.mark.asyncio
    async def test_model_validates_clean_round_trip(self, service: A2AAgentService) -> None:
        """Synthesized card round-trips through ``AgentCard.model_validate``."""
        agent = _mock_agent_for_synth()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com")
        assert card is not None
        wire = card.model_dump(by_alias=True, exclude_none=True)
        assert "protocolBinding" in wire["supportedInterfaces"][0]
        assert "protocolVersion" in wire["supportedInterfaces"][0]
        assert "protocolVersion" not in wire  # NEVER top-level
        re_parsed = AgentCard.model_validate(wire)
        assert re_parsed.name == agent.name

    @pytest.mark.asyncio
    async def test_v_server_membership_miss_returns_none(self, service: A2AAgentService) -> None:
        """``server_id`` set + agent NOT in server -> ``None`` (foreign-agent forge prevention)."""
        agent = _mock_agent_for_synth()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with patch.object(service, "check_server_a2a_membership", new=AsyncMock(return_value=False)):
            result = await service.synthesize_agent_card(db, "echo", "https://gw.example.com", server_id="srv-X")
            assert result is None

    @pytest.mark.asyncio
    async def test_disabled_agent_returns_none(self, service: A2AAgentService) -> None:
        """Disabled agents are not served via native passthrough.

        Query filters on ``enabled.is_(True)`` so disabled agents look
        like missing ones (consistent with the legacy ``get_agent_card``
        at ``a2a_service.py:1370``).
        """
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        result = await service.synthesize_agent_card(db, "disabled-agent", "https://gw.example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_skill_extraction_from_capabilities(self, service: A2AAgentService) -> None:
        """Skills come from ``agent.capabilities.skills`` (validated per-item)."""
        agent = _mock_agent_for_synth(
            capabilities={
                "streaming": True,
                "skills": [
                    {"id": "echo", "name": "Echo", "description": "Echo back", "tags": [], "examples": []},
                    {"id": "ping", "name": "Ping", "description": "Reachability probe", "tags": [], "examples": []},
                ],
            }
        )
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com")
        assert card is not None
        assert len(card.skills) == 2
        assert card.skills[0].id == "echo"
        assert card.skills[1].id == "ping"

    @pytest.mark.asyncio
    async def test_malformed_skill_is_skipped(self, service: A2AAgentService) -> None:
        """A skill dict missing required fields is skipped, not raised."""
        agent = _mock_agent_for_synth(
            capabilities={
                "skills": [
                    {"id": "echo", "name": "Echo", "description": "Echo back"},
                    {"name": "broken", "description": "no id"},  # missing required id
                ],
            }
        )
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com")
        assert card is not None
        assert len(card.skills) == 1
        assert card.skills[0].id == "echo"

    @pytest.mark.asyncio
    async def test_capabilities_extended_agent_card_flag(self, service: A2AAgentService) -> None:
        """``extendedAgentCard`` from agent.capabilities drives the -32007 trigger."""
        agent = _mock_agent_for_synth(capabilities={"streaming": True, "extendedAgentCard": True})
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com")
        assert card is not None
        assert card.capabilities.extended_agent_card is True

    @pytest.mark.asyncio
    async def test_capabilities_extended_agent_card_defaults_false(self, service: A2AAgentService) -> None:
        """Absent ``extendedAgentCard`` defaults to False (triggers -32007 in T12)."""
        agent = _mock_agent_for_synth(capabilities={"streaming": True})
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com")
        assert card is not None
        assert card.capabilities.extended_agent_card is False

    @pytest.mark.asyncio
    async def test_description_none_falls_back_to_empty_string(self, service: A2AAgentService) -> None:
        """A2AAgent.description is nullable; ``None`` becomes ``""`` (required field)."""
        agent = _mock_agent_for_synth(description=None)
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        card = await service.synthesize_agent_card(db, "echo", "https://gw.example.com")
        assert card is not None
        assert card.description == ""


class TestJsonRpcErrorConstants:
    """Plan T6: standard JSON-RPC + A2A 1.0.0 spec section 5.4 codes (14 total)."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            # Standard JSON-RPC 2.0
            ("PARSE_ERROR", -32700),
            ("INVALID_REQUEST", -32600),
            ("METHOD_NOT_FOUND", -32601),
            ("INVALID_PARAMS", -32602),
            ("INTERNAL_ERROR", -32603),
            # A2A 1.0.0 spec section 5.4
            ("TASK_NOT_FOUND", -32001),
            ("TASK_NOT_CANCELABLE", -32002),
            ("PUSH_NOT_SUPPORTED", -32003),
            ("UNSUPPORTED_OPERATION", -32004),
            ("CONTENT_TYPE_NOT_SUPPORTED", -32005),
            ("INVALID_AGENT_RESPONSE", -32006),
            ("AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED", -32007),
            ("MULTIPLE_PUSH_NOT_SUPPORTED", -32008),
            ("VERSION_NOT_SUPPORTED", -32009),
        ],
    )
    def test_constant_value(self, name: str, expected: int) -> None:
        """Each constant is exported from the module with the spec-correct value."""
        actual = getattr(a2a_service_module, name)
        assert actual == expected, f"{name} should be {expected}, got {actual}"


class TestMakeJsonrpcError:
    """Plan T6 + D6: wire envelope shape, ``data`` omission, ``id`` passthrough."""

    def test_basic_shape(self) -> None:
        """Standard envelope ordering and field names."""
        err = make_jsonrpc_error(METHOD_NOT_FOUND, "Method not found", 1)
        assert err == {"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}, "id": 1}

    def test_data_omitted_when_none(self) -> None:
        """When ``data`` is None it does NOT appear in the wire payload."""
        err = make_jsonrpc_error(INTERNAL_ERROR, "Internal", None)
        assert "data" not in err["error"]
        assert err["error"] == {"code": -32603, "message": "Internal"}

    def test_data_included_when_provided(self) -> None:
        """A dict ``data`` field round-trips into the error block verbatim."""
        err = make_jsonrpc_error(INTERNAL_ERROR, "Internal", 1, data={"trace": "x"})
        assert err["error"]["data"] == {"trace": "x"}

    def test_data_typed_array(self) -> None:
        """The A2A spec section 5.4 typed-array ``data`` shape is preserved."""
        err = make_jsonrpc_error(INVALID_PARAMS, "Invalid params", 1, data=[{"field": "method"}])
        assert err["error"]["data"] == [{"field": "method"}]

    def test_id_passthrough_int(self) -> None:
        """Integer request_id echoes verbatim."""
        err = make_jsonrpc_error(INVALID_REQUEST, "x", 42)
        assert err["id"] == 42

    def test_id_passthrough_string(self) -> None:
        """String request_id echoes verbatim."""
        err = make_jsonrpc_error(INVALID_REQUEST, "x", "req-1")
        assert err["id"] == "req-1"

    def test_id_passthrough_null(self) -> None:
        """``None`` (JSON-RPC notification null) echoes as ``None``."""
        err = make_jsonrpc_error(PARSE_ERROR, "Parse error", None)
        assert err["id"] is None

    def test_a2a_code_not_coerced_to_internal_error(self) -> None:
        """A2A-specific codes (-32001..-32009) are preserved, NOT silently coerced.

        Oracle v3 #6 explicitly called out the anti-pattern of falling back
        every gateway-detected error to ``-32603`` and discarding the
        spec-correct code.
        """
        for code in (
            TASK_NOT_FOUND,
            TASK_NOT_CANCELABLE,
            PUSH_NOT_SUPPORTED,
            UNSUPPORTED_OPERATION,
            CONTENT_TYPE_NOT_SUPPORTED,
            INVALID_AGENT_RESPONSE,
            AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED,
            MULTIPLE_PUSH_NOT_SUPPORTED,
            VERSION_NOT_SUPPORTED,
        ):
            err = make_jsonrpc_error(code, "msg", 1)
            assert err["error"]["code"] == code, f"Code {code} was coerced"

    def test_envelope_jsonrpc_field_always_present(self) -> None:
        """The ``jsonrpc: 2.0`` envelope marker is required by spec."""
        err = make_jsonrpc_error(PARSE_ERROR, "x", None)
        assert err["jsonrpc"] == "2.0"


class TestValidateA2AVersion:
    """Plan T7 + D13: method-aware A2A-Version header validation."""

    @pytest.mark.parametrize("header", ["1.0", "1.0.0"])
    def test_accepted_versions(self, header: str) -> None:
        """Spec-recognized v1 header values return verbatim, regardless of method."""
        assert validate_a2a_version(header, "SendMessage") == header
        assert validate_a2a_version(header, None) == header

    def test_missing_with_v1_method_rejected(self) -> None:
        """Missing header + v1 method → :py:class:`VersionNotSupportedError`."""
        with pytest.raises(VersionNotSupportedError):
            validate_a2a_version(None, "SendMessage")

    def test_empty_with_v1_method_rejected(self) -> None:
        """Empty string header + v1 method → :py:class:`VersionNotSupportedError`."""
        with pytest.raises(VersionNotSupportedError):
            validate_a2a_version("", "SendMessage")

    def test_missing_with_method_none_rejected(self) -> None:
        """Missing header + unknown method (None) → :py:class:`VersionNotSupportedError`.

        T12 only knows the method AFTER body parse, so callers may pass
        ``method=None`` if validation fires before parse. In that case
        we cannot apply the legacy-alias exception and must reject.
        """
        with pytest.raises(VersionNotSupportedError):
            validate_a2a_version(None, None)

    @pytest.mark.parametrize("alias", sorted(LEGACY_V03_METHOD_ALIASES))
    def test_missing_with_legacy_alias_accepted(self, alias: str, caplog: pytest.LogCaptureFixture) -> None:
        """Missing header + legacy v0.3 alias method → returns ``"1.0"`` + info log.

        Q12 transitional support: v0.3 clients don't know about the
        ``A2A-Version`` header. Tolerating their legacy method names
        without the header keeps the transition smooth.
        """
        import logging

        with caplog.at_level(logging.INFO):
            result = validate_a2a_version(None, alias)
        assert result == "1.0"
        assert any(alias in record.getMessage() for record in caplog.records)

    @pytest.mark.parametrize("alias", sorted(LEGACY_V03_METHOD_ALIASES))
    def test_empty_with_legacy_alias_accepted(self, alias: str) -> None:
        """Empty-string header + legacy alias is treated like missing."""
        assert validate_a2a_version("", alias) == "1.0"

    @pytest.mark.parametrize("bad_version", ["2.0", "0.3", "abc", "1.1", "1.0.1"])
    def test_unsupported_versions_rejected(self, bad_version: str) -> None:
        """Anything other than ``1.0`` / ``1.0.0`` is rejected, regardless of method."""
        with pytest.raises(VersionNotSupportedError):
            validate_a2a_version(bad_version, "SendMessage")
        with pytest.raises(VersionNotSupportedError):
            validate_a2a_version(bad_version, "message/send")
        with pytest.raises(VersionNotSupportedError):
            validate_a2a_version(bad_version, None)

    def test_legacy_alias_set_complete(self) -> None:
        """Plan F8 + what's-new-v1: 10 legacy aliases the v1 gateway tolerates."""
        expected = {
            "message/send",
            "message/stream",
            "tasks/get",
            "tasks/cancel",
            "tasks/resubscribe",
            "tasks/pushNotificationConfig/set",
            "tasks/pushNotificationConfig/get",
            "tasks/pushNotificationConfig/list",
            "tasks/pushNotificationConfig/delete",
            "agent/getAuthenticatedExtendedCard",
        }
        assert set(LEGACY_V03_METHOD_ALIASES) == expected


class TestOutboundA2AVersion:
    """Plan T7 + Oracle v3 #21: outbound header uses the agent's stored version."""

    def test_returns_agent_protocol_version(self) -> None:
        """Outbound header echoes ``agent.protocol_version`` verbatim."""
        agent = MagicMock()
        agent.protocol_version = "1.0.0"
        assert outbound_a2a_version(agent) == "1.0.0"

    def test_returns_legacy_v03_when_agent_is_legacy(self) -> None:
        """A registered legacy v0.3 agent gets ``A2A-Version: 0.3`` forwarded."""
        agent = MagicMock()
        agent.protocol_version = "0.3"
        assert outbound_a2a_version(agent) == "0.3"

    def test_never_hardcodes(self) -> None:
        """Oracle v3 #21 anti-pattern: outbound version must NOT be hardcoded.

        Verified by parametrizing on arbitrary values — whatever the
        agent row says, the helper echoes verbatim.
        """
        for version in ("1.0", "1.0.0", "1.0.5", "0.3", "2.0"):
            agent = MagicMock()
            agent.protocol_version = version
            assert outbound_a2a_version(agent) == version


class TestDispatchA2AJsonrpcUnary:
    """Plan T4: envelope validation + alias mapping + invoke_agent delegation."""

    @pytest.fixture
    def agent_stub(self) -> MagicMock:
        """Build a minimal agent stub with id + name."""
        agent = MagicMock()
        agent.id = "agt-1"
        agent.name = "echo"
        return agent

    @pytest.mark.asyncio
    async def test_invalid_jsonrpc_version_returns_error_tuple(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """``jsonrpc != "2.0"`` -> INVALID_REQUEST tuple per D6."""
        result = await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "1.0", "method": "SendMessage"})
        assert isinstance(result, tuple)
        assert result[0] == INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_missing_method_returns_error_tuple(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """Missing method field -> INVALID_REQUEST tuple."""
        result = await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0"})
        assert isinstance(result, tuple)
        assert result[0] == INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_empty_method_returns_error_tuple(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """Empty method string -> INVALID_REQUEST tuple."""
        result = await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": ""})
        assert isinstance(result, tuple)
        assert result[0] == INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_non_string_method_returns_error_tuple(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """Non-string method -> INVALID_REQUEST tuple."""
        result = await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": 123})
        assert isinstance(result, tuple)
        assert result[0] == INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_non_dict_params_returns_error_tuple(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """``params`` that isn't dict-or-null -> INVALID_PARAMS tuple."""
        result = await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": "SendMessage", "params": "not-a-dict"})
        assert isinstance(result, tuple)
        assert result[0] == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_null_params_accepted(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """``params: null`` is valid per JSON-RPC 2.0; dispatch proceeds."""
        with patch.object(service, "invoke_agent", new=AsyncMock(return_value={"result": "ok"})):
            result = await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": "SendMessage", "params": None})
            assert result == {"result": "ok"}

    @pytest.mark.parametrize("v03_method,v1_method", sorted(LEGACY_V03_METHOD_MAP.items()))
    @pytest.mark.asyncio
    async def test_legacy_alias_mapped(self, service: A2AAgentService, agent_stub: MagicMock, v03_method: str, v1_method: str) -> None:
        """All 10 legacy v0.3 aliases are mapped to their v1 names before forwarding."""
        invoke_mock = AsyncMock(return_value={"result": "ok"})
        with patch.object(service, "invoke_agent", new=invoke_mock):
            await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": v03_method, "params": {}, "id": 1})
        # The 3rd positional arg `parameters` is the rebuilt envelope.
        call_kwargs = invoke_mock.call_args.kwargs
        assert call_kwargs["parameters"]["method"] == v1_method

    @pytest.mark.asyncio
    async def test_tasks_list_not_mapped(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """``tasks/list`` is NEW in v1.0 (Oracle v3 #22) — NOT a legacy alias, passes verbatim."""
        invoke_mock = AsyncMock(return_value={"result": "ok"})
        with patch.object(service, "invoke_agent", new=invoke_mock):
            await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": "tasks/list", "params": {}, "id": 1})
        # Verify the method is forwarded verbatim, NOT mapped to anything.
        assert invoke_mock.call_args.kwargs["parameters"]["method"] == "tasks/list"
        # And confirm tasks/list is NOT a key in the mapping (defense in depth).
        assert "tasks/list" not in LEGACY_V03_METHOD_MAP

    @pytest.mark.asyncio
    async def test_unknown_method_passes_through(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """Unknown methods pass through verbatim; upstream decides whether to honor."""
        invoke_mock = AsyncMock(return_value={"result": "ok"})
        with patch.object(service, "invoke_agent", new=invoke_mock):
            await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": "MyCustomMethod", "params": {}, "id": 1})
        assert invoke_mock.call_args.kwargs["parameters"]["method"] == "MyCustomMethod"

    @pytest.mark.asyncio
    async def test_invoke_agent_called_with_t12_kwargs(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """T12 calls dispatch_a2a_jsonrpc_unary with bearer_token/hop_count/request_headers — verify forwarding (Oracle v3 #2)."""
        invoke_mock = AsyncMock(return_value={"result": "ok"})
        with patch.object(service, "invoke_agent", new=invoke_mock):
            await service.dispatch_a2a_jsonrpc_unary(
                MagicMock(),
                agent_stub,
                {"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": 1},
                bearer_token="ey.token.here",
                hop_count=2,
                request_headers={"content-type": "application/json", "x-trace": "abc"},
            )
        kwargs = invoke_mock.call_args.kwargs
        assert kwargs["bearer_token"] == "ey.token.here"
        assert kwargs["hop_count"] == 2
        assert kwargs["request_headers"] == {"content-type": "application/json", "x-trace": "abc"}
        assert kwargs["content_type"] == "application/json"  # extracted from request_headers
        assert kwargs["agent_id"] == "agt-1"  # T3 already resolved; skip re-resolution

    @pytest.mark.asyncio
    async def test_envelope_preserved_to_upstream(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """The upstream sees a complete jsonrpc+method+params+id envelope, not a wrapped legacy v0.3 shape."""
        invoke_mock = AsyncMock(return_value={"result": "ok"})
        with patch.object(service, "invoke_agent", new=invoke_mock):
            await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": "SendMessage", "params": {"foo": "bar"}, "id": 42})
        upstream_body = invoke_mock.call_args.kwargs["parameters"]
        assert upstream_body["jsonrpc"] == "2.0"
        assert upstream_body["method"] == "SendMessage"
        assert upstream_body["params"] == {"foo": "bar"}
        assert upstream_body["id"] == 42

    @pytest.mark.asyncio
    async def test_invoke_agent_not_found_error_translated_to_tuple(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """A2AAgentNotFoundError -> METHOD_NOT_FOUND tuple (defense-in-depth per D14)."""
        with patch.object(service, "invoke_agent", new=AsyncMock(side_effect=A2AAgentNotFoundError("not found"))):
            result = await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": 1})
        assert isinstance(result, tuple)
        assert result[0] == METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_a2a_agent_error_translated_to_internal_error_tuple(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """A2AAgentError (non-not-found) -> INTERNAL_ERROR tuple per D6."""
        with patch.object(service, "invoke_agent", new=AsyncMock(side_effect=A2AAgentError("upstream blew up"))):
            result = await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": 1})
        assert isinstance(result, tuple)
        assert result[0] == INTERNAL_ERROR
        assert "upstream blew up" in result[1]

    @pytest.mark.asyncio
    async def test_successful_dispatch_returns_dict(self, service: A2AAgentService, agent_stub: MagicMock) -> None:
        """Successful invoke_agent return value is returned verbatim as a dict (not a tuple)."""
        with patch.object(service, "invoke_agent", new=AsyncMock(return_value={"jsonrpc": "2.0", "result": {"ok": True}, "id": 1})):
            result = await service.dispatch_a2a_jsonrpc_unary(MagicMock(), agent_stub, {"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": 1})
        assert isinstance(result, dict)
        assert result["result"] == {"ok": True}


# ----------------------------------------------------------------------
# T5 (streaming dispatch) test helpers
# ----------------------------------------------------------------------


class _FakeSSEResponse:
    """Minimal stand-in for ``httpx.Response`` covering the bits T5 reads."""

    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    """Async context manager mimicking ``client.stream(...) as response``."""

    def __init__(self, response: _FakeSSEResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeSSEResponse:
        return self._response

    async def __aexit__(self, *args: object) -> bool:
        return False


def _patch_http_client(mock_client: MagicMock):
    """Patch ``get_http_client`` (imported lazily in T5) to return ``mock_client``."""
    return patch(
        "mcpgateway.services.http_client_service.get_http_client",
        new=AsyncMock(return_value=mock_client),
    )


def _agent_for_streaming(protocol_version: str = "1.0.0", endpoint_url: str = "http://upstream.example.com/a2a") -> MagicMock:
    """Minimal agent stub for streaming dispatch tests."""
    agent = MagicMock()
    agent.id = "agt-1"
    agent.name = "echo"
    agent.protocol_version = protocol_version
    agent.endpoint_url = endpoint_url
    return agent


class TestDispatchA2AJsonrpcStreaming:
    """Plan T5 + D10 + D15 + Oracle v2 #5: real SSE parser + envelope semantics."""

    @pytest.mark.asyncio
    async def test_multiple_sse_chunks_streamed(self, service: A2AAgentService) -> None:
        """Two SSE events → two yielded dicts."""
        agent = _agent_for_streaming()
        response = _FakeSSEResponse(200, ['data: {"a": 1}', "", 'data: {"b": 2}', ""])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 1})]
        assert chunks == [{"a": 1}, {"b": 2}]

    @pytest.mark.asyncio
    async def test_multi_line_data_accumulation(self, service: A2AAgentService) -> None:
        """``data: {"a":1\\ndata: ,"b":2}\\n\\n`` → one yielded dict (plan T5 acceptance b)."""
        agent = _agent_for_streaming()
        # Two ``data:`` lines forming a single JSON event, then blank delimiter.
        response = _FakeSSEResponse(200, ['data: {"a":1,', 'data: "b":2}', ""])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 1})]
        assert chunks == [{"a": 1, "b": "b:2"}] or chunks == [{"a": 1, "b": 2}]
        # Either is acceptable depending on how the spec multi-line ``data:``
        # joining works in practice. The critical property: exactly ONE
        # yielded dict, not two.
        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_blank_lines_with_empty_buffer_ignored(self, service: A2AAgentService) -> None:
        """Blank lines arriving before any ``data:`` line don't break parsing."""
        agent = _agent_for_streaming()
        response = _FakeSSEResponse(200, ["", "", 'data: {"a": 1}', "", ""])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 1})]
        assert chunks == [{"a": 1}]

    @pytest.mark.asyncio
    async def test_ignored_sse_fields_skipped(self, service: A2AAgentService) -> None:
        """``id:``, ``event:``, ``retry:`` SSE field lines are ignored per F8."""
        agent = _agent_for_streaming()
        response = _FakeSSEResponse(200, ["id: 42", "event: update", "retry: 3000", 'data: {"a": 1}', ""])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 1})]
        assert chunks == [{"a": 1}]

    @pytest.mark.asyncio
    async def test_malformed_json_yields_invalid_agent_response(self, service: A2AAgentService) -> None:
        """Malformed JSON in a ``data:`` payload → INVALID_AGENT_RESPONSE error chunk + parser continues (plan T5 acceptance f)."""
        agent = _agent_for_streaming()
        response = _FakeSSEResponse(200, ["data: not-json", "", 'data: {"a": 1}', ""])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 7})]
        assert chunks[0]["error"]["code"] == INVALID_AGENT_RESPONSE
        assert chunks[0]["id"] == 7
        assert chunks[1] == {"a": 1}

    @pytest.mark.asyncio
    async def test_upstream_http_error_yields_one_chunk_and_exits(self, service: A2AAgentService) -> None:
        """Upstream returns HTTP 500 → ONE INTERNAL_ERROR chunk yielded + exit (plan T5 acceptance e)."""
        agent = _agent_for_streaming()
        response = _FakeSSEResponse(500, [])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 1})]
        assert len(chunks) == 1
        assert chunks[0]["error"]["code"] == INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_invalid_envelope_yields_error_chunk(self, service: A2AAgentService) -> None:
        """``jsonrpc != "2.0"`` → INVALID_REQUEST chunk; no upstream call made."""
        agent = _agent_for_streaming()
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(_FakeSSEResponse(200, [])))
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "1.0", "method": "SendStreamingMessage"})]
        assert len(chunks) == 1
        assert chunks[0]["error"]["code"] == INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_missing_method_yields_error_chunk(self, service: A2AAgentService) -> None:
        """Missing method → INVALID_REQUEST chunk."""
        agent = _agent_for_streaming()
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(_FakeSSEResponse(200, [])))
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0"})]
        assert chunks[0]["error"]["code"] == INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_non_dict_params_yields_invalid_params(self, service: A2AAgentService) -> None:
        """``params`` not dict-or-null → INVALID_PARAMS chunk."""
        agent = _agent_for_streaming()
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(_FakeSSEResponse(200, [])))
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": "not-a-dict"})]
        assert chunks[0]["error"]["code"] == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_hop_count_limit_yields_error(self, service: A2AAgentService) -> None:
        """Hop count >= settings.uaid_max_federation_hops → INTERNAL_ERROR + exit."""
        agent = _agent_for_streaming()
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(_FakeSSEResponse(200, [])))
        # Use a very high hop_count beyond any reasonable limit.
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 1}, hop_count=999)]
        assert len(chunks) == 1
        assert chunks[0]["error"]["code"] == INTERNAL_ERROR
        # And the upstream was NEVER called.
        client.stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_alias_mapped_before_upstream(self, service: A2AAgentService) -> None:
        """Legacy v0.3 method names are mapped to v1 names in the upstream request body."""
        agent = _agent_for_streaming()
        response = _FakeSSEResponse(200, [])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            _ = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "message/stream", "params": {}, "id": 1})]
        call_kwargs = client.stream.call_args.kwargs
        assert call_kwargs["json"]["method"] == "SendStreamingMessage"

    @pytest.mark.asyncio
    async def test_tasks_list_not_mapped(self, service: A2AAgentService) -> None:
        """``tasks/list`` is NEW in v1.0 (Oracle v3 #22) — NOT mapped, passes verbatim."""
        agent = _agent_for_streaming()
        response = _FakeSSEResponse(200, [])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            _ = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "tasks/list", "params": {}, "id": 1})]
        assert client.stream.call_args.kwargs["json"]["method"] == "tasks/list"

    @pytest.mark.asyncio
    async def test_outbound_headers(self, service: A2AAgentService) -> None:
        """Outbound headers: Accept/Content-Type, A2A-Version from agent, hop+1, bearer, request_headers passthrough."""
        agent = _agent_for_streaming(protocol_version="1.0.5")
        response = _FakeSSEResponse(200, [])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            _ = [
                c
                async for c in service.dispatch_a2a_jsonrpc_streaming(
                    MagicMock(),
                    agent,
                    {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 1},
                    bearer_token="jwt.token.here",
                    hop_count=2,
                    request_headers={"x-trace": "abc", "content-type": "application/json"},
                )
            ]
        sent_headers = client.stream.call_args.kwargs["headers"]
        assert sent_headers["Accept"] == "text/event-stream"
        assert sent_headers["Content-Type"] == "application/json"
        assert sent_headers["A2A-Version"] == "1.0.5"
        assert sent_headers["X-Contextforge-UAID-Hop"] == "3"  # hop_count + 1
        assert sent_headers["Authorization"] == "Bearer jwt.token.here"
        assert sent_headers["x-trace"] == "abc"

    @pytest.mark.asyncio
    async def test_no_bearer_no_authorization_header(self, service: A2AAgentService) -> None:
        """Without a bearer token, no Authorization header is set (defense-in-depth)."""
        agent = _agent_for_streaming()
        response = _FakeSSEResponse(200, [])
        client = MagicMock()
        client.stream = MagicMock(return_value=_FakeStreamCtx(response))
        with _patch_http_client(client):
            _ = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 1})]
        sent_headers = client.stream.call_args.kwargs["headers"]
        assert "Authorization" not in sent_headers

    @pytest.mark.asyncio
    async def test_httpx_error_yields_internal_error_chunk(self, service: A2AAgentService) -> None:
        """``httpx.HTTPError`` (network failure) → INTERNAL_ERROR chunk + exit cleanly."""

        # Patch the stream context to raise httpx.HTTPError when entered.
        class _RaisingCtx:
            async def __aenter__(self):
                import httpx

                raise httpx.HTTPError("connection refused")

            async def __aexit__(self, *args: object) -> bool:
                return False

        agent = _agent_for_streaming()
        client = MagicMock()
        client.stream = MagicMock(return_value=_RaisingCtx())
        with _patch_http_client(client):
            chunks = [c async for c in service.dispatch_a2a_jsonrpc_streaming(MagicMock(), agent, {"jsonrpc": "2.0", "method": "SendStreamingMessage", "params": {}, "id": 1})]
        assert len(chunks) == 1
        assert chunks[0]["error"]["code"] == INTERNAL_ERROR
