# -*- coding: utf-8 -*-
"""
Simple test script for testing metrics functionality (issue #699)
"""
import sqlite3
import datetime
import uuid
import sys

# Database path
db_path = "mcp-context-forge/mcp.db"

def create_test_data():
    """Create test data for metrics functionality"""
    print("Creating test data in the database...")

    # Connect to SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. Create test tools
        print("Adding test tools...")
        current_time = datetime.datetime.now()
        time_suffix = current_time.strftime("%Y%m%d%H%M%S")
        test_tools = [
            (str(uuid.uuid4()), f"Test Tool 1 - {time_suffix}", f"Test_Tool_1_{time_suffix}", "http://example.com/tool1", "REST", "GET",
             "{}", "{}", "{}", datetime.datetime.now().isoformat(), datetime.datetime.now().isoformat(),
             1, 1, "$", "{}", "test", "127.0.0.1", "test-script", "test-agent",
             "test", "127.0.0.1", "test-script", "test-agent", None, None, 1,
             None, None, f"Test Tool 1 - {time_suffix}", f"test-tool-1-{time_suffix}", None, f"Test Tool 1 - {time_suffix}"),

            (str(uuid.uuid4()), f"Test Tool 2 - {time_suffix}", f"Test_Tool_2_{time_suffix}", "http://example.com/tool2", "REST", "GET",
             "{}", "{}", "{}", datetime.datetime.now().isoformat(), datetime.datetime.now().isoformat(),
             1, 1, "$", "{}", "test", "127.0.0.1", "test-script", "test-agent",
             "test", "127.0.0.1", "test-script", "test-agent", None, None, 1,
             None, None, f"Test Tool 2 - {time_suffix}", f"test-tool-2-{time_suffix}", None, f"Test Tool 2 - {time_suffix}"),

            (str(uuid.uuid4()), f"Test Tool 3 - {time_suffix}", f"Test_Tool_3_{time_suffix}", "http://example.com/tool3", "REST", "GET",
             "{}", "{}", "{}", datetime.datetime.now().isoformat(), datetime.datetime.now().isoformat(),
             1, 1, "$", "{}", "test", "127.0.0.1", "test-script", "test-agent",
             "test", "127.0.0.1", "test-script", "test-agent", None, None, 1,
             None, None, f"Test Tool 3 - {time_suffix}", f"test-tool-3-{time_suffix}", None, f"Test Tool 3 - {time_suffix}")
        ]

        cursor.executemany(
            """INSERT OR REPLACE INTO tools (
                id, original_name, custom_name, url, integration_type, request_type,
                headers, input_schema, annotations, created_at, updated_at,
                enabled, reachable, jsonpath_filter, tags, created_by, created_from_ip,
                created_via, created_user_agent, modified_by, modified_from_ip,
                modified_via, modified_user_agent, import_batch_id, federation_source,
                version, auth_type, auth_value, custom_name, custom_name_slug,
                gateway_id, name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            test_tools
        )

        # Store the tool IDs for reference
        tool_ids = [tool[0] for tool in test_tools]
        print(f"Added tools with IDs: {tool_ids}")

        # 2. Clean up any existing metrics
        print("Cleaning up existing metrics...")
        cursor.execute("DELETE FROM tool_metrics WHERE tool_id IN (?, ?, ?)", (tool_ids[0], tool_ids[1], tool_ids[2]))

        # 3. Add tool metrics with different patterns:
        # - Tool 1: 80% success rate (8 success, 2 failure)
        # - Tool 2: 100% success rate (5 success, 0 failure)
        # - Tool 3: 0% success rate (0 success, 3 failure)

        now = datetime.datetime.now()

        # Tool 1: 80% success rate
        print(f"Adding metrics for Tool 1: 80% success rate... (ID: {tool_ids[0]})")
        for i in range(8):  # 8 successful calls
            cursor.execute(
                "INSERT INTO tool_metrics (tool_id, timestamp, response_time, is_success, error_message) VALUES (?, ?, ?, 1, NULL)",
                (tool_ids[0], (now - datetime.timedelta(minutes=i)).isoformat(), 1.23456)
            )

        for i in range(2):  # 2 failed calls
            cursor.execute(
                "INSERT INTO tool_metrics (tool_id, timestamp, response_time, is_success, error_message) VALUES (?, ?, ?, 0, ?)",
                (tool_ids[0], (now - datetime.timedelta(minutes=i+8)).isoformat(), 2.34567, "Test error")
            )

        # Tool 2: 100% success rate
        print(f"Adding metrics for Tool 2: 100% success rate... (ID: {tool_ids[1]})")
        for i in range(5):  # 5 successful calls
            cursor.execute(
                "INSERT INTO tool_metrics (tool_id, timestamp, response_time, is_success, error_message) VALUES (?, ?, ?, 1, NULL)",
                (tool_ids[1], (now - datetime.timedelta(minutes=i)).isoformat(), 0.9876)
            )

        # Tool 3: 0% success rate
        print(f"Adding metrics for Tool 3: 0% success rate... (ID: {tool_ids[2]})")
        for i in range(3):  # 3 failed calls
            cursor.execute(
                "INSERT INTO tool_metrics (tool_id, timestamp, response_time, is_success, error_message) VALUES (?, ?, ?, 0, ?)",
                (tool_ids[2], (now - datetime.timedelta(minutes=i)).isoformat(), 3.45678, "Test error")
            )

        # Commit the changes
        conn.commit()
        print("Test data created successfully!")

        # Save the tool IDs for reference during testing
        with open("test_tool_ids.txt", "w") as f:
            for i, tool_id in enumerate(tool_ids):
                f.write(f"Tool {i+1} ID: {tool_id}\n")
        print("Tool IDs saved to test_tool_ids.txt")

    except Exception as e:
        print(f"Error creating test data: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    create_test_data()
    print("\nTest data added to the database.")
    print("\nManual Testing Instructions:")
    print("1. Make sure the MCP Gateway is running with admin features enabled:")
    print("   - $env:MCPGATEWAY_ADMIN_API_ENABLED=\"true\"")
    print("   - $env:MCPGATEWAY_UI_ENABLED=\"true\"")
    print("   - python -m uvicorn mcpgateway.main:app --host 0.0.0.0 --port 8008 --reload")
    print("\n2. Access the admin UI at: http://localhost:8008/admin")
    print("   - Login with: admin / changeme")
    print("\n3. Navigate to the Metrics tab and verify:")
    print("   - Test Tool 1 shows 80% success rate with 10 executions")
    print("   - Test Tool 2 shows 100% success rate with 5 executions")
    print("   - Test Tool 3 shows 0% success rate with 3 executions")
    print("   - Response times are formatted with 3 decimal places (x.xxx)")
    print("\n4. Test CSV export:")
    print("   - Click Export Metrics button and verify all rows are included")
    print("   - Or access: http://localhost:8008/admin/metrics/export?entity_type=tools")
    print("   - Verify the CSV includes ALL rows, not just top 5")
    print("   - Verify response times have 3 decimal places")
    print("\n5. Test empty state:")
    print("   - Delete all metrics from the database for a specific tool")
    print("   - Verify the UI and export handle empty state gracefully")
    print("\nDone!")
