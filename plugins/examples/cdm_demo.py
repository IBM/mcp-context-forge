#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDM Plugin Demo - Demonstrates the CDM message_evaluate hook with example plugins.

Usage:
    cd mcp-context-forge
    python plugins/examples/cdm_demo.py

This demo shows how to:
1. Create CDM Messages with different content types
2. Load plugins via PluginManager
3. Call the message_evaluate hook
4. Handle results and violations
"""

import asyncio
import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcpgateway.plugins.framework import PluginManager, GlobalContext, MessageHookType
from mcpgateway.plugins.framework.cdm.models import (
    Message,
    Role,
    ContentPart,
    ContentType,
    ToolCall,
    Resource,
    ResourceReference,
    ResourceType,
)


def create_test_messages() -> list[tuple[str, Message]]:
    """Create a variety of test messages to demonstrate CDM evaluation."""
    messages = []

    # 1. Simple text message (should pass)
    messages.append((
        "Simple text message",
        Message(
            role=Role.USER,
            content="Hello, can you help me with my code?",
        )
    ))

    # 2. Message with PII - SSN (should be blocked by content scanner)
    messages.append((
        "Message with SSN (PII)",
        Message(
            role=Role.USER,
            content="My social security number is 123-45-6789, please help me file taxes.",
        )
    ))

    # 3. Message with email (should pass, email is low severity)
    messages.append((
        "Message with email",
        Message(
            role=Role.USER,
            content="Please send the report to john.doe@example.com",
        )
    ))

    # 4. Safe tool call - read_file (should pass allowlist)
    messages.append((
        "Safe tool call (read_file)",
        Message(
            role=Role.ASSISTANT,
            content=[
                ContentPart(
                    type=ContentType.TOOL_CALL,
                    tool_call=ToolCall(
                        name="read_file",
                        arguments={"path": "/workspace/README.md"},
                        id="call_1",
                    ),
                )
            ],
        )
    ))

    # 5. Dangerous tool call - execute_shell (should be blocked)
    messages.append((
        "Dangerous tool call (execute_shell)",
        Message(
            role=Role.ASSISTANT,
            content=[
                ContentPart(
                    type=ContentType.TOOL_CALL,
                    tool_call=ToolCall(
                        name="execute_shell",
                        arguments={"command": "rm -rf /"},
                        id="call_2",
                    ),
                )
            ],
        )
    ))

    # 6. Safe resource access (should pass)
    messages.append((
        "Safe resource access (/workspace)",
        Message(
            role=Role.USER,
            content=[
                ContentPart(
                    type=ContentType.RESOURCE,
                    resource=Resource(
                        uri="file:///workspace/data.json",
                        name="data.json",
                        resource_type=ResourceType.FILE,
                    ),
                )
            ],
        )
    ))

    # 7. Sensitive resource access (should be blocked)
    messages.append((
        "Sensitive resource access (/etc/passwd)",
        Message(
            role=Role.USER,
            content=[
                ContentPart(
                    type=ContentType.RESOURCE,
                    resource_ref=ResourceReference(
                        uri="file:///etc/passwd",
                        name="passwd",
                        resource_type=ResourceType.FILE,
                    ),
                )
            ],
        )
    ))

    # 8. Mixed content - text + safe tool call (should pass)
    messages.append((
        "Mixed: text + safe tool",
        Message(
            role=Role.ASSISTANT,
            content=[
                ContentPart(
                    type=ContentType.TEXT,
                    text="Let me search for that information.",
                ),
                ContentPart(
                    type=ContentType.TOOL_CALL,
                    tool_call=ToolCall(
                        name="search_docs",
                        arguments={"query": "authentication"},
                        id="call_3",
                    ),
                ),
            ],
        )
    ))

    # 9. Credit card in tool arguments (should be blocked)
    messages.append((
        "Credit card in tool args",
        Message(
            role=Role.ASSISTANT,
            content=[
                ContentPart(
                    type=ContentType.TOOL_CALL,
                    tool_call=ToolCall(
                        name="process_payment",
                        arguments={"card": "4111-1111-1111-1111", "amount": 100},
                        id="call_4",
                    ),
                )
            ],
        )
    ))

    return messages


async def main():
    """Run the CDM plugin demo."""
    print("=" * 70)
    print("CDM Plugin Demo - message_evaluate hook")
    print("=" * 70)
    print()

    # Get config path relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "cdm_demo_config.yaml")

    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}")
        return

    print(f"Loading plugins from: {config_path}")
    print()

    # Reset any existing singleton state (useful when running multiple times)
    PluginManager.reset()

    # Initialize plugin manager
    manager = PluginManager(config_path)
    await manager.initialize()

    print(f"Loaded {manager.plugin_count} plugins")
    print()

    # Create global context
    global_context = GlobalContext(
        request_id="demo-001",
        user="demo_user",
        tenant_id="demo_tenant",
    )

    # Test each message
    messages = create_test_messages()

    for i, (description, message) in enumerate(messages, 1):
        print("-" * 70)
        print(f"Test {i}: {description}")
        print(f"  Role: {message.role.value}")

        # Show content preview
        if isinstance(message.content, str):
            preview = message.content[:50] + "..." if len(message.content) > 50 else message.content
            print(f"  Content: {preview}")
        else:
            for j, part in enumerate(message.content):
                if part.type == ContentType.TEXT:
                    print(f"  Part {j+1}: TEXT - {part.text[:40]}...")
                elif part.type == ContentType.TOOL_CALL and part.tool_call:
                    print(f"  Part {j+1}: TOOL_CALL - {part.tool_call.name}")
                elif part.type == ContentType.RESOURCE and part.resource:
                    print(f"  Part {j+1}: RESOURCE - {part.resource.uri}")
                elif part.type == ContentType.RESOURCE and part.resource_ref:
                    print(f"  Part {j+1}: RESOURCE_REF - {part.resource_ref.uri}")

        print()

        # Show MessageViews
        views = message.view(global_context)
        print(f"  MessageViews ({len(views)}):")
        for view in views:
            print(f"    - {view}")

        print()

        # Invoke the message_evaluate hook
        try:
            result, contexts = await manager.invoke_hook(
                hook_type=MessageHookType.MESSAGE_EVALUATE.value,
                payload=message,
                global_context=global_context,
            )

            if result.continue_processing:
                print(f"  Result: ✓ ALLOWED")
            else:
                print(f"  Result: ✗ BLOCKED")
                if result.violation:
                    print(f"    Reason: {result.violation.reason}")
                    print(f"    Code: {result.violation.code}")
                    if result.violation.details:
                        print(f"    Details: {result.violation.details}")

        except Exception as e:
            print(f"  Result: ✗ ERROR - {e}")

        print()

    # Demonstrate OPA serialization
    print("-" * 70)
    print("OPA Serialization Demo")
    print("-" * 70)

    sample_message = Message(
        role=Role.ASSISTANT,
        content=[
            ContentPart(
                type=ContentType.TOOL_CALL,
                tool_call=ToolCall(
                    name="read_file",
                    arguments={"path": "/workspace/test.py"},
                    id="call_opa",
                ),
            )
        ],
    )

    # Show OPA input format
    import json
    opa_input = sample_message.to_opa_input(global_context)
    print("Message.to_opa_input() output:")
    print(json.dumps(opa_input, indent=2, default=str))
    print()

    # Show single view serialization
    views = sample_message.view(global_context)
    if views:
        view_dict = views[0].to_dict()
        print("MessageView.to_dict() output:")
        print(json.dumps(view_dict, indent=2, default=str))

    # Cleanup
    await manager.shutdown()

    print()
    print("=" * 70)
    print("Demo complete!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
