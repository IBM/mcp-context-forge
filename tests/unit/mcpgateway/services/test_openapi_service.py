# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_openapi_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for OpenAPI service.
"""

# Standard
from contextlib import asynccontextmanager
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import orjson
import pytest

# First-Party
from mcpgateway.services.openapi_service import (
    _MAX_SPEC_BYTES,
    extract_schemas_from_openapi,
    fetch_and_extract_schemas,
    fetch_openapi_spec,
)


class TestExtractSchemasFromOpenAPI:
    """Tests for extract_schemas_from_openapi function."""

    def test_extract_inline_schemas(self):
        """Test extraction of inline schemas (no $ref)."""
        spec = {
            "paths": {
                "/calculate": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "a": {"type": "number"},
                                            "b": {"type": "number"},
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"result": {"type": "number"}},
                                        }
                                    }
                                }
                            }
                        },
                    }
                }
            }
        }

        input_schema, output_schema = extract_schemas_from_openapi(spec, "/calculate", "post")

        assert input_schema is not None
        assert input_schema["type"] == "object"
        assert "a" in input_schema["properties"]
        assert "b" in input_schema["properties"]

        assert output_schema is not None
        assert output_schema["type"] == "object"
        assert "result" in output_schema["properties"]

    def test_extract_ref_schemas(self):
        """Test extraction of schemas with $ref references."""
        spec = {
            "paths": {
                "/calculate": {
                    "post": {
                        "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/CalculateRequest"}}}},
                        "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/CalculateResponse"}}}}},
                    }
                }
            },
            "components": {
                "schemas": {
                    "CalculateRequest": {
                        "type": "object",
                        "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                    },
                    "CalculateResponse": {"type": "object", "properties": {"sum": {"type": "number"}}},
                }
            },
        }

        input_schema, output_schema = extract_schemas_from_openapi(spec, "/calculate", "post")

        assert input_schema is not None
        assert input_schema["type"] == "object"
        assert "x" in input_schema["properties"]
        assert "y" in input_schema["properties"]

        assert output_schema is not None
        assert output_schema["type"] == "object"
        assert "sum" in output_schema["properties"]

    def test_extract_with_201_response(self):
        """Test extraction when response is 201 instead of 200."""
        spec = {
            "paths": {
                "/create": {
                    "post": {
                        "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"name": {"type": "string"}}}}}},
                        "responses": {"201": {"content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}}}},
                    }
                }
            }
        }

        input_schema, output_schema = extract_schemas_from_openapi(spec, "/create", "post")

        assert input_schema is not None
        assert output_schema is not None
        assert "id" in output_schema["properties"]

    def test_extract_no_request_body(self):
        """Test extraction when there's no request body (GET request)."""
        spec = {"paths": {"/status": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {"status": {"type": "string"}}}}}}}}}}}

        input_schema, output_schema = extract_schemas_from_openapi(spec, "/status", "get")

        assert input_schema is None
        assert output_schema is not None
        assert "status" in output_schema["properties"]

    def test_extract_no_response_schema(self):
        """Test extraction when there's no response schema."""
        spec = {
            "paths": {
                "/delete": {
                    "delete": {
                        "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}}},
                        "responses": {"204": {"description": "No content"}},
                    }
                }
            }
        }

        input_schema, output_schema = extract_schemas_from_openapi(spec, "/delete", "delete")

        assert input_schema is not None
        assert output_schema is None

    def test_path_not_found(self):
        """Test error when path doesn't exist in spec."""
        spec = {"paths": {"/calculate": {"post": {}}}}

        with pytest.raises(KeyError, match="Path '/nonexistent' not found"):
            extract_schemas_from_openapi(spec, "/nonexistent", "post")

    def test_method_not_found(self):
        """Test error when method doesn't exist for path."""
        spec = {"paths": {"/calculate": {"post": {}}}}

        with pytest.raises(KeyError, match="Method 'get' not found"):
            extract_schemas_from_openapi(spec, "/calculate", "get")

    def test_method_case_insensitive(self):
        """Test that method matching is case-insensitive."""
        spec = {"paths": {"/test": {"post": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}}}}}}

        # Should work with uppercase
        input_schema, output_schema = extract_schemas_from_openapi(spec, "/test", "POST")
        assert output_schema is not None

        # Should work with mixed case
        input_schema, output_schema = extract_schemas_from_openapi(spec, "/test", "Post")
        assert output_schema is not None

    def test_missing_ref_returns_none(self):
        """Test that missing $ref returns None instead of raising error."""
        spec = {
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/NonExistent"}}}},
                        "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                    }
                }
            },
            "components": {"schemas": {}},
        }

        input_schema, output_schema = extract_schemas_from_openapi(spec, "/test", "post")

        # Missing ref should return None
        assert input_schema is None
        assert output_schema is not None

    def test_missing_ref_logs_warning(self, caplog):
        """Unresolved $ref logs a warning with the ref path and schema name."""
        spec = {
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Missing"}}}},
                        "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                    }
                }
            },
            "components": {"schemas": {}},
        }

        with caplog.at_level("WARNING", logger="mcpgateway.services.openapi_service"):
            extract_schemas_from_openapi(spec, "/test", "post")

        assert any("Unresolved $ref" in msg and "Missing" in msg for msg in caplog.messages)

    def test_unsupported_ref_format_returns_none_and_logs(self, caplog):
        """External or malformed $ref returns None and logs a warning."""
        spec = {
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {"content": {"application/json": {"schema": {"$ref": "https://external.com/schemas/Foo"}}}},
                        "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "SomeGarbage"}}}}},
                    }
                }
            },
            "components": {"schemas": {"Foo": {"type": "object"}}},
        }

        with caplog.at_level("WARNING", logger="mcpgateway.services.openapi_service"):
            input_schema, output_schema = extract_schemas_from_openapi(spec, "/test", "post")

        assert input_schema is None
        assert output_schema is None
        assert any("Unsupported $ref format" in msg for msg in caplog.messages)


@asynccontextmanager
async def _mock_isolated_client(body: bytes, headers: Optional[dict] = None, raise_for_status: Optional[Exception] = None):
    """Async context manager mimicking ``get_isolated_http_client`` with canned responses."""

    async def _aiter_bytes(chunk_size=8192):
        for i in range(0, len(body), chunk_size):
            yield body[i : i + chunk_size]

    mock_response = MagicMock()
    mock_response.headers = headers or {}
    if raise_for_status:
        mock_response.raise_for_status.side_effect = raise_for_status
    else:
        mock_response.raise_for_status = MagicMock()
    mock_response.aiter_bytes = _aiter_bytes
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_response)
    yield mock_client


_PATCH_CLIENT = "mcpgateway.services.openapi_service.get_isolated_http_client"
_PATCH_VALIDATE = "mcpgateway.services.openapi_service.SecurityValidator.validate_url"


class TestFetchOpenAPISpec:
    """Tests for fetch_openapi_spec function."""

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """Test successful fetch of OpenAPI spec."""
        mock_spec = {"openapi": "3.0.0", "paths": {}}

        with patch(_PATCH_CLIENT, return_value=_mock_isolated_client(orjson.dumps(mock_spec))):
            with patch(_PATCH_VALIDATE):
                result = await fetch_openapi_spec("http://example.com/openapi.json")

        assert result == mock_spec

    @pytest.mark.asyncio
    async def test_fetch_with_ssrf_validation(self):
        """Test that SSRF validation is called when enabled."""
        with patch(_PATCH_CLIENT, return_value=_mock_isolated_client(orjson.dumps({"openapi": "3.0.0"}))):
            with patch(_PATCH_VALIDATE) as mock_validate_url:
                await fetch_openapi_spec("http://example.com/openapi.json")

        mock_validate_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_url_validation_failure(self):
        """Test that URL validation errors are propagated."""
        with patch(_PATCH_VALIDATE) as mock_validate:
            mock_validate.side_effect = ValueError("Invalid URL")

            with pytest.raises(ValueError, match="Invalid URL"):
                await fetch_openapi_spec("javascript:alert(1)")

    @pytest.mark.asyncio
    async def test_fetch_http_error(self):
        """Test handling of HTTP errors."""
        error = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=MagicMock())

        with patch(_PATCH_CLIENT, return_value=_mock_isolated_client(b"", raise_for_status=error)):
            with patch(_PATCH_VALIDATE):
                with pytest.raises(httpx.HTTPStatusError):
                    await fetch_openapi_spec("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_fetch_timeout(self):
        """Test custom timeout is passed to get_isolated_http_client."""
        with patch(_PATCH_CLIENT, return_value=_mock_isolated_client(orjson.dumps({"openapi": "3.0.0"}))) as mock_get_client:
            with patch(_PATCH_VALIDATE):
                await fetch_openapi_spec("http://example.com/openapi.json", timeout=5.0)

        mock_get_client.assert_called_once_with(timeout=5.0, follow_redirects=False)

    @pytest.mark.asyncio
    async def test_rejects_response_with_content_length_exceeding_limit(self):
        """Content-Length header exceeding _MAX_SPEC_BYTES raises ValueError."""
        with patch(_PATCH_CLIENT, return_value=_mock_isolated_client(b"", headers={"content-length": str(_MAX_SPEC_BYTES + 1)})):
            with patch(_PATCH_VALIDATE):
                with pytest.raises(ValueError, match="too large"):
                    await fetch_openapi_spec("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_rejects_response_body_exceeding_limit(self):
        """Response body exceeding _MAX_SPEC_BYTES raises ValueError during streaming."""
        with patch(_PATCH_CLIENT, return_value=_mock_isolated_client(b"x" * (_MAX_SPEC_BYTES + 1))):
            with patch(_PATCH_VALIDATE):
                with pytest.raises(ValueError, match="too large"):
                    await fetch_openapi_spec("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_malformed_content_length_falls_through_to_body_check(self):
        """Malformed Content-Length header doesn't crash — falls through to streamed check."""
        mock_spec = {"openapi": "3.0.0"}

        with patch(_PATCH_CLIENT, return_value=_mock_isolated_client(orjson.dumps(mock_spec), headers={"content-length": "not-a-number"})):
            with patch(_PATCH_VALIDATE):
                result = await fetch_openapi_spec("http://example.com/openapi.json")

        assert result == mock_spec

    @pytest.mark.asyncio
    async def test_invalid_json_response_raises_valueerror(self):
        """Non-JSON response body (e.g. HTML) raises ValueError with clear message."""
        with patch(_PATCH_CLIENT, return_value=_mock_isolated_client(b"<html>Not Found</html>")):
            with patch(_PATCH_VALIDATE):
                with pytest.raises(ValueError, match="not valid JSON"):
                    await fetch_openapi_spec("http://example.com/openapi.json")


class TestFetchAndExtractSchemas:
    """Tests for fetch_and_extract_schemas function."""

    @pytest.mark.asyncio
    async def test_fetch_and_extract_success(self):
        """Test successful fetch and extraction."""
        mock_spec = {
            "paths": {
                "/calculate": {
                    "post": {
                        "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"x": {"type": "number"}}}}}},
                        "responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {"result": {"type": "number"}}}}}}},
                    }
                }
            }
        }

        with patch("mcpgateway.services.openapi_service.fetch_openapi_spec") as mock_fetch:
            mock_fetch.return_value = mock_spec

            input_schema, output_schema, spec_url = await fetch_and_extract_schemas(base_url="http://localhost:8100", path="/calculate", method="POST")

        assert input_schema is not None
        assert "x" in input_schema["properties"]
        assert output_schema is not None
        assert "result" in output_schema["properties"]
        assert spec_url == "http://localhost:8100/openapi.json"

    @pytest.mark.asyncio
    async def test_fetch_and_extract_with_custom_openapi_url(self):
        """Test using custom OpenAPI URL instead of base_url."""
        mock_spec = {"paths": {"/test": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}}}}}}

        with patch("mcpgateway.services.openapi_service.fetch_openapi_spec") as mock_fetch:
            mock_fetch.return_value = mock_spec

            input_schema, output_schema, spec_url = await fetch_and_extract_schemas(
                base_url="http://localhost:8100",
                path="/test",
                method="GET",
                openapi_url="http://custom.com/spec.json",
            )

        # Should use custom URL
        assert spec_url == "http://custom.com/spec.json"
        mock_fetch.assert_called_once_with("http://custom.com/spec.json", timeout=10.0)

    @pytest.mark.asyncio
    async def test_fetch_and_extract_path_not_found(self):
        """Test error propagation when path not found."""
        mock_spec = {"paths": {"/other": {"get": {}}}}

        with patch("mcpgateway.services.openapi_service.fetch_openapi_spec") as mock_fetch:
            mock_fetch.return_value = mock_spec

            with pytest.raises(KeyError, match="Path '/calculate' not found"):
                await fetch_and_extract_schemas(base_url="http://localhost:8100", path="/calculate", method="POST")

    @pytest.mark.asyncio
    async def test_fetch_and_extract_custom_timeout(self):
        """Test custom timeout is passed through."""
        mock_spec = {"paths": {"/test": {"get": {"responses": {"200": {}}}}}}

        with patch("mcpgateway.services.openapi_service.fetch_openapi_spec") as mock_fetch:
            mock_fetch.return_value = mock_spec

            await fetch_and_extract_schemas(
                base_url="http://localhost:8100",
                path="/test",
                method="GET",
                timeout=5.0,
            )

        # Verify timeout was passed
        mock_fetch.assert_called_once_with("http://localhost:8100/openapi.json", timeout=5.0)
