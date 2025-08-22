# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/test_jsonrpc_fuzz.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Property-based fuzz testing for JSON-RPC validation.
"""
import json
from hypothesis import given, strategies as st, settings, example
import pytest
from mcpgateway.validation.jsonrpc import validate_request, validate_response, JSONRPCError


class TestJSONRPCRequestFuzzing:
    """Fuzz testing for JSON-RPC request validation."""

    @given(st.binary())
    @example(b"")  # Empty binary
    @example(b"\x00\x01\x02")  # Non-UTF8 bytes
    @example(b"\xff\xfe")  # BOM markers
    def test_validate_request_handles_binary_input(self, raw_bytes):
        """Test that binary input never crashes the validator."""
        try:
            # First try to decode as UTF-8, then parse as JSON
            text = raw_bytes.decode('utf-8', errors='ignore')
            data = json.loads(text)
            # Only validate if we get a dict (JSON-RPC expects dict)
            if isinstance(data, dict):
                validate_request(data)
        except (JSONRPCError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            # These are acceptable exceptions
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text())
    @example("")  # Empty string
    @example("null")  # Valid JSON but invalid request
    @example('{"incomplete":')  # Malformed JSON
    @example('{"jsonrpc": "2.0"}')  # Missing method
    def test_validate_request_handles_text_input(self, text_input):
        """Test that text input never crashes the validator."""
        try:
            data = json.loads(text_input)
            # Only validate if we get a dict (JSON-RPC expects dict)
            if isinstance(data, dict):
                validate_request(data)
        except (JSONRPCError, ValueError, TypeError, json.JSONDecodeError, AttributeError):
            # Expected exceptions for invalid input
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.dictionaries(
        keys=st.text(min_size=1, max_size=50),
        values=st.recursive(
            st.one_of(st.none(), st.booleans(), st.integers(), st.floats(), st.text()),
            lambda children: st.lists(children) | st.dictionaries(st.text(), children),
            max_leaves=20
        ),
        max_size=20
    ))
    def test_validate_request_handles_arbitrary_dicts(self, data):
        """Test arbitrary dictionary structures."""
        try:
            validate_request(data)
        except (JSONRPCError, ValueError, TypeError):
            # Expected exceptions for invalid structures
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=0, max_size=10))
    def test_jsonrpc_version_field_fuzzing(self, version):
        """Test jsonrpc version field with various inputs."""
        request = {
            "jsonrpc": version,
            "method": "test",
            "id": 1
        }
        try:
            validate_request(request)
            # If validation succeeds, it should be version "2.0"
            assert version == "2.0"
        except JSONRPCError:
            # Expected for non-"2.0" versions
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(
        st.text(min_size=0, max_size=100),
        st.integers(),
        st.floats(),
        st.booleans(),
        st.none(),
        st.lists(st.text()),
        st.dictionaries(st.text(), st.text())
    ))
    def test_method_field_fuzzing(self, method):
        """Test method field with various data types."""
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": 1
        }
        try:
            validate_request(request)
            # If validation succeeds, method should be non-empty string
            assert isinstance(method, str) and len(method) > 0
        except JSONRPCError:
            # Expected for invalid methods
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(
        st.integers(),
        st.text(min_size=0, max_size=100),
        st.booleans(),
        st.floats(),
        st.none(),
        st.lists(st.integers()),
        st.dictionaries(st.text(), st.text())
    ))
    def test_id_field_fuzzing(self, request_id):
        """Test ID field with various data types."""
        request = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": request_id
        }
        try:
            validate_request(request)
            # If validation succeeds, ID should be string or int (not bool)
            assert isinstance(request_id, (str, int)) and not isinstance(request_id, bool)
        except JSONRPCError:
            # Expected for invalid IDs
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(
        st.lists(st.integers()),
        st.dictionaries(st.text(), st.text()),
        st.text(),
        st.integers(),
        st.booleans(),
        st.none()
    ))
    def test_params_field_fuzzing(self, params):
        """Test params field with various data types."""
        request = {
            "jsonrpc": "2.0",
            "method": "test",
            "params": params,
            "id": 1
        }
        try:
            validate_request(request)
            # If validation succeeds, params should be dict, list, or None
            assert isinstance(params, (dict, list, type(None)))
        except JSONRPCError:
            # Expected for invalid params
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=st.one_of(st.text(), st.integers(), st.booleans(), st.none()),
        min_size=0,
        max_size=10
    ))
    def test_extra_fields_fuzzing(self, extra_fields):
        """Test requests with extra fields."""
        request = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": 1,
            **extra_fields
        }
        try:
            validate_request(request)
            # Should succeed regardless of extra fields
        except JSONRPCError:
            # Should only fail for core field validation issues
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


class TestJSONRPCResponseFuzzing:
    """Fuzz testing for JSON-RPC response validation."""

    @given(st.dictionaries(
        keys=st.text(min_size=1, max_size=50),
        values=st.recursive(
            st.one_of(st.none(), st.booleans(), st.integers(), st.floats(), st.text()),
            lambda children: st.lists(children) | st.dictionaries(st.text(), children),
            max_leaves=20
        ),
        max_size=20
    ))
    def test_validate_response_handles_arbitrary_dicts(self, data):
        """Test response validation with arbitrary dictionary structures."""
        try:
            validate_response(data)
        except (JSONRPCError, ValueError, TypeError):
            # Expected exceptions for invalid structures
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(
        st.integers(),
        st.text(min_size=0, max_size=100),
        st.booleans(),
        st.floats(),
        st.none(),
        st.lists(st.integers()),
        st.dictionaries(st.text(), st.text())
    ))
    def test_response_id_field_fuzzing(self, response_id):
        """Test response ID field with various data types."""
        response = {
            "jsonrpc": "2.0",
            "result": "success",
            "id": response_id
        }
        try:
            validate_response(response)
            # If validation succeeds, ID should be string, int, or None (not bool)
            assert isinstance(response_id, (str, int, type(None))) and not isinstance(response_id, bool)
        except JSONRPCError:
            # Expected for invalid IDs
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(
        st.text(),
        st.integers(),
        st.booleans(),
        st.none(),
        st.lists(st.text()),
        st.dictionaries(st.text(), st.text())
    ))
    def test_result_field_fuzzing(self, result):
        """Test result field with various data types."""
        response = {
            "jsonrpc": "2.0",
            "result": result,
            "id": 1
        }
        try:
            validate_response(response)
            # Should succeed with any result type
        except JSONRPCError:
            # Should not fail due to result content
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.one_of(
        st.dictionaries(
            keys=st.sampled_from(["code", "message", "data"]),
            values=st.one_of(st.integers(), st.text(), st.booleans()),
            min_size=1,
            max_size=3
        ),
        st.text(),
        st.integers(),
        st.booleans(),
        st.none(),
        st.lists(st.text())
    ))
    def test_error_field_fuzzing(self, error):
        """Test error field with various structures."""
        response = {
            "jsonrpc": "2.0",
            "error": error,
            "id": 1
        }
        try:
            validate_response(response)
            # If validation succeeds, error should be proper dict with code/message
            if isinstance(error, dict):
                assert "code" in error and "message" in error
                assert isinstance(error["code"], int)
                assert isinstance(error["message"], str)
        except JSONRPCError:
            # Expected for invalid error structures
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    def test_response_missing_required_fields(self):
        """Test responses missing required result/error fields."""
        response = {
            "jsonrpc": "2.0",
            "id": 1
        }
        try:
            validate_response(response)
            pytest.fail("Should have failed validation")
        except JSONRPCError:
            # Expected
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    def test_response_both_result_and_error(self):
        """Test responses with both result and error fields."""
        response = {
            "jsonrpc": "2.0",
            "result": "success",
            "error": {"code": -1, "message": "error"},
            "id": 1
        }
        try:
            validate_response(response)
            pytest.fail("Should have failed validation")
        except JSONRPCError:
            # Expected
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


class TestJSONRPCErrorFuzzing:
    """Fuzz testing for JSONRPCError class."""

    @given(st.integers(), st.text(min_size=0, max_size=200))
    def test_jsonrpc_error_creation(self, code, message):
        """Test JSONRPCError creation with various inputs."""
        try:
            error = JSONRPCError(code, message)
            assert error.code == code
            assert error.message == message
            # Should be able to convert to dict
            error_dict = error.to_dict()
            assert isinstance(error_dict, dict)
            assert error_dict["jsonrpc"] == "2.0"
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(
        st.integers(),
        st.text(min_size=0, max_size=200),
        st.one_of(st.none(), st.text(), st.integers(), st.dictionaries(st.text(), st.text())),
        st.one_of(st.none(), st.integers(), st.text())
    )
    def test_jsonrpc_error_with_data_and_id(self, code, message, data, request_id):
        """Test JSONRPCError with optional data and request_id."""
        try:
            error = JSONRPCError(code, message, data, request_id)
            assert error.code == code
            assert error.message == message
            assert error.data == data
            assert error.request_id == request_id

            # Should be able to convert to dict
            error_dict = error.to_dict()
            assert isinstance(error_dict, dict)
            assert error_dict["jsonrpc"] == "2.0"
            assert error_dict["error"]["code"] == code
            assert error_dict["error"]["message"] == message
            assert error_dict["request_id"] == request_id

            if data is not None:
                assert error_dict["error"]["data"] == data
            else:
                assert "data" not in error_dict["error"]

        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")
