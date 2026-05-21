# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_per_tool_ssl.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for per-tool SSL certificate verification.
Tests that REST API tools can use custom CA certificates from their gateway configuration.
"""

# Standard
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.tool_service import ToolService


class TestPerToolSSL:
    """Test per-tool SSL certificate verification for REST tools."""

    @staticmethod
    def _make_ca_cert_mocks():
        """Build mock SSL context and certificates for CA cert tests.

        Returns (mock_ssl_context, ca_cert, ca_cert_sig, client_cert, client_key).
        """
        mock_ssl_context = MagicMock(spec=ssl.SSLContext)
        ca_cert = "-----BEGIN CERTIFICATE-----\nMIIC...\n-----END CERTIFICATE-----"
        ca_cert_sig = "mock_signature_abc123"
        client_cert = "-----BEGIN CERTIFICATE-----\nCLIENT...\n-----END CERTIFICATE-----"
        client_key = "-----BEGIN PRIVATE KEY-----\nKEY...\n-----END PRIVATE KEY-----"  # pragma: allowlist secret

        return mock_ssl_context, ca_cert, ca_cert_sig, client_cert, client_key

    @pytest.mark.asyncio
    async def test_rest_tool_with_ca_cert_creates_custom_ssl_context(self):
        """Test that REST tools with gateway CA certificate create custom SSL context."""
        tool_service = ToolService()
        mock_ssl_context, ca_cert, ca_cert_sig, client_cert, client_key = self._make_ca_cert_mocks()

        # Mock the database and tool lookup
        mock_db = MagicMock()
        mock_tool = MagicMock()
        mock_tool.id = "test-tool-id"
        mock_tool.name = "test-tool"
        mock_tool.integration_type = "REST"
        mock_tool.enabled = True
        mock_tool.reachable = True
        mock_tool.visibility = "public"
        mock_tool.team_id = None
        mock_tool.owner_email = "test@example.com"

        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.ca_certificate = ca_cert
        mock_gateway.ca_certificate_sig = ca_cert_sig
        mock_gateway.client_cert = client_cert
        mock_gateway.client_key = client_key

        mock_tool.gateway = mock_gateway

        # Mock the cache payload that includes gateway CA cert
        cache_payload = {
            "tool": {
                "id": "test-tool-id",
                "name": "test-tool",
                "integration_type": "REST",
                "url": "https://api.example.com/endpoint",
                "request_type": "POST",
                "auth_type": "none",
                "headers": {},
                "gateway_id": "test-gateway-id",
            },
            "gateway": {
                "id": "test-gateway-id",
                "name": "test-gateway",
                "url": "https://gateway.example.com",
                "auth_type": "none",
                "ca_certificate": ca_cert,
                "ca_certificate_sig": ca_cert_sig,
                "client_cert": client_cert,
                "client_key": client_key,
            }
        }

        with patch.object(tool_service, "_load_invocable_tools", return_value=[mock_tool]):
            with patch.object(tool_service, "_check_tool_access", return_value=True):
                with patch.object(tool_service, "_build_tool_cache_payload", return_value=cache_payload):
                    with patch("mcpgateway.utils.ssl_context_cache.get_cached_ssl_context", return_value=mock_ssl_context) as mock_get_ssl:
                        with patch("mcpgateway.utils.validate_signature.validate_signature", return_value=True):
                            with patch("mcpgateway.services.tool_service.ResilientHttpClient") as mock_resilient_client:
                                # Mock the isolated HTTP client
                                mock_isolated_client = AsyncMock()
                                mock_response = MagicMock()
                                mock_response.status_code = 200
                                mock_response.json.return_value = {"result": "success"}
                                mock_isolated_client.request = AsyncMock(return_value=mock_response)
                                mock_isolated_client.get = AsyncMock(return_value=mock_response)
                                mock_isolated_client.aclose = AsyncMock()
                                mock_resilient_client.return_value = mock_isolated_client

                                # Invoke the tool
                                try:
                                    await tool_service.invoke_tool(
                                        db=mock_db,
                                        name="test-tool",
                                        arguments={"param": "value"},
                                        user_email="test@example.com",
                                        token_teams=[],
                                    )
                                except Exception:
                                    # We expect some errors due to incomplete mocking
                                    pass

                                # Verify that get_cached_ssl_context was called with the gateway's CA certificate
                                mock_get_ssl.assert_called_once_with(ca_cert, client_cert=client_cert, client_key=client_key)

                                # Verify that ResilientHttpClient was created with the custom SSL context
                                mock_resilient_client.assert_called_once()
                                client_args = mock_resilient_client.call_args[1]["client_args"]
                                assert client_args["verify"] == mock_ssl_context

    @pytest.mark.asyncio
    async def test_rest_tool_without_ca_cert_uses_shared_client(self):
        """Test that REST tools without gateway CA certificate use shared HTTP client."""
        tool_service = ToolService()

        # Mock the database and tool lookup
        mock_db = MagicMock()
        mock_tool = MagicMock()
        mock_tool.id = "test-tool-id"
        mock_tool.name = "test-tool"
        mock_tool.integration_type = "REST"
        mock_tool.enabled = True
        mock_tool.reachable = True
        mock_tool.visibility = "public"
        mock_tool.team_id = None
        mock_tool.owner_email = "test@example.com"

        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.ca_certificate = None  # No CA certificate
        mock_gateway.ca_certificate_sig = None

        mock_tool.gateway = mock_gateway

        # Mock the cache payload without gateway CA cert
        cache_payload = {
            "tool": {
                "id": "test-tool-id",
                "name": "test-tool-no-cert",
                "integration_type": "REST",
                "url": "https://api.example.com/endpoint",
                "request_type": "POST",
                "auth_type": "none",
                "headers": {},
                "gateway_id": "test-gateway-no-cert-id",
            },
            "gateway": {
                "id": "test-gateway-no-cert-id",
                "name": "test-gateway-no-cert",
                "url": "https://gateway.example.com",
                "auth_type": "none",
                "ca_certificate": None,
                "ca_certificate_sig": None,
                "client_cert": None,
                "client_key": None,
            }
        }

        with patch.object(tool_service, "_load_invocable_tools", return_value=[mock_tool]):
            with patch.object(tool_service, "_check_tool_access", return_value=True):
                with patch.object(tool_service, "_build_tool_cache_payload", return_value=cache_payload):
                    with patch("mcpgateway.utils.ssl_context_cache.get_cached_ssl_context") as mock_get_ssl:
                        with patch("mcpgateway.services.tool_service.ResilientHttpClient") as mock_resilient_client:
                            # Mock the shared HTTP client
                            tool_service._http_client = AsyncMock()
                            mock_response = MagicMock()
                            mock_response.status_code = 200
                            mock_response.json.return_value = {"result": "success"}
                            tool_service._http_client.request = AsyncMock(return_value=mock_response)

                            # Invoke the tool
                            try:
                                await tool_service.invoke_tool(
                                    db=mock_db,
                                    name="test-tool-no-cert",
                                    arguments={"param": "value"},
                                    user_email="test@example.com",
                                    token_teams=[],
                                )
                            except Exception:
                                # We expect some errors due to incomplete mocking
                                pass

                            # Verify that get_cached_ssl_context was NOT called
                            mock_get_ssl.assert_not_called()

                            # Verify that ResilientHttpClient was NOT created (no isolated client)
                            mock_resilient_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_rest_tool_with_invalid_ca_cert_signature_uses_shared_client(self):
        """Test that REST tools with invalid CA certificate signature fall back to shared client."""
        tool_service = ToolService()
        mock_ssl_context, ca_cert, ca_cert_sig, client_cert, client_key = self._make_ca_cert_mocks()

        # Mock the database and tool lookup
        mock_db = MagicMock()
        mock_tool = MagicMock()
        mock_tool.id = "test-tool-invalid-sig-id"
        mock_tool.name = "test-tool-invalid-sig"
        mock_tool.integration_type = "REST"
        mock_tool.enabled = True
        mock_tool.reachable = True
        mock_tool.visibility = "public"
        mock_tool.team_id = None
        mock_tool.owner_email = "test@example.com"

        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-invalid-sig-id"
        mock_gateway.name = "test-gateway-invalid-sig"
        mock_gateway.ca_certificate = ca_cert
        mock_gateway.ca_certificate_sig = "invalid_signature"  # Invalid signature
        mock_gateway.client_cert = client_cert
        mock_gateway.client_key = client_key

        mock_tool.gateway = mock_gateway

        # Mock the cache payload with gateway CA cert but invalid signature
        cache_payload = {
            "tool": {
                "id": "test-tool-invalid-sig-id",
                "name": "test-tool-invalid-sig",
                "integration_type": "REST",
                "url": "https://api.example.com/endpoint",
                "request_type": "POST",
                "auth_type": "none",
                "headers": {},
                "gateway_id": "test-gateway-invalid-sig-id",
            },
            "gateway": {
                "id": "test-gateway-invalid-sig-id",
                "name": "test-gateway-invalid-sig",
                "url": "https://gateway.example.com",
                "auth_type": "none",
                "ca_certificate": ca_cert,
                "ca_certificate_sig": "invalid_signature",
                "client_cert": client_cert,
                "client_key": client_key,
            }
        }

        # Mock settings to enable signature validation
        with patch("mcpgateway.services.tool_service.settings") as mock_settings:
            mock_settings.enable_ed25519_signing = True
            mock_settings.ed25519_public_key = "mock_public_key"

            with patch.object(tool_service, "_load_invocable_tools", return_value=[mock_tool]):
                with patch.object(tool_service, "_check_tool_access", return_value=True):
                    with patch.object(tool_service, "_build_tool_cache_payload", return_value=cache_payload):
                        with patch("mcpgateway.utils.ssl_context_cache.get_cached_ssl_context", return_value=mock_ssl_context) as mock_get_ssl:
                            with patch("mcpgateway.utils.validate_signature.validate_signature", return_value=False):  # Signature validation fails
                                with patch("mcpgateway.services.tool_service.ResilientHttpClient") as mock_resilient_client:
                                    # Mock the shared HTTP client
                                    tool_service._http_client = AsyncMock()
                                    mock_response = MagicMock()
                                    mock_response.status_code = 200
                                    mock_response.json.return_value = {"result": "success"}
                                    tool_service._http_client.request = AsyncMock(return_value=mock_response)

                                    # Invoke the tool
                                    try:
                                        await tool_service.invoke_tool(
                                            db=mock_db,
                                            name="test-tool-invalid-sig",
                                            arguments={"param": "value"},
                                            user_email="test@example.com",
                                            token_teams=[],
                                        )
                                    except Exception:
                                        # We expect some errors due to incomplete mocking
                                        pass

                                    # Verify that get_cached_ssl_context was NOT called (signature validation failed)
                                    mock_get_ssl.assert_not_called()

                                    # Verify that ResilientHttpClient was NOT created
                                    mock_resilient_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_rest_tool_with_ca_cert_signature_disabled_uses_custom_ssl(self):
        """Test that REST tools with CA cert use custom SSL when signature validation is disabled."""
        tool_service = ToolService()
        mock_ssl_context, ca_cert, ca_cert_sig, client_cert, client_key = self._make_ca_cert_mocks()

        # Mock the database and tool lookup
        mock_db = MagicMock()
        mock_tool = MagicMock()
        mock_tool.id = "test-tool-no-sig-id"
        mock_tool.name = "test-tool-no-sig"
        mock_tool.integration_type = "REST"
        mock_tool.enabled = True
        mock_tool.reachable = True
        mock_tool.visibility = "public"
        mock_tool.team_id = None
        mock_tool.owner_email = "test@example.com"

        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-no-sig-id"
        mock_gateway.name = "test-gateway-no-sig"
        mock_gateway.ca_certificate = ca_cert
        mock_gateway.ca_certificate_sig = None  # No signature
        mock_gateway.client_cert = client_cert
        mock_gateway.client_key = client_key

        mock_tool.gateway = mock_gateway

        # Mock the cache payload with gateway CA cert but no signature
        cache_payload = {
            "tool": {
                "id": "test-tool-no-sig-id",
                "name": "test-tool-no-sig",
                "integration_type": "REST",
                "url": "https://api.example.com/endpoint",
                "request_type": "POST",
                "auth_type": "none",
                "headers": {},
                "gateway_id": "test-gateway-no-sig-id",
            },
            "gateway": {
                "id": "test-gateway-no-sig-id",
                "name": "test-gateway-no-sig",
                "url": "https://gateway.example.com",
                "auth_type": "none",
                "ca_certificate": ca_cert,
                "ca_certificate_sig": None,
                "client_cert": client_cert,
                "client_key": client_key,
            }
        }

        # Mock settings to disable signature validation
        with patch("mcpgateway.services.tool_service.settings") as mock_settings:
            mock_settings.enable_ed25519_signing = False

            with patch.object(tool_service, "_load_invocable_tools", return_value=[mock_tool]):
                with patch.object(tool_service, "_check_tool_access", return_value=True):
                    with patch.object(tool_service, "_build_tool_cache_payload", return_value=cache_payload):
                        with patch("mcpgateway.utils.ssl_context_cache.get_cached_ssl_context", return_value=mock_ssl_context) as mock_get_ssl:
                            with patch("mcpgateway.services.tool_service.ResilientHttpClient") as mock_resilient_client:
                                # Mock the isolated HTTP client
                                mock_isolated_client = AsyncMock()
                                mock_response = MagicMock()
                                mock_response.status_code = 200
                                mock_response.json.return_value = {"result": "success"}
                                mock_isolated_client.request = AsyncMock(return_value=mock_response)
                                mock_isolated_client.get = AsyncMock(return_value=mock_response)
                                mock_isolated_client.aclose = AsyncMock()
                                mock_resilient_client.return_value = mock_isolated_client

                                # Invoke the tool
                                try:
                                    await tool_service.invoke_tool(
                                        db=mock_db,
                                        name="test-tool-no-sig",
                                        arguments={"param": "value"},
                                        user_email="test@example.com",
                                        token_teams=[],
                                    )
                                except Exception:
                                    # We expect some errors due to incomplete mocking
                                    pass

                                # Verify that get_cached_ssl_context was called (signature validation disabled)
                                mock_get_ssl.assert_called_once_with(ca_cert, client_cert=client_cert, client_key=client_key)

                                # Verify that ResilientHttpClient was created with the custom SSL context
                                mock_resilient_client.assert_called_once()
                                client_args = mock_resilient_client.call_args[1]["client_args"]
                                assert client_args["verify"] == mock_ssl_context
