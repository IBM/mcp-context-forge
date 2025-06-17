# fast-time-server

Ultra‑light MCP server in Go that exposes a single tool, `get_system_time(timezone)`, returning the current time in RFC 3339.

---

## Prerequisites

* **Go ≥ 1.22** ([https://go.dev/dl/](https://go.dev/dl/))

---

## Build

Use the provided `build.sh` helper:

```bash
./build.sh
```

<details>
<summary>What <code>build.sh</code> does</summary>

```bash
#!/usr/bin/env bash
set -euo pipefail

go mod tidy                       # ensure deps are synced
GOFLAGS="-trimpath -ldflags=-s -w" \
  go build -o fast-time-server .
```

</details>

---

## Run

```bash
npx -y supergateway \
  --stdio "./fast-time-server" \
  --port 8003
```

---


##  Benchmark

```
while :; do curl -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"get_system_time"}' \
     http://localhost:4444/rpc; done

# or
hey -n 100 -c 10 -m POST \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"get_system_time"}' \
  http://localhost:4444/rpc
```
