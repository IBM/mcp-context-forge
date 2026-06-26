# **Design Document**

## **1\. Purpose**

The `ContainerScannerPlugin` provides pre-deployment container security validation.

It scans container images using Trivy or Grype before:

* `server_pre_register`  
* `runtime_pre_deploy`

The plugin enforces configurable security policies and may block deployment when violations are detected.

---

## **2\. Flow**

### **2.1 Flow**

Gateway

* **Hook Trigger**

   The gateway invokes the ContainerScannerPlugin during:

  * `server_pre_register`  
  * `runtime_pre_deploy`

---

ContainerScannerPlugin

* **Image Extraction**

   Extract `image_ref` from payload.

   Resolve `image_digest` if available (preferred for caching).

---

ContainerScannerPlugin

* **Cache Check**

   If caching is enabled:

  * Lookup scan result by `image_digest`  
  * If valid (TTL not expired) → reuse cached result  
  * Otherwise → continue to scanning

---

ContainerScannerPlugin

* **Registry Authentication Resolution**

   Determine if the image registry requires authentication.

  * If public → continue  
  * If private → resolve credentials from configuration and environment variables

---

ContainerScannerPlugin → ScannerRunner

* **Scanner Execution**  
  * If `scanner = trivy` → execute `TrivyRunner`  
  * If `scanner = grype` → execute `GrypeRunner`  
  * Enforce `timeout_seconds`  
  * Require JSON output

---

ScannerRunner → ContainerScannerPlugin

* **Result Collection**  
  * Collect raw JSON output  
  * Parse into unified `Vulnerability[]`

---

ContainerScannerPlugin

* **Policy Evaluation**  
  * Apply `severity_threshold`  
  * Remove `ignore_cves`  
  * Apply `fail_on_unfixed`  
  * Determine block/allow decision  
  * Distinguish scan failure vs policy violation

---

ContainerScannerPlugin

* **Result Persistence**  
  * Store scan results  
  * Store decision metadata  
  * Store scan\_error (if any)

---

ContainerScannerPlugin → Gateway

* **Result Propagation**  
  * Return `ScanResult`  
  * If enforce mode and violation → block workflow  
  * Otherwise → allow continuation

---

### **2.2 Call Flow**

```py
Gateway
  → ContainerScannerPlugin
      →extract_image(payload) → image_ref
      →resolve_digest(image_ref) → image_digest        #If image_digest not provided in context, scanner may resolve it internally and return it in result.
      → CacheManager.lookup(image_digest)
            → if valid →use cached_result
            → else continue
      → AuthResolver.resolve(image_ref)
      → ScannerRunner.run(image_ref, config, timeout)
            → raw_json
      → ParserNormalizer.normalize(raw_json) → vulnerabilities[]
      → PolicyEvaluator.evaluate(vulnerabilities, config) → decision
      → StorageLayer.save(scan_result)                #Always persist raw scan result first, Then persist decision metadata
      → return ScanResult
```

---

## **3\. Hook Integration**

### **Trigger Points**

* `server_pre_register`  
* `runtime_pre_deploy`

Both hooks use the same internal scan workflow.

---

## **4\. Core Responsibilities**

### **4.1 ContainerScannerPlugin (Orchestrator)**

Responsibilities:

* Extract image reference from payload  
* Handle cache lookup  
* Resolve registry authentication  
* Select scanner implementation  
* Normalize results  
* Apply policy evaluation  
* Persist scan results  
* Return allow/block decision

Talks to:

* `ScannerRunner`  
* `CacheManager`  
* `PolicyEvaluator`  
* `StorageLayer`

---

### **4.2 ScannerRunner (Interface)**

Abstract interface:

```py
run(image_ref: str,config:object,timeout_s:int) -> Vulnerability[]
```

Implementations:

* `TrivyRunner`  
* `GrypeRunner`

Responsibilities:

* Execute CLI  
* Enforce timeout  
* Parse JSON  
* Return normalized vulnerability objects

---

### **4.3 CacheManager**

Keyed by:

```py
image_digest
```

Responsibilities:

* Lookup cached results  
* Validate TTL  
* Store scan results

If cache is disabled → skip entirely.

---

### **4.4 PolicyEvaluator**

**Input:**

* vulnerabilities  
* severity\_threshold  
* ignore\_cves  
* fail\_on\_unfixed  
* mode (audit/enforce)

**Output:**

```py
{
  blocked:bool,
  reason?:str
}
```

**Logic**:

* Filter vulnerabilities ≥ threshold  
* Remove ignored CVEs  
* Apply fail\_on\_unfixed rule  
* If mode \= enforce and violation exists → blocked \= true

---

## **5\. Data Contracts**

### **5.1 Vulnerability (Unified Schema)**

```py
- scanner:"trivy" |"grype"
- cve_id:string
- severity:"CRITICAL" |"HIGH" |"MEDIUM" |"LOW"
- package_name:string
- installed_version:string
- fixed_version?:string
- description?:string
```

All scanners must normalize their output into this format.

---

### **5.2 ScanResult**

```py
-image_ref:string
-image_digest?:string
-scanners:string[]
-scan_time: datetime
-duration_ms:number
-vulnerabilities:Vulnerability[]
-summary:
    -critical_count:number
    -high_count:number
    -medium_count:number
    -low_count:number
-blocked:boolean
-reason?:string
-scan_error?:string
```

Important:

* `scan_error` distinguishes execution failure from policy violation.

---

## **6\. Configuration**

Example:

```py
scanner: trivy | grype
severity_threshold: CRITICAL | HIGH | MEDIUM | LOW
fail_on_unfixed:boolean
ignore_cves:string[]
timeout_seconds: number
mode: enforce | audit
cache_enabled:boolean
cache_ttl_hours: number
registries:
  - url:string
    auth_type: token | basic
    token_env?:string
    username_env?:string
    password_env?:string
```

---

## **7\. Failure Handling Strategy**

### **7.1 Scan Execution Failure**

Examples:

* CLI crash  
* Authentication failure  
* Timeout  
* Image not found

Recommended default:

```py
fail-closed (block deployment)            # This behavior applies only in enforce mode
```

Optional configuration:

```
on_scan_error: fail_closed | fail_open
```

---

### **7.2 Policy Violation**

Occurs when vulnerabilities meet configured threshold.

Handling:

* If mode \= enforce → block  
* If mode \= audit → allow but record

---

## **8\. Cache Strategy**

* Cache key: `image_digest`  
* Tag-based caching is NOT allowed, if image\_digest is unavailable, caching MUST be skipped.  
* TTL required due to CVE database updates  
* Cache optional but recommended

---

## **9\. Design Principles**

* Scanner-agnostic (Trivy/Grype interchangeable)  
* Digest-based identity  
* Clear separation:  
  * Execution errors  
  * Policy violations  
* Single orchestration layer  
* All scanner outputs normalized

---

## **10\. Suggest Structure**

Path: `plugins/container_scanner`

Structure:

```py
container_scanner/
│
├── __init__.py
│
├── container_scanner.py        # Plugin entry (hook integration)
├── config.py                   # Config model
├── types.py                    # Unified data models (Vulnerability, ScanResult)
│
├── cache/
│   ├── __init__.py
│   └── cache_manager.py        # Digest-based cache logic
│
├── auth/
│   ├── __init__.py
│   └── auth_resolver.py        # Registry auth resolution
│
├── scanners/
│   ├── __init__.py
│   ├── base.py                 # ScannerRunner interface
│   ├── trivy_runner.py
│   └── grype_runner.py
│
├── policy/
│   ├── __init__.py
│   └── policy_evaluator.py
│
└── storage/
    ├── __init__.py
    └── repository.py           # DB integration (if needed)
```

---

## **11\. Suggest Plan**

### **Week 1: Core Scanning Capabilities**

**Phase 1: Infrastructure (2-3 days)**

* Project structure setup (`container_scanner/` directory)  
* Config models & Types (Vulnerability, ScanResult)  
* Database schema

**Phase 2: Scanner Implementation (2-3 days)**

* ScannerRunner interface  
* TrivyRunner (CLI wrapper, JSON parsing)  
* GrypeRunner  
* Timeout & error handling

### **Week 2: Integration & Policies**

**Phase 3: Peripheral Components (2-3 days)**

* AuthResolver (registry authentication)  
* CacheManager (digest-based caching)  
* PolicyEvaluator (severity filtering, ignore list)

**Phase 4: Plugin Integration (2-3 days)**

* ContainerScannerPlugin main class  
* Hook integration (server\_pre\_register, runtime\_pre\_deploy)  
* Result persistence

**Phase 5: Testing & Polish (1-2 days)**

* Integration tests (real image scanning)  
* Admin UI (scan results display)  
* Documentation

---

### **Main Order**

\<aside\> 📝

Types/Config → TrivyRunner → PolicyEvaluator → Plugin ↓ CacheManager \+ AuthResolver

\</aside\>

# **Plugin Interface Alignment Document**

## **1\. Assessment Context Structure**

All plugins receive a standardized context from the Gateway:

```py
from dataclasses import dataclass
from typing import Optional

@dataclass
class AssessmentContext:
    """Context passed from Gateway to plugins"""
    assessment_id: str          # UUID generated by Gateway
    image_ref: str              # Full image reference
    image_digest: Optional[str] # Image digest (SHA256), if available
    # Extensible for future fields
```

**Example:**

```py
context = AssessmentContext(
    assessment_id="550e8400-e29b-41d4-a716-446655440000",
    image_ref="ghcr.io/myorg/myapp:v1.0.0",
    image_digest="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
)
```

---

## **2\. Image Reference Format**

### **2.1 image\_ref Format**

**Standard OCI format:**

`<registry>/<repository>:<tag>`

**Examples:**

* `ghcr.io/myorg/myapp:v1.0.0`  
* `docker.io/library/nginx:latest`  
* `gcr.io/my-project/service:main`

**Rules:**

* Must include registry (use `docker.io` for Docker Hub)  
* Repository can contain `/` (e.g., `library/nginx`, `org/team/app`)  
* Tag is required (default to `latest` if parsing user input)

### **2.2 image\_digest Format**

**Standard format:**

`sha256:<64-character-hex-string>`

**Example:**

`sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef`

**Validation:**

* Must start with `sha256:`  
* Total length: 71 characters (7 \+ 1 \+ 64\)  
* Hex characters only after colon

---

## **3\. Plugin Base Class**

All plugins must extend the base `Plugin` class:

```py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class PluginResult:
    """Result returned by plugin to Gateway"""
    blocked: bool                       # Whether to block deployment
    reason: Optional[str] = None        # Block reason (required if blocked=True)
    metadata: Optional[Dict[str, Any]] = None  # Additional data for logging/UI

class Plugin(ABC):
    """Base class for all security assessment plugins"""
    
    @abstractmethod
    def execute(self, context: AssessmentContext) -> PluginResult:
        """
        Execute plugin logic
        
        Args:
            context: Assessment context from Gateway
            
        Returns:
            PluginResult with block decision and metadata
        """
        pass
```

**Usage Example:**

```py
class ContainerScannerPlugin(Plugin):
    def execute(self, context: AssessmentContext) -> PluginResult:
        vulnerabilities = self.scan(context.image_ref)
        
        if self.has_critical_vulnerabilities(vulnerabilities):
            return PluginResult(
                blocked=True,
                reason="Found 3 CRITICAL vulnerabilities",
                metadata={"critical_count": 3, "high_count": 5}
            )
        
        return PluginResult(blocked=False)
```

---

## **4\. Configuration Standards**

### **4.1 Naming Conventions**

| Field Type | Convention | Example |
| ----- | ----- | ----- |
| Mode | `mode` | `"enforce"`, `"audit"`, `"disabled"` |
| Timeout | `timeout_seconds` | `300` |
| Environment Variable | `xxx_env` | `"GITHUB_TOKEN"` |
| Boolean Flag | `xxx_enabled` | `true`, `false` |

### **4.2 Standard Configuration Structure**

```py
plugins:
  - name: "PluginName"
    kind: "plugins.module.ClassName"
    hooks:
      - hook_name
    mode: "enforce"        # enforce | audit | disabled
    priority: 10           # Lower executes first
    
    config:
      # Timeout (always in seconds)
      timeout_seconds: 300
      
      # Environment variables (always _env suffix)
      token_env: "GITHUB_TOKEN"
      username_env: "DOCKER_USER"
      password_env: "DOCKER_PASS"
      
      # Boolean flags (always _enabled suffix)
      cache_enabled: true
      offline_enabled: false
      
      # Plugin-specific config
      # ...
```

**4.3 Mode Definitions**

* **`enforce`**: Block deployment if policy violated  
* **`audit`**: Log violations but allow deployment  
* **`disabled`**: Skip plugin execution

