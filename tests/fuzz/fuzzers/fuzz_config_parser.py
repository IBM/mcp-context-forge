#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/fuzz/fuzzers/fuzz_config_parser.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Coverage-guided fuzzing for configuration parsing using Atheris.
"""

# Standard
import os
import sys
import tempfile

# Third-Party
import atheris

# Ensure the project is in the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

try:
    # Third-Party
    from pydantic import ValidationError

    # First-Party
    from mcpgateway.config import Settings
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)


def TestOneInput(data: bytes) -> None:  # noqa: N802
    """Fuzz target for configuration parsing.

    Args:
        data: Raw bytes from Atheris fuzzer
    """
    fdp = atheris.FuzzedDataProvider(data)

    try:
        if fdp.remaining_bytes() < 1:
            return

        choice = fdp.ConsumeIntInRange(0, 3)

        if choice == 0:
            # Test Settings creation with random kwargs
            kwargs = {}

            # Basic string fields
            string_fields = ["app_name", "host", "database_url", "basic_auth_user", "basic_auth_password", "log_level", "transport_type"]

            for field in string_fields:
                if fdp.ConsumeBool():
                    kwargs[field] = fdp.ConsumeUnicodeNoSurrogates(100)

            # Integer fields
            int_fields = ["port", "resource_cache_size", "resource_cache_ttl", "tool_timeout"]
            for field in int_fields:
                if fdp.ConsumeBool():
                    kwargs[field] = fdp.ConsumeIntInRange(-1000, 65535)

            # Boolean fields
            bool_fields = ["skip_ssl_verify", "auth_required", "docs_allow_basic_auth"]
            for field in bool_fields:
                if fdp.ConsumeBool():
                    kwargs[field] = fdp.ConsumeBool()

            settings = Settings(**kwargs)

            # Test methods that might fail
            try:
                settings.validate_transport()
            except ValueError:
                # Expected for invalid transport types
                pass

            try:
                settings.validate_database()
            except (ValueError, OSError):
                # Expected for invalid database URLs
                pass

            # Test properties
            _ = settings.api_key
            _ = settings.database_settings

        elif choice == 1:
            # Test environment variable parsing
            env_vars = {}

            # Generate random environment variables
            for _ in range(fdp.ConsumeIntInRange(0, 10)):
                key = fdp.ConsumeUnicodeNoSurrogates(30)
                value = fdp.ConsumeUnicodeNoSurrogates(100)
                if key and not key.startswith("_"):
                    env_vars[key] = value

            # Backup original env
            original_env = dict(os.environ)

            try:
                # Set test environment
                os.environ.update(env_vars)

                # Create settings (will read from env)
                settings = Settings()

                # Test basic functionality
                _ = settings.model_dump()

            finally:
                # Restore original environment
                os.environ.clear()
                os.environ.update(original_env)

        elif choice == 2:
            # Test with .env file content
            env_content = ""
            for _ in range(fdp.ConsumeIntInRange(0, 20)):
                key = fdp.ConsumeUnicodeNoSurrogates(30)
                value = fdp.ConsumeUnicodeNoSurrogates(100)
                if key and "=" not in key and "\n" not in key:
                    env_content += f"{key}={value}\n"

            # Create temporary .env file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
                f.write(env_content)
                env_file_path = f.name

            try:
                # Test loading from .env file (simulate)
                lines = env_content.split("\n")
                env_dict = {}
                for line in lines:
                    if "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        env_dict[key.strip()] = value.strip()

                # Test with parsed values
                if env_dict:
                    settings = Settings(**env_dict)
                    _ = settings.model_dump()

            finally:
                # Clean up temp file
                try:
                    os.unlink(env_file_path)
                except OSError:
                    pass

        else:
            # Test database URL parsing
            db_url = fdp.ConsumeUnicodeNoSurrogates(200)

            try:
                settings = Settings(database_url=db_url)
                db_settings = settings.database_settings

                # Verify basic structure if parsing succeeded
                if isinstance(db_settings, dict):
                    # Should have basic keys for valid URLs
                    pass

            except (ValueError, ValidationError):
                # Expected for invalid URLs
                pass

    except (ValidationError, ValueError, TypeError, OSError, KeyError):
        # Expected exceptions for invalid configuration
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
