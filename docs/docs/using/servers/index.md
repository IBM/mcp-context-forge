# 🎯 Sample MCP Servers

The **MCP Context Forge Gateway** includes a collection of **high-performance sample MCP servers** built in different programming languages. These servers serve multiple purposes: demonstrating best practices for MCP implementation, providing ready-to-use tools for testing and development, and showcasing the performance characteristics of different language ecosystems.

> **Perfect for testing, learning, and production use** - each server is optimized for speed, reliability, and demonstrates language-specific MCP patterns.

---

## 🌟 Available Servers

### 🦫 Fast Time Server (Go)
**`mcp-servers/go/fast-time-server`** - Ultra-fast timezone and time conversion tools

- **Language:** Go 1.21+
- **Performance:** Sub-millisecond response times
- **Transport:** stdio, HTTP, SSE, dual-mode
- **Tools:** `get_system_time`, timezone conversions with DST support
- **Container:** `ghcr.io/ibm/fast-time-server:latest`

**[📖 Full Documentation →](go-fast-time-server.md)**

#### Quick Start
```bash
# Docker (recommended)
docker run --rm -it -p 8888:8080 \
  ghcr.io/ibm/fast-time-server:latest \
  -transport=dual -log-level=debug

# From source
cd mcp-servers/go/fast-time-server
make build && make run
```

---

## 🚀 Coming Soon

### 🐍 Python Samples
- **Fast Calculator Server** - Mathematical operations and conversions
- **System Info Server** - OS and hardware information tools
- **File Operations Server** - Safe file system operations

### 🟨 JavaScript/TypeScript Samples
- **Web Scraper Server** - URL content extraction and parsing
- **JSON Transformer Server** - Data transformation and validation
- **API Client Server** - REST API interaction tools

### 🦀 Rust Samples
- **High-Performance Parser Server** - Ultra-fast text and data parsing
- **Crypto Utils Server** - Cryptographic operations and hashing
- **Network Tools Server** - Network diagnostics and utilities

### ☕ Java Samples
- **Enterprise Integration Server** - Database and messaging operations
- **Document Processor Server** - PDF and office document handling
- **Monitoring Server** - Application metrics and health checks

---

## 🎯 Use Cases

### **🧪 Testing & Development**
- **Protocol Testing** - Validate MCP client implementations
- **Performance Benchmarking** - Compare language runtime characteristics
- **Integration Testing** - Test gateway federation and tool routing

### **📚 Learning & Reference**
- **Best Practices** - Language-specific MCP implementation patterns
- **Architecture Examples** - Different transport and authentication approaches
- **Performance Optimization** - Learn optimization techniques per language

### **🏭 Production Ready**
- **Horizontal Scaling** - All servers support container orchestration
- **Monitoring Integration** - Built-in health checks and metrics
- **Security Hardened** - Authentication, input validation, and safe defaults

---

## 🌐 Gateway Integration

All sample servers are designed to integrate seamlessly with the MCP Gateway:

### **Direct Registration**
```bash
# Register any sample server with the gateway
curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"sample_server","url":"http://localhost:8080/sse"}' \
     http://localhost:4444/gateways
```

### **Via Translate Bridge**
```bash
# Expose stdio servers over SSE using mcpgateway.translate
python3 -m mcpgateway.translate \
  --stdio "path/to/sample-server" \
  --expose-sse \
  --port 8002
```

### **Testing with Wrapper**
```bash
# Test through mcpgateway.wrapper
export MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN
export MCP_SERVER_CATALOG_URLS='http://localhost:4444/servers/UUID_OF_SERVER_1'
python3 -m mcpgateway.wrapper
```

---

## 🛠 Development Guidelines

### **Adding New Sample Servers**

Each sample server should follow these conventions:

#### **Directory Structure**
```
mcp-servers/
├── go/
│   └── your-server/
│       ├── main.go
│       ├── Makefile
│       ├── Dockerfile
│       └── README.md
├── python/
│   └── your-server/
│       ├── main.py
│       ├── pyproject.toml
│       ├── Dockerfile
│       └── README.md
└── typescript/
    └── your-server/
        ├── src/index.ts
        ├── package.json
        ├── Dockerfile
        └── README.md
```

#### **Required Features**
- ✅ **Multiple transports** - stdio, SSE, HTTP support
- ✅ **Container ready** - Dockerfile with multi-stage builds
- ✅ **Health checks** - `/health` endpoint for monitoring
- ✅ **Authentication** - Bearer token support for web transports
- ✅ **Logging** - Configurable log levels
- ✅ **Documentation** - Complete usage examples and API docs

#### **Performance Targets**
- **Response Time:** < 10ms for simple operations
- **Memory Usage:** < 50MB baseline memory footprint
- **Startup Time:** < 1 second cold start
- **Throughput:** > 1000 requests/second under load

---

## 📊 Performance Comparison

| Server | Language | Response Time | Memory | Binary Size | Cold Start |
|--------|----------|---------------|---------|-------------|------------|
| fast-time-server | Go | **0.5ms** | 8MB | 12MB | 100ms |
| *coming soon* | Python | ~2ms | 25MB | N/A | 300ms |
| *coming soon* | TypeScript | ~3ms | 35MB | N/A | 400ms |
| *coming soon* | Rust | **0.3ms** | 4MB | 8MB | 50ms |
| *coming soon* | Java | ~5ms | 45MB | 25MB | 800ms |

*Benchmarks measured on standard GitHub Actions runners*

---

## 🤝 Contributing

We welcome contributions of new sample servers!

### **Contribution Process**

1. **Choose a language** and create the directory structure
2. **Implement core MCP functionality** following our guidelines
3. **Add comprehensive tests** and performance benchmarks
4. **Create documentation** following the fast-time-server example
5. **Submit a pull request** with your implementation

### **Language Priorities**

We're particularly interested in:
- **Python** - Most popular for AI/ML tooling
- **TypeScript** - Web-native integration
- **Rust** - Maximum performance critical applications
- **Java** - Enterprise integration scenarios

---

## 📚 Resources

### **MCP Specification**
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)

### **Gateway Documentation**
- [MCP Context Forge Gateway](../README.md)
- [mcpgateway.wrapper Usage](../mcpgateway-wrapper.md)
- [mcpgateway.translate Bridge](../mcpgateway-translate.md)

### **Development Tools**
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector) - Interactive protocol debugging
- [mcpgateway.translate Bridge](../mcpgateway-translate.md) - stdio ↔ SSE/Streamable HTTP bridge
- [UV](https://docs.astral.sh/uv/) - Fast Python package management

---

## 🔗 Quick Links

- [🦫 **Fast Time Server (Go)** →](go-fast-time-server.md)

---

*Want to add a new sample server? [Open an issue](https://github.com/ibm/mcp-context-forge/issues) or submit a pull request!*
