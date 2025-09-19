#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/python_sandbox_server/src/python_sandbox_server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Python Sandbox MCP Server

A highly secure MCP server for executing Python code in a sandboxed environment.
Uses RestrictedPython for code transformation and optional gVisor containers for isolation.

Security Features:
- RestrictedPython for AST-level code restriction
- Resource limits (memory, CPU, execution time)
- Namespace isolation with safe builtins
- Optional container-based execution with gVisor
- Comprehensive logging and monitoring
- Input validation and output sanitization
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool
from pydantic import BaseModel, Field

# Configure logging to stderr to avoid MCP protocol interference
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Create server instance
server = Server("python-sandbox-server")

# Configuration constants
DEFAULT_TIMEOUT = int(os.getenv("SANDBOX_DEFAULT_TIMEOUT", "30"))
MAX_TIMEOUT = int(os.getenv("SANDBOX_MAX_TIMEOUT", "300"))
DEFAULT_MEMORY_LIMIT = os.getenv("SANDBOX_DEFAULT_MEMORY_LIMIT", "128m")
MAX_OUTPUT_SIZE = int(os.getenv("SANDBOX_MAX_OUTPUT_SIZE", "1048576"))  # 1MB
ENABLE_CONTAINER_MODE = os.getenv("SANDBOX_ENABLE_CONTAINER_MODE", "false").lower() == "true"
CONTAINER_IMAGE = os.getenv("SANDBOX_CONTAINER_IMAGE", "python-sandbox:latest")


class ExecuteCodeRequest(BaseModel):
    """Request to execute Python code."""
    code: str = Field(..., description="Python code to execute")
    timeout: int = Field(DEFAULT_TIMEOUT, description="Execution timeout in seconds", le=MAX_TIMEOUT)
    memory_limit: str = Field(DEFAULT_MEMORY_LIMIT, description="Memory limit (e.g., '128m', '512m')")
    use_container: bool = Field(False, description="Use container-based execution")
    allowed_imports: List[str] = Field(default_factory=list, description="List of allowed import modules")
    capture_output: bool = Field(True, description="Capture stdout/stderr output")


class ValidateCodeRequest(BaseModel):
    """Request to validate Python code without execution."""
    code: str = Field(..., description="Python code to validate")


class ListCapabilitiesRequest(BaseModel):
    """Request to list sandbox capabilities."""
    pass


class PythonSandbox:
    """Secure Python code execution sandbox."""

    def __init__(self):
        """Initialize the sandbox."""
        self.restricted_python_available = self._check_restricted_python()
        self.container_runtime_available = self._check_container_runtime()

    def _check_restricted_python(self) -> bool:
        """Check if RestrictedPython is available."""
        try:
            import RestrictedPython
            return True
        except ImportError:
            logger.warning("RestrictedPython not available, using basic validation")
            return False

    def _check_container_runtime(self) -> bool:
        """Check if container runtime is available."""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Docker runtime not available")
            return False

    def create_safe_globals(self, allowed_imports: List[str] = None) -> Dict[str, Any]:
        """Create a safe global namespace for code execution."""
        if allowed_imports is None:
            allowed_imports = []

        # Safe built-in functions
        safe_builtins = {
            # Basic types and constructors
            'bool': bool, 'int': int, 'float': float, 'str': str, 'list': list,
            'dict': dict, 'tuple': tuple, 'set': set, 'frozenset': frozenset,

            # Safe functions
            'len': len, 'abs': abs, 'min': min, 'max': max, 'sum': sum,
            'round': round, 'sorted': sorted, 'reversed': reversed,
            'enumerate': enumerate, 'zip': zip, 'map': map, 'filter': filter,
            'any': any, 'all': all, 'range': range,

            # String and formatting
            'print': print, 'repr': repr, 'ord': ord, 'chr': chr,
            'format': format,

            # Math (basic)
            'divmod': divmod, 'pow': pow,

            # Exceptions that might be useful
            'ValueError': ValueError, 'TypeError': TypeError, 'IndexError': IndexError,
            'KeyError': KeyError, 'AttributeError': AttributeError,

            # Safe iterators
            'iter': iter, 'next': next,
        }

        # Safe modules that can be imported
        safe_modules = {}
        allowed_safe_modules = {
            'math': ['math'],
            'random': ['random'],
            'datetime': ['datetime'],
            'json': ['json'],
            'base64': ['base64'],
            'hashlib': ['hashlib'],
            'uuid': ['uuid'],
            'collections': ['collections'],
            'itertools': ['itertools'],
            'functools': ['functools'],
            're': ['re'],
            'string': ['string'],
            'decimal': ['decimal'],
            'fractions': ['fractions'],
            'statistics': ['statistics'],
        }

        # Add requested safe modules
        for module_name in allowed_imports:
            if module_name in allowed_safe_modules:
                try:
                    module = __import__(module_name)
                    safe_modules[module_name] = module
                except ImportError:
                    logger.warning(f"Could not import requested module: {module_name}")

        return {
            '__builtins__': safe_builtins,
            **safe_modules,
            # Add some useful constants
            'True': True, 'False': False, 'None': None,
        }

    def validate_code(self, code: str) -> Dict[str, Any]:
        """Validate Python code using RestrictedPython."""
        if not self.restricted_python_available:
            return {"valid": True, "message": "RestrictedPython not available, basic validation only"}

        try:
            from RestrictedPython import compile_restricted

            # Compile the code with restrictions
            compiled_result = compile_restricted(code, '<sandbox>', 'exec')

            # Check if compilation was successful
            if hasattr(compiled_result, 'errors') and compiled_result.errors:
                return {
                    "valid": False,
                    "errors": compiled_result.errors,
                    "message": "Code contains restricted operations"
                }
            elif hasattr(compiled_result, 'code') and compiled_result.code is None:
                return {
                    "valid": False,
                    "errors": ["Compilation failed"],
                    "message": "Code could not be compiled"
                }

            return {
                "valid": True,
                "message": "Code passed validation",
                "compiled": True
            }

        except Exception as e:
            logger.error(f"Error validating code: {e}")
            return {
                "valid": False,
                "message": f"Validation error: {str(e)}"
            }

    def create_output_capture(self) -> Tuple[StringIO, StringIO]:
        """Create output capture streams."""
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        return stdout_capture, stderr_capture

    async def execute_code_restricted(
        self,
        code: str,
        timeout: int = DEFAULT_TIMEOUT,
        allowed_imports: List[str] = None,
        capture_output: bool = True
    ) -> Dict[str, Any]:
        """Execute code using RestrictedPython."""
        execution_id = str(uuid4())
        logger.info(f"Executing code with RestrictedPython, ID: {execution_id}")

        if not self.restricted_python_available:
            return {
                "success": False,
                "error": "RestrictedPython not available",
                "execution_id": execution_id
            }

        try:
            from RestrictedPython import compile_restricted
            from RestrictedPython.Guards import safe_builtins, safe_globals, safer_getattr

            # Validate and compile code
            validation_result = self.validate_code(code)
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "error": "Code validation failed",
                    "details": validation_result,
                    "execution_id": execution_id
                }

            # Compile the restricted code
            compiled_code = compile_restricted(code, '<sandbox>', 'exec')
            if compiled_code.errors:
                return {
                    "success": False,
                    "error": "Compilation failed",
                    "details": compiled_code.errors,
                    "execution_id": execution_id
                }

            # Create safe execution environment
            safe_globals_dict = self.create_safe_globals(allowed_imports)
            safe_globals_dict.update({
                '__metaclass__': type,
                '_getattr_': safer_getattr,
                '_getitem_': lambda obj, key: obj[key],
                '_getiter_': lambda obj: iter(obj),
                '_print_': lambda *args, **kwargs: print(*args, **kwargs),
            })

            # Capture output if requested
            if capture_output:
                stdout_capture, stderr_capture = self.create_output_capture()
                original_stdout = sys.stdout
                original_stderr = sys.stderr
                sys.stdout = stdout_capture
                sys.stderr = stderr_capture

            start_time = time.time()
            local_vars = {}

            try:
                # Execute with timeout using signal (Unix only)
                def timeout_handler(signum, frame):
                    raise TimeoutError(f"Code execution timed out after {timeout} seconds")

                if hasattr(signal, 'SIGALRM'):  # Unix systems only
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(timeout)

                # Execute the code
                exec(compiled_code.code, safe_globals_dict, local_vars)

                if hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)  # Cancel the alarm

                execution_time = time.time() - start_time

                # Capture output
                stdout_output = ""
                stderr_output = ""
                if capture_output:
                    stdout_output = stdout_capture.getvalue()
                    stderr_output = stderr_capture.getvalue()

                # Get the result (look for common result variables)
                result = None
                for var_name in ['result', '_', '__result__', 'output']:
                    if var_name in local_vars:
                        result = local_vars[var_name]
                        break

                # If no explicit result, try to get the last expression
                if result is None and local_vars:
                    # Get non-private variables
                    public_vars = {k: v for k, v in local_vars.items() if not k.startswith('_')}
                    if public_vars:
                        result = list(public_vars.values())[-1]

                # Format result for JSON serialization
                formatted_result = self._format_result(result)

                return {
                    "success": True,
                    "execution_id": execution_id,
                    "result": formatted_result,
                    "stdout": stdout_output[:MAX_OUTPUT_SIZE],
                    "stderr": stderr_output[:MAX_OUTPUT_SIZE],
                    "execution_time": execution_time,
                    "variables": list(local_vars.keys())
                }

            except TimeoutError as e:
                return {
                    "success": False,
                    "error": "Execution timeout",
                    "execution_id": execution_id,
                    "timeout": timeout
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "execution_id": execution_id,
                    "traceback": traceback.format_exc()
                }
            finally:
                if hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)
                if capture_output:
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr

        except Exception as e:
            logger.error(f"Error in restricted execution: {e}")
            return {
                "success": False,
                "error": f"Sandbox error: {str(e)}",
                "execution_id": execution_id
            }

    async def execute_code_container(
        self,
        code: str,
        timeout: int = DEFAULT_TIMEOUT,
        memory_limit: str = DEFAULT_MEMORY_LIMIT
    ) -> Dict[str, Any]:
        """Execute code in a gVisor container."""
        execution_id = str(uuid4())
        logger.info(f"Executing code in container, ID: {execution_id}")

        if not self.container_runtime_available:
            return {
                "success": False,
                "error": "Container runtime not available",
                "execution_id": execution_id
            }

        try:
            # Create temporary file for code
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                code_file = f.name

            # Prepare container execution command
            cmd = [
                "timeout", str(timeout),
                "docker", "run", "--rm",
                "--memory", memory_limit,
                "--cpus", "0.5",  # Limit CPU usage
                "--network", "none",  # No network access
                "--user", "1001:1001",  # Non-root user
                "-v", f"{code_file}:/tmp/code.py:ro",  # Mount code as read-only
            ]

            # Use gVisor if available
            if ENABLE_CONTAINER_MODE:
                cmd.extend(["--runtime", "runsc"])

            cmd.extend([
                CONTAINER_IMAGE,
                "python", "/tmp/code.py"
            ])

            logger.debug(f"Container command: {' '.join(cmd)}")

            # Execute in container
            start_time = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5  # Add buffer for container overhead
            )
            execution_time = time.time() - start_time

            # Clean up
            os.unlink(code_file)

            if result.returncode == 124:  # timeout command return code
                return {
                    "success": False,
                    "error": "Container execution timeout",
                    "execution_id": execution_id,
                    "timeout": timeout
                }
            elif result.returncode != 0:
                return {
                    "success": False,
                    "error": "Container execution failed",
                    "execution_id": execution_id,
                    "return_code": result.returncode,
                    "stderr": result.stderr[:MAX_OUTPUT_SIZE]
                }

            return {
                "success": True,
                "execution_id": execution_id,
                "stdout": result.stdout[:MAX_OUTPUT_SIZE],
                "stderr": result.stderr[:MAX_OUTPUT_SIZE],
                "execution_time": execution_time,
                "return_code": result.returncode
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Container execution timeout (hard limit)",
                "execution_id": execution_id
            }
        except Exception as e:
            logger.error(f"Error in container execution: {e}")
            return {
                "success": False,
                "error": f"Container error: {str(e)}",
                "execution_id": execution_id
            }

    def _format_result(self, result: Any) -> Any:
        """Format execution result for JSON serialization."""
        if result is None:
            return None
        elif isinstance(result, (str, int, float, bool)):
            return result
        elif isinstance(result, (list, tuple)):
            return [self._format_result(item) for item in result[:100]]  # Limit size
        elif isinstance(result, dict):
            formatted_dict = {}
            for k, v in list(result.items())[:100]:  # Limit size
                formatted_dict[str(k)] = self._format_result(v)
            return formatted_dict
        elif hasattr(result, '__dict__'):
            return f"<{type(result).__name__} object>"
        else:
            return str(result)[:1000]  # Limit string length

    async def execute_code(
        self,
        code: str,
        timeout: int = DEFAULT_TIMEOUT,
        memory_limit: str = DEFAULT_MEMORY_LIMIT,
        use_container: bool = False,
        allowed_imports: List[str] = None,
        capture_output: bool = True
    ) -> Dict[str, Any]:
        """Execute Python code with the specified method."""
        if allowed_imports is None:
            allowed_imports = []

        logger.info(f"Executing code, container mode: {use_container}")

        # Basic input validation
        if not code.strip():
            return {
                "success": False,
                "error": "Empty code provided"
            }

        if len(code) > 100000:  # 100KB limit
            return {
                "success": False,
                "error": "Code too large (max 100KB)"
            }

        # Check for obviously dangerous patterns
        dangerous_patterns = [
            r'import\s+os',
            r'import\s+sys',
            r'import\s+subprocess',
            r'__import__',
            r'eval\s*\(',
            r'exec\s*\(',
            r'compile\s*\(',
            r'open\s*\(',
            r'file\s*\(',
        ]

        for pattern in dangerous_patterns:
            import re
            if re.search(pattern, code, re.IGNORECASE):
                return {
                    "success": False,
                    "error": f"Potentially dangerous operation detected: {pattern}"
                }

        # Choose execution method
        if use_container and self.container_runtime_available:
            return await self.execute_code_container(code, timeout, memory_limit)
        else:
            return await self.execute_code_restricted(code, timeout, allowed_imports, capture_output)

    async def validate_code_only(self, code: str) -> Dict[str, Any]:
        """Validate code without executing it."""
        validation_result = self.validate_code(code)

        # Additional static analysis
        analysis = {
            "line_count": len(code.split('\n')),
            "character_count": len(code),
            "estimated_complexity": "low"  # Simple heuristic
        }

        # Basic complexity estimation
        if any(keyword in code for keyword in ['for', 'while', 'if', 'def', 'class']):
            analysis["estimated_complexity"] = "medium"
        if any(keyword in code for keyword in ['nested', 'recursive', 'lambda']):
            analysis["estimated_complexity"] = "high"

        return {
            "validation": validation_result,
            "analysis": analysis,
            "recommendations": self._get_code_recommendations(code)
        }

    def _get_code_recommendations(self, code: str) -> List[str]:
        """Get recommendations for code improvement."""
        recommendations = []

        if len(code.split('\n')) > 50:
            recommendations.append("Consider breaking large code blocks into smaller functions")

        if 'print(' in code:
            recommendations.append("Output will be captured automatically")

        if any(word in code.lower() for word in ['import', 'open', 'file']):
            recommendations.append("Some operations may be restricted in sandbox environment")

        return recommendations

    def list_capabilities(self) -> Dict[str, Any]:
        """List sandbox capabilities and configuration."""
        return {
            "sandbox_type": "RestrictedPython + Optional Container",
            "restricted_python_available": self.restricted_python_available,
            "container_runtime_available": self.container_runtime_available,
            "container_mode_enabled": ENABLE_CONTAINER_MODE,
            "limits": {
                "default_timeout": DEFAULT_TIMEOUT,
                "max_timeout": MAX_TIMEOUT,
                "default_memory_limit": DEFAULT_MEMORY_LIMIT,
                "max_output_size": MAX_OUTPUT_SIZE
            },
            "safe_modules": [
                "math", "random", "datetime", "json", "base64", "hashlib",
                "uuid", "collections", "itertools", "functools", "re",
                "string", "decimal", "fractions", "statistics"
            ],
            "security_features": [
                "RestrictedPython AST transformation",
                "Safe builtins only",
                "Namespace isolation",
                "Resource limits",
                "Timeout protection",
                "Output size limits",
                "Container isolation (optional)",
                "gVisor support (optional)"
            ]
        }


# Initialize sandbox (conditionally for testing)
try:
    sandbox = PythonSandbox()
except Exception:
    sandbox = None


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available Python sandbox tools."""
    return [
        Tool(
            name="execute_code",
            description="Execute Python code in a secure sandbox environment",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds",
                        "default": DEFAULT_TIMEOUT,
                        "maximum": MAX_TIMEOUT
                    },
                    "memory_limit": {
                        "type": "string",
                        "description": "Memory limit (e.g., '128m', '512m')",
                        "default": DEFAULT_MEMORY_LIMIT
                    },
                    "use_container": {
                        "type": "boolean",
                        "description": "Use container-based execution for additional isolation",
                        "default": False
                    },
                    "allowed_imports": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of allowed import modules",
                        "default": []
                    },
                    "capture_output": {
                        "type": "boolean",
                        "description": "Capture stdout/stderr output",
                        "default": True
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="validate_code",
            description="Validate Python code without executing it",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to validate"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="list_capabilities",
            description="List sandbox capabilities and security features",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Handle tool calls."""
    try:
        if sandbox is None:
            result = {"success": False, "error": "Python sandbox not available"}
        elif name == "execute_code":
            request = ExecuteCodeRequest(**arguments)
            result = await sandbox.execute_code(
                code=request.code,
                timeout=request.timeout,
                memory_limit=request.memory_limit,
                use_container=request.use_container,
                allowed_imports=request.allowed_imports,
                capture_output=request.capture_output
            )

        elif name == "validate_code":
            request = ValidateCodeRequest(**arguments)
            result = await sandbox.validate_code_only(code=request.code)

        elif name == "list_capabilities":
            result = sandbox.list_capabilities()

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

    except Exception as e:
        logger.error(f"Error in {name}: {str(e)}")
        result = {"success": False, "error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    """Main server entry point."""
    logger.info("Starting Python Sandbox MCP Server...")

    from mcp.server.stdio import stdio_server

    logger.info("Waiting for MCP client connection...")
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP client connected, starting server...")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="python-sandbox-server",
                server_version="0.1.0",
                capabilities={
                    "tools": {},
                    "logging": {},
                },
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
