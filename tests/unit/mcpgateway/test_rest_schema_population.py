# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_rest_schema_population.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for REST tool schema population from OpenAPI specs.
"""

# Standard
from unittest.mock import Mock, patch
import json

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.schemas import ToolCreate, ToolUpdate


class TestRESTSchemaPopulation:
    """Test suite for REST tool OpenAPI schema population."""

    @pytest.fixture
    def mock_openapi_spec(self):
        """Mock OpenAPI specification."""
        return {
            "openapi": "3.0.0",
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
                                            "b": {"type": "number"}
                                        },
                                        "required": ["a", "b"]
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
                                            "properties": {
                                                "result": {"type": "number"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "/no-request-body": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "data": {"type": "string"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "CalculateRequest": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"}
                        }
                    },
                    "CalculateResponse": {
                        "type": "object",
                        "properties": {
                            "sum": {"type": "number"}
                        }
                    }
                }
            }
        }

    @pytest.fixture
    def mock_openapi_spec_with_refs(self):
        """Mock OpenAPI spec with $ref references."""
        return {
            "openapi": "3.0.0",
            "paths": {
                "/calculate": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/CalculateRequest"
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/CalculateResponse"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "CalculateRequest": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"}
                        }
                    },
                    "CalculateResponse": {
                        "type": "object",
                        "properties": {
                            "sum": {"type": "number"}
                        }
                    }
                }
            }
        }

    def test_empty_schema_detection_none(self):
        """Test is_empty_schema with None."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "input_schema": None
        }
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("Should not be called")
            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_empty_schema_detection_empty_dict(self):
        """Test is_empty_schema with empty dict."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "input_schema": {}
        }
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("Should not be called")
            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_empty_schema_detection_empty_properties(self):
        """Test is_empty_schema with empty properties."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "input_schema": {"type": "object", "properties": {}}
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"paths": {}}
            mock_get.return_value = mock_response
            tool = ToolCreate(**tool_data)
            # Should skip population since schema has structure
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_empty_schema_detection_properties_key_only(self):
        """Test is_empty_schema with properties key but no content."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "input_schema": {"properties": {}}
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"paths": {}}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool = ToolCreate(**tool_data)
            # Schema with just properties key is considered empty and should trigger population
            # Since the OpenAPI spec has no paths, it falls back to default
            assert "properties" in tool.input_schema

    def test_schemas_already_populated_skip_fetch(self):
        """Test that OpenAPI fetch is skipped when schemas are already populated."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "input_schema": {"type": "object", "properties": {"a": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"b": {"type": "string"}}}
        }
        with patch("requests.get") as mock_get:
            tool = ToolCreate(**tool_data)
            # Should not call requests.get since schemas are populated
            mock_get.assert_not_called()
            assert tool.input_schema["properties"]["a"]["type"] == "string"

    def test_no_base_url_skip_population(self):
        """Test that schema population is skipped when base_url is missing."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "path_template": "/test"
        }
        tool = ToolCreate(**tool_data)
        assert tool.input_schema == {"type": "object", "properties": {}}

    def test_successful_schema_population_direct(self, mock_openapi_spec):
        """Test successful schema population with direct schema definitions."""
        tool_data = {
            "name": "calculate_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/calculate",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_openapi_spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert "a" in tool.input_schema["properties"]
            assert "b" in tool.input_schema["properties"]
            assert "result" in tool.output_schema["properties"]

    def test_successful_schema_population_with_refs(self, mock_openapi_spec_with_refs):
        """Test successful schema population with $ref references."""
        tool_data = {
            "name": "calculate_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/calculate",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_openapi_spec_with_refs
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert "x" in tool.input_schema["properties"]
            assert "y" in tool.input_schema["properties"]
            assert "sum" in tool.output_schema["properties"]

    def test_missing_ref_in_components(self):
        """Test handling of missing $ref in components."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/MissingSchema"
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {}
            }
        }
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            # Should fall back to default schema
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_invalid_openapi_spec_missing_paths(self):
        """Test handling of invalid OpenAPI spec missing paths."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"openapi": "3.0.0"}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_path_not_found_in_spec(self, mock_openapi_spec):
        """Test handling when path is not found in OpenAPI spec."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/nonexistent"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_openapi_spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_missing_path_template(self):
        """Test handling when path_template is missing."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"paths": {}}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_method_not_found_in_path(self, mock_openapi_spec):
        """Test handling when HTTP method is not found for path."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/calculate",
            "request_type": "DELETE"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_openapi_spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_no_request_body_in_operation(self, mock_openapi_spec):
        """Test handling when operation has no requestBody."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/no-request-body",
            "request_type": "GET"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_openapi_spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}
            assert "data" in tool.output_schema["properties"]

    def test_response_201_status_code(self):
        """Test extraction of output schema from 201 response."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/create": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        },
                        "responses": {
                            "201": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "string"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        tool_data = {
            "name": "create_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/create",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert "id" in tool.output_schema["properties"]

    def test_response_default_status_code(self):
        """Test extraction of output schema from default response."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        },
                        "responses": {
                            "default": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "message": {"type": "string"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert "message" in tool.output_schema["properties"]

    def test_response_ref_not_found_warning(self):
        """Test warning when response $ref is not found in components."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/MissingResponse"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {}
            }
        }
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            # Should not have output_schema populated
            assert tool.output_schema is None or tool.output_schema == {}

    def test_no_valid_response_schema(self):
        """Test handling when no valid response schema is found."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "Success"
                            }
                        }
                    }
                }
            }
        }
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            # Should have input but no output schema
            assert tool.input_schema == {"type": "object"}

    def test_request_exception_fallback(self):
        """Test fallback to default schema on request exception."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test"
        }
        with patch("requests.get") as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.RequestException("Connection error")

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_key_error_fallback(self):
        """Test fallback to default schema on KeyError."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"invalid": "structure"}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_generic_exception_fallback(self):
        """Test fallback to default schema on generic exception."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test"
        }
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("Unexpected error")

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_final_validation_empty_input_schema(self):
        """Test final validation sets default when input_schema is empty."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "post": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_empty_input_schema_after_population_attempt(self):
        """Test that empty input_schema after population gets default schema (lines 902-903)."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "GET"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            # GET with no requestBody should result in empty input_schema, triggering default
            assert tool.input_schema == {"type": "object", "properties": {}}

    def test_key_error_with_no_input_schema(self):
        """Test KeyError exception path with no input_schema (lines 910-912)."""
        tool_data = {
            "name": "test_tool",
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            # Return spec that will cause KeyError when accessing paths
            mock_response.json.side_effect = KeyError("paths")
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool = ToolCreate(**tool_data)
            assert tool.input_schema == {"type": "object", "properties": {}}


class TestToolUpdateSchemaPopulation:
    """Test suite for ToolUpdate schema population."""

    @pytest.fixture
    def mock_openapi_spec(self):
        """Mock OpenAPI specification."""
        return {
            "openapi": "3.0.0",
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
                                            "b": {"type": "number"}
                                        }
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
                                            "properties": {
                                                "result": {"type": "number"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

    def test_url_changed_forces_repopulation(self, mock_openapi_spec):
        """Test that URL change forces schema re-population."""
        tool_data = {
            "integration_type": "REST",
            "url": "http://newexample.com/calculate",  # Providing url triggers URL change detection
            "request_type": "POST",
            "input_schema": {"type": "object", "properties": {"old": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"old": {"type": "string"}}}
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_openapi_spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            tool_update = ToolUpdate(**tool_data)
            # When url is provided, it forces re-population
            assert tool_update.input_schema is not None
            assert tool_update.base_url == "http://newexample.com"
            assert tool_update.path_template == "/calculate"

    def test_no_url_change_respects_existing_schemas(self):
        """Test that existing schemas are preserved when URL hasn't changed."""
        tool_data = {
            "integration_type": "REST",
            "input_schema": {"type": "object", "properties": {"existing": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"existing": {"type": "string"}}}
        }
        with patch("requests.get") as mock_get:
            tool_update = ToolUpdate(**tool_data)
            # Should not call requests.get since schemas are populated and URL not changed
            mock_get.assert_not_called()
            # ToolUpdate doesn't enforce schemas, so they may be None
            if tool_update.input_schema:
                assert "existing" in tool_update.input_schema["properties"]

    def test_tool_update_no_base_url(self):
        """Test ToolUpdate with no base_url skips population."""
        tool_data = {
            "integration_type": "REST",
            "path_template": "/test"
        }
        tool_update = ToolUpdate(**tool_data)
        # ToolUpdate doesn't enforce default schemas like ToolCreate does
        # It may return None if no schema is provided
        assert tool_update.input_schema is None or tool_update.input_schema == {"type": "object", "properties": {}}

    def test_tool_update_with_url_triggers_population(self):
        """Test ToolUpdate with url field triggers schema population."""
        tool_data = {
            "integration_type": "REST",
            "url": "http://example.com/test"
        }

        # Test RequestException
        with patch("requests.get") as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.RequestException("Error")
            tool_update = ToolUpdate(**tool_data)
            # Should have default schema after exception
            assert tool_update.input_schema == {"type": "object", "properties": {}}

        # Test KeyError
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            assert tool_update.input_schema == {"type": "object", "properties": {}}

        # Test generic Exception
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("Generic error")
            tool_update = ToolUpdate(**tool_data)
            assert tool_update.input_schema == {"type": "object", "properties": {}}

    def test_tool_update_empty_schema_detection(self):
        """Test ToolUpdate is_empty_schema logic (lines 1318, 1320)."""
        # Test with properties key but empty value
        tool_data = {
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "input_schema": {"properties": {}}
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"paths": {}}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            # Should trigger population attempt due to empty properties
            assert tool_update.input_schema is not None

    def test_tool_update_missing_path_template(self):
        """Test ToolUpdate with missing path_template (line 1367)."""
        tool_data = {
            "integration_type": "REST",
            "base_url": "http://example.com"
            # No path_template
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"paths": {"/test": {}}}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            # Should fall back to default schema
            assert tool_update.input_schema == {"type": "object", "properties": {}}

    def test_tool_update_path_not_found(self):
        """Test ToolUpdate when path not found in spec (line 1380)."""
        tool_data = {
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/nonexistent"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "paths": {
                    "/other": {"get": {}}
                }
            }
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            assert tool_update.input_schema == {"type": "object", "properties": {}}

    def test_tool_update_method_not_found(self):
        """Test ToolUpdate when HTTP method not found (line 1387)."""
        tool_data = {
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "DELETE"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "paths": {
                    "/test": {
                        "get": {},
                        "post": {}
                    }
                }
            }
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            assert tool_update.input_schema == {"type": "object", "properties": {}}

    def test_tool_update_ref_not_found_in_components(self):
        """Test ToolUpdate with missing $ref in components (lines 1400-1401, 1403-1406, 1408)."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/MissingSchema"
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {}
            }
        }
        tool_data = {
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            # Should fall back to default schema
            assert tool_update.input_schema == {"type": "object", "properties": {}}

    def test_tool_update_response_ref_not_found(self):
        """Test ToolUpdate with missing response $ref (lines 1430-1431, 1433-1436)."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/MissingResponse"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {}
            }
        }
        tool_data = {
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            # Should have input schema but no output schema
            assert tool_update.input_schema == {"type": "object"}

    def test_tool_update_no_valid_response_schema(self):
        """Test ToolUpdate when no valid response schema found (line 1446)."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "Success"
                            }
                        }
                    }
                }
            }
        }
        tool_data = {
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "POST"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            # Should have input but no output schema
            assert tool_update.input_schema == {"type": "object"}

    def test_tool_update_empty_input_after_population(self):
        """Test ToolUpdate final validation for empty input_schema (lines 1451-1452)."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/test": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        tool_data = {
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test",
            "request_type": "GET"
        }
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = spec
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            # GET with no requestBody should result in empty input_schema, triggering default
            assert tool_update.input_schema == {"type": "object", "properties": {}}

    def test_tool_update_exception_handlers(self):
        """Test ToolUpdate exception handlers (lines 1459-1461)."""
        tool_data = {
            "integration_type": "REST",
            "base_url": "http://example.com",
            "path_template": "/test"
        }

        # Test KeyError with no input_schema
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.side_effect = KeyError("paths")
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            tool_update = ToolUpdate(**tool_data)
            assert tool_update.input_schema == {"type": "object", "properties": {}}
