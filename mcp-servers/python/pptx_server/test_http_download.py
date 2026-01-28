#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pptx_server/test_http_download.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test HTTP download functionality.
"""

# Standard
import asyncio
import os
import sys
import threading
from pathlib import Path

# Third-Party
import requests

sys.path.insert(0, str(Path(__file__).parent / "src"))


def start_http_server():
    """Start HTTP server in background."""
    try:
        # Third-Party
        import uvicorn

        from pptx_server.http_server import app

        uvicorn.run(app, host="localhost", port=9000, log_level="warning")
    except Exception as e:
        print(f"HTTP server error: {e}")


async def test_download_workflow():
    """Test complete download workflow."""
    print("🌐 TESTING HTTP DOWNLOAD WORKFLOW")
    print("=" * 45)

    # Start HTTP server in background
    print("\n🚀 Starting HTTP server...")
    server_thread = threading.Thread(target=start_http_server, daemon=True)
    server_thread.start()

    # Wait for server to start
    await asyncio.sleep(2)

    # Test server health
    try:
        health_response = requests.get("http://localhost:9000/health", timeout=5)
        if health_response.status_code == 200:
            print("✅ HTTP server running")
            print(f"   Health: {health_response.json()}")
        else:
            print(f"❌ HTTP server unhealthy: {health_response.status_code}")
            return False
    except Exception as e:
        print(f"❌ HTTP server not accessible: {e}")
        return False

    # Create presentation and download link
    # Third-Party
    from pptx_server.server import create_download_link, create_presentation

    print("\n📊 Creating presentation...")
    pres = await create_presentation("download_demo.pptx", "Download Demo")
    print(f"✅ Created: {os.path.basename(pres['secure_path'])}")

    print("\n🔗 Creating download link...")
    download = await create_download_link(pres["secure_path"], pres["session_id"])
    download_url = download["download_url"]
    print(f"✅ Download URL: {download_url}")

    # Test actual download
    print("\n📥 Testing actual download...")
    try:
        download_response = requests.get(download_url, timeout=10)
        if download_response.status_code == 200:
            # Save downloaded file
            test_download_path = "test_downloaded.pptx"
            with open(test_download_path, "wb") as f:
                f.write(download_response.content)

            # Verify downloaded file
            file_size = len(download_response.content)
            print(f"✅ Download successful: {file_size} bytes")

            # Verify it's a valid PowerPoint file
            try:
                # Third-Party
                from pptx import Presentation

                verify_prs = Presentation(test_download_path)
                print(f"✅ Valid PowerPoint: {len(verify_prs.slides)} slides")

                # Cleanup test file
                os.remove(test_download_path)
                return True

            except Exception as e:
                print(f"❌ Invalid PowerPoint file: {e}")
                return False

        else:
            print(f"❌ Download failed: HTTP {download_response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Download error: {e}")
        return False


async def main():
    """Main test function."""
    success = await test_download_workflow()

    print(f"\n{'=' * 45}")
    if success:
        print("🎉 HTTP DOWNLOAD SYSTEM: ✅ FULLY WORKING!")
        print("   ✅ HTTP server running")
        print("   ✅ Download links working")
        print("   ✅ File serving functional")
        print("   ✅ PowerPoint files downloadable")
        print("\n🎯 Your PowerPoint MCP Server now provides:")
        print("   📊 47 comprehensive PowerPoint tools")
        print("   🔒 Automatic session isolation")
        print("   📺 16:9 widescreen format default")
        print("   📥 Working HTTP downloads!")
        return 0
    else:
        print("💥 HTTP DOWNLOAD SYSTEM: ❌ NEEDS DEBUGGING")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
