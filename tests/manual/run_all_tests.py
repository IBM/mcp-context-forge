#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Gateway v0.7.0 - Master Test Runner

Coordinates execution of all manual test suites.
Designed for comprehensive validation after v0.6.0 → v0.7.0 migration.

Usage:
    python3 tests/manual/run_all_tests.py
    python3 tests/manual/run_all_tests.py --quick
    python3 tests/manual/run_all_tests.py --critical-only
"""

import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

# Test suite configuration
TEST_SUITES = [
    {
        "name": "Setup Instructions",
        "file": "setup_instructions.py",
        "description": "Environment setup and validation",
        "priority": "CRITICAL",
        "estimated_time": "30-60 minutes",
        "prerequisite": True
    },
    {
        "name": "Migration Validation", 
        "file": "migration_tests.py",
        "description": "Post-migration validation tests",
        "priority": "CRITICAL",
        "estimated_time": "45-90 minutes",
        "main_test": True
    },
    {
        "name": "Admin UI Testing",
        "file": "admin_ui_tests.py", 
        "description": "Complete admin interface testing",
        "priority": "CRITICAL",
        "estimated_time": "60-120 minutes",
        "includes_main_test": True
    },
    {
        "name": "API Authentication",
        "file": "api_authentication_tests.py",
        "description": "Authentication endpoint testing",
        "priority": "HIGH",
        "estimated_time": "30-60 minutes"
    },
    {
        "name": "API Teams",
        "file": "api_teams_tests.py",
        "description": "Team management API testing", 
        "priority": "HIGH",
        "estimated_time": "30-60 minutes"
    },
    {
        "name": "API Servers", 
        "file": "api_servers_tests.py",
        "description": "Virtual servers API testing",
        "priority": "HIGH", 
        "estimated_time": "45-90 minutes"
    },
    {
        "name": "Database Testing",
        "file": "database_tests.py",
        "description": "SQLite and PostgreSQL compatibility",
        "priority": "HIGH",
        "estimated_time": "60-120 minutes"
    },
    {
        "name": "Security Testing",
        "file": "security_tests.py", 
        "description": "Security and penetration testing",
        "priority": "MEDIUM",
        "estimated_time": "90-180 minutes",
        "warning": "Performs actual attack scenarios"
    }
]

# Tester assignment suggestions
TESTER_ASSIGNMENTS = [
    {
        "tester": "Tester 1",
        "focus": "Critical Path", 
        "assignments": ["Setup Instructions", "Migration Validation", "Admin UI Testing"],
        "database": "SQLite",
        "estimated_time": "3-5 hours"
    },
    {
        "tester": "Tester 2",
        "focus": "API Testing",
        "assignments": ["API Authentication", "API Teams", "API Servers"], 
        "database": "SQLite",
        "estimated_time": "2-4 hours"
    },
    {
        "tester": "Tester 3",
        "focus": "Database Compatibility",
        "assignments": ["Database Testing", "Migration Validation"],
        "database": "PostgreSQL", 
        "estimated_time": "2-3 hours"
    },
    {
        "tester": "Tester 4",
        "focus": "Security Validation",
        "assignments": ["Security Testing", "API Authentication"],
        "database": "Both",
        "estimated_time": "3-5 hours"
    }
]


def main():
    """Main test coordination."""
    
    print("🎯 MCP GATEWAY COMPREHENSIVE MANUAL TESTING")
    print("=" * 70)
    print("🔄 Post-Migration Validation Suite")
    print("👥 Designed for multiple testers")
    
    print("\\n📋 Available Test Suites:")
    for i, suite in enumerate(TEST_SUITES, 1):
        priority_icon = "🚨" if suite['priority'] == 'CRITICAL' else "🔧" if suite['priority'] == 'HIGH' else "📝"
        main_icon = " 🎯" if suite.get('main_test') or suite.get('includes_main_test') else ""
        
        print(f"   {i:2}. {suite['name']} {priority_icon}{main_icon}")
        print(f"       {suite['description']}")
        print(f"       Time: {suite['estimated_time']}")
        
        if suite.get('warning'):
            print(f"       ⚠️ {suite['warning']}")
    
    print("\\n👥 Suggested Tester Assignments:")
    for assignment in TESTER_ASSIGNMENTS:
        print(f"   {assignment['tester']} ({assignment['focus']}):")
        print(f"      Tests: {', '.join(assignment['assignments'])}")
        print(f"      Database: {assignment['database']}")
        print(f"      Time: {assignment['estimated_time']}")
        print()


def run_quick_validation():
    """Run quick critical tests only."""
    
    print("⚡ QUICK VALIDATION - Critical Tests Only")
    print("=" * 50)
    
    critical_suites = [s for s in TEST_SUITES if s['priority'] == 'CRITICAL']
    
    for suite in critical_suites:
        print(f"\\n🚨 {suite['name']}")
        print(f"   {suite['description']}")
        
        response = input(f"\\nRun {suite['name']}? (y/n): ").lower()
        if response == 'y':
            run_test_suite(suite)


def run_test_suite(suite):
    """Run a specific test suite."""
    
    print(f"\\n🧪 RUNNING: {suite['name']}")
    print("=" * 50)
    
    test_file = Path("tests/manual") / suite['file']
    
    if not test_file.exists():
        print(f"❌ Test file not found: {test_file}")
        return False
    
    print(f"📄 Executing: {test_file}")
    print(f"⏱️ Estimated time: {suite['estimated_time']}")
    
    if suite.get('warning'):
        print(f"⚠️ Warning: {suite['warning']}")
        proceed = input("Proceed? (y/N): ").lower()
        if proceed != 'y':
            print("⚠️ Test suite skipped")
            return False
    
    try:
        # Execute test file
        result = subprocess.run([sys.executable, str(test_file)], 
                              capture_output=True, text=True, timeout=1800)  # 30 min timeout
        
        if result.returncode == 0:
            print(f"✅ {suite['name']}: Completed successfully")
            if result.stdout:
                print("Output summary:")
                print(result.stdout[-500:])  # Last 500 chars
        else:
            print(f"❌ {suite['name']}: Failed or incomplete")
            if result.stderr:
                print("Errors:")
                print(result.stderr[-500:])
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print(f"⏰ {suite['name']}: Timeout (exceeded 30 minutes)")
        return False
    except Exception as e:
        print(f"❌ {suite['name']}: Execution error - {e}")
        return False


def interactive_testing():
    """Interactive test suite selection and execution."""
    
    print("🎯 INTERACTIVE TESTING MODE")
    print("=" * 50)
    
    print("\\nSelect test suites to run:")
    for i, suite in enumerate(TEST_SUITES, 1):
        print(f"   {i}. {suite['name']} ({suite['priority']})")
    
    print("\\nOptions:")
    print("   a - Run all test suites")
    print("   c - Run critical tests only") 
    print("   1,2,3 - Run specific test suites")
    print("   q - Quit")
    
    selection = input("\\nYour choice: ").lower().strip()
    
    if selection == 'q':
        print("❌ Testing cancelled")
        return
    elif selection == 'a':
        print("🚀 Running ALL test suites...")
        for suite in TEST_SUITES:
            run_test_suite(suite)
    elif selection == 'c':
        run_quick_validation()
    else:
        # Parse specific selections
        try:
            indices = [int(x.strip()) for x in selection.split(',')]
            for idx in indices:
                if 1 <= idx <= len(TEST_SUITES):
                    suite = TEST_SUITES[idx - 1]
                    run_test_suite(suite)
                else:
                    print(f"❌ Invalid selection: {idx}")
        except ValueError:
            print("❌ Invalid input format")


def generate_overall_summary():
    """Generate comprehensive test summary."""
    
    print("\\n📊 GENERATING OVERALL TEST SUMMARY")
    print("=" * 60)
    
    # Collect results from all test files
    results_files = list(Path("tests/manual").glob("*_test_results.json"))
    
    overall_summary = {
        "test_execution": {
            "timestamp": datetime.now().isoformat(),
            "total_suites": len(TEST_SUITES),
            "results_files": len(results_files)
        },
        "suite_results": {}
    }
    
    for results_file in results_files:
        try:
            with open(results_file, 'r') as f:
                data = json.load(f)
                suite_name = results_file.stem.replace('_test_results', '')
                overall_summary['suite_results'][suite_name] = data
        except Exception as e:
            print(f"⚠️ Could not read {results_file}: {e}")
    
    # Save overall summary
    summary_file = Path("tests/manual/overall_test_summary.json")
    with open(summary_file, 'w') as f:
        json.dump(overall_summary, f, indent=2)
    
    print(f"📄 Overall summary saved: {summary_file}")
    
    # Print summary
    if overall_summary['suite_results']:
        print("\\n📈 Test Suite Results:")
        for suite_name, data in overall_summary['suite_results'].items():
            if 'summary' in data:
                summary = data['summary']
                passed = summary.get('passed', 0)
                total = summary.get('total', 0)
                print(f"   {suite_name}: {passed}/{total} passed")
            else:
                print(f"   {suite_name}: Results available")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help":
            print("🎯 MCP Gateway Manual Test Runner")
            print("Usage:")
            print("  python3 tests/manual/run_all_tests.py              # Interactive mode")
            print("  python3 tests/manual/run_all_tests.py --quick      # Critical tests only")
            print("  python3 tests/manual/run_all_tests.py --critical-only  # Same as --quick")
            print("  python3 tests/manual/run_all_tests.py --list       # List all test suites") 
            print("  python3 tests/manual/run_all_tests.py --help       # This help")
            print("\\n🎯 Individual test suites can be run directly:")
            for suite in TEST_SUITES:
                print(f"  python3 tests/manual/{suite['file']}")
        elif sys.argv[1] == "--list":
            main()  # Show test suites
        elif sys.argv[1] == "--quick" or sys.argv[1] == "--critical-only":
            run_quick_validation()
            generate_overall_summary()
        else:
            print("❌ Unknown option. Use --help for usage.")
    else:
        try:
            main()
            print("\\n🚀 Starting interactive testing...")
            interactive_testing()
            generate_overall_summary()
            print("\\n🎉 Manual testing session complete!")
        except KeyboardInterrupt:
            print("\\n❌ Testing cancelled by user")
        except Exception as e:
            print(f"❌ Testing error: {e}")
            sys.exit(1)