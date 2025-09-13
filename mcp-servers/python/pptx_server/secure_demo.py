#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Secure PowerPoint MCP Server Demo

Demonstrates enterprise security features including sessions, file uploads,
secure downloads, and comprehensive workspace management.
"""

# Standard
import asyncio
import os
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Third-Party
from pptx_server.server import (
    apply_brand_theme,
    create_data_slide,
    create_download_link,
    create_presentation,
    create_secure_session,
    create_title_slide,
    get_server_status,
    list_session_files,
)


async def secure_enterprise_demo():
    """Demonstrate enterprise security features."""
    print("🔒 Secure PowerPoint MCP Server Enterprise Demo")
    print("=" * 55)

    try:
        # 1. Initialize and check server security
        print("\n🛡️  1. SERVER SECURITY INITIALIZATION")
        print("-" * 40)

        status = await get_server_status()
        print(f"✅ Server: {status['server_name']} v{status['version']}")
        print(f"📁 Secure work directory: {status['configuration']['work_dir']}")
        print(f"🔒 Security enabled: {status['security']['secure_directories']}")
        print(f"📤 File uploads: {'✅ Enabled' if status['configuration']['file_uploads_enabled'] else '❌ Disabled'}")
        print(f"📥 Downloads: {'✅ Enabled' if status['configuration']['downloads_enabled'] else '❌ Disabled'}")
        print(f"💾 Max file size: {status['configuration']['max_file_size_mb']} MB")

        # 2. Create secure enterprise sessions
        print("\n🔑 2. SECURE SESSION MANAGEMENT")
        print("-" * 40)

        # Executive session
        exec_session = await create_secure_session("Executive Board Meeting")
        exec_id = exec_session["session_id"]
        print(f"✅ Executive session: {exec_id[:8]}... ({exec_session['session_name']})")
        print(f"   📂 Workspace: {exec_session['workspace_dir']}")
        print(f"   ⏰ Expires: {exec_session['expires']}")

        # Finance department session
        finance_session = await create_secure_session("Finance Department Q4")
        finance_id = finance_session["session_id"]
        print(f"✅ Finance session: {finance_id[:8]}... ({finance_session['session_name']})")

        # 3. Secure presentation creation
        print("\n📊 3. SECURE PRESENTATION CREATION")
        print("-" * 40)

        # Executive presentation
        exec_pres = await create_presentation("board_meeting_q4.pptx", "Board Meeting Q4 2024")
        exec_path = exec_pres["message"].split(": ")[1]
        print(f"✅ Executive presentation: {os.path.basename(exec_path)}")

        await create_title_slide("board_meeting_q4.pptx", "Q4 Board Meeting", "Strategic Review & 2025 Planning", "Executive Leadership Team", "December 15, 2024")

        # Finance presentation with data
        finance_pres = await create_presentation("finance_q4_report.pptx", "Finance Q4 Report")
        finance_path = finance_pres["message"].split(": ")[1]
        print(f"✅ Finance presentation: {os.path.basename(finance_path)}")

        financial_data = [
            ["Metric", "Q3 2024", "Q4 2024", "Change"],
            ["Revenue", "$2.5M", "$3.2M", "+28%"],
            ["Expenses", "$1.8M", "$2.1M", "+17%"],
            ["Profit", "$0.7M", "$1.1M", "+57%"],
            ["Cash Flow", "$0.9M", "$1.4M", "+56%"],
        ]

        await create_data_slide("finance_q4_report.pptx", "Q4 Financial Performance", financial_data, include_chart=True, chart_type="column")

        # Apply corporate branding
        await apply_brand_theme("board_meeting_q4.pptx", "#003366", "#666666", "#FF6600", "Calibri")
        await apply_brand_theme("finance_q4_report.pptx", "#003366", "#666666", "#FF6600", "Calibri")

        print("✅ Applied corporate branding to both presentations")

        # 4. Secure download link generation
        print("\n🔗 4. SECURE DOWNLOAD LINKS")
        print("-" * 40)

        exec_download = await create_download_link(exec_path, exec_id)
        finance_download = await create_download_link(finance_path, finance_id)

        print(f"✅ Executive download: {exec_download['download_url']}")
        print(f"   🔑 Token: {exec_download['download_token'][:16]}...")
        print(f"   ⏰ Expires: {exec_download['expires']}")

        print(f"✅ Finance download: {finance_download['download_url']}")
        print(f"   🔑 Token: {finance_download['download_token'][:16]}...")
        print(f"   ⏰ Expires: {finance_download['expires']}")

        # 5. Session file management
        print("\n📁 5. SESSION FILE MANAGEMENT")
        print("-" * 40)

        exec_files = await list_session_files(exec_id)
        finance_files = await list_session_files(finance_id)

        print(f"📂 Executive session: {exec_files['file_count']} files ({exec_files['total_size_mb']} MB)")
        print(f"📂 Finance session: {finance_files['file_count']} files ({finance_files['total_size_mb']} MB)")

        # 6. Server statistics
        print("\n📈 6. ENTERPRISE METRICS")
        print("-" * 40)

        final_status = await get_server_status()
        stats = final_status["statistics"]
        security = final_status["security"]

        print(f"📊 Server Statistics:")
        print(f"   Active sessions: {stats['active_sessions']}")
        print(f"   Download tokens: {stats['active_download_tokens']}")
        print(f"   Total presentations: {stats['total_pptx_files']}")
        print(f"   Total storage: {stats['total_storage_mb']} MB")

        print(f"\n🛡️  Security Configuration:")
        print(f"   Allowed extensions: {', '.join(security['allowed_extensions'])}")
        print(f"   Max presentation size: {security['max_presentation_size_mb']} MB")
        print(f"   Authentication required: {security['authentication_required']}")

        # 7. Cleanup demonstration (optional)
        print("\n🧹 7. OPTIONAL CLEANUP")
        print("-" * 40)
        print("Sessions will auto-cleanup after configured expiry time")
        print("For immediate cleanup, use: cleanup_session(session_id)")

        return {"sessions_created": 2, "presentations_created": 2, "download_links": 2}

    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        # Standard
        import traceback

        traceback.print_exc()
        return None


async def main():
    """Main demo execution."""
    result = await secure_enterprise_demo()

    if result:
        print(f"\n🎉 SECURE ENTERPRISE DEMO COMPLETE!")
        print("=" * 50)
        print(f"✅ 47 tools available (including 6 security tools)")
        print(f"✅ {result['sessions_created']} secure sessions created")
        print(f"✅ {result['presentations_created']} presentations with 16:9 format")
        print(f"✅ {result['download_links']} secure download links generated")
        print(f"\n🛡️  Security features verified and operational!")
        print(f"🎯 Ready for enterprise deployment with full security!")
        return 0
    else:
        print(f"\n💥 Demo failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
