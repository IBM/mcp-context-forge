# -*- coding: utf-8 -*-
"""Location: ./tests/integration/plugins/test_span_attribute_customizer_integration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for SpanAttributeCustomizer plugin with ObservabilityService.
"""

import pytest
from sqlalchemy.orm import Session

from mcpgateway.db import ObservabilitySpan, SessionLocal
from mcpgateway.plugins.framework import GlobalContext, PluginConfig, PluginContext, ToolHookType, ToolPreInvokePayload
from mcpgateway.services.observability_service import ObservabilityService
from plugins.span_attribute_customizer.span_attribute_customizer import SpanAttributeCustomizerPlugin


@pytest.fixture
def db_session():
    """Create a test database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def observability_service():
    """Create an ObservabilityService instance."""
    return ObservabilityService()


@pytest.fixture
def plugin_with_global_attrs():
    """Create plugin with global attributes."""
    config = PluginConfig(
        name="SpanAttributeCustomizer",
        kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
        config={
            "global_attributes": {
                "environment": "integration-test",
                "region": "us-west-2",
                "team": "test-team",
            }
        },
    )
    return SpanAttributeCustomizerPlugin(config)


@pytest.fixture
def plugin_with_transformations():
    """Create plugin with attribute transformations."""
    config = PluginConfig(
        name="SpanAttributeCustomizer",
        kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
        config={
            "global_attributes": {
                "user_email": "test@example.com",
                "service_name": "weather-api",
            },
            "transformations": [
                {"field": "user_email", "operation": "hash"},
                {"field": "service_name", "operation": "uppercase"},
            ],
        },
    )
    return SpanAttributeCustomizerPlugin(config)


@pytest.fixture
def plugin_with_removal():
    """Create plugin with attribute removal."""
    config = PluginConfig(
        name="SpanAttributeCustomizer",
        kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
        hooks=[ToolHookType.TOOL_PRE_INVOKE],
        priority=10,
        config={
            "global_attributes": {
                "public_attr": "visible",
                "sensitive_attr": "should_be_removed",
            },
            "remove_attributes": ["sensitive_attr"],
        },
    )
    return SpanAttributeCustomizerPlugin(config)


class TestSpanAttributeCustomizerIntegration:
    """Integration tests for SpanAttributeCustomizer with ObservabilityService."""

    @pytest.mark.asyncio
    async def test_global_attributes_injected_into_span(self, db_session: Session, observability_service: ObservabilityService, plugin_with_global_attrs):
        """Test that global attributes are injected into created spans."""
        # Setup
        global_ctx = GlobalContext(request_id="test-integration-1")
        plugin_ctx = PluginContext(global_context=global_ctx)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        # Execute plugin hook
        await plugin_with_global_attrs.tool_pre_invoke(payload, plugin_ctx)

        # Create trace and span with context
        trace_id = observability_service.start_trace(
            name="test_trace",
            http_method="POST",
            http_url="/test",
        )

        span_id = observability_service.start_span(
            trace_id=trace_id,
            name="test_span",
            resource_type="tool",
            resource_name="test_tool",
            context=plugin_ctx,
        )

        # Verify span has custom attributes
        span = db_session.query(ObservabilitySpan).filter_by(span_id=span_id).first()
        assert span is not None
        assert span.attributes["environment"] == "integration-test"
        assert span.attributes["region"] == "us-west-2"
        assert span.attributes["team"] == "test-team"

        # Cleanup
        observability_service.end_span(span_id)
        observability_service.end_trace(trace_id)

    @pytest.mark.asyncio
    async def test_transformed_attributes_in_span(self, db_session: Session, observability_service: ObservabilityService, plugin_with_transformations):
        """Test that attribute transformations are applied correctly."""
        # Setup
        global_ctx = GlobalContext(request_id="test-integration-2")
        plugin_ctx = PluginContext(global_context=global_ctx)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        # Execute plugin hook
        await plugin_with_transformations.tool_pre_invoke(payload, plugin_ctx)

        # Create trace and span with context
        trace_id = observability_service.start_trace(name="test_trace")
        span_id = observability_service.start_span(
            trace_id=trace_id,
            name="test_span",
            context=plugin_ctx,
        )

        # Verify transformations were applied
        span = db_session.query(ObservabilitySpan).filter_by(span_id=span_id).first()
        assert span is not None
        # Email should be hashed (16 chars)
        assert len(span.attributes["user_email"]) == 16
        assert span.attributes["user_email"] != "test@example.com"
        # Service name should be uppercase
        assert span.attributes["service_name"] == "WEATHER-API"

        # Cleanup
        observability_service.end_span(span_id)
        observability_service.end_trace(trace_id)

    @pytest.mark.asyncio
    async def test_attribute_removal_from_span(self, db_session: Session, observability_service: ObservabilityService, plugin_with_removal):
        """Test that specified attributes are removed from spans."""
        # Setup
        global_ctx = GlobalContext(request_id="test-integration-3")
        plugin_ctx = PluginContext(global_context=global_ctx)
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        # Execute plugin hook
        await plugin_with_removal.tool_pre_invoke(payload, plugin_ctx)

        # Create trace and span with context
        trace_id = observability_service.start_trace(name="test_trace")
        span_id = observability_service.start_span(
            trace_id=trace_id,
            name="test_span",
            attributes={"base_attr": "value"},
            context=plugin_ctx,
        )

        # Verify sensitive attribute was removed
        span = db_session.query(ObservabilitySpan).filter_by(span_id=span_id).first()
        assert span is not None
        assert "public_attr" in span.attributes
        assert "sensitive_attr" not in span.attributes
        assert span.attributes["public_attr"] == "visible"

        # Cleanup
        observability_service.end_span(span_id)
        observability_service.end_trace(trace_id)

    @pytest.mark.asyncio
    async def test_tool_specific_overrides(self, db_session: Session, observability_service: ObservabilityService):
        """Test per-tool attribute overrides work correctly."""
        # Setup plugin with tool-specific config
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"environment": "test"},
                "tool_overrides": {
                    "weather_tool": {
                        "attributes": {
                            "service": "weather",
                            "cost_center": "engineering",
                        }
                    }
                },
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)

        global_ctx = GlobalContext(request_id="test-integration-4")
        plugin_ctx = PluginContext(global_context=global_ctx)
        payload = ToolPreInvokePayload(name="weather_tool", arguments={})

        # Execute plugin hook
        await plugin.tool_pre_invoke(payload, plugin_ctx)

        # Create trace and span
        trace_id = observability_service.start_trace(name="test_trace")
        span_id = observability_service.start_span(
            trace_id=trace_id,
            name="test_span",
            resource_name="weather_tool",
            context=plugin_ctx,
        )

        # Verify tool-specific attributes
        span = db_session.query(ObservabilitySpan).filter_by(span_id=span_id).first()
        assert span is not None
        assert span.attributes["environment"] == "test"
        assert span.attributes["service"] == "weather"
        assert span.attributes["cost_center"] == "engineering"

        # Cleanup
        observability_service.end_span(span_id)
        observability_service.end_trace(trace_id)

    @pytest.mark.asyncio
    async def test_conditional_attributes(self, db_session: Session, observability_service: ObservabilityService):
        """Test conditional attributes are added when conditions match."""
        # Setup plugin with conditional config
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {"environment": "test"},
                "conditions": [
                    {
                        "when": 'tool.name == "sensitive_tool"',
                        "add": {
                            "audit_required": True,
                            "compliance_level": "high",
                        },
                    }
                ],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)

        global_ctx = GlobalContext(request_id="test-integration-5")
        plugin_ctx = PluginContext(global_context=global_ctx)
        payload = ToolPreInvokePayload(name="sensitive_tool", arguments={})

        # Execute plugin hook
        await plugin.tool_pre_invoke(payload, plugin_ctx)

        # Create trace and span
        trace_id = observability_service.start_trace(name="test_trace")
        span_id = observability_service.start_span(
            trace_id=trace_id,
            name="test_span",
            context=plugin_ctx,
        )

        # Verify conditional attributes were added
        span = db_session.query(ObservabilitySpan).filter_by(span_id=span_id).first()
        assert span is not None
        assert span.attributes["audit_required"] is True
        assert span.attributes["compliance_level"] == "high"

        # Cleanup
        observability_service.end_span(span_id)
        observability_service.end_trace(trace_id)

    @pytest.mark.asyncio
    async def test_span_without_plugin_context(self, db_session: Session, observability_service: ObservabilityService):
        """Test that spans work normally without plugin context."""
        # Create span without plugin context
        trace_id = observability_service.start_trace(name="test_trace")
        span_id = observability_service.start_span(
            trace_id=trace_id,
            name="test_span",
            attributes={"base_attr": "value"},
        )

        # Verify span was created with only base attributes
        span = db_session.query(ObservabilitySpan).filter_by(span_id=span_id).first()
        assert span is not None
        assert span.attributes == {"base_attr": "value"}

        # Cleanup
        observability_service.end_span(span_id)
        observability_service.end_trace(trace_id)

    @pytest.mark.asyncio
    async def test_complex_scenario(self, db_session: Session, observability_service: ObservabilityService):
        """Test complex scenario with multiple features combined."""
        # Setup plugin with all features
        config = PluginConfig(
            name="SpanAttributeCustomizer",
            kind="plugins.span_attribute_customizer.span_attribute_customizer.SpanAttributeCustomizerPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            priority=10,
            config={
                "global_attributes": {
                    "environment": "production",
                    "user_email": "admin@example.com",
                    "debug_info": "sensitive",
                },
                "tool_overrides": {
                    "api_tool": {
                        "attributes": {"service": "api"},
                        "remove_attributes": ["debug_info"],
                    }
                },
                "transformations": [
                    {"field": "user_email", "operation": "hash"},
                ],
                "conditions": [
                    {
                        "when": 'tool.name == "api_tool"',
                        "add": {"cost_tracking": True},
                    }
                ],
                "remove_attributes": ["internal_id"],
            },
        )
        plugin = SpanAttributeCustomizerPlugin(config)

        global_ctx = GlobalContext(request_id="test-integration-6")
        plugin_ctx = PluginContext(global_context=global_ctx)
        payload = ToolPreInvokePayload(name="api_tool", arguments={})

        # Execute plugin hook
        await plugin.tool_pre_invoke(payload, plugin_ctx)

        # Create trace and span
        trace_id = observability_service.start_trace(name="test_trace")
        span_id = observability_service.start_span(
            trace_id=trace_id,
            name="test_span",
            attributes={"internal_id": "12345"},
            context=plugin_ctx,
        )

        # Verify all features work together
        span = db_session.query(ObservabilitySpan).filter_by(span_id=span_id).first()
        assert span is not None

        # Global attributes
        assert span.attributes["environment"] == "production"

        # Transformations
        assert len(span.attributes["user_email"]) == 16  # Hashed

        # Tool overrides
        assert span.attributes["service"] == "api"

        # Conditional attributes
        assert span.attributes["cost_tracking"] is True

        # Attribute removal (both global and tool-specific)
        assert "debug_info" not in span.attributes
        assert "internal_id" not in span.attributes

        # Cleanup
        observability_service.end_span(span_id)
        observability_service.end_trace(trace_id)
