#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Gateway v0.7.0 - Virtual Servers API Tests

Comprehensive testing of virtual server management including:
- Server listing and creation
- Server configuration and updates  
- Transport endpoints (SSE, WebSocket)
- Server status and health monitoring

Usage:
    python3 tests/manual/api_servers_tests.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Virtual Servers API test cases
SERVERS_TESTS = [
    {
        "id": "SRV-001",
        "endpoint": "/servers", 
        "method": "GET",
        "description": "List virtual servers with team filtering",
        "curl_command": 'curl http://localhost:4444/servers -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Array of virtual servers user can access",
        "test_steps": [
            "1. Use valid JWT token",
            "2. Execute servers list request", 
            "3. Verify HTTP 200 status",
            "4. Check response contains server array",
            "5. Verify team-based filtering applied",
            "6. Check server metadata (name, transport, team, etc.)"
        ],
        "validation": "Servers listed with proper team-based access control",
        "critical": True
    },
    {
        "id": "SRV-002",
        "endpoint": "/servers",
        "method": "POST", 
        "description": "Create new virtual server",
        "curl_command": 'curl -X POST http://localhost:4444/servers -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json"',
        "request_body": '{"name":"Manual Test Server","description":"Server created during manual testing","transport":"sse","config":{"timeout":30}}',
        "expected_status": 201,
        "expected_response": "Virtual server created with ID and team assignment",
        "test_steps": [
            "1. Prepare server configuration data",
            "2. Execute server creation request",
            "3. Verify HTTP 201 status",
            "4. Check response contains server ID",
            "5. Verify server appears in servers list",
            "6. Check automatic team assignment",
            "7. Save server ID for subsequent tests"
        ],
        "validation": "Server created with automatic team assignment"
    },
    {
        "id": "SRV-003", 
        "endpoint": "/servers/{id}",
        "method": "GET",
        "description": "Get server details and configuration",
        "curl_command": 'curl http://localhost:4444/servers/{SERVER_ID} -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Server details with full configuration",
        "test_steps": [
            "1. Use server ID from creation test or existing server",
            "2. Request server details",
            "3. Verify HTTP 200 status",
            "4. Check detailed server information",
            "5. Verify configuration data is included",
            "6. Check team and ownership information"
        ],
        "validation": "Server details accessible with complete metadata"
    },
    {
        "id": "SRV-004",
        "endpoint": "/servers/{id}",
        "method": "PUT",
        "description": "Update server configuration",
        "curl_command": 'curl -X PUT http://localhost:4444/servers/{SERVER_ID} -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json"',
        "request_body": '{"name":"Updated Server Name","description":"Updated during manual testing","config":{"timeout":60}}',
        "expected_status": 200,
        "expected_response": "Server updated successfully", 
        "test_steps": [
            "1. Use server ID from previous tests",
            "2. Prepare update configuration", 
            "3. Execute server update request",
            "4. Verify HTTP 200 status",
            "5. Check server details show updates",
            "6. Verify permissions enforced (owner/team access)"
        ],
        "validation": "Server updates work with proper authorization"
    },
    {
        "id": "SRV-005",
        "endpoint": "/servers/{id}/sse",
        "method": "GET", 
        "description": "Server-Sent Events connection test",
        "curl_command": 'curl -N http://localhost:4444/servers/{SERVER_ID}/sse -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "SSE stream established, events received",
        "test_steps": [
            "1. Use server ID with SSE transport",
            "2. Execute SSE connection request",
            "3. Verify HTTP 200 status", 
            "4. Check for SSE headers (text/event-stream)",
            "5. Monitor stream for events",
            "6. Test connection stability"
        ],
        "validation": "SSE connection works, events stream properly"
    },
    {
        "id": "SRV-006",
        "endpoint": "/servers/{id}/ws",
        "method": "WebSocket",
        "description": "WebSocket connection test", 
        "curl_command": "Use WebSocket client or browser developer tools",
        "request_body": "WebSocket upgrade request with Authorization header",
        "expected_status": 101,
        "expected_response": "WebSocket connection established",
        "test_steps": [
            "1. Use WebSocket client tool or browser dev tools",
            "2. Connect to ws://localhost:4444/servers/{SERVER_ID}/ws",
            "3. Include Authorization header with JWT token",
            "4. Verify WebSocket upgrade (status 101)",
            "5. Test bidirectional communication",
            "6. Check connection stability and message handling"
        ],
        "validation": "WebSocket connection works, bidirectional communication"
    },
    {
        "id": "SRV-007",
        "endpoint": "/servers/{id}/tools",
        "method": "GET",
        "description": "List tools available on server",
        "curl_command": 'curl http://localhost:4444/servers/{SERVER_ID}/tools -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Array of tools available on the server",
        "test_steps": [
            "1. Use server ID with available tools",
            "2. Request server tools",
            "3. Verify HTTP 200 status",
            "4. Check tools array in response", 
            "5. Verify tool details and schemas",
            "6. Check team-based tool access"
        ],
        "validation": "Server tools listed with proper access control"
    },
    {
        "id": "SRV-008",
        "endpoint": "/servers/{id}/resources", 
        "method": "GET",
        "description": "List resources available on server",
        "curl_command": 'curl http://localhost:4444/servers/{SERVER_ID}/resources -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Array of resources available on the server",
        "test_steps": [
            "1. Use server ID with available resources",
            "2. Request server resources",
            "3. Verify HTTP 200 status",
            "4. Check resources array",
            "5. Verify resource URIs and metadata",
            "6. Test resource access permissions"
        ],
        "validation": "Server resources listed with access control"
    },
    {
        "id": "SRV-009",
        "endpoint": "/servers/{id}/status",
        "method": "GET",
        "description": "Get server status and health",
        "curl_command": 'curl http://localhost:4444/servers/{SERVER_ID}/status -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Server status, health, and connection info",
        "test_steps": [
            "1. Use any valid server ID",
            "2. Request server status",
            "3. Verify HTTP 200 status",
            "4. Check status information", 
            "5. Verify health indicators",
            "6. Check connection and performance metrics"
        ],
        "validation": "Server status and health data provided"
    },
    {
        "id": "SRV-010",
        "endpoint": "/servers/{id}",
        "method": "DELETE",
        "description": "Delete virtual server",
        "curl_command": 'curl -X DELETE http://localhost:4444/servers/{SERVER_ID} -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 204,
        "expected_response": "Server deleted successfully", 
        "test_steps": [
            "1. Use test server ID (not production server)",
            "2. Execute server deletion request",
            "3. Verify HTTP 204 status",
            "4. Check server no longer in list",
            "5. Verify permissions enforced",
            "6. Check cleanup of associated resources"
        ],
        "validation": "Server deletion works with proper authorization"
    }
]


def run_servers_tests():
    """Run all servers API tests."""
    
    print("🖥️ VIRTUAL SERVERS API TESTING")
    print("=" * 60)
    
    results = []
    
    # Get JWT token
    token = input("Enter JWT token: ").strip()
    if not token:
        print("❌ Token required")
        return []
    
    for test in SERVERS_TESTS:
        print(f"\\n{'='*60}")
        print(f"🧪 {test['id']}: {test['endpoint']} ({test['method']})")
        
        if test.get('critical'):
            print("🚨 CRITICAL TEST")
        
        # Show steps and execute
        print(f"\\nSteps:")
        for step in test['test_steps']:
            print(f"   {step}")
        
        curl_cmd = test['curl_command'].replace('<TOKEN>', token)
        print(f"\\nCommand: {curl_cmd}")
        
        response = input(f"\\nExecute {test['id']}? (y/n/skip): ")
        
        if response.lower() == 'skip':
            results.append({"id": test['id'], "status": "SKIP"})
        elif response.lower() == 'y':
            status_code = input("HTTP status: ")
            response_summary = input("Response summary: ")
            
            passed = status_code == str(test['expected_status'])
            results.append({
                "id": test['id'],
                "status": "PASS" if passed else "FAIL",
                "actual_status": status_code,
                "response": response_summary
            })
    
    # Save results
    with open("tests/manual/servers_test_results.json", 'w') as f:
        json.dump(results, f, indent=2)
    
    return results


if __name__ == "__main__":
    try:
        results = run_servers_tests()
        print("\\n🎉 Servers API testing complete!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)