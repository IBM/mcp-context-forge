#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/helpers/trace_generator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Trace generator helper for testing observability backends.

This tool generates sample traces to verify that observability is working
correctly with Phoenix, Jaeger, Zipkin, or other OTLP backends.

Usage:
    python tests/integration/helpers/trace_generator.py
"""

# Standard
import asyncio
import os
import sys

# Add the project root to path so we can import mcpgateway
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

# Standard
import random  # noqa: E402

# First-Party
from mcpgateway.observability import init_telemetry  # noqa: E402


async def test_phoenix_integration():
    """Send some test traces to Phoenix."""

    # Initialize telemetry (if not already done)
    tracer = init_telemetry()

    if not tracer:
        print("❌ Phoenix not configured. Make sure to start with:")
        print("   docker-compose -f docker-compose.yml -f docker-compose.with-phoenix.yml up -d")
        return

    print("✅ Connected to Phoenix. Sending test traces...")

    # Simulate some MCP operations
    operations = [
        ("tool.invoke", {"tool.name": "calculator", "operation": "add"}),
        ("tool.invoke", {"tool.name": "weather", "operation": "get_forecast"}),
        ("prompt.render", {"prompt.name": "greeting", "language": "en"}),
        ("resource.fetch", {"resource.uri": "file:///data.json", "cache.hit": True}),
        ("gateway.federate", {"target.gateway": "gateway-2", "request.size": 1024}),
    ]

    for op_name, attributes in operations:
        with tracer.start_as_current_span(op_name) as span:
            # Add attributes
            for key, value in attributes.items():
                span.set_attribute(key, value)

            # Simulate some work
            duration = random.uniform(0.01, 0.5)
            await asyncio.sleep(duration)

            # Add result
            span.set_attribute("duration.ms", duration * 1000)
            span.set_attribute("status", "success")

            # Simulate occasional errors
            if random.random() < 0.2:
                span.set_attribute("status", "error")
                span.set_attribute("error.message", "Simulated error for testing")

            print(f"  📊 Sent trace: {op_name} ({attributes.get('tool.name') or attributes.get('prompt.name') or 'operation'})")

    # Create a more complex trace with nested spans
    with tracer.start_as_current_span("workflow.complex") as parent_span:
        parent_span.set_attribute("workflow.name", "data_processing")
        parent_span.set_attribute("workflow.steps", 3)

        for i in range(3):
            with tracer.start_as_current_span(f"step.{i + 1}") as child_span:
                child_span.set_attribute("step.index", i + 1)
                child_span.set_attribute("step.name", f"process_batch_{i + 1}")
                await asyncio.sleep(0.1)

        print("  📊 Sent complex workflow trace with nested spans")

    print("\n✅ Test traces sent successfully!")
    print("📈 View them in Phoenix UI: http://localhost:6006")
    print("\nIn Phoenix, you should see:")
    print("  - Tool invocations (calculator, weather)")
    print("  - Prompt rendering")
    print("  - Resource fetching")
    print("  - Gateway federation")
    print("  - Complex workflow with nested spans")


if __name__ == "__main__":
    # Set environment variables if not already set
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["OTEL_SERVICE_NAME"] = "mcp-gateway-test"

    asyncio.run(test_phoenix_integration())
