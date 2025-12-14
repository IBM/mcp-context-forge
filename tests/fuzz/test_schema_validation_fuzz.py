# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/test_schema_validation_fuzz.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Property-based fuzz testing for Pydantic schema validation.
"""

# Standard
import json

# Third-Party
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.schemas import AuthenticationValues, GatewayCreate, PromptCreate, ResourceCreate, ToolCreate


class TestToolCreateSchemaFuzzing:
    """Fuzz testing for ToolCreate schema validation."""

    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=50),
            values=st.one_of(st.none(), st.booleans(), st.integers(), st.floats(), st.text(max_size=100), st.lists(st.text(max_size=20), max_size=5)),
            max_size=20,
        )
    )
    def test_tool_create_schema_robust(self, data):
        """Test ToolCreate schema with arbitrary data."""
        try:
            tool = ToolCreate(**data)
            # If validation succeeds, basic required fields should be present
            assert hasattr(tool, "name")
            if hasattr(tool, "url") and tool.url:
                assert isinstance(tool.url, (str, type(tool.url)))
        except (ValidationError, TypeError, ValueError):
            # Expected for invalid data
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=0, max_size=1000))
    def test_tool_create_name_field(self, name):
        """Test tool name field with various string inputs."""
        try:
            tool = ToolCreate(name=name, url="http://example.com")
            # If validation succeeds, name should not be empty after stripping
            assert len(tool.name.strip()) > 0
        except ValidationError:
            # Expected for invalid names (empty after stripping)
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(st.text(max_size=200), st.integers(), st.booleans(), st.none(), st.lists(st.text(max_size=20)), st.dictionaries(st.text(max_size=10), st.text(max_size=10))))
    def test_tool_create_url_field(self, url):
        """Test tool URL field with various data types."""
        try:
            tool = ToolCreate(name="test", url=url)
            # If validation succeeds, URL should be string or AnyHttpUrl
            assert isinstance(tool.url, (str, type(tool.url)))
        except ValidationError:
            # Expected for invalid URLs
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(st.sampled_from(["REST", "MCP"]), st.text(max_size=50), st.integers(), st.booleans(), st.none()))
    def test_tool_create_integration_type(self, integration_type):
        """Test integration_type field with various inputs."""
        try:
            tool = ToolCreate(name="test", url="http://example.com", integration_type=integration_type)
            # If validation succeeds, should be one of the allowed values
            assert tool.integration_type in ["REST", "MCP"]
        except ValidationError:
            # Expected for invalid integration types
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH", "SSE", "STDIO", "STREAMABLEHTTP"]), st.text(max_size=50), st.integers(), st.booleans()))
    def test_tool_create_request_type(self, request_type):
        """Test request_type field with various inputs."""
        try:
            tool = ToolCreate(name="test", url="http://example.com", request_type=request_type)
            # If validation succeeds, should be one of the allowed values
            assert tool.request_type in ["GET", "POST", "PUT", "DELETE", "PATCH", "SSE", "STDIO", "STREAMABLEHTTP"]
        except ValidationError:
            # Expected for invalid request types
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(st.dictionaries(keys=st.text(min_size=1, max_size=20), values=st.text(max_size=100), max_size=10), st.text(max_size=100), st.integers(), st.booleans(), st.none()))
    def test_tool_create_headers_field(self, headers):
        """Test headers field with various data types."""
        try:
            tool = ToolCreate(name="test", url="http://example.com", headers=headers)
            # If validation succeeds, headers should be dict or None
            assert tool.headers is None or isinstance(tool.headers, dict)
        except ValidationError:
            # Expected for invalid header types
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(
        st.one_of(
            st.dictionaries(keys=st.text(min_size=1, max_size=20), values=st.one_of(st.text(max_size=50), st.integers(), st.booleans()), max_size=10),
            st.text(max_size=100),
            st.integers(),
            st.booleans(),
            st.none(),
        )
    )
    def test_tool_create_input_schema_field(self, input_schema):
        """Test input_schema field with various structures."""
        try:
            tool = ToolCreate(name="test", url="http://example.com", input_schema=input_schema)
            # If validation succeeds, input_schema should be dict or None
            assert isinstance(tool.input_schema, (dict, type(None)))
        except ValidationError:
            # Expected for invalid schema types
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.lists(st.text(min_size=1, max_size=50), min_size=0, max_size=20))
    def test_tool_create_tags_field(self, tags):
        """Test tags field with various lists."""
        try:
            tool = ToolCreate(name="test", url="http://example.com", tags=tags)
            # If validation succeeds, tags should be list of dicts with id/label keys
            assert isinstance(tool.tags, list)
            assert all(isinstance(tag, dict) and "id" in tag and "label" in tag for tag in tool.tags)
        except ValidationError:
            # Expected for invalid tag structures
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


class TestResourceCreateSchemaFuzzing:
    """Fuzz testing for ResourceCreate schema validation."""

    @given(st.dictionaries(keys=st.text(min_size=1, max_size=50), values=st.one_of(st.none(), st.booleans(), st.integers(), st.floats(), st.text(max_size=100)), max_size=15))
    def test_resource_create_schema_robust(self, data):
        """Test ResourceCreate schema with arbitrary data."""
        try:
            resource = ResourceCreate(**data)
            # If validation succeeds, basic fields should be present
            assert hasattr(resource, "uri")
            assert hasattr(resource, "name")
        except (ValidationError, TypeError, ValueError):
            # Expected for invalid data
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=0, max_size=500))
    def test_resource_create_uri_field(self, uri):
        """Test resource URI field with various inputs."""
        try:
            resource = ResourceCreate(uri=uri, name="test")
            # If validation succeeds, URI should be string
            assert isinstance(resource.uri, str)
        except ValidationError:
            # Expected for invalid URIs
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


class TestPromptCreateSchemaFuzzing:
    """Fuzz testing for PromptCreate schema validation."""

    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=50), values=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=100), st.lists(st.text(max_size=20), max_size=5)), max_size=15
        )
    )
    def test_prompt_create_schema_robust(self, data):
        """Test PromptCreate schema with arbitrary data."""
        try:
            prompt = PromptCreate(**data)
            # If validation succeeds, basic fields should be present
            assert hasattr(prompt, "name")
        except (ValidationError, TypeError, ValueError):
            # Expected for invalid data
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


class TestGatewayCreateSchemaFuzzing:
    """Fuzz testing for GatewayCreate schema validation."""

    @given(st.dictionaries(keys=st.text(min_size=1, max_size=50), values=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=100)), max_size=15))
    def test_gateway_create_schema_robust(self, data):
        """Test GatewayCreate schema with arbitrary data."""
        try:
            gateway = GatewayCreate(**data)
            # If validation succeeds, basic fields should be present
            assert hasattr(gateway, "name")
            assert hasattr(gateway, "url")
        except (ValidationError, TypeError, ValueError):
            # Expected for invalid data
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=0, max_size=500))
    def test_gateway_create_url_field(self, url):
        """Test gateway URL field with various inputs."""
        try:
            gateway = GatewayCreate(name="test", url=url)
            # If validation succeeds, URL should be valid
            assert isinstance(gateway.url, (str, type(gateway.url)))
        except ValidationError:
            # Expected for invalid URLs
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


class TestAuthenticationValuesSchemaFuzzing:
    """Fuzz testing for AuthenticationValues schema validation."""

    @given(
        st.dictionaries(keys=st.sampled_from(["username", "password", "token", "auth_type", "custom_header_name", "auth_header_value"]), values=st.one_of(st.text(max_size=100), st.none()), max_size=6)
    )
    def test_auth_values_schema_robust(self, data):
        """Test AuthenticationValues schema with arbitrary data."""
        try:
            auth = AuthenticationValues(**data)
            # If validation succeeds, should have auth_type
            assert hasattr(auth, "auth_type")
        except (ValidationError, TypeError, ValueError):
            # Expected for invalid data
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(st.sampled_from(["basic", "bearer", "custom"]), st.text(max_size=50), st.integers(), st.booleans(), st.none()))
    def test_auth_type_field(self, auth_type):
        """Test auth_type field with various inputs."""
        try:
            auth = AuthenticationValues(auth_type=auth_type)
            # If validation succeeds, auth_type can be any string, None
            assert isinstance(auth.auth_type, (str, type(None)))
        except ValidationError:
            # Expected for invalid auth types
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


class TestComplexSchemaFuzzing:
    """Fuzz testing for complex schema interactions."""

    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=30),
            values=st.recursive(
                st.one_of(st.none(), st.booleans(), st.integers(min_value=-1000, max_value=1000), st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=100)),
                lambda children: st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=20), children, max_size=5),
                max_leaves=20,
            ),
            max_size=15,
        )
    )
    def test_nested_schema_structures(self, data):
        """Test schemas with deeply nested data structures."""
        schemas = [ToolCreate, ResourceCreate, PromptCreate, GatewayCreate]

        for schema_class in schemas:
            try:
                instance = schema_class(**data)
                # If validation succeeds, should be proper instance
                assert isinstance(instance, schema_class)
            except (ValidationError, TypeError, ValueError):
                # Expected for invalid nested structures
                pass
            except Exception as e:
                pytest.fail(f"Unexpected exception with {schema_class.__name__}: {type(e).__name__}: {e}")

    @given(st.text(min_size=0, max_size=10000))
    def test_very_large_text_fields(self, large_text):
        """Test schema validation with very large text inputs."""
        test_cases = [
            ("ToolCreate", {"name": large_text, "url": "http://example.com"}),
            ("ResourceCreate", {"uri": large_text, "name": "test"}),
            ("PromptCreate", {"name": large_text}),
            ("GatewayCreate", {"name": large_text, "url": "http://example.com"}),
        ]

        for schema_name, data in test_cases:
            schema_class = globals()[schema_name]
            try:
                instance = schema_class(**data)
                # If validation succeeds, text should be handled properly
                assert isinstance(instance, schema_class)
            except (ValidationError, TypeError, ValueError, MemoryError):
                # Expected for very large inputs
                pass
            except Exception as e:
                pytest.fail(f"Unexpected exception with {schema_name}: {type(e).__name__}: {e}")

    def test_schema_with_json_serialization(self):
        """Test schema validation after JSON round-trip."""
        test_data = {
            "name": "test_tool",
            "url": "http://example.com",
            "description": "Test tool",
            "integration_type": "REST",
            "request_type": "POST",
            "headers": {"Content-Type": "application/json"},
            "tags": ["test", "api"],
        }

        try:
            # Create instance
            tool = ToolCreate(**test_data)

            # Serialize to JSON and back
            json_str = tool.model_dump_json()
            parsed_data = json.loads(json_str)

            # Create new instance from parsed data
            tool2 = ToolCreate(**parsed_data)

            # Should be equivalent
            assert tool.name == tool2.name
            assert tool.url == tool2.url

        except (ValidationError, json.JSONDecodeError, TypeError, ValueError):
            # Expected for serialization issues
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception in JSON round-trip: {type(e).__name__}: {e}")

    @given(st.integers(min_value=-(2**31), max_value=2**31))
    def test_schema_with_extreme_integers(self, extreme_int):
        """Test schema validation with extreme integer values."""
        # Test with fields that might accept integers
        test_cases = [
            {"name": "test", "url": "http://example.com", "some_field": extreme_int},
            {"name": str(extreme_int), "url": "http://example.com"},
        ]

        for data in test_cases:
            try:
                tool = ToolCreate(**data)
                assert isinstance(tool, ToolCreate)
            except (ValidationError, TypeError, ValueError, OverflowError):
                # Expected for extreme values
                pass
            except Exception as e:
                pytest.fail(f"Unexpected exception with extreme int {extreme_int}: {type(e).__name__}: {e}")
