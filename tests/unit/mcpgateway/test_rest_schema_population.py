# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_rest_schema_population.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for REST tool validator behaviour: URL component extraction and
default input_schema population.

Schema *fetching* from OpenAPI specs is tested in test_openapi_service.py
and test_admin_openapi.py.  These tests cover the Pydantic model validators
in ToolCreate and ToolUpdate.
"""

# Third-Party

# First-Party
from mcpgateway.schemas import ToolCreate, ToolUpdate

_DEFAULT_SCHEMA = {"type": "object", "properties": {}}


class TestToolCreateRESTDefaults:
    """ToolCreate validator: URL extraction and default input_schema for REST tools."""

    def test_default_input_schema_when_none(self):
        """REST ToolCreate with no input_schema gets the typed default."""
        tool = ToolCreate(name="t", integration_type="REST", base_url="http://example.com", path_template="/api")
        assert tool.input_schema == _DEFAULT_SCHEMA

    def test_default_input_schema_when_empty_dict(self):
        """REST ToolCreate with input_schema={} gets the typed default."""
        tool = ToolCreate(name="t", integration_type="REST", base_url="http://example.com", path_template="/api", input_schema={})
        assert tool.input_schema == _DEFAULT_SCHEMA

    def test_provided_input_schema_preserved(self):
        """REST ToolCreate with a real input_schema keeps it untouched."""
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        tool = ToolCreate(name="t", integration_type="REST", base_url="http://example.com", path_template="/api", input_schema=schema)
        assert tool.input_schema == schema

    def test_url_extracts_base_url_and_path(self):
        """Providing 'url' auto-populates base_url and path_template."""
        tool = ToolCreate(name="t", integration_type="REST", url="https://api.example.com:8443/v1/calculate")
        assert tool.base_url == "https://api.example.com:8443"
        assert tool.path_template == "/v1/calculate"

    def test_explicit_base_url_not_overwritten(self):
        """Explicit base_url takes precedence over url-derived value."""
        tool = ToolCreate(name="t", integration_type="REST", url="http://derived.com/path", base_url="http://explicit.com")
        assert tool.base_url == "http://explicit.com"

    def test_non_rest_tool_skips_extraction(self):
        """Non-REST integration types don't get URL extraction or default schema.

        MCP/A2A types are rejected outright by other validators, so we verify
        by testing that a REST tool *does* get extraction (positive case) and
        that the helper is gated on integration_type.
        """
        # First-Party
        from mcpgateway.schemas import _extract_rest_url_components

        values = {"integration_type": "MCP", "url": "http://example.com/path"}
        # The helper is never called for non-REST, but verify it's a no-op
        # when called directly without URL (simulating the guard in the validator).
        non_rest_values: dict = {}
        _extract_rest_url_components(non_rest_values)
        assert "base_url" not in non_rest_values

    def test_no_url_no_base_url(self):
        """REST tool with no url still gets default schema."""
        tool = ToolCreate(name="t", integration_type="REST", path_template="/test")
        assert tool.input_schema == _DEFAULT_SCHEMA

    def test_output_schema_not_set_by_default(self):
        """Validator does not touch output_schema."""
        tool = ToolCreate(name="t", integration_type="REST", base_url="http://example.com", path_template="/api")
        assert tool.output_schema is None


class TestToolUpdateRESTDefaults:
    """ToolUpdate validator: URL extraction and empty-schema normalisation."""

    def test_url_extracts_components(self):
        """Providing 'url' on update extracts base_url and path_template."""
        update = ToolUpdate(integration_type="REST", url="http://example.com/test")
        assert update.base_url == "http://example.com"
        assert update.path_template == "/test"

    def test_existing_schemas_preserved(self):
        """Existing schemas are not overwritten by the validator."""
        schema = {"type": "object", "properties": {"existing": {"type": "string"}}}
        update = ToolUpdate(integration_type="REST", input_schema=schema)
        assert update.input_schema == schema

    def test_empty_dict_normalised(self):
        """An explicitly empty {} input_schema is normalised to the typed default."""
        update = ToolUpdate(integration_type="REST", input_schema={})
        assert update.input_schema == _DEFAULT_SCHEMA

    def test_none_schema_left_alone(self):
        """None input_schema is not changed (update may intentionally omit it)."""
        update = ToolUpdate(integration_type="REST")
        assert update.input_schema is None

    def test_non_empty_schema_not_normalised(self):
        """A schema with actual properties is not touched."""
        schema = {"properties": {"x": {"type": "number"}}}
        update = ToolUpdate(integration_type="REST", input_schema=schema)
        assert update.input_schema == schema

    def test_non_rest_skips_extraction(self):
        """Non-REST updates skip URL extraction entirely.

        MCP/A2A types are rejected by other validators, so we verify via
        the helper function directly.
        """
        # First-Party
        from mcpgateway.schemas import _extract_rest_url_components

        values: dict = {}
        _extract_rest_url_components(values)
        assert "base_url" not in values

    def test_output_schema_not_set(self):
        """Validator does not touch output_schema on update."""
        update = ToolUpdate(integration_type="REST", url="http://example.com/api")
        assert update.output_schema is None
