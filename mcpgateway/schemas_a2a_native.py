# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/schemas_a2a_native.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

A2A 1.0.0 wire-format Pydantic models for native passthrough.

These models serialize to the spec-correct camelCase JSON wire shape used
by ``a2a-sdk`` clients (``ClientFactory.create_from_url(...)``). They are
intentionally separate from the legacy v0.3-shaped dict returned by
``a2a_service.get_agent_card()`` (kept in place for the existing internal
trusted-MCP-runtime endpoint at ``mcpgateway/main.py:9372-9405``).

Strict field-name enforcement (plan D8/D9):

- JSON field is ``protocolBinding`` (camelCase). The Python attribute is
  ``protocol_binding`` (snake_case). ``Field(alias="protocolBinding")``
  binds the two; ``populate_by_name=True`` lets Python-side construction
  use the snake form too.
- ``protocolVersion`` lives on ``SupportedInterface`` only, NEVER on the
  ``AgentCard`` root. The v1.0.0 spec moved it per-interface (proto
  L334-L355 vs the v0.3 top-level location).
- ``extra="forbid"`` rejects unknown fields at parse time, preventing
  silent acceptance of typos like ``transportProtocol`` that the SDK
  would drop instead of erroring on. The session that produced this plan
  hit exactly that bug once already (``ClientFactory`` raised "no
  compatible transports found" because a misnamed field was dropped).

These models are the canonical wire shape for native A2A 1.0.0 passthrough
emitted by the synthesizer in ``a2a_service.synthesize_agent_card`` (T2).
The legacy ``a2a_service.get_agent_card()`` is intentionally NOT migrated
through these models per plan D12 — it stays on the v0.3-shaped dict.
"""

from __future__ import annotations

# Standard
from typing import Any, Dict, List, Optional

# Third-Party
from pydantic import BaseModel, ConfigDict, Field


def _camel_config() -> ConfigDict:
    """Build the shared :class:`ConfigDict` for all native A2A models.

    Returns:
        ConfigDict: configured for camelCase JSON serialization with strict
            unknown-field rejection. Use this on every model in this module
            so the wire contract is uniform.

    Examples:
        >>> cfg = _camel_config()
        >>> cfg["populate_by_name"]
        True
        >>> cfg["extra"]
        'forbid'
    """
    return ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )


class AgentProvider(BaseModel):
    """A2A 1.0.0 ``AgentProvider`` (optional on :class:`AgentCard`)."""

    model_config = _camel_config()

    organization: Optional[str] = None
    url: Optional[str] = None


class AgentCapabilities(BaseModel):
    """A2A 1.0.0 ``AgentCapabilities`` (required on :class:`AgentCard`).

    The ``extended_agent_card`` flag drives the JSON-RPC
    ``-32007 AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED`` trigger in
    the dispatcher (plan T12 step 8). When the upstream agent does NOT
    advertise extended-card support, the gateway returns ``-32007`` for
    ``GetExtendedAgentCard`` instead of synthesizing a placeholder.
    """

    model_config = _camel_config()

    streaming: bool = False
    push_notifications: bool = Field(default=False, alias="pushNotifications")
    state_transition_history: bool = Field(default=False, alias="stateTransitionHistory")
    extended_agent_card: bool = Field(default=False, alias="extendedAgentCard")


class AgentSkill(BaseModel):
    """A2A 1.0.0 ``AgentSkill`` (at least one required on :class:`AgentCard`)."""

    model_config = _camel_config()

    id: str
    name: str
    description: str
    tags: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    input_modes: Optional[List[str]] = Field(default=None, alias="inputModes")
    output_modes: Optional[List[str]] = Field(default=None, alias="outputModes")


class SupportedInterface(BaseModel):
    """A2A 1.0.0 ``SupportedInterface`` entry on :class:`AgentCard`.

    Required fields per spec proto L334-L355: ``url``, ``protocolBinding``,
    ``protocolVersion``. Optional ``tenant`` for multi-tenant routing.

    Wire-name enforcement:

    - ``protocolBinding`` is the JSON field name (proto ``protocol_binding``).
      The Python attribute is ``protocol_binding``. Aliases bind them.
    - ``protocolVersion`` is REQUIRED here and NEVER at :class:`AgentCard`
      root. ``extra="forbid"`` on :class:`AgentCard` enforces this.
    """

    model_config = _camel_config()

    url: str
    protocol_binding: str = Field(alias="protocolBinding")
    protocol_version: str = Field(alias="protocolVersion")
    tenant: Optional[str] = None


class AgentCard(BaseModel):
    """A2A 1.0.0 ``AgentCard`` wire model.

    Required fields per spec proto L361-L398: ``name``, ``description``,
    ``supportedInterfaces``, ``version``, ``capabilities``,
    ``defaultInputModes``, ``defaultOutputModes``, ``skills``.

    Optional: ``provider``, ``documentationUrl``, ``securitySchemes``,
    ``securityRequirements``, ``signatures``, ``iconUrl``.

    Critical D9 invariant: ``protocolVersion`` does NOT live here in
    v1.0.0 — it moved onto each :class:`SupportedInterface` entry. A
    top-level ``protocolVersion`` on this model is rejected by
    ``extra="forbid"``.
    """

    model_config = _camel_config()

    name: str
    description: str
    supported_interfaces: List[SupportedInterface] = Field(alias="supportedInterfaces")
    version: str
    capabilities: AgentCapabilities
    default_input_modes: List[str] = Field(alias="defaultInputModes")
    default_output_modes: List[str] = Field(alias="defaultOutputModes")
    skills: List[AgentSkill]
    provider: Optional[AgentProvider] = None
    documentation_url: Optional[str] = Field(default=None, alias="documentationUrl")
    security_schemes: Optional[Dict[str, Any]] = Field(default=None, alias="securitySchemes")
    security_requirements: Optional[List[Dict[str, Any]]] = Field(default=None, alias="securityRequirements")
    signatures: Optional[List[Dict[str, Any]]] = None
    icon_url: Optional[str] = Field(default=None, alias="iconUrl")
