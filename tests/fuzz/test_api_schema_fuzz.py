# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/test_api_schema_fuzz.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Schemathesis-based API endpoint fuzzing.
"""
import pytest
from fastapi.testclient import TestClient
from mcpgateway.main import app


class TestAPIEndpointFuzzing:
    """API endpoint fuzzing without schema dependency."""

    @pytest.mark.skip("Schemathesis schema loading requires auth configuration - use manual testing for now")
    def test_api_schema_fuzzing_placeholder(self):
        """Placeholder for future schema-based fuzzing."""
        pass


class TestAPIFuzzingCustom:
    """Custom API fuzzing scenarios not covered by schema."""

    def test_authentication_fuzzing(self):
        """Test authentication with various malformed credentials."""
        client = TestClient(app)

        auth_variants = [
            "Basic invalid",
            "Bearer token123",
            "Basic " + "x" * 1000,  # Very long auth
            "Digest username=test",
            "Negotiate token",
            "",
            None,
            "Basic", # Incomplete
            "Basic " + ":" * 100,  # Many colons
            "Basic " + "=" * 50,   # Many equals
        ]

        for auth in auth_variants:
            headers = {"Authorization": auth} if auth else {}
            response = client.get("/admin/tools", headers=headers)
            # Should return 401 or handle gracefully
            assert response.status_code in [401, 400, 422], f"Unexpected status for auth '{auth}': {response.status_code}"

    def test_large_payload_fuzzing(self):
        """Test endpoints with very large payloads."""
        client = TestClient(app)

        # Very large tool creation payload
        large_payload = {
            "name": "test_tool",
            "url": "http://example.com",
            "description": "x" * 10000,  # 10KB description
            "headers": {f"header_{i}": f"value_{i}" * 100 for i in range(50)},  # Many headers
            "tags": [f"tag_{i}" for i in range(1000)]  # Many tags
        }

        response = client.post(
            "/admin/tools",
            json=large_payload,
            headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="}
        )

        # Should handle large payloads gracefully (may reject or accept)
        assert response.status_code in [200, 201, 400, 401, 413, 422]

    def test_malformed_json_fuzzing(self):
        """Test endpoints with malformed JSON."""
        client = TestClient(app)

        malformed_json_cases = [
            '{"incomplete":',
            '{"key": "value",}',  # Trailing comma
            '{"key": value}',     # Unquoted value
            '{key: "value"}',     # Unquoted key
            '{"nested": {"incomplete"}',
            '[]',                 # Array instead of object
            '"string"',           # String instead of object
            '123',                # Number instead of object
            'null',               # Null instead of object
            '{"unicode": "\\uXXXX"}',  # Invalid unicode
        ]

        for malformed in malformed_json_cases:
            response = client.post(
                "/admin/tools",
                data=malformed,
                headers={
                    "Authorization": "Basic YWRtaW46Y2hhbmdlbWU=",
                    "Content-Type": "application/json"
                }
            )

            # Should handle malformed JSON gracefully
            assert response.status_code in [400, 401, 422], f"Unexpected status for malformed JSON: {response.status_code}"

    def test_unicode_fuzzing(self):
        """Test endpoints with various unicode characters."""
        client = TestClient(app)

        unicode_test_cases = [
            {"name": "test_ñäme", "url": "http://example.com"},
            {"name": "测试工具", "url": "http://example.com"},
            {"name": "🚀🔧⚡", "url": "http://example.com"},  # Emoji
            {"name": "\x00\x01\x02", "url": "http://example.com"},  # Control chars
            {"name": "A" * 1000, "url": "http://example.com"},  # Long ASCII
            {"name": "ñ" * 1000, "url": "http://example.com"},  # Long unicode
        ]

        for test_case in unicode_test_cases:
            response = client.post(
                "/admin/tools",
                json=test_case,
                headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="}
            )

            # Should handle unicode gracefully
            assert response.status_code in [200, 201, 400, 401, 422]

    def test_concurrent_request_fuzzing(self):
        """Test concurrent requests to check for race conditions."""
        import threading
        import time

        client = TestClient(app)
        results = []

        def make_request():
            try:
                response = client.post(
                    "/admin/tools",
                    json={"name": f"tool_{time.time()}", "url": "http://example.com"},
                    headers={"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="}
                )
                results.append(response.status_code)
            except Exception as e:
                results.append(f"Exception: {e}")

        # Start multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All requests should complete successfully or with expected errors
        for result in results:
            if isinstance(result, int):
                assert result in [200, 201, 400, 401, 422, 409], f"Unexpected concurrent status: {result}"
            else:
                # No exceptions should occur
                pytest.fail(f"Concurrent request failed: {result}")

    def test_content_type_fuzzing(self):
        """Test endpoints with various Content-Type headers."""
        client = TestClient(app)

        content_types = [
            "application/json",
            "application/json; charset=utf-8",
            "text/plain",
            "application/xml",
            "multipart/form-data",
            "application/x-www-form-urlencoded",
            "text/html",
            "image/png",
            "",
            None,
            "application/json; boundary=something",
            "application/json" + "x" * 1000,  # Very long
        ]

        test_data = '{"name": "test", "url": "http://example.com"}'

        for content_type in content_types:
            headers = {"Authorization": "Basic YWRtaW46Y2hhbmdlbWU="}
            if content_type is not None:
                headers["Content-Type"] = content_type

            response = client.post(
                "/admin/tools",
                data=test_data,
                headers=headers
            )

            # Should handle various content types gracefully
            assert response.status_code in [200, 201, 400, 401, 415, 422]
