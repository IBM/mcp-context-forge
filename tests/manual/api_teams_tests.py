#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Gateway v0.7.0 - Teams API Tests

Comprehensive testing of team management endpoints including:
- Team creation and management
- Team membership operations
- Team invitations
- Team visibility and permissions

Usage:
    python3 tests/manual/api_teams_tests.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Teams API test cases
TEAMS_TESTS = [
    {
        "id": "TEAM-001",
        "endpoint": "/teams",
        "method": "GET",
        "description": "List user's teams",
        "curl_command": 'curl http://localhost:4444/teams -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Array of teams user belongs to",
        "test_steps": [
            "1. Get JWT token from login first",
            "2. Execute teams list request",
            "3. Verify HTTP 200 status",
            "4. Check response is JSON array",
            "5. Verify personal team is included",
            "6. Check team data includes name, id, visibility"
        ],
        "validation": "Returns user's teams including personal team"
    },
    {
        "id": "TEAM-002", 
        "endpoint": "/teams",
        "method": "POST",
        "description": "Create new team",
        "curl_command": 'curl -X POST http://localhost:4444/teams -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json"',
        "request_body": '{"name":"Manual Test Team","description":"Team created during manual testing","visibility":"private","max_members":20}',
        "expected_status": 201,
        "expected_response": "Team created successfully with generated ID",
        "test_steps": [
            "1. Prepare team creation data",
            "2. Execute team creation request",
            "3. Verify HTTP 201 status",
            "4. Check response contains team ID",
            "5. Verify team appears in teams list", 
            "6. Save team ID for subsequent tests"
        ],
        "validation": "Team created and accessible"
    },
    {
        "id": "TEAM-003",
        "endpoint": "/teams/{id}",
        "method": "GET", 
        "description": "Get team details",
        "curl_command": 'curl http://localhost:4444/teams/{TEAM_ID} -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Team details with member information",
        "test_steps": [
            "1. Use team ID from creation test or personal team",
            "2. Request team details",
            "3. Verify HTTP 200 status",
            "4. Check response includes team metadata",
            "5. Verify member list is included",
            "6. Check permissions are enforced"
        ],
        "validation": "Team details accessible to members"
    },
    {
        "id": "TEAM-004",
        "endpoint": "/teams/{id}",
        "method": "PUT",
        "description": "Update team information",
        "curl_command": 'curl -X PUT http://localhost:4444/teams/{TEAM_ID} -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json"',
        "request_body": '{"name":"Updated Team Name","description":"Updated during manual testing"}',
        "expected_status": 200,
        "expected_response": "Team updated successfully",
        "test_steps": [
            "1. Use team ID from creation test",
            "2. Prepare update data",
            "3. Execute team update request",
            "4. Verify HTTP 200 status", 
            "5. Check team details show updated information",
            "6. Verify only team owners can update"
        ],
        "validation": "Team update works for owners"
    },
    {
        "id": "TEAM-005",
        "endpoint": "/teams/{id}/members",
        "method": "GET",
        "description": "List team members", 
        "curl_command": 'curl http://localhost:4444/teams/{TEAM_ID}/members -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Array of team members with roles",
        "test_steps": [
            "1. Use valid team ID",
            "2. Request member list",
            "3. Verify HTTP 200 status",
            "4. Check members array in response",
            "5. Verify member roles (owner/member)",
            "6. Check join dates and status"
        ],
        "validation": "Member list shows users with correct roles"
    },
    {
        "id": "TEAM-006",
        "endpoint": "/teams/{id}/members", 
        "method": "POST",
        "description": "Add team member",
        "curl_command": 'curl -X POST http://localhost:4444/teams/{TEAM_ID}/members -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json"',
        "request_body": '{"user_email":"newmember@example.com","role":"member"}',
        "expected_status": 201,
        "expected_response": "Member added to team successfully",
        "test_steps": [
            "1. Create test user first (if needed)",
            "2. Prepare member addition data",
            "3. Execute add member request", 
            "4. Verify HTTP 201 status",
            "5. Check member appears in member list",
            "6. Verify only team owners can add members"
        ],
        "validation": "Member addition works for team owners"
    },
    {
        "id": "TEAM-007",
        "endpoint": "/teams/{id}/invitations",
        "method": "GET",
        "description": "List team invitations",
        "curl_command": 'curl http://localhost:4444/teams/{TEAM_ID}/invitations -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Array of pending invitations",
        "test_steps": [
            "1. Use valid team ID",
            "2. Request invitations list", 
            "3. Verify HTTP 200 status",
            "4. Check invitations array",
            "5. Verify invitation details (email, role, status)",
            "6. Test permissions (team owners only)"
        ],
        "validation": "Invitation list accessible to team owners"
    },
    {
        "id": "TEAM-008",
        "endpoint": "/teams/{id}/invitations",
        "method": "POST", 
        "description": "Create team invitation",
        "curl_command": 'curl -X POST http://localhost:4444/teams/{TEAM_ID}/invitations -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json"',
        "request_body": '{"email":"invitee@example.com","role":"member","message":"Join our testing team!"}',
        "expected_status": 201,
        "expected_response": "Invitation created and sent",
        "test_steps": [
            "1. Prepare invitation data",
            "2. Execute invitation creation",
            "3. Verify HTTP 201 status",
            "4. Check invitation created in database",
            "5. Verify email sent (if email configured)",
            "6. Test invitation token functionality"
        ],
        "validation": "Invitation created with valid token"
    },
    {
        "id": "TEAM-009", 
        "endpoint": "/teams/{id}/leave",
        "method": "POST",
        "description": "Leave team",
        "curl_command": 'curl -X POST http://localhost:4444/teams/{TEAM_ID}/leave -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Successfully left team (or 403 if personal team)",
        "test_steps": [
            "1. Use non-personal team ID",
            "2. Execute leave team request",
            "3. Verify appropriate response",
            "4. Check user no longer in member list",
            "5. Test that personal teams cannot be left",
            "6. Verify access to team resources is removed"
        ],
        "validation": "Team leave functionality works, personal teams protected"
    },
    {
        "id": "TEAM-010",
        "endpoint": "/teams/{id}",
        "method": "DELETE",
        "description": "Delete team",
        "curl_command": 'curl -X DELETE http://localhost:4444/teams/{TEAM_ID} -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 204, 
        "expected_response": "Team deleted successfully (or 403 if personal team)",
        "test_steps": [
            "1. Use test team ID (not personal team)",
            "2. Execute team deletion request",
            "3. Verify appropriate HTTP status",
            "4. Check team no longer exists",
            "5. Test that personal teams cannot be deleted",
            "6. Verify team resources are handled properly"
        ],
        "validation": "Team deletion works, personal teams protected"
    }
]


def run_teams_tests():
    """Run all teams API tests."""
    
    print("👥 TEAMS API TESTING")
    print("=" * 60)
    print("🎯 Testing team management endpoints")
    
    results = []
    
    print("\\n🔧 Pre-test Requirements:")
    print("1. MCP Gateway running (make dev)")
    print("2. Valid JWT token (from login)")
    print("3. Admin access for team operations")
    
    # Get JWT token
    token = input("\\nEnter JWT token (from auth login test): ").strip()
    if not token:
        print("❌ JWT token required for team API testing")
        return []
    
    print("\\n🧪 Executing Teams API Tests...")
    
    for test in TEAMS_TESTS:
        print(f"\\n{'='*60}")
        print(f"🧪 TEST {test['id']}: {test['endpoint']} ({test['method']})")
        print(f"Description: {test['description']}")
        
        print(f"\\n📋 Test Steps:")
        for step in test['test_steps']:
            print(f"   {step}")
        
        # Show curl command with token
        curl_cmd = test['curl_command'].replace('<TOKEN>', token)
        print(f"\\n💻 cURL Command:")
        print(f"   {curl_cmd}")
        if test['request_body']:
            print(f"   Data: {test['request_body']}")
        
        print(f"\\n✅ Expected:")
        print(f"   Status: {test['expected_status']}")
        print(f"   Response: {test['expected_response']}")
        
        # Manual execution
        response = input(f"\\nExecute test {test['id']}? (y/n/skip): ").lower()
        
        if response == 'skip' or response == 's':
            results.append({"id": test['id'], "status": "SKIP"})
            continue
        elif response != 'y':
            break
        
        # Get results
        actual_status = input("Actual HTTP status: ")
        actual_response = input("Response summary: ")
        
        passed = actual_status == str(test['expected_status'])
        status = "PASS" if passed else "FAIL"
        
        print(f"\\n{'✅' if passed else '❌'} {test['id']}: {status}")
        
        results.append({
            "id": test['id'],
            "endpoint": test['endpoint'], 
            "status": status,
            "actual_status": actual_status,
            "actual_response": actual_response,
            "timestamp": datetime.now().isoformat()
        })
    
    # Save results
    results_file = Path("tests/manual/teams_test_results.json")
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\\n📄 Results saved: {results_file}")
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("👥 Teams API Tests") 
        print("Usage:")
        print("  python3 tests/manual/api_teams_tests.py    # Run all tests")
        print("  python3 tests/manual/api_teams_tests.py --help  # This help")
    else:
        try:
            results = run_teams_tests()
            print("\\n🎉 Teams API testing complete!")
        except KeyboardInterrupt:
            print("\\n❌ Testing cancelled")
        except Exception as e:
            print(f"❌ Error: {e}")
            sys.exit(1)