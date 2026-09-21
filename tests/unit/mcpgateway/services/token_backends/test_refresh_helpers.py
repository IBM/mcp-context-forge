# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/token_backends/test_refresh_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for shared OAuth token refresh helper functions.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.token_backends.refresh_helpers import (
    apply_omit_resource_and_normalize,
    compute_prior_ttl,
)


# ============================================================================
# compute_prior_ttl() Tests
# ============================================================================


def test_compute_prior_ttl_with_datetime_objects():
    """compute_prior_ttl handles datetime objects (DatabaseTokenBackend path)."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=3600)
    updated_at = now

    result = compute_prior_ttl(expires_at, updated_at, "gw-1")

    assert result == 3600


def test_compute_prior_ttl_with_iso_strings():
    """compute_prior_ttl handles ISO strings (VaultTokenBackend path)."""
    expires_at = "2026-07-27T12:00:00Z"
    updated_at = "2026-07-27T11:00:00Z"

    result = compute_prior_ttl(expires_at, updated_at, "gw-1")

    assert result == 3600


def test_compute_prior_ttl_with_iso_strings_plus_timezone():
    """compute_prior_ttl handles ISO strings with +00:00 timezone."""
    expires_at = "2026-07-27T12:00:00+00:00"
    updated_at = "2026-07-27T11:00:00+00:00"

    result = compute_prior_ttl(expires_at, updated_at, "gw-1")

    assert result == 3600


def test_compute_prior_ttl_missing_expires_at():
    """compute_prior_ttl returns None when expires_at is missing."""
    updated_at = "2026-07-27T11:00:00Z"

    result = compute_prior_ttl(None, updated_at, "gw-1")

    assert result is None


def test_compute_prior_ttl_missing_updated_at():
    """compute_prior_ttl returns None when updated_at is missing."""
    expires_at = "2026-07-27T12:00:00Z"

    result = compute_prior_ttl(expires_at, None, "gw-1")

    assert result is None


def test_compute_prior_ttl_both_missing():
    """compute_prior_ttl returns None when both timestamps missing."""
    result = compute_prior_ttl(None, None, "gw-1")

    assert result is None


def test_compute_prior_ttl_negative_ttl():
    """compute_prior_ttl returns None when TTL is negative (clock skew)."""
    # expires_at is BEFORE updated_at (impossible scenario)
    expires_at = "2026-07-27T11:00:00Z"
    updated_at = "2026-07-27T12:00:00Z"

    result = compute_prior_ttl(expires_at, updated_at, "gw-1")

    assert result is None


def test_compute_prior_ttl_zero_ttl():
    """compute_prior_ttl returns None when TTL is zero."""
    same_time = "2026-07-27T12:00:00Z"

    result = compute_prior_ttl(same_time, same_time, "gw-1")

    assert result is None


def test_compute_prior_ttl_naive_datetime():
    """compute_prior_ttl handles naive datetime (no timezone info)."""
    now = datetime.now()  # Naive datetime
    expires_at = now + timedelta(seconds=3600)
    updated_at = now

    result = compute_prior_ttl(expires_at, updated_at, "gw-1")

    assert result == 3600


def test_compute_prior_ttl_mixed_aware_and_naive():
    """compute_prior_ttl handles mixed aware and naive datetimes."""
    # Use same base time to ensure positive TTL
    base_time = datetime.now()
    aware_time = base_time.replace(tzinfo=timezone.utc) + timedelta(seconds=3600)
    naive_time = base_time

    result = compute_prior_ttl(aware_time, naive_time, "gw-1")

    # Should handle by normalizing to UTC and computing TTL
    assert result is not None
    assert isinstance(result, int)
    assert result > 0


def test_compute_prior_ttl_invalid_iso_string():
    """compute_prior_ttl returns None for invalid ISO string."""
    result = compute_prior_ttl("not-a-date", "2026-07-27T11:00:00Z", "gw-1")

    assert result is None


def test_compute_prior_ttl_large_ttl():
    """compute_prior_ttl handles large TTL values (e.g., 7 days)."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)
    updated_at = now

    result = compute_prior_ttl(expires_at, updated_at, "gw-1")

    assert result == 7 * 24 * 3600  # 604800 seconds


@patch("mcpgateway.services.token_backends.refresh_helpers.logger")
def test_compute_prior_ttl_logs_success(mock_logger):
    """compute_prior_ttl logs when TTL is successfully computed."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=3600)
    updated_at = now

    result = compute_prior_ttl(expires_at, updated_at, "gw-test-123")

    assert result == 3600
    # Check that info log was called
    mock_logger.info.assert_called_once()
    call_args = mock_logger.info.call_args[0]
    assert "gw-test-123" in str(call_args)
    assert "3600" in str(call_args)


# ============================================================================
# apply_omit_resource_and_normalize() Tests
# ============================================================================


def test_apply_omit_resource_when_true_removes_existing():
    """omit_resource=true removes existing resource parameter."""
    oauth_config = {
        "client_id": "test-client",
        "omit_resource": True,
        "resource": "https://api.example.com",
    }

    apply_omit_resource_and_normalize(oauth_config, "https://gateway.example.com", "gw-1")

    assert "resource" not in oauth_config


def test_apply_omit_resource_when_true_no_resource_present():
    """omit_resource=true is no-op when resource not present."""
    oauth_config = {
        "client_id": "test-client",
        "omit_resource": True,
    }

    apply_omit_resource_and_normalize(oauth_config, "https://gateway.example.com", "gw-1")

    assert "resource" not in oauth_config


def test_apply_omit_resource_when_false_injects_from_gateway_url():
    """omit_resource=false (default) injects resource from gateway.url."""
    oauth_config = {
        "client_id": "test-client",
    }
    gateway_url = "https://gateway.example.com"

    apply_omit_resource_and_normalize(oauth_config, gateway_url, "gw-1")

    assert oauth_config["resource"] == "https://gateway.example.com"


def test_apply_omit_resource_when_false_preserves_existing():
    """omit_resource=false preserves explicitly configured resource."""
    oauth_config = {
        "client_id": "test-client",
        "resource": "https://custom.example.com",
    }

    apply_omit_resource_and_normalize(oauth_config, "https://gateway.example.com", "gw-1")

    # Should normalize but keep the explicitly configured resource
    assert oauth_config["resource"] == "https://custom.example.com"


def test_apply_omit_resource_normalizes_url_strips_fragment():
    """Resource URL is normalized (fragment stripped)."""
    oauth_config = {
        "client_id": "test-client",
        "resource": "https://api.example.com/path#fragment",
    }

    apply_omit_resource_and_normalize(oauth_config, None, "gw-1")

    assert oauth_config["resource"] == "https://api.example.com/path"


def test_apply_omit_resource_normalizes_url_strips_query():
    """Resource URL is normalized (origin-level for auto-derived per RFC 8707 §2.2)."""
    oauth_config = {
        "client_id": "test-client",
    }
    gateway_url = "https://gateway.example.com/path?query=value"

    apply_omit_resource_and_normalize(oauth_config, gateway_url, "gw-1")

    # Auto-derived resource is origin-level (scheme + netloc only)
    assert oauth_config["resource"] == "https://gateway.example.com"


def test_apply_omit_resource_preserves_query_for_explicit():
    """Resource URL preserves query for explicitly configured resource."""
    oauth_config = {
        "client_id": "test-client",
        "resource": "https://api.example.com/path?audience=custom",
    }

    apply_omit_resource_and_normalize(oauth_config, None, "gw-1")

    # Explicitly configured resource preserves query
    assert oauth_config["resource"] == "https://api.example.com/path?audience=custom"


def test_apply_omit_resource_handles_resource_list():
    """Resource parameter as list is normalized."""
    oauth_config = {
        "client_id": "test-client",
        "resource": [
            "https://api1.example.com",
            "https://api2.example.com#fragment",
            "https://api3.example.com?query=1",
        ],
    }

    apply_omit_resource_and_normalize(oauth_config, None, "gw-1")

    # Each resource in list should be normalized
    assert oauth_config["resource"] == [
        "https://api1.example.com",
        "https://api2.example.com",
        "https://api3.example.com?query=1",  # Explicit preserves query
    ]


def test_apply_omit_resource_handles_empty_string_in_list():
    """Empty strings in resource list are removed."""
    oauth_config = {
        "client_id": "test-client",
        "resource": [
            "https://api1.example.com",
            "",
            "https://api2.example.com",
        ],
    }

    apply_omit_resource_and_normalize(oauth_config, None, "gw-1")

    assert oauth_config["resource"] == [
        "https://api1.example.com",
        "https://api2.example.com",
    ]


def test_apply_omit_resource_handles_all_empty_resources():
    """All empty resources in list triggers warning."""
    oauth_config = {
        "client_id": "test-client",
        "resource": ["", "", ""],
    }

    with patch("mcpgateway.services.token_backends.refresh_helpers.logger") as mock_logger:
        apply_omit_resource_and_normalize(oauth_config, None, "gw-1")

        # Should log warning about empty resources
        mock_logger.warning.assert_called()
        assert oauth_config["resource"] == []


def test_apply_omit_resource_handles_empty_gateway_url():
    """Empty gateway_url is handled gracefully."""
    oauth_config = {
        "client_id": "test-client",
    }

    # Empty gateway_url should not add resource parameter (no warning expected)
    apply_omit_resource_and_normalize(oauth_config, "", "gw-1")

    # Should not add resource when gateway_url is empty
    assert "resource" not in oauth_config


def test_apply_omit_resource_handles_none_gateway_url():
    """None gateway_url is handled gracefully."""
    oauth_config = {
        "client_id": "test-client",
    }

    apply_omit_resource_and_normalize(oauth_config, None, "gw-1")

    # Should not add resource when gateway_url is None
    assert "resource" not in oauth_config


def test_apply_omit_resource_opaque_identifier_passthrough():
    """Opaque identifiers (non-URL) are passed through unchanged."""
    oauth_config = {
        "client_id": "test-client",
        "resource": "client-id-123",  # Opaque identifier (no scheme)
    }

    apply_omit_resource_and_normalize(oauth_config, None, "gw-1")

    # Should preserve opaque identifier unchanged
    assert oauth_config["resource"] == "client-id-123"


@patch("mcpgateway.services.token_backends.refresh_helpers.logger")
def test_apply_omit_resource_logs_omit_debug(mock_logger):
    """omit_resource=true logs debug message."""
    oauth_config = {
        "client_id": "test-client",
        "omit_resource": True,
        "resource": "https://api.example.com",
    }

    apply_omit_resource_and_normalize(oauth_config, "https://gateway.example.com", "gw-test-456")

    # Check that debug log was called
    mock_logger.debug.assert_called_once()
    call_args = mock_logger.debug.call_args[0]
    assert "gw-test-456" in str(call_args)
    assert "omit_resource=true" in str(call_args)


def test_apply_omit_resource_empty_resource_string():
    """Empty resource string is normalized to None."""
    oauth_config = {
        "client_id": "test-client",
        "resource": "",
    }

    with patch("mcpgateway.services.token_backends.refresh_helpers.logger") as mock_logger:
        apply_omit_resource_and_normalize(oauth_config, None, "gw-1")

        # Empty resource should be normalized (warning logged for explicitly configured empty string)
        assert oauth_config.get("resource") in [None, ""]
        # Warning may or may not be logged depending on normalization logic
