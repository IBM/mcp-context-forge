# 🛠 STDIO Wrapper (`mcpgateway.wrapper`)

`mcpgateway.wrapper` ships **inside** the main PyPI package and re-publishes
your Gateway's **tools / prompts / resources** over `stdin ↔ stdout`,
while connecting securely to the gateway using `SSE` + `JWT`.

> Perfect for clients that can't open SSE streams or attach JWT headers
> (e.g. **Claude Desktop**, **Cline**, **Continue**, custom CLI scripts).

---

## 🔑 Key Highlights

* **Dynamic catalog** - auto-syncs from one or more `.../servers/{id}` Virtual Server endpoints
* **Full MCP protocol** - `initialize`, `ping`, `tools/call`, streaming content, resources and prompts/template rendering
* **Transparent proxy** - stdio → Gateway → tool, results stream back to stdout
* **Secure** - wrapper keeps using your **JWT** to talk to the Gateway

---

## 🚀 Launch Options

Ensure you have a valid JWT token:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
      --username admin --exp 10080 --secret my-test-key)
```

Configure the wrapper via ENV variables:

```bash
export MCP_AUTH="Bearer ${MCPGATEWAY_BEARER_TOKEN}"
export MCP_SERVER_URL='http://localhost:4444/servers/UUID_OF_SERVER_1/mcp'  # select a virtual server
export MCP_TOOL_CALL_TIMEOUT=120          # tool call timeout in seconds (optional - default 90)
export MCP_WRAPPER_LOG_LEVEL=INFO         # DEBUG | INFO | OFF
```

Configure via Pip or Docker. Note that lauching the wrapper should be done from an MCP Client (ex: via the JSON configuration).

Launching it in your terminal (ex: `python3 -m mcpgateway.wrapper`) is useful for testing.

=== "Local shell (venv)"

    ```bash
    pip install mcp-contextforge-gateway
    python3 -m mcpgateway.wrapper
    ```

=== "Docker / Podman"

    ```bash
    docker run -i --rm --network=host \
      -e MCP_SERVER_URL=$MCP_SERVER_URL \
      -e MCP_AUTH=$MCP_AUTH \
      ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-1 \
      python3 -m mcpgateway.wrapper
    ```

=== "pipx (one-liner)"

    ```bash
    pipx install --include-deps mcp-contextforge-gateway
    MCP_AUTH=$MCP_AUTH \
    MCP_SERVER_URL=$MCP_SERVER_URL \
    python3 -m mcpgateway.wrapper
    ```

=== "uv / uvx (ultra-fast)"

    ```bash
    curl -Ls https://astral.sh/uv/install.sh | sh
    uv venv ~/.venv/mcpgw && source ~/.venv/mcpgw/bin/activate
    uv pip install mcp-contextforge-gateway
    uv python3 -m mcpgateway.wrapper
    ```

The wrapper now waits for JSON-RPC on **stdin** and emits replies on **stdout**.

---

## ✅ Environment Variables

| Variable                  | Purpose                                      | Default |
| ------------------------- | -------------------------------------------- | ------- |
| `MCP_SERVER_URL` | Comma-sep list of `/servers/{id}` endpoints  | -       |
| `MCP_AUTH`          | Bearer token the wrapper forwards to Gateway | -       |
| `MCP_TOOL_CALL_TIMEOUT`   | Per-tool timeout (seconds)                   | `90`    |
| `MCP_WRAPPER_LOG_LEVEL`   | `OFF`, `INFO`, `DEBUG`, ...                    | `INFO`  |

---

## 🖥 GUI Client Config JSON Snippets

You can run `mcpgateway.wrapper` from any MCP client, using either `python3`, `uv`, `uvx`, `uvx`, `pipx`, `docker`, or `podman` entrypoints.

The MCP Client calls the entrypoint, which needs to have the `mcp-contextforge-gateway` module installed, able to call `mcpgateway.wrapper` and the right `env` settings exported (`MCP_SERVER_URL` and `MCP_AUTH` at a minimum).

=== "Claude Desktop (venv)"

    ```json
    {
      "mcpServers": {
        "mcpgateway-wrapper": {
          "command": "python3",
          "args": ["-m", "mcpgateway.wrapper"],
          "env": {
            "MCP_AUTH": "Bearer <paste-token>",
            "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1"
          }
        }
      }
    }
    ```

    !!! tip "Use your venv's Python"
        Replace `/path/to/python` with the exact interpreter in your venv (e.g. `$HOME/.venv/mcpgateway/bin/python3`) - where the `mcp-contextforge-gateway` module is installed.


=== "Claude Desktop (uvx)"

    ```json
    {
      "mcpServers": {
        "mcpgateway-wrapper": {
          "command": "uvx",
          "args": [
            "run",
            "--",
            "python",
            "-m",
            "mcpgateway.wrapper"
          ],
          "env": {
            "MCP_AUTH": "Bearer <paste-token>",
            "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1"
          }
        }
      }
    }
    ```

=== "Continue (python3)"

    Add to **Settings → Continue: MCP Servers**:

    ```json
    {
      "mcpgateway-wrapper": {
        "command": "/path/to/python",
        "args": ["-m", "mcpgateway.wrapper"],
        "env": {
          "MCP_AUTH": "Bearer <token>",
          "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1"
        }
      }
    }
    ```

    *(Replace `/path/to/python` with your venv interpreter.)*

=== "Cline (uv)"

    ```json
    {
      "mcpServers": {
        "mcpgateway-wrapper": {
          "disabled": false,
          "timeout": 60,
          "type": "stdio",
          "command": "uv",
          "args": [
            "run",
            "--directory",
            "REPLACE_WITH_PATH_TO_REPO",
            "-m",
            "mcpgateway.wrapper"
          ],
          "env": {
            "MCP_SERVER_URL": "http://localhost:4444/servers/UUID_OF_SERVER_1",
            "MCP_AUTH": "Bearer REPLACE_WITH_MCPGATEWAY_BEARER_TOKEN",
            "MCP_WRAPPER_LOG_LEVEL": "OFF"
          }
        }
      }
    }
    ```

---

## 🐍 Local Development

```bash
# Hot-reload wrapper code while hacking
uv --dev run python3 -m mcpgateway.wrapper
```

### 🔎 MCP Inspector

```bash
npx @modelcontextprotocol/inspector \
     python3 -m mcpgateway.wrapper -- \
     --log-level DEBUG
```

---

## 📝 Example call flow

```json
{
  "method": "get_system_time",
  "params": { "timezone": "Europe/Dublin" }
}
```

1. Wrapper maps `get_system_time` → tool ID 123 in the catalog.
2. Sends RPC to the Gateway with your JWT token.
3. Gateway executes the tool and returns JSON → wrapper → stdout.

---

## 🧪 Manual JSON-RPC Smoke-test

The wrapper speaks plain JSON-RPC over **stdin/stdout**, so you can exercise it from any
terminal-no GUI required.
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
     "params":{"name":"get_system_time","arguments":{"timezone":"Europe/Dublin"}}}
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
      "serverInfo":{"name":"mcpgateway-wrapper","version":"0.9.0"}
    }}

    # Empty tool list
    {"jsonrpc":"2.0","id":2,"result":{"tools":[]}}

    # ...after adding tools (example)
    {"jsonrpc":"2.0","id":2,"result":{
      "tools":[
        {
          "name":"get_system_time",
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
