# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_gateway_test_ssrf_protection.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for SSRF protection in the /admin/gateways/test endpoint.

This module tests that the gateway test endpoint properly respects the global
ssrf_protection_enabled flag and enforces allowlist-based restrictions to prevent
Server-Side Request Forgery (SSRF) attacks.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.common.validators import SecurityValidator


class TestGatewayTestSSRFProtection:
    """Test SSRF protection for gateway test endpoint."""

    @pytest.mark.asyncio
    async def test_private_ip_blocked_when_ssrf_enabled(self):
        """Test that private IPs are blocked when SSRF protection is enabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            with pytest.raises(ValueError, match="is not allowed"):
                await SecurityValidator.validate_gateway_test_url(
                    "https://192.168.1.1/api",
                    allowed_hosts=["192.168.1.1"],
                    field_name="Gateway test URL"
                )

    @pytest.mark.asyncio
    async def test_private_ip_allowed_when_ssrf_disabled(self):
        """Test that private IPs are allowed when SSRF protection is disabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = False
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution to return the private IP
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("192.168.1.1", 0))
                ]

                result = await SecurityValidator.validate_gateway_test_url(
                    "https://192.168.1.1/api",
                    allowed_hosts=["192.168.1.1"],
                    field_name="Gateway test URL"
                )

                assert result["validated_url"] == "https://192.168.1.1/api"
                assert result["hostname"] == "192.168.1.1"
                assert result["resolved_ip"] == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_loopback_blocked_when_ssrf_enabled(self):
        """Test that loopback addresses are blocked when SSRF protection is enabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            with pytest.raises(ValueError, match="is not allowed"):
                await SecurityValidator.validate_gateway_test_url(
                    "https://127.0.0.1/api",
                    allowed_hosts=["127.0.0.1"],
                    field_name="Gateway test URL"
                )

    @pytest.mark.asyncio
    async def test_loopback_allowed_when_ssrf_disabled(self):
        """Test that loopback addresses are allowed when SSRF protection is disabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = False
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("127.0.0.1", 0))
                ]

                result = await SecurityValidator.validate_gateway_test_url(
                    "https://127.0.0.1/api",
                    allowed_hosts=["127.0.0.1"],
                    field_name="Gateway test URL"
                )

                assert result["validated_url"] == "https://127.0.0.1/api"
                assert result["hostname"] == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_link_local_blocked_when_ssrf_enabled(self):
        """Test that link-local addresses are blocked when SSRF protection is enabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            with pytest.raises(ValueError, match="is not allowed"):
                await SecurityValidator.validate_gateway_test_url(
                    "https://169.254.169.254/latest/meta-data",
                    allowed_hosts=["169.254.169.254"],
                    field_name="Gateway test URL"
                )

    @pytest.mark.asyncio
    async def test_carrier_grade_nat_blocked_when_ssrf_enabled(self):
        """Test that carrier-grade NAT addresses are blocked when SSRF protection is enabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            with pytest.raises(ValueError, match="is not allowed"):
                await SecurityValidator.validate_gateway_test_url(
                    "https://100.64.0.1/api",
                    allowed_hosts=["100.64.0.1"],
                    field_name="Gateway test URL"
                )

    @pytest.mark.asyncio
    async def test_public_ip_allowed_with_ssrf_enabled(self):
        """Test that public IPs are allowed when in allowlist and SSRF protection is enabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution to return a public IP
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("8.8.8.8", 0))
                ]

                result = await SecurityValidator.validate_gateway_test_url(
                    "https://8.8.8.8/api",
                    allowed_hosts=["8.8.8.8"],
                    field_name="Gateway test URL"
                )

                assert result["validated_url"] == "https://8.8.8.8/api"
                assert result["hostname"] == "8.8.8.8"
                assert result["resolved_ip"] == "8.8.8.8"

    @pytest.mark.asyncio
    async def test_hostname_resolving_to_private_ip_blocked_when_ssrf_enabled(self):
        """Test that hostnames resolving to private IPs are blocked when SSRF protection is enabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution to return a private IP
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("192.168.1.100", 0))
                ]

                with pytest.raises(ValueError, match="is not allowed"):
                    await SecurityValidator.validate_gateway_test_url(
                        "https://internal.example.com/api",
                        allowed_hosts=["internal.example.com"],
                        field_name="Gateway test URL"
                    )

    @pytest.mark.asyncio
    async def test_hostname_resolving_to_private_ip_allowed_when_ssrf_disabled(self):
        """Test that hostnames resolving to private IPs are allowed when SSRF protection is disabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = False
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution to return a private IP
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("192.168.1.100", 0))
                ]

                result = await SecurityValidator.validate_gateway_test_url(
                    "https://internal.example.com/api",
                    allowed_hosts=["internal.example.com"],
                    field_name="Gateway test URL"
                )

                assert result["validated_url"] == "https://internal.example.com/api"
                assert result["hostname"] == "internal.example.com"
                assert result["resolved_ip"] == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_allowlist_enforcement_independent_of_ssrf_flag(self):
        """Test that allowlist enforcement works regardless of SSRF protection flag."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = False
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("8.8.8.8", 0))
                ]

                # Should fail because not in allowlist, even with SSRF disabled
                with pytest.raises(ValueError, match="is not allowed"):
                    await SecurityValidator.validate_gateway_test_url(
                        "https://evil.com/api",
                        allowed_hosts=["trusted.com"],
                        field_name="Gateway test URL"
                    )

    @pytest.mark.asyncio
    async def test_empty_allowlist_rejects_all(self):
        """Test that empty allowlist rejects all URLs regardless of SSRF flag."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = False
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("8.8.8.8", 0))
                ]

                with pytest.raises(ValueError, match="is not allowed"):
                    await SecurityValidator.validate_gateway_test_url(
                        "https://example.com/api",
                        allowed_hosts=[],
                        field_name="Gateway test URL"
                    )

    @pytest.mark.asyncio
    async def test_wildcard_subdomain_matching(self):
        """Test that wildcard subdomain patterns work correctly."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution to return a public IP
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("93.184.216.34", 0))  # example.com public IP
                ]

                result = await SecurityValidator.validate_gateway_test_url(
                    "https://api.example.com/v1",
                    allowed_hosts=["*.example.com"],
                    field_name="Gateway test URL"
                )

                assert result["validated_url"] == "https://api.example.com/v1"
                assert result["hostname"] == "api.example.com"
                # Verify that resolved IP was captured
                assert result["resolved_ip"] == "93.184.216.34"

    @pytest.mark.asyncio
    async def test_ipv6_loopback_blocked_when_ssrf_enabled(self):
        """Test that IPv6 loopback addresses are blocked when SSRF protection is enabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            with pytest.raises(ValueError, match="is not allowed"):
                await SecurityValidator.validate_gateway_test_url(
                    "https://[::1]/api",
                    allowed_hosts=["::1"],
                    field_name="Gateway test URL"
                )

    @pytest.mark.asyncio
    async def test_ipv6_link_local_blocked_when_ssrf_enabled(self):
        """Test that IPv6 link-local addresses are blocked when SSRF protection is enabled."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            with pytest.raises(ValueError, match="is not allowed"):
                await SecurityValidator.validate_gateway_test_url(
                    "https://[fe80::1]/api",
                    allowed_hosts=["fe80::1"],
                    field_name="Gateway test URL"
                )

    @pytest.mark.asyncio
    async def test_dns_rebinding_protection(self):
        """Test that DNS resolution captures IP for rebinding protection."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution to return a public IP
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("93.184.216.34", 0))  # example.com public IP
                ]

                result = await SecurityValidator.validate_gateway_test_url(
                    "https://example.com/api",
                    allowed_hosts=["example.com"],
                    field_name="Gateway test URL"
                )

                # Verify that resolved IP is captured for pinning
                assert result["resolved_ip"] == "93.184.216.34"
                assert result["hostname"] == "example.com"

    @pytest.mark.asyncio
    async def test_fqdn_normalization_prevents_bypass(self):
        """Test that trailing dots in FQDNs are normalized to prevent bypass."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            # Mock DNS resolution to return a public IP
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (2, 1, 6, "", ("93.184.216.34", 0))  # example.com public IP
                ]

                # Trailing dot should be normalized and match allowlist
                result = await SecurityValidator.validate_gateway_test_url(
                    "https://example.com./api",
                    allowed_hosts=["example.com"],
                    field_name="Gateway test URL"
                )

                assert result["hostname"] == "example.com."
                # Verify that resolved IP was captured
                assert result["resolved_ip"] == "93.184.216.34"

    @pytest.mark.asyncio
    async def test_consistency_with_standard_validate_url(self):
        """Test that gateway test validation calls standard validate_url first."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 5.0

            # Invalid URL should be caught by standard validation
            with pytest.raises(ValueError, match="is not allowed"):
                await SecurityValidator.validate_gateway_test_url(
                    "javascript:alert(1)",
                    allowed_hosts=["example.com"],
                    field_name="Gateway test URL"
                )

    @pytest.mark.asyncio
    async def test_dns_timeout_configuration(self):
        """Test that DNS timeout is configurable."""
        with patch("mcpgateway.common.validators.settings") as mock_settings:
            mock_settings.ssrf_protection_enabled = True
            mock_settings.gateway_test_dns_timeout = 0.1  # Very short timeout

            # Mock slow DNS resolution
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                import asyncio
                async def slow_dns(*args, **kwargs):
                    await asyncio.sleep(1)  # Longer than timeout
                    return [(2, 1, 6, "", ("203.0.113.1", 0))]

                mock_getaddrinfo.side_effect = slow_dns

                # Should timeout and reject
                with pytest.raises(ValueError, match="is not allowed"):
                    await SecurityValidator.validate_gateway_test_url(
                        "https://example.com/api",
                        allowed_hosts=["example.com"],
                        field_name="Gateway test URL"
                    )
