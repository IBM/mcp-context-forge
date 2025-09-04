#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Gateway v0.7.0 - Migration Validation Tests

Critical post-migration validation tests to ensure the v0.6.0 → v0.7.0
upgrade completed successfully and old servers are now visible.

Usage:
    python3 tests/manual/migration_tests.py
    python3 tests/manual/migration_tests.py --run-all
"""

import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Migration test cases
MIGRATION_TESTS = [
    {
        "id": "MIG-001",
        "priority": "CRITICAL", 
        "component": "Admin User Creation",
        "description": "Verify platform admin user was created during migration",
        "steps": [
            "1. Check expected admin email from configuration:",
            '   python3 -c "from mcpgateway.config import settings; print(f\'Expected admin: {settings.platform_admin_email}\')"',
            "2. Check actual admin user in database:",
            '   python3 -c "from mcpgateway.db import SessionLocal, EmailUser; db=SessionLocal(); admin=db.query(EmailUser).filter(EmailUser.is_admin==True).first(); print(f\'Found admin: {admin.email if admin else None}, is_admin: {admin.is_admin if admin else False}\'); db.close()"',
            "3. Compare expected vs actual results",
            "4. Record both outputs exactly"
        ],
        "expected": "Expected admin email matches found admin email, is_admin=True",
        "validation_command": 'python3 -c "from mcpgateway.config import settings; from mcpgateway.db import SessionLocal, EmailUser; db=SessionLocal(); admin=db.query(EmailUser).filter(EmailUser.email==settings.platform_admin_email, EmailUser.is_admin==True).first(); result = \'PASS\' if admin else \'FAIL\'; print(f\'Result: {result} - Admin {settings.platform_admin_email} exists: {admin is not None}\'); db.close()"'
    },
    {
        "id": "MIG-002",
        "priority": "CRITICAL",
        "component": "Personal Team Creation", 
        "description": "Verify admin user has personal team created automatically",
        "steps": [
            "1. Run the verification script:",
            "   python3 scripts/verify_multitenancy_0_7_0_migration.py",
            "2. Look for 'PERSONAL TEAM CHECK' section in the output",
            "3. Record the team ID, name, and slug shown", 
            "4. Verify there are no error messages",
            "5. Note team visibility (should be 'private')"
        ],
        "expected": "✅ Personal team found: <Name> (Team ID: <uuid>, Slug: <slug>, Visibility: private)",
        "validation_command": 'python3 -c "from mcpgateway.db import SessionLocal, EmailTeam, EmailUser; from mcpgateway.config import settings; db=SessionLocal(); admin=db.query(EmailUser).filter(EmailUser.email==settings.platform_admin_email).first(); team=db.query(EmailTeam).filter(EmailTeam.created_by==settings.platform_admin_email, EmailTeam.is_personal==True).first() if admin else None; result = \'PASS\' if team else \'FAIL\'; print(f\'Result: {result} - Personal team exists: {team is not None}\'); db.close()"'
    },
    {
        "id": "MIG-003", 
        "priority": "CRITICAL",
        "component": "Server Visibility Fix",
        "description": "OLD SERVERS NOW VISIBLE - This is the main issue being fixed",
        "steps": [
            "1. Open web browser (Chrome or Firefox recommended)",
            "2. Navigate to: http://localhost:4444/admin", 
            "3. Login using admin email and password from your .env file",
            "4. Click 'Virtual Servers' in the navigation menu",
            "5. Count the total number of servers displayed",
            "6. Look for servers with older creation dates (pre-migration)", 
            "7. Click on each server to verify details are accessible",
            "8. Take screenshot of the server list showing all servers",
            "9. Record server names, creation dates, and visibility"
        ],
        "expected": "ALL pre-migration servers visible in admin UI server list, details accessible",
        "validation_command": 'python3 -c "from mcpgateway.db import SessionLocal, Server; db=SessionLocal(); total=db.query(Server).count(); with_teams=db.query(Server).filter(Server.team_id!=None).count(); print(f\'Server visibility: {with_teams}/{total} servers have team assignments\'); result = \'PASS\' if with_teams == total else \'FAIL\'; print(f\'Result: {result}\'); db.close()"',
        "main_test": True,
        "screenshot_required": True
    },
    {
        "id": "MIG-004",
        "priority": "CRITICAL", 
        "component": "Resource Team Assignment",
        "description": "All resources assigned to teams (no NULL team_id values)",
        "steps": [
            "1. In admin UI, navigate to Tools section",
            "2. Click on any tool to view its details",
            "3. Verify 'Team' field shows a team name (not empty or NULL)",
            "4. Verify 'Owner' field shows the admin email address", 
            "5. Verify 'Visibility' field has a value (private/team/public)",
            "6. Repeat this check for Resources and Prompts sections",
            "7. Run database verification command to check for NULL team assignments",
            "8. Record the count of unassigned resources"
        ],
        "expected": "All resources show Team/Owner/Visibility, database query shows 0 unassigned",
        "validation_command": 'python3 -c "from mcpgateway.db import SessionLocal, Tool, Resource, Prompt; db=SessionLocal(); tool_null=db.query(Tool).filter(Tool.team_id==None).count(); res_null=db.query(Resource).filter(Resource.team_id==None).count(); prompt_null=db.query(Prompt).filter(Prompt.team_id==None).count(); total_null=tool_null+res_null+prompt_null; print(f\'Unassigned resources: Tools={tool_null}, Resources={res_null}, Prompts={prompt_null}, Total={total_null}\'); result = \'PASS\' if total_null == 0 else \'FAIL\'; print(f\'Result: {result}\'); db.close()"'
    },
    {
        "id": "MIG-005",
        "priority": "CRITICAL",
        "component": "Email Authentication",
        "description": "Email-based authentication functional after migration",
        "steps": [
            "1. Open new private/incognito browser window",
            "2. Navigate to http://localhost:4444/admin",
            "3. Look for email login form or 'Email Login' option",
            "4. Enter the admin email address from your .env file",
            "5. Enter the admin password from your .env file", 
            "6. Click the Login/Submit button",
            "7. Verify successful redirect to admin dashboard",
            "8. Check that user menu/profile shows the correct email address"
        ],
        "expected": "Email authentication successful, dashboard loads, correct email displayed in UI",
        "validation_command": 'curl -s -X POST http://localhost:4444/auth/login -H "Content-Type: application/json" -d \'{"email":"admin@example.com","password":"changeme"}\' | python3 -c "import json, sys; data=json.load(sys.stdin); print(f\'Email auth result: {\"PASS\" if \"token\" in data else \"FAIL\"} - Token present: {\"token\" in data}\')"'
    },
    {
        "id": "MIG-006",
        "priority": "HIGH",
        "component": "Basic Auth Compatibility", 
        "description": "Basic authentication still works alongside email auth",
        "steps": [
            "1. Open a new browser window (not incognito)",
            "2. Navigate to http://localhost:4444/admin",
            "3. When browser prompts for authentication, use basic auth:",
            "   Username: admin",
            "   Password: changeme", 
            "4. Verify access is granted to admin interface",
            "5. Navigate to different admin sections to test functionality",
            "6. Confirm no conflicts with email authentication"
        ],
        "expected": "Basic auth continues to work, no conflicts with email auth system",
        "validation_command": 'curl -s -u admin:changeme http://localhost:4444/admin/teams | python3 -c "import json, sys; try: data=json.load(sys.stdin); print(\'Basic auth result: PASS - API accessible\'); except: print(\'Basic auth result: FAIL - API not accessible\')"'
    },
    {
        "id": "MIG-007",
        "priority": "HIGH",
        "component": "Database Schema Validation",
        "description": "All multitenancy tables created with proper structure",
        "steps": [
            "1. Check multitenancy tables exist:",
            "   SQLite: sqlite3 mcp.db '.tables' | grep email",
            "   PostgreSQL: psql -d mcp -c '\\\\dt' | grep email",
            "2. Verify required tables: email_users, email_teams, email_team_members, roles, user_roles",
            "3. Check table row counts:",
            '   python3 -c "from mcpgateway.db import SessionLocal, EmailUser, EmailTeam; db=SessionLocal(); users=db.query(EmailUser).count(); teams=db.query(EmailTeam).count(); print(f\'Users: {users}, Teams: {teams}\'); db.close()"',
            "4. Test foreign key relationships work properly"
        ],
        "expected": "All multitenancy tables exist with proper data and working relationships",
        "validation_command": 'python3 -c "from mcpgateway.db import SessionLocal, EmailUser, EmailTeam, EmailTeamMember; db=SessionLocal(); users=db.query(EmailUser).count(); teams=db.query(EmailTeam).count(); members=db.query(EmailTeamMember).count(); result = \'PASS\' if users > 0 and teams > 0 and members > 0 else \'FAIL\'; print(f\'Schema validation: {result} - Users: {users}, Teams: {teams}, Members: {members}\'); db.close()"'
    },
    {
        "id": "MIG-008",
        "priority": "HIGH", 
        "component": "Team Membership Validation",
        "description": "Admin user properly added to personal team as owner",
        "steps": [
            "1. In admin UI, navigate to the Teams section",
            "2. Find the personal team (usually named '<Admin Name>'s Team')",
            "3. Click on the personal team to view its details", 
            "4. Click 'View Members' or 'Members' tab",
            "5. Verify admin user is listed with role 'Owner'",
            "6. Check the join date is recent (around migration execution time)",
            "7. Test basic team management functions"
        ],
        "expected": "Admin user listed as Owner in personal team with recent join date",
        "validation_command": 'python3 -c "from mcpgateway.db import SessionLocal, EmailTeamMember, EmailUser; from mcpgateway.config import settings; db=SessionLocal(); admin=db.query(EmailUser).filter(EmailUser.email==settings.platform_admin_email).first(); membership=db.query(EmailTeamMember).filter(EmailTeamMember.user_email==settings.platform_admin_email, EmailTeamMember.role==\'owner\').first() if admin else None; result = \'PASS\' if membership else \'FAIL\'; print(f\'Team membership: {result} - Admin is owner: {membership is not None}\'); db.close()"'
    },
    {
        "id": "MIG-009",
        "priority": "MEDIUM",
        "component": "API Functionality Validation", 
        "description": "Core APIs respond correctly after migration",
        "steps": [
            "1. Test health endpoint:",
            "   curl http://localhost:4444/health",
            "2. Get authentication token:",
            '   curl -X POST http://localhost:4444/auth/login -H "Content-Type: application/json" -d \'{"email":"<admin-email>","password":"<admin-password>"}\'',
            "3. Test teams API with the token:",
            '   curl -H "Authorization: Bearer <token>" http://localhost:4444/teams',
            "4. Test servers API:",
            '   curl -H "Authorization: Bearer <token>" http://localhost:4444/servers',
            "5. Record all HTTP status codes and response content"
        ],
        "expected": "Health=200, Login=200 with JWT token, Teams=200 with team data, Servers=200 with server data",
        "validation_command": 'curl -s http://localhost:4444/health | python3 -c "import json, sys; data=json.load(sys.stdin); print(f\'Health check: {\"PASS\" if data.get(\"status\") == \"ok\" else \"FAIL\"} - Status: {data.get(\"status\")}\') if isinstance(data, dict) else print(\'Health check: FAIL - Invalid response\')"'
    },
    {
        "id": "MIG-010",
        "priority": "MEDIUM", 
        "component": "Post-Migration Resource Creation",
        "description": "New resources created after migration get proper team assignments",
        "steps": [
            "1. In admin UI, navigate to Tools section",
            "2. Click 'Create Tool' or 'Add Tool' button",
            "3. Fill in tool details:",
            "   Name: 'Post-Migration Test Tool'",
            "   Description: 'Tool created after v0.7.0 migration'",
            "   Visibility: 'Team'", 
            "4. Save the new tool",
            "5. Verify tool appears in the tools list",
            "6. Check tool details show automatic team assignment",
            "7. Delete the test tool when validation is complete"
        ],
        "expected": "New tool created successfully with automatic team assignment to creator's team",
        "validation_command": "# Manual test - check via UI that new resources get team assignments"
    }
]


def run_migration_validation():
    """Run interactive migration validation."""
    
    print("🔄 MCP GATEWAY MIGRATION VALIDATION")
    print("=" * 60) 
    print("🎯 Purpose: Validate v0.6.0 → v0.7.0 migration success")
    print("🚨 Critical: These tests must pass for production use")
    
    results = []
    
    print("\\n📋 MIGRATION TEST EXECUTION")
    
    for test in MIGRATION_TESTS:
        print(f"\\n{'='*60}")
        print(f"🧪 TEST {test['id']}: {test['component']}")
        print(f"Priority: {test['priority']}")
        print(f"Description: {test['description']}")
        
        if test.get('main_test'):
            print("🎯 THIS IS THE MAIN MIGRATION TEST!")
        
        print(f"\\n📋 Test Steps:")
        for step in test['steps']:
            print(f"   {step}")
        
        print(f"\\n✅ Expected Result:")
        print(f"   {test['expected']}")
        
        # Run validation command if available
        if 'validation_command' in test and not test['validation_command'].startswith('#'):
            print(f"\\n🔍 Running automated validation...")
            try:
                result = subprocess.run(test['validation_command'], shell=True, 
                                      capture_output=True, text=True, timeout=30)
                print(f"   Validation output: {result.stdout.strip()}")
                if result.stderr:
                    print(f"   Validation errors: {result.stderr.strip()}")
            except subprocess.TimeoutExpired:
                print("   ⚠️ Validation timeout")
            except Exception as e:
                print(f"   ❌ Validation error: {e}")
        
        # Get user confirmation
        print(f"\\n📝 Manual Verification Required:")
        response = input(f"Did test {test['id']} PASS? (y/n/skip): ").lower()
        
        if response == 'y':
            status = "PASS"
            print(f"✅ {test['id']}: PASSED")
        elif response == 'n':
            status = "FAIL"
            print(f"❌ {test['id']}: FAILED")
            if test['priority'] == 'CRITICAL':
                print(f"🚨 CRITICAL TEST FAILED!")
                print(f"🛑 Migration may not be successful")
                break_early = input("Continue with remaining tests? (y/N): ").lower()
                if break_early != 'y':
                    break
        else:
            status = "SKIP"
            print(f"⚠️ {test['id']}: SKIPPED")
        
        # Record result
        result_data = {
            "test_id": test['id'],
            "component": test['component'],
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "priority": test['priority']
        }
        
        if response == 'n':  # Failed test
            details = input("Please describe what failed: ")
            result_data['failure_details'] = details
        
        results.append(result_data)
    
    # Generate summary
    generate_test_summary(results)
    
    return results


def generate_test_summary(results):
    """Generate test execution summary."""
    
    print(f"\\n{'='*60}")
    print("📊 MIGRATION VALIDATION SUMMARY")
    print("=" * 60)
    
    # Count results
    passed = len([r for r in results if r['status'] == 'PASS'])
    failed = len([r for r in results if r['status'] == 'FAIL'])
    skipped = len([r for r in results if r['status'] == 'SKIP'])
    total = len(results)
    
    print(f"📈 Test Results:")
    print(f"   ✅ Passed: {passed}/{total}")
    print(f"   ❌ Failed: {failed}/{total}")
    print(f"   ⚠️ Skipped: {skipped}/{total}")
    
    # Check critical tests
    critical_results = [r for r in results if r['priority'] == 'CRITICAL']
    critical_passed = len([r for r in critical_results if r['status'] == 'PASS'])
    critical_total = len(critical_results)
    
    print(f"\\n🚨 Critical Test Results:")
    print(f"   ✅ Critical Passed: {critical_passed}/{critical_total}")
    
    # Overall assessment
    if failed == 0 and critical_passed == critical_total:
        print(f"\\n🎉 MIGRATION VALIDATION: SUCCESS!")
        print("✅ All critical tests passed")
        print("✅ Migration completed successfully") 
        print("✅ Ready for production use")
    elif critical_passed == critical_total:
        print(f"\\n⚠️ MIGRATION VALIDATION: PARTIAL SUCCESS")
        print("✅ All critical tests passed")
        print("⚠️ Some non-critical tests failed")
        print("💡 Review failed tests but migration core is successful")
    else:
        print(f"\\n❌ MIGRATION VALIDATION: FAILED")
        print("❌ Critical tests failed")
        print("🛑 Migration may not be successful")
        print("🔧 Please investigate failures before production use")
    
    # Save results
    save_results(results)


def save_results(results):
    """Save test results to file."""
    
    results_file = Path("tests/manual/migration_test_results.json")
    
    summary = {
        "test_execution": {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(results),
            "passed": len([r for r in results if r['status'] == 'PASS']),
            "failed": len([r for r in results if r['status'] == 'FAIL']),
            "skipped": len([r for r in results if r['status'] == 'SKIP'])
        },
        "test_results": results
    }
    
    with open(results_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\\n📄 Results saved: {results_file}")


def list_all_tests():
    """List all migration tests."""
    
    print("📋 ALL MIGRATION VALIDATION TESTS")
    print("=" * 50)
    
    for test in MIGRATION_TESTS:
        priority_indicator = "🚨" if test['priority'] == 'CRITICAL' else "🔧" if test['priority'] == 'HIGH' else "📝"
        main_indicator = " 🎯 MAIN TEST" if test.get('main_test') else ""
        
        print(f"\\n{test['id']}: {test['component']} {priority_indicator}{main_indicator}")
        print(f"   Priority: {test['priority']}")
        print(f"   Description: {test['description']}")
        print(f"   Expected: {test['expected']}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help":
            print("📋 Migration Validation Tests")
            print("Usage:")
            print("  python3 tests/manual/migration_tests.py           # Interactive testing")
            print("  python3 tests/manual/migration_tests.py --list    # List all tests") 
            print("  python3 tests/manual/migration_tests.py --help    # This help")
        elif sys.argv[1] == "--list":
            list_all_tests()
        elif sys.argv[1] == "--run-all":
            print("🚀 Running all migration tests...")
            run_migration_validation()
        else:
            print("❌ Unknown option. Use --help for usage.")
    else:
        # Interactive mode
        print("🔄 Starting interactive migration validation...")
        print("💡 Tip: Use --list to see all tests first")
        
        try:
            results = run_migration_validation()
            print("\\n🎉 Migration validation complete!")
        except KeyboardInterrupt:
            print("\\n❌ Testing cancelled by user")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Testing error: {e}")
            sys.exit(1)