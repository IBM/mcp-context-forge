#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Gateway v0.7.0 - Admin UI Manual Tests

Comprehensive testing of the admin web interface including:
- Login and authentication
- Dashboard and navigation
- Server management UI (CRITICAL for migration validation)
- Team management interface
- User administration
- Export/import interface

Usage:
    python3 tests/manual/admin_ui_tests.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Admin UI test cases
ADMIN_UI_TESTS = [
    {
        "id": "UI-001",
        "section": "Authentication",
        "component": "Login Page",
        "action": "Test admin login interface",
        "steps": [
            "1. Open web browser (Chrome or Firefox recommended)",
            "2. Navigate to: http://localhost:4444/admin",
            "3. Observe login page layout and components",
            "4. Check for email and password input fields",
            "5. Look for 'Login' or 'Sign In' button",
            "6. Test form validation (empty fields)",
            "7. Enter admin email from .env file",
            "8. Enter admin password from .env file", 
            "9. Click Login button",
            "10. Verify successful redirect to admin dashboard"
        ],
        "expected": "Login page loads, form validation works, authentication successful",
        "browser": "Chrome/Firefox",
        "screenshot": "Optional",
        "critical": True
    },
    {
        "id": "UI-002", 
        "section": "Dashboard",
        "component": "Main Dashboard",
        "action": "Navigate and test admin dashboard",
        "steps": [
            "1. After successful login, observe dashboard layout",
            "2. Count the number of statistics cards displayed",
            "3. Check navigation menu on left side or top",
            "4. Click on each statistic card to test interactions",
            "5. Test responsive design (resize browser window)",
            "6. Check for any error messages or warnings",
            "7. Verify user menu/profile in top right",
            "8. Test logout functionality"
        ],
        "expected": "Dashboard functional with stats, navigation menu works, responsive design",
        "browser": "Chrome/Firefox",
        "screenshot": "Optional",
        "critical": False
    },
    {
        "id": "UI-003",
        "section": "Virtual Servers", 
        "component": "Server List View",
        "action": "View and verify server list - CRITICAL MIGRATION TEST",
        "steps": [
            "1. Click 'Virtual Servers' in navigation menu",
            "2. Observe server list/grid layout",
            "3. COUNT the total number of servers displayed", 
            "4. IDENTIFY servers created before migration (older creation dates)",
            "5. Click on each server card/row to view details",
            "6. Verify server information is accessible and complete",
            "7. Check server actions (start/stop/restart if available)",
            "8. Test server filtering and search if available",
            "9. TAKE SCREENSHOT of server list showing all servers",
            "10. Record server names and their visibility status"
        ],
        "expected": "ALL servers visible including pre-migration servers, details accessible",
        "browser": "Chrome/Firefox",
        "screenshot": "REQUIRED",
        "critical": True,
        "main_migration_test": True
    },
    {
        "id": "UI-004",
        "section": "Teams",
        "component": "Team Management Interface", 
        "action": "Test team management functionality",
        "steps": [
            "1. Navigate to 'Teams' section in admin interface",
            "2. View team list/grid display",
            "3. Find your personal team (usually '<Name>'s Team')", 
            "4. Click on personal team to view details",
            "5. Check team information display",
            "6. Click 'View Members' or 'Members' tab",
            "7. Verify you're listed as 'Owner'",
            "8. Test 'Create Team' functionality",
            "9. Fill out team creation form",
            "10. Verify new team appears in list"
        ],
        "expected": "Team interface functional, personal team visible, team creation works",
        "browser": "Chrome/Firefox", 
        "screenshot": "Optional",
        "critical": False
    },
    {
        "id": "UI-005",
        "section": "Tools",
        "component": "Tool Registry Interface",
        "action": "Test tool management and invocation",
        "steps": [
            "1. Navigate to 'Tools' section",
            "2. View available tools list",
            "3. Check team-based filtering is working",
            "4. Click on any tool to view details", 
            "5. Look for 'Invoke' or 'Execute' button",
            "6. Test tool invocation interface",
            "7. Fill in tool parameters if prompted",
            "8. Submit tool execution",
            "9. Verify results are displayed properly",
            "10. Test tool creation form if available"
        ],
        "expected": "Tools accessible by team permissions, invocation interface works",
        "browser": "Chrome/Firefox",
        "screenshot": "Optional", 
        "critical": False
    },
    {
        "id": "UI-006",
        "section": "Resources",
        "component": "Resource Management Interface",
        "action": "Test resource browser and management",
        "steps": [
            "1. Navigate to 'Resources' section",
            "2. Browse available resources",
            "3. Check team-based resource filtering",
            "4. Click on any resource to view details",
            "5. Test resource download functionality",
            "6. Try 'Upload Resource' button if available",
            "7. Test file upload interface",
            "8. Fill in resource metadata",
            "9. Verify upload completes successfully", 
            "10. Check new resource appears in list"
        ],
        "expected": "Resource browser functional, upload/download works, team filtering applied",
        "browser": "Chrome/Firefox",
        "screenshot": "Optional",
        "critical": False
    },
    {
        "id": "UI-007",
        "section": "User Management",
        "component": "User Administration Interface",
        "action": "Test user management (admin only)",
        "steps": [
            "1. Navigate to 'Users' section (admin only)",
            "2. View user list display",
            "3. Click on any user to view details",
            "4. Check user profile information",
            "5. Test 'Create User' functionality if available",
            "6. Fill user creation form",
            "7. Test role assignment interface",
            "8. Verify user permissions management",
            "9. Check user activity/audit information",
            "10. Test user status changes (active/inactive)"
        ],
        "expected": "User management interface functional, role assignment works",
        "browser": "Chrome/Firefox", 
        "screenshot": "Optional",
        "critical": False,
        "requires": "Platform admin privileges"
    },
    {
        "id": "UI-008",
        "section": "Export/Import",
        "component": "Configuration Management Interface",
        "action": "Test configuration backup and restore",
        "steps": [
            "1. Navigate to 'Export/Import' section",
            "2. Locate 'Export Configuration' button/link",
            "3. Click export and select export options",
            "4. Download the configuration JSON file",
            "5. Open JSON file and verify contents",
            "6. Locate 'Import Configuration' button/link",
            "7. Select the downloaded JSON file",
            "8. Choose import options (merge/replace)", 
            "9. Execute the import process",
            "10. Verify import completion and success"
        ],
        "expected": "Export downloads complete JSON, import processes successfully",
        "browser": "Chrome/Firefox",
        "screenshot": "Recommended",
        "critical": False
    },
    {
        "id": "UI-009",
        "section": "Mobile Compatibility",
        "component": "Responsive Design",
        "action": "Test mobile device compatibility",
        "steps": [
            "1. Resize browser window to mobile width (<768px)",
            "2. OR open admin UI on actual mobile device",
            "3. Test navigation menu (hamburger menu?)",
            "4. Check form input usability on mobile",
            "5. Test touch interactions and gestures",
            "6. Verify text readability and sizing",
            "7. Check all features remain accessible",
            "8. Test portrait and landscape orientations",
            "9. Verify no horizontal scrolling required",
            "10. Check mobile-specific UI adaptations"
        ],
        "expected": "Interface adapts to mobile screens while maintaining full functionality",
        "browser": "Mobile Chrome/Safari",
        "screenshot": "Optional",
        "critical": False
    },
    {
        "id": "UI-010",
        "section": "Error Handling",
        "component": "UI Error Scenarios",
        "action": "Test error handling and user experience",
        "steps": [
            "1. Trigger network error (disconnect internet briefly)",
            "2. Submit forms with invalid data",
            "3. Try accessing resources without permission",
            "4. Test session timeout scenarios", 
            "5. Check error message display",
            "6. Verify error messages are user-friendly",
            "7. Test error recovery mechanisms",
            "8. Check browser console for JavaScript errors",
            "9. Verify graceful degradation",
            "10. Test error logging and reporting"
        ],
        "expected": "Graceful error handling, helpful error messages, no JavaScript crashes",
        "browser": "Chrome/Firefox",
        "screenshot": "For errors",
        "critical": False
    }
]


def run_admin_ui_tests():
    """Run comprehensive admin UI tests."""
    
    print("🖥️ ADMIN UI COMPREHENSIVE TESTING")
    print("=" * 60)
    print("🎯 Testing every admin interface component")
    print("🚨 Includes critical migration validation (server visibility)")
    
    results = []
    
    print("\\n🔧 Pre-test Requirements:")
    print("1. MCP Gateway running (make dev)")
    print("2. Admin login credentials available")
    print("3. Browser with developer tools (F12)")
    
    input("\\nPress Enter when ready to begin UI testing...")
    
    for test in ADMIN_UI_TESTS:
        print(f"\\n{'='*60}")
        print(f"🧪 TEST {test['id']}: {test['component']}")
        print(f"Section: {test['section']}")
        print(f"Action: {test['action']}")
        
        if test.get('critical'):
            print("🚨 CRITICAL TEST")
        
        if test.get('main_migration_test'):
            print("🎯 MAIN MIGRATION VALIDATION TEST!")
        
        if test.get('requires'):
            print(f"⚠️ Requires: {test['requires']}")
        
        print(f"\\n📋 Detailed Steps:")
        for step in test['steps']:
            print(f"   {step}")
        
        print(f"\\n✅ Expected Result:")
        print(f"   {test['expected']}")
        
        print(f"\\n🌐 Browser: {test['browser']}")
        print(f"📸 Screenshot: {test['screenshot']}")
        
        # Manual execution
        response = input(f"\\nExecute UI test {test['id']}? (y/n/skip): ").lower()
        
        if response == 'skip' or response == 's':
            print(f"⚠️ {test['id']}: SKIPPED")
            results.append({"id": test['id'], "status": "SKIP", "timestamp": datetime.now().isoformat()})
            continue
        elif response != 'y':
            print(f"❌ {test['id']}: ABORTED")
            break
        
        # Get test results
        print(f"\\n📝 Record Results for {test['id']}:")
        ui_result = input("Did the UI behave as expected? (y/n): ").lower()
        
        if ui_result == 'y':
            status = "PASS"
            print(f"✅ {test['id']}: PASSED")
        else:
            status = "FAIL"
            print(f"❌ {test['id']}: FAILED")
            failure_details = input("Describe what went wrong: ")
            
            if test.get('critical') or test.get('main_migration_test'):
                print("🚨 CRITICAL UI TEST FAILED!")
                print("This may indicate migration issues")
        
        # Record detailed results
        result_data = {
            "id": test['id'],
            "section": test['section'],
            "component": test['component'],
            "status": status,
            "browser": test['browser'],
            "timestamp": datetime.now().isoformat()
        }
        
        if status == "FAIL":
            result_data['failure_details'] = failure_details
        
        if test.get('screenshot') == "REQUIRED" or test.get('screenshot') == "Recommended":
            screenshot_taken = input("Screenshot taken? (y/n): ").lower() == 'y'
            result_data['screenshot_taken'] = screenshot_taken
        
        results.append(result_data)
    
    # Generate UI test summary
    generate_ui_summary(results)
    
    return results


def generate_ui_summary(results):
    """Generate UI testing summary."""
    
    print(f"\\n{'='*60}")
    print("📊 ADMIN UI TEST SUMMARY")
    print("=" * 60)
    
    passed = len([r for r in results if r['status'] == 'PASS'])
    failed = len([r for r in results if r['status'] == 'FAIL'])
    skipped = len([r for r in results if r['status'] == 'SKIP'])
    total = len(results)
    
    print(f"📈 UI Test Results:")
    print(f"   ✅ Passed: {passed}/{total}")
    print(f"   ❌ Failed: {failed}/{total}")
    print(f"   ⚠️ Skipped: {skipped}/{total}")
    
    # Check critical UI tests
    critical_results = [r for r in results if 'UI-001' in r['id'] or 'UI-003' in r['id']]  # Login and server visibility
    critical_passed = len([r for r in critical_results if r['status'] == 'PASS'])
    
    print(f"\\n🚨 Critical UI Tests:")
    print(f"   ✅ Critical Passed: {critical_passed}/{len(critical_results)}")
    
    # Look for main migration test result
    server_visibility_test = next((r for r in results if 'UI-003' in r['id']), None)
    if server_visibility_test:
        if server_visibility_test['status'] == 'PASS':
            print("\\n🎯 MAIN MIGRATION TEST: ✅ PASSED")
            print("   Old servers are visible in admin UI!")
        else:
            print("\\n🎯 MAIN MIGRATION TEST: ❌ FAILED")
            print("   Old servers may not be visible - check migration")
    
    # Overall assessment
    if failed == 0 and critical_passed == len(critical_results):
        print(f"\\n🎉 ADMIN UI: FULLY FUNCTIONAL!")
        print("✅ All critical UI tests passed")
        print("✅ Admin interface ready for production use")
    else:
        print(f"\\n⚠️ ADMIN UI: ISSUES DETECTED") 
        print("🔧 Review failed tests and resolve issues")
    
    # Save results
    results_file = Path("tests/manual/admin_ui_test_results.json")
    with open(results_file, 'w') as f:
        json.dump({
            "summary": {"passed": passed, "failed": failed, "skipped": skipped},
            "results": results,
            "timestamp": datetime.now().isoformat()
        }, f, indent=2)
    
    print(f"\\n📄 Results saved: {results_file}")


def test_specific_ui_component(component_id):
    """Test specific UI component."""
    
    test = next((t for t in ADMIN_UI_TESTS if t['id'] == component_id), None)
    
    if not test:
        print(f"❌ Component {component_id} not found")
        available = [t['id'] for t in ADMIN_UI_TESTS]
        print(f"Available: {available}")
        return False
    
    print(f"🧪 TESTING UI COMPONENT: {component_id}")
    print("=" * 50)
    print(f"Section: {test['section']}")
    print(f"Component: {test['component']}")
    print(f"Action: {test['action']}")
    
    if test.get('main_migration_test'):
        print("🎯 THIS IS THE MAIN MIGRATION TEST!")
    
    print(f"\\n📋 Steps:")
    for step in test['steps']:
        print(f"   {step}")
    
    print(f"\\n✅ Expected: {test['expected']}")
    
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help":
            print("🖥️ Admin UI Tests")
            print("Usage:")
            print("  python3 tests/manual/admin_ui_tests.py                # Run all UI tests")
            print("  python3 tests/manual/admin_ui_tests.py --component UI-003  # Test specific component") 
            print("  python3 tests/manual/admin_ui_tests.py --help         # This help")
        elif sys.argv[1] == "--component" and len(sys.argv) > 2:
            test_specific_ui_component(sys.argv[2])
        else:
            print("❌ Unknown option. Use --help for usage.")
    else:
        try:
            print("🖥️ Starting admin UI testing...")
            print("💡 Focus on UI-003 (server visibility) - this is the main migration test!")
            results = run_admin_ui_tests()
            print("\\n🎉 Admin UI testing complete!")
            print("Next: python3 tests/manual/database_tests.py")
        except KeyboardInterrupt:
            print("\\n❌ Testing cancelled by user")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Testing error: {e}")
            sys.exit(1)