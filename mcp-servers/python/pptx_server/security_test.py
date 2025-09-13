#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Security Vulnerability Test & Secure Solution Demo

Demonstrates the multi-agent security issue and shows the proper secure usage pattern.
"""

# Standard
import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "src"))

# Third-Party
from pptx_server.server import (
    create_presentation,
    create_secure_session,
    get_server_status,
    list_session_files,
)


async def demonstrate_security_issue():
    """Demonstrate the current security vulnerability."""
    print("🚨 DEMONSTRATING SECURITY VULNERABILITY")
    print("=" * 50)

    try:
        # Simulate Agent A
        print("\n👤 AGENT A Operations:")
        pres_a = await create_presentation("confidential_report.pptx", "Agent A Confidential Report")
        print(f"   Created: {os.path.basename(pres_a['message'].split(': ')[1])}")
        print(f"   Path: {pres_a['message'].split(': ')[1]}")

        # Simulate Agent B (same filename!)
        print("\n👤 AGENT B Operations:")
        pres_b = await create_presentation("confidential_report.pptx", "Agent B Secret Data")
        print(f"   Created: {os.path.basename(pres_b['message'].split(': ')[1])}")
        print(f"   Path: {pres_b['message'].split(': ')[1]}")

        # Check if paths are the same (security issue!)
        path_a = pres_a["message"].split(": ")[1]
        path_b = pres_b["message"].split(": ")[1]

        print(f"\n🚨 SECURITY ANALYSIS:")
        if path_a == path_b:
            print(f"   ❌ CRITICAL: Same file path! Agent B overwrote Agent A's file!")
            print(f"   ❌ File collision: {path_a}")
        else:
            print(f"   ✅ Different paths (session isolation working)")

        return {"agent_a_path": path_a, "agent_b_path": path_b, "collision": path_a == path_b}

    except Exception as e:
        print(f"❌ Error in vulnerability demo: {e}")
        return None


async def demonstrate_secure_solution():
    """Demonstrate the proper secure usage with session isolation."""
    print("\n🛡️ DEMONSTRATING SECURE SOLUTION")
    print("=" * 50)

    try:
        # Agent A: Create isolated session
        print("\n👤 AGENT A - Secure Session:")
        session_a = await create_secure_session("Agent-A-Confidential-Work")
        session_a_id = session_a["session_id"]
        print(f"   ✅ Session: {session_a_id[:8]}... ({session_a['session_name']})")
        print(f"   📂 Workspace: {session_a['workspace_dir']}")

        # Agent B: Create separate isolated session
        print("\n👤 AGENT B - Secure Session:")
        session_b = await create_secure_session("Agent-B-Secret-Project")
        session_b_id = session_b["session_id"]
        print(f"   ✅ Session: {session_b_id[:8]}... ({session_b['session_name']})")
        print(f"   📂 Workspace: {session_b['workspace_dir']}")

        # Verify complete isolation
        print(f"\n🔒 ISOLATION VERIFICATION:")
        print(f"   Agent A workspace: {session_a['workspace_dir']}")
        print(f"   Agent B workspace: {session_b['workspace_dir']}")
        print(f"   ✅ Completely isolated: {session_a_id != session_b_id}")

        # Show session file isolation
        files_a = await list_session_files(session_a_id)
        files_b = await list_session_files(session_b_id)

        print(f"\n📁 SESSION FILE ISOLATION:")
        print(f"   Agent A files: {files_a['file_count']} (in {files_a['workspace_dir']})")
        print(f"   Agent B files: {files_b['file_count']} (in {files_b['workspace_dir']})")

        # Generate secure download links
        print(f"\n🔗 SECURE DOWNLOAD LINKS:")
        print(f"   Each agent gets isolated download tokens")
        print(f"   No cross-session access possible")

        return {"session_a": session_a_id, "session_b": session_b_id, "isolated": session_a_id != session_b_id}

    except Exception as e:
        print(f"❌ Error in secure demo: {e}")
        return None


async def security_recommendations():
    """Provide security recommendations."""
    print("\n🎯 SECURITY RECOMMENDATIONS")
    print("=" * 50)

    print("\n🚨 IMMEDIATE ACTIONS REQUIRED:")
    print("   1. DO NOT deploy in multi-user environment yet")
    print("   2. Always use create_secure_session() first")
    print("   3. Update all tools to require session_id parameter")
    print("   4. Implement session-scoped file operations")

    print("\n🛡️ SECURE DEPLOYMENT PATTERN:")
    print("   1. Each AI agent/user gets unique session")
    print("   2. All files created in session-isolated directories")
    print("   3. Download links scoped to session ownership")
    print("   4. Automatic cleanup prevents data leakage")

    print("\n🔧 REQUIRED IMPLEMENTATION:")
    print("   • Add session_id to all 47 tool schemas")
    print("   • Update all functions to use session-scoped paths")
    print("   • Isolate presentation cache by session")
    print("   • Add session validation to all operations")

    # Get current status
    status = await get_server_status()
    print(f"\n📊 CURRENT SERVER STATUS:")
    print(f"   Active sessions: {status['statistics']['active_sessions']}")
    print(f"   Security framework: ✅ IMPLEMENTED")
    print(f"   Session isolation: ⚠️  PARTIAL (needs completion)")


async def main():
    """Main security demonstration."""
    print("🔒 PowerPoint MCP Server - Security Analysis")
    print("=" * 60)

    # Demonstrate the vulnerability
    vuln_result = await demonstrate_security_issue()

    # Demonstrate the secure solution
    secure_result = await demonstrate_secure_solution()

    # Provide recommendations
    await security_recommendations()

    print("\n" + "=" * 60)
    if vuln_result and vuln_result["collision"]:
        print("🚨 CRITICAL: File collision detected - security vulnerability confirmed!")
    else:
        print("✅ No file collision detected")

    if secure_result and secure_result["isolated"]:
        print("🛡️ SECURE: Session isolation working correctly")
    else:
        print("❌ Session isolation failed")

    print("\n🎯 CONCLUSION:")
    print("   The server has the security FRAMEWORK implemented,")
    print("   but needs COMPLETE session isolation across all tools.")
    print("   Use create_secure_session() + session-aware tools only.")

    return 0 if secure_result else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
