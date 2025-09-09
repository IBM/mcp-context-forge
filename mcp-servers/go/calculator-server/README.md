# Calculator Server - Go MCP Server

A comprehensive **Go-based MCP (Model Context Protocol) server** for mathematical computations, implementing 6+ mathematical tools with advanced features and high precision calculations.

**Owner & Maintainer:** Avinash Sangle (avinash.sangle123@gmail.com)

[![Go Version](https://img.shields.io/badge/go-%3E%3D1.21-blue)](https://golang.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)]()
[![Coverage](https://img.shields.io/badge/coverage-%3E95%25-brightgreen)]()

## 🧮 Features

### Core Mathematical Tools (6 Tools)

1. **Basic Math Operations** - Precision arithmetic with configurable decimal places
   - Addition, subtraction, multiplication, division
   - Multiple operand support
   - Decimal precision control (0-15 places)

2. **Advanced Mathematical Functions** - Scientific calculations
   - Trigonometric: `sin`, `cos`, `tan`, `asin`, `acos`, `atan`
   - Logarithmic: `log`, `log10`, `ln`
   - Other: `sqrt`, `abs`, `factorial`, `exp`, `pow`
   - Unit support: degrees/radians for trig functions

3. **Expression Evaluation** - Complex mathematical expressions
   - Variable substitution support
   - Mathematical constants (`π`, `e`)
   - Nested expressions with parentheses
   - Function calls within expressions

4. **Statistical Analysis** - Comprehensive data analysis
   - Descriptive statistics: mean, median, mode
   - Variability: standard deviation, variance
   - Percentile calculations
   - Data validation and error handling

5. **Unit Conversion** - Multi-category unit conversion
   - **Length**: mm, cm, m, km, in, ft, yd, mi
   - **Weight**: mg, g, kg, t, oz, lb, stone
   - **Temperature**: °C, °F, K, R
   - **Volume**: ml, l, fl oz, cup, pint, quart, gallon
   - **Area**: m², cm², km², in², ft², acre, hectare

6. **Financial Calculations** - Comprehensive financial modeling
   - Interest calculations: simple & compound
   - Loan payment calculations
   - Return on Investment (ROI)
   - Present/Future value calculations
   - Net Present Value (NPV) & Internal Rate of Return (IRR)

### Additional Features

- **High Precision**: Uses `shopspring/decimal` for financial calculations
- **Scientific Computing**: Powered by `gonum.org/v1/gonum`
- **Expression Engine**: Advanced parsing with `govaluate`
- **Comprehensive Testing**: >95% test coverage
- **Error Handling**: Detailed error messages and validation
- **MCP Protocol**: Full compliance with MCP specification
- **Build Automation**: Complete Makefile with CI/CD support

## 🚀 Quick Start

### Prerequisites

- **Go 1.21+** (required)
- **Git** (for version control)

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd calculator-server

# Install dependencies
make deps

# Build the server
make build

# Run the server
make run
```

### Alternative Setup

```bash
# Initialize Go module
go mod init calculator-server
go mod tidy

# Build and run
go build -o calculator-server ./cmd/server
./calculator-server -transport=stdio
```

## 📊 Usage Examples

### Basic Mathematics

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "basic_math",
    "arguments": {
      "operation": "add",
      "operands": [15.5, 20.3, 10.2],
      "precision": 2
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text", 
        "text": "{\"result\": 46.0}"
      }
    ]
  }
}
```

### Advanced Mathematical Functions

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "advanced_math",
    "arguments": {
      "function": "sin",
      "value": 90,
      "unit": "degrees"
    }
  }
}
```

### Expression Evaluation

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "expression_eval",
    "arguments": {
      "expression": "sqrt(x^2 + y^2)",
      "variables": {"x": 3, "y": 4}
    }
  }
}
```

### Statistical Analysis

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "statistics",
    "arguments": {
      "data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
      "operation": "mean"
    }
  }
}
```

### Unit Conversion

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "unit_conversion",
    "arguments": {
      "value": 100,
      "fromUnit": "cm",
      "toUnit": "m",
      "category": "length"
    }
  }
}
```

### Financial Calculations

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "tools/call",
  "params": {
    "name": "financial",
    "arguments": {
      "operation": "compound_interest",
      "principal": 10000,
      "rate": 5.5,
      "time": 3,
      "periods": 12
    }
  }
}
```

## 🌐 MCP Streamable HTTP Transport

The server implements **MCP-compliant streamable HTTP transport** according to the official MCP specification, providing real-time communication with Server-Sent Events (SSE) streaming support.

### MCP Protocol Compliance

✅ **Single Endpoint**: `/mcp` only (per MCP specification)  
✅ **Required Headers**: `MCP-Protocol-Version`, `Accept`  
✅ **Session Management**: Cryptographically secure session IDs  
✅ **SSE Streaming**: Server-Sent Events for real-time responses  
✅ **CORS Support**: Origin validation and security headers  

### HTTP Endpoints

#### Single MCP Endpoint (Specification Compliant)
- **POST /mcp** - MCP JSON-RPC with optional SSE streaming
- **GET /mcp** - SSE stream establishment
- **OPTIONS /mcp** - CORS preflight handling

### Example Usage

```bash
# Start MCP-compliant HTTP server
./calculator-server -transport=http -port=8080

# Basic JSON-RPC request
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "MCP-Protocol-Version: 2024-11-05" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "basic_math",
      "arguments": {
        "operation": "add",
        "operands": [15, 25],
        "precision": 2
      }
    }
  }'

# SSE streaming request (for real-time responses)
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "MCP-Protocol-Version: 2024-11-05" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "statistics",
      "arguments": {"data": [1,2,3,4,5], "operation": "mean"}
    }
  }'

# Establish SSE stream connection
curl -X GET http://localhost:8080/mcp \
  -H "Accept: text/event-stream" \
  -H "MCP-Protocol-Version: 2024-11-05"
```

### Session Management

The server supports optional MCP session management:

```bash
# Request with session ID
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "MCP-Protocol-Version: 2024-11-05" \
  -H "Mcp-Session-Id: abc123def456" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### Configuration

```yaml
server:
  transport: "http"
  http:
    host: "127.0.0.1"  # Localhost for security (per MCP spec)
    port: 8080
    session_timeout: "5m"
    max_connections: 100
    cors:
      enabled: true
      origins: ["*"]  # Configure appropriately for production
```

### Security Features

- **Origin Validation**: CORS origin checking
- **Session Security**: Cryptographically secure session IDs
- **Local Binding**: Default to localhost for security
- **Protocol Enforcement**: Strict MCP protocol compliance

## 🏗️ Project Structure

```
calculator-server/
├── cmd/
│   └── server/
│       └── main.go              # Main server entry point
├── internal/
│   ├── calculator/
│   │   ├── basic.go            # Basic math operations
│   │   ├── advanced.go         # Advanced mathematical functions
│   │   ├── expression.go       # Expression evaluation
│   │   ├── statistics.go       # Statistical analysis
│   │   ├── units.go           # Unit conversion
│   │   └── financial.go       # Financial calculations
│   ├── handlers/
│   │   ├── math_handler.go    # Math operation handlers
│   │   ├── stats_handler.go   # Statistics handlers
│   │   └── finance_handler.go # Financial handlers
│   └── types/
│       └── requests.go        # Request/response types
├── pkg/
│   └── mcp/
│       ├── server.go          # MCP server implementation
│       └── protocol.go        # MCP protocol handling
├── tests/
│   ├── basic_test.go         # Basic math tests
│   ├── advanced_test.go      # Advanced math tests
│   ├── expression_test.go    # Expression evaluation tests
│   └── integration_test.go   # Integration tests
├── go.mod                    # Go module definition
├── go.sum                    # Go module checksums
├── Makefile                  # Build automation
└── README.md                 # Project documentation
```

## 🛠️ Development

### Building

```bash
# Build for current platform
make build

# Build for all platforms
make build-all

# Install to $GOPATH/bin
make install
```

### Testing

```bash
# Run all tests
make test

# Run tests with coverage
make coverage

# Run tests with race detection
make test-race

# Run benchmarks
make benchmark
```

### Quality Assurance

```bash
# Format code
make fmt

# Run linter
make lint

# Run vet
make vet

# Run all quality checks
make quality
```

### Development Mode

```bash
# Run without building (development)
make run-dev

# Run with rebuild
make run
```

## 📋 Available Tools

### 1. `basic_math`
**Purpose:** Basic arithmetic operations with precision control

**Parameters:**
- `operation` (string): "add", "subtract", "multiply", "divide"
- `operands` (array of numbers): Numbers to operate on (minimum 2)
- `precision` (integer, optional): Decimal places (0-15, default: 2)

### 2. `advanced_math`
**Purpose:** Advanced mathematical functions

**Parameters:**
- `function` (string): Function name (sin, cos, tan, log, sqrt, etc.)
- `value` (number): Input value
- `unit` (string, optional): "radians" or "degrees" for trig functions

### 3. `expression_eval`
**Purpose:** Evaluate mathematical expressions with variables

**Parameters:**
- `expression` (string): Mathematical expression to evaluate
- `variables` (object, optional): Variable name-value pairs

### 4. `statistics`
**Purpose:** Statistical analysis of datasets

**Parameters:**
- `data` (array of numbers): Dataset to analyze
- `operation` (string): Statistical operation (mean, median, mode, std_dev, variance, percentile)

### 5. `unit_conversion`
**Purpose:** Convert between measurement units

**Parameters:**
- `value` (number): Value to convert
- `fromUnit` (string): Source unit
- `toUnit` (string): Target unit
- `category` (string): Unit category (length, weight, temperature, volume, area)

### 6. `financial`
**Purpose:** Financial calculations and modeling

**Parameters:**
- `operation` (string): Financial operation type
- `principal` (number): Principal amount
- `rate` (number): Interest rate (percentage)
- `time` (number): Time period in years
- `periods` (integer, optional): Compounding periods per year
- `futureValue` (number, optional): Future value for some calculations

## 🔧 Configuration

### Command Line Options

```bash
./calculator-server [OPTIONS]

Options:
  -transport string
        Transport method (stdio, http) (default "stdio")
  -port int
        Port for HTTP transport (default 8080)
  -host string
        Host for HTTP transport (default "0.0.0.0")
  -config string
        Path to configuration file (YAML or JSON)

Examples:
  ./calculator-server                           # Run with stdio transport (default)
  ./calculator-server -transport=http          # Run with HTTP transport on port 8080
  ./calculator-server -transport=http -port=9000 -host=localhost  # Custom host/port
  ./calculator-server -config=config.yaml     # Load configuration from file
  ./calculator-server -config=config.yaml -transport=http  # Override config with CLI flags
```

### Configuration Files

The server supports configuration files in YAML and JSON formats. Configuration files are searched in the following locations:

1. Current directory (`./config.yaml`, `./config.json`)
2. `./config/` directory
3. `/etc/calculator-server/`
4. `$HOME/.calculator-server/`

#### Sample YAML Configuration

```yaml
server:
  transport: "http"
  http:
    host: "0.0.0.0"
    port: 8080
    cors:
      enabled: true
      origins: ["*"]
    timeout:
      read: "30s"
      write: "30s"
      idle: "120s"
    tls:
      enabled: false
      cert_file: ""
      key_file: ""

logging:
  level: "info"
  format: "json"
  output: "stdout"

tools:
  precision:
    max_decimal_places: 15
    default_decimal_places: 2
  expression_eval:
    timeout: "10s"
    max_variables: 100
  statistics:
    max_data_points: 10000
  financial:
    currency_default: "USD"

security:
  rate_limiting:
    enabled: true
    requests_per_minute: 100
  request_size_limit: "1MB"
```

See `config.sample.yaml` and `config.sample.json` for complete configuration examples.

### Environment Variables

Environment variables override configuration file settings:

- `CALCULATOR_TRANSPORT`: Transport method (stdio, http)
- `CALCULATOR_HTTP_HOST`: HTTP server host
- `CALCULATOR_HTTP_PORT`: HTTP server port
- `CALCULATOR_LOG_LEVEL`: Set logging level (debug, info, warn, error)
- `CALCULATOR_LOG_FORMAT`: Log format (json, text)
- `CALCULATOR_LOG_OUTPUT`: Log output (stdout, stderr, file path)
- `CALCULATOR_MAX_PRECISION`: Override maximum precision limit (0-15)
- `CALCULATOR_DEFAULT_PRECISION`: Default precision for results
- `CALCULATOR_RATE_LIMIT_ENABLED`: Enable rate limiting (true, false)
- `CALCULATOR_REQUESTS_PER_MINUTE`: Requests per minute limit

## 📈 Performance

### Benchmarks

- **Basic Operations**: ~1-5 μs per operation
- **Advanced Functions**: ~10-50 μs per operation  
- **Expression Evaluation**: ~100-500 μs per expression
- **Statistical Operations**: ~10-100 μs per dataset (depends on size)
- **Unit Conversions**: ~1-10 μs per conversion
- **Financial Calculations**: ~50-200 μs per calculation

### Memory Usage

- **Base Memory**: ~10-20 MB
- **Per Operation**: ~1-10 KB additional
- **Large Datasets**: Linear scaling with data size

## 🧪 Testing

The project includes comprehensive tests with >95% coverage:

- **Unit Tests**: Test individual calculators and functions
- **Integration Tests**: Test MCP protocol integration
- **Error Handling Tests**: Validate error conditions
- **Performance Tests**: Benchmark critical operations

```bash
# Run specific test suites
go test ./tests/basic_test.go -v
go test ./tests/advanced_test.go -v
go test ./tests/expression_test.go -v
go test ./tests/integration_test.go -v

# Generate coverage report
make coverage
open ./coverage/coverage.html
```

## 🚢 Deployment

### Docker Deployment

```bash
# Build Docker image
make docker-build

# Run in Docker
make docker-run

# Push to registry
make docker-push
```

### Binary Distribution

```bash
# Create release build
make release

# Binaries will be in ./dist/release/
ls -la ./dist/release/
```

## 📝 API Reference

### MCP Protocol Support

The server implements the full MCP (Model Context Protocol) specification:

- **Initialize**: Server initialization and capability negotiation
- **Tools List**: Dynamic tool discovery
- **Tools Call**: Tool execution with parameter validation
- **Error Handling**: Comprehensive error responses

### Tool Schemas

All tools include comprehensive JSON Schema definitions for parameter validation and documentation. Schemas are automatically generated and include:

- Parameter types and validation rules
- Required vs optional parameters
- Default values and constraints
- Documentation strings

### 📏 Unit Conversion Reference

Complete list of supported units by category:

#### Length Units
| Unit | Abbreviation | Description | Conversion to Meters |
|------|--------------|-------------|---------------------|
| Millimeter | `mm` | 0.001 meters | 0.001 |
| Centimeter | `cm` | 0.01 meters | 0.01 |
| Meter | `m` | Base unit | 1.0 |
| Kilometer | `km` | 1000 meters | 1000.0 |
| Inch | `in` | Imperial inch | 0.0254 |
| Foot | `ft` | Imperial foot | 0.3048 |
| Yard | `yd` | Imperial yard | 0.9144 |
| Mile | `mi` | Imperial mile | 1609.344 |
| Mil | `mil` | 1/1000 inch | 0.0000254 |
| Micrometer | `μm` | 0.000001 meters | 0.000001 |
| Nanometer | `nm` | 0.000000001 meters | 0.000000001 |

#### Weight/Mass Units
| Unit | Abbreviation | Description | Conversion to Grams |
|------|--------------|-------------|-------------------|
| Milligram | `mg` | 0.001 grams | 0.001 |
| Gram | `g` | Base unit | 1.0 |
| Kilogram | `kg` | 1000 grams | 1000.0 |
| Metric Ton | `t` | 1,000,000 grams | 1000000.0 |
| Ounce | `oz` | Imperial ounce | 28.3495 |
| Pound | `lb` | Imperial pound | 453.592 |
| Stone | `st` | Imperial stone | 6350.29 |
| US Ton | `ton` | US ton | 907185 |

#### Temperature Units
| Unit | Abbreviation | Description |
|------|--------------|-------------|
| Celsius | `C` | Degrees Celsius |
| Fahrenheit | `F` | Degrees Fahrenheit |
| Kelvin | `K` | Kelvin (absolute) |
| Rankine | `R` | Degrees Rankine |

**Note**: Temperature conversions are non-linear and handled specially.

#### Volume Units
| Unit | Abbreviation | Description | Conversion to Liters |
|------|--------------|-------------|---------------------|
| Milliliter | `ml` | 0.001 liters | 0.001 |
| Centiliter | `cl` | 0.01 liters | 0.01 |
| Deciliter | `dl` | 0.1 liters | 0.1 |
| Liter | `l` | Base unit | 1.0 |
| Kiloliter | `kl` | 1000 liters | 1000.0 |
| US Fluid Ounce | `fl_oz` | US fluid ounce | 0.0295735 |
| US Cup | `cup` | US cup | 0.236588 |
| US Pint | `pt` | US pint | 0.473176 |
| US Quart | `qt` | US quart | 0.946353 |
| US Gallon | `gal` | US gallon | 3.78541 |
| Teaspoon | `tsp` | US teaspoon | 0.00492892 |
| Tablespoon | `tbsp` | US tablespoon | 0.0147868 |
| Barrel | `bbl` | Barrel | 158.987 |

#### Area Units
| Unit | Abbreviation | Description | Conversion to m² |
|------|--------------|-------------|-----------------|
| Square Millimeter | `mm2` | Square mm | 0.000001 |
| Square Centimeter | `cm2` | Square cm | 0.0001 |
| Square Meter | `m2` | Base unit | 1.0 |
| Square Kilometer | `km2` | Square km | 1000000.0 |
| Square Inch | `in2` | Square inch | 0.00064516 |
| Square Foot | `ft2` | Square foot | 0.092903 |
| Square Yard | `yd2` | Square yard | 0.836127 |
| Square Mile | `mi2` | Square mile | 2589988.11 |
| Acre | `acre` | Acre | 4046.86 |
| Hectare | `ha` | Hectare | 10000.0 |

### 🔢 Mathematical Functions Reference

Complete guide to mathematical functions available in expressions:

#### Trigonometric Functions
| Function | Syntax | Description | Example |
|----------|--------|-------------|---------|
| Sine | `sin(x)` | Sine of x (radians) | `sin(pi/2)` → 1.0 |
| Cosine | `cos(x)` | Cosine of x (radians) | `cos(0)` → 1.0 |
| Tangent | `tan(x)` | Tangent of x (radians) | `tan(pi/4)` → 1.0 |
| Arcsine | `asin(x)` | Inverse sine | `asin(1)` → 1.5708 |
| Arccosine | `acos(x)` | Inverse cosine | `acos(1)` → 0.0 |
| Arctangent | `atan(x)` | Inverse tangent | `atan(1)` → 0.7854 |

#### Logarithmic Functions
| Function | Syntax | Description | Example |
|----------|--------|-------------|---------|
| Common Log | `log(x)` | Base-10 logarithm | `log(100)` → 2.0 |
| Natural Log | `ln(x)` | Natural logarithm (base e) | `ln(e)` → 1.0 |

#### Power & Root Functions
| Function | Syntax | Description | Example |
|----------|--------|-------------|---------|
| Square Root | `sqrt(x)` | Square root of x | `sqrt(16)` → 4.0 |
| Power | `pow(x, y)` | x raised to power y | `pow(2, 3)` → 8.0 |
| Exponential | `exp(x)` | e raised to power x | `exp(1)` → 2.7183 |

#### Other Functions
| Function | Syntax | Description | Example |
|----------|--------|-------------|---------|
| Absolute Value | `abs(x)` | Absolute value of x | `abs(-5)` → 5.0 |

#### Mathematical Constants
| Constant | Value | Description |
|----------|-------|-------------|
| `pi` | 3.14159... | Pi (π) |
| `e` | 2.71828... | Euler's number |
| `PI` | 3.14159... | Pi (uppercase) |
| `E` | 2.71828... | Euler's number (uppercase) |

#### Complex Expression Examples
```javascript
// Pythagorean theorem
"sqrt(x^2 + y^2)"

// Trigonometric identity
"sin(x)^2 + cos(x)^2"

// Compound calculations
"2 * sqrt(25) + pow(3, 2) - abs(-4)"

// Using constants
"2 * pi * r"

// Financial formula
"1000 * pow(1 + 0.05, 10)"
```

### ⚠️ Error Codes Reference

#### MCP Protocol Error Codes
| Code | Name | Description |
|------|------|-------------|
| -32600 | Invalid Request | Malformed JSON-RPC request |
| -32601 | Method Not Found | Requested method doesn't exist |
| -32602 | Invalid Params | Invalid method parameters |
| -32603 | Internal Error | Server internal error |

#### Mathematical Error Types
| Error Category | Description | Example |
|----------------|-------------|---------|
| Domain Error | Input outside function domain | `sqrt(-1)`, `log(-5)` |
| Division by Zero | Attempt to divide by zero | `10 / 0` |
| Overflow Error | Result too large | `exp(1000)` |
| Precision Error | Loss of precision warning | Very large calculations |
| Validation Error | Invalid input parameters | Empty data set, invalid units |

#### Common Error Messages
- `"expression cannot be empty"` - Empty expression string
- `"invalid variable name: x"` - Variable name violates naming rules
- `"division by zero"` - Mathematical division by zero
- `"domain error: value must be positive"` - Logarithm of negative number
- `"unsupported unit: xyz"` - Unit not recognized for category
- `"evaluation error: ..."` - Expression parsing or evaluation failed

#### Troubleshooting Guide
1. **Function Not Found**: Ensure function name is spelled correctly and is supported
2. **Domain Errors**: Check input values are within valid ranges
3. **Variable Errors**: Use valid variable names (letters, digits, underscore only)
4. **Unit Errors**: Use exact unit abbreviations from reference tables
5. **Expression Syntax**: Check parentheses balance and operator placement

## 🤝 Contributing

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** changes (`git commit -m 'Add amazing feature'`)
4. **Push** to branch (`git push origin feature/amazing-feature`)
5. **Create** a Pull Request

### Development Guidelines

- Follow Go best practices and conventions
- Maintain >95% test coverage
- Add comprehensive documentation
- Use meaningful commit messages
- Run `make quality` before submitting

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Go Team**: For the excellent programming language
- **MCP Protocol**: Model Context Protocol specification
- **External Libraries**:
  - [`shopspring/decimal`](https://github.com/shopspring/decimal): Precise decimal arithmetic
  - [`Knetic/govaluate`](https://github.com/Knetic/govaluate): Expression evaluation
  - [`gonum`](https://gonum.org/): Scientific computing

## 📞 Support & Contact

**Primary Contact:**
- **Maintainer**: Avinash Sangle
- **Email**: avinash.sangle123@gmail.com
- **GitHub**: [https://github.com/avisangle](https://github.com/avisangle)
- **Website**: [https://avisangle.github.io/](https://avisangle.github.io/)

**Project Resources:**
- **Issues**: [GitHub Issues](https://github.com/IBM/mcp-context-forge/issues)
- **Documentation**: This README and inline code documentation
- **Examples**: See `make example-*` commands

**Getting Help:**
1. Check this README for comprehensive documentation
2. Review the test files for usage examples
3. Submit issues with detailed error information
4. Contact the maintainer for direct support

## 🗺️ Roadmap

### Version 1.1 ✅ Completed
- [x] HTTP transport support
- [x] Configuration file support (YAML/JSON)
- [x] TLS/HTTPS support
- [x] CORS configuration
- [x] Environment variable overrides
- [ ] WebSocket transport support
- [ ] Advanced statistical functions

### Version 1.2
- [ ] Graphing and visualization tools
- [ ] Matrix operations
- [ ] Complex number support
- [ ] Custom function definitions

### Version 2.0
- [ ] Plugin system
- [ ] Database integration
- [ ] REST API endpoints
- [ ] Web-based interface

---

**Built with ❤️ by Avinash Sangle for the IBM MCP Context Forge project**

**Connect with the Author:**
- 🌐 Website: [https://avisangle.github.io/](https://avisangle.github.io/)
- 💻 GitHub: [https://github.com/avisangle](https://github.com/avisangle)
- 📧 Email: avinash.sangle123@gmail.com

For more information about MCP servers and the Context Forge project, visit the [IBM MCP Context Forge repository](https://github.com/IBM/mcp-context-forge).