# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_openapi_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for OpenAPI service.
"""

# Standard
import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import orjson
import pytest

# First-Party
from mcpgateway.services.openapi_service import (
    _MAX_SPEC_BYTES,
    _SPEC_CACHE_MAX,
    _SPEC_CACHE_TTL,
    _SPEC_ERROR_TTL,
    _spec_cache,
    _spec_locks,
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


_VALID_PIN = {
    "validated_url": "http://example.com/openapi.json",
    "hostname": "example.com",
    "original_authority": "example.com",
    "resolved_ip": "93.184.216.34",
}

_PATCH_VALIDATE = "mcpgateway.services.openapi_service.SecurityValidator.validate_url_for_connection_pinning"
_PATCH_SETTINGS = "mcpgateway.services.openapi_service.settings"


def _mock_httpx_client(body: bytes, headers: Optional[dict] = None, raise_for_status: Optional[Exception] = None):
    """Return a mock ``httpx.AsyncClient`` usable as an async context manager."""

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
    mock_response.aclose = AsyncMock()

    mock_client = MagicMock()
    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


class TestFetchOpenAPISpec:
    """Tests for fetch_openapi_spec function."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear the spec cache and locks before and after each test."""
        _spec_cache.clear()
        _spec_locks.clear()
        yield
        _spec_cache.clear()
        _spec_locks.clear()

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """Successful fetch returns parsed JSON spec."""
        mock_spec = {"openapi": "3.0.0", "paths": {}}
        client = _mock_httpx_client(orjson.dumps(mock_spec))

        with patch("httpx.AsyncClient", return_value=client):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN):
                result = await fetch_openapi_spec("http://example.com/openapi.json")

        assert result == mock_spec

    @pytest.mark.asyncio
    async def test_fetch_with_ssrf_validation(self):
        """Connection-pinning validation is called for every cache miss."""
        client = _mock_httpx_client(orjson.dumps({"openapi": "3.0.0"}))

        with patch("httpx.AsyncClient", return_value=client):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN) as mock_validate:
                await fetch_openapi_spec("http://example.com/openapi.json")

        mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_url_validation_failure(self):
        """URL validation errors propagate to the caller."""
        with patch(_PATCH_VALIDATE, new_callable=AsyncMock, side_effect=ValueError("Invalid URL")):
            with pytest.raises(ValueError, match="Invalid URL"):
                await fetch_openapi_spec("javascript:alert(1)")

    @pytest.mark.asyncio
    async def test_fetch_http_error(self):
        """HTTP errors propagate to the caller."""
        error = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=MagicMock())
        client = _mock_httpx_client(b"", raise_for_status=error)

        with patch("httpx.AsyncClient", return_value=client):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN):
                with pytest.raises(httpx.HTTPStatusError):
                    await fetch_openapi_spec("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_fetch_timeout_passed_to_build_request(self):
        """Custom timeout is forwarded to ``build_request``."""
        client = _mock_httpx_client(orjson.dumps({"openapi": "3.0.0"}))

        with patch("httpx.AsyncClient", return_value=client):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN):
                await fetch_openapi_spec("http://example.com/openapi.json", timeout=5.0)

        _, kwargs = client.build_request.call_args
        assert kwargs["timeout"] == 5.0

    @pytest.mark.asyncio
    async def test_rejects_response_with_content_length_exceeding_limit(self):
        """Content-Length header exceeding _MAX_SPEC_BYTES raises ValueError."""
        client = _mock_httpx_client(b"", headers={"content-length": str(_MAX_SPEC_BYTES + 1)})

        with patch("httpx.AsyncClient", return_value=client):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN):
                with pytest.raises(ValueError, match="too large"):
                    await fetch_openapi_spec("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_rejects_response_body_exceeding_limit(self):
        """Response body exceeding _MAX_SPEC_BYTES raises ValueError during streaming."""
        client = _mock_httpx_client(b"x" * (_MAX_SPEC_BYTES + 1))

        with patch("httpx.AsyncClient", return_value=client):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN):
                with pytest.raises(ValueError, match="too large"):
                    await fetch_openapi_spec("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_malformed_content_length_falls_through_to_body_check(self):
        """Malformed Content-Length header falls through to the streamed body check."""
        mock_spec = {"openapi": "3.0.0"}
        client = _mock_httpx_client(orjson.dumps(mock_spec), headers={"content-length": "not-a-number"})

        with patch("httpx.AsyncClient", return_value=client):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN):
                result = await fetch_openapi_spec("http://example.com/openapi.json")

        assert result == mock_spec

    @pytest.mark.asyncio
    async def test_invalid_json_response_raises_valueerror(self):
        """Non-JSON response body raises ValueError with a clear message."""
        client = _mock_httpx_client(b"<html>Not Found</html>")

        with patch("httpx.AsyncClient", return_value=client):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN):
                with pytest.raises(ValueError, match="not valid JSON"):
                    await fetch_openapi_spec("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_cache_hit_skips_fetch(self):
        """Cached spec is returned without a second HTTP call."""
        mock_spec = {"openapi": "3.0.0", "paths": {}}
        client = _mock_httpx_client(orjson.dumps(mock_spec))

        with patch("httpx.AsyncClient", return_value=client):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN) as mock_val:
                first = await fetch_openapi_spec("http://example.com/openapi.json")
                second = await fetch_openapi_spec("http://example.com/openapi.json")

        assert first == second == mock_spec
        # Validation (and therefore fetch) called only once; second call from cache.
        assert mock_val.await_count == 1

    @pytest.mark.asyncio
    async def test_ssrf_blocked_when_pinning_returns_no_ip(self):
        """Missing resolved_ip with SSRF protection enabled raises ValueError."""
        no_ip_pin = {**_VALID_PIN, "resolved_ip": None}
        mock_settings = MagicMock()
        mock_settings.ssrf_protection_enabled = True
        mock_settings.skip_ssl_verify = False

        with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=no_ip_pin):
            with patch(_PATCH_SETTINGS, mock_settings):
                with pytest.raises(ValueError, match="blocked by URL policy"):
                    await fetch_openapi_spec("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_cache_ttl_expiry_triggers_refetch(self):
        """Expired cache entry triggers a fresh upstream fetch."""
        mock_spec_v1 = {"openapi": "3.0.0", "info": {"version": "1"}}
        mock_spec_v2 = {"openapi": "3.0.0", "info": {"version": "2"}}
        url = "http://example.com/openapi.json"

        client_v1 = _mock_httpx_client(orjson.dumps(mock_spec_v1))
        with patch("httpx.AsyncClient", return_value=client_v1):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN):
                first = await fetch_openapi_spec(url)
        assert first == mock_spec_v1

        # Expire the cache entry by backdating its expiry.
        expires_at, spec = _spec_cache[url]
        _spec_cache[url] = (expires_at - _SPEC_CACHE_TTL - 1, spec)

        client_v2 = _mock_httpx_client(orjson.dumps(mock_spec_v2))
        with patch("httpx.AsyncClient", return_value=client_v2):
            with patch(_PATCH_VALIDATE, new_callable=AsyncMock, return_value=_VALID_PIN) as mock_val:
                second = await fetch_openapi_spec(url)

        assert second == mock_spec_v2
        mock_val.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_concurrent_fetches_coalesce_to_single_request(self):
        """Multiple concurrent callers for the same URL produce exactly one upstream fetch."""
        mock_spec = {"openapi": "3.0.0", "paths": {}}
        fetch_count = 0

        async def _counting_fetch(spec_url, timeout):
            nonlocal fetch_count
            fetch_count += 1
            await asyncio.sleep(0.05)  # Simulate network latency.
            return mock_spec

        with patch("mcpgateway.services.openapi_service._do_fetch", side_effect=_counting_fetch):
            results = await asyncio.gather(
                fetch_openapi_spec("http://example.com/openapi.json"),
                fetch_openapi_spec("http://example.com/openapi.json"),
                fetch_openapi_spec("http://example.com/openapi.json"),
            )

        assert fetch_count == 1, f"Expected 1 upstream fetch, got {fetch_count}"
        for r in results:
            assert r == mock_spec

    @pytest.mark.asyncio
    async def test_failed_fetch_is_cached_for_error_ttl(self):
        """Callers arriving after a failure re-raise it without a second upstream fetch."""
        url = "http://example.com/openapi.json"
        fetch_count = 0

        async def _failing_fetch(spec_url, timeout):
            nonlocal fetch_count
            fetch_count += 1
            await asyncio.sleep(0.05)  # Simulate network latency.
            raise ValueError("boom")

        with patch("mcpgateway.services.openapi_service._do_fetch", side_effect=_failing_fetch):
            waiters = await asyncio.gather(*(fetch_openapi_spec(url) for _ in range(3)), return_exceptions=True)
            with pytest.raises(ValueError, match="boom"):
                await fetch_openapi_spec(url)

        assert fetch_count == 1, f"Expected 1 upstream fetch, got {fetch_count}"
        assert all(isinstance(r, ValueError) for r in waiters)

        # The negative entry expires: backdate it and the next caller refetches.
        expires_at, err = _spec_cache[url]
        _spec_cache[url] = (expires_at - _SPEC_ERROR_TTL - 1, err)
        with patch("mcpgateway.services.openapi_service._do_fetch", new_callable=AsyncMock, return_value={"openapi": "3.0.0"}):
            assert await fetch_openapi_spec(url) == {"openapi": "3.0.0"}

    @pytest.mark.asyncio
    async def test_failed_fetches_stay_bounded(self):
        """Distinct failing URLs never grow the cache or lock maps past ``_SPEC_CACHE_MAX``."""
        with patch("mcpgateway.services.openapi_service._do_fetch", side_effect=ValueError("boom")):
            for i in range(_SPEC_CACHE_MAX + 10):
                with pytest.raises(ValueError, match="boom"):
                    await fetch_openapi_spec(f"http://example.com/{i}/openapi.json")

        assert len(_spec_cache) == _SPEC_CACHE_MAX
        assert len(_spec_locks) == _SPEC_CACHE_MAX

    @pytest.mark.asyncio
    async def test_cache_returns_independent_copy(self):
        """Mutating a returned spec never corrupts the cached copy."""
        url = "http://example.com/openapi.json"
        mock_spec = {"openapi": "3.0.0", "paths": {"/a": {"get": {}}}}

        with patch("mcpgateway.services.openapi_service._do_fetch", new_callable=AsyncMock, return_value=mock_spec):
            miss = await fetch_openapi_spec(url)
            miss["paths"]["/a"]["get"]["polluted"] = True
            hit = await fetch_openapi_spec(url)
            hit["paths"].clear()
            again = await fetch_openapi_spec(url)

        assert again == {"openapi": "3.0.0", "paths": {"/a": {"get": {}}}}

    @pytest.mark.asyncio
    async def test_cache_bounded_eviction(self):
        """Cache never grows past ``_SPEC_CACHE_MAX``; oldest URLs are evicted first."""
        with patch("mcpgateway.services.openapi_service._do_fetch", new_callable=AsyncMock, return_value={"openapi": "3.0.0"}):
            for i in range(_SPEC_CACHE_MAX + 10):
                await fetch_openapi_spec(f"http://example.com/{i}/openapi.json")

        assert len(_spec_cache) == _SPEC_CACHE_MAX
        assert len(_spec_locks) == _SPEC_CACHE_MAX
        assert "http://example.com/0/openapi.json" not in _spec_cache
        assert f"http://example.com/{_SPEC_CACHE_MAX + 9}/openapi.json" in _spec_cache


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
