#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Gateway v0.7.0 - Authentication API Tests

Comprehensive testing of all authentication endpoints including:
- Email registration and login
- JWT token management  
- SSO integration (GitHub, Google)
- Password management
- Profile operations

Usage:
    python3 tests/manual/api_authentication_tests.py
    python3 tests/manual/api_authentication_tests.py --endpoint /auth/login
"""

import sys
import subprocess
import json
import requests
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Authentication test cases
AUTH_TESTS = [
    {
        "id": "AUTH-001",
        "endpoint": "/auth/register",
        "method": "POST",
        "description": "User registration endpoint",
        "curl_command": 'curl -X POST http://localhost:4444/auth/register -H "Content-Type: application/json"',
        "request_body": '{"email":"testuser@example.com","password":"TestPass123","full_name":"Test User"}',
        "expected_status": 201,
        "expected_response": "User created successfully with personal team",
        "test_steps": [
            "1. Execute the cURL command with test user data",
            "2. Verify HTTP status code is 201", 
            "3. Check response contains user ID and email",
            "4. Verify personal team was created for user",
            "5. Record exact response content"
        ],
        "validation": "Response should include user_id, email, and personal_team_id"
    },
    {
        "id": "AUTH-002", 
        "endpoint": "/auth/login",
        "method": "POST", 
        "description": "Email authentication login",
        "curl_command": 'curl -X POST http://localhost:4444/auth/login -H "Content-Type: application/json"',
        "request_body": '{"email":"admin@example.com","password":"changeme"}',
        "expected_status": 200,
        "expected_response": "JWT token returned in response",
        "test_steps": [
            "1. Use admin credentials from .env file",
            "2. Execute login request",
            "3. Verify HTTP 200 status code",
            "4. Check response contains 'token' field", 
            "5. Verify token is valid JWT format",
            "6. Save token for subsequent API tests"
        ],
        "validation": "Response must contain valid JWT token",
        "critical": True
    },
    {
        "id": "AUTH-003",
        "endpoint": "/auth/logout", 
        "method": "POST",
        "description": "User logout endpoint",
        "curl_command": 'curl -X POST http://localhost:4444/auth/logout -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "Logout successful, token invalidated",
        "test_steps": [
            "1. Use JWT token from login test",
            "2. Execute logout request with Authorization header",
            "3. Verify HTTP 200 status",
            "4. Try using the token again (should fail)",
            "5. Verify token is now invalid"
        ],
        "validation": "Token becomes invalid after logout"
    },
    {
        "id": "AUTH-004",
        "endpoint": "/auth/refresh",
        "method": "POST", 
        "description": "JWT token refresh",
        "curl_command": 'curl -X POST http://localhost:4444/auth/refresh -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "New JWT token issued",
        "test_steps": [
            "1. Use valid JWT token",
            "2. Request token refresh",
            "3. Verify new token returned",
            "4. Test both old and new tokens",
            "5. Verify new token works, old may be invalidated"
        ],
        "validation": "New token returned and functional"
    },
    {
        "id": "AUTH-005",
        "endpoint": "/auth/profile",
        "method": "GET",
        "description": "Get user profile information", 
        "curl_command": 'curl http://localhost:4444/auth/profile -H "Authorization: Bearer <TOKEN>"',
        "request_body": "",
        "expected_status": 200,
        "expected_response": "User profile data including email, teams, roles",
        "test_steps": [
            "1. Use valid JWT token",
            "2. Request user profile",
            "3. Verify profile contains user email",
            "4. Check team membership information",
            "5. Verify role assignments if applicable"
        ],
        "validation": "Profile includes email, teams, and role data"
    },
    {
        "id": "AUTH-006",
        "endpoint": "/auth/change-password",
        "method": "POST",
        "description": "Change user password",
        "curl_command": 'curl -X POST http://localhost:4444/auth/change-password -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json"',
        "request_body": '{"old_password":"changeme","new_password":"NewPassword123"}',
        "expected_status": 200, 
        "expected_response": "Password updated successfully",
        "test_steps": [
            "1. Use current password as old_password",
            "2. Provide strong new password",
            "3. Execute password change request",
            "4. Verify success response",
            "5. Test login with new password",
            "6. IMPORTANT: Change password back for other tests"
        ],
        "validation": "Password change works, can login with new password"
    },
    {
        "id": "AUTH-007",
        "endpoint": "/auth/sso/github", 
        "method": "GET",
        "description": "GitHub SSO authentication initiation",
        "curl_command": 'curl -I http://localhost:4444/auth/sso/github',
        "request_body": "",
        "expected_status": 302,
        "expected_response": "Redirect to GitHub OAuth authorization",
        "test_steps": [
            "1. Execute request to GitHub SSO endpoint",
            "2. Verify HTTP 302 redirect status",
            "3. Check Location header contains github.com",
            "4. Verify OAuth parameters in redirect URL",
            "5. Note: Full OAuth flow requires GitHub app setup"
        ],
        "validation": "Redirects to GitHub OAuth (if SSO enabled)",
        "requires_config": "SSO_GITHUB_ENABLED=true, GitHub OAuth app"
    },
    {
        "id": "AUTH-008",
        "endpoint": "/auth/sso/google",
        "method": "GET", 
        "description": "Google SSO authentication initiation",
        "curl_command": 'curl -I http://localhost:4444/auth/sso/google',
        "request_body": "",
        "expected_status": 302,
        "expected_response": "Redirect to Google OAuth authorization", 
        "test_steps": [
            "1. Execute request to Google SSO endpoint",
            "2. Verify HTTP 302 redirect status",
            "3. Check Location header contains accounts.google.com",
            "4. Verify OAuth parameters in redirect URL",
            "5. Note: Full OAuth flow requires Google OAuth app"
        ],
        "validation": "Redirects to Google OAuth (if SSO enabled)",
        "requires_config": "SSO_GOOGLE_ENABLED=true, Google OAuth app"
    },
    {
        "id": "AUTH-009",
        "endpoint": "/auth/verify-email",
        "method": "POST",
        "description": "Email address verification",
        "curl_command": 'curl -X POST http://localhost:4444/auth/verify-email -H "Content-Type: application/json"',
        "request_body": '{"token":"<verification-token>"}',
        "expected_status": 200,
        "expected_response": "Email verified successfully", 
        "test_steps": [
            "1. Register new user first (to get verification token)",
            "2. Check email for verification token (if email configured)",
            "3. Use token in verification request",
            "4. Verify email verification status updated",
            "5. Check user can now perform email-verified actions"
        ],
        "validation": "Email verification updates user status",
        "requires_config": "Email delivery configured"
    },
    {
        "id": "AUTH-010",
        "endpoint": "/auth/forgot-password",
        "method": "POST",
        "description": "Password reset request",
        "curl_command": 'curl -X POST http://localhost:4444/auth/forgot-password -H "Content-Type: application/json"',
        "request_body": '{"email":"admin@example.com"}',
        "expected_status": 200,
        "expected_response": "Password reset email sent",
        "test_steps": [
            "1. Request password reset for known user",
            "2. Verify HTTP 200 response",
            "3. Check email for reset link (if email configured)", 
            "4. Test reset token functionality",
            "5. Verify password can be reset via token"
        ],
        "validation": "Password reset process initiated",
        "requires_config": "Email delivery configured"
    }
]


def run_auth_tests():
    """Run all authentication tests."""
    
    print("🔐 AUTHENTICATION API TESTING")
    print("=" * 60)
    print("🎯 Testing all authentication endpoints")
    
    # Get base URL and setup
    base_url = "http://localhost:4444"
    results = []
    
    print("\\n🔧 Pre-test Setup:")
    print("1. Ensure MCP Gateway is running (make dev)")
    print("2. Ensure migration completed successfully")
    print("3. Have admin credentials from .env file ready")
    
    input("\\nPress Enter when ready to begin testing...")
    
    for test in AUTH_TESTS:
        print(f"\\n{'='*60}")
        print(f"🧪 TEST {test['id']}: {test['endpoint']}")
        print(f"Method: {test['method']}")
        print(f"Description: {test['description']}")
        
        if test.get('critical'):
            print("🚨 CRITICAL TEST")
        
        if test.get('requires_config'):
            print(f"⚠️ Requires: {test['requires_config']}")
        
        print(f"\\n📋 Test Steps:")
        for step in test['test_steps']:
            print(f"   {step}")
        
        print(f"\\n💻 cURL Command:")
        print(f"   {test['curl_command']}")
        if test['request_body']:
            print(f"   Data: {test['request_body']}")
        
        print(f"\\n✅ Expected:")
        print(f"   Status: {test['expected_status']}")
        print(f"   Response: {test['expected_response']}")
        
        # Manual execution
        response = input(f"\\nExecute test {test['id']}? (y/n/skip): ").lower()
        
        if response == 'skip' or response == 's':
            print(f"⚠️ {test['id']}: SKIPPED")
            results.append({"id": test['id'], "status": "SKIP", "timestamp": datetime.now().isoformat()})
            continue
        elif response != 'y':
            print(f"❌ {test['id']}: ABORTED")
            break
        
        # Get actual results from user
        print(f"\\n📝 Record Results:")
        actual_status = input("Actual HTTP status code: ")
        actual_response = input("Actual response (summary): ")
        
        # Determine pass/fail
        expected_str = str(test['expected_status'])
        passed = actual_status == expected_str
        status = "PASS" if passed else "FAIL"
        
        print(f"\\n{'✅' if passed else '❌'} {test['id']}: {status}")
        
        if not passed and test.get('critical'):
            print("🚨 CRITICAL TEST FAILED!")
            continue_testing = input("Continue with remaining tests? (y/N): ").lower()
            if continue_testing != 'y':
                break
        
        # Record result
        results.append({
            "id": test['id'],
            "endpoint": test['endpoint'],
            "status": status,
            "expected_status": test['expected_status'],
            "actual_status": actual_status,
            "actual_response": actual_response,
            "timestamp": datetime.now().isoformat()
        })
    
    # Generate summary
    generate_auth_summary(results)
    return results


def generate_auth_summary(results):
    """Generate authentication test summary."""
    
    print(f"\\n{'='*60}")
    print("📊 AUTHENTICATION API TEST SUMMARY")
    print("=" * 60)
    
    passed = len([r for r in results if r['status'] == 'PASS'])
    failed = len([r for r in results if r['status'] == 'FAIL'])
    skipped = len([r for r in results if r['status'] == 'SKIP'])
    total = len(results)
    
    print(f"📈 Results:")
    print(f"   ✅ Passed: {passed}/{total}")
    print(f"   ❌ Failed: {failed}/{total}") 
    print(f"   ⚠️ Skipped: {skipped}/{total}")
    
    if failed == 0:
        print(f"\\n🎉 ALL AUTHENTICATION TESTS PASSED!")
        print("✅ Authentication system fully functional")
    else:
        print(f"\\n⚠️ SOME AUTHENTICATION TESTS FAILED")
        print("🔧 Review failed tests before production deployment")
    
    # Save results
    results_file = Path("tests/manual/auth_test_results.json")
    with open(results_file, 'w') as f:
        json.dump({
            "summary": {"passed": passed, "failed": failed, "skipped": skipped, "total": total},
            "results": results,
            "timestamp": datetime.now().isoformat()
        }, f, indent=2)
    
    print(f"\\n📄 Results saved: {results_file}")


def test_specific_endpoint(endpoint):
    """Test a specific authentication endpoint."""
    
    test = next((t for t in AUTH_TESTS if t['endpoint'] == endpoint), None)
    
    if not test:
        print(f"❌ Endpoint {endpoint} not found in test suite")
        available = [t['endpoint'] for t in AUTH_TESTS]
        print(f"Available endpoints: {available}")
        return False
    
    print(f"🧪 TESTING SPECIFIC ENDPOINT: {endpoint}")
    print("=" * 50)
    print(f"Test ID: {test['id']}")
    print(f"Method: {test['method']}")
    print(f"Description: {test['description']}")
    
    print(f"\\n💻 cURL Command:")
    print(f"{test['curl_command']}")
    if test['request_body']:
        print(f"Data: {test['request_body']}")
    
    print(f"\\n📋 Test Steps:")
    for step in test['test_steps']:
        print(f"   {step}")
    
    print(f"\\n✅ Expected:")
    print(f"   Status: {test['expected_status']}")
    print(f"   Response: {test['expected_response']}")
    
    return True


def list_all_endpoints():
    """List all authentication endpoints."""
    
    print("📋 ALL AUTHENTICATION ENDPOINTS")
    print("=" * 50)
    
    for test in AUTH_TESTS:
        critical_marker = " 🚨 CRITICAL" if test.get('critical') else ""
        config_marker = f" ⚠️ Requires: {test.get('requires_config')}" if test.get('requires_config') else ""
        
        print(f"\\n{test['id']}: {test['endpoint']} ({test['method']}){critical_marker}{config_marker}")
        print(f"   Description: {test['description']}")
        print(f"   Expected: {test['expected_status']} - {test['expected_response']}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help":
            print("🔐 Authentication API Tests")
            print("Usage:")
            print("  python3 tests/manual/api_authentication_tests.py                    # Run all tests")
            print("  python3 tests/manual/api_authentication_tests.py --endpoint <path>  # Test specific endpoint") 
            print("  python3 tests/manual/api_authentication_tests.py --list             # List all endpoints")
            print("  python3 tests/manual/api_authentication_tests.py --help             # This help")
        elif sys.argv[1] == "--list":
            list_all_endpoints()
        elif sys.argv[1] == "--endpoint" and len(sys.argv) > 2:
            test_specific_endpoint(sys.argv[2])
        else:
            print("❌ Unknown option. Use --help for usage.")
    else:
        # Run all authentication tests
        try:
            print("🔐 Starting authentication API testing...")
            results = run_auth_tests()
            print("\\n🎉 Authentication testing complete!")
            print("Next: python3 tests/manual/api_teams_tests.py")
        except KeyboardInterrupt:
            print("\\n❌ Testing cancelled by user")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Testing error: {e}")
            sys.exit(1)