#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/fuzzers/fuzz_jsonpath.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Coverage-guided fuzzing for JSONPath processing using Atheris.
"""

# Standard
import json
import os
import sys

# Third-Party
import atheris

# Ensure the project is in the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

try:
    # Third-Party
    from fastapi import HTTPException

    # First-Party
    from mcpgateway.main import jsonpath_modifier
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)


def TestOneInput(data: bytes) -> None:  # noqa: N802
    """Fuzz target for JSONPath processing.

    Args:
        data: Raw bytes from Atheris fuzzer
    """
    fdp = atheris.FuzzedDataProvider(data)

    try:
        if fdp.remaining_bytes() < 1:
            return

        # Generate test data structure
        choice = fdp.ConsumeIntInRange(0, 4)

        if choice == 0:
            # Simple object
            test_data = {"name": fdp.ConsumeUnicodeNoSurrogates(50), "value": fdp.ConsumeIntInRange(0, 1000), "enabled": fdp.ConsumeBool()}
        elif choice == 1:
            # Array of objects
            test_data = {"items": [{"id": i, "data": fdp.ConsumeUnicodeNoSurrogates(20)} for i in range(fdp.ConsumeIntInRange(0, 10))]}
        elif choice == 2:
            # Nested structure
            test_data = {"root": {"nested": {"deep": {"value": fdp.ConsumeUnicodeNoSurrogates(30)}}}}
        elif choice == 3:
            # Mixed structure
            test_data = {
                "string": fdp.ConsumeUnicodeNoSurrogates(40),
                "number": fdp.ConsumeIntInRange(-1000, 1000),
                "array": [fdp.ConsumeIntInRange(0, 100) for _ in range(fdp.ConsumeIntInRange(0, 5))],
                "object": {"key": fdp.ConsumeUnicodeNoSurrogates(20)},
            }
        else:
            # Raw data
            try:
                raw_str = fdp.ConsumeUnicodeNoSurrogates(100)
                test_data = json.loads(raw_str) if raw_str else {}
            except (json.JSONDecodeError, ValueError):
                test_data = {"fallback": "data"}

        # Generate JSONPath expression
        expr_choice = fdp.ConsumeIntInRange(0, 6)

        if expr_choice == 0:
            # Root access
            jsonpath = "$"
        elif expr_choice == 1:
            # Property access
            prop_name = fdp.ConsumeUnicodeNoSurrogates(30)
            jsonpath = f"$.{prop_name}"
        elif expr_choice == 2:
            # Array access
            index = fdp.ConsumeIntInRange(0, 20)
            jsonpath = f"$[{index}]"
        elif expr_choice == 3:
            # Wildcard
            jsonpath = "$[*]"
        elif expr_choice == 4:
            # Recursive descent
            prop_name = fdp.ConsumeUnicodeNoSurrogates(20)
            jsonpath = f"$..{prop_name}"
        elif expr_choice == 5:
            # Complex expression
            parts = []
            for _ in range(fdp.ConsumeIntInRange(1, 5)):
                if fdp.ConsumeBool():
                    parts.append(fdp.ConsumeUnicodeNoSurrogates(15))
                else:
                    parts.append(f"[{fdp.ConsumeIntInRange(0, 10)}]")
            jsonpath = "$." + ".".join(parts)
        else:
            # Raw expression
            jsonpath = fdp.ConsumeUnicodeNoSurrogates(100)

        # Test JSONPath modifier (should never crash)
        result = jsonpath_modifier(test_data, jsonpath)

        # Verify result type if successful
        if result is not None:
            assert isinstance(result, (list, dict)), f"Invalid result type: {type(result)}"

        # Test with mappings if there's remaining data
        if fdp.remaining_bytes() > 10:
            mappings = {}
            for _ in range(fdp.ConsumeIntInRange(0, 3)):
                key = fdp.ConsumeUnicodeNoSurrogates(20)
                value = fdp.ConsumeUnicodeNoSurrogates(30)
                if key and value:
                    mappings[key] = value

            if mappings:
                result_with_mappings = jsonpath_modifier(test_data, "$[*]", mappings)
                if result_with_mappings is not None:
                    assert isinstance(result_with_mappings, (list, dict))

    except (HTTPException, ValueError, TypeError, AttributeError, KeyError, IndexError):
        # Expected exceptions for invalid input
        pass
    except Exception:
        # Unexpected exceptions should be caught by Atheris
        raise


def main():
    """Main fuzzing entry point."""
    # Instrument all Python code for coverage guidance
    atheris.instrument_all()

    # Setup fuzzing with command line arguments
    atheris.Setup(sys.argv, TestOneInput)

    # Start fuzzing
    atheris.Fuzz()


if __name__ == "__main__":
    main()
