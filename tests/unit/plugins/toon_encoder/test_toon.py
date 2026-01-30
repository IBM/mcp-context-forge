# -*- coding: utf-8 -*-
"""Unit tests for TOON encoder/decoder.

Tests the pure Python TOON implementation against the spec v3.0.
"""

import json
import math

import pytest

from plugins.toon_encoder.toon import (
    _encode_key,
    _encode_string,
    _is_simple_value,
    _needs_quotes,
    _try_columnar_encoding,
    decode,
    encode,
    estimate_token_savings,
)


class TestEncodePrimitives:
    """Test encoding of primitive values."""

    def test_encode_null(self):
        """Null encodes to 'null'."""
        assert encode(None) == "null"

    def test_encode_true(self):
        """True encodes to 'true'."""
        assert encode(True) == "true"

    def test_encode_false(self):
        """False encodes to 'false'."""
        assert encode(False) == "false"

    def test_encode_integer(self):
        """Integers encode as-is."""
        assert encode(0) == "0"
        assert encode(42) == "42"
        assert encode(-17) == "-17"
        assert encode(1000000) == "1000000"

    def test_encode_float(self):
        """Floats encode with minimal representation."""
        assert encode(3.14) == "3.14"
        assert encode(-2.5) == "-2.5"
        assert encode(1.0) == "1"  # Whole floats drop .0
        assert encode(0.0) == "0"

    def test_encode_float_special(self):
        """Special float values convert to null per TOON spec."""
        assert encode(float("nan")) == "null"
        assert encode(float("inf")) == "null"  # Per TOON spec: Infinity -> null
        assert encode(float("-inf")) == "null"  # Per TOON spec: -Infinity -> null

    def test_encode_simple_string(self):
        """Simple strings encode without quotes."""
        assert encode("hello") == "hello"
        assert encode("world") == "world"
        assert encode("simple_name") == "simple_name"

    def test_encode_string_with_space(self):
        """Strings with spaces don't need quotes in TOON."""
        assert encode("hello world") == "hello world"

    def test_encode_string_needs_quotes(self):
        """Strings with special chars need quotes."""
        assert encode("has,comma") == '"has,comma"'
        assert encode("has:colon") == '"has:colon"'
        assert encode("has\nnewline") == '"has\\nnewline"'
        assert encode("") == '""'
        assert encode("null") == '"null"'  # Reserved word
        assert encode("true") == '"true"'
        assert encode("false") == '"false"'
        assert encode("123") == '"123"'  # Looks like number


class TestEncodeArrays:
    """Test encoding of arrays."""

    def test_encode_empty_array(self):
        """Empty arrays encode to [0]: per TOON spec."""
        assert encode([]) == "[0]:"

    def test_encode_simple_array(self):
        """Simple arrays use compact format."""
        assert encode([1, 2, 3]) == "[3]: 1,2,3"
        assert encode(["a", "b", "c"]) == "[3]: a,b,c"
        assert encode([True, False, None]) == "[3]: true,false,null"

    def test_encode_mixed_array(self):
        """Mixed type arrays work."""
        assert encode([1, "two", True]) == "[3]: 1,two,true"

    def test_encode_nested_array(self):
        """Nested arrays are handled."""
        result = encode([[1, 2], [3, 4]])
        assert "[2]:" in result


class TestEncodeObjects:
    """Test encoding of objects (dicts)."""

    def test_encode_empty_object(self):
        """Empty objects encode to empty string per TOON spec."""
        assert encode({}) == ""

    def test_encode_simple_object(self):
        """Simple objects use key: value format."""
        assert encode({"a": 1}) == "a: 1"
        result = encode({"a": 1, "b": 2})
        assert "a: 1" in result
        assert "b: 2" in result

    def test_encode_nested_object(self):
        """Nested objects are handled."""
        result = encode({"outer": {"inner": 1}})
        assert "outer:" in result
        assert "inner: 1" in result

    def test_encode_object_with_complex_keys(self):
        """Keys with special chars are quoted."""
        result = encode({"has space": 1})
        assert '"has space": 1' in result


class TestColumnarEncoding:
    """Test columnar encoding for arrays of objects."""

    def test_columnar_simple(self):
        """Arrays of similar objects use columnar format."""
        data = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
        result = encode(data)
        assert "[2]{" in result
        assert "x" in result
        assert "y" in result

    def test_columnar_not_applied_for_different_keys(self):
        """Columnar not used when objects have different keys."""
        data = [{"a": 1}, {"b": 2}]
        result = _try_columnar_encoding(data)
        assert result is None

    def test_columnar_not_applied_for_nested(self):
        """Columnar not used when objects have nested values."""
        data = [{"a": {"nested": 1}}, {"a": {"nested": 2}}]
        result = _try_columnar_encoding(data)
        assert result is None


class TestDecodePrimitives:
    """Test decoding of primitive values."""

    def test_decode_null(self):
        """'null' decodes to None."""
        assert decode("null") is None

    def test_decode_true(self):
        """'true' decodes to True."""
        assert decode("true") is True

    def test_decode_false(self):
        """'false' decodes to False."""
        assert decode("false") is False

    def test_decode_integer(self):
        """Integers decode correctly."""
        assert decode("42") == 42
        assert decode("-17") == -17
        assert decode("0") == 0

    def test_decode_float(self):
        """Floats decode correctly."""
        assert decode("3.14") == 3.14
        assert decode("-2.5") == -2.5

    def test_decode_unquoted_string(self):
        """Unquoted strings decode as-is."""
        assert decode("hello") == "hello"
        assert decode("simple") == "simple"

    def test_decode_quoted_string(self):
        """Quoted strings decode with unescaping."""
        assert decode('"hello"') == "hello"
        assert decode('"with\\nnewline"') == "with\nnewline"
        assert decode('"with\\ttab"') == "with\ttab"


class TestDecodeArrays:
    """Test decoding of arrays."""

    def test_decode_empty_array(self):
        """[0]: decodes to empty list per TOON spec."""
        assert decode("[0]:") == []

    def test_decode_simple_array(self):
        """Simple arrays decode correctly."""
        assert decode("[3]: 1,2,3") == [1, 2, 3]
        assert decode("[2]: a,b") == ["a", "b"]

    def test_decode_columnar_array(self):
        """Columnar arrays decode to list of dicts."""
        toon = "[2]{x,y}:\n 1,2\n 3,4"
        result = decode(toon)
        assert result == [{"x": 1, "y": 2}, {"x": 3, "y": 4}]


class TestDecodeObjects:
    """Test decoding of objects."""

    def test_decode_empty_object(self):
        """Empty string decodes to empty dict per TOON spec."""
        assert decode("") == {}

    def test_decode_simple_object(self):
        """Simple objects decode correctly."""
        assert decode("a: 1") == {"a": 1}
        assert decode("a: 1\nb: 2") == {"a": 1, "b": 2}

    def test_decode_object_with_string_value(self):
        """String values decode correctly."""
        assert decode("name: alice") == {"name": "alice"}


class TestRoundTrip:
    """Test encode->decode round-trip preserves data."""

    @pytest.mark.parametrize(
        "data",
        [
            None,
            True,
            False,
            42,
            3.14,
            "hello",
            [],
            [1, 2, 3],
            {},
            {"a": 1},
            {"a": 1, "b": "two", "c": True},
            [{"x": 1}, {"x": 2}],
            {"nested": {"deep": [1, 2, 3]}},
        ],
    )
    def test_round_trip(self, data):
        """Encode then decode returns original data."""
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_round_trip_complex(self):
        """Complex nested structure round-trips."""
        data = {
            "users": [
                {"id": 1, "name": "alice", "active": True},
                {"id": 2, "name": "bob", "active": False},
            ],
            "metadata": {"count": 2, "page": 1},
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data


class TestTokenSavings:
    """Test token savings estimation."""

    def test_savings_simple_object(self):
        """Simple objects should show savings."""
        data = {"name": "alice", "age": 30, "active": True}
        json_str = json.dumps(data)
        json_len, toon_len, savings = estimate_token_savings(json_str)
        assert toon_len < json_len
        assert savings > 0

    def test_savings_array_of_objects(self):
        """Arrays of objects should show significant savings."""
        data = [
            {"id": i, "name": f"user{i}", "score": i * 10}
            for i in range(10)
        ]
        json_str = json.dumps(data)
        json_len, toon_len, savings = estimate_token_savings(json_str)
        assert toon_len < json_len
        assert savings > 20  # Should save at least 20%

    def test_savings_invalid_json(self):
        """Invalid JSON returns zero savings."""
        json_len, toon_len, savings = estimate_token_savings("not valid json {")
        assert savings == 0.0


class TestHelperFunctions:
    """Test internal helper functions."""

    def test_needs_quotes_empty(self):
        """Empty strings need quotes."""
        assert _needs_quotes("") is True

    def test_needs_quotes_reserved(self):
        """Reserved words need quotes."""
        assert _needs_quotes("null") is True
        assert _needs_quotes("true") is True
        assert _needs_quotes("false") is True

    def test_needs_quotes_special_chars(self):
        """Special characters need quotes."""
        assert _needs_quotes("has,comma") is True
        assert _needs_quotes("has:colon") is True
        assert _needs_quotes("has\nnewline") is True

    def test_needs_quotes_number_like(self):
        """Number-like strings need quotes."""
        assert _needs_quotes("123") is True
        assert _needs_quotes("3.14") is True
        assert _needs_quotes("-42") is True

    def test_needs_quotes_simple(self):
        """Simple strings don't need quotes."""
        assert _needs_quotes("hello") is False
        assert _needs_quotes("simple_name") is False

    def test_is_simple_value(self):
        """Simple values are primitives only."""
        assert _is_simple_value(None) is True
        assert _is_simple_value(True) is True
        assert _is_simple_value(42) is True
        assert _is_simple_value("hello") is True
        assert _is_simple_value([1, 2]) is False
        assert _is_simple_value({"a": 1}) is False

    def test_encode_key(self):
        """Keys are encoded correctly."""
        assert _encode_key("simple") == "simple"
        assert _encode_key("has space") == '"has space"'
        assert _encode_key("has:colon") == '"has:colon"'

    def test_encode_string_escapes(self):
        """String escaping works correctly."""
        assert _encode_string("normal") == "normal"
        assert _encode_string("has\nnewline") == '"has\\nnewline"'
        assert _encode_string('has"quote') == '"has\\"quote"'
        assert _encode_string("has\\backslash") == '"has\\\\backslash"'


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_encode_tuple(self):
        """Tuples are encoded as arrays."""
        assert encode((1, 2, 3)) == "[3]: 1,2,3"

    def test_encode_unsupported_type(self):
        """Unsupported types raise TypeError."""
        with pytest.raises(TypeError):
            encode(object())

    def test_decode_empty_string(self):
        """Empty string decodes to empty object per TOON spec."""
        assert decode("") == {}
        assert decode("   ") == {}

    def test_unicode_strings(self):
        """Unicode strings work correctly."""
        data = {"emoji": "Hello! Nice!"}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_large_numbers(self):
        """Large numbers encode correctly."""
        assert encode(10**20) == "100000000000000000000"
        assert decode("100000000000000000000") == 10**20

    def test_scientific_notation(self):
        """Scientific notation is handled."""
        assert decode("1e10") == 1e10
        assert decode("1.5e-5") == 1.5e-5


class TestUnicodeAndSpecialCharacters:
    """Test unicode and special character handling."""

    def test_unicode_emoji(self):
        """Emoji characters encode/decode correctly."""
        data = {"message": "Hello 👋 World 🌍"}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_unicode_cjk(self):
        """CJK characters encode/decode correctly."""
        data = {"greeting": "你好世界", "japanese": "こんにちは"}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_unicode_arabic(self):
        """Arabic/RTL characters encode/decode correctly."""
        data = {"arabic": "مرحبا بالعالم"}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_special_chars_in_values(self):
        """Special characters in values are properly quoted."""
        data = {
            "comma": "a,b,c",
            "colon": "key:value",
            "brackets": "[1,2,3]",
            "braces": "{a:b}",
            "newline": "line1\nline2",
            "tab": "col1\tcol2",
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_backslash_handling(self):
        """Backslashes are properly escaped."""
        data = {"path": "C:\\Users\\test\\file.txt"}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_quote_handling(self):
        """Quotes in strings are properly escaped."""
        data = {"quoted": 'He said "hello"'}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data


class TestDeeplyNestedStructures:
    """Test deeply nested data structures."""

    def test_deeply_nested_objects(self):
        """Deeply nested objects encode/decode correctly."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {"value": "deep"}
                    }
                }
            }
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_object_with_nested_array(self):
        """Object containing a simple nested array works correctly."""
        data = {
            "items": [1, 2, 3, 4, 5],
            "name": "test",
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_nested_object_with_array(self):
        """Nested object containing array works correctly."""
        data = {
            "outer": {
                "inner": {
                    "values": [1, 2, 3]
                }
            }
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_columnar_array_in_nested_object(self):
        """Columnar array inside nested object works correctly."""
        data = {
            "response": {
                "users": [
                    {"id": 1, "name": "alice"},
                    {"id": 2, "name": "bob"},
                ],
            }
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_object_with_multiple_arrays(self):
        """Object with multiple array fields works correctly."""
        data = {
            "ids": [1, 2, 3],
            "names": ["alice", "bob", "charlie"],
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data


class TestKeyQuoting:
    """Test object key quoting rules.

    Note: The current decoder has limitations with single-line quoted keys.
    These tests verify the encoder produces correctly quoted keys.
    """

    def test_simple_keys_unquoted(self):
        """Simple alphanumeric keys are not quoted."""
        data = {"simple": 1, "with_underscore": 2, "camelCase": 3}
        encoded = encode(data)
        assert '"simple"' not in encoded
        assert '"with_underscore"' not in encoded
        assert '"camelCase"' not in encoded

    def test_keys_with_spaces_quoted_in_encoding(self):
        """Keys with spaces are quoted in encoding."""
        data = {"has space": 1}
        encoded = encode(data)
        assert '"has space"' in encoded

    def test_keys_with_colons_quoted_in_encoding(self):
        """Keys with colons are quoted in encoding."""
        data = {"key:colon": 1}
        encoded = encode(data)
        assert '"key:colon"' in encoded

    def test_valid_key_patterns(self):
        """Keys matching ^[A-Za-z_][A-Za-z0-9_.]*$ are unquoted."""
        from plugins.toon_encoder.toon import _encode_key

        # Valid patterns - should NOT be quoted
        assert _encode_key("simple") == "simple"
        assert _encode_key("_private") == "_private"
        assert _encode_key("camelCase") == "camelCase"
        assert _encode_key("with_underscore") == "with_underscore"
        assert _encode_key("with.dot") == "with.dot"
        assert _encode_key("name123") == "name123"

        # Invalid patterns - should BE quoted
        assert _encode_key("has space").startswith('"')
        assert _encode_key("123numeric").startswith('"')
        assert _encode_key("key:colon").startswith('"')
        assert _encode_key("key,comma").startswith('"')
        assert _encode_key("null").startswith('"')  # Reserved word
        assert _encode_key("").startswith('"')  # Empty


class TestArrayFormats:
    """Test various array encoding formats."""

    def test_empty_array(self):
        """Empty arrays encode correctly per TOON spec."""
        assert encode([]) == "[0]:"
        assert decode("[0]:") == []

    def test_single_element_array(self):
        """Single element arrays work correctly."""
        assert decode("[1]: 42") == [42]
        assert decode("[1]: hello") == ["hello"]

    def test_mixed_type_array(self):
        """Arrays with mixed types work correctly."""
        data = [1, "two", True, None, 3.14]
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_array_of_empty_objects(self):
        """Arrays of empty objects work correctly."""
        data = [{}, {}, {}]
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_array_with_null_values(self):
        """Arrays containing null values work correctly."""
        data = [1, None, 3, None, 5]
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_columnar_with_boolean_values(self):
        """Columnar format handles boolean values."""
        data = [
            {"id": 1, "active": True},
            {"id": 2, "active": False},
            {"id": 3, "active": True},
        ]
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_columnar_with_null_values(self):
        """Columnar format handles null values."""
        data = [
            {"id": 1, "value": "a"},
            {"id": 2, "value": None},
            {"id": 3, "value": "c"},
        ]
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data


class TestNumericEdgeCases:
    """Test numeric edge cases."""

    def test_negative_zero(self):
        """Negative zero normalizes to positive zero."""
        assert encode(-0.0) == "0"

    def test_very_small_float(self):
        """Very small floats are handled."""
        data = {"tiny": 0.000001}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded["tiny"] == pytest.approx(0.000001)

    def test_very_large_float(self):
        """Very large floats are handled."""
        data = {"big": 1e15}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded["big"] == pytest.approx(1e15)

    def test_negative_numbers(self):
        """Negative numbers work correctly."""
        data = {"neg_int": -42, "neg_float": -3.14}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_integer_float_distinction(self):
        """Integer-valued floats are encoded as integers."""
        assert encode(5.0) == "5"
        assert encode(100.0) == "100"


class TestEmptyAndNullValues:
    """Test empty and null value handling."""

    def test_empty_string_value(self):
        """Empty string values are quoted."""
        data = {"empty": ""}
        encoded = encode(data)
        assert '""' in encoded
        decoded = decode(encoded)
        assert decoded == data

    def test_null_value(self):
        """Null values encode/decode correctly."""
        data = {"value": None}
        encoded = encode(data)
        assert "null" in encoded
        decoded = decode(encoded)
        assert decoded == data

    def test_empty_object(self):
        """Empty objects encode/decode correctly per TOON spec."""
        data = {}
        encoded = encode(data)
        assert encoded == ""  # Empty object is empty document
        decoded = decode(encoded)
        assert decoded == data

    def test_object_with_empty_nested(self):
        """Objects with empty nested structures work."""
        data = {"empty_obj": {}, "empty_arr": [], "value": 1}
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data


class TestRealWorldScenarios:
    """Test real-world data scenarios."""

    def test_api_response_users(self):
        """Typical API user list response."""
        data = {
            "users": [
                {"id": 1, "username": "alice", "email": "alice@example.com", "active": True},
                {"id": 2, "username": "bob", "email": "bob@example.com", "active": True},
                {"id": 3, "username": "charlie", "email": "charlie@example.com", "active": False},
            ],
            "pagination": {"page": 1, "per_page": 10, "total": 3},
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_database_query_result(self):
        """Typical database query result."""
        data = {
            "rows": [
                {"product_id": 101, "name": "Widget", "price": 29.99, "in_stock": True},
                {"product_id": 102, "name": "Gadget", "price": 49.99, "in_stock": False},
                {"product_id": 103, "name": "Doohickey", "price": 19.99, "in_stock": True},
            ],
            "query_time_ms": 12,
            "total_rows": 3,
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_config_structure(self):
        """Typical configuration structure."""
        data = {
            "server": {
                "host": "localhost",
                "port": 8080,
                "ssl": {"enabled": True, "cert_path": "/etc/ssl/cert.pem"},
            },
            "database": {
                "url": "postgresql://localhost/db",
                "pool_size": 10,
            },
            "features": ["auth", "caching", "logging"],
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_log_entries(self):
        """Typical log entry structure."""
        data = {
            "logs": [
                {"timestamp": "2024-01-15T10:30:00Z", "level": "INFO", "message": "Server started"},
                {"timestamp": "2024-01-15T10:30:05Z", "level": "DEBUG", "message": "Connection established"},
                {"timestamp": "2024-01-15T10:30:10Z", "level": "ERROR", "message": "Failed to connect"},
            ]
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data

    def test_mcp_tool_result(self):
        """Typical MCP tool result structure."""
        data = {
            "content": [
                {
                    "type": "text",
                    "text": "Search results for query",
                },
                {
                    "type": "text",
                    "text": "Found 5 matching documents",
                },
            ],
            "isError": False,
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded == data
