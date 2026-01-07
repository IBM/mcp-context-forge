# -*- coding: utf-8 -*-
"""Location: ./tests/async/async_validator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Validate async code patterns and detect common pitfalls.
"""

# Standard
import argparse
import ast
import json
from pathlib import Path
from typing import Any, Dict


class AsyncCodeValidator:
    """Validate async code for common patterns and pitfalls."""

    def __init__(self):
        self.issues = []
        self.suggestions = []

    def validate_directory(self, source_dir: Path) -> Dict[str, Any]:
        """Validate all Python files in directory."""

        validation_results = {"files_checked": 0, "issues_found": 0, "suggestions": 0, "details": []}

        python_files = list(source_dir.rglob("*.py"))

        for file_path in python_files:
            if self._should_skip_file(file_path):
                continue

            file_results = self._validate_file(file_path)
            validation_results["details"].append(file_results)
            validation_results["files_checked"] += 1
            validation_results["issues_found"] += len(file_results["issues"])
            validation_results["suggestions"] += len(file_results["suggestions"])

        return validation_results

    def _validate_file(self, file_path: Path) -> Dict[str, Any]:
        """Validate a single Python file."""

        file_results = {"file": str(file_path), "issues": [], "suggestions": []}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source_code = f.read()

            tree = ast.parse(source_code, filename=str(file_path))

            # Analyze AST for async patterns
            validator = AsyncPatternVisitor(file_path)
            validator.visit(tree)

            file_results["issues"] = validator.issues
            file_results["suggestions"] = validator.suggestions

        except Exception as e:
            file_results["issues"].append({"type": "parse_error", "message": f"Failed to parse file: {str(e)}", "line": 0})

        return file_results

    def _should_skip_file(self, file_path: Path) -> bool:
        """Determine if a file should be skipped (e.g., __init__.py files)."""
        return file_path.name == "__init__.py"


class AsyncPatternVisitor(ast.NodeVisitor):
    """AST visitor to detect async patterns and issues."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.issues = []
        self.suggestions = []
        self.in_async_function = False

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        """Visit async function definitions."""

        self.in_async_function = True

        # Check for blocking operations in async functions
        self._check_blocking_operations(node)

        # Check for proper error handling
        self._check_error_handling(node)

        self.generic_visit(node)
        self.in_async_function = False

    def visit_Call(self, node):  # noqa: N802
        """Visit function calls."""

        if self.in_async_function:
            # Check for potentially unawaited async calls
            self._check_unawaited_calls(node)

            # Check for blocking I/O operations
            self._check_blocking_io(node)

        self.generic_visit(node)

    def _check_blocking_operations(self, node):
        """Check for blocking operations in async functions."""

        blocking_patterns = [
            "time.sleep",
            "requests.get",
            "requests.post",
            "subprocess.run",
            "subprocess.call",
            "open",  # File I/O without async
        ]

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_name = self._get_call_name(child)
                if call_name in blocking_patterns:
                    self.issues.append(
                        {"type": "blocking_operation", "message": f"Blocking operation '{call_name}' in async function", "line": child.lineno, "suggestion": f"Use async equivalent of {call_name}"}
                    )

    def _check_unawaited_calls(self, node):
        """Check for potentially unawaited async calls."""

        # Look for calls that might return coroutines
        async_patterns = [
            "aiohttp",
            "asyncio",
            "asyncpg",
            "websockets",
            "motor",  # Common async libraries
        ]

        call_name = self._get_call_name(node)

        for pattern in async_patterns:
            if pattern in call_name:
                # Check if this call is awaited
                parent = getattr(node, "parent", None)
                if not isinstance(parent, ast.Await):
                    self.suggestions.append({"type": "potentially_unawaited", "message": f"Call to '{call_name}' might need await", "line": node.lineno})
                    break

    def _get_call_name(self, node):
        """Extract the name of a function call."""

        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return f"{node.func.value.id}.{node.func.attr}"
            else:
                return node.func.attr
        return "unknown"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate async code patterns and detect common pitfalls.")
    parser.add_argument("--source", type=Path, required=True, help="Source directory to validate.")
    parser.add_argument("--report", type=Path, required=True, help="Path to the output validation report.")

    args = parser.parse_args()

    validator = AsyncCodeValidator()
    results = validator.validate_directory(args.source)

    with open(args.report, "w") as f:
        json.dump(results, f, indent=4)

    print(f"Validation report saved to {args.report}")
