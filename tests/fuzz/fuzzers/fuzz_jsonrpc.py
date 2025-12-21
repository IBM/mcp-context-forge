#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/fuzzers/fuzz_jsonrpc.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Coverage-guided fuzzing for JSON-RPC validation using Atheris.
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
    # First-Party
    from mcpgateway.validation.jsonrpc import JSONRPCError, validate_request, validate_response
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)


def TestOneInput(data: bytes) -> None:  # noqa: N802
    """Fuzz target for JSON-RPC validation.

    Args:
        data: Raw bytes from Atheris fuzzer
    """
    fdp = atheris.FuzzedDataProvider(data)

    try:
        if fdp.remaining_bytes() < 1:
            return

        choice = fdp.ConsumeIntInRange(0, 5)

        if choice == 0:
            # Test request validation with structured data
            request = {"jsonrpc": fdp.ConsumeUnicodeNoSurrogates(10), "method": fdp.ConsumeUnicodeNoSurrogates(50), "id": fdp.ConsumeIntInRange(0, 1000000)}

            # Add params sometimes
            if fdp.ConsumeBool():
                param_choice = fdp.ConsumeIntInRange(0, 2)
                if param_choice == 0:
                    # List params
                    request["params"] = [fdp.ConsumeUnicodeNoSurrogates(30) for _ in range(fdp.ConsumeIntInRange(0, 5))]
                elif param_choice == 1:
                    # Dict params
                    request["params"] = {fdp.ConsumeUnicodeNoSurrogates(20): fdp.ConsumeUnicodeNoSurrogates(40) for _ in range(fdp.ConsumeIntInRange(0, 5))}
                else:
                    # Invalid params
                    request["params"] = fdp.ConsumeUnicodeNoSurrogates(50)

            validate_request(request)

        elif choice == 1:
            # Test response validation with structured data
            response = {"jsonrpc": fdp.ConsumeUnicodeNoSurrogates(10), "id": fdp.ConsumeIntInRange(0, 1000000)}

            # Add result or error
            if fdp.ConsumeBool():
                # Success response
                result_choice = fdp.ConsumeIntInRange(0, 3)
                if result_choice == 0:
                    response["result"] = fdp.ConsumeUnicodeNoSurrogates(100)
                elif result_choice == 1:
                    response["result"] = fdp.ConsumeIntInRange(-1000, 1000)
                elif result_choice == 2:
                    response["result"] = None
                else:
                    response["result"] = {"data": fdp.ConsumeUnicodeNoSurrogates(50)}
            else:
                # Error response
                error = {"code": fdp.ConsumeIntInRange(-32768, 32767), "message": fdp.ConsumeUnicodeNoSurrogates(100)}
                if fdp.ConsumeBool():
                    error["data"] = fdp.ConsumeUnicodeNoSurrogates(100)
                response["error"] = error

            validate_response(response)

        elif choice == 2:
            # Test with malformed JSON structure
            raw_data = fdp.ConsumeUnicodeNoSurrogates(200)
            try:
                parsed = json.loads(raw_data)
                if isinstance(parsed, dict):
                    validate_request(parsed)
            except (json.JSONDecodeError, TypeError):
                # Expected for malformed JSON
                pass

        elif choice == 3:
            # Test with random dictionary
            random_dict = {}
            for _ in range(fdp.ConsumeIntInRange(0, 10)):
                key = fdp.ConsumeUnicodeNoSurrogates(20)
                value_type = fdp.ConsumeIntInRange(0, 4)
                if value_type == 0:
                    value = fdp.ConsumeUnicodeNoSurrogates(50)
                elif value_type == 1:
                    value = fdp.ConsumeIntInRange(-1000, 1000)
                elif value_type == 2:
                    value = fdp.ConsumeBool()
                elif value_type == 3:
                    value = None
                else:
                    value = [fdp.ConsumeIntInRange(0, 100) for _ in range(fdp.ConsumeIntInRange(0, 3))]

                if key:
                    random_dict[key] = value

            validate_request(random_dict)

        elif choice == 4:
            # Test with binary data
            raw_bytes = fdp.ConsumeBytes(100)
            try:
                text = raw_bytes.decode("utf-8", errors="ignore")
                data = json.loads(text)
                if isinstance(data, dict):
                    validate_request(data)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                # Expected for binary/invalid data
                pass

        else:
            # Test JSONRPCError creation
            code = fdp.ConsumeIntInRange(-32768, 32767)
            message = fdp.ConsumeUnicodeNoSurrogates(100)

            error = JSONRPCError(code, message)
            error_dict = error.to_dict()

            # Verify error dict structure
            assert "jsonrpc" in error_dict
            assert "error" in error_dict
            assert error_dict["jsonrpc"] == "2.0"
            assert error_dict["error"]["code"] == code
            assert error_dict["error"]["message"] == message

            # Test with data and request_id
            if fdp.remaining_bytes() > 10:
                data_obj = fdp.ConsumeUnicodeNoSurrogates(50)
                request_id = fdp.ConsumeIntInRange(0, 1000) if fdp.ConsumeBool() else None

                error_with_extras = JSONRPCError(code, message, data_obj, request_id)
                extra_dict = error_with_extras.to_dict()

                assert extra_dict["error"]["data"] == data_obj
                assert extra_dict["request_id"] == request_id

    except (JSONRPCError, ValueError, TypeError, json.JSONDecodeError, KeyError, AttributeError):
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
