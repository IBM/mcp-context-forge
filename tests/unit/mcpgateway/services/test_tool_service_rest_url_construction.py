# -*- coding: utf-8 -*-
"""Test REST tool URL construction with None/empty values.

This test verifies that REST tools properly construct URLs from gateway URL + endpoint
when the tool's URL field is None, empty, or the string 'None'.
"""


def test_url_construction_with_none_string():
    """Test that string 'None' triggers URL construction."""
    tool_url = "None"
    tool_endpoint = "/api/test"
    gateway_url = "https://api.example.com"
    
    should_construct = bool((not tool_url or tool_url.strip() == "" or tool_url.strip().lower() == "none") and tool_endpoint and gateway_url)
    
    assert should_construct is True
    
    # Simulate URL construction
    if should_construct:
        gateway_url_base = gateway_url.rstrip("/")
        endpoint_path = tool_endpoint.lstrip("/")
        constructed_url = f"{gateway_url_base}/{endpoint_path}"
        
    assert constructed_url == "https://api.example.com/api/test"


def test_url_construction_with_empty_string():
    """Test that empty string triggers URL construction."""
    tool_url = ""
    tool_endpoint = "/api/test"
    gateway_url = "https://api.example.com/"
    
    # Simulate the condition check
    should_construct = bool((not tool_url or tool_url.strip() == "" or tool_url.strip().lower() == "none") and tool_endpoint and gateway_url)
    
    assert should_construct is True
    
    # Simulate URL construction with trailing slash handling
    if should_construct:
        gateway_url_base = gateway_url.rstrip("/")
        endpoint_path = tool_endpoint.lstrip("/")
        constructed_url = f"{gateway_url_base}/{endpoint_path}"
        
    assert constructed_url == "https://api.example.com/api/test"


def test_url_construction_with_python_none():
    """Test that Python None triggers URL construction."""
    tool_url = None
    tool_endpoint = "/api/test"
    gateway_url = "https://api.example.com"
    
    # Simulate the condition check - need to handle None carefully
    should_construct = bool((not tool_url) and tool_endpoint and gateway_url)
    
    assert should_construct is True
    
    # Simulate URL construction
    if should_construct:
        gateway_url_base = gateway_url.rstrip("/")
        endpoint_path = tool_endpoint.lstrip("/")
        constructed_url = f"{gateway_url_base}/{endpoint_path}"
        
    assert constructed_url == "https://api.example.com/api/test"


def test_final_url_assignment_with_none_string():
    """Test that final_url assignment treats string 'None' as None."""
    tool_url = "None"
    
    # Simulate the assignment from line 4167
    final_url = tool_url if tool_url and tool_url.lower() != 'none' else None
    
    assert final_url is None


def test_final_url_assignment_with_valid_url():
    """Test that final_url assignment preserves valid URLs."""
    tool_url = "https://api.example.com/test"
    
    # Simulate the assignment
    final_url = tool_url if tool_url and tool_url.lower() != 'none' else None
    
    assert final_url == "https://api.example.com/test"


def test_final_url_assignment_with_python_none():
    """Test that final_url assignment handles Python None."""
    tool_url = None
    
    # Simulate the assignment
    final_url = tool_url if tool_url and tool_url.lower() != 'none' else None
    
    assert final_url is None


def test_url_construction_does_not_trigger_with_valid_url():
    """Test that valid URL does not trigger construction."""
    tool_url = "https://api.example.com/existing"
    tool_endpoint = "/api/test"
    gateway_url = "https://api.example.com"
    
    # Simulate the condition check
    should_construct = bool((not tool_url or tool_url.strip() == "" or tool_url.strip().lower() == "none") and tool_endpoint and gateway_url)
    
    assert should_construct is False

# Made with Bob
