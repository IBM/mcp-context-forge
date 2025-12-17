# QR Code Server Documentation

MCP server that provides QR code generation, decoding, and validation capabilities.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Tools](#tools)
- [Examples](#examples)
- [MCP Client Setup](#mcp-client-setup)
- [Troubleshooting](#troubleshooting)

## Installation

```bash
# Install in development mode
make dev-install

# Or install normally
make install
```

## Usage

### Running the FastMCP Server

```bash
# Start the server
make dev

# Or directly
python -m qr_code_server.server

# Using installed script
qr-code-server

# Using uvx
uvx --from . qr-code-server
```

**HTTP mode:**
```bash
# Default: http://0.0.0.0:9001
qr-code-server --transport http

# Custom host and port
qr-code-server --transport http --host localhost --port 8080
```

### Test the Server

```bash
# Run tests
make test

## Configuration

Configuration file: `config.yaml`

```yaml
qr_generation:
  default_size: 10                    # QR code box size (pixels)
  default_border: 4                   # Border size (boxes)
  default_error_correction: "M"       # L=7%, M=15%, Q=25%, H=30%
  max_data_length: 4296              # Maximum characters
  supported_formats: ["png", "svg", "ascii"]

output:
  default_directory: "./output/"      # Default save location
  max_batch_size: 100                # Maximum batch generation
  enable_zip_export: true            # Enable ZIP for batches

decoding:
  preprocessing_enabled: true         # Image preprocessing
  max_image_size: "10MB"             # Maximum image size
  supported_image_formats: ["png", "jpg", "jpeg", "gif", "bmp", "tiff"]

performance:
  cache_generated_codes: false        # Disable caching (security)
  max_concurrent_requests: 10         # Concurrent request limit
```

## Tools

### 1. generate_qr_code

Generate a single QR code.

**Parameters:**
- `data` (str, required): Content to encode
- `format` (str): Output format - "png", "svg", "ascii" (default: "png")
- `size` (int): Box size in pixels (default: 10)
- `border` (int): Border size in boxes (default: 4)
- `error_correction` (str): Error correction level - "L", "M", "Q", "H" (default: "M")
- `fill_color` (str): Foreground color (default: "black")
- `back_color` (str): Background color (default: "white")
- `save_path` (str|null): Save directory (default: "./output/")
- `return_base64` (bool): Return base64 encoded data (default: false)


### 2. generate_batch_qr_codes

Generate multiple QR codes at once.

**Parameters:**
- `data_list` (list[str], required): List of data to encode
- `format` (str): Output format (default: "png")
- `size` (int): Box size in pixels (default: 10)
- `naming_pattern` (str): File naming pattern with {index} placeholder (default: "qr_{index}")
- `output_directory` (str): Output directory (default: "./qr_codes/")
- `zip_output` (bool): Create ZIP archive (default: false)


### 3. decode_qr_code

Decode QR code(s) from an image.

**Parameters:**
- `image_data` (str, required): Base64 encoded image or file path
- `image_format` (str): Image format - "auto", "png", "jpg", etc. (default: "auto")
- `multiple_codes` (bool): Detect multiple QR codes (default: false)
- `return_positions` (bool): Return QR code positions (default: false)
- `preprocessing` (bool): Enable image preprocessing (default: true)


### 4. validate_qr_data

Validate and analyze data before generating QR code.

**Parameters:**
- `data` (str, required): Data to validate
- `target_version` (int|null): Target QR version 1-40 (default: null)
- `error_correction` (str): Error correction level (default: "M")
- `check_capacity` (bool): Check if data fits (default: true)
- `suggest_optimization` (bool): Suggest optimizations (default: true)

## Development

```bash
# Format code
make format

# Run tests
make test

# Lint code
make lint
```

## Examples

### Example 1: Generate Simple QR Code

```python
# Tool call
{
  "tool": "generate_qr_code",
  "data": "https://github.com"
}

```

### Example 2: Generate Custom Colored QR Code

```python
# Tool call
{
  "tool": "generate_qr_code",
  "data": "Custom QR Code",
  "size": 15,
  "border": 2,
  "fill_color": "darkblue",
  "back_color": "lightgray",
  "error_correction": "H"
}

```

### Example 3: Generate SVG QR Code

```python
# Tool call
{
  "tool": "generate_qr_code",
  "data": "SVG Format Example",
  "format": "svg",
  "save_path": "./svg_output/"
}

```

### Example 4: Generate Batch QR Codes

```python
# Tool call
{
  "tool": "generate_batch_qr_codes",
  "data_list": [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3"
  ],
  "naming_pattern": "url_qr_{index}",
  "output_directory": "./batch_qr/",
  "zip_output": true
}

```

### Example 5: Decode QR Code from File

```python
# Tool call
{
  "tool": "decode_qr_code",
  "image_data": "/path/to/qr_image.png",
  "preprocessing": true
}

```

### Example 6: Decode Multiple QR Codes

```python
# Tool call
{
  "tool": "decode_qr_code",
  "image_data": "/path/to/multi_qr.png",
  "multiple_codes": true,
  "return_positions": true
}
```

### Example 7: Decode from Base64

```python
# Tool call
{
  "tool": "decode_qr_code",
  "image_data": "iVBORw0KGgoAAAANSUhEUgAA...",  # Base64 encoded image
  "image_format": "png"
}

```

### Example 8: Validate Data Before Generation

```python
# Tool call
{
  "tool": "validate_qr_data",
  "data": "https://very-long-url.com/path/to/resource?param1=value1&param2=value2",
  "error_correction": "H",
  "suggest_optimization": true
}

```

### Example 9: Generate ASCII QR Code

```python
# Tool call
{
  "tool": "generate_qr_code",
  "data": "ASCII QR",
  "format": "ascii",
  "return_base64": false
}

```

### Example 10: Batch with Custom Pattern

```python
# Tool call
{
  "tool": "generate_batch_qr_codes",
  "data_list": ["Product A", "Product B", "Product C"],
  "naming_pattern": "product_tag_{index}",
  "size": 20,
  "output_directory": "./product_qrs/"
}

```

## MCP Client Setup

### Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "qr-code-server": {
      "command": "uvx",
      "args": ["--from", "/path/to/qr-code-server", "qr-code-server"]
    }
  }
}
```

Or using Python directly:

```json
{
  "mcpServers": {
    "qr-code-server": {
      "command": "python",
      "args": ["-m", "qr_code_server.server"],
      "cwd": "/path/to/qr-code-server"
    }
  }
}
```

### Other MCP Clients

Use the stdio transport:

```javascript
const client = new MCPClient({
  command: "qr-code-server",
  args: [],
  transport: "stdio"
});
```

## Troubleshooting

### Server Won't Start

**Issue:** `ModuleNotFoundError`
```bash
# Solution: Install the package
uv pip install -e .
```

**Issue:** `Port already in use` (HTTP mode)
```bash
# Solution: Use different port
qr-code-server --transport http --port 9002
```

## Error Correction Levels

| Level | Error Recovery | Data Capacity | Use Case |
|-------|---------------|---------------|----------|
| L | 7% | Highest | Clean environments |
| M | 15% | High | General use (default) |
| Q | 25% | Medium | Potential damage |
| H | 30% | Lowest | High damage risk |

## QR Code Versions

- Version 1: 21x21 modules, ~25 characters
- Version 10: 57x57 modules, ~271 characters
- Version 20: 97x97 modules, ~858 characters
- Version 40: 177x177 modules, ~4,296 characters

Use `validate_qr_data` to find optimal version for your data.

## License

Apache-2.0

