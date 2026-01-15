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
```

## Configuration

Configuration file: `config.yaml`

```yaml
qr_generation:
  default_size: 10                    # QR code box size (pixels)
  default_border: 4                   # Border size (boxes)
  default_error_correction: "M"       # L=7%, M=15%, Q=25%, H=30%
  max_data_length: 4296               # Maximum characters
  supported_formats: ["png", "svg", "ascii"]

output:
  default_directory: "./output/"      # Default save location
  max_batch_size: 100                 # Maximum batch generation
  enable_zip_export: true             # Enable ZIP for batches

decoding:
  preprocessing_enabled: true         # Image preprocessing
  max_image_size: "10MB"              # Maximum image size
  supported_image_formats: ["png", "jpg", "jpeg", "gif", "bmp", "tiff"]

performance:
  max_concurrent_requests: 10         # Concurrent request limit
```

## Tools

All tools return normalized Pydantic models.
Failures are always reported via `success=false` or `error`.

### 1. generate_qr_code

Generate a single QR code.

**Parameters:**

- `data` (str, required)
- `format` ("png" | "svg" | "ascii", default "png")
- `size` (int, default from config)
- `border` (int, default from config)
- `error_correction` ("L" | "M" | "Q" | "H", default "M")
- `fill_color` (str, default "black")
- `back_color` (str, default "white")
- `save_path` (str | null)
- `return_base64` (bool, default false)

**Notes:**

- `border` is capped at 100 to avoid memory overloading
- `fill_color` and  `back_color` look at [Colors](#supported-colors)


#### Returns — QRCodeResult

```json
{
  "success": true,
  "output_format": "png",
  "file_path": "./output/qr.png",
  "image_base64": null,
  "message": "QR code image saved at ./output/qr.png",
  "error": null
}
```

**Notes:**

- `file_path` is set when saved to disk
- `image_base64` is set only if `return_base64=true`
- On failure, `success=false` and `error` is populated

### 2. generate_batch_qr_codes

Generate multiple QR codes at once.

**Parameters:**

- `data_list` (list[str], required, must not be empty)
- `format` ("png" | "svg" | "ascii", default "png")
- `size` (int, default from config)
- `border` (int, default from config)
- `error_correction` ("L" | "M" | "Q" | "H", default from config)
- `naming_pattern` (str, default "qr_{index}")
- `output_directory` (str, default from config)
- `zip_output` (bool, default from config)

#### Validation

- Batch size ≤ `output.max_batch_size`
- Each item length ≤ `qr_generation.max_data_length`

#### Returns — BatchQRCodeResult

```json
{
  "success": true,
  "zip_file_path": "./output/qr.zip",
  "output_directory": "./output/",
  "message": "QR code images saved in zip archive at ./output/qr.zip",
  "error": null
}
```

### 3. decode_qr_code

Decode QR code(s) from an image.

**Parameters:**

- `image_data` (base64 string or file path, required)
- `image_format` ("auto", "png", "jpg", "jpeg", "gif", "bmp", "tiff")
- `multiple_codes` (bool, default false)
- `return_positions` (bool, default false)
- `preprocessing` (bool, default true)

#### Returns — QRCodeDecodeResult

```json
{
  "success": true,
  "data": "https://example.com",
  "positions": null,
  "error": null
}
```

**Notes:**

- `data` is a string for single QR, `list[str]` when `multiple_codes=true`
- `positions` is returned only if `return_positions=true`
- `image_format` validates the declared format against supported formats; actual format is auto-detected from image data

### 4. validate_qr_data

Validate and analyze data before generating QR code.

**Parameters:**

- `data` (str, required)
- `target_version` (int | null, 1–40)
- `error_correction` ("L" | "M" | "Q" | "H", default "M")
- `check_capacity` (bool, default true)
- `suggest_optimization` (bool, default true)

#### Returns — QRValidationResult

```json
{
  "valid": true,
  "fits": true,
  "suggested_version": 7,
  "error": null
}
```

**Notes:**

- `valid` → data is syntactically acceptable
- `fits` → data fits QR capacity constraints
- `suggested_version` is provided when optimization is enabled

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

```json
{
  "tool": "generate_qr_code",
  "data": "https://github.com"
}
```

### Example 2: Generate Custom Colored QR Code

```json
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

```json
{
  "tool": "generate_qr_code",
  "data": "SVG Format Example",
  "format": "svg",
  "save_path": "./svg_output/"
}
```

### Example 4: Generate Batch QR Codes

```json
{
  "tool": "generate_batch_qr_codes",
  "data_list": [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3"
  ],
  "naming_pattern": "url_qr_{index}"
}
```

### Example 5: Decode QR Code from File

```json
{
  "tool": "decode_qr_code",
  "image_data": "/path/to/qr_image.png",
  "preprocessing": true
}
```

### Example 6: Decode Multiple QR Codes

```json
{
  "tool": "decode_qr_code",
  "image_data": "/path/to/multi_qr.png",
  "multiple_codes": true,
  "return_positions": true
}
```

### Example 7: Decode from Base64

```json
{
  "tool": "decode_qr_code",
  "image_data": "iVBORw0KGgoAAAANSUhEUgAA...",
  "image_format": "png"
}
```

### Example 8: Validate Data Before Generation

```json
{
  "tool": "validate_qr_data",
  "data": "https://very-long-url.com/path/to/resource?param1=value1&param2=value2",
  "error_correction": "H",
  "suggest_optimization": true
}
```

### Example 9: Generate ASCII QR Code

```json
{
  "tool": "generate_qr_code",
  "data": "ASCII QR",
  "format": "ascii"
}
```

## Supported Colors

The `fill_color` (QR modules) and `back_color` (background) parameters accept any color value supported by the Pillow imaging library.

### Accepted Formats

#### 1. Named Colors

Standard Pillow / CSS-style color names are supported.

**Examples:**

- "black" (default)
- "white" (default background)
- "red"
- "blue"
- "green"
- "darkblue"
- "lightgray"
- "purple"
- "orange"

If the name is not recognized by Pillow, the request will fail with a validation error.

#### 2. Hex Color Codes (Recommended)

All standard hex formats are supported.

**Examples:**

- "#000000"
- "#FFFFFF"
- "#FF5733"
- "#1E90FF"

Hex colors are strongly recommended for reliability and consistency.

#### 3. RGB / RGBA Tuples

Colors may be provided as numeric tuples.

**Examples:**

- `(0, 0, 0)`
- `(255, 255, 255)`
- `(30, 144, 255)`
- `(0, 0, 0, 255)`

**Notes:**

- RGBA alpha values are ignored for raster formats (PNG)
- Alpha transparency is preserved in SVG output

### Contrast Requirements (Important)

While many color combinations are technically valid, QR codes require high contrast to remain scannable.

#### Recommended:

- Dark `fill_color` on a light `back_color`
- Black on white (default) for maximum compatibility
- High contrast ratios (WCAG AA or better)

#### Not Recommended (May Be Unscannable):

- Light-on-light combinations (e.g., "lightgray" on "white")
- Low contrast color pairs
- Transparent backgrounds for printed QR codes

### Unsupported Color Formats

The following are not supported and will fail validation:

- Gradients
- Pattern fills
- CSS color strings like "rgb(0,0,0)" or "hsl(0,100%,50%)"
- CSS variables
- HSV / HSL formats

### Example

```json
{
  "tool": "generate_qr_code",
  "data": "https://example.com",
  "fill_color": "#1E90FF",
  "back_color": "white"
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

| Level | Error Recovery | Data Capacity | Use Case              |
|-------|----------------|---------------|-----------------------|
| L     | 7%             | Highest       | Clean environments    |
| M     | 15%            | High          | General use (default) |
| Q     | 25%            | Medium        | Potential damage      |
| H     | 30%            | Lowest        | High damage risk      |

## QR Code Versions

- **Version 1:** 21×21 modules, ~25 characters
- **Version 10:** 57×57 modules, ~271 characters
- **Version 20:** 97×97 modules, ~858 characters
- **Version 40:** 177×177 modules, ~4,296 characters

Use `validate_qr_data` to find optimal version for your data.

## License

Apache-2.0
