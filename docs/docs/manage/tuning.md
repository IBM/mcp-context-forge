# Gateway Tuning Guide

> This page collects practical levers for squeezing the most performance, reliability, and observability out of **MCP Gateway**—no matter where you run the container (Code Engine, Kubernetes, Docker Compose, Nomad, etc.).
>
> **TL;DR**
>
> 1. Tune the **runtime environment** via `.env` and configure mcpgateway to use PostgreSQL and Redis.
> 2. Adjust **Gunicorn** workers & time‑outs in `gunicorn.conf.py`.
> 3. Right‑size **CPU/RAM** for the container or spin up more instances (with shared Redis state).
> 4. Benchmark with **hey** (or your favourite load‑generator) before & after.

---

## 1 · Environment variables (`.env`)

|  Variable        |  Default       |  Why you might change it                                                            |
| ---------------- | -------------- | ----------------------------------------------------------------------------------- |
| `AUTH_REQUIRED`  | `true`         | Disable for internal/behind‑VPN deployments to shave a few ms per request.          |
| `JWT_SECRET_KEY` | random         | Longer key ➜ slower HMAC verify; still negligible—leave as is.                      |
| `CACHE_TYPE`     | `database`     | Switch to `redis` or `memory` if your workload is read‑heavy and latency‑sensitive. |
| `DATABASE_URL`   | SQLite         | Move to managed PostgreSQL + connection pooling for anything beyond dev tests.      |
| `HOST`/`PORT`    | `0.0.0.0:4444` | Expose a different port or bind only to `127.0.0.1` behind a reverse‑proxy.         |

> **Tip**  Any change here requires rebuilding or restarting the container if you pass the file with `--env‑file`.

---

## 2 · Gunicorn settings (`gunicorn.conf.py`)

|  Knob                    |  Purpose            |  Rule of thumb                                                    |
| ------------------------ | ------------------- | ----------------------------------------------------------------- |
| `workers`                | Parallel processes  | `2–4 × vCPU` for CPU‑bound work; fewer if memory‑bound.           |
| `threads`                | Per‑process threads | Use only with `sync` worker; keeps memory low for I/O workloads.  |
| `timeout`                | Kill stuck worker   | Set ≥ end‑to‑end model latency. E.g. 600 s for LLM calls.         |
| `preload_app`            | Load app once       | Saves RAM; safe for pure‑Python apps.                             |
| `worker_class`           | Async workers       | `gevent` or `eventlet` for many concurrent requests / websockets. |
| `max_requests(+_jitter)` | Self‑healing        | Recycle workers to mitigate memory leaks.                         |

Edit the file **before** building the image, then redeploy.

---

## 3 · Container resources

| vCPU × RAM   | Good for              | Notes                                              |
| ------------ | --------------------- | -------------------------------------------------- |
| `0.5 × 1 GB` | Smoke tests / CI      | Smallest footprint; likely CPU‑starved under load. |
| `1 × 4 GB`   | Typical dev / staging | Handles a few hundred RPS with default 8 workers.  |
| `2 × 8 GB`   | Small prod            | Allows \~16–20 workers; good concurrency.          |
| `4 × 16 GB`+ | Heavy prod            | Combine with async workers or autoscaling.         |

> Always test with **your** workload; JSON‑RPC payload size and backend model latency change the equation.

---

## 4 · Performance testing

### 4.1 Tooling: **hey**

Install one of:

```bash
brew install hey            # macOS
sudo apt install hey         # Debian/Ubuntu
# or build from source
go install github.com/rakyll/hey@latest  # $GOPATH/bin must be in PATH
```

### 4.2 Sample load‑test script (`tests/hey.sh`)

```bash
#!/usr/bin/env bash
# Run 10 000 requests with 200 concurrent workers.
JWT="$(cat jwt.txt)"   # <- place a valid token here
hey -n 10000 -c 200 \
    -m POST \
    -T application/json \
    -H "Authorization: Bearer ${JWT}" \
    -D tests/hey/payload.json \
    http://localhost:4444/rpc
```

**Payload (`tests/hey/payload.json`)**

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

### 4.3 Reading the output

`hey` prints latency distribution, requests/second, and error counts. Focus on:

* **99th percentile latency** – adjust `timeout` if it clips.
* **Errors** – 5xx under load often mean too few workers or DB connections.
* **Throughput (RPS)** – compare before/after tuning.

### 4.4 Common bottlenecks & fixes

| Symptom                  | Likely cause                        | Mitigation                                                 |
| ------------------------ | ----------------------------------- | ---------------------------------------------------------- |
| High % of 5xx under load | Gunicorn workers exhausted          | Increase `workers`, switch to async workers, raise CPU.    |
| Latency > timeout        | Long model call / external API      | Increase `timeout`, add queueing, review upstream latency. |
| Memory OOM               | Too many workers / large batch size | Lower `workers`, disable `preload_app`, add RAM.           |

---

## 5 · Logging & observability

* Set `loglevel = "debug"` in `gunicorn.conf.py` during tests; revert to `info` in prod.
* Forward `stdout`/`stderr` from the container to your platform’s log stack (e.g. `kubectl logs`, `docker logs`).
* Expose `/metrics` via Prometheus exporter (coming soon) for request timing & queue depth.

---

## 6 · Security tips while tuning

* Never commit real `JWT_SECRET_KEY`, DB passwords, or tokens—use `.env.example` as a template.
* Prefer platform secrets (K8s Secrets, Code Engine secrets) over baking creds into the image.
* If you enable `gevent`/`eventlet`, pin their versions and run **bandit** or **trivy** scans.

---
