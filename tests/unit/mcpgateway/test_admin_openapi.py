# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_openapi.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for admin OpenAPI endpoints to improve coverage.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import orjson
import pytest
from fastapi import Request
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.admin import generate_schemas_from_openapi


class TestGenerateSchemasFromOpenAPI:
    """Tests for generate_schemas_from_openapi endpoint."""

    @pytest.mark.asyncio
    async def test_generate_schemas_success(self):
        """Test successful schema generation."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "http://example.com/calculate",
            "request_type": "POST"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        input_schema = {"type": "object", "properties": {"x": {"type": "number"}}}
        output_schema = {"type": "object", "properties": {"result": {"type": "number"}}}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.return_value = (input_schema, output_schema, "http://example.com/openapi.json")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 200
            content = orjson.loads(response.body)
            assert content["success"] is True
            assert content["input_schema"] == input_schema
            assert content["output_schema"] == output_schema
            assert content["spec_url"] == "http://example.com/openapi.json"
            assert "Schemas generated successfully" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_with_openapi_url(self):
        """Test schema generation with custom openapi_url."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "openapi_url": "http://example.com/custom-spec.json",
            "request_type": "GET"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        input_schema = None
        output_schema = {"type": "object"}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.return_value = (input_schema, output_schema, "http://example.com/custom-spec.json")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 200
            content = orjson.loads(response.body)
            assert content["success"] is True

    @pytest.mark.asyncio
    async def test_generate_schemas_missing_url_and_openapi_url(self):
        """Test error when both url and openapi_url are missing."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "request_type": "POST"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        response = await generate_schemas_from_openapi(
            request=mock_request,
            _db=mock_db,
            _user=mock_user
        )

        assert response.status_code == 400
        content = orjson.loads(response.body)
        assert content["success"] is False
        assert "Either 'url' or 'openapi_url' is required" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_empty_url_and_openapi_url(self):
        """Test error when both url and openapi_url are empty strings."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "",
            "openapi_url": "",
            "request_type": "POST"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        response = await generate_schemas_from_openapi(
            request=mock_request,
            _db=mock_db,
            _user=mock_user
        )

        assert response.status_code == 400
        content = orjson.loads(response.body)
        assert content["success"] is False
        assert "Either 'url' or 'openapi_url' is required" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_security_validation_failed(self):
        """Test security validation failure."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "http://192.168.1.1/api",
            "request_type": "POST"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.side_effect = ValueError("SSRF protection: private IP detected")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 400
            content = orjson.loads(response.body)
            assert content["success"] is False
            assert "Security validation failed" in content["message"]
            assert "SSRF protection" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_path_not_found(self):
        """Test error when path not found in spec."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "http://example.com/nonexistent",
            "request_type": "POST"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.side_effect = KeyError("Path '/nonexistent' not found in OpenAPI spec")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 404
            content = orjson.loads(response.body)
            assert content["success"] is False
            assert "Path '/nonexistent' not found" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_method_not_found(self):
        """Test error when method not found for path."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "http://example.com/api",
            "request_type": "DELETE"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.side_effect = KeyError("Method 'delete' not found for path '/api'")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 404
            content = orjson.loads(response.body)
            assert content["success"] is False

    @pytest.mark.asyncio
    async def test_generate_schemas_http_error(self):
        """Test HTTP error handling."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "http://example.com/api",
            "request_type": "POST"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.side_effect = httpx.ConnectError("Connection refused")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 404
            content = orjson.loads(response.body)
            assert content["success"] is False
            assert "Failed to fetch OpenAPI spec" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_http_timeout(self):
        """Test HTTP timeout error."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "http://slow-server.com/api",
            "request_type": "POST"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.side_effect = httpx.TimeoutException("Request timeout")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 404
            content = orjson.loads(response.body)
            assert content["success"] is False
            assert "Failed to fetch OpenAPI spec" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_generic_exception_in_fetch(self):
        """Test generic exception handling during fetch."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "http://example.com/api",
            "request_type": "POST"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.side_effect = Exception("Unexpected error during fetch")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 500
            content = orjson.loads(response.body)
            assert content["success"] is False
            assert "Error:" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_invalid_json(self):
        """Test invalid JSON in request body."""
        mock_request = MagicMock(spec=Request)
        # Create a proper orjson.JSONDecodeError by catching one
        try:
            orjson.loads(b"invalid json {")
        except orjson.JSONDecodeError as e:
            json_error = e
        
        mock_request.json = AsyncMock(side_effect=json_error)
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        response = await generate_schemas_from_openapi(
            request=mock_request,
            _db=mock_db,
            _user=mock_user
        )

        assert response.status_code == 400
        content = orjson.loads(response.body)
        assert content["success"] is False
        assert "Invalid JSON in request body" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_outer_exception(self):
        """Test outer exception handling."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(side_effect=Exception("Request processing error"))
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        response = await generate_schemas_from_openapi(
            request=mock_request,
            _db=mock_db,
            _user=mock_user
        )

        assert response.status_code == 500
        content = orjson.loads(response.body)
        assert content["success"] is False
        assert "Error:" in content["message"]

    @pytest.mark.asyncio
    async def test_generate_schemas_default_request_type(self):
        """Test default request_type is GET when not provided."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "http://example.com/status"
            # request_type not provided
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        input_schema = None
        output_schema = {"type": "object"}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.return_value = (input_schema, output_schema, "http://example.com/openapi.json")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 200
            # Verify GET was used as default
            call_args = mock_fetch.call_args
            assert call_args[1]["method"] == "GET"

    @pytest.mark.asyncio
    async def test_generate_schemas_url_parsing(self):
        """Test URL parsing extracts base_url and path correctly."""
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={
            "url": "https://api.example.com:8443/v1/calculate",
            "request_type": "POST"
        })
        mock_db = MagicMock(spec=Session)
        mock_user = {"email": "test@example.com"}

        input_schema = {"type": "object"}
        output_schema = {"type": "object"}

        with patch("mcpgateway.admin.fetch_and_extract_schemas") as mock_fetch:
            mock_fetch.return_value = (input_schema, output_schema, "https://api.example.com:8443/openapi.json")

            response = await generate_schemas_from_openapi(
                request=mock_request,
                _db=mock_db,
                _user=mock_user
            )

            assert response.status_code == 200
            # Verify correct base_url and path were extracted
            call_args = mock_fetch.call_args
            assert call_args[1]["base_url"] == "https://api.example.com:8443"
            assert call_args[1]["path"] == "/v1/calculate"
            assert call_args[1]["method"] == "POST"

