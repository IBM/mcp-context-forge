#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Gateway v0.7.0 - Security & Penetration Tests

Security testing including attack scenarios:
- SQL injection attempts
- Authentication bypass
- Authorization violations
- XSS and CSRF attacks
- Input validation testing

Usage:
    python3 tests/manual/security_tests.py
    python3 tests/manual/security_tests.py --attack-type sql-injection
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

# Security test scenarios
SECURITY_TESTS = [
    {
        "id": "SEC-001",
        "attack_type": "SQL Injection",
        "target": "Teams API",
        "risk_level": "Critical",
        "description": "Attempt SQL injection via team creation",
        "attack_steps": [
            "1. Get valid JWT token from admin login",
            "2. Prepare malicious team name with SQL injection:",
            '   {"name":"\'; DROP TABLE users; --","description":"injection test"}',
            "3. Execute attack:",
            '   curl -X POST http://localhost:4444/teams -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d \'{"name":"\\"; DROP TABLE users; --","description":"test"}\'',
            "4. Check database integrity:",
            "   sqlite3 mcp.db '.tables' (verify users table still exists)",
            "5. Check error response handling"
        ],
        "expected_defense": "Input sanitized, parameterized queries prevent injection, error handled gracefully",
        "validation": "Database remains intact, no SQL executed, proper error returned"
    },
    {
        "id": "SEC-002",
        "attack_type": "JWT Token Manipulation", 
        "target": "Authentication System",
        "risk_level": "Critical",
        "description": "Attempt to manipulate JWT token claims",
        "attack_steps": [
            "1. Obtain valid JWT token through normal login",
            "2. Decode JWT payload (use jwt.io or similar tool)",
            "3. Modify claims (e.g., change user email, add admin role)",
            "4. Re-encode JWT with different signature", 
            "5. Attempt to use modified token:",
            '   curl -H "Authorization: Bearer <MODIFIED_TOKEN>" http://localhost:4444/admin/users',
            "6. Verify access is denied"
        ],
        "expected_defense": "Token signature validation prevents tampering, access denied",
        "validation": "Modified tokens rejected, signature verification works"
    },
    {
        "id": "SEC-003",
        "attack_type": "Team Isolation Bypass",
        "target": "Multi-tenancy Authorization",
        "risk_level": "Critical", 
        "description": "Attempt to access resources from other teams",
        "attack_steps": [
            "1. Create two test users in different teams",
            "2. User A creates a private resource in Team 1",
            "3. Get User B's JWT token",
            "4. User B attempts to access User A's resource:",
            '   curl -H "Authorization: Bearer <USER_B_TOKEN>" http://localhost:4444/resources/{USER_A_RESOURCE_ID}',
            "5. Verify access is denied",
            "6. Test with direct resource ID guessing"
        ],
        "expected_defense": "Team boundaries strictly enforced, cross-team access blocked",
        "validation": "Access denied, team isolation maintained"
    },
    {
        "id": "SEC-004",
        "attack_type": "Privilege Escalation",
        "target": "RBAC System",
        "risk_level": "Critical",
        "description": "Attempt to elevate privileges or access admin functions",
        "attack_steps": [
            "1. Login as regular user (non-admin)",
            "2. Attempt to access admin-only endpoints:", 
            '   curl -H "Authorization: Bearer <USER_TOKEN>" http://localhost:4444/admin/users',
            "3. Try to modify own user role in database",
            "4. Attempt direct admin API calls",
            "5. Test admin UI access with regular user"
        ],
        "expected_defense": "Admin privileges protected, privilege escalation prevented",
        "validation": "Admin functions inaccessible to regular users"
    },
    {
        "id": "SEC-005",
        "attack_type": "Cross-Site Scripting (XSS)",
        "target": "Admin UI",
        "risk_level": "High",
        "description": "Attempt script injection in web interface",
        "attack_steps": [
            "1. Access admin UI with valid credentials",
            "2. Create tool with malicious name:",
            '   Name: <script>alert("XSS Test")</script>',
            "3. Save tool and navigate to tools list",
            "4. Check if JavaScript executes in browser",
            "5. Test other input fields for XSS vulnerabilities",
            "6. Check browser console for script execution"
        ],
        "expected_defense": "Script tags escaped or sanitized, no JavaScript execution",
        "validation": "No alert boxes, scripts properly escaped in HTML"
    },
    {
        "id": "SEC-006",
        "attack_type": "Cross-Site Request Forgery (CSRF)",
        "target": "State-Changing Operations", 
        "risk_level": "High",
        "description": "Attempt CSRF attack on admin operations",
        "attack_steps": [
            "1. Create malicious HTML page with form posting to gateway",
            "2. Form targets state-changing endpoint (e.g., team creation)",
            "3. Get authenticated user to visit malicious page",
            "4. Check if operation executes without user consent",
            "5. Verify CSRF token requirements",
            "6. Test cross-origin request blocking"
        ],
        "expected_defense": "CSRF tokens required, cross-origin requests properly blocked",
        "validation": "Operations require explicit user consent and CSRF protection"
    },
    {
        "id": "SEC-007",
        "attack_type": "Brute Force Attack",
        "target": "Login Endpoint",
        "risk_level": "Medium", 
        "description": "Attempt password brute force attack",
        "attack_steps": [
            "1. Script multiple rapid login attempts with wrong passwords:",
            '   for i in {1..10}; do curl -X POST http://localhost:4444/auth/login -d \'{"email":"admin@example.com","password":"wrong$i"}\'; done',
            "2. Monitor response times and status codes",
            "3. Check for rate limiting implementation",
            "4. Test account lockout after failed attempts",
            "5. Verify lockout duration enforcement"
        ],
        "expected_defense": "Account locked after multiple failures, rate limiting enforced",
        "validation": "Brute force attacks mitigated by lockout and rate limiting"
    },
    {
        "id": "SEC-008",
        "attack_type": "File Upload Attack",
        "target": "Resource Management",
        "risk_level": "High",
        "description": "Attempt to upload malicious files",
        "attack_steps": [
            "1. Try uploading executable file (.exe, .sh)",
            "2. Attempt script file upload (.py, .js, .php)",
            "3. Test oversized file upload", 
            "4. Try files with malicious names",
            "5. Attempt path traversal in filenames (../../../etc/passwd)",
            "6. Check file type and size validation"
        ],
        "expected_defense": "File type validation, size limits enforced, path sanitization",
        "validation": "Malicious uploads blocked, validation errors returned"
    },
    {
        "id": "SEC-009",
        "attack_type": "API Rate Limiting",
        "target": "DoS Prevention",
        "risk_level": "Medium",
        "description": "Test API rate limiting and DoS protection", 
        "attack_steps": [
            "1. Script rapid API requests to test rate limiting:",
            '   for i in {1..100}; do curl -s http://localhost:4444/health; done',
            "2. Monitor response times and status codes",
            "3. Check for rate limit headers in responses",
            "4. Verify throttling and backoff mechanisms",
            "5. Test rate limiting on authenticated endpoints"
        ],
        "expected_defense": "Rate limits enforced, DoS protection active, proper HTTP status codes",
        "validation": "Rate limiting prevents abuse, service remains stable"
    },
    {
        "id": "SEC-010",
        "attack_type": "Information Disclosure",
        "target": "Error Handling", 
        "risk_level": "Medium",
        "description": "Check for sensitive information in error responses",
        "attack_steps": [
            "1. Trigger various error conditions:",
            "   - Invalid JSON syntax",
            "   - Missing required fields", 
            "   - Invalid authentication",
            "   - Access denied scenarios",
            "2. Analyze error messages for sensitive information",
            "3. Check for stack traces in responses",
            "4. Look for database connection strings",
            "5. Verify no internal paths or system info disclosed"
        ],
        "expected_defense": "No sensitive information disclosed in error responses",
        "validation": "Error messages are user-friendly without exposing system internals"
    }
]


def run_security_tests():
    """Run comprehensive security testing."""
    
    print("🛡️ SECURITY & PENETRATION TESTING")
    print("=" * 60)
    print("⚠️ WARNING: This performs actual attack scenarios")
    print("🎯 Purpose: Validate security defenses")
    
    print("\\n🔧 Security Testing Prerequisites:")
    print("1. Test environment (not production)")
    print("2. Database backup available") 
    print("3. MCP Gateway running")
    print("4. Valid admin credentials")
    
    proceed = input("\\nProceed with security testing? (yes/no): ").lower()
    if proceed != 'yes':
        print("❌ Security testing cancelled")
        return []
    
    results = []
    
    for test in SECURITY_TESTS:
        print(f"\\n{'='*60}")
        print(f"🛡️ SECURITY TEST {test['id']}")
        print(f"Attack Type: {test['attack_type']}")
        print(f"Target: {test['target']}")
        print(f"Risk Level: {test['risk_level']}")
        print(f"Description: {test['description']}")
        
        if test['risk_level'] == 'Critical':
            print("🚨 CRITICAL SECURITY TEST")
        
        print(f"\\n⚔️ Attack Steps:")
        for step in test['attack_steps']:
            print(f"   {step}")
        
        print(f"\\n🛡️ Expected Defense:")
        print(f"   {test['expected_defense']}")
        
        print(f"\\n✅ Validation Criteria:")
        print(f"   {test['validation']}")
        
        # Manual execution
        response = input(f"\\nExecute security test {test['id']}? (y/n/skip): ").lower()
        
        if response == 'skip':
            results.append({"id": test['id'], "status": "SKIP"})
            continue
        elif response == 'y':
            print("\\n🔍 Execute the attack steps above and observe results...")
            
            # Get results
            defense_worked = input("Did the expected defense work? (y/n): ").lower()
            vulnerability_found = input("Any vulnerability discovered? (y/n): ").lower()
            
            if defense_worked == 'y' and vulnerability_found == 'n':
                status = "PASS"
                print(f"✅ {test['id']}: Security defense PASSED")
            else:
                status = "FAIL" 
                print(f"❌ {test['id']}: Security vulnerability DETECTED")
                vuln_details = input("Describe the vulnerability: ")
                
                if test['risk_level'] == 'Critical':
                    print("🚨 CRITICAL VULNERABILITY FOUND!")
                    print("🛑 Do not deploy to production until fixed")
            
            # Record results
            result_data = {
                "id": test['id'],
                "attack_type": test['attack_type'],
                "risk_level": test['risk_level'],
                "status": status,
                "timestamp": datetime.now().isoformat()
            }
            
            if status == "FAIL":
                result_data['vulnerability_details'] = vuln_details
            
            results.append(result_data)
    
    # Generate security summary
    generate_security_summary(results)
    
    return results


def generate_security_summary(results):
    """Generate security test summary."""
    
    print(f"\\n{'='*60}")
    print("🛡️ SECURITY TEST SUMMARY") 
    print("=" * 60)
    
    passed = len([r for r in results if r['status'] == 'PASS'])
    failed = len([r for r in results if r['status'] == 'FAIL'])
    skipped = len([r for r in results if r['status'] == 'SKIP'])
    
    # Check by risk level
    critical_tests = [r for r in results if r.get('risk_level') == 'Critical']
    critical_passed = len([r for r in critical_tests if r['status'] == 'PASS'])
    
    print(f"📈 Security Test Results:")
    print(f"   ✅ Defenses Passed: {passed}/{len(results)}")
    print(f"   ❌ Vulnerabilities Found: {failed}/{len(results)}")
    print(f"   ⚠️ Tests Skipped: {skipped}/{len(results)}")
    
    print(f"\\n🚨 Critical Security Tests:")
    print(f"   ✅ Critical Defenses: {critical_passed}/{len(critical_tests)}")
    
    # Security assessment
    if failed == 0 and critical_passed == len(critical_tests):
        print(f"\\n🎉 SECURITY ASSESSMENT: EXCELLENT!")
        print("✅ All security defenses working") 
        print("✅ No vulnerabilities detected")
        print("✅ Ready for production deployment")
    elif critical_passed == len(critical_tests):
        print(f"\\n⚠️ SECURITY ASSESSMENT: GOOD")
        print("✅ Critical defenses working")
        print("⚠️ Some non-critical issues found")
        print("💡 Review non-critical findings")
    else:
        print(f"\\n❌ SECURITY ASSESSMENT: VULNERABLE")
        print("❌ Critical vulnerabilities detected")
        print("🛑 DO NOT DEPLOY TO PRODUCTION")
        print("🔧 Fix vulnerabilities before deployment")
    
    # Save results
    results_file = Path("tests/manual/security_test_results.json")
    with open(results_file, 'w') as f:
        json.dump({
            "summary": {
                "passed": passed,
                "failed": failed, 
                "skipped": skipped,
                "critical_passed": critical_passed,
                "critical_total": len(critical_tests)
            },
            "results": results,
            "timestamp": datetime.now().isoformat()
        }, f, indent=2)
    
    print(f"\\n📄 Security results saved: {results_file}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help":
            print("🛡️ Security & Penetration Tests")
            print("Usage:")
            print("  python3 tests/manual/security_tests.py                    # Run all security tests")
            print("  python3 tests/manual/security_tests.py --list             # List all tests")  
            print("  python3 tests/manual/security_tests.py --help             # This help")
            print("\\n⚠️ WARNING: These tests perform actual attack scenarios")
            print("🎯 Only run in test environments, never production")
        elif sys.argv[1] == "--list":
            print("🛡️ All Security Tests:")
            for test in SECURITY_TESTS:
                print(f"   {test['id']}: {test['attack_type']} ({test['risk_level']})")
                print(f"      Target: {test['target']}")
                print(f"      Description: {test['description']}")
        else:
            print("❌ Unknown option. Use --help")
    else:
        try:
            print("🛡️ Starting security testing...")
            print("⚠️ This will perform actual attack scenarios")
            results = run_security_tests()
            print("\\n🎉 Security testing complete!")
        except KeyboardInterrupt:
            print("\\n❌ Security testing cancelled")
        except Exception as e:
            print(f"❌ Error: {e}")
            sys.exit(1)