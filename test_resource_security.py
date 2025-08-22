#!/usr/bin/env python3
"""
Simple test script to verify resource security validation.
This tests the specific scenarios mentioned in the user's curl commands.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcpgateway.services.resource_service import ResourceService, ResourceError
from mcpgateway.schemas import ResourceCreate
from mcpgateway.config import settings
from unittest.mock import MagicMock

async def test_script_injection():
    """Test that script tags are blocked."""
    print("Testing script injection...")
    
    service = ResourceService()
    
    # Mock database session
    db = MagicMock()
    
    # Test 1: Script injection
    try:
        resource = ResourceCreate(
            uri="test://script",
            name="Script",
            content="<script>alert(1)</script>"
        )
        
        result = await service.register_resource(db, resource)
        print("❌ Script injection was NOT blocked!")
        return False
    except ResourceError as e:
        if "disallowed script tags" in str(e):
            print("✅ Script injection correctly blocked:", str(e))
            return True
        else:
            print("❌ Script injection blocked but with wrong message:", str(e))
            return False
    except Exception as e:
        print("❌ Unexpected error:", str(e))
        return False

async def test_html_mime_type():
    """Test that HTML MIME type is blocked."""
    print("Testing HTML MIME type...")
    
    service = ResourceService()
    
    # Mock database session
    db = MagicMock()
    
    # Test 2: HTML MIME type
    try:
        resource = ResourceCreate(
            uri="test.html",
            name="HTML",
            content="<html>test</html>",
            mime_type="text/html"
        )
        
        result = await service.register_resource(db, resource)
        print("❌ HTML MIME type was NOT blocked!")
        return False
    except ResourceError as e:
        if "disallowed MIME type" in str(e) and "text/html" in str(e):
            print("✅ HTML MIME type correctly blocked:", str(e))
            return True
        else:
            print("❌ HTML MIME type blocked but with wrong message:", str(e))
            return False
    except Exception as e:
        print("❌ Unexpected error:", str(e))
        return False

async def test_valid_content():
    """Test that valid content is allowed."""
    print("Testing valid content...")
    
    service = ResourceService()
    
    # Mock database session and its methods
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    
    # Mock the resource object that would be created
    mock_resource = MagicMock()
    mock_resource.id = 1
    mock_resource.uri = "test://valid"
    mock_resource.name = "Valid"
    mock_resource.content = "This is valid content"
    mock_resource.metrics = []
    mock_resource.tags = []
    
    # Make refresh set the mock resource
    def refresh_side_effect(resource):
        resource.id = 1
        resource.metrics = []
        resource.tags = []
    
    db.refresh.side_effect = refresh_side_effect
    
    try:
        resource = ResourceCreate(
            uri="test://valid",
            name="Valid",
            content="This is valid content"
        )
        
        result = await service.register_resource(db, resource)
        print("✅ Valid content correctly allowed")
        return True
    except Exception as e:
        print("❌ Valid content was blocked:", str(e))
        return False

async def main():
    """Run all tests."""
    print("Running resource security validation tests...\n")
    
    # Enable content validation patterns for testing
    settings.content_validate_patterns = True
    
    results = []
    
    # Test script injection
    results.append(await test_script_injection())
    print()
    
    # Test HTML MIME type
    results.append(await test_html_mime_type())
    print()
    
    # Test valid content
    results.append(await test_valid_content())
    print()
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All security validation tests passed!")
        return 0
    else:
        print("❌ Some security validation tests failed!")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)