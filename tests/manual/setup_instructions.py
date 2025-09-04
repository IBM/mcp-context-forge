#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Gateway v0.7.0 - Setup Instructions for Manual Testing

Complete environment setup guide for testers.
This file contains step-by-step instructions for setting up
the MCP Gateway for comprehensive manual testing.

Usage:
    python3 tests/manual/setup_instructions.py
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Test case data structure
SETUP_TESTS = [
    {
        "id": "SETUP-001",
        "step": "Check Prerequisites",
        "action": "Verify Python 3.11+, Git, and curl installed",
        "command": "python3 --version && git --version && curl --version",
        "expected": "All tools show version numbers",
        "troubleshooting": "Install missing tools via package manager",
        "required": True
    },
    {
        "id": "SETUP-002", 
        "step": "Clone Repository",
        "action": "Download MCP Gateway source code",
        "command": "git clone https://github.com/anthropics/mcp-context-forge.git",
        "expected": "Repository cloned successfully",
        "troubleshooting": "Check git credentials and network access",
        "required": True
    },
    {
        "id": "SETUP-003",
        "step": "Enter Directory", 
        "action": "Navigate to project directory",
        "command": "cd mcp-context-forge",
        "expected": "Directory changed, can see project files",
        "troubleshooting": "Use 'ls' to verify files like README.md, .env.example",
        "required": True
    },
    {
        "id": "SETUP-004",
        "step": "Copy Environment",
        "action": "Create environment configuration file", 
        "command": "cp .env.example .env",
        "expected": ".env file created",
        "troubleshooting": "Check file exists: ls -la .env",
        "required": True
    },
    {
        "id": "SETUP-005",
        "step": "Edit Configuration",
        "action": "Configure platform admin credentials",
        "command": "vi .env",
        "expected": "File opens in vi editor",
        "troubleshooting": "Use :wq to save and quit vi",
        "required": True,
        "details": [
            "Set PLATFORM_ADMIN_EMAIL=<your-test-email>",
            "Set PLATFORM_ADMIN_PASSWORD=<strong-password>", 
            "Set EMAIL_AUTH_ENABLED=true",
            "Save file with :wq"
        ]
    },
    {
        "id": "SETUP-006",
        "step": "Verify Configuration", 
        "action": "Check settings are loaded correctly",
        "command": 'python3 -c "from mcpgateway.config import settings; print(f\'Admin: {settings.platform_admin_email}\')"',
        "expected": "Shows your configured admin email",
        "troubleshooting": "If error, check .env file syntax",
        "required": True
    },
    {
        "id": "SETUP-007",
        "step": "Install Dependencies",
        "action": "Install Python packages",
        "command": "make install-dev", 
        "expected": "All dependencies installed successfully",
        "troubleshooting": "May take 5-15 minutes, check internet connection",
        "required": True
    },
    {
        "id": "SETUP-008",
        "step": "Run Migration",
        "action": "Execute database migration (CRITICAL STEP)",
        "command": "python3 -m mcpgateway.bootstrap_db",
        "expected": "'Database ready' message at end",
        "troubleshooting": "MUST complete successfully - get help if fails",
        "required": True,
        "critical": True
    },
    {
        "id": "SETUP-009",
        "step": "Verify Migration",
        "action": "Validate migration completed correctly",
        "command": "python3 scripts/verify_multitenancy_0_7_0_migration.py", 
        "expected": "'🎉 MIGRATION VERIFICATION: SUCCESS!' at end",
        "troubleshooting": "All checks must pass - use fix script if needed",
        "required": True,
        "critical": True
    },
    {
        "id": "SETUP-010",
        "step": "Start Gateway",
        "action": "Start MCP Gateway server",
        "command": "make dev",
        "expected": "'Uvicorn running on http://0.0.0.0:4444' message",
        "troubleshooting": "Keep this terminal window open during testing",
        "required": True
    },
    {
        "id": "SETUP-011",
        "step": "Test Health Check",
        "action": "Verify server is responding",
        "command": "curl http://localhost:4444/health",
        "expected": '{"status":"ok"}',
        "troubleshooting": "If fails, check server started correctly",
        "required": True
    },
    {
        "id": "SETUP-012",
        "step": "Access Admin UI",
        "action": "Open admin interface in browser",
        "command": "Open http://localhost:4444/admin in browser",
        "expected": "Login page appears",
        "troubleshooting": "Try both http:// and https://",
        "required": True
    },
    {
        "id": "SETUP-013",
        "step": "Test Admin Login",
        "action": "Authenticate with admin credentials",
        "command": "Login with admin email/password from .env",
        "expected": "Dashboard loads successfully",
        "troubleshooting": "Main authentication validation test",
        "required": True,
        "critical": True
    },
    {
        "id": "SETUP-014", 
        "step": "Verify Servers Visible",
        "action": "Check old servers appear in UI (MAIN MIGRATION TEST)",
        "command": "Navigate to Virtual Servers section",
        "expected": "Servers listed, including pre-migration servers",
        "troubleshooting": "If empty list, migration failed - get help immediately",
        "required": True,
        "critical": True,
        "main_test": True
    }
]

# Tester information template
TESTER_INFO = {
    "name": "",
    "email": "",
    "start_date": "",
    "database_type": "SQLite/PostgreSQL",
    "os": "",
    "browser": "Chrome/Firefox",
    "experience": "Beginner/Intermediate/Expert",
    "time_available": "",
    "organization": "",
    "contact": ""
}

# Prerequisites checklist
PREREQUISITES = [
    "Python 3.11+ installed (python3 --version)",
    "Git installed (git --version)",
    "curl installed (curl --version)", 
    "Modern web browser (Chrome/Firefox recommended)",
    "Text editor (vi/vim/VSCode)",
    "Terminal/command line access",
    "4+ hours dedicated testing time",
    "Reliable internet connection",
    "Admin/sudo access for package installation",
    "Basic understanding of web applications and APIs"
]


def run_setup_validation():
    """Interactive setup validation."""
    
    print("🚀 MCP GATEWAY SETUP VALIDATION")
    print("=" * 60)
    
    print("\\n👤 TESTER INFORMATION")
    print("Please provide your information:")
    
    tester_info = {}
    for key, default in TESTER_INFO.items():
        prompt = f"{key.replace('_', ' ').title()}"
        if default:
            prompt += f" ({default})"
        prompt += ": "
        
        value = input(prompt).strip()
        tester_info[key] = value
    
    print("\\n⚠️ PREREQUISITES CHECK")
    print("Verify you have all prerequisites:")
    
    for i, prereq in enumerate(PREREQUISITES, 1):
        print(f"   {i:2}. {prereq}")
        
    response = input("\\nDo you have all prerequisites? (y/N): ").lower()
    if response != 'y':
        print("❌ Please install missing prerequisites before continuing")
        return False
    
    print("\\n🔧 SETUP EXECUTION")
    print("Follow these steps exactly:")
    
    for i, test in enumerate(SETUP_TESTS, 1):
        print(f"\\n--- STEP {i}: {test['step']} ---")
        print(f"Action: {test['action']}")
        print(f"Command: {test['command']}")
        print(f"Expected: {test['expected']}")
        
        if test.get('details'):
            print("Details:")
            for detail in test['details']:
                print(f"  - {detail}")
        
        if test.get('critical'):
            print("🚨 CRITICAL: This step must succeed!")
        
        if test.get('main_test'):
            print("🎯 MAIN TEST: This validates the migration fix!")
        
        # Wait for user confirmation
        response = input(f"\\nCompleted step {i}? (y/n/q): ").lower()
        
        if response == 'q':
            print("❌ Setup cancelled by user")
            return False
        elif response == 'n':
            print(f"⚠️ Step {i} not completed")
            if test.get('critical'):
                print("🚨 Critical step failed - please resolve before continuing")
                troubleshoot = input("Need troubleshooting help? (y/N): ").lower()
                if troubleshoot == 'y':
                    print(f"💡 Troubleshooting: {test['troubleshooting']}")
                return False
        else:
            print(f"✅ Step {i} completed")
    
    print("\\n🎊 SETUP COMPLETE!")
    print("✅ All setup steps completed successfully")
    print("🧪 Ready to begin manual testing")
    
    # Save tester info for reference
    save_tester_info(tester_info)
    
    return True


def save_tester_info(info):
    """Save tester information for tracking."""
    
    info_file = Path("tests/manual/tester_info.txt")
    
    with open(info_file, 'w') as f:
        f.write(f"Tester Information\\n")
        f.write(f"Generated: {datetime.now().isoformat()}\\n")
        f.write("=" * 40 + "\\n")
        
        for key, value in info.items():
            f.write(f"{key.replace('_', ' ').title()}: {value}\\n")
    
    print(f"\\n📄 Tester info saved: {info_file}")


def print_usage():
    """Print usage instructions."""
    
    print("📋 SETUP INSTRUCTIONS USAGE")
    print("=" * 40)
    print()
    print("This script guides you through complete environment setup.")
    print()
    print("Options:")
    print("  python3 tests/manual/setup_instructions.py          # Interactive setup")
    print("  python3 tests/manual/setup_instructions.py --list   # Show all steps")
    print("  python3 tests/manual/setup_instructions.py --help   # This help")
    print()
    print("Next steps after setup:")
    print("  python3 tests/manual/migration_tests.py             # Critical migration tests")
    print("  python3 tests/manual/api_authentication_tests.py    # API authentication")
    print("  python3 tests/manual/admin_ui_tests.py              # Admin UI testing")
    print()


def list_all_steps():
    """List all setup steps."""
    
    print("📋 ALL SETUP STEPS")
    print("=" * 40)
    
    for i, test in enumerate(SETUP_TESTS, 1):
        status = "🚨 CRITICAL" if test.get('critical') else "📋 Required" if test.get('required') else "📝 Optional"
        print(f"\\n{i:2}. {test['step']} ({status})")
        print(f"    Action: {test['action']}")
        print(f"    Command: {test['command']}")
        print(f"    Expected: {test['expected']}")
        
        if test.get('main_test'):
            print("    🎯 THIS IS THE MAIN MIGRATION TEST!")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help":
            print_usage()
        elif sys.argv[1] == "--list":
            list_all_steps()
        else:
            print("❌ Unknown option. Use --help for usage.")
    else:
        # Run interactive setup
        try:
            success = run_setup_validation()
            if success:
                print("\\n🎉 Setup complete! Ready for testing.")
                print("Next: python3 tests/manual/migration_tests.py")
            else:
                print("❌ Setup incomplete. Please resolve issues.")
                sys.exit(1)
        except KeyboardInterrupt:
            print("\\n❌ Setup cancelled by user")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Setup error: {e}")
            sys.exit(1)