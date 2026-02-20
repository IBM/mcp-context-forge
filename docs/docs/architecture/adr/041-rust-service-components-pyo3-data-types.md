# ADR-041: Rust Service Components Architecture and PyO3 Data Type Strategy

- *Status:* Proposed
- *Date:* 2026-02-18
- *Deciders:* Core Engineering Team

## Context

The MCP Gateway is introducing Rust-based service implementations to achieve 10-50x performance improvements over Python asyncio/httpx for performance-critical operations. The initial implementation focuses on the A2A (Agent-to-Agent) service, which handles high-frequency HTTP invocations to external agents.

Key architectural decisions are needed for:

1. **Internal Component Structure**: How to organize Rust services within the monorepo
2. **PyO3 Data Type Strategy**: Whether to use PyO3 native types (requiring GIL) or copy data to Rust types (potentially slow for large payloads)
3. **Workspace Organization**: How to manage dependencies and versioning across Rust components
4. **Python-Rust Boundary**: How to minimize overhead when crossing the FFI boundary

## Decision

We will adopt a **modular workspace architecture** with **hybrid data type strategy** for PyO3 bindings.

### 1. Internal Component Structure

**Workspace Layout:**
```
mcpgateway_rust/
├── Cargo.toml                    # Workspace root with shared dependencies
├── src/lib.rs                    # Top-level Python module aggregator
├── services/
│   ├── a2a_service/
│   │   ├── Cargo.toml           # Service-specific crate
│   │   └── src/lib.rs           # Service implementation + PyO3 bindings
│   ├── tool_service/            # Future: tool invocation service
│   └── resource_service/        # Future: resource fetch service
└── pyproject.toml               # Maturin build configuration
```

**Key Design Principles:**

- **Workspace Members**: Each service is a workspace member with independent versioning
- **Shared Dependencies**: Common dependencies (PyO3, tokio, reqwest, serde) defined at workspace level
- **Top-Level Aggregation**: Root `mcpgateway_rust` crate re-exports service modules for Python
- **PyO3 Bindings**: Services expose their functionality through PyO3 bindings

### 2. PyO3 Data Type Strategy

We adopt a **copy-first approach** with selective use of PyO3 GIL types:

**Core Principle: "Copy when you can, use PyO3 GIL types when you must"**

Copy data from Python to Rust native types by default. This provides two critical benefits:

1. **Performance**: Enables GIL-free processing (10-50x faster for I/O)
2. **Future Composability**: Rust services can call each other directly without Python FFI overhead

**Exception: Use PyO3 GIL Types When Copy is Too Expensive**

Only use PyO3 native types when copying would be prohibitively expensive in terms of memory or time.

#### Strategy A: Rust Native Types (Copy/Convert) - **PREFERRED**

**Use for (default):**
- All operations unless copy is prohibitively expensive
- Any I/O-bound work (HTTP, database, file operations)
- CPU-intensive processing
- Operations that benefit from parallelism
- **Future Rust-to-Rust service calls** (no Python types in internal APIs)

**Example:**
```rust
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};

#[pyfunction]
fn invoke_agent(
    py: Python<'_>,
    url: &PyString,           // PyO3 type - requires GIL
    headers: &PyDict,         // PyO3 type - requires GIL
) -> PyResult<PyObject> {
    // Extract data while holding GIL
    let url_str = url.to_str()?;
    let headers_map = extract_headers(headers)?;

    // Release GIL for I/O-bound work
    py.allow_threads(|| {
        // Perform HTTP request without GIL
        tokio_runtime.block_on(async {
            make_request(url_str, headers_map).await
        })
    })
}
```

**Benefits:**
- **GIL-free processing** - enables true parallelism (10-50x faster)
- **Future composability** - Rust services can call each other without Python
- Can be sent across threads (`Send` + `Sync`)
- Suitable for async operations
- No GIL contention during processing
- Better for concurrent workloads

**Trade-offs:**
- Copy overhead during Python→Rust conversion (typically <1ms, negligible)

#### Strategy B: PyO3 Native Types (GIL-Bound) - **USE SPARINGLY**

**Use only when:**
- Copying would exhaust memory (e.g., multi-GB datasets)
- Copying would take excessive time (e.g., >100ms just to copy)
- Data is only accessed briefly and immediately returned
- Zero-copy is critical for the specific use case

**Example:**
```rust
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

#[derive(Deserialize, Serialize)]
struct AgentRequest {
    url: String,
    method: String,
    headers: HashMap<String, String>,
    body: Option<Vec<u8>>,
}

#[pyfunction]
fn invoke_agent_bulk(
    py: Python<'_>,
    request_json: &str,       // Copy string data
) -> PyResult<String> {
    // Parse JSON to Rust types (one-time copy)
    let request: AgentRequest = serde_json::from_str(request_json)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

    // Release GIL for entire operation
    py.allow_threads(|| {
        tokio_runtime.block_on(async {
            // Work with Rust types - no GIL needed
            let response = make_request(&request).await?;
            serde_json::to_string(&response)
        })
    })
}
```

**Benefits:**
- Zero-copy access to Python objects
- Simpler for trivial pass-through operations

**Trade-offs:**
- **Requires GIL for all access** - blocks other Python threads
- **Prevents Rust-to-Rust composition** - Python types can't cross service boundaries
- Not suitable for long-running operations
- Cannot be sent across threads
- Kills performance for I/O-bound work

### 3. Decision Matrix

| Scenario | Data Size | Copy Time | Recommendation | Rationale |
|----------|-----------|-----------|----------------|-----------|
| **HTTP request** | Any | <1ms | **Rust Native** | GIL-free I/O is 10-50x faster |
| **Database query** | Any | <1ms | **Rust Native** | GIL-free I/O critical |
| **JSON processing** | <10MB | <10ms | **Rust Native** | Copy cost negligible vs GIL benefit |
| **Large file (1GB+)** | >1GB | >100ms | **PyO3 GIL** | Copy would exhaust memory/time |
| **Tight loop (10K+ items)** | Any | Accumulated | **PyO3 GIL** | Copy overhead accumulates per iteration |
| **CPU-intensive** | Any | Any | **Rust Native** | Need parallelism |
| **Rust→Rust call** | Any | N/A | **Rust Native** | No Python types in internal APIs |

**Key Principle**: Copy unless copying itself becomes the bottleneck (rare).

**Future Architecture Benefit**: When Rust services use native types internally, they can call each other directly:

```rust
// Future: Rust-to-Rust service composition (no Python!)
pub async fn tool_service_invoke(request: ToolRequest) -> Result<ToolResponse> {
    // Call A2A service directly - no Python FFI overhead
    let agent_response = a2a_service::invoke_agent(&request.url, &request.headers).await?;
    // Process response...
}
```

### 4. Service Implementation Pattern

**Standard Service Structure (Layered Architecture):**

```rust
// services/a2a_service/src/lib.rs
use pyo3::prelude::*;

// ============================================================================
// LAYER 1: Pure Rust Core (No Python types - enables Rust-to-Rust calls)
// ============================================================================
pub mod core {
    use reqwest::Client;
    use serde_json::Value;
    use std::collections::HashMap;

    /// Pure Rust implementation - can be called from other Rust services
    pub async fn invoke_agent(
        url: &str,
        method: &str,
        headers: &HashMap<String, String>,
        body: Option<&[u8]>,
    ) -> Result<Value, Box<dyn std::error::Error>> {
        // Pure Rust implementation
        // No PyO3 types, no GIL
        // Can be called from Python (via FFI) OR other Rust services (direct)
    }
}

// ============================================================================
// LAYER 2: PyO3 Bindings (Thin FFI layer - copies data and delegates to core)
// ============================================================================
#[pyfunction]
fn invoke_agent(
    py: Python<'_>,
    url: String,              // Copy from Python
    method: String,           // Copy from Python
    headers_json: String,     // Copy from Python
    body: Option<Vec<u8>>,    // Copy from Python
) -> PyResult<String> {
    // Parse headers (one-time copy cost)
    let headers: HashMap<String, String> = serde_json::from_str(&headers_json)?;

    // Release GIL and delegate to pure Rust core
    let result = py.allow_threads(|| {
        tokio_runtime.block_on(async {
            core::invoke_agent(&url, &method, &headers, body.as_deref()).await
        })
    });

    // Convert result back to Python
    match result {
        Ok(value) => Ok(serde_json::to_string(&value)?),
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())),
    }
}

#[pymodule]
pub fn a2a_service(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(invoke_agent, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
```

**Key Architecture Principle**: Keep the core logic in pure Rust (no PyO3 types). This enables:
- **Today**: Python calls Rust via FFI (with copy overhead)
- **Future**: Rust services call each other directly (zero FFI overhead)

### 5. Python Integration Pattern

**Python Service Wrapper:**
```python
# mcpgateway/services/a2a_service.py
from typing import Optional, Dict, Any
import json

try:
    from mcpgateway_rust.services.a2a_service import invoke_agent as rust_invoke_agent
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

class A2AService:
    async def invoke_agent(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        body: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """Invoke A2A agent with automatic Rust acceleration."""
        if RUST_AVAILABLE:
            # Use Rust implementation
            headers_json = json.dumps(headers)
            result_json = rust_invoke_agent(url, method, headers_json, body)
            return json.loads(result_json)
        else:
            # Fallback to Python implementation
            return await self._invoke_agent_python(url, method, headers, body)
```

## Consequences

### Positive

- ✅ **Modular Architecture**: Each service is independently versioned and maintainable
- ✅ **Performance**: 10-50x improvement for I/O-bound operations by releasing GIL
- ✅ **Future Composability**: Pure Rust cores enable direct Rust-to-Rust service calls
- ✅ **Gradual Migration**: Services can be ported incrementally
- ✅ **Type Safety**: Rust's type system catches errors at compile time
- ✅ **Async Native**: Tokio provides efficient async I/O without GIL
- ✅ **Workspace Benefits**: Shared dependencies reduce compilation time
- ✅ **Clean Architecture**: PyO3 types isolated to thin FFI layer

### Negative

- ❌ **Complexity**: Two implementations to maintain (Rust + Python fallback)
- ❌ **Build Time**: Rust compilation adds to CI/CD duration
- ❌ **Copy Overhead**: Large data structures incur serialization cost
- ❌ **Learning Curve**: Team needs Rust and PyO3 expertise
- ❌ **Debugging**: Cross-language debugging is more complex
- ❌ **Binary Size**: Rust binaries increase package size (~5-10MB per service)

### Neutral

- 🔄 **GIL Strategy**: Requires careful analysis per operation
- 🔄 **Error Handling**: Need consistent error conversion between Rust and Python
- 🔄 **Testing**: Requires both Rust unit tests and Python integration tests

## Performance Characteristics

**Key Insights:**
- **GIL elimination is the primary win**
- Copy overhead is negligible compared to GIL benefit (even for 100KB)
- Concurrent workloads show dramatic improvement due to true parallelism
- Copy time is typically <1ms, while GIL-free I/O saves 10-100ms
- **Future**: Rust-to-Rust calls will be even faster (no FFI overhead at all)


## Data Type Guidelines

### Default: Use Rust Native Types (Copy)

```rust
// ✅ PREFERRED: Copy and release GIL for I/O
#[pyfunction]
fn invoke_agent(
    py: Python<'_>,
    url: String,              // Copy string
    method: String,           // Copy string
    headers_json: String,     // Copy headers
    body: Option<Vec<u8>>,    // Copy body
) -> PyResult<String> {
    let headers: HashMap<String, String> = serde_json::from_str(&headers_json)?;

    // Release GIL and delegate to pure Rust core
    py.allow_threads(|| {
        tokio_runtime.block_on(async {
            core::invoke_agent(&url, &method, &headers, body.as_deref()).await
        })
    })
}

// ✅ PREFERRED: Pure Rust core for future composability
pub mod core {
    pub async fn invoke_agent(
        url: &str,
        method: &str,
        headers: &HashMap<String, String>,
        body: Option<&[u8]>,
    ) -> Result<Value, Error> {
        // No Python types - can be called from other Rust services
    }
}
```

### Exception: Use PyO3 GIL Types (Sparingly)

Use PyO3 types only when:
1. **Very large data** (>1GB) - copy would exhaust memory
2. **Tight loops** (10K+ iterations) - accumulated copy overhead becomes significant

```rust
// ⚠️ RARE: Only when copy is prohibitively expensive
#[pyfunction]
fn process_huge_dataset(py: Python<'_>, data: &PyBytes) -> PyResult<()> {
    // data is 5GB - copying would exhaust memory
    // Must work with PyBytes directly (requires GIL)
    let bytes = data.as_bytes();
    // Process in chunks to minimize GIL hold time
}

// ⚠️ RARE: Tight loop with many iterations
#[pyfunction]
fn process_batch(py: Python<'_>, items: &PyList) -> PyResult<Vec<String>> {
    // 100K+ items - copying each would accumulate overhead
    let mut results = Vec::with_capacity(items.len());
    for item in items.iter() {
        // Direct access without copy per iteration
        let item_str = item.extract::<String>()?;
        results.push(process_item(&item_str)?);
    }
    Ok(results)
}

// ⚠️ RARE: Trivial pass-through (but copy is usually fine too)
#[pyfunction]
fn echo_string(s: &str) -> PyResult<String> {
    // So trivial that copy vs no-copy doesn't matter
    Ok(s.to_string())
}
```

**Note**: For loops with <1000 iterations and small items, copying is still preferred for GIL-free benefits.

### Anti-Patterns to Avoid

```rust
// ❌ WORST: Using PyO3 types for I/O (holds GIL)
#[pyfunction]
fn invoke_agent_bad(py: Python<'_>, url: &PyString) -> PyResult<PyObject> {
    let url_str = url.to_str()?;
    // TERRIBLE: Holding GIL during HTTP request!
    let response = tokio_runtime.block_on(make_request(url_str))?;
    Ok(response.into_py(py))
}

// ❌ BAD: PyO3 types in core logic (prevents Rust-to-Rust calls)
pub fn process_data(data: &PyDict) -> PyResult<()> {
    // TERRIBLE: Core logic depends on Python types
    // Cannot be called from other Rust services!
}

// ❌ BAD: Copying in tight loop (accumulated overhead)
#[pyfunction]
fn process_batch_bad(py: Python<'_>, items: Vec<String>) -> PyResult<Vec<String>> {
    let mut results = Vec::new();
    for item in items {  // Each iteration copies from Python
        // If items.len() > 10,000, accumulated copy overhead becomes significant
        results.push(process_item(&item)?);
    }
    Ok(results)
}

// ✅ CORRECT: Copy and use Rust types
#[pyfunction]
fn process_data_good(py: Python<'_>, data_json: String) -> PyResult<String> {
    let data: HashMap<String, Value> = serde_json::from_str(&data_json)?;
    py.allow_threads(|| {
        core::process_data(&data)  // Pure Rust core
    })
}

// ✅ CORRECT: Use PyO3 types for tight loops
#[pyfunction]
fn process_batch_good(py: Python<'_>, items: &PyList) -> PyResult<Vec<String>> {
    let mut results = Vec::with_capacity(items.len());
    for item in items.iter() {  // Direct access, no copy per iteration
        let item_str = item.extract::<String>()?;
        results.push(process_item(&item_str)?);
    }
    Ok(results)
}
```

## Alternatives Considered

| Alternative | Why Not |
|-------------|---------|
| **Pure PyO3 types everywhere** | GIL contention kills performance; prevents Rust-to-Rust composition |
| **Pure Rust types everywhere** | large object copies can slow down performance |
| **Separate binary processes** | IPC overhead higher than FFI; deployment complexity |
| **Cython instead of Rust** | Still GIL-bound; less ecosystem support for async |
| **Monolithic Rust crate** | Harder to maintain; all-or-nothing migration |
| **No workspace** | Duplicate dependencies; longer build times |

## Future Enhancements

### Planned Improvements

1. **Rust-to-Rust Service Composition**: Direct service calls without Python FFI
   ```rust
   // Future: Tool service calls A2A service directly
   let response = a2a_service::core::invoke_agent(url, headers).await?;
   ```
2. **Zero-Copy Buffers**: Use `pyo3::buffer::PyBuffer` for large binary data (when copy is prohibitive)
3. **Async PyO3**: Leverage `pyo3-asyncio` for native async/await integration
4. **Shared Memory**: Use `memmap2` for very large payloads (>10MB)
5. **SIMD Optimization**: Use `packed_simd` for bulk data processing
6. **Custom Allocators**: Use `jemalloc` for better memory efficiency

### Research Areas

- **Rust Async Traits**: Simplify async service interfaces
- **Cross-Language Profiling**: Better tools for identifying bottlenecks
- **Incremental Compilation**: Reduce Rust build times in CI/CD

## References

- [PyO3 User Guide](https://pyo3.rs/)
- [PyO3 Performance Guide](https://pyo3.rs/v0.28.0/performance)
- [Tokio Documentation](https://tokio.rs/)
- [Maturin Build Tool](https://www.maturin.rs/)
- ADR-001: Adopt FastAPI + Pydantic (Rust-core)
- ADR-038: Experimental Rust Transport Backend
- ADR-039: Adopt Fully Independent Plugin Crates Architecture

## Status

This decision is **proposed** for the A2A service. The architecture serves as the template for future Rust service implementations.

## Implementation Checklist

- [x] Workspace structure defined
- [x] A2A service implemented with hybrid data types
- [x] Python fallback mechanism
- [x] Build configuration (Maturin)
- [x] CI/CD integration
- [ ] Tool service migration (in progress)
- [ ] Resource service migration (planned)
- [ ] Performance benchmarking suite
- [ ] Documentation for service authors
