# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_common_models.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for mcpgateway/common/models.py.
"""

# First-Party
from mcpgateway.common.models import Gateway, ServerCapabilities


class TestGatewayModel:
    """Regression tests for the Gateway model."""

    def test_last_seen_is_optional_with_default(self):
        """Duplicate `last_seen` field declaration must not make the field required.

        The model previously declared `last_seen` twice; the second declaration
        (no default) shadowed the first and made the field implicitly required.
        """
        field = Gateway.model_fields["last_seen"]
        assert not field.is_required()
        assert field.default is None

    def test_gateway_instantiates_without_last_seen(self):
        """A Gateway can be constructed without providing last_seen."""
        gateway = Gateway(
            id="g1",
            name="test-gateway",
            url="http://example.com",
            capabilities=ServerCapabilities(),
            slug="test-gateway",
            transport="sse",
            passthrough_headers=None,
            auth_value=None,
        )
        assert gateway.last_seen is None
