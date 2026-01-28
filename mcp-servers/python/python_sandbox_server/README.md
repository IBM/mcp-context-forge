# Python Sandbox MCP Server

> Author: Mihai Criveti

A highly secure MCP server for executing Python code in sandboxed environments. Combines RestrictedPython for AST-level code transformation with optional gVisor container isolation for maximum security. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **Multi-Layer Security**: RestrictedPython + tiered capability model
- **Resource Controls**: Configurable memory, CPU, and execution time limits
- **Safe Execution Environment**: Restricted builtins and namespace isolation
- **Tiered Security Model**: Basic, Data Science, Network, and Filesystem capabilities
- **Code Validation**: Pre-execution code analysis and validation
- **Security Monitoring**: Tracks and reports security events and blocked operations
- **Rich Module Library**: 40+ safe stdlib modules, optional data science and network support

## Security Architecture

### Layer 1: RestrictedPython
- **AST Transformation**: Modifies code at the Abstract Syntax Tree level
- **Safe Builtins**: Only allows approved built-in functions
- **Import Restrictions**: Controls which modules can be imported
- **Namespace Isolation**: Prevents access to dangerous globals

### Layer 2: Container Isolation (Optional)
- **gVisor Runtime**: Application kernel for additional isolation
- **Resource Limits**: Memory, CPU, and network restrictions
- **Read-only Filesystem**: Prevents file system modifications
- **No Network Access**: Blocks all network operations
- **Non-root Execution**: Runs with minimal privileges

### Layer 3: Host-Level Controls
- **Execution Timeouts**: Hard limits on execution time
- **Output Size Limits**: Prevents excessive output generation
- **Process Monitoring**: Tracks resource usage and execution state

## Tools

- `execute_code` - Execute Python code in secure sandbox
- `validate_code` - Validate code without execution
- `get_sandbox_info` - Get sandbox capabilities and configuration

## Installation

```bash
# Install in development mode with sandbox dependencies
make dev-install

# Or install normally
make install
```

## Configuration

Create a `.env` file (see `.env.example`) to configure the sandbox:

```bash
# Copy example configuration
cp .env.example .env

# Edit as needed
vi .env
```

### Environment Variables

#### Core Settings
- `SANDBOX_TIMEOUT` - Execution timeout in seconds (default: 30)
- `SANDBOX_MAX_OUTPUT_SIZE` - Maximum output size in bytes (default: 1MB)

#### Security Capabilities
- `SANDBOX_ENABLE_NETWORK` - Enable network modules like httpx, requests (default: false)
- `SANDBOX_ENABLE_FILESYSTEM` - Enable filesystem modules like pathlib, tempfile (default: false)
- `SANDBOX_ENABLE_DATA_SCIENCE` - Enable numpy, pandas, scipy, matplotlib, etc. (default: false)
- `SANDBOX_ALLOWED_IMPORTS` - Override with custom comma-separated module list (optional)

### Security Profiles

#### Basic Profile (Default)
Safe standard library modules only:
- **Math & Random**: math, random, statistics, decimal, fractions
- **Data Structures**: collections, itertools, functools, heapq, bisect
- **Text Processing**: string, textwrap, re, difflib, unicodedata
- **Encoding**: base64, binascii, hashlib, hmac, secrets
- **Parsing**: json, csv, html.parser, xml.etree, urllib.parse
- **Utilities**: datetime, uuid, calendar, dataclasses, enum, typing

#### Data Science Profile
Enable with `SANDBOX_ENABLE_DATA_SCIENCE=true`:
- numpy, pandas, scipy, matplotlib
- seaborn, sklearn, statsmodels
- plotly, sympy

#### Network Profile
Enable with `SANDBOX_ENABLE_NETWORK=true`:
- httpx, requests, urllib.request
- aiohttp, websocket
- email, smtplib, ftplib

#### Filesystem Profile
Enable with `SANDBOX_ENABLE_FILESYSTEM=true`:
- pathlib, os.path, tempfile
- shutil, glob
- zipfile, tarfile

## Container Setup (Optional)

For maximum security with container isolation:

```bash
# Build the sandbox container
make build-sandbox

# Test the container
make test-sandbox
```

### gVisor Installation (Recommended)

For additional security, install gVisor runtime:

```bash
# Install gVisor (Ubuntu/Debian)
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list > /dev/null
sudo apt-get update && sudo apt-get install -y runsc

# Configure Docker to use gVisor
sudo systemctl restart docker
```

## Configuration

Environment variables for customization:

```bash
export SANDBOX_DEFAULT_TIMEOUT=30           # Default execution timeout
export SANDBOX_MAX_TIMEOUT=300              # Maximum allowed timeout
export SANDBOX_DEFAULT_MEMORY_LIMIT=128m    # Default memory limit
export SANDBOX_MAX_OUTPUT_SIZE=1048576      # Max output size (1MB)
export SANDBOX_ENABLE_CONTAINER_MODE=true   # Enable container execution
export SANDBOX_CONTAINER_IMAGE=python-sandbox:latest  # Container image name
```

## Usage

### Stdio Mode (for Claude Desktop, IDEs)

```bash
make dev
```

### HTTP Mode (via MCP Gateway)

```bash
make serve-http
```

## Examples

### Basic Code Execution

```python
{
  "name": "execute_code",
  "arguments": {
    "code": "result = 2 + 2\nprint(f'The answer is: {result}')",
    "timeout": 10,
    "capture_output": true
  }
}
```

### Data Analysis Example

```python
{
  "name": "execute_code",
  "arguments": {
    "code": "import math\ndata = [1, 2, 3, 4, 5]\nresult = sum(data) / len(data)\nprint(f'Average: {result}')",
    "allowed_imports": ["math"],
    "timeout": 15
  }
}
```

### Container-Based Execution

```python
{
  "name": "execute_code",
  "arguments": {
    "code": "import numpy as np\ndata = np.array([1, 2, 3, 4, 5])\nresult = np.mean(data)",
    "use_container": true,
    "memory_limit": "256m",
    "timeout": 30
  }
}
```

### Code Validation

```python
{
  "name": "validate_code",
  "arguments": {
    "code": "import os\nos.system('rm -rf /')"
  }
}
```

### Check Capabilities

```python
{
  "name": "list_capabilities",
  "arguments": {}
}
```

## Response Format

### Successful Execution
```json
{
  "success": true,
  "execution_id": "uuid-here",
  "result": 4,
  "stdout": "The answer is: 4\n",
  "stderr": "",
  "execution_time": 0.001,
  "variables": ["result"]
}
```

### Validation Response
```json
{
  "validation": {
    "valid": false,
    "errors": ["Line 1: Import 'os' is not allowed"],
    "message": "Code contains restricted operations"
  },
  "analysis": {
    "line_count": 2,
    "character_count": 25,
    "estimated_complexity": "low"
  },
  "recommendations": [
    "Some operations may be restricted in sandbox environment"
  ]
}
```

### Error Response
```json
{
  "success": false,
  "error": "Execution timeout",
  "execution_id": "uuid-here",
  "timeout": 30
}
```

## Supported Libraries

### Always Available (RestrictedPython Mode)
- **Built-ins**: All safe Python built-in functions
- **Math**: Basic math operations and math module
- **Collections**: lists, dicts, sets, tuples

### Available with allowed_imports
- **math**: Mathematical functions
- **random**: Random number generation
- **datetime**: Date and time handling
- **json**: JSON processing
- **base64**: Base64 encoding/decoding
- **hashlib**: Cryptographic hashing
- **uuid**: UUID generation
- **collections**: Advanced collections
- **itertools**: Iterator functions
- **functools**: Higher-order functions
- **re**: Regular expressions
- **string**: String operations
- **decimal**: Decimal arithmetic
- **fractions**: Rational numbers
- **statistics**: Statistical functions

### Container Mode Additional Libraries
- **numpy**: Numerical computing
- **pandas**: Data analysis
- **matplotlib**: Plotting (output as text/data)
- **requests**: HTTP requests (if network enabled)

## Security Features

### Code Analysis
- **Syntax Validation**: Checks for valid Python syntax
- **Dangerous Pattern Detection**: Identifies potentially harmful operations
- **Import Restrictions**: Controls which modules can be imported
- **Function Allowlisting**: Only permits safe function calls

### Runtime Protection
- **Execution Timeouts**: Prevents infinite loops and long-running code
- **Memory Limits**: Prevents memory exhaustion attacks
- **Output Limits**: Prevents excessive output generation
- **Namespace Isolation**: Isolates code from host environment

### Container Isolation (Optional)
- **Process Isolation**: Separate process space
- **Filesystem Isolation**: Read-only filesystem access
- **Network Isolation**: No network access by default
- **User Isolation**: Non-root execution

## Use Cases

### Educational/Learning
```python
# Teach Python concepts safely
code = """
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

result = [fibonacci(i) for i in range(10)]
print("Fibonacci sequence:", result)
"""
```

### Data Analysis Prototyping
```python
# Quick data analysis
code = """
import statistics
data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
mean = statistics.mean(data)
median = statistics.median(data)
stdev = statistics.stdev(data)

result = {
    'mean': mean,
    'median': median,
    'std_dev': stdev
}
print(f"Statistics: {result}")
"""
```

### Algorithm Testing
```python
# Test sorting algorithms
code = """
def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        for j in range(0, n-i-1):
            if arr[j] > arr[j+1]:
                arr[j], arr[j+1] = arr[j+1], arr[j]
    return arr

test_data = [64, 34, 25, 12, 22, 11, 90]
result = bubble_sort(test_data.copy())
print(f"Sorted: {result}")
"""
```

### Mathematical Computations
```python
# Complex mathematical operations
code = """
import math

def calculate_pi_leibniz(terms):
    pi_approx = 0
    for i in range(terms):
        pi_approx += ((-1) ** i) / (2 * i + 1)
    return pi_approx * 4

result = calculate_pi_leibniz(1000)
print(f"Pi approximation: {result}")
print(f"Difference from math.pi: {abs(result - math.pi)}")
"""
```

## Development

```bash
# Format code
make format

# Run tests
make test

# Lint code
make lint

# Build sandbox container
make build-sandbox
```

## Deployment Recommendations

### Production Deployment
1. **Container Infrastructure**: Deploy with container orchestration (Kubernetes, Docker Swarm)
2. **Resource Limits**: Set strict CPU and memory limits
3. **Network Policies**: Restrict network access
4. **Monitoring**: Implement comprehensive logging and alerting
5. **Updates**: Regularly update dependencies and container images

### Security Hardening
1. **Use gVisor**: Enable gVisor runtime for container execution
2. **Read-only Filesystem**: Mount filesystems as read-only where possible
3. **SELinux/AppArmor**: Enable additional MAC controls
4. **Audit Logging**: Log all code execution attempts
5. **Rate Limiting**: Implement rate limiting for execution requests

### High-Security Environment
```yaml
# Example Kubernetes deployment with security
apiVersion: v1
kind: Pod
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1001
    fsGroup: 1001
  containers:
  - name: python-sandbox-server
    image: python-sandbox-server:latest
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
    resources:
      limits:
        memory: "512Mi"
        cpu: "500m"
      requests:
        memory: "256Mi"
        cpu: "250m"
```

## Error Handling

The server handles various error conditions gracefully:

- **Syntax Errors**: Returns detailed syntax error information
- **Runtime Errors**: Captures and returns exception details
- **Timeout Errors**: Handles execution timeouts cleanly
- **Resource Errors**: Manages out-of-memory and resource exhaustion
- **Security Violations**: Blocks and reports dangerous operations

## Monitoring and Logging

- **Execution Tracking**: Each execution gets a unique ID
- **Performance Metrics**: Execution time and resource usage
- **Security Events**: Logs security violations and blocked operations
- **Error Analytics**: Detailed error reporting and categorization

## Limitations

- **No Persistent State**: Each execution is isolated
- **Limited I/O**: File system access is heavily restricted
- **Network Restrictions**: Network access is disabled by default
- **Resource Bounds**: Strict limits on memory and execution time
- **Module Restrictions**: Only safe modules are allowed

## Best Practices

1. **Always Validate**: Use `validate_code` before `execute_code`
2. **Set Appropriate Timeouts**: Balance functionality with security
3. **Use Container Mode**: For untrusted code, use container execution
4. **Monitor Resource Usage**: Track execution metrics
5. **Regular Updates**: Keep RestrictedPython and containers updated
6. **Audit Logs**: Review execution logs regularly for suspicious activity
