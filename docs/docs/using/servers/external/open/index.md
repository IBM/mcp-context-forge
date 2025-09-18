# Open MCP Servers

## Overview

Open MCP servers are publicly accessible services that implement the Model Context Protocol without requiring authentication. These servers provide various specialized capabilities for software development, code analysis, and documentation access.

## Available Open Servers

### Semgrep MCP Server

**Category:** Software Development / Security Analysis

**Endpoint:** `https://mcp.semgrep.ai/sse`

**Transport:** Server-Sent Events (SSE)

#### Overview

Semgrep MCP provides static analysis and security scanning capabilities through the Model Context Protocol. It enables AI applications to perform code analysis, identify security vulnerabilities, and suggest fixes using Semgrep's powerful pattern-matching engine.

#### Features

- 🔍 Static code analysis
- 🛡️ Security vulnerability detection
- 🐛 Bug pattern identification
- 📝 Code quality checks
- 🔧 Automated fix suggestions
- 📊 Compliance scanning
- 🎯 Custom rule support
- 🌐 Multi-language support (30+ languages)

#### Integration with MCP Gateway

```bash
# Register Semgrep with MCP Gateway
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "semgrep",
    "url": "https://mcp.semgrep.ai/sse",
    "transport": "sse",
    "description": "Static analysis and security scanning",
    "tags": ["security", "analysis", "open-source"]
  }'
```

#### Available Tools

**scan_code**
```json
{
  "tool": "scan_code",
  "arguments": {
    "code": "import pickle\ndata = pickle.loads(user_input)",
    "language": "python",
    "rule_sets": ["security", "best-practices"]
  }
}
```

**scan_repository**
```json
{
  "tool": "scan_repository",
  "arguments": {
    "repository_url": "https://github.com/example/repo",
    "branch": "main",
    "paths": ["src/", "lib/"],
    "config": "auto"
  }
}
```

**check_compliance**
```json
{
  "tool": "check_compliance",
  "arguments": {
    "standard": "OWASP-Top-10",
    "file_path": "app.py",
    "severity_threshold": "WARNING"
  }
}
```

#### Example Usage

```python
import asyncio
from mcp_client import MCPClient

async def analyze_code_with_semgrep():
    client = MCPClient("https://mcp.semgrep.ai/sse", transport="sse")

    # Connect to Semgrep MCP
    await client.connect()

    # Scan code for vulnerabilities
    result = await client.call_tool(
        "scan_code",
        {
            "code": """
            def process_user_data(request):
                user_id = request.GET['id']
                query = f"SELECT * FROM users WHERE id = {user_id}"
                cursor.execute(query)
            """,
            "language": "python",
            "rule_sets": ["security"]
        }
    )

    print("Security Issues Found:")
    for issue in result['findings']:
        print(f"- {issue['severity']}: {issue['message']}")
        print(f"  Rule: {issue['rule_id']}")
        print(f"  Fix: {issue['fix']}")

asyncio.run(analyze_code_with_semgrep())
```

---

### Javadocs MCP Server

**Category:** Software Development / Documentation

**Endpoint:** `https://www.javadocs.dev/mcp`

**Transport:** HTTP

#### Overview

The Javadocs MCP server provides access to Java documentation, API references, and package information for millions of Java libraries hosted on Maven Central and other repositories.

#### Features

- 📚 Comprehensive Java documentation
- 🔍 API search and discovery
- 📦 Package and class information
- 🔗 Dependency information
- 📊 Version comparison
- 💡 Code examples
- 🏷️ Annotation details
- 🌳 Inheritance hierarchy

#### Integration with MCP Gateway

```bash
# Register Javadocs with MCP Gateway
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "javadocs",
    "url": "https://www.javadocs.dev/mcp",
    "transport": "http",
    "description": "Java documentation and API reference",
    "tags": ["documentation", "java", "api-reference", "open-source"]
  }'
```

#### Available Tools

**search_class**
```json
{
  "tool": "search_class",
  "arguments": {
    "query": "ArrayList",
    "package": "java.util",
    "version": "latest"
  }
}
```

**get_documentation**
```json
{
  "tool": "get_documentation",
  "arguments": {
    "class": "java.util.HashMap",
    "method": "put",
    "include_examples": true
  }
}
```

**find_dependencies**
```json
{
  "tool": "find_dependencies",
  "arguments": {
    "artifact": "org.springframework.boot:spring-boot-starter-web",
    "version": "3.1.0",
    "scope": "compile"
  }
}
```

**compare_versions**
```json
{
  "tool": "compare_versions",
  "arguments": {
    "artifact": "com.google.guava:guava",
    "version1": "31.0-jre",
    "version2": "32.0-jre",
    "show_breaking_changes": true
  }
}
```

#### Example Usage

```python
import requests
import json

class JavadocsMCPClient:
    def __init__(self):
        self.base_url = "https://www.javadocs.dev/mcp"

    def search_documentation(self, class_name, package=None):
        """Search for Java class documentation"""
        response = requests.post(
            self.base_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "search_class",
                    "arguments": {
                        "query": class_name,
                        "package": package
                    }
                }
            }
        )
        return response.json()

    def get_method_docs(self, full_class_name, method_name):
        """Get documentation for a specific method"""
        response = requests.post(
            self.base_url,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_documentation",
                    "arguments": {
                        "class": full_class_name,
                        "method": method_name,
                        "include_examples": True
                    }
                }
            }
        )
        return response.json()

# Example usage
client = JavadocsMCPClient()

# Search for ArrayList documentation
result = client.search_documentation("ArrayList", "java.util")
print(json.dumps(result, indent=2))

# Get specific method documentation
method_docs = client.get_method_docs("java.util.ArrayList", "add")
print(f"Method signature: {method_docs['result']['signature']}")
print(f"Description: {method_docs['result']['description']}")
```

## Using Open Servers with MCP Gateway

### Direct Connection

Open servers can be accessed directly without authentication:

```python
from mcp_gateway_client import MCPGatewayClient

# Initialize gateway client
gateway = MCPGatewayClient("http://localhost:4444")

# Call Semgrep tool
semgrep_result = await gateway.call_tool(
    server="semgrep",
    tool="scan_code",
    arguments={
        "code": suspicious_code,
        "language": "python"
    }
)

# Call Javadocs tool
javadoc_result = await gateway.call_tool(
    server="javadocs",
    tool="get_documentation",
    arguments={
        "class": "java.util.Stream",
        "method": "filter"
    }
)
```

### Batch Processing

```python
async def batch_analyze_project(project_files):
    """Analyze multiple files using open MCP servers"""
    results = {
        "security_issues": [],
        "documentation_refs": []
    }

    # Security analysis with Semgrep
    for file_path, content in project_files.items():
        if file_path.endswith('.py'):
            scan = await gateway.call_tool(
                server="semgrep",
                tool="scan_code",
                arguments={
                    "code": content,
                    "language": "python"
                }
            )
            results["security_issues"].extend(scan["findings"])

        # Get documentation for Java imports
        elif file_path.endswith('.java'):
            imports = extract_imports(content)
            for import_stmt in imports:
                docs = await gateway.call_tool(
                    server="javadocs",
                    tool="search_class",
                    arguments={"query": import_stmt}
                )
                results["documentation_refs"].append(docs)

    return results
```

### Streaming with SSE

For SSE-enabled servers like Semgrep:

```python
import aiohttp
import json

async def stream_semgrep_analysis(code_repository):
    """Stream analysis results from Semgrep SSE endpoint"""
    async with aiohttp.ClientSession() as session:
        # Initialize SSE connection
        async with session.get(
            "https://mcp.semgrep.ai/sse",
            headers={"Accept": "text/event-stream"}
        ) as response:
            # Send analysis request
            await session.post(
                "https://mcp.semgrep.ai/sse",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "scan_repository",
                        "arguments": {
                            "repository_url": code_repository,
                            "streaming": True
                        }
                    }
                }
            )

            # Process streaming results
            async for line in response.content:
                if line.startswith(b'data: '):
                    data = json.loads(line[6:])
                    yield data
```

## Best Practices

### Error Handling

```python
async def safe_call_open_server(server, tool, arguments, retry=3):
    """Call open server with retry logic"""
    for attempt in range(retry):
        try:
            result = await gateway.call_tool(
                server=server,
                tool=tool,
                arguments=arguments
            )
            return result
        except ConnectionError as e:
            if attempt < retry - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue
            raise
        except Exception as e:
            print(f"Error calling {server}/{tool}: {e}")
            return None
```

### Caching Results

```python
from functools import lru_cache
import hashlib

class CachedMCPClient:
    def __init__(self):
        self.cache = {}

    def _cache_key(self, server, tool, arguments):
        """Generate cache key for request"""
        key_str = f"{server}:{tool}:{json.dumps(arguments, sort_keys=True)}"
        return hashlib.md5(key_str.encode()).hexdigest()

    async def call_with_cache(self, server, tool, arguments, ttl=3600):
        """Call with caching for expensive operations"""
        cache_key = self._cache_key(server, tool, arguments)

        # Check cache
        if cache_key in self.cache:
            cached, timestamp = self.cache[cache_key]
            if time.time() - timestamp < ttl:
                return cached

        # Make request
        result = await gateway.call_tool(server, tool, arguments)

        # Store in cache
        self.cache[cache_key] = (result, time.time())
        return result
```

### Rate Limiting

Even though these are open servers, implement rate limiting to be respectful:

```python
from asyncio import Semaphore

class RateLimitedClient:
    def __init__(self, max_concurrent=10, requests_per_second=5):
        self.semaphore = Semaphore(max_concurrent)
        self.rate_limit = requests_per_second
        self.last_request_time = 0

    async def call_with_limit(self, server, tool, arguments):
        """Call with rate limiting"""
        async with self.semaphore:
            # Enforce rate limit
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < 1.0 / self.rate_limit:
                await asyncio.sleep(1.0 / self.rate_limit - time_since_last)

            self.last_request_time = time.time()
            return await gateway.call_tool(server, tool, arguments)
```

## Advantages of Open Servers

1. **No Authentication Required**: Immediate access without OAuth flows
2. **Free to Use**: No API keys or subscriptions needed
3. **Community Driven**: Often open-source and community maintained
4. **Always Available**: Public endpoints with high availability
5. **Standard Compliance**: Full MCP protocol implementation
6. **Easy Integration**: Simple to add to any MCP Gateway

## Limitations

1. **Rate Limits**: May have stricter rate limits than authenticated services
2. **Feature Restrictions**: Some advanced features may require authentication
3. **No SLA**: No guaranteed service level agreements
4. **Public Data Only**: Cannot access private or proprietary data
5. **Limited Customization**: Cannot configure server-side settings

## Contributing

Many open MCP servers accept contributions:

- **Semgrep**: [github.com/returntocorp/semgrep](https://github.com/returntocorp/semgrep)
- **Javadocs**: Contact through [javadocs.dev](https://javadocs.dev)

## Related Resources

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [Semgrep Documentation](https://semgrep.dev/docs/)
- [Javadocs.dev API](https://javadocs.dev/api)
- [MCP Gateway Documentation](../../index.md)