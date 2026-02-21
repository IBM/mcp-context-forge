# AutoGen Integration with ContextForge

[AutoGen](https://github.com/microsoft/autogen) is an open-source framework from Microsoft for building multi-agent systems. It supports tool calling and dynamic agent coordination.

---

## 🔧 MCP Support

Experimental support for MCP integration is available via custom `ToolAgent` wrappers that call MCP tools via HTTP or `mcpgateway-wrapper`.

Minimal example using HTTP JSON-RPC with `requests`:

```python
import os
import requests

GATEWAY = os.getenv("GATEWAY", "http://localhost:4444")
TOKEN = os.getenv("MCPGATEWAY_BEARER_TOKEN")

def call_tool(name: str, arguments: dict):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    r = requests.post(f"{GATEWAY}/rpc", json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

# Example usage inside an AutoGen tool wrapper
result = call_tool("get_system_time", {"timezone": "Europe/Dublin"})
print(result)
```

For stdio-based integration, launch `mcpgateway-wrapper` and connect AutoGen via a subprocess bridge.

---

## 🔗 Resources

- [AutoGen GitHub](https://github.com/microsoft/autogen)
- [AutoGen Docs](https://microsoft.github.io/autogen)
