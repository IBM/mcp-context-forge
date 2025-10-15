# Go Calculator Server

## Overview

A comprehensive **Go-based MCP server** for mathematical computations, implementing **13 mathematical tools** with advanced features and high precision calculations. This server provides everything from basic arithmetic to advanced financial modeling, statistical analysis, and unit conversions.

**Key Features:**

- 🧮 13 specialized mathematical tools
- 📊 Advanced statistical analysis
- 💰 Financial calculations (NPV, IRR, loans)
- 🔄 Multi-category unit conversions
- 📐 Expression evaluation with variables
- 🎯 High precision using decimal arithmetic
- ⚡ Sub-millisecond response times

## Quick Start

### Using with MCP Gateway

```bash
# Start the calculator server
cd mcp-servers/go/calculator-server
go build -o calculator-server ./cmd/server
./calculator-server -transport=stdio

# Or use HTTP transport
./calculator-server -transport=http -port=8081
```

### Integration with MCP Gateway

```bash
# Register with MCP Gateway (if using HTTP)
curl -X POST http://localhost:4444/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "calculator-server",
    "url": "http://localhost:8081/mcp",
    "transport": "http",
    "description": "Comprehensive mathematical computation server"
  }'
```

## Available Tools

### Basic Mathematical Tools (6 Tools)

#### 1. basic_math
Perform arithmetic operations with precision control.

**Operations:** add, subtract, multiply, divide

```json
{
  "tool": "basic_math",
  "arguments": {
    "operation": "add",
    "operands": [15.5, 20.3, 10.2],
    "precision": 2
  }
}
```

#### 2. advanced_math
Scientific mathematical functions including trigonometry and logarithms.

**Functions:** sin, cos, tan, asin, acos, atan, log, log10, ln, sqrt, abs, factorial, exp, pow

```json
{
  "tool": "advanced_math",
  "arguments": {
    "function": "pow",
    "value": 2,
    "exponent": 8
  }
}
```

#### 3. expression_eval
Evaluate complex mathematical expressions with variable substitution.

```json
{
  "tool": "expression_eval",
  "arguments": {
    "expression": "2 * pi * r",
    "variables": {
      "r": 5
    }
  }
}
```

#### 4. statistics
Perform statistical analysis on datasets.

**Operations:** mean, median, mode, std_dev, variance, percentile

```json
{
  "tool": "statistics",
  "arguments": {
    "data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "operation": "mean"
  }
}
```

#### 5. unit_conversion
Convert between various measurement units.

**Categories:**

- **Length:** mm, cm, m, km, in, ft, yd, mi
- **Weight:** mg, g, kg, t, oz, lb, st, ton
- **Temperature:** C, F, K, R
- **Volume:** ml, cl, dl, l, kl, fl_oz, cup, pt, qt, gal
- **Area:** mm², cm², m², km², in², ft², yd², mi², acre, ha

```json
{
  "tool": "unit_conversion",
  "arguments": {
    "value": 100,
    "fromUnit": "cm",
    "toUnit": "m",
    "category": "length"
  }
}
```

#### 6. financial
Comprehensive financial calculations.

**Operations:** compound_interest, simple_interest, loan_payment, roi, present_value, future_value

```json
{
  "tool": "financial",
  "arguments": {
    "operation": "compound_interest",
    "principal": 10000,
    "rate": 5,
    "time": 3,
    "periods": 12
  }
}
```

### Advanced Specialized Tools (7 Tools)

#### 7. stats_summary
Get a comprehensive statistical summary of a dataset.

```json
{
  "tool": "stats_summary",
  "arguments": {
    "data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
  }
}
```

#### 8. percentile
Calculate specific percentiles (0-100) for a dataset.

```json
{
  "tool": "percentile",
  "arguments": {
    "data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "percentile": 90
  }
}
```

#### 9. batch_conversion
Convert multiple values between units at once.

```json
{
  "tool": "batch_conversion",
  "arguments": {
    "values": [100, 200, 300],
    "fromUnit": "cm",
    "toUnit": "m",
    "category": "length"
  }
}
```

#### 10. npv (Net Present Value)
Calculate NPV for investment analysis.

```json
{
  "tool": "npv",
  "arguments": {
    "cashFlows": [-50000, 15000, 20000, 25000, 30000],
    "discountRate": 8
  }
}
```

#### 11. irr (Internal Rate of Return)
Calculate IRR for investment performance evaluation.

```json
{
  "tool": "irr",
  "arguments": {
    "cashFlows": [-100000, 30000, 35000, 40000, 45000]
  }
}
```

#### 12. loan_comparison
Compare multiple loan scenarios.

```json
{
  "tool": "loan_comparison",
  "arguments": {
    "loans": [
      {"principal": 100000, "rate": 3.5, "time": 15},
      {"principal": 100000, "rate": 4.0, "time": 30}
    ]
  }
}
```

#### 13. investment_scenarios
Compare multiple investment options.

```json
{
  "tool": "investment_scenarios",
  "arguments": {
    "scenarios": [
      {"principal": 10000, "rate": 5, "time": 10},
      {"principal": 10000, "rate": 7, "time": 7}
    ]
  }
}
```

## Installation

### Prerequisites
- Go 1.21+
- Git

### Build from Source

```bash
# Clone and navigate to calculator server
cd mcp-servers/go/calculator-server

# Install dependencies
go mod download

# Build the server
go build -o calculator-server ./cmd/server

# Run the server
./calculator-server -transport=stdio
```

### Using Makefile

```bash
# Install dependencies
make deps

# Build for current platform
make build

# Run the server
make run

# Run tests
make test

# Check code quality
make quality
```

## Configuration

### Command Line Options

```bash
./calculator-server [OPTIONS]

Options:
  -transport string   Transport method (stdio, http) (default "stdio")
  -port int          Port for HTTP transport (default 8080)
  -host string       Host for HTTP transport (default "127.0.0.1")
  -config string     Path to configuration file (YAML or JSON)
```

### Configuration File

Create a `config.yaml`:

```yaml
server:
  transport: "http"
  http:
    host: "127.0.0.1"
    port: 8081
    session_timeout: "5m"
    cors:
      enabled: true
      origins: ["http://localhost:3000"]

logging:
  level: "info"
  format: "json"

tools:
  precision:
    max_decimal_places: 15
    default_decimal_places: 2
  statistics:
    max_data_points: 10000
```

### Environment Variables

- `CALCULATOR_TRANSPORT`: Transport method (stdio, http)
- `CALCULATOR_HTTP_HOST`: HTTP server host
- `CALCULATOR_HTTP_PORT`: HTTP server port
- `CALCULATOR_LOG_LEVEL`: Logging level (debug, info, warn, error)

## HTTP Transport

The server supports MCP-compliant HTTP transport with SSE streaming:

```bash
# Start HTTP server
./calculator-server -transport=http -port=8081

# Make a request
curl -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -H "MCP-Protocol-Version: 2024-11-05" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "basic_math",
      "arguments": {
        "operation": "add",
        "operands": [10, 20],
        "precision": 2
      }
    }
  }'
```

## Performance

- **Basic Operations:** ~1-5 μs per operation
- **Advanced Functions:** ~10-50 μs per operation
- **Expression Evaluation:** ~100-500 μs per expression
- **Statistical Operations:** ~10-100 μs per dataset
- **Financial Calculations:** ~50-200 μs per calculation
- **Memory Usage:** ~10-20 MB base, linear scaling with data

## Testing

```bash
# Run all tests
make test

# Run with coverage
make coverage

# Run benchmarks
make benchmark

# Run specific test suites
go test ./tests/basic_test.go -v
go test ./tests/advanced_test.go -v
```

## Mathematical Functions Reference

### Supported Functions
- **Trigonometric:** sin, cos, tan, asin, acos, atan
- **Logarithmic:** log (base 10), ln (natural), log10
- **Power/Root:** sqrt, pow, exp
- **Other:** abs, factorial

### Mathematical Constants
- `pi` - 3.14159...
- `e` - 2.71828...

## Unit Conversion Reference

### Quick Reference Table

| Category | Units | Example |
|----------|-------|---------|
| Length | mm, cm, m, km, in, ft, yd, mi | 100 cm → 1 m |
| Weight | mg, g, kg, t, oz, lb | 1000 g → 1 kg |
| Temperature | C, F, K, R | 0°C → 32°F |
| Volume | ml, l, gal, cup, pt, qt | 1000 ml → 1 l |
| Area | m², ft², acre, ha | 10000 m² → 1 ha |

## Troubleshooting

### Common Issues

**Server won't start:**
```bash
# Check if port is in use
lsof -i :8081

# Verify Go version
go version  # Should be 1.21+
```

**Build errors:**
```bash
# Clean and rebuild
make clean
make deps
make build
```

**Test failures:**
```bash
# Run verbose tests
go test -v ./...

# Check specific test
go test -run TestBasicMath -v
```

## Examples

### Financial Analysis Script

```bash
#!/bin/bash
# Compare investment options

SERVER="http://localhost:8081/mcp"

# Calculate NPV for an investment
curl -X POST $SERVER \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "npv",
      "arguments": {
        "cashFlows": [-100000, 30000, 35000, 40000, 45000],
        "discountRate": 10
      }
    }
  }'
```

### Statistical Analysis

```python
import requests
import json

def analyze_dataset(data):
    """Get statistical summary of a dataset"""

    response = requests.post('http://localhost:8081/mcp',
        headers={'Content-Type': 'application/json'},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "stats_summary",
                "arguments": {
                    "data": data
                }
            }
        }
    )

    return response.json()

# Analyze sample data
result = analyze_dataset([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
print(json.dumps(result, indent=2))
```

## Related Resources

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [Go MCP SDK](https://github.com/mark3labs/mcp-go)
- [Calculator Server Source](https://github.com/IBM/mcp-context-forge/tree/main/mcp-servers/go/calculator-server)

## License

Apache License 2.0

## Author

**Avinash Sangle**

- GitHub: [avisangle](https://github.com/avisangle)
- Website: [avisangle.github.io](https://avisangle.github.io/)
