# Code Splitter MCP Server

> Author: Mihai Criveti

AST-based code analysis and splitting for intelligent code segmentation. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **AST-Based Analysis**: Uses Python Abstract Syntax Tree for accurate parsing
- **Multiple Split Levels**: Functions, classes, methods, imports, or all
- **Detailed Metadata**: Function signatures, docstrings, decorators, inheritance
- **Complexity Analysis**: Cyclomatic complexity and nesting depth analysis
- **Dependency Analysis**: Import analysis and dependency categorization
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Installation

```bash
# Basic installation with FastMCP
make install

# Installation with development dependencies
make dev-install
```

## Usage

### Running the FastMCP Server

```bash
# Start the server
make dev

# Or directly
python -m code_splitter_server.server_fastmcp
```

### HTTP Bridge

Expose the server over HTTP for REST API access:

```bash
make serve-http
```

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

**Example:**
```json
{
  "code": "def hello():\n    print('Hello')\n\nclass MyClass:\n    pass",
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
      "code": "class MyClass:\n    pass",
      "start_line": 4,
      "end_line": 5,
      "methods": [],
      "base_classes": []
    }
  ]
}
```

### analyze_code
Analyze code structure, complexity, and dependencies.

**Parameters:**
- `code` (required): Source code to analyze
- `language`: Programming language (default: "python")
- `include_complexity`: Include complexity metrics (default: true)
- `include_dependencies`: Include dependency analysis (default: true)

**Example:**
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

### extract_functions
Extract only function definitions from code.

**Parameters:**
- `code` (required): Source code
- `language`: Programming language (default: "python")
- `include_docstrings`: Include function docstrings (default: true)
- `include_decorators`: Include function decorators (default: true)

**Example:**
```json
{
  "code": "@decorator\ndef my_func(x, y):\n    '''Docstring'''\n    return x + y",
  "include_docstrings": true,
  "include_decorators": true
}
```

### extract_classes
Extract only class definitions from code.

**Parameters:**
- `code` (required): Source code
- `language`: Programming language (default: "python")
- `include_methods`: Include class methods (default: true)
- `include_inheritance`: Include inheritance information (default: true)

**Example:**
```json
{
  "code": "class MyClass(BaseClass):\n    def __init__(self):\n        pass",
  "include_methods": true,
  "include_inheritance": true
}
```

## Supported Languages

- **Python**: Full AST support with comprehensive analysis
- **Future**: JavaScript, TypeScript, Java (with tree-sitter integration)

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

## Examples

### Splitting a Python Module

```bash
make example-split
```

This will split example code and show the extracted segments.

### Analyzing Code Complexity

```bash
make example-analyze
```

This will analyze example code and show complexity metrics.

### Real-World Example

```python
# Input code
code = """
import os
import sys
from typing import List, Dict

class DataProcessor:
    '''Processes data with various methods.'''

    def __init__(self, config: Dict):
        self.config = config

    @property
    def name(self) -> str:
        return self.config.get('name', 'default')

    def process(self, data: List) -> List:
        '''Process the data list.'''
        result = []
        for item in data:
            if self._validate(item):
                result.append(self._transform(item))
        return result

    def _validate(self, item) -> bool:
        return item is not None

    def _transform(self, item):
        return str(item).upper()

def helper_function(x: int) -> int:
    '''Helper function for calculations.'''
    return x * 2
"""

# Using split_code with split_level="all"
# Returns all functions, classes, methods, and imports as separate segments
```

## Development

### Running Tests
```bash
make test
```

### Code Formatting
```bash
make format
```

### Linting
```bash
make lint
```

## FastMCP Advantages

The FastMCP implementation provides:

1. **Type-Safe Parameters**: Automatic validation using Pydantic Field constraints
2. **Pattern Validation**: Ensures only valid options are accepted (e.g., language must be "python")
3. **Cleaner Code**: Decorator-based tool definitions (`@mcp.tool`)
4. **Better Error Handling**: Built-in exception management
5. **Automatic Schema Generation**: No manual JSON schema definitions

## Troubleshooting

### Syntax Errors

If code splitting fails with syntax errors:
- Ensure the code is valid Python
- Check for proper indentation
- Verify all brackets and quotes are balanced

### Performance

For large files:
- Consider splitting by specific levels instead of "all"
- Increase `min_lines` to reduce number of small segments
- Disable metadata if not needed

## License

Apache-2.0 License - See LICENSE file for details

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request
