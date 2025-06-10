# Performance Testing

Use this guide to benchmark **MCP Gateway** under load, validate performance improvements, and identify bottlenecks before production deployment.

---

## ⚙️ Tooling: `hey`

[`hey`](https://github.com/rakyll/hey) is a CLI-based HTTP load generator. Install it with:

```bash
brew install hey            # macOS
sudo apt install hey        # Debian/Ubuntu
go install github.com/rakyll/hey@latest  # From source
```

---

## 🎯 Establishing a Baseline

Before benchmarking the full MCP Gateway stack, run tests against the **MCP server directly** (if applicable) to establish baseline latency and throughput. This helps isolate issues related to gateway overhead, authentication, or network I/O.

If your backend service exposes a direct HTTP interface or gRPC gateway, target it with `hey` using the same payload and concurrency settings.

```bash
hey -n 5000 -c 100 \
  -m POST \
  -T application/json \
  -D tests/hey/payload.json \
  http://localhost:5000/your-backend-endpoint
```

Compare the 95/99th percentile latencies and error rates with and without the gateway in front. Any significant increase can guide you toward:

* Bottlenecks in auth middleware
* Overhead from JSON-RPC wrapping/unwrapping
* Improper worker/thread config in Gunicorn

## 🚀 Scripted Load Tests: `tests/hey/hey.sh`

A wrapper script exists at:

```bash
tests/hey/hey.sh
```

This script provides:

* Strict error handling (`set -euo pipefail`)
* Helpful CLI interface (`-n`, `-c`, `-d`, etc.)
* Required dependency checks
* Optional dry-run mode
* Timestamped logging

Example usage:

```bash
./hey.sh -n 10000 -c 200 \
  -X POST \
  -T application/json \
  -H "Authorization: Bearer $JWT" \
  -d payload.json \
  -u http://localhost:4444/rpc
```

> The `payload.json` file is expected to be a valid JSON-RPC request payload.

Sample payload (`tests/hey/payload.json`):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "convert_time",
  "params": {
    "source_timezone": "Europe/Berlin",
    "target_timezone": "Europe/Dublin",
    "time": "09:00"
  }
}
```

Logs are saved automatically (e.g. `hey-20250610_120000.log`).

---

## 📊 Interpreting Results

When the test completes, look at:

| Metric             | Interpretation                                          |
| ------------------ | ------------------------------------------------------- |
| Requests/sec (RPS) | Raw throughput capability                               |
| 95/99th percentile | Tail latency — tune `timeout`, workers, or DB pooling   |
| Non-2xx responses  | Failures under load — common with CPU/memory starvation |

---

## 🧪 Tips & Best Practices

* Always test against a **realistic endpoint** (e.g. `POST /rpc` with auth and payload).
* Use the same JWT and payload structure your clients would.
* Run from a dedicated machine to avoid local CPU skewing results.
* Use `make run` or `make serve` to launch the app for local testing.

For runtime tuning details, see [Gateway Tuning Guide](../manage/tuning.md).

---
