# Code Splitter Server

## Overview

The Code Splitter MCP Server provides AST-based code analysis and splitting for intelligent code segmentation. It uses Python's Abstract Syntax Tree to accurately parse and segment code into logical components while providing detailed metadata about each segment. The server is powered by FastMCP for enhanced type safety and automatic validation.

### Key Features

- **AST-Based Analysis**: Uses Python Abstract Syntax Tree for accurate parsing
- **Multiple Split Levels**: Functions, classes, methods, imports, or all
- **Detailed Metadata**: Function signatures, docstrings, decorators, inheritance
- **Complexity Analysis**: Cyclomatic complexity and nesting depth analysis
- **Dependency Analysis**: Import analysis and dependency categorization
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Quick Start

### Installation

```bash
# Basic installation with FastMCP
make install

# Installation with development dependencies
make dev-install
```

### Running the Server

```bash
# Start the FastMCP server
make dev

# Or directly
python -m code_splitter_server.server_fastmcp

# HTTP bridge for REST API access
make serve-http
```

## Available Tools

### split_code
Split code into logical segments using AST analysis.

**Parameters:**

- `code` (required): Source code to split
- `language`: Programming language (currently "python" only)
- `split_level`: What to extract - "function", "class", "method", "import", or "all"
- `include_metadata`: Include detailed metadata (default: true)
- `preserve_comments`: Include comments in output (default: true)
- `min_lines`: Minimum lines per segment (default: 5, min: 1)

**Returns:**

- `success`: Boolean indicating success/failure
- `language`: Programming language used
- `split_level`: The split level used
- `total_segments`: Number of segments created
- `segments`: Array of code segments with metadata

### analyze_code
Analyze code structure, complexity, and dependencies.

**Parameters:**

- `code` (required): Source code to analyze
- `language`: Programming language (default: "python")
- `include_complexity`: Include complexity metrics (default: true)
- `include_dependencies`: Include dependency analysis (default: true)

**Returns:**

- Code statistics and structure information
- Complexity metrics (cyclomatic complexity, nesting depth)
- Dependency analysis (imports categorized by type)

### extract_functions
Extract only function definitions from code.

**Parameters:**

- `code` (required): Source code
- `language`: Programming language (default: "python")
- `include_docstrings`: Include function docstrings (default: true)
- `include_decorators`: Include function decorators (default: true)

### extract_classes
Extract only class definitions from code.

**Parameters:**

- `code` (required): Source code
- `language`: Programming language (default: "python")
- `include_methods`: Include class methods (default: true)
- `include_inheritance`: Include inheritance information (default: true)

## Configuration

### MCP Client Configuration

```json
{
  "mcpServers": {
    "code-splitter": {
      "command": "python",
      "args": ["-m", "code_splitter_server.server_fastmcp"],
      "cwd": "/path/to/code_splitter_server"
    }
  }
}
```

## Examples

### Split Python Module into All Components

```json
{
  "code": "def hello():\n    print('Hello')\n\nclass MyClass:\n    def method(self):\n        pass",
  "split_level": "all",
  "include_metadata": true
}
```

**Response:**
```json
{
  "success": true,
  "language": "python",
  "split_level": "all",
  "total_segments": 2,
  "segments": [
    {
      "type": "function",
      "name": "hello",
      "code": "def hello():\n    print('Hello')",
      "start_line": 1,
      "end_line": 2,
      "arguments": [],
      "docstring": null
    },
    {
      "type": "class",
      "name": "MyClass",
      "code": "class MyClass:\n    def method(self):\n        pass",
      "start_line": 4,
      "end_line": 6,
      "methods": ["method"],
      "base_classes": []
    }
  ]
}
```

### Analyze Code Complexity

```json
{
  "code": "import os\nimport requests\n\ndef complex_func():\n    if True:\n        for i in range(10):\n            print(i)",
  "include_complexity": true,
  "include_dependencies": true
}
```

**Response:**
```json
{
  "success": true,
  "language": "python",
  "total_lines": 7,
  "function_count": 1,
  "class_count": 0,
  "complexity": {
    "cyclomatic_complexity": 3,
    "max_nesting_depth": 1,
    "complexity_rating": "low"
  },
  "dependencies": {
    "imports": {
      "standard_library": ["os"],
      "third_party": ["requests"],
      "local": []
    },
    "total_imports": 2,
    "external_dependencies": true
  }
}
```

### Extract Functions with Decorators

```json
{
  "code": "@decorator\ndef my_func(x, y):\n    '''Docstring'''\n    return x + y",
  "include_docstrings": true,
  "include_decorators": true
}
```

### Extract Classes with Methods

```json
{
  "code": "class MyClass(BaseClass):\n    def __init__(self):\n        pass\n    def method(self):\n        return True",
  "include_methods": true,
  "include_inheritance": true
}
```

## Integration

### With ContextForge

```bash
# Start the code splitter server via HTTP
make serve-http

# Register with ContextForge
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "code-splitter",
    "url": "http://localhost:9000",
    "description": "AST-based code analysis server"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def split_code():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "code_splitter_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool("split_code", {
                "code": "def example():\n    return 'Hello'",
                "split_level": "function",
                "include_metadata": True
            })

            print(result.content[0].text)

asyncio.run(split_code())
```

## Code Analysis Features

### Split Levels

- **function**: Extract all function definitions
- **class**: Extract all class definitions
- **method**: Extract all methods from classes
- **import**: Extract all import statements
- **all**: Extract everything above

### Complexity Metrics

The complexity analysis includes:

- **Cyclomatic Complexity**: Measures code complexity based on control flow
- **Nesting Depth**: Maximum depth of nested structures
- **Complexity Rating**: Low (<10), Medium (10-20), High (>20)

### Dependency Categorization

Dependencies are categorized into:

- **Standard Library**: Built-in Python modules
- **Third Party**: External packages
- **Local**: Relative imports

## Supported Languages

- **Python**: Full AST support with comprehensive analysis
- **Future**: JavaScript, TypeScript, Java (with tree-sitter integration)

## Use Cases

### Code Documentation Generation
Extract functions and classes to automatically generate API documentation.

### Code Review Assistance
Analyze complexity metrics to identify areas that need refactoring.

### Codebase Migration
Split large files into smaller, more manageable modules.

### Dependency Analysis
Understand import relationships and external dependencies.

### Educational Tools
Help students understand code structure and organization.

## Performance Considerations

### For Large Files
- Consider splitting by specific levels instead of "all"
- Increase `min_lines` to reduce number of small segments
- Disable metadata if not needed

### Syntax Error Handling
If code splitting fails with syntax errors:

- Ensure the code is valid Python
- Check for proper indentation
- Verify all brackets and quotes are balanced
