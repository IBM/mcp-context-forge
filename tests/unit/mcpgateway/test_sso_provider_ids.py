# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_sso_provider_ids.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for SSO provider ID canonicalization.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.sso_provider_ids import canonicalize_sso_provider_id, SSOProviderValidationError


@pytest.mark.parametrize(
    ("provider_id", "expected"),
    [
        ("azure-ad", "entra"),
        ("AZURE-AD", "entra"),
        (" Entra ", "entra"),
        ("okta", "okta"),
        (" Custom-OIDC ", "custom-oidc"),
    ],
)
def test_canonicalize_sso_provider_id(provider_id: str, expected: str) -> None:
    """Provider IDs are normalized without becoming a hard-coded allowlist."""
    assert canonicalize_sso_provider_id(provider_id) == expected


@pytest.mark.parametrize("provider_id", ["", "   ", None])
def test_canonicalize_sso_provider_id_rejects_missing(provider_id: object) -> None:
    """Missing provider IDs raise the typed provider validation error."""
    with pytest.raises(SSOProviderValidationError, match="required"):
        canonicalize_sso_provider_id(provider_id)


def test_canonicalize_sso_provider_id_checks_length_after_aliasing() -> None:
    """Length is checked after normalization and alias resolution."""
    assert canonicalize_sso_provider_id(" " + ("x" * 50) + " ") == "x" * 50
    with pytest.raises(SSOProviderValidationError, match="exceeds 50"):
        canonicalize_sso_provider_id("x" * 51)
