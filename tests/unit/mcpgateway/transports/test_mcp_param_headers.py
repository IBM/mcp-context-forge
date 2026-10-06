# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_mcp_param_headers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for Mcp-Param-* header extraction and tools/list annotation.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import patch

# Third-Party

# First-Party
from mcpgateway.transports.streamablehttp_transport import (
    _extract_mcp_param_headers,
    _annotate_tools_with_rule_params,
)


class TestExtractMcpParamHeaders:
    def test_empty_headers(self):
        assert _extract_mcp_param_headers(None) == {}
        assert _extract_mcp_param_headers({}) == {}

    def test_extracts_matching(self):
        headers = {"Mcp-Param-tenant": "acme", "Mcp-Param-level": "5", "Content-Type": "application/json"}
        assert _extract_mcp_param_headers(headers) == {"tenant": "acme", "level": "5"}

    def test_case_insensitive(self):
        headers = {"mcp-param-customer_id": "abc", "MCP-PARAM-REGION": "us"}
        assert _extract_mcp_param_headers(headers) == {"customer_id": "abc", "region": "us"}

    def test_ignores_non_matching(self):
        headers = {"Authorization": "Bearer x", "Mcp-Method": "tools/call", "Mcp-Name": "get_data"}
        assert _extract_mcp_param_headers(headers) == {}


class TestAnnotateToolsWithRuleParams:
    def _make_tool(self, name="get_data", props=None):
        if props is None:
            props = {"tenant": {"type": "string"}, "level": {"type": "integer"}, "other": {"type": "string"}}
        return SimpleNamespace(
            name=name,
            title=None,
            description="test",
            inputSchema={"type": "object", "properties": props},
            outputSchema=None,
            annotations=None,
            extension_metadata=None,
        )

    def test_no_rules_leaves_schema_unchanged(self):
        from mcpgateway.transports.streamablehttp_transport import types

        tool = types.Tool.model_validate({"name": "get_data", "description": "test", "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}}}})
        result = _annotate_tools_with_rule_params([tool])
        assert result[0].input_schema == tool.input_schema

    def test_annotates_matching_params(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from mcpgateway.db import Base, RbacRule

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        session.add(
            RbacRule(
                id="r1",
                name="arg-tenant",
                description="",
                capability_type="tool",
                capability_id="get_data",
                permission=None,
                phase="pre_invocation",
                predicate="args.tenant == 'acme'",
                effect="deny",
                priority=100,
                is_active=True,
                is_system=False,
                created_by="admin@example.com",
            )
        )
        session.flush()

        tool = self._make_tool()
        tool.inputSchema = dict(tool.inputSchema)
        tool.inputSchema["properties"] = dict(tool.inputSchema["properties"])

        from mcpgateway.transports.streamablehttp_transport import types

        mcp_tool = types.Tool.model_validate({"name": tool.name, "description": tool.description, "inputSchema": tool.inputSchema})

        with patch("mcpgateway.db.SessionLocal", return_value=session):
            result = _annotate_tools_with_rule_params([mcp_tool])

        assert "x-mcp-header" in result[0].input_schema["properties"]["tenant"]
        assert result[0].input_schema["properties"]["tenant"]["x-mcp-header"] == "tenant"
        # Non-referenced params stay clean
        assert "x-mcp-header" not in result[0].input_schema["properties"]["other"]

    def test_no_matching_props_no_annotation(self):
        tool = self._make_tool(props={"unrelated": {"type": "string"}})
        from mcpgateway.transports.streamablehttp_transport import types

        mcp_tool = types.Tool.model_validate({"name": tool.name, "description": tool.description, "inputSchema": tool.inputSchema})
        result = _annotate_tools_with_rule_params([mcp_tool])
        assert "x-mcp-header" not in result[0].input_schema["properties"]["unrelated"]

    def test_union_typed_param_never_annotated(self):
        # SEP-2243 allows x-mcp-header only on properties whose type IS one
        # primitive; a union node must not be annotated even when one branch
        # is primitive. Validating clients drop tools that carry the
        # annotation on a union-typed parameter.
        from mcpgateway.services.tool_header_annotation import annotate_schema

        schema = {"properties": {"timezone": {"type": ["string", "null"]}, "plain": {"type": "string"}}}
        result = annotate_schema(schema, {"timezone", "plain"})
        assert "x-mcp-header" not in result["properties"]["timezone"]
        assert result["properties"]["plain"]["x-mcp-header"] == "plain"
