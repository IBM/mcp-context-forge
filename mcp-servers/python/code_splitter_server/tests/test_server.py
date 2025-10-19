# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/code_splitter_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Code Splitter MCP Server (FastMCP).
"""

from code_splitter_server.server_fastmcp import splitter


def test_analyze_code_structure():
    """Test code analysis."""
    python_code = '''
def hello_world():
    """Print hello world."""
    print("Hello, World!")

class MyClass:
    def method(self):
        return "test"
'''
    result = splitter.analyze_code_structure(python_code)
    assert result["success"] is True
    assert result["function_count"] == 2  # hello_world + method (counts all functions)
    assert result["class_count"] == 1
    assert len(result["functions"]) == 2
    assert len(result["classes"]) == 1


def test_extract_functions_only():
    """Test function extraction."""
    python_code = '''
def func1():
    return 1

def func2(x, y):
    """Add two numbers."""
    return x + y
'''
    result = splitter.extract_functions_only(python_code)
    assert result["success"] is True
    assert result["function_count"] == 2
    assert len(result["functions"]) == 2


def test_extract_classes_only():
    """Test class extraction."""
    python_code = """
class BaseClass:
    def base_method(self):
        pass

class DerivedClass(BaseClass):
    def derived_method(self):
        pass
"""
    result = splitter.extract_classes_only(python_code)
    assert result["success"] is True
    assert result["class_count"] == 2
    assert len(result["classes"]) == 2


def test_split_python_code():
    """Test code splitting."""
    python_code = """
def func1():
    return 1

class MyClass:
    def method(self):
        return 2

def func2():
    return 3
"""
    # Use min_lines=1 since test functions are short
    result = splitter.split_python_code(python_code, min_lines=1)
    assert result["success"] is True
    assert "segments" in result
    assert result["total_segments"] > 0


def test_supported_languages():
    """Test getting supported languages."""
    languages = splitter.supported_languages
    assert isinstance(languages, dict)
    assert "python" in languages
    # Should have at least Python support
