# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/test_jsonpath_fuzz.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Property-based fuzz testing for JSONPath processing.
"""

# Third-Party
from fastapi import HTTPException
from hypothesis import given
from hypothesis import strategies as st
import pytest

# First-Party
from mcpgateway.main import jsonpath_modifier


class TestJSONPathFuzzing:
    """Fuzz testing for JSONPath expression processing."""

    @given(st.text(min_size=1, max_size=200))
    def test_jsonpath_modifier_never_crashes(self, path_expression):
        """Test that arbitrary JSONPath expressions never crash the system."""
        test_data = {"a": 1, "b": [1, 2, 3], "c": {"d": "test"}}

        try:
            result = jsonpath_modifier(test_data, path_expression)
            # If it succeeds, result should be a list or dict
            assert isinstance(result, (list, dict))
        except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError, ZeroDivisionError):
            # These are acceptable exceptions for invalid paths
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=1, max_size=100))
    def test_jsonpath_with_dollar_expressions(self, expression):
        """Test JSONPath expressions containing $ operators."""
        # Only test if expression contains $, otherwise skip
        if "$" not in expression:
            return
        test_data = {"root": {"items": [{"id": 1}, {"id": 2}]}}

        try:
            jsonpath_modifier(test_data, expression)
        except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError):
            # Expected for invalid expressions
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=1, max_size=100))
    def test_jsonpath_with_brackets(self, expression):
        """Test JSONPath expressions with array notation."""
        # Only test if expression contains brackets, otherwise skip
        if "[" not in expression and "]" not in expression:
            return
        test_data = {"items": [{"a": 1}, {"a": 2}, {"a": 3}]}

        try:
            jsonpath_modifier(test_data, expression)
        except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError):
            # Expected for invalid bracket expressions
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=1, max_size=100))
    def test_jsonpath_with_dots(self, expression):
        """Test JSONPath expressions with property access."""
        # Only test if expression contains dots, otherwise skip
        if "." not in expression:
            return
        test_data = {"a": {"b": {"c": "value"}}, "x": {"y": [1, 2, 3]}}

        try:
            jsonpath_modifier(test_data, expression)
        except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError):
            # Expected for invalid property paths
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(
        st.one_of(
            st.dictionaries(
                keys=st.text(min_size=1, max_size=20),
                values=st.recursive(
                    st.one_of(st.integers(), st.text(max_size=50), st.booleans(), st.none()), lambda children: st.lists(children) | st.dictionaries(st.text(max_size=10), children), max_leaves=10
                ),
                max_size=10,
            ),
            st.lists(st.dictionaries(keys=st.text(min_size=1, max_size=10), values=st.one_of(st.integers(), st.text(max_size=20)), max_size=5), max_size=5),
            st.integers(),
            st.text(max_size=100),
            st.booleans(),
            st.none(),
        )
    )
    def test_jsonpath_with_arbitrary_data(self, data):
        """Test JSONPath processing with arbitrary data structures."""
        expressions = ["$", "$.*", "$[*]", "$..*", "$..name", "$[0]"]

        for expr in expressions:
            try:
                result = jsonpath_modifier(data, expr)
                assert isinstance(result, (list, dict))
            except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError):
                # Expected for data/expression mismatches
                pass
            except Exception as e:
                pytest.fail(f"Unexpected exception with expr '{expr}' and data {type(data)}: {type(e).__name__}: {e}")

    @given(st.dictionaries(keys=st.text(min_size=1, max_size=20), values=st.text(min_size=1, max_size=50), min_size=1, max_size=5))
    def test_jsonpath_with_mappings(self, mappings):
        """Test JSONPath processing with arbitrary mappings."""
        test_data = {"items": [{"name": "test1", "value": 1}, {"name": "test2", "value": 2}]}
        base_expression = "$[*]"

        try:
            result = jsonpath_modifier(test_data, base_expression, mappings)
            assert isinstance(result, (list, dict))
        except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError):
            # Expected for invalid mapping expressions
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=0, max_size=200))
    def test_jsonpath_empty_and_whitespace_expressions(self, expression):
        """Test JSONPath with empty, whitespace, and unusual characters."""
        test_data = {"a": 1}

        try:
            result = jsonpath_modifier(test_data, expression)
            if not expression.strip():
                # Empty expressions should use default "$[*]"
                assert isinstance(result, (list, dict))
        except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError):
            # Expected for invalid expressions
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=1, max_size=100))
    def test_jsonpath_with_special_characters(self, expression):
        """Test JSONPath with special characters that might break parsing."""
        # Only test if expression contains special characters, otherwise skip
        if not any(char in expression for char in '!@#%^&*()=+{}|;:",<>?/~`'):
            return
        test_data = {"field": "value", "array": [1, 2, 3]}

        try:
            jsonpath_modifier(test_data, expression)
        except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError):
            # Expected for expressions with invalid special chars
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    @given(st.text(min_size=100, max_size=1000))
    def test_jsonpath_very_long_expressions(self, expression):
        """Test JSONPath with very long expressions."""
        test_data = {"data": "test"}

        try:
            jsonpath_modifier(test_data, expression)
        except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError):
            # Expected for very long/complex expressions
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

    def test_jsonpath_recursive_expressions(self):
        """Test deeply recursive JSONPath expressions."""
        test_data = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        expressions = [
            "$.." + ".".join(["a"] * 50),  # Very deep property access
            "$" + "[0]" * 20,  # Deep array access
            "$..*" * 10,  # Repeated recursive descent
        ]

        for expr in expressions:
            try:
                jsonpath_modifier(test_data, expr)
            except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError):
                # Expected for complex recursive expressions
                pass
            except Exception as e:
                pytest.fail(f"Unexpected exception with expr '{expr}': {type(e).__name__}: {e}")

    @given(st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=10))
    def test_jsonpath_chained_expressions(self, parts):
        """Test chained JSONPath expressions."""
        test_data = {"root": {"items": [{"name": "test"}]}}

        # Create chained expression
        expression = "$" + "".join(f".{part}" for part in parts)

        try:
            jsonpath_modifier(test_data, expression)
        except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError):
            # Expected for invalid chained expressions
            pass
        except Exception as e:
            pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


class TestJSONPathEdgeCases:
    """Edge case testing for JSONPath processing."""

    def test_jsonpath_null_data(self):
        """Test JSONPath with null data."""
        try:
            result = jsonpath_modifier(None, "$")
            assert isinstance(result, list)
        except (HTTPException, ValueError, TypeError):
            # Expected for null data
            pass

    def test_jsonpath_empty_data(self):
        """Test JSONPath with empty data structures."""
        test_cases = [{}, [], "", 0, False]

        for data in test_cases:
            try:
                result = jsonpath_modifier(data, "$")
                assert isinstance(result, (list, dict))
            except (HTTPException, ValueError, TypeError):
                # Expected for some empty data types
                pass

    def test_jsonpath_circular_data(self):
        """Test JSONPath with circular references (if supported)."""
        data = {"a": 1}
        data["self"] = data  # Create circular reference

        try:
            result = jsonpath_modifier(data, "$.a")
            assert isinstance(result, list)
        except (HTTPException, ValueError, TypeError, RecursionError):
            # Expected for circular data
            pass

    @given(st.integers(min_value=-1000, max_value=1000))
    def test_jsonpath_numeric_indices(self, index):
        """Test JSONPath with various numeric indices."""
        test_data = {"items": list(range(10))}
        expression = f"$.items[{index}]"

        try:
            result = jsonpath_modifier(test_data, expression)
            assert isinstance(result, list)
        except (HTTPException, ValueError, TypeError, IndexError):
            # Expected for out-of-bounds indices
            pass

    def test_jsonpath_unicode_expressions(self):
        """Test JSONPath with unicode characters."""
        test_data = {"ñamé": "tést", "数据": [1, 2, 3]}
        expressions = ["$.ñamé", "$.数据[*]", "$..tést"]

        for expr in expressions:
            try:
                result = jsonpath_modifier(test_data, expr)
                assert isinstance(result, (list, dict))
            except (HTTPException, ValueError, TypeError, UnicodeError):
                # Expected for unicode handling issues
                pass
