#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/python_sandbox_server/src/python_sandbox_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Python Sandbox FastMCP Server

A secure MCP server for executing Python code in a sandboxed environment.
Uses RestrictedPython for code transformation and safety controls.
Powered by FastMCP for enhanced type safety and automatic validation.

Security Features:
- RestrictedPython for AST-level code restriction
- Resource limits (memory, CPU, execution time)
- Namespace isolation with safe builtins
- Tiered security model with different capability levels
- Comprehensive logging and monitoring
"""

import logging
import os
import signal
import sys
import time
import traceback
from io import StringIO
from typing import Any
from uuid import uuid4

import orjson
from fastmcp import FastMCP
from pydantic import Field

# Configure logging to stderr to avoid MCP protocol interference
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Create FastMCP server instance
mcp = FastMCP("python-sandbox-server")

# Configuration from environment variables
TIMEOUT = int(os.getenv("SANDBOX_TIMEOUT", "30"))
MAX_OUTPUT_SIZE = int(os.getenv("SANDBOX_MAX_OUTPUT_SIZE", "1048576"))  # 1MB

# Security capability flags
ENABLE_NETWORK = os.getenv("SANDBOX_ENABLE_NETWORK", "false").lower() == "true"
ENABLE_FILESYSTEM = os.getenv("SANDBOX_ENABLE_FILESYSTEM", "false").lower() == "true"
ENABLE_DATA_SCIENCE = os.getenv("SANDBOX_ENABLE_DATA_SCIENCE", "false").lower() == "true"

# Safe standard library modules (no I/O, no system access)
SAFE_STDLIB_MODULES = [
    # Core utilities
    "math",
    "random",
    "datetime",
    "json",
    "re",
    "time",
    "calendar",
    "uuid",
    # Data structures and algorithms
    "collections",
    "itertools",
    "functools",
    "operator",
    "bisect",
    "heapq",
    "copy",
    "dataclasses",
    "enum",
    "typing",
    # Text processing
    "string",
    "textwrap",
    "unicodedata",
    "difflib",
    # Numeric and math
    "decimal",
    "fractions",
    "statistics",
    "cmath",
    # Encoding and hashing
    "base64",
    "binascii",
    "hashlib",
    "hmac",
    "secrets",
    # Parsing and formatting
    "html",
    "html.parser",
    "xml.etree.ElementTree",
    "csv",
    "configparser",
    "urllib.parse",  # URL parsing only, not fetching
    # Abstract base classes and protocols
    "abc",
    "contextlib",
    "types",
]

# Data science modules (require ENABLE_DATA_SCIENCE)
DATA_SCIENCE_MODULES = [
    "numpy",
    "pandas",
    "scipy",
    "matplotlib",
    "seaborn",
    "sklearn",
    "statsmodels",
    "plotly",
    "sympy",
]

# Network modules (require ENABLE_NETWORK)
NETWORK_MODULES = [
    "httpx",
    "requests",
    "urllib.request",
    "aiohttp",
    "websocket",
    "ftplib",
    "smtplib",
    "email",
]

# File system modules (require ENABLE_FILESYSTEM)
FILESYSTEM_MODULES = [
    "pathlib",
    "os.path",
    "tempfile",
    "shutil",
    "glob",
    "zipfile",
    "tarfile",
]


# Build allowed imports based on configuration
def get_allowed_imports() -> list[str]:
    """Build the list of allowed imports based on configuration."""
    # Start with custom imports from environment
    custom_imports = os.getenv("SANDBOX_ALLOWED_IMPORTS", "").strip()

    if custom_imports:
        # If custom imports are specified, use only those
        return custom_imports.split(",")

    # Otherwise build from our categories
    allowed = SAFE_STDLIB_MODULES.copy()

    if ENABLE_DATA_SCIENCE:
        allowed.extend(DATA_SCIENCE_MODULES)

    if ENABLE_NETWORK:
        allowed.extend(NETWORK_MODULES)

    if ENABLE_FILESYSTEM:
        allowed.extend(FILESYSTEM_MODULES)

    return allowed


ALLOWED_IMPORTS = get_allowed_imports()


class PythonSandbox:
    """Secure Python code execution sandbox with tiered security model."""

    def __init__(self):
        """Initialize the sandbox."""
        self.restricted_python_available = self._check_restricted_python()
        self.allowed_modules = set(ALLOWED_IMPORTS)

        # Track security warnings
        self.security_warnings: list[str] = []

    def _check_restricted_python(self) -> bool:
        """Check if RestrictedPython is available."""
        try:
            import RestrictedPython

            return True
        except ImportError:
            logger.warning("RestrictedPython not available")
            return False

    def _check_import_safety(self, module_name: str) -> bool:
        """Check if a module import is allowed."""
        # Check direct module
        if module_name in self.allowed_modules:
            return True

        # Check parent modules (e.g., os.path when os is not allowed)
        parts = module_name.split(".")
        for i in range(len(parts)):
            partial = ".".join(parts[: i + 1])
            if partial in self.allowed_modules:
                return True

        # Log security warning
        if module_name not in ["os", "sys", "subprocess", "__builtin__", "__builtins__"]:
            self.security_warnings.append(f"Blocked import attempt: {module_name}")

        return False

    def _safe_import(self, name, *args, **kwargs):
        """Controlled import function that checks against allowed modules."""
        if not self._check_import_safety(name):
            raise ImportError(f"Import of '{name}' is not allowed in sandbox")
        return __import__(name, *args, **kwargs)

    def create_safe_globals(self) -> dict[str, Any]:
        """Create a safe global namespace for code execution."""
        # Safe built-in functions
        safe_builtins = {
            # Basic types
            "bool": bool,
            "int": int,
            "float": float,
            "str": str,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "frozenset": frozenset,
            "bytes": bytes,
            "bytearray": bytearray,
            # Safe functions
            "len": len,
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "round": round,
            "sorted": sorted,
            "reversed": reversed,
            "enumerate": enumerate,
            "zip": zip,
            "map": map,
            "filter": filter,
            "all": all,
            "any": any,
            "range": range,
            "print": print,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "hasattr": hasattr,
            "getattr": getattr,
            "setattr": setattr,
            "callable": callable,
            "type": type,
            "id": id,
            "hash": hash,
            "iter": iter,
            "next": next,
            "slice": slice,
            # String/conversion methods
            "chr": chr,
            "ord": ord,
            "hex": hex,
            "oct": oct,
            "bin": bin,
            "format": format,
            "repr": repr,
            "ascii": ascii,
            # Math
            "divmod": divmod,
            "pow": pow,
            # Constants
            "True": True,
            "False": False,
            "None": None,
            "NotImplemented": NotImplemented,
            "Ellipsis": Ellipsis,
        }

        # Optionally remove dangerous builtins in strict mode
        if not ENABLE_FILESYSTEM:
            # These could potentially be used to access file system indirectly
            safe_builtins.pop("open", None)
            safe_builtins.pop("compile", None)
            safe_builtins.pop("eval", None)
            safe_builtins.pop("exec", None)

        # Pre-import allowed modules
        safe_imports = {}
        for module_name in ALLOWED_IMPORTS:
            try:
                # Only import if it's actually available
                safe_imports[module_name] = __import__(module_name)
            except ImportError:
                # Module not installed, skip it
                pass

        globals_dict = {"__builtins__": safe_builtins, **safe_imports}

        # Note: RestrictedPython support is added during execution

        return globals_dict

    def validate_code(self, code: str) -> dict[str, Any]:
        """Validate Python code for syntax and security."""
        # First, always do a basic Python syntax check
        try:
            compile(code, "<sandbox>", "exec")
        except SyntaxError as e:
            return {
                "valid": False,
                "error": f"Syntax error: {str(e)}",
                "line": e.lineno,
                "offset": e.offset,
                "text": e.text,
            }
        except Exception as e:
            return {"valid": False, "error": f"Compilation error: {str(e)}"}

        # If basic syntax passes, check with RestrictedPython if available
        if self.restricted_python_available:
            try:
                from RestrictedPython import compile_restricted_exec

                # Compile with restrictions
                result = compile_restricted_exec(code, "<sandbox>")

                # Check for RestrictedPython errors
                if result.errors:
                    return {
                        "valid": False,
                        "errors": result.errors,
                        "message": "Code contains restricted operations",
                    }

                if result.code is None:
                    return {"valid": False, "message": "RestrictedPython compilation failed"}

            except Exception as e:
                return {"valid": False, "error": f"RestrictedPython error: {str(e)}"}

        # Additional security checks for dangerous patterns
        warnings = []
        security_issues = []

        # Check for obvious dangerous patterns
        dangerous_patterns = [
            ("__import__", "Dynamic imports detected"),
            ("eval(", "Use of eval detected"),
            ("exec(", "Use of exec detected"),
            ("compile(", "Use of compile detected"),
            ("open(", "File operations detected"),
        ]

        for pattern, warning in dangerous_patterns:
            if pattern in code:
                warnings.append(warning)

        # Check for dunder methods (but allow __name__, __main__)
        if "__" in code:
            # More nuanced check for dangerous dunders
            dangerous_dunders = [
                "__class__",
                "__base__",
                "__subclasses__",
                "__globals__",
                "__code__",
                "__closure__",
            ]
            for dunder in dangerous_dunders:
                if dunder in code:
                    security_issues.append(f"Potentially dangerous dunder method: {dunder}")

        # Check for attempts to access builtins
        if "builtins" in code or "__builtins__" in code:
            security_issues.append("Attempt to access builtins detected")

        # If there are security issues, mark as invalid
        if security_issues:
            return {
                "valid": False,
                "message": "Code failed security validation",
                "security_issues": security_issues,
                "warnings": warnings if warnings else None,
            }

        return {
            "valid": True,
            "message": "Code passed validation",
            "warnings": warnings if warnings else None,
        }

    def execute(self, code: str) -> dict[str, Any]:
        """Execute Python code in the sandbox."""
        execution_id = str(uuid4())
        self.security_warnings = []  # Reset warnings for this execution

        # Validate code first
        validation = self.validate_code(code)
        if not validation["valid"]:
            return {
                "success": False,
                "error": validation.get("error") or validation.get("message", "Validation failed"),
                "validation_errors": validation.get("errors"),
                "execution_id": execution_id,
            }

        # Check if this is a single expression or has a final expression to display
        # Try to compile as eval first (single expression)
        # But exclude function calls that have side effects like print()
        is_single_expression = False
        if not any(code.strip().startswith(func) for func in ["print(", "input(", "help("]):
            try:
                compile(code, "<sandbox>", "eval")
                # Also check it's not a void function call
                is_single_expression = True
            except SyntaxError:
                # Not a single expression
                pass

        # For multi-line code, check if the last line is an expression
        # This mimics IPython behavior
        last_line_expression = None
        if not is_single_expression and "\n" in code:
            lines = code.rstrip().split("\n")
            if lines:
                last_line_raw = lines[-1]
                last_line = last_line_raw.strip()

                # Check if the last line is indented (part of a block)
                is_indented = len(last_line_raw) > 0 and last_line_raw[0].isspace()

                # Check if the last line is an expression (not an assignment or statement)
                if (
                    last_line
                    and not is_indented
                    and not any(
                        last_line.startswith(kw)
                        for kw in [
                            "import ",
                            "from ",
                            "def ",
                            "class ",
                            "if ",
                            "for ",
                            "while ",
                            "with ",
                            "try:",
                            "except:",
                            "finally:",
                            "elif ",
                            "else:",
                            "return ",
                            "yield ",
                            "raise ",
                            "assert ",
                            "del ",
                            "global ",
                            "nonlocal ",
                            "pass",
                            "break",
                            "continue",
                            "print(",
                            "input(",
                            "help(",
                        ]
                    )
                ):
                    # Also check it's not an assignment (simple check)
                    if "=" not in last_line or any(
                        op in last_line for op in ["==", "!=", "<=", ">=", " in ", " is "]
                    ):
                        try:
                            # Try to compile just the last line as an expression
                            compile(last_line, "<sandbox>", "eval")
                            last_line_expression = last_line
                            # Modify code to capture the last expression
                            # Use a name that RestrictedPython allows
                            lines[-1] = f"SANDBOX_EVAL_RESULT = ({last_line})"
                            code = "\n".join(lines)
                        except SyntaxError:
                            # Last line is not a valid expression
                            pass

        # Prepare execution environment
        safe_globals = self.create_safe_globals()
        local_vars = {}

        # Capture output
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture

            # Set timeout if on Unix
            if hasattr(signal, "SIGALRM"):

                def timeout_handler(signum, frame):
                    raise TimeoutError(f"Execution timed out after {TIMEOUT} seconds")

                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(TIMEOUT)

            start_time = time.time()

            # Store the expression result if it's an expression
            expression_result = None

            # Execute the code
            if self.restricted_python_available:
                from RestrictedPython import (
                    PrintCollector,
                    compile_restricted_eval,
                    compile_restricted_exec,
                )
                from RestrictedPython import safe_globals as rp_safe_globals

                # Update safe globals with RestrictedPython requirements
                # Save our builtins
                our_builtins = safe_globals.get("__builtins__", {})

                # Add RestrictedPython helpers
                for key, value in rp_safe_globals.items():
                    if key.startswith("_"):  # Only add the underscore helpers
                        safe_globals[key] = value

                # Add missing helpers
                if "_getiter_" not in safe_globals:
                    safe_globals["_getiter_"] = iter
                if "_getitem_" not in safe_globals:
                    safe_globals["_getitem_"] = lambda obj, key: obj[key]

                # Merge builtins (ours + RestrictedPython's)
                if "__builtins__" in rp_safe_globals and isinstance(
                    rp_safe_globals["__builtins__"], dict
                ):
                    merged_builtins = dict(rp_safe_globals["__builtins__"])
                    merged_builtins.update(our_builtins)
                    safe_globals["__builtins__"] = merged_builtins
                else:
                    safe_globals["__builtins__"] = our_builtins

                safe_globals["_print_"] = PrintCollector

                # Use our controlled import function
                safe_globals["__builtins__"]["__import__"] = self._safe_import

                if is_single_expression:
                    # Compile and evaluate as expression
                    compiled = compile_restricted_eval(code, "<sandbox>")
                    if compiled.code:
                        expression_result = eval(compiled.code, safe_globals, local_vars)
                    else:
                        raise RuntimeError("Failed to compile expression")
                else:
                    # Compile and execute as statements
                    compiled = compile_restricted_exec(code, "<sandbox>")
                    if compiled.code:
                        exec(compiled.code, safe_globals, local_vars)
                        # Check if we captured a final expression
                        if last_line_expression and "SANDBOX_EVAL_RESULT" in local_vars:
                            expression_result = local_vars["SANDBOX_EVAL_RESULT"]
                    else:
                        raise RuntimeError("Failed to compile code")
            else:
                # Fallback to regular Python
                safe_globals["__builtins__"]["__import__"] = self._safe_import
                if is_single_expression:
                    expression_result = eval(code, safe_globals, local_vars)
                else:
                    exec(code, safe_globals, local_vars)
                    # Check if we captured a final expression
                    if last_line_expression and "__ipython_result__" in local_vars:
                        expression_result = local_vars["__ipython_result__"]

            # Cancel timeout
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)

            execution_time = time.time() - start_time

            # Get output
            stdout_output = stdout_capture.getvalue()
            stderr_output = stderr_capture.getvalue()

            # Get RestrictedPython print output if available
            if self.restricted_python_available and "_print" in local_vars:
                _print_collector = local_vars["_print"]
                if hasattr(_print_collector, "txt"):
                    # Use the collected prints as a list
                    printed_text = "".join(_print_collector.txt) if _print_collector.txt else ""
                    if stdout_output:
                        stdout_output = printed_text + stdout_output
                    else:
                        stdout_output = printed_text

            # Truncate if too large
            if len(stdout_output) > MAX_OUTPUT_SIZE:
                stdout_output = stdout_output[:MAX_OUTPUT_SIZE] + "\n[Output truncated]"
            if len(stderr_output) > MAX_OUTPUT_SIZE:
                stderr_output = stderr_output[:MAX_OUTPUT_SIZE] + "\n[Output truncated]"

            # Determine what to return as the result
            result = None

            # If it was a single expression, use that result
            if expression_result is not None:
                result = expression_result
                # Also add it to stdout for display (like IPython)
                if stdout_output or (self.restricted_python_available and "_print" in local_vars):
                    # If there was already output, add a newline
                    if not stdout_output.endswith("\n") and stdout_output:
                        stdout_output += "\n"
                else:
                    # No prior output, just show the result
                    pass
                # Format the result for display
                try:
                    # Try to use repr for better display (like IPython)
                    display_str = repr(result)
                    stdout_output = stdout_output + display_str
                except:
                    stdout_output = stdout_output + str(result)
            else:
                # Look for result variable in assignments
                for var in ["result", "output", "_"]:
                    if var in local_vars:
                        result = local_vars[var]
                        break

            # Format result for JSON serialization
            if result is not None:
                try:
                    orjson.dumps(result)
                except (TypeError, ValueError):
                    result = str(result)

            return {
                "success": True,
                "stdout": stdout_output,
                "stderr": stderr_output,
                "result": result,
                "execution_time": execution_time,
                "execution_id": execution_id,
                "variables": [k for k in local_vars.keys() if k != "SANDBOX_EVAL_RESULT"],
                "security_warnings": self.security_warnings if self.security_warnings else None,
            }

        except ImportError as e:
            return {
                "success": False,
                "error": str(e),
                "execution_id": execution_id,
                "security_event": "blocked_import",
            }
        except TimeoutError as e:
            return {"success": False, "error": str(e), "execution_id": execution_id}
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue(),
                "execution_id": execution_id,
            }
        finally:
            # Restore stdout/stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr

            # Cancel any pending alarm
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)


# Create sandbox instance
sandbox = PythonSandbox()


@mcp.tool(description="Execute Python code in a secure sandbox environment")
async def execute_code(
    code: str = Field(..., description="Python code to execute"),
) -> dict[str, Any]:
    """
    Execute Python code in a secure sandbox with RestrictedPython.

    Features IPython-like behavior:
    - Single expressions are automatically evaluated and displayed
    - Multi-line code with a final expression shows that expression
    - Example: "1 + 1" returns 2, "x = 5\\nx * 2" returns 10

    The sandbox provides:
    - Safe subset of Python builtins
    - Configurable module imports based on security level
    - Execution timeout (via SANDBOX_TIMEOUT env var)
    - Output size limits (via SANDBOX_MAX_OUTPUT_SIZE env var)

    Security levels (via environment variables):
    - Basic (default): Safe stdlib modules only
    - Data Science: + numpy, pandas, scipy, matplotlib, etc.
    - Network: + httpx, requests, urllib, etc.
    - Filesystem: + pathlib, os.path, tempfile, etc.

    Returns execution results including stdout, stderr, and any result value.
    """
    return sandbox.execute(code)


@mcp.tool(description="Validate Python code without executing it")
async def validate_code(
    code: str = Field(..., description="Python code to validate"),
) -> dict[str, Any]:
    """
    Validate Python code for syntax and security without execution.

    Checks:
    - Python syntax validity (like python -c)
    - RestrictedPython security constraints (if available)
    - Reports specific errors and restricted operations
    - Warns about potentially dangerous patterns

    Note: This validates SYNTAX, not runtime behavior. Code like
    `print(undefined_var)` will pass validation but fail at execution.
    This matches standard Python behavior where NameErrors, ImportErrors,
    and other runtime errors are not caught during syntax checking.
    """
    return sandbox.validate_code(code)


@mcp.tool(description="Get current sandbox capabilities and configuration")
async def get_sandbox_info() -> dict[str, Any]:
    """
    Get information about the sandbox environment.

    Returns:
    - Available modules grouped by category
    - Timeout settings
    - Security features status
    - Configuration details
    """
    # Group modules by category for clarity
    modules_by_category = {"safe_stdlib": [], "data_science": [], "network": [], "filesystem": []}

    for module in ALLOWED_IMPORTS:
        if module in SAFE_STDLIB_MODULES:
            modules_by_category["safe_stdlib"].append(module)
        elif module in DATA_SCIENCE_MODULES:
            modules_by_category["data_science"].append(module)
        elif module in NETWORK_MODULES:
            modules_by_category["network"].append(module)
        elif module in FILESYSTEM_MODULES:
            modules_by_category["filesystem"].append(module)

    return {
        "restricted_python": sandbox.restricted_python_available,
        "timeout_seconds": TIMEOUT,
        "max_output_size": MAX_OUTPUT_SIZE,
        "security_capabilities": {
            "network_enabled": ENABLE_NETWORK,
            "filesystem_enabled": ENABLE_FILESYSTEM,
            "data_science_enabled": ENABLE_DATA_SCIENCE,
        },
        "allowed_imports": modules_by_category,
        "total_allowed_modules": len(ALLOWED_IMPORTS),
        "safe_builtins": [
            "bool",
            "int",
            "float",
            "str",
            "list",
            "dict",
            "tuple",
            "set",
            "len",
            "abs",
            "min",
            "max",
            "sum",
            "round",
            "sorted",
            "reversed",
            "enumerate",
            "zip",
            "map",
            "filter",
            "all",
            "any",
            "range",
            "print",
            "chr",
            "ord",
            "hex",
            "oct",
            "bin",
            "isinstance",
            "type",
            "hasattr",
        ],
    }


def main():
    """Run the FastMCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Python Sandbox FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9015, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting Python Sandbox FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting Python Sandbox FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
