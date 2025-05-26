# Logging

MCP Gateway emits structured logs that can be viewed locally or forwarded to a log aggregation service. This guide shows how to configure log levels, formats, and destinations.

---

## 🧾 Log Structure

Logs are emitted in JSON or text format, depending on your configuration.

Example (JSON format):

```json
{
  "timestamp": "2025-05-15T10:32:10Z",
  "level": "INFO",
  "module": "gateway_service",
  "message": "Registered gateway: peer-gateway-1"
}
```

---

## 🔧 Configuring Logs

You can control logging behavior using `.env` settings:

| Variable     | Description                     | Example                   |
| ------------ | ------------------------------- | ------------------------- |
| `LOG_LEVEL`  | Minimum log level               | `INFO`, `DEBUG`, `ERROR`  |
| `LOG_FORMAT` | Log output format               | `json` or `text`          |
| `LOG_FILE`   | Write logs to a file (optional) | `/var/log/mcpgateway.log` |

---

## 📡 Streaming Logs (Containers)

```bash
docker logs -f mcpgateway
# or with Podman
podman logs -f mcpgateway
```

---

## 📤 Shipping Logs to External Services

MCP Gateway can write to stdout or a file. To forward logs to services like:

* **ELK (Elastic Stack)**
* **LogDNA / IBM Log Analysis**
* **Datadog**
* **Fluentd / Loki**

You can:

* Mount log files to a sidecar container
* Use a logging agent (e.g., Filebeat)
* Pipe logs to syslog-compatible services

---

## 🧪 Debug Mode

For development, enable verbose logs by setting:

```env
LOG_LEVEL=debug
LOG_FORMAT=text
DEBUG=true
```

This enables detailed request traces and internal service logs.

---
