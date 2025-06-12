# STDIO Wrapper

`mcpgateway.wrapper` is a lightweight **MCP-compatible stdio server** shipped **inside the main
package** (`mcp-contextforge-gateway`).
It mirrors the tools, prompts and resources that live in an MCP Gateway catalog and re-publishes
them via stdin/stdout so that any MCP client — **even those without SSE support or JWT headers** —
can call them locally (e.g. Claude Desktop, Cline, Continue).

---

## 🔑 Key Features

* **Dynamic tool discovery** – automatically pulls the latest catalog from one or more
  `…/servers/{id}` endpoints.
* **Centralised gateway bridge** – everything behind a single stdio interface.
* **Full MCP protocol** – responds to `initialize`, `ping`, `notify`, `complete`,
  `createMessage`, etc.
* **Transparent tool proxy** – wrapper → Gateway HTTP RPC → tool; results stream back to stdout.
* **Extensible** – prompt & resource support landed; further features (federation fallback,
  token caching) on the roadmap.

---

## ⚙️ Components

| Component | Status | Notes |
|-----------|--------|-------|
| Tools     | ✅ Live | Mirrored 1-to-1 from the catalog |
| Resources | ✅ Live | Read-only fetch via MCP Gateway |
| Prompts   | ✅ Live | Template rendering & argument injection |

---

## 🚀 Quick Start – Local shell

```bash
# 1 · Install the gateway (or use pipx/uv/venv as you prefer)
pip install mcp-contextforge-gateway        # or: pipx install … / uv pip install …

# 2 · Create / export a bearer token so the wrapper can reach the Gateway
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
        --username admin --exp 10080 --secret my-test-key)

# 3 · Tell the wrapper where the catalog lives & how to auth
export MCP_AUTH_TOKEN=${MCPGATEWAY_BEARER_TOKEN}
export MCP_SERVER_CATALOG_URLS='http://localhost:4444/servers/1'
export MCP_TOOL_CALL_TIMEOUT=120          # seconds (optional – default 90)
export MCP_WRAPPER_LOG_LEVEL=INFO         # DEBUG | INFO | OFF

# 4 · Launch!
python3 -m mcpgateway.wrapper
```

The wrapper now waits for JSON-RPC traffic on **stdin** and emits replies on **stdout**.

---

### 🔄 Other launch methods

<details>
<summary><strong>🐳 Docker / Podman</strong></summary>

```bash
docker run -i --rm \
  --network=host \
  -e MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1 \
  -e MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN \
  ghcr.io/ibm/mcp-context-forge:latest \
  python3 -m mcpgateway.wrapper
```

</details>

<details>
<summary><strong>📦 pipx</strong> (one-liner install &amp; run)</summary>

```bash
pipx install --include-deps mcp-contextforge-gateway
MCP_AUTH_TOKEN=$MCPGATEWAY_BEARER_TOKEN \
MCP_SERVER_CATALOG_URLS=http://localhost:4444/servers/1 \
python3 -m mcpgateway.wrapper
```

</details>

<details>
<summary><strong>⚡ uv / uvenv</strong></summary>

```bash
curl -Ls https://astral.sh/uv/install.sh | sh          # installs uv + uvenv
uv venv ~/.venv/mcpgw && source ~/.venv/mcpgw/bin/activate
uv pip install mcp-contextforge-gateway
uv python -m mcpgateway.wrapper
```

</details>

---

### ✅ Environment Variables

| Variable                  | Purpose                                              | Default |
| ------------------------- | ---------------------------------------------------- | ------- |
| `MCP_SERVER_CATALOG_URLS` | Comma-separated list of `/servers/{id}` catalog URLs | —       |
| `MCP_AUTH_TOKEN`          | Bearer token that the wrapper sends to the Gateway   | —       |
| `MCP_TOOL_CALL_TIMEOUT`   | Per-tool call timeout (seconds)                      | `90`    |
| `MCP_WRAPPER_LOG_LEVEL`   | Wrapper log level (`OFF`, `INFO`, `DEBUG`…)          | `INFO`  |

---

## 🐍 Local Development

```bash
# Hot-reload wrapper code while hacking
uv --dev run python -m mcpgateway.wrapper
```

### 🔎 MCP Inspector

```bash
npx @modelcontextprotocol/inspector \
     python -m mcpgateway.wrapper -- \
     --log-level DEBUG
```

---

## 📝 Example call flow

```json
{
  "method": "get_current_time",
  "params": { "timezone": "Europe/Dublin" }
}
```

1. Wrapper maps `get_current_time` → tool ID 123 in the catalog.
2. Sends RPC to the Gateway with your JWT token.
3. Gateway executes the tool and returns JSON → wrapper → stdout.

---

## 🛠 Using from GUI clients (Claude Desktop example)

Open **File → Settings → Developer → Edit Config** and add:

```json
{
  "mcpServers": {
    "mcpgateway-wrapper": {
      "command": "python3",
      "args": ["-m", "mcpgateway.wrapper"],
      "env": {
        "MCP_AUTH_TOKEN": "<paste-your-token>",
        "MCP_SERVER_CATALOG_URLS": "http://localhost:4444/servers/1"
      }
    }
  }
}
```

Restart the app; the wrapper will appear in the tool list.

---

## 🧪 Manual JSON-RPC Smoke-test

The wrapper speaks plain JSON-RPC over **stdin/stdout**, so you can exercise it from any
terminal—no GUI required.
Open two shells or use a tool like `jq -c | nc -U` to pipe messages in and view replies.

??? example "Step-by-step request sequence"
    ```json
    # 1️⃣ Initialize session
    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},
      "clientInfo":{"name":"demo","version":"0.0.1"}
    }}

    # 2️⃣ Ack initialisation (required by MCP)
    {"jsonrpc":"2.0","method":"notifications/initialized","params":{}}

    # 3️⃣ Prompts
    {"jsonrpc":"2.0","id":4,"method":"prompts/list"}
    {"jsonrpc":"2.0","id":5,"method":"prompts/get",
     "params":{"name":"greeting","arguments":{"user":"Bob"}}}

    # 4️⃣ Resources
    {"jsonrpc":"2.0","id":6,"method":"resources/list"}
    {"jsonrpc":"2.0","id":7,"method":"resources/read",
     "params":{"uri":"https://example.com/some.txt"}}

    # 5️⃣ Tools (list / call)
    {"jsonrpc":"2.0","id":2,"method":"tools/list"}
    {"jsonrpc":"2.0","id":3,"method":"tools/call",
     "params":{"name":"get_current_time","arguments":{"timezone":"Europe/Dublin"}}}
    ```

??? success "Sample responses you should see"
    ```json
    # Initialise
    {"jsonrpc":"2.0","id":1,"result":{
      "protocolVersion":"2025-03-26",
      "capabilities":{
        "experimental":{},
        "prompts":{"listChanged":false},
        "resources":{"subscribe":false,"listChanged":false},
        "tools":{"listChanged":false}
      },
      "serverInfo":{"name":"mcpgateway-wrapper","version":"0.1.0"}
    }}

    # Empty tool list
    {"jsonrpc":"2.0","id":2,"result":{"tools":[]}}

    # …after adding tools (example)
    {"jsonrpc":"2.0","id":2,"result":{
      "tools":[
        {
          "name":"get_current_time",
          "description":"Get current time in a specific timezone",
          "inputSchema":{
            "type":"object",
            "properties":{
              "timezone":{
                "type":"string",
                "description":"IANA timezone name (e.g. 'Europe/London')."
              }
            },
            "required":["timezone"]
          }
        }
      ]
    }}

    # Tool invocation
    {"jsonrpc":"2.0","id":3,"result":{
      "content":[
        {
          "type":"text",
          "text":"{ \"timezone\": \"Europe/Dublin\", \"datetime\": \"2025-06-08T21:47:07+01:00\", \"is_dst\": true }"
        }
      ],
      "isError":false
    }}
    ```

---

## 🔮 Planned Roadmap

* OAuth2 / OIDC token refresh
* Automatic reconnection & retry on Gateway outage
* Advanced prompt piping / streaming
