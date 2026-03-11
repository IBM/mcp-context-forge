# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_openapi_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for OpenAPI service.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.services.openapi_service import (
    extract_all_schemas_from_openapi,
    extract_schemas_from_openapi,
    fetch_and_extract_all_schemas,
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
                        "requestBody": {
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/CalculateRequest"}}
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"$ref": "#/components/schemas/CalculateResponse"}}
                                }
                            }
                        },
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
                        "requestBody": {
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"name": {"type": "string"}}}}}
                        },
                        "responses": {
                            "201": {
                                "content": {
                                    "application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}
                                }
                            }
                        },
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
        spec = {
            "paths": {
                "/status": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"type": "object", "properties": {"status": {"type": "string"}}}}
                                }
                            }
                        }
                    }
                }
            }
        }

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
                        "requestBody": {
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}}
                        },
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
        spec = {
            "paths": {
                "/test": {
                    "post": {
                        "responses": {
                            "200": {
                                "content": {"application/json": {"schema": {"type": "object"}}}
                            }
                        }
                    }
                }
            }
        }

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
                        "requestBody": {
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/NonExistent"}}}
                        },
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


class TestFetchOpenAPISpec:
    """Tests for fetch_openapi_spec function."""

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """Test successful fetch of OpenAPI spec."""
        mock_spec = {"openapi": "3.0.0", "paths": {}}

        with patch("mcpgateway.services.openapi_service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_spec
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("mcpgateway.services.openapi_service.SecurityValidator.validate_url"):
                result = await fetch_openapi_spec("http://example.com/openapi.json")

            assert result == mock_spec
            mock_client.get.assert_called_once_with("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_fetch_with_ssrf_validation(self):
        """Test that SSRF validation is called when enabled."""
        mock_spec = {"openapi": "3.0.0"}

        with patch("mcpgateway.services.openapi_service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_spec
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("mcpgateway.services.openapi_service.SecurityValidator.validate_url") as mock_validate_url:
                await fetch_openapi_spec("http://example.com/openapi.json")

            mock_validate_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_url_validation_failure(self):
        """Test that URL validation errors are propagated."""
        with patch("mcpgateway.services.openapi_service.SecurityValidator.validate_url") as mock_validate:
            mock_validate.side_effect = ValueError("Invalid URL")

            with pytest.raises(ValueError, match="Invalid URL"):
                await fetch_openapi_spec("javascript:alert(1)")

    @pytest.mark.asyncio
    async def test_fetch_http_error(self):
        """Test handling of HTTP errors."""
        with patch("mcpgateway.services.openapi_service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=MagicMock()
            )
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("mcpgateway.services.openapi_service.SecurityValidator.validate_url"):
                with pytest.raises(httpx.HTTPStatusError):
                    await fetch_openapi_spec("http://example.com/openapi.json")

    @pytest.mark.asyncio
    async def test_fetch_timeout(self):
        """Test custom timeout is passed to client."""
        mock_spec = {"openapi": "3.0.0"}

        with patch("mcpgateway.services.openapi_service.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_spec
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with patch("mcpgateway.services.openapi_service.SecurityValidator.validate_url"):
                await fetch_openapi_spec("http://example.com/openapi.json", timeout=5.0)

            # Verify timeout was passed to AsyncClient
            mock_client_class.assert_called_once_with(timeout=5.0)


class TestFetchAndExtractSchemas:
    """Tests for fetch_and_extract_schemas function."""

    @pytest.mark.asyncio
    async def test_fetch_and_extract_success(self):
        """Test successful fetch and extraction."""
        mock_spec = {
            "paths": {
                "/calculate": {
                    "post": {
                        "requestBody": {
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"x": {"type": "number"}}}}}
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"type": "object", "properties": {"result": {"type": "number"}}}}
                                }
                            }
                        },
                    }
                }
            }
        }

        with patch("mcpgateway.services.openapi_service.fetch_openapi_spec") as mock_fetch:
            mock_fetch.return_value = mock_spec

            input_schema, output_schema, spec_url = await fetch_and_extract_schemas(
                base_url="http://localhost:8100", path="/calculate", method="POST"
            )

        assert input_schema is not None
        assert "x" in input_schema["properties"]
        assert output_schema is not None
        assert "result" in output_schema["properties"]
        assert spec_url == "http://localhost:8100/openapi.json"

    @pytest.mark.asyncio
    async def test_fetch_and_extract_with_custom_openapi_url(self):
        """Test using custom OpenAPI URL instead of base_url."""
        mock_spec = {
            "paths": {
                "/test": {
                    "get": {
                        "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}}
                    }
                }
            }
        }

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





class TestExtractAllSchemasFromOpenAPI:
    """Tests for extract_all_schemas_from_openapi function."""

    def test_extract_all_schemas_multiple_paths(self):
        """Test extraction of schemas from multiple paths and methods."""
        spec = {
            "paths": {
                "/calculate": {
                    "post": {
                        "requestBody": {
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CalcRequest"}}}
                        },
                        "responses": {
                            "200": {
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CalcResponse"}}}
                            }
                        },
                    }
                },
                "/status": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"type": "object", "properties": {"status": {"type": "string"}}}}
                                }
                            }
                        }
                    }
                },
                "/users": {
                    "post": {
                        "requestBody": {
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"name": {"type": "string"}}}}}
                        },
                        "responses": {"201": {"content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}}}}
                    },
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/User"}}}
                                }
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "CalcRequest": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}},
                    "CalcResponse": {"type": "object", "properties": {"sum": {"type": "number"}}},
                    "User": {"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}}
                }
            }
        }

        result = extract_all_schemas_from_openapi(spec)

        # Check /calculate POST
        assert "/calculate" in result
        assert "post" in result["/calculate"]
        assert result["/calculate"]["post"]["input_schema"]["properties"]["x"]["type"] == "number"
        assert result["/calculate"]["post"]["output_schema"]["properties"]["sum"]["type"] == "number"

        # Check /status GET
        assert "/status" in result
        assert "get" in result["/status"]
        assert result["/status"]["get"]["input_schema"] is None
        assert result["/status"]["get"]["output_schema"]["properties"]["status"]["type"] == "string"

        # Check /users POST
        assert "/users" in result
        assert "post" in result["/users"]
        assert result["/users"]["post"]["input_schema"]["properties"]["name"]["type"] == "string"
        assert result["/users"]["post"]["output_schema"]["properties"]["id"]["type"] == "string"

        # Check /users GET
        assert "get" in result["/users"]
        assert result["/users"]["get"]["input_schema"] is None
        assert result["/users"]["get"]["output_schema"]["type"] == "array"

    def test_extract_all_schemas_empty_spec(self):
        """Test extraction from empty spec."""
        spec = {"paths": {}}
        result = extract_all_schemas_from_openapi(spec)
        assert result == {}

    def test_extract_all_schemas_no_schemas(self):
        """Test extraction when paths have no schemas."""
        spec = {
            "paths": {
                "/health": {
                    "get": {
                        "responses": {"204": {"description": "No content"}}
                    }
                }
            }
        }
        result = extract_all_schemas_from_openapi(spec)
        # Should not include paths with no schemas
        assert result == {}

    def test_extract_all_schemas_mixed_inline_and_refs(self):
        """Test extraction with mix of inline schemas and $refs."""
        spec = {
            "paths": {
                "/mixed": {
                    "post": {
                        "requestBody": {
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"inline": {"type": "string"}}}}}
                        },
                        "responses": {
                            "200": {
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Response"}}}
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "Response": {"type": "object", "properties": {"result": {"type": "boolean"}}}
                }
            }
        }

        result = extract_all_schemas_from_openapi(spec)

        assert "/mixed" in result
        assert "post" in result["/mixed"]
        assert result["/mixed"]["post"]["input_schema"]["properties"]["inline"]["type"] == "string"
        assert result["/mixed"]["post"]["output_schema"]["properties"]["result"]["type"] == "boolean"

    def test_extract_all_schemas_all_http_methods(self):
        """Test extraction for all HTTP methods."""
        spec = {
            "paths": {
                "/resource": {
                    "get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}}},
                    "post": {"requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}}, "responses": {"201": {}}},
                    "put": {"requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}}, "responses": {"200": {}}},
                    "patch": {"requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}}, "responses": {"200": {}}},
                    "delete": {"responses": {"204": {}}},
                }
            }
        }

        result = extract_all_schemas_from_openapi(spec)

        assert "/resource" in result
        assert "get" in result["/resource"]
        assert "post" in result["/resource"]
        assert "put" in result["/resource"]
        assert "patch" in result["/resource"]
        # delete should not be included as it has no schemas
        assert "delete" not in result["/resource"]


class TestFetchAndExtractAllSchemas:
    """Tests for fetch_and_extract_all_schemas function."""

    @pytest.mark.asyncio
    async def test_fetch_and_extract_all_success(self):
        """Test successful fetch and extraction of all schemas."""
        mock_spec = {
            "paths": {
                "/calculate": {
                    "post": {
                        "requestBody": {
                            "content": {"application/json": {"schema": {"type": "object", "properties": {"x": {"type": "number"}}}}}
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"type": "object", "properties": {"result": {"type": "number"}}}}
                                }
                            }
                        },
                    }
                },
                "/status": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {"application/json": {"schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}}
                            }
                        }
                    }
                }
            }
        }

        with patch("mcpgateway.services.openapi_service.fetch_openapi_spec") as mock_fetch:
            mock_fetch.return_value = mock_spec

            all_schemas, spec_url = await fetch_and_extract_all_schemas(base_url="http://localhost:8100")

        assert "/calculate" in all_schemas
        assert "post" in all_schemas["/calculate"]
        assert "x" in all_schemas["/calculate"]["post"]["input_schema"]["properties"]
        assert "result" in all_schemas["/calculate"]["post"]["output_schema"]["properties"]

        assert "/status" in all_schemas
        assert "get" in all_schemas["/status"]
        assert all_schemas["/status"]["get"]["input_schema"] is None
        assert "ok" in all_schemas["/status"]["get"]["output_schema"]["properties"]

        assert spec_url == "http://localhost:8100/openapi.json"

    @pytest.mark.asyncio
    async def test_fetch_and_extract_all_with_custom_url(self):
        """Test using custom OpenAPI URL."""
        mock_spec = {
            "paths": {
                "/test": {
                    "get": {
                        "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}}
                    }
                }
            }
        }

        with patch("mcpgateway.services.openapi_service.fetch_openapi_spec") as mock_fetch:
            mock_fetch.return_value = mock_spec

            all_schemas, spec_url = await fetch_and_extract_all_schemas(
                base_url="http://localhost:8100",
                openapi_url="http://custom.com/spec.json"
            )

        assert spec_url == "http://custom.com/spec.json"
        mock_fetch.assert_called_once_with("http://custom.com/spec.json", timeout=10.0)

    @pytest.mark.asyncio
    async def test_fetch_and_extract_all_custom_timeout(self):
        """Test custom timeout is passed through."""
        mock_spec = {"paths": {"/test": {"get": {"responses": {"200": {}}}}}}

        with patch("mcpgateway.services.openapi_service.fetch_openapi_spec") as mock_fetch:
            mock_fetch.return_value = mock_spec

            await fetch_and_extract_all_schemas(
                base_url="http://localhost:8100",
                timeout=5.0
            )

        mock_fetch.assert_called_once_with("http://localhost:8100/openapi.json", timeout=5.0)
