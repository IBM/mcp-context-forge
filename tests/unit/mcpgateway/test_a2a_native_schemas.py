# -*- coding: utf-8 -*-
"""Tests for A2A 1.0.0 native Pydantic schemas (plan T1).

Location: ./tests/unit/mcpgateway/test_a2a_native_schemas.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Asserts strict field-name enforcement (plan D8/D9) and round-trip JSON shape:

- ``protocolBinding`` is the only accepted JSON name for the binding field
  (rejects ``transportProtocol`` even though the SDK silently drops it —
  the gotcha the planning session burned a debug cycle on already).
- ``protocolVersion`` lives on :class:`SupportedInterface` only, NEVER at
  :class:`AgentCard` root.
- Round-trip ``model_dump(by_alias=True)`` emits camelCase wire form.
- ``extra="forbid"`` rejects unknown fields at parse time.
- ``AgentCapabilities.extendedAgentCard`` drives the dispatcher's
  ``-32007 AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED`` trigger (T12).
"""

# Future
from __future__ import annotations

# Standard
from typing import Any

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.schemas_a2a_native import (
    AgentCapabilities,
    AgentCard,
    SupportedInterface,
)


def _minimal_valid_card() -> dict[str, Any]:
    """Build a minimal spec-conformant A2A 1.0.0 card wire dict.

    Returns:
        dict[str, Any]: the JSON-wire shape a v1 ``ClientFactory.create_from_url``
            client would receive.
    """
    return {
        "name": "echo",
        "description": "Reference echo agent",
        "supportedInterfaces": [
            {
                "url": "https://gateway.example.com/a2a/echo",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "version": "1.0.0",
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": "echo",
                "name": "Echo",
                "description": "Echo back the input message",
                "tags": [],
                "examples": [],
            }
        ],
    }


class TestAgentCardValidation:
    """T1 acceptance: rejects bad field names, accepts spec-correct shape."""

    def test_minimal_valid_card_accepted(self) -> None:
        """Spec-conformant card parses without ValidationError."""
        card = AgentCard.model_validate(_minimal_valid_card())
        assert card.name == "echo"
        assert len(card.supported_interfaces) == 1
        assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
        assert card.supported_interfaces[0].protocol_version == "1.0"

    def test_rejects_transport_protocol_alias(self) -> None:
        """``transportProtocol`` is the SDK gotcha — must raise, not silently accept."""
        wire = _minimal_valid_card()
        wire["supportedInterfaces"][0]["transportProtocol"] = "JSONRPC"
        del wire["supportedInterfaces"][0]["protocolBinding"]
        with pytest.raises(ValidationError):
            AgentCard.model_validate(wire)

    def test_rejects_top_level_protocol_version(self) -> None:
        """``protocolVersion`` is per-interface in v1.0.0 — root-level must raise."""
        wire = _minimal_valid_card()
        wire["protocolVersion"] = "1.0"
        with pytest.raises(ValidationError):
            AgentCard.model_validate(wire)

    def test_rejects_unknown_field_at_root(self) -> None:
        """``extra="forbid"`` catches typos at the root level."""
        wire = _minimal_valid_card()
        wire["unknownField"] = "anything"
        with pytest.raises(ValidationError):
            AgentCard.model_validate(wire)

    def test_rejects_unknown_field_on_supported_interface(self) -> None:
        """``extra="forbid"`` catches typos inside nested objects too."""
        wire = _minimal_valid_card()
        wire["supportedInterfaces"][0]["randomField"] = "x"
        with pytest.raises(ValidationError):
            AgentCard.model_validate(wire)

    def test_required_fields_enforced(self) -> None:
        """Missing any required field raises ValidationError."""
        required = [
            "name",
            "description",
            "supportedInterfaces",
            "version",
            "capabilities",
            "defaultInputModes",
            "defaultOutputModes",
            "skills",
        ]
        for field_name in required:
            wire = _minimal_valid_card()
            del wire[field_name]
            with pytest.raises(ValidationError):
                AgentCard.model_validate(wire)

    def test_round_trip_emits_camel_case(self) -> None:
        """``model_dump(by_alias=True)`` emits the wire-correct camelCase JSON shape."""
        card = AgentCard.model_validate(_minimal_valid_card())
        wire = card.model_dump(by_alias=True, exclude_none=True)
        # camelCase wire names present
        assert "protocolBinding" in wire["supportedInterfaces"][0]
        assert "protocolVersion" in wire["supportedInterfaces"][0]
        assert "supportedInterfaces" in wire
        assert "defaultInputModes" in wire
        assert "defaultOutputModes" in wire
        # snake_case Python names NOT present in wire output
        assert "protocol_binding" not in wire["supportedInterfaces"][0]
        assert "protocol_version" not in wire["supportedInterfaces"][0]
        # ``protocolVersion`` is NEVER at the root
        assert "protocolVersion" not in wire

    def test_python_construction_with_snake_case_works(self) -> None:
        """``populate_by_name=True`` accepts Python-side snake_case construction.

        The ``# type: ignore[call-arg]`` below is honest: static type
        checkers see the alias-based constructor signature
        (``protocolBinding``/``protocolVersion``), but at runtime the
        ``populate_by_name=True`` config also accepts the snake_case
        attribute names. This test specifically validates that runtime
        path so the gateway-side code (e.g. the synthesizer in T2) can
        construct models using Pythonic kwargs.
        """
        iface = SupportedInterface(  # type: ignore[call-arg]
            url="https://x",
            protocol_binding="JSONRPC",
            protocol_version="1.0",
        )
        assert iface.protocol_binding == "JSONRPC"
        # And still serializes to camelCase
        wire = iface.model_dump(by_alias=True)
        assert wire["protocolBinding"] == "JSONRPC"


class TestSupportedInterfaceValidation:
    """SupportedInterface required field enforcement."""

    def test_requires_protocol_binding(self) -> None:
        """``protocolBinding`` is required."""
        with pytest.raises(ValidationError):
            SupportedInterface.model_validate({"url": "https://x", "protocolVersion": "1.0"})

    def test_requires_protocol_version(self) -> None:
        """``protocolVersion`` is required."""
        with pytest.raises(ValidationError):
            SupportedInterface.model_validate({"url": "https://x", "protocolBinding": "JSONRPC"})

    def test_requires_url(self) -> None:
        """``url`` is required."""
        with pytest.raises(ValidationError):
            SupportedInterface.model_validate({"protocolBinding": "JSONRPC", "protocolVersion": "1.0"})

    def test_accepts_optional_tenant(self) -> None:
        """``tenant`` is optional but accepted when present."""
        iface = SupportedInterface.model_validate(
            {
                "url": "https://x",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
                "tenant": "tenant-a",
            }
        )
        assert iface.tenant == "tenant-a"


class TestAgentCapabilitiesExtendedFlag:
    """``extendedAgentCard`` flag drives -32007 trigger in T12 dispatcher."""

    def test_default_is_false(self) -> None:
        """If no flag in input dict, parsed model has False — triggers -32007."""
        caps = AgentCapabilities.model_validate({})
        assert caps.extended_agent_card is False

    def test_explicit_true(self) -> None:
        """When the agent supports it, parsing preserves the flag."""
        caps = AgentCapabilities.model_validate({"extendedAgentCard": True})
        assert caps.extended_agent_card is True

    def test_wire_camel_case(self) -> None:
        """Serialization uses ``extendedAgentCard`` camelCase wire name.

        ``# type: ignore[call-arg]`` is honest: static type checkers see
        the alias-based signature; ``populate_by_name=True`` allows the
        snake_case attribute name at runtime.
        """
        caps = AgentCapabilities(extended_agent_card=True)  # type: ignore[call-arg]
        wire = caps.model_dump(by_alias=True)
        assert wire["extendedAgentCard"] is True
        assert "extended_agent_card" not in wire
