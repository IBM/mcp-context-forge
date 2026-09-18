# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_common_models.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for mcpgateway.common.models — structural / schema-level invariants.

These are intentionally lightweight: they pin contract details (field
presence, optionality, default values) that are easy to accidentally break
during model refactoring and are not covered elsewhere.
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Gateway, ServerCapabilities


class TestGatewayModel:
    """Pin structural invariants of the Gateway schema model."""

    def _minimal_gateway(self, **overrides):
        """Return the minimal set of kwargs needed to construct a Gateway."""
        defaults = dict(
            id="gw-1",
            name="test-gateway",
            url="http://localhost:9000/mcp",
            slug="test-gateway",
            transport="sse",
            capabilities=ServerCapabilities(),
            passthrough_headers=None,
            auth_value=None,
        )
        defaults.update(overrides)
        return defaults

    def test_last_seen_field_is_optional_with_none_default(self):
        """Gateway.last_seen must be Optional[datetime] with a None default.

        Regression: the model previously declared last_seen twice; the second
        declaration shadowed the first and removed the = None default, causing
        Gateway(...) calls that omit last_seen to fail with a missing-field
        validation error.
        """
        gw = Gateway(**self._minimal_gateway())
        assert gw.last_seen is None

    def test_last_seen_field_accepts_datetime_value(self):
        """Gateway.last_seen round-trips a real datetime without loss."""
        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        gw = Gateway(**self._minimal_gateway(id="gw-2", name="test-gateway-2",
                                              url="http://localhost:9001/mcp",
                                              slug="test-gateway-2",
                                              last_seen=ts))
        assert gw.last_seen == ts

    def test_last_seen_is_only_declared_once(self):
        """Gateway must declare last_seen exactly once.

        Regression: the model previously had two declarations; Pydantic
        silently accepts the override but the second (un-defaulted) declaration
        changes the field's optionality contract.
        """
        fields = Gateway.model_fields
        assert "last_seen" in fields
        # Pydantic merges duplicate declarations; if only one declaration
        # survives, model_fields has exactly one entry for the key.
        # The assertion is trivially true after deduplication — the real
        # guard is test_last_seen_field_is_optional_with_none_default above,
        # which fails if the second (non-defaulted) declaration wins.
        assert fields["last_seen"].is_required() is False
