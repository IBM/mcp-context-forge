#!/usr/bin/env python3
import sqlite3
from datetime import datetime

def check_todays_metrics():
    conn = sqlite3.connect('mcp.db')
    cursor = conn.cursor()
    
    print("=== TOOL METRICS FROM TODAY (2025-08-27) ===")
    cursor.execute("""
    SELECT t.name, tm.timestamp, tm.is_success, tm.response_time 
    FROM tool_metrics tm 
    JOIN tools t ON t.id = tm.tool_id 
    WHERE tm.timestamp LIKE '2025-08-27%'
    ORDER BY tm.timestamp DESC
    """)
    results = cursor.fetchall()
    if results:
        for name, timestamp, success, response_time in results:
            print(f"  {name}: {timestamp} (success: {success}, {response_time:.3f}s)")
    else:
        print("  No tool metrics recorded today!")
    
    print(f"\nTotal tool metrics today: {len(results)}")
    
    print("\n=== CHECKING TOOLS THAT APPEAR IN UI ===")
    cursor.execute("SELECT id, name, enabled FROM tools WHERE name LIKE 'json%' OR name LIKE 'test%' OR name LIKE 'book%' ORDER BY name")
    tools = cursor.fetchall()
    for tool_id, name, enabled in tools:
        cursor.execute("SELECT COUNT(*) FROM tool_metrics WHERE tool_id = ?", (tool_id,))
        metric_count = cursor.fetchone()[0]
        cursor.execute("SELECT MAX(timestamp) FROM tool_metrics WHERE tool_id = ?", (tool_id,))
        last_exec = cursor.fetchone()[0]
        print(f"  {name}:")
        print(f"    ID: {tool_id}")
        print(f"    Enabled: {enabled}")
        print(f"    Total metrics: {metric_count}")
        print(f"    Last execution: {last_exec}")
        print()
    
    conn.close()

if __name__ == "__main__":
    check_todays_metrics()
