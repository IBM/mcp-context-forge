# Calculator Server - Go MCP Server

A comprehensive **Go-based MCP (Model Context Protocol) server** for mathematical computations, implementing **13 mathematical tools** with advanced features and high precision calculations.

**Owner & Maintainer:** Avinash Sangle

[![Go Version](https://img.shields.io/badge/go-%3E%3D1.21-blue)](https://golang.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)]()
[![Coverage](https://img.shields.io/badge/coverage-%3E95%25-brightgreen)]()

## 🧮 Features

### Core Mathematical Tools (13 Tools)

#### Basic Mathematical Tools (6 Tools)

1. **Basic Math Operations** - Precision arithmetic with configurable decimal places
   - Addition, subtraction, multiplication, division
   - Multiple operand support
   - Decimal precision control (0-15 places)

2. **Advanced Mathematical Functions** - Scientific calculations
   - Trigonometric: `sin`, `cos`, `tan`, `asin`, `acos`, `atan`
   - Logarithmic: `log`, `log10`, `ln`
   - Other: `sqrt`, `abs`, `factorial`, `exp`, `pow`
   - Unit support: degrees/radians for trig functions
   - Power function with base and exponent parameters

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
   - **Length**: mm, cm, m, km, in, ft, yd, mi, mil, μm, nm
   - **Weight**: mg, g, kg, t, oz, lb, st (stone), ton (US ton)
   - **Temperature**: °C, °F, K, R (Rankine)
   - **Volume**: ml, cl, dl, l, kl, fl_oz, cup, pt, qt, gal, tsp, tbsp, bbl
   - **Area**: mm², cm², m², km², in², ft², yd², mi², acre, ha

6. **Financial Calculations** - Comprehensive financial modeling
   - Interest calculations: simple & compound
   - Loan payment calculations
   - Return on Investment (ROI)
   - Present/Future value calculations
   - Net Present Value (NPV) & Internal Rate of Return (IRR)

#### Advanced Specialized Tools (7 Tools)

7. **Statistics Summary** - Comprehensive statistical summary of datasets
   - Complete statistical overview including all measures
   - Data preview with first/last elements
   - Common percentiles (25th, 50th, 75th)

8. **Percentile Calculation** - Calculate specific percentiles (0-100)
   - Any percentile value between 0 and 100
   - Data count and preview information
   - Accurate percentile calculations using empirical method

9. **Batch Unit Conversion** - Convert multiple values between units at once
   - Bulk conversion operations
   - Same unit categories as single conversion
   - Efficient batch processing

10. **Net Present Value (NPV)** - Advanced NPV calculations with cash flows
    - Multiple cash flow periods
    - Discount rate calculations
    - Investment decision support

11. **Internal Rate of Return (IRR)** - IRR calculations for investment analysis
    - Cash flow analysis
    - Newton-Raphson method for accurate IRR calculation
    - Investment performance evaluation

12. **Loan Comparison** - Compare multiple loan scenarios
    - Multiple loan option analysis
    - Payment calculations for each scenario
    - Comparison metrics and recommendations

13. **Investment Scenarios** - Compare multiple investment scenarios
    - Multiple investment option analysis
    - Future value calculations for each scenario
    - Investment comparison and recommendations

### Technical Features

- **High Precision**: Uses `shopspring/decimal` for financial calculations
- **Scientific Computing**: Powered by `gonum.org/v1/gonum`
- **Expression Engine**: Advanced parsing with `govaluate`
- **Comprehensive Testing**: >95% test coverage
- **Error Handling**: Detailed error messages and validation
- **MCP Protocol**: Full compliance with MCP specification
- **Build Automation**: Complete Makefile with CI/CD support
- **Streamable HTTP Transport**: MCP-compliant HTTP transport with SSE support

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
      "function": "pow",
      "value": 2,
      "exponent": 8
    }
  }
}
```

### Statistics Summary

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "stats_summary",
    "arguments": {
      "data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    }
  }
}
```

### Percentile Calculation

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "percentile",
    "arguments": {
      "data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
      "percentile": 90
    }
  }
}
```

### Net Present Value

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "npv",
    "arguments": {
      "cashFlows": [-50000, 15000, 20000, 25000, 30000],
      "discountRate": 8
    }
  }
}
```

### Batch Unit Conversion

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "tools/call",
  "params": {
    "name": "batch_conversion",
    "arguments": {
      "values": [100, 200, 300],
      "fromUnit": "cm",
      "toUnit": "m",
      "category": "length"
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
      "name": "stats_summary",
      "arguments": {"data": [1,2,3,4,5]}
    }
  }'
```

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
│   │   ├── stats_handler.go   # Statistics & specialized handlers
│   │   └── finance_handler.go # Financial handlers
│   ├── config/
│   │   ├── config.go          # Configuration structures
│   │   ├── loader.go          # Configuration loader
│   │   └── errors.go          # Configuration errors
│   └── types/
│       └── requests.go        # Request/response types
├── pkg/
│   └── mcp/
│       ├── protocol.go        # MCP protocol handling
│       └── streamable_http_transport.go # HTTP transport
├── tests/
│   ├── basic_test.go         # Basic math tests
│   ├── advanced_test.go      # Advanced math tests
│   ├── expression_test.go    # Expression evaluation tests
│   ├── integration_test.go   # Integration tests
│   ├── config_test.go        # Configuration tests
│   └── streamable_http_transport_test.go # HTTP transport tests
├── config.sample.yaml        # Sample YAML configuration
├── config.sample.json        # Sample JSON configuration
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

# Pre-commit checks
make pre-commit

# CI pipeline
make ci
```

### Development Mode

```bash
# Run without building (development)
make run-dev

# Run with rebuild
make run
```

## 📋 Available Tools

### Core Tools (6)

#### 1. `basic_math`
**Purpose:** Basic arithmetic operations with precision control

**Parameters:**
- `operation` (string): "add", "subtract", "multiply", "divide"
- `operands` (array of numbers): Numbers to operate on (minimum 2)
- `precision` (integer, optional): Decimal places (0-15, default: 2)

#### 2. `advanced_math`
**Purpose:** Advanced mathematical functions

**Parameters:**
- `function` (string): Function name (sin, cos, tan, asin, acos, atan, log, log10, ln, sqrt, abs, factorial, pow, exp)
- `value` (number): Input value (base for pow function)
- `exponent` (number, optional): Exponent for pow function (required for pow)
- `unit` (string, optional): "radians" or "degrees" for trig functions

#### 3. `expression_eval`
**Purpose:** Evaluate mathematical expressions with variables

**Parameters:**
- `expression` (string): Mathematical expression to evaluate
- `variables` (object, optional): Variable name-value pairs

#### 4. `statistics`
**Purpose:** Statistical analysis of datasets

**Parameters:**
- `data` (array of numbers): Dataset to analyze
- `operation` (string): Statistical operation (mean, median, mode, std_dev, variance, percentile)

#### 5. `unit_conversion`
**Purpose:** Convert between measurement units

**Parameters:**
- `value` (number): Value to convert
- `fromUnit` (string): Source unit
- `toUnit` (string): Target unit
- `category` (string): Unit category (length, weight, temperature, volume, area)

#### 6. `financial`
**Purpose:** Financial calculations and modeling

**Parameters:**
- `operation` (string): Financial operation type (compound_interest, simple_interest, loan_payment, roi, present_value, future_value)
- `principal` (number): Principal amount
- `rate` (number): Interest rate (percentage)
- `time` (number): Time period in years
- `periods` (integer, optional): Compounding periods per year
- `futureValue` (number, optional): Future value for some calculations

### Specialized Tools (7)

#### 7. `stats_summary`
**Purpose:** Comprehensive statistical summary of datasets

**Parameters:**
- `data` (array of numbers): Dataset for summary statistics

#### 8. `percentile`
**Purpose:** Calculate specific percentiles

**Parameters:**
- `data` (array of numbers): Dataset to analyze
- `percentile` (number): Percentile to calculate (0-100)

#### 9. `batch_conversion`
**Purpose:** Convert multiple values between units

**Parameters:**
- `values` (array of numbers): Values to convert
- `fromUnit` (string): Source unit
- `toUnit` (string): Target unit
- `category` (string): Unit category

#### 10. `npv`
**Purpose:** Calculate Net Present Value

**Parameters:**
- `cashFlows` (array of numbers): Cash flows (negative for outflows, positive for inflows)
- `discountRate` (number): Discount rate as percentage

#### 11. `irr`
**Purpose:** Calculate Internal Rate of Return

**Parameters:**
- `cashFlows` (array of numbers): Cash flows (minimum 2 values)

#### 12. `loan_comparison`
**Purpose:** Compare multiple loan scenarios

**Parameters:**
- `loans` (array of objects): Loan scenarios with principal, rate, and time

#### 13. `investment_scenarios`
**Purpose:** Compare multiple investment scenarios

**Parameters:**
- `scenarios` (array of objects): Investment scenarios with principal, rate, and time

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
        Host for HTTP transport (default "127.0.0.1")
  -config string
        Path to configuration file (YAML or JSON)

Examples:
  ./calculator-server                           # Run with stdio transport (default)
  ./calculator-server -transport=http          # Run with HTTP transport on port 8080
  ./calculator-server -transport=http -port=9000 -host=localhost  # Custom host/port
  ./calculator-server -config=config.yaml     # Load configuration from file
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
    host: "127.0.0.1"  # Localhost for security
    port: 8080
    session_timeout: "5m"
    max_connections: 100
    cors:
      enabled: true
      origins: ["http://localhost:3000", "http://127.0.0.1:3000"]  # Never use "*" in production

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

### Environment Variables

Environment variables override configuration file settings:

- `CALCULATOR_TRANSPORT`: Transport method (stdio, http)
- `CALCULATOR_HTTP_HOST`: HTTP server host
- `CALCULATOR_HTTP_PORT`: HTTP server port
- `CALCULATOR_LOG_LEVEL`: Set logging level (debug, info, warn, error)
- `CALCULATOR_LOG_FORMAT`: Log format (json, text)
- `CALCULATOR_LOG_OUTPUT`: Log output (stdout, stderr)

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
go test ./tests/integration_test.go -v

# Generate coverage report
make coverage
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

## 📏 Unit Conversion Reference

### Length Units
| Unit | Abbreviation | Conversion to Meters |
|------|--------------|---------------------|
| Millimeter | `mm` | 0.001 |
| Centimeter | `cm` | 0.01 |
| Meter | `m` | 1.0 |
| Kilometer | `km` | 1000.0 |
| Inch | `in` | 0.0254 |
| Foot | `ft` | 0.3048 |
| Yard | `yd` | 0.9144 |
| Mile | `mi` | 1609.344 |
| Mil | `mil` | 0.0000254 |
| Micrometer | `μm` | 0.000001 |
| Nanometer | `nm` | 0.000000001 |

### Weight/Mass Units
| Unit | Abbreviation | Conversion to Grams |
|------|--------------|-------------------|
| Milligram | `mg` | 0.001 |
| Gram | `g` | 1.0 |
| Kilogram | `kg` | 1000.0 |
| Metric Ton | `t` | 1000000.0 |
| Ounce | `oz` | 28.3495 |
| Pound | `lb` | 453.592 |
| Stone | `st` | 6350.29 |
| US Ton | `ton` | 907185 |

### Temperature Units
| Unit | Abbreviation | Description |
|------|--------------|-------------|
| Celsius | `C` | Degrees Celsius |
| Fahrenheit | `F` | Degrees Fahrenheit |
| Kelvin | `K` | Kelvin (absolute) |
| Rankine | `R` | Degrees Rankine |

### Volume Units
| Unit | Abbreviation | Conversion to Liters |
|------|--------------|---------------------|
| Milliliter | `ml` | 0.001 |
| Centiliter | `cl` | 0.01 |
| Deciliter | `dl` | 0.1 |
| Liter | `l` | 1.0 |
| Kiloliter | `kl` | 1000.0 |
| US Fluid Ounce | `fl_oz` | 0.0295735 |
| US Cup | `cup` | 0.236588 |
| US Pint | `pt` | 0.473176 |
| US Quart | `qt` | 0.946353 |
| US Gallon | `gal` | 3.78541 |
| Teaspoon | `tsp` | 0.00492892 |
| Tablespoon | `tbsp` | 0.0147868 |
| Barrel | `bbl` | 158.987 |

### Area Units
| Unit | Abbreviation | Conversion to m² |
|------|--------------|------------------|
| Square Millimeter | `mm2` | 0.000001 |
| Square Centimeter | `cm2` | 0.0001 |
| Square Meter | `m2` | 1.0 |
| Square Kilometer | `km2` | 1000000.0 |
| Square Inch | `in2` | 0.00064516 |
| Square Foot | `ft2` | 0.092903 |
| Square Yard | `yd2` | 0.836127 |
| Square Mile | `mi2` | 2589988.11 |
| Acre | `acre` | 4046.86 |
| Hectare | `ha` | 10000.0 |

## 🔢 Mathematical Functions Reference

### Trigonometric Functions
| Function | Syntax | Description | Example |
|----------|--------|-------------|---------|
| Sine | `sin(x)` | Sine of x (radians) | `sin(pi/2)` → 1.0 |
| Cosine | `cos(x)` | Cosine of x (radians) | `cos(0)` → 1.0 |
| Tangent | `tan(x)` | Tangent of x (radians) | `tan(pi/4)` → 1.0 |
| Arcsine | `asin(x)` | Inverse sine | `asin(1)` → 1.5708 |
| Arccosine | `acos(x)` | Inverse cosine | `acos(1)` → 0.0 |
| Arctangent | `atan(x)` | Inverse tangent | `atan(1)` → 0.7854 |

### Logarithmic Functions
| Function | Syntax | Description | Example |
|----------|--------|-------------|---------|
| Common Log | `log(x)` | Base-10 logarithm | `log(100)` → 2.0 |
| Natural Log | `ln(x)` | Natural logarithm (base e) | `ln(e)` → 1.0 |

### Power & Root Functions
| Function | Syntax | Description | Example |
|----------|--------|-------------|---------|
| Square Root | `sqrt(x)` | Square root of x | `sqrt(16)` → 4.0 |
| Power | `pow(x, y)` | x raised to power y | `pow(2, 3)` → 8.0 |
| Exponential | `exp(x)` | e raised to power x | `exp(1)` → 2.7183 |

### Other Functions
| Function | Syntax | Description | Example |
|----------|--------|-------------|---------|
| Absolute Value | `abs(x)` | Absolute value of x | `abs(-5)` → 5.0 |
| Factorial | `factorial(x)` | Factorial of x | `factorial(5)` → 120.0 |

### Mathematical Constants
| Constant | Value | Description |
|----------|-------|-------------|
| `pi` | 3.14159... | Pi (π) |
| `e` | 2.71828... | Euler's number |

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

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Go Team**: For the excellent programming language
- **MCP Protocol**: Model Context Protocol specification
- **External Libraries**:
  - [`shopspring/decimal`](https://github.com/shopspring/decimal): Precise decimal arithmetic
  - [`Knetic/govaluate`](https://github.com/Knetic/govaluate): Expression evaluation
  - [`gonum`](https://gonum.org/): Scientific computing
  - [`gopkg.in/yaml.v3`](https://gopkg.in/yaml.v3): YAML configuration support

**Project Resources:**
- **Issues**: [GitHub Issues](https://github.com/IBM/mcp-context-forge/issues)
- **Documentation**: This README and inline code documentation
- **Examples**: See `make example-*` commands

**Getting Help:**
1. Check this README for comprehensive documentation
2. Review the test files for usage examples
3. Submit issues with detailed error information
4. Contact the maintainer for direct support

---

**Built with ❤️ by Avinash Sangle for the IBM ContextForge project**

**Connect with the Author:**
- 🌐 Website: [https://avisangle.github.io/](https://avisangle.github.io/)
- 💻 GitHub: [https://github.com/avisangle](https://github.com/avisangle)

For more information about MCP servers and the ContextForge project, visit the [IBM ContextForge repository](https://github.com/IBM/mcp-context-forge).
