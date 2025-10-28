#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/code_splitter_server/src/code_splitter_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Code Splitter FastMCP Server

Advanced code analysis and splitting using Abstract Syntax Tree (AST) parsing with FastMCP framework.
Supports multiple programming languages and intelligent code segmentation.
"""

import ast
import logging
import sys
from typing import Any

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
mcp = FastMCP(name="code-splitter-server", version="2.0.0")


class CodeSplitter:
    """Advanced code splitting and analysis."""

    def __init__(self):
        """Initialize the code splitter."""
        self.supported_languages = self._check_language_support()

    def _check_language_support(self) -> dict[str, bool]:
        """Check supported programming languages."""
        languages = {
            "python": True,  # Always supported via built-in ast
            "javascript": False,
            "typescript": False,
            "java": False,
            "csharp": False,
            "go": False,
            "rust": False,
        }

        # Check for additional language parsers
        try:
            import tree_sitter

            languages["javascript"] = True
            languages["typescript"] = True
        except ImportError:
            pass

        return languages

    def split_python_code(
        self,
        code: str,
        split_level: str = "function",
        include_metadata: bool = True,
        preserve_comments: bool = True,
        min_lines: int = 5,
    ) -> dict[str, Any]:
        """Split Python code using AST analysis."""
        try:
            # Parse the code into AST
            tree = ast.parse(code)

            segments = []
            lines = code.split("\n")

            # Extract different types of code segments
            if split_level in ["function", "all"]:
                segments.extend(self._extract_functions(tree, lines, include_metadata))

            if split_level in ["class", "all"]:
                segments.extend(self._extract_classes(tree, lines, include_metadata))

            if split_level in ["method", "all"]:
                segments.extend(self._extract_methods(tree, lines, include_metadata))

            if split_level == "import":
                segments.extend(self._extract_imports(tree, lines, include_metadata))

            # Filter by minimum lines
            filtered_segments = [s for s in segments if len(s["code"].split("\n")) >= min_lines]

            # Add comments if preserved
            if preserve_comments:
                comment_segments = self._extract_comments(lines, include_metadata)
                filtered_segments.extend(comment_segments)

            # Sort by line number
            filtered_segments.sort(key=lambda x: x.get("start_line", 0))

            return {
                "success": True,
                "language": "python",
                "split_level": split_level,
                "total_segments": len(filtered_segments),
                "segments": filtered_segments,
                "original_lines": len(lines),
                "metadata": {
                    "functions": len([s for s in segments if s.get("type") == "function"]),
                    "classes": len([s for s in segments if s.get("type") == "class"]),
                    "methods": len([s for s in segments if s.get("type") == "method"]),
                    "imports": len([s for s in segments if s.get("type") == "import"]),
                },
            }

        except SyntaxError as e:
            return {
                "success": False,
                "error": f"Python syntax error: {str(e)}",
                "line": getattr(e, "lineno", None),
                "offset": getattr(e, "offset", None),
            }
        except Exception as e:
            logger.error(f"Error splitting Python code: {e}")
            return {"success": False, "error": str(e)}

    def _extract_functions(
        self, tree: ast.AST, lines: list[str], include_metadata: bool
    ) -> list[dict[str, Any]]:
        """Extract function definitions from AST."""
        functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                start_line = node.lineno - 1
                end_line = self._find_node_end_line(node, lines)

                function_code = "\n".join(lines[start_line : end_line + 1])

                function_info = {
                    "type": "function",
                    "name": node.name,
                    "code": function_code,
                    "start_line": start_line + 1,
                    "end_line": end_line + 1,
                    "line_count": end_line - start_line + 1,
                }

                if include_metadata:
                    function_info.update(
                        {
                            "arguments": [arg.arg for arg in node.args.args],
                            "decorators": [ast.unparse(dec) for dec in node.decorator_list],
                            "docstring": ast.get_docstring(node),
                            "is_async": isinstance(node, ast.AsyncFunctionDef),
                            "returns": ast.unparse(node.returns) if node.returns else None,
                        }
                    )

                functions.append(function_info)

        return functions

    def _extract_classes(
        self, tree: ast.AST, lines: list[str], include_metadata: bool
    ) -> list[dict[str, Any]]:
        """Extract class definitions from AST."""
        classes = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                start_line = node.lineno - 1
                end_line = self._find_node_end_line(node, lines)

                class_code = "\n".join(lines[start_line : end_line + 1])

                class_info = {
                    "type": "class",
                    "name": node.name,
                    "code": class_code,
                    "start_line": start_line + 1,
                    "end_line": end_line + 1,
                    "line_count": end_line - start_line + 1,
                }

                if include_metadata:
                    methods = [
                        n.name
                        for n in node.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ]
                    bases = [ast.unparse(base) for base in node.bases]

                    class_info.update(
                        {
                            "methods": methods,
                            "base_classes": bases,
                            "decorators": [ast.unparse(dec) for dec in node.decorator_list],
                            "docstring": ast.get_docstring(node),
                            "method_count": len(methods),
                        }
                    )

                classes.append(class_info)

        return classes

    def _extract_methods(
        self, tree: ast.AST, lines: list[str], include_metadata: bool
    ) -> list[dict[str, Any]]:
        """Extract method definitions from classes."""
        methods = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                for method_node in node.body:
                    if isinstance(method_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        start_line = method_node.lineno - 1
                        end_line = self._find_node_end_line(method_node, lines)

                        method_code = "\n".join(lines[start_line : end_line + 1])

                        method_info = {
                            "type": "method",
                            "name": method_node.name,
                            "class_name": class_name,
                            "code": method_code,
                            "start_line": start_line + 1,
                            "end_line": end_line + 1,
                            "line_count": end_line - start_line + 1,
                        }

                        if include_metadata:
                            method_info.update(
                                {
                                    "arguments": [arg.arg for arg in method_node.args.args],
                                    "decorators": [
                                        ast.unparse(dec) for dec in method_node.decorator_list
                                    ],
                                    "docstring": ast.get_docstring(method_node),
                                    "is_async": isinstance(method_node, ast.AsyncFunctionDef),
                                    "is_property": any(
                                        "property" in ast.unparse(dec)
                                        for dec in method_node.decorator_list
                                    ),
                                    "is_static": any(
                                        "staticmethod" in ast.unparse(dec)
                                        for dec in method_node.decorator_list
                                    ),
                                    "is_class_method": any(
                                        "classmethod" in ast.unparse(dec)
                                        for dec in method_node.decorator_list
                                    ),
                                }
                            )

                        methods.append(method_info)

        return methods

    def _extract_imports(
        self, tree: ast.AST, lines: list[str], include_metadata: bool
    ) -> list[dict[str, Any]]:
        """Extract import statements."""
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                start_line = node.lineno - 1
                import_code = lines[start_line]

                import_info = {
                    "type": "import",
                    "code": import_code,
                    "start_line": start_line + 1,
                    "end_line": start_line + 1,
                    "line_count": 1,
                }

                if include_metadata:
                    if isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                        import_info.update(
                            {"import_type": "import", "modules": modules, "from_module": None}
                        )
                    else:  # ImportFrom
                        modules = [alias.name for alias in node.names]
                        import_info.update(
                            {
                                "import_type": "from_import",
                                "modules": modules,
                                "from_module": node.module,
                            }
                        )

                imports.append(import_info)

        return imports

    def _extract_comments(self, lines: list[str], include_metadata: bool) -> list[dict[str, Any]]:
        """Extract standalone comments."""
        comments = []
        current_comment = []
        start_line = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                if not current_comment:
                    start_line = i
                current_comment.append(line)
            else:
                if current_comment:
                    comment_code = "\n".join(current_comment)
                    comment_info = {
                        "type": "comment",
                        "code": comment_code,
                        "start_line": start_line + 1,
                        "end_line": i,
                        "line_count": len(current_comment),
                    }

                    if include_metadata:
                        comment_info["is_docstring"] = False
                        comment_info["content"] = "\n".join(
                            [line.strip().lstrip("#").strip() for line in current_comment]
                        )

                    comments.append(comment_info)
                    current_comment = []

        # Handle trailing comments
        if current_comment:
            comment_code = "\n".join(current_comment)
            comment_info = {
                "type": "comment",
                "code": comment_code,
                "start_line": start_line + 1,
                "end_line": len(lines),
                "line_count": len(current_comment),
            }
            comments.append(comment_info)

        return comments

    def _find_node_end_line(self, node: ast.AST, lines: list[str]) -> int:
        """Find the end line of an AST node."""
        if hasattr(node, "end_lineno") and node.end_lineno:
            return node.end_lineno - 1

        # Fallback: find by indentation
        start_line = node.lineno - 1
        if start_line >= len(lines):
            return len(lines) - 1

        # Get the indentation of the node
        start_line_content = lines[start_line]
        base_indent = len(start_line_content) - len(start_line_content.lstrip())

        # Find where indentation returns to base level or less
        for i in range(start_line + 1, len(lines)):
            line = lines[i]
            if line.strip():  # Non-empty line
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= base_indent:
                    return i - 1

        return len(lines) - 1

    def analyze_code_structure(
        self,
        code: str,
        language: str = "python",
        include_complexity: bool = True,
        include_dependencies: bool = True,
    ) -> dict[str, Any]:
        """Analyze code structure and complexity."""
        if language != "python":
            return {"success": False, "error": f"Language '{language}' not supported yet"}

        try:
            tree = ast.parse(code)
            lines = code.split("\n")

            analysis = {
                "success": True,
                "language": language,
                "total_lines": len(lines),
                "non_empty_lines": len([line for line in lines if line.strip()]),
                "comment_lines": len([line for line in lines if line.strip().startswith("#")]),
            }

            # Count code elements
            functions = []
            classes = []
            imports = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        imports.extend([alias.name for alias in node.names])
                    else:
                        imports.append(node.module or "relative_import")

            analysis.update(
                {
                    "functions": functions,
                    "classes": classes,
                    "function_count": len(functions),
                    "class_count": len(classes),
                    "import_count": len(set(imports)),
                }
            )

            if include_complexity:
                complexity = self._calculate_complexity(tree)
                analysis["complexity"] = complexity

            if include_dependencies:
                dependencies = self._analyze_dependencies(tree)
                analysis["dependencies"] = dependencies

            return analysis

        except SyntaxError as e:
            return {
                "success": False,
                "error": f"Syntax error: {str(e)}",
                "line": getattr(e, "lineno", None),
            }
        except Exception as e:
            logger.error(f"Error analyzing code: {e}")
            return {"success": False, "error": str(e)}

    def _calculate_complexity(self, tree: ast.AST) -> dict[str, Any]:
        """Calculate cyclomatic complexity and other metrics."""
        complexity_nodes = [
            ast.If,
            ast.While,
            ast.For,
            ast.AsyncFor,
            ast.ExceptHandler,
            ast.With,
            ast.AsyncWith,
            ast.BoolOp,
            ast.Compare,
        ]

        complexity = 1  # Base complexity
        for node in ast.walk(tree):
            if any(isinstance(node, node_type) for node_type in complexity_nodes):
                complexity += 1

        # Count nested levels
        class DepthVisitor(ast.NodeVisitor):
            def __init__(self):
                self.max_depth = 0
                self.current_depth = 0

            def visit_FunctionDef(self, node):
                self.current_depth += 1
                self.max_depth = max(self.max_depth, self.current_depth)
                self.generic_visit(node)
                self.current_depth -= 1

            def visit_ClassDef(self, node):
                self.current_depth += 1
                self.max_depth = max(self.max_depth, self.current_depth)
                self.generic_visit(node)
                self.current_depth -= 1

        visitor = DepthVisitor()
        visitor.visit(tree)

        return {
            "cyclomatic_complexity": complexity,
            "max_nesting_depth": visitor.max_depth,
            "complexity_rating": "low"
            if complexity < 10
            else "medium"
            if complexity < 20
            else "high",
        }

    def _analyze_dependencies(self, tree: ast.AST) -> dict[str, Any]:
        """Analyze code dependencies."""
        imports = {"standard_library": [], "third_party": [], "local": []}
        standard_lib_modules = {
            "os",
            "sys",
            "re",
            "json",
            "time",
            "datetime",
            "math",
            "random",
            "collections",
            "itertools",
            "functools",
            "pathlib",
            "typing",
            "asyncio",
            "threading",
            "multiprocessing",
            "subprocess",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]
                    if module in standard_lib_modules:
                        imports["standard_library"].append(alias.name)
                    else:
                        imports["third_party"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split(".")[0]
                    if module in standard_lib_modules:
                        imports["standard_library"].append(node.module)
                    else:
                        imports["third_party"].append(node.module)
                else:
                    imports["local"].extend([alias.name for alias in node.names])

        return {
            "imports": imports,
            "total_imports": sum(len(v) for v in imports.values()),
            "external_dependencies": len(imports["third_party"]) > 0,
        }

    def extract_functions_only(
        self,
        code: str,
        language: str = "python",
        include_docstrings: bool = True,
        include_decorators: bool = True,
    ) -> dict[str, Any]:
        """Extract only function definitions."""
        if language != "python":
            return {"success": False, "error": f"Language '{language}' not supported"}

        try:
            tree = ast.parse(code)
            lines = code.split("\n")
            functions = []

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start_line = node.lineno - 1
                    end_line = self._find_node_end_line(node, lines)

                    function_code = "\n".join(lines[start_line : end_line + 1])

                    function_info = {
                        "name": node.name,
                        "code": function_code,
                        "line_range": [start_line + 1, end_line + 1],
                        "is_async": isinstance(node, ast.AsyncFunctionDef),
                        "arguments": [arg.arg for arg in node.args.args],
                    }

                    if include_docstrings:
                        function_info["docstring"] = ast.get_docstring(node)

                    if include_decorators:
                        function_info["decorators"] = [
                            ast.unparse(dec) for dec in node.decorator_list
                        ]

                    functions.append(function_info)

            return {
                "success": True,
                "language": language,
                "functions": functions,
                "function_count": len(functions),
            }

        except Exception as e:
            logger.error(f"Error extracting functions: {e}")
            return {"success": False, "error": str(e)}

    def extract_classes_only(
        self,
        code: str,
        language: str = "python",
        include_methods: bool = True,
        include_inheritance: bool = True,
    ) -> dict[str, Any]:
        """Extract only class definitions."""
        if language != "python":
            return {"success": False, "error": f"Language '{language}' not supported"}

        try:
            tree = ast.parse(code)
            lines = code.split("\n")
            classes = []

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    start_line = node.lineno - 1
                    end_line = self._find_node_end_line(node, lines)

                    class_code = "\n".join(lines[start_line : end_line + 1])

                    class_info = {
                        "name": node.name,
                        "code": class_code,
                        "line_range": [start_line + 1, end_line + 1],
                        "docstring": ast.get_docstring(node),
                    }

                    if include_methods:
                        methods = []
                        for method_node in node.body:
                            if isinstance(method_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                methods.append(
                                    {
                                        "name": method_node.name,
                                        "is_async": isinstance(method_node, ast.AsyncFunctionDef),
                                        "arguments": [arg.arg for arg in method_node.args.args],
                                        "line_range": [
                                            method_node.lineno,
                                            self._find_node_end_line(method_node, lines) + 1,
                                        ],
                                    }
                                )
                        class_info["methods"] = methods

                    if include_inheritance:
                        class_info["base_classes"] = [ast.unparse(base) for base in node.bases]
                        class_info["decorators"] = [ast.unparse(dec) for dec in node.decorator_list]

                    classes.append(class_info)

            return {
                "success": True,
                "language": language,
                "classes": classes,
                "class_count": len(classes),
            }

        except Exception as e:
            logger.error(f"Error extracting classes: {e}")
            return {"success": False, "error": str(e)}


# Initialize splitter
splitter = CodeSplitter()


# Tool definitions using FastMCP
@mcp.tool(description="Split code into logical segments using AST analysis")
async def split_code(
    code: str = Field(..., description="Source code to split"),
    language: str = Field(
        "python", pattern="^python$", description="Programming language (currently only Python)"
    ),
    split_level: str = Field(
        "function",
        pattern="^(function|class|method|import|all)$",
        description="What to extract: function, class, method, import, or all",
    ),
    include_metadata: bool = Field(
        True, description="Include detailed metadata about code segments"
    ),
    preserve_comments: bool = Field(True, description="Include comments in output"),
    min_lines: int = Field(5, ge=1, description="Minimum lines per segment"),
) -> dict[str, Any]:
    """Split code into logical segments using AST analysis."""
    return splitter.split_python_code(
        code=code,
        split_level=split_level,
        include_metadata=include_metadata,
        preserve_comments=preserve_comments,
        min_lines=min_lines,
    )


@mcp.tool(description="Analyze code structure, complexity, and dependencies")
async def analyze_code(
    code: str = Field(..., description="Source code to analyze"),
    language: str = Field("python", pattern="^python$", description="Programming language"),
    include_complexity: bool = Field(True, description="Include complexity metrics"),
    include_dependencies: bool = Field(True, description="Include dependency analysis"),
) -> dict[str, Any]:
    """Analyze code structure and complexity."""
    return splitter.analyze_code_structure(
        code=code,
        language=language,
        include_complexity=include_complexity,
        include_dependencies=include_dependencies,
    )


@mcp.tool(description="Extract function definitions from code")
async def extract_functions(
    code: str = Field(..., description="Source code"),
    language: str = Field("python", pattern="^python$", description="Programming language"),
    include_docstrings: bool = Field(True, description="Include function docstrings"),
    include_decorators: bool = Field(True, description="Include function decorators"),
) -> dict[str, Any]:
    """Extract all function definitions from code."""
    return splitter.extract_functions_only(
        code=code,
        language=language,
        include_docstrings=include_docstrings,
        include_decorators=include_decorators,
    )


@mcp.tool(description="Extract class definitions from code")
async def extract_classes(
    code: str = Field(..., description="Source code"),
    language: str = Field("python", pattern="^python$", description="Programming language"),
    include_methods: bool = Field(True, description="Include class methods"),
    include_inheritance: bool = Field(True, description="Include inheritance information"),
) -> dict[str, Any]:
    """Extract all class definitions from code."""
    return splitter.extract_classes_only(
        code=code,
        language=language,
        include_methods=include_methods,
        include_inheritance=include_inheritance,
    )


def main():
    """Main server entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Code Splitter FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9002, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting Code Splitter FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting Code Splitter FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
