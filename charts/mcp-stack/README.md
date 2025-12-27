# mcp-stack

![Version: 1.0.0-BETA-1](https://img.shields.io/badge/Version-1.0.0--BETA--1-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.0.0-BETA-1](https://img.shields.io/badge/AppVersion-1.0.0--BETA--1-informational?style=flat-square)

A full-stack Helm chart for IBM's **Model Context Protocol (MCP) Gateway
& Registry - Context-Forge**.  It bundles:
  - MCP Gateway application (HTTP / WebSocket server)
  - PostgreSQL database with persistent storage
  - Optional PgBouncer connection pooler for high concurrency
  - Redis cache for sessions & completions
  - Optional PgAdmin and Redis-Commander web UIs

**Homepage:** <https://github.com/IBM/mcp-context-forge>

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| Mihai Criveti |  | <https://github.com/IBM> |

## Source Code

* <https://github.com/IBM/mcp-context-forge>

## Requirements

Kubernetes: `>=1.21.0-0`

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| global.fullnameOverride | string | `""` |  |
| global.imagePullSecrets | list | `[]` |  |
| global.nameOverride | string | `""` |  |
| mcpContextForge.config.ALLOWED_ORIGINS | string | `"[\"http://localhost\",\"http://localhost:4444\"]"` |  |
| mcpContextForge.config.APP_DOMAIN | string | `"http://localhost"` |  |
| mcpContextForge.config.APP_NAME | string | `"MCP_Gateway"` |  |
| mcpContextForge.config.APP_ROOT_PATH | string | `""` |  |
| mcpContextForge.config.CACHE_PREFIX | string | `"mcpgw:"` |  |
| mcpContextForge.config.CACHE_TYPE | string | `"redis"` |  |
| mcpContextForge.config.COOKIE_SAMESITE | string | `"lax"` |  |
| mcpContextForge.config.CORS_ALLOW_CREDENTIALS | string | `"true"` |  |
| mcpContextForge.config.CORS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.DB_MAX_OVERFLOW | string | `"10"` |  |
| mcpContextForge.config.DB_MAX_RETRIES | string | `"3"` |  |
| mcpContextForge.config.DB_POOL_RECYCLE | string | `"3600"` |  |
| mcpContextForge.config.DB_POOL_SIZE | string | `"200"` |  |
| mcpContextForge.config.DB_POOL_TIMEOUT | string | `"30"` |  |
| mcpContextForge.config.DB_RETRY_INTERVAL_MS | string | `"2000"` |  |
| mcpContextForge.config.DEBUG | string | `"false"` |  |
| mcpContextForge.config.DEFAULT_PASSTHROUGH_HEADERS | string | `"[\"X-Tenant-Id\", \"X-Trace-Id\"]"` |  |
| mcpContextForge.config.DEFAULT_ROOTS | string | `"[]"` |  |
| mcpContextForge.config.DEV_MODE | string | `"false"` |  |
| mcpContextForge.config.DISABLE_ACCESS_LOG | string | `"true"` |  |
| mcpContextForge.config.ENABLE_HEADER_PASSTHROUGH | string | `"false"` |  |
| mcpContextForge.config.ENABLE_METRICS | string | `"true"` |  |
| mcpContextForge.config.ENABLE_OVERWRITE_BASE_HEADERS | string | `"false"` |  |
| mcpContextForge.config.ENVIRONMENT | string | `"development"` |  |
| mcpContextForge.config.FEDERATION_DISCOVERY | string | `"false"` |  |
| mcpContextForge.config.FEDERATION_ENABLED | string | `"true"` |  |
| mcpContextForge.config.FEDERATION_PEERS | string | `"[]"` |  |
| mcpContextForge.config.FEDERATION_SYNC_INTERVAL | string | `"300"` |  |
| mcpContextForge.config.FEDERATION_TIMEOUT | string | `"120"` |  |
| mcpContextForge.config.FILELOCK_NAME | string | `"gateway_healthcheck_init.lock"` |  |
| mcpContextForge.config.GATEWAY_MODEL | string | `"gpt-4o"` |  |
| mcpContextForge.config.GATEWAY_TEMPERATURE | string | `"0.7"` |  |
| mcpContextForge.config.GATEWAY_TOOL_NAME_SEPARATOR | string | `"-"` |  |
| mcpContextForge.config.GATEWAY_VALIDATION_TIMEOUT | string | `"5"` |  |
| mcpContextForge.config.GLOBAL_CONFIG_CACHE_TTL | string | `"60"` |  |
| mcpContextForge.config.GUNICORN_DEV_MODE | string | `"false"` |  |
| mcpContextForge.config.GUNICORN_MAX_REQUESTS | string | `"100000"` |  |
| mcpContextForge.config.GUNICORN_MAX_REQUESTS_JITTER | string | `"100"` |  |
| mcpContextForge.config.GUNICORN_PRELOAD_APP | string | `"true"` |  |
| mcpContextForge.config.GUNICORN_TIMEOUT | string | `"600"` |  |
| mcpContextForge.config.GUNICORN_WORKERS | string | `"auto"` |  |
| mcpContextForge.config.HEALTH_CHECK_INTERVAL | string | `"60"` |  |
| mcpContextForge.config.HEALTH_CHECK_TIMEOUT | string | `"10"` |  |
| mcpContextForge.config.HOST | string | `"0.0.0.0"` |  |
| mcpContextForge.config.HSTS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.HSTS_INCLUDE_SUBDOMAINS | string | `"true"` |  |
| mcpContextForge.config.HSTS_MAX_AGE | string | `"31536000"` |  |
| mcpContextForge.config.JSON_RESPONSE_ENABLED | string | `"true"` |  |
| mcpContextForge.config.LLMCHAT_ENABLED | string | `"false"` |  |
| mcpContextForge.config.LLM_API_PREFIX | string | `"/v1"` |  |
| mcpContextForge.config.LLM_HEALTH_CHECK_INTERVAL | string | `"300"` |  |
| mcpContextForge.config.LLM_REQUEST_TIMEOUT | string | `"120"` |  |
| mcpContextForge.config.LLM_STREAMING_ENABLED | string | `"true"` |  |
| mcpContextForge.config.LOG_BACKUP_COUNT | string | `"5"` |  |
| mcpContextForge.config.LOG_BUFFER_SIZE_MB | string | `"1.0"` |  |
| mcpContextForge.config.LOG_FILE | string | `""` |  |
| mcpContextForge.config.LOG_FILEMODE | string | `"a+"` |  |
| mcpContextForge.config.LOG_FOLDER | string | `""` |  |
| mcpContextForge.config.LOG_FORMAT | string | `"json"` |  |
| mcpContextForge.config.LOG_LEVEL | string | `"INFO"` |  |
| mcpContextForge.config.LOG_MAX_SIZE_MB | string | `"1"` |  |
| mcpContextForge.config.LOG_REQUESTS | string | `"false"` |  |
| mcpContextForge.config.LOG_ROTATION_ENABLED | string | `"false"` |  |
| mcpContextForge.config.LOG_TO_FILE | string | `"false"` |  |
| mcpContextForge.config.MAX_PROMPT_SIZE | string | `"102400"` |  |
| mcpContextForge.config.MAX_RESOURCE_SIZE | string | `"10485760"` |  |
| mcpContextForge.config.MAX_TOOL_RETRIES | string | `"3"` |  |
| mcpContextForge.config.MCPGATEWAY_A2A_DEFAULT_TIMEOUT | string | `"30"` |  |
| mcpContextForge.config.MCPGATEWAY_A2A_ENABLED | string | `"true"` |  |
| mcpContextForge.config.MCPGATEWAY_A2A_MAX_AGENTS | string | `"100"` |  |
| mcpContextForge.config.MCPGATEWAY_A2A_MAX_RETRIES | string | `"3"` |  |
| mcpContextForge.config.MCPGATEWAY_A2A_METRICS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.MCPGATEWAY_ADMIN_API_ENABLED | string | `"true"` |  |
| mcpContextForge.config.MCPGATEWAY_BULK_IMPORT_ENABLED | string | `"true"` |  |
| mcpContextForge.config.MCPGATEWAY_BULK_IMPORT_MAX_TOOLS | string | `"200"` |  |
| mcpContextForge.config.MCPGATEWAY_BULK_IMPORT_RATE_LIMIT | string | `"10"` |  |
| mcpContextForge.config.MCPGATEWAY_CATALOG_AUTO_HEALTH_CHECK | string | `"true"` |  |
| mcpContextForge.config.MCPGATEWAY_CATALOG_CACHE_TTL | string | `"3600"` |  |
| mcpContextForge.config.MCPGATEWAY_CATALOG_ENABLED | string | `"true"` |  |
| mcpContextForge.config.MCPGATEWAY_CATALOG_FILE | string | `"mcp-catalog.yml"` |  |
| mcpContextForge.config.MCPGATEWAY_CATALOG_PAGE_SIZE | string | `"100"` |  |
| mcpContextForge.config.MCPGATEWAY_UI_AIRGAPPED | string | `"false"` |  |
| mcpContextForge.config.MCPGATEWAY_UI_ENABLED | string | `"true"` |  |
| mcpContextForge.config.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT | string | `"60000"` |  |
| mcpContextForge.config.MESSAGE_TTL | string | `"600"` |  |
| mcpContextForge.config.METRICS_BUFFER_ENABLED | string | `"true"` |  |
| mcpContextForge.config.METRICS_BUFFER_FLUSH_INTERVAL | string | `"60"` |  |
| mcpContextForge.config.METRICS_BUFFER_MAX_SIZE | string | `"1000"` |  |
| mcpContextForge.config.METRICS_CUSTOM_LABELS | string | `""` |  |
| mcpContextForge.config.METRICS_EXCLUDED_HANDLERS | string | `""` |  |
| mcpContextForge.config.METRICS_NAMESPACE | string | `"default"` |  |
| mcpContextForge.config.METRICS_SUBSYSTEM | string | `""` |  |
| mcpContextForge.config.OBSERVABILITY_ENABLED | string | `"false"` |  |
| mcpContextForge.config.OBSERVABILITY_EVENTS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.OBSERVABILITY_EXCLUDE_PATHS | string | `"[\"/health\", \"/healthz\", \"/ready\", \"/metrics\", \"/static/.*\"]"` |  |
| mcpContextForge.config.OBSERVABILITY_MAX_TRACES | string | `"100000"` |  |
| mcpContextForge.config.OBSERVABILITY_METRICS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.OBSERVABILITY_SAMPLE_RATE | string | `"1.0"` |  |
| mcpContextForge.config.OBSERVABILITY_TRACE_HTTP_REQUESTS | string | `"true"` |  |
| mcpContextForge.config.OBSERVABILITY_TRACE_RETENTION_DAYS | string | `"7"` |  |
| mcpContextForge.config.OTEL_BSP_MAX_EXPORT_BATCH_SIZE | string | `"512"` |  |
| mcpContextForge.config.OTEL_BSP_MAX_QUEUE_SIZE | string | `"2048"` |  |
| mcpContextForge.config.OTEL_BSP_SCHEDULE_DELAY | string | `"5000"` |  |
| mcpContextForge.config.OTEL_ENABLE_OBSERVABILITY | string | `"false"` |  |
| mcpContextForge.config.OTEL_EXPORTER_OTLP_INSECURE | string | `"true"` |  |
| mcpContextForge.config.OTEL_EXPORTER_OTLP_PROTOCOL | string | `"grpc"` |  |
| mcpContextForge.config.OTEL_SERVICE_NAME | string | `"mcp-gateway"` |  |
| mcpContextForge.config.OTEL_TRACES_EXPORTER | string | `"otlp"` |  |
| mcpContextForge.config.PAGINATION_BASE_URL | string | `""` |  |
| mcpContextForge.config.PAGINATION_COUNT_CACHE_TTL | string | `"300"` |  |
| mcpContextForge.config.PAGINATION_CURSOR_ENABLED | string | `"true"` |  |
| mcpContextForge.config.PAGINATION_CURSOR_THRESHOLD | string | `"10000"` |  |
| mcpContextForge.config.PAGINATION_DEFAULT_PAGE_SIZE | string | `"50"` |  |
| mcpContextForge.config.PAGINATION_DEFAULT_SORT_FIELD | string | `"created_at"` |  |
| mcpContextForge.config.PAGINATION_DEFAULT_SORT_ORDER | string | `"desc"` |  |
| mcpContextForge.config.PAGINATION_INCLUDE_LINKS | string | `"true"` |  |
| mcpContextForge.config.PAGINATION_MAX_OFFSET | string | `"100000"` |  |
| mcpContextForge.config.PAGINATION_MAX_PAGE_SIZE | string | `"500"` |  |
| mcpContextForge.config.PAGINATION_MIN_PAGE_SIZE | string | `"1"` |  |
| mcpContextForge.config.PLUGINS_CLI_COMPLETION | string | `"false"` |  |
| mcpContextForge.config.PLUGINS_CLI_MARKUP_MODE | string | `"rich"` |  |
| mcpContextForge.config.PLUGINS_ENABLED | string | `"false"` |  |
| mcpContextForge.config.PLUGINS_MTLS_CA_BUNDLE | string | `""` |  |
| mcpContextForge.config.PLUGINS_MTLS_CHECK_HOSTNAME | string | `"true"` |  |
| mcpContextForge.config.PLUGINS_MTLS_CLIENT_CERT | string | `""` |  |
| mcpContextForge.config.PLUGINS_MTLS_CLIENT_KEY | string | `""` |  |
| mcpContextForge.config.PLUGINS_MTLS_CLIENT_KEY_PASSWORD | string | `""` |  |
| mcpContextForge.config.PLUGINS_MTLS_VERIFY | string | `"true"` |  |
| mcpContextForge.config.PLUGIN_CONFIG_FILE | string | `"plugins/config.yaml"` |  |
| mcpContextForge.config.PORT | string | `"4444"` |  |
| mcpContextForge.config.PROMPT_CACHE_SIZE | string | `"100"` |  |
| mcpContextForge.config.PROMPT_RENDER_TIMEOUT | string | `"10"` |  |
| mcpContextForge.config.PROTOCOL_VERSION | string | `"2025-03-26"` |  |
| mcpContextForge.config.REDIS_DECODE_RESPONSES | string | `"true"` |  |
| mcpContextForge.config.REDIS_HEALTH_CHECK_INTERVAL | string | `"30"` |  |
| mcpContextForge.config.REDIS_LEADER_HEARTBEAT_INTERVAL | string | `"5"` |  |
| mcpContextForge.config.REDIS_LEADER_KEY | string | `"gateway_service_leader"` |  |
| mcpContextForge.config.REDIS_LEADER_TTL | string | `"15"` |  |
| mcpContextForge.config.REDIS_MAX_CONNECTIONS | string | `"50"` |  |
| mcpContextForge.config.REDIS_MAX_RETRIES | string | `"3"` |  |
| mcpContextForge.config.REDIS_RETRY_INTERVAL_MS | string | `"2000"` |  |
| mcpContextForge.config.REDIS_RETRY_ON_TIMEOUT | string | `"true"` |  |
| mcpContextForge.config.REDIS_SOCKET_CONNECT_TIMEOUT | string | `"2.0"` |  |
| mcpContextForge.config.REDIS_SOCKET_TIMEOUT | string | `"2.0"` |  |
| mcpContextForge.config.RELOAD | string | `"false"` |  |
| mcpContextForge.config.REMOVE_SERVER_HEADERS | string | `"true"` |  |
| mcpContextForge.config.RESOURCE_CACHE_SIZE | string | `"1000"` |  |
| mcpContextForge.config.RESOURCE_CACHE_TTL | string | `"3600"` |  |
| mcpContextForge.config.RETRY_BASE_DELAY | string | `"1.0"` |  |
| mcpContextForge.config.RETRY_JITTER_MAX | string | `"0.5"` |  |
| mcpContextForge.config.RETRY_MAX_ATTEMPTS | string | `"3"` |  |
| mcpContextForge.config.RETRY_MAX_DELAY | string | `"60"` |  |
| mcpContextForge.config.SECURE_COOKIES | string | `"true"` |  |
| mcpContextForge.config.SECURITY_HEADERS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.SESSION_TTL | string | `"3600"` |  |
| mcpContextForge.config.SKIP_SSL_VERIFY | string | `"false"` |  |
| mcpContextForge.config.SSE_KEEPALIVE_ENABLED | string | `"true"` |  |
| mcpContextForge.config.SSE_KEEPALIVE_INTERVAL | string | `"30"` |  |
| mcpContextForge.config.SSE_RETRY_TIMEOUT | string | `"5000"` |  |
| mcpContextForge.config.TOOLOPS_ENABLED | string | `"false"` |  |
| mcpContextForge.config.TOOL_CONCURRENT_LIMIT | string | `"10"` |  |
| mcpContextForge.config.TOOL_RATE_LIMIT | string | `"100"` |  |
| mcpContextForge.config.TOOL_TIMEOUT | string | `"60"` |  |
| mcpContextForge.config.TRANSPORT_TYPE | string | `"all"` |  |
| mcpContextForge.config.UNHEALTHY_THRESHOLD | string | `"3"` |  |
| mcpContextForge.config.USE_STATEFUL_SESSIONS | string | `"false"` |  |
| mcpContextForge.config.VALIDATION_ALLOWED_MIME_TYPES | string | `"[\"text/plain\", \"text/html\", \"text/css\", \"text/markdown\", \"text/javascript\", \"application/json\", \"application/xml\", \"application/pdf\", \"image/png\", \"image/jpeg\", \"image/gif\", \"image/svg+xml\", \"application/octet-stream\"]"` |  |
| mcpContextForge.config.VALIDATION_ALLOWED_URL_SCHEMES | string | `"[\"http://\", \"https://\", \"ws://\", \"wss://\"]"` |  |
| mcpContextForge.config.VALIDATION_DANGEROUS_HTML_PATTERN | string | `"<(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)\\b|</*(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)>"` |  |
| mcpContextForge.config.VALIDATION_DANGEROUS_JS_PATTERN | string | `"(?i)(?:^|\\s|[\\\"'`<>=])(javascript:|vbscript:|data:\\s*[^,]*[;\\s]*(javascript|vbscript)|\\bon[a-z]+\\s*=|<\\s*script\\b)"` |  |
| mcpContextForge.config.VALIDATION_IDENTIFIER_PATTERN | string | `"^[a-zA-Z0-9_\\-\\.]+$"` |  |
| mcpContextForge.config.VALIDATION_MAX_CONTENT_LENGTH | string | `"1048576"` |  |
| mcpContextForge.config.VALIDATION_MAX_DESCRIPTION_LENGTH | string | `"8192"` |  |
| mcpContextForge.config.VALIDATION_MAX_JSON_DEPTH | string | `"10"` |  |
| mcpContextForge.config.VALIDATION_MAX_METHOD_LENGTH | string | `"128"` |  |
| mcpContextForge.config.VALIDATION_MAX_NAME_LENGTH | string | `"255"` |  |
| mcpContextForge.config.VALIDATION_MAX_REQUESTS_PER_MINUTE | string | `"60"` |  |
| mcpContextForge.config.VALIDATION_MAX_RPC_PARAM_SIZE | string | `"262144"` |  |
| mcpContextForge.config.VALIDATION_MAX_TEMPLATE_LENGTH | string | `"65536"` |  |
| mcpContextForge.config.VALIDATION_MAX_URL_LENGTH | string | `"2048"` |  |
| mcpContextForge.config.VALIDATION_NAME_PATTERN | string | `"^[a-zA-Z0-9_.\\-\\s]+$"` |  |
| mcpContextForge.config.VALIDATION_SAFE_URI_PATTERN | string | `"^[a-zA-Z0-9_\\-.:/?=&%{}]+$"` |  |
| mcpContextForge.config.VALIDATION_TOOL_METHOD_PATTERN | string | `"^[a-zA-Z][a-zA-Z0-9_\\./-]*$"` |  |
| mcpContextForge.config.VALIDATION_TOOL_NAME_PATTERN | string | `"^[a-zA-Z][a-zA-Z0-9._-]*$"` |  |
| mcpContextForge.config.VALIDATION_UNSAFE_URI_PATTERN | string | `"[<>\"'\\\\]"` |  |
| mcpContextForge.config.WEBSOCKET_PING_INTERVAL | string | `"30"` |  |
| mcpContextForge.config.WELL_KNOWN_CACHE_MAX_AGE | string | `"3600"` |  |
| mcpContextForge.config.WELL_KNOWN_CUSTOM_FILES | string | `"{}"` |  |
| mcpContextForge.config.WELL_KNOWN_ENABLED | string | `"true"` |  |
| mcpContextForge.config.WELL_KNOWN_ROBOTS_TXT | string | `"User-agent: *\nDisallow: /\n\n# MCP Gateway is a private API gateway\n# Public crawling is disabled by default\n"` |  |
| mcpContextForge.config.WELL_KNOWN_SECURITY_TXT | string | `""` |  |
| mcpContextForge.config.X_CONTENT_TYPE_OPTIONS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.X_DOWNLOAD_OPTIONS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.X_FRAME_OPTIONS | string | `"DENY"` |  |
| mcpContextForge.config.X_XSS_PROTECTION_ENABLED | string | `"true"` |  |
| mcpContextForge.containerPort | int | `4444` |  |
| mcpContextForge.env.host | string | `"0.0.0.0"` |  |
| mcpContextForge.env.postgres.db | string | `"postgresdb"` |  |
| mcpContextForge.env.postgres.passwordKey | string | `"POSTGRES_PASSWORD"` |  |
| mcpContextForge.env.postgres.port | int | `5432` |  |
| mcpContextForge.env.postgres.userKey | string | `"POSTGRES_USER"` |  |
| mcpContextForge.env.redis.port | int | `6379` |  |
| mcpContextForge.envFrom[0].secretRef.name | string | `"mcp-gateway-secret"` |  |
| mcpContextForge.envFrom[1].configMapRef.name | string | `"mcp-gateway-config"` |  |
| mcpContextForge.hpa | object | `{"enabled":true,"maxReplicas":10,"minReplicas":2,"targetCPUUtilizationPercentage":90,"targetMemoryUtilizationPercentage":90}` | ------------------------------------------------------------------ |
| mcpContextForge.image.pullPolicy | string | `"Always"` |  |
| mcpContextForge.image.repository | string | `"ghcr.io/ibm/mcp-context-forge"` |  |
| mcpContextForge.image.tag | string | `"latest"` |  |
| mcpContextForge.ingress.annotations | object | `{}` |  |
| mcpContextForge.ingress.className | string | `"nginx"` |  |
| mcpContextForge.ingress.enabled | bool | `true` |  |
| mcpContextForge.ingress.host | string | `"gateway.local"` |  |
| mcpContextForge.ingress.path | string | `"/"` |  |
| mcpContextForge.ingress.pathType | string | `"Prefix"` |  |
| mcpContextForge.ingress.tls.enabled | bool | `false` |  |
| mcpContextForge.ingress.tls.secretName | string | `""` |  |
| mcpContextForge.metrics.customLabels | object | `{}` |  |
| mcpContextForge.metrics.enabled | bool | `true` |  |
| mcpContextForge.metrics.port | int | `8000` |  |
| mcpContextForge.metrics.serviceMonitor.enabled | bool | `true` |  |
| mcpContextForge.pluginConfig.enabled | bool | `false` |  |
| mcpContextForge.pluginConfig.plugins | string | `"# plugin file\n"` |  |
| mcpContextForge.probes.liveness.failureThreshold | int | `3` |  |
| mcpContextForge.probes.liveness.initialDelaySeconds | int | `10` |  |
| mcpContextForge.probes.liveness.path | string | `"/health"` |  |
| mcpContextForge.probes.liveness.periodSeconds | int | `15` |  |
| mcpContextForge.probes.liveness.port | int | `4444` |  |
| mcpContextForge.probes.liveness.successThreshold | int | `1` |  |
| mcpContextForge.probes.liveness.timeoutSeconds | int | `2` |  |
| mcpContextForge.probes.liveness.type | string | `"http"` |  |
| mcpContextForge.probes.readiness.failureThreshold | int | `3` |  |
| mcpContextForge.probes.readiness.initialDelaySeconds | int | `15` |  |
| mcpContextForge.probes.readiness.path | string | `"/ready"` |  |
| mcpContextForge.probes.readiness.periodSeconds | int | `10` |  |
| mcpContextForge.probes.readiness.port | int | `4444` |  |
| mcpContextForge.probes.readiness.successThreshold | int | `1` |  |
| mcpContextForge.probes.readiness.timeoutSeconds | int | `2` |  |
| mcpContextForge.probes.readiness.type | string | `"http"` |  |
| mcpContextForge.probes.startup.command[0] | string | `"sh"` |  |
| mcpContextForge.probes.startup.command[1] | string | `"-c"` |  |
| mcpContextForge.probes.startup.command[2] | string | `"sleep 10"` |  |
| mcpContextForge.probes.startup.failureThreshold | int | `1` |  |
| mcpContextForge.probes.startup.periodSeconds | int | `5` |  |
| mcpContextForge.probes.startup.timeoutSeconds | int | `15` |  |
| mcpContextForge.probes.startup.type | string | `"exec"` |  |
| mcpContextForge.replicaCount | int | `2` |  |
| mcpContextForge.resources.limits.cpu | string | `"200m"` |  |
| mcpContextForge.resources.limits.memory | string | `"1024Mi"` |  |
| mcpContextForge.resources.requests.cpu | string | `"100m"` |  |
| mcpContextForge.resources.requests.memory | string | `"512Mi"` |  |
| mcpContextForge.secret.ACCOUNT_LOCKOUT_DURATION_MINUTES | string | `"30"` |  |
| mcpContextForge.secret.ARGON2ID_MEMORY_COST | string | `"65536"` |  |
| mcpContextForge.secret.ARGON2ID_PARALLELISM | string | `"1"` |  |
| mcpContextForge.secret.ARGON2ID_TIME_COST | string | `"3"` |  |
| mcpContextForge.secret.AUTH_ENCRYPTION_SECRET | string | `"my-test-salt"` |  |
| mcpContextForge.secret.AUTH_REQUIRED | string | `"true"` |  |
| mcpContextForge.secret.AUTO_CREATE_PERSONAL_TEAMS | string | `"true"` |  |
| mcpContextForge.secret.BASIC_AUTH_PASSWORD | string | `"changeme"` |  |
| mcpContextForge.secret.BASIC_AUTH_USER | string | `"admin"` |  |
| mcpContextForge.secret.DCR_ALLOWED_ISSUERS | string | `"[]"` |  |
| mcpContextForge.secret.DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS | string | `"true"` |  |
| mcpContextForge.secret.DCR_CLIENT_NAME_TEMPLATE | string | `"MCP Gateway ({gateway_name})"` |  |
| mcpContextForge.secret.DCR_DEFAULT_SCOPES | string | `"[\"mcp:read\"]"` |  |
| mcpContextForge.secret.DCR_ENABLED | string | `"true"` |  |
| mcpContextForge.secret.DCR_METADATA_CACHE_TTL | string | `"3600"` |  |
| mcpContextForge.secret.DCR_TOKEN_ENDPOINT_AUTH_METHOD | string | `"client_secret_basic"` |  |
| mcpContextForge.secret.DOCS_ALLOW_BASIC_AUTH | string | `"false"` |  |
| mcpContextForge.secret.ED25519_PRIVATE_KEY | string | `""` |  |
| mcpContextForge.secret.EMAIL_AUTH_ENABLED | string | `"true"` |  |
| mcpContextForge.secret.ENABLE_ED25519_SIGNING | string | `"false"` |  |
| mcpContextForge.secret.INVITATION_EXPIRY_DAYS | string | `"7"` |  |
| mcpContextForge.secret.JWT_ALGORITHM | string | `"HS256"` |  |
| mcpContextForge.secret.JWT_AUDIENCE | string | `"mcpgateway-api"` |  |
| mcpContextForge.secret.JWT_AUDIENCE_VERIFICATION | string | `"true"` |  |
| mcpContextForge.secret.JWT_ISSUER | string | `"mcpgateway"` |  |
| mcpContextForge.secret.JWT_PRIVATE_KEY_PATH | string | `""` |  |
| mcpContextForge.secret.JWT_PUBLIC_KEY_PATH | string | `""` |  |
| mcpContextForge.secret.JWT_SECRET_KEY | string | `"my-test-key"` |  |
| mcpContextForge.secret.MAX_FAILED_LOGIN_ATTEMPTS | string | `"5"` |  |
| mcpContextForge.secret.MAX_MEMBERS_PER_TEAM | string | `"100"` |  |
| mcpContextForge.secret.MAX_TEAMS_PER_USER | string | `"50"` |  |
| mcpContextForge.secret.MCP_CLIENT_AUTH_ENABLED | string | `"true"` |  |
| mcpContextForge.secret.MIN_PASSWORD_LENGTH | string | `"12"` |  |
| mcpContextForge.secret.MIN_SECRET_LENGTH | string | `"32"` |  |
| mcpContextForge.secret.OAUTH_DEFAULT_TIMEOUT | string | `"3600"` |  |
| mcpContextForge.secret.OAUTH_DISCOVERY_ENABLED | string | `"true"` |  |
| mcpContextForge.secret.OAUTH_MAX_RETRIES | string | `"3"` |  |
| mcpContextForge.secret.OAUTH_PREFERRED_CODE_CHALLENGE_METHOD | string | `"S256"` |  |
| mcpContextForge.secret.OAUTH_REQUEST_TIMEOUT | string | `"30"` |  |
| mcpContextForge.secret.OTEL_EXPORTER_JAEGER_ENDPOINT | string | `""` |  |
| mcpContextForge.secret.OTEL_EXPORTER_OTLP_ENDPOINT | string | `""` |  |
| mcpContextForge.secret.OTEL_EXPORTER_OTLP_HEADERS | string | `""` |  |
| mcpContextForge.secret.OTEL_EXPORTER_ZIPKIN_ENDPOINT | string | `""` |  |
| mcpContextForge.secret.OTEL_RESOURCE_ATTRIBUTES | string | `""` |  |
| mcpContextForge.secret.PASSWORD_MIN_LENGTH | string | `"8"` |  |
| mcpContextForge.secret.PASSWORD_REQUIRE_LOWERCASE | string | `"false"` |  |
| mcpContextForge.secret.PASSWORD_REQUIRE_NUMBERS | string | `"false"` |  |
| mcpContextForge.secret.PASSWORD_REQUIRE_SPECIAL | string | `"false"` |  |
| mcpContextForge.secret.PASSWORD_REQUIRE_UPPERCASE | string | `"false"` |  |
| mcpContextForge.secret.PERSONAL_TEAM_PREFIX | string | `"personal"` |  |
| mcpContextForge.secret.PLATFORM_ADMIN_EMAIL | string | `"admin@example.com"` |  |
| mcpContextForge.secret.PLATFORM_ADMIN_FULL_NAME | string | `"Platform Administrator"` |  |
| mcpContextForge.secret.PLATFORM_ADMIN_PASSWORD | string | `"changeme"` |  |
| mcpContextForge.secret.PREV_ED25519_PRIVATE_KEY | string | `""` |  |
| mcpContextForge.secret.PROXY_USER_HEADER | string | `"X-Authenticated-User"` |  |
| mcpContextForge.secret.REQUIRE_EMAIL_VERIFICATION_FOR_INVITES | string | `"true"` |  |
| mcpContextForge.secret.REQUIRE_STRONG_SECRETS | string | `"false"` |  |
| mcpContextForge.secret.REQUIRE_TOKEN_EXPIRATION | string | `"false"` |  |
| mcpContextForge.secret.SSO_AUTO_ADMIN_DOMAINS | string | `"[]"` |  |
| mcpContextForge.secret.SSO_AUTO_CREATE_USERS | string | `"true"` |  |
| mcpContextForge.secret.SSO_ENABLED | string | `"false"` |  |
| mcpContextForge.secret.SSO_ENTRA_CLIENT_ID | string | `""` |  |
| mcpContextForge.secret.SSO_ENTRA_CLIENT_SECRET | string | `""` |  |
| mcpContextForge.secret.SSO_ENTRA_ENABLED | string | `"false"` |  |
| mcpContextForge.secret.SSO_ENTRA_TENANT_ID | string | `""` |  |
| mcpContextForge.secret.SSO_GENERIC_AUTHORIZATION_URL | string | `""` |  |
| mcpContextForge.secret.SSO_GENERIC_CLIENT_ID | string | `""` |  |
| mcpContextForge.secret.SSO_GENERIC_CLIENT_SECRET | string | `""` |  |
| mcpContextForge.secret.SSO_GENERIC_DISPLAY_NAME | string | `""` |  |
| mcpContextForge.secret.SSO_GENERIC_ENABLED | string | `"false"` |  |
| mcpContextForge.secret.SSO_GENERIC_ISSUER | string | `""` |  |
| mcpContextForge.secret.SSO_GENERIC_PROVIDER_ID | string | `""` |  |
| mcpContextForge.secret.SSO_GENERIC_SCOPE | string | `"openid profile email"` |  |
| mcpContextForge.secret.SSO_GENERIC_TOKEN_URL | string | `""` |  |
| mcpContextForge.secret.SSO_GENERIC_USERINFO_URL | string | `""` |  |
| mcpContextForge.secret.SSO_GITHUB_ADMIN_ORGS | string | `"[]"` |  |
| mcpContextForge.secret.SSO_GITHUB_CLIENT_ID | string | `""` |  |
| mcpContextForge.secret.SSO_GITHUB_CLIENT_SECRET | string | `""` |  |
| mcpContextForge.secret.SSO_GITHUB_ENABLED | string | `"false"` |  |
| mcpContextForge.secret.SSO_GOOGLE_ADMIN_DOMAINS | string | `"[]"` |  |
| mcpContextForge.secret.SSO_GOOGLE_CLIENT_ID | string | `""` |  |
| mcpContextForge.secret.SSO_GOOGLE_CLIENT_SECRET | string | `""` |  |
| mcpContextForge.secret.SSO_GOOGLE_ENABLED | string | `"false"` |  |
| mcpContextForge.secret.SSO_IBM_VERIFY_CLIENT_ID | string | `""` |  |
| mcpContextForge.secret.SSO_IBM_VERIFY_CLIENT_SECRET | string | `""` |  |
| mcpContextForge.secret.SSO_IBM_VERIFY_ENABLED | string | `"false"` |  |
| mcpContextForge.secret.SSO_IBM_VERIFY_ISSUER | string | `""` |  |
| mcpContextForge.secret.SSO_ISSUERS | string | `""` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_BASE_URL | string | `""` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_CLIENT_ID | string | `""` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_CLIENT_SECRET | string | `""` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_EMAIL_CLAIM | string | `"email"` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_ENABLED | string | `"false"` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_GROUPS_CLAIM | string | `"groups"` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_MAP_CLIENT_ROLES | string | `"false"` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_MAP_REALM_ROLES | string | `"true"` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_REALM | string | `"master"` |  |
| mcpContextForge.secret.SSO_KEYCLOAK_USERNAME_CLAIM | string | `"preferred_username"` |  |
| mcpContextForge.secret.SSO_OKTA_CLIENT_ID | string | `""` |  |
| mcpContextForge.secret.SSO_OKTA_CLIENT_SECRET | string | `""` |  |
| mcpContextForge.secret.SSO_OKTA_ENABLED | string | `"false"` |  |
| mcpContextForge.secret.SSO_OKTA_ISSUER | string | `""` |  |
| mcpContextForge.secret.SSO_PRESERVE_ADMIN_AUTH | string | `"true"` |  |
| mcpContextForge.secret.SSO_REQUIRE_ADMIN_APPROVAL | string | `"false"` |  |
| mcpContextForge.secret.SSO_TRUSTED_DOMAINS | string | `"[]"` |  |
| mcpContextForge.secret.TOKEN_EXPIRY | string | `"10080"` |  |
| mcpContextForge.secret.TRUST_PROXY_AUTH | string | `"false"` |  |
| mcpContextForge.service.port | int | `80` |  |
| mcpContextForge.service.type | string | `"ClusterIP"` |  |
| mcpFastTimeServer.enabled | bool | `true` |  |
| mcpFastTimeServer.image.pullPolicy | string | `"IfNotPresent"` |  |
| mcpFastTimeServer.image.repository | string | `"ghcr.io/ibm/fast-time-server"` |  |
| mcpFastTimeServer.image.tag | string | `"latest"` |  |
| mcpFastTimeServer.ingress.enabled | bool | `true` |  |
| mcpFastTimeServer.ingress.path | string | `"/fast-time"` |  |
| mcpFastTimeServer.ingress.pathType | string | `"Prefix"` |  |
| mcpFastTimeServer.ingress.servicePort | int | `80` |  |
| mcpFastTimeServer.port | int | `8080` |  |
| mcpFastTimeServer.probes.liveness.failureThreshold | int | `3` |  |
| mcpFastTimeServer.probes.liveness.initialDelaySeconds | int | `3` |  |
| mcpFastTimeServer.probes.liveness.path | string | `"/health"` |  |
| mcpFastTimeServer.probes.liveness.periodSeconds | int | `15` |  |
| mcpFastTimeServer.probes.liveness.port | int | `8080` |  |
| mcpFastTimeServer.probes.liveness.successThreshold | int | `1` |  |
| mcpFastTimeServer.probes.liveness.timeoutSeconds | int | `2` |  |
| mcpFastTimeServer.probes.liveness.type | string | `"http"` |  |
| mcpFastTimeServer.probes.readiness.failureThreshold | int | `3` |  |
| mcpFastTimeServer.probes.readiness.initialDelaySeconds | int | `3` |  |
| mcpFastTimeServer.probes.readiness.path | string | `"/health"` |  |
| mcpFastTimeServer.probes.readiness.periodSeconds | int | `10` |  |
| mcpFastTimeServer.probes.readiness.port | int | `8080` |  |
| mcpFastTimeServer.probes.readiness.successThreshold | int | `1` |  |
| mcpFastTimeServer.probes.readiness.timeoutSeconds | int | `2` |  |
| mcpFastTimeServer.probes.readiness.type | string | `"http"` |  |
| mcpFastTimeServer.replicaCount | int | `2` |  |
| mcpFastTimeServer.resources.limits.cpu | string | `"50m"` |  |
| mcpFastTimeServer.resources.limits.memory | string | `"64Mi"` |  |
| mcpFastTimeServer.resources.requests.cpu | string | `"25m"` |  |
| mcpFastTimeServer.resources.requests.memory | string | `"10Mi"` |  |
| migration.activeDeadlineSeconds | int | `600` |  |
| migration.backoffLimit | int | `3` |  |
| migration.command.migrate | string | `"alembic upgrade head || echo '⚠️ Migration check failed'"` |  |
| migration.command.waitForDb | string | `"python3 /app/mcpgateway/utils/db_isready.py --max-tries 30 --interval 2 --timeout 5"` |  |
| migration.enabled | bool | `true` |  |
| migration.image.pullPolicy | string | `"Always"` |  |
| migration.image.repository | string | `"ghcr.io/ibm/mcp-context-forge"` |  |
| migration.image.tag | string | `"latest"` |  |
| migration.resources.limits.cpu | string | `"200m"` |  |
| migration.resources.limits.memory | string | `"512Mi"` |  |
| migration.resources.requests.cpu | string | `"100m"` |  |
| migration.resources.requests.memory | string | `"256Mi"` |  |
| migration.restartPolicy | string | `"Never"` |  |
| minio.credentials.rootPassword | string | `"minioadminchangeme"` |  |
| minio.credentials.rootUser | string | `"minioadmin"` |  |
| minio.enabled | bool | `true` |  |
| minio.existingSecret | string | `""` |  |
| minio.image.pullPolicy | string | `"IfNotPresent"` |  |
| minio.image.repository | string | `"minio/minio"` |  |
| minio.image.tag | string | `"RELEASE.2025-09-07T16-13-09Z-cpuv1"` |  |
| minio.persistence.accessModes[0] | string | `"ReadWriteOnce"` |  |
| minio.persistence.enabled | bool | `true` |  |
| minio.persistence.reclaimPolicy | string | `"Retain"` |  |
| minio.persistence.size | string | `"10Gi"` |  |
| minio.persistence.storageClassName | string | `""` |  |
| minio.resources.limits.cpu | string | `"500m"` |  |
| minio.resources.limits.memory | string | `"1Gi"` |  |
| minio.resources.requests.cpu | string | `"100m"` |  |
| minio.resources.requests.memory | string | `"256Mi"` |  |
| minio.service.apiPort | int | `9000` |  |
| minio.service.consolePort | int | `9001` |  |
| minio.service.type | string | `"ClusterIP"` |  |
| pgadmin.enabled | bool | `true` |  |
| pgadmin.env.email | string | `"admin@example.com"` |  |
| pgadmin.env.password | string | `"admin123"` |  |
| pgadmin.image.pullPolicy | string | `"IfNotPresent"` |  |
| pgadmin.image.repository | string | `"dpage/pgadmin4"` |  |
| pgadmin.image.tag | string | `"latest"` |  |
| pgadmin.probes.liveness.failureThreshold | int | `3` |  |
| pgadmin.probes.liveness.initialDelaySeconds | int | `90` |  |
| pgadmin.probes.liveness.path | string | `"/misc/ping"` |  |
| pgadmin.probes.liveness.periodSeconds | int | `20` |  |
| pgadmin.probes.liveness.port | int | `80` |  |
| pgadmin.probes.liveness.successThreshold | int | `1` |  |
| pgadmin.probes.liveness.timeoutSeconds | int | `5` |  |
| pgadmin.probes.liveness.type | string | `"http"` |  |
| pgadmin.probes.readiness.failureThreshold | int | `5` |  |
| pgadmin.probes.readiness.initialDelaySeconds | int | `60` |  |
| pgadmin.probes.readiness.path | string | `"/misc/ping"` |  |
| pgadmin.probes.readiness.periodSeconds | int | `10` |  |
| pgadmin.probes.readiness.port | int | `80` |  |
| pgadmin.probes.readiness.successThreshold | int | `1` |  |
| pgadmin.probes.readiness.timeoutSeconds | int | `5` |  |
| pgadmin.probes.readiness.type | string | `"http"` |  |
| pgadmin.resources.limits.cpu | string | `"200m"` |  |
| pgadmin.resources.limits.memory | string | `"256Mi"` |  |
| pgadmin.resources.requests.cpu | string | `"100m"` |  |
| pgadmin.resources.requests.memory | string | `"128Mi"` |  |
| pgadmin.service.port | int | `80` |  |
| pgadmin.service.type | string | `"ClusterIP"` |  |
| postgres.credentials.database | string | `"postgresdb"` |  |
| postgres.credentials.password | string | `"test123"` |  |
| postgres.credentials.user | string | `"admin"` |  |
| postgres.enabled | bool | `true` |  |
| postgres.existingSecret | string | `""` |  |
| postgres.image.pullPolicy | string | `"IfNotPresent"` |  |
| postgres.image.repository | string | `"postgres"` |  |
| postgres.image.tag | string | `"17"` |  |
| postgres.persistence.accessModes[0] | string | `"ReadWriteOnce"` |  |
| postgres.persistence.annotations | object | `{}` |  |
| postgres.persistence.enabled | bool | `true` |  |
| postgres.persistence.reclaimPolicy | string | `"Retain"` |  |
| postgres.persistence.size | string | `"5Gi"` |  |
| postgres.persistence.storageClassName | string | `""` |  |
| postgres.probes.liveness.command[0] | string | `"pg_isready"` |  |
| postgres.probes.liveness.command[1] | string | `"-U"` |  |
| postgres.probes.liveness.command[2] | string | `"$(POSTGRES_USER)"` |  |
| postgres.probes.liveness.failureThreshold | int | `5` |  |
| postgres.probes.liveness.initialDelaySeconds | int | `10` |  |
| postgres.probes.liveness.periodSeconds | int | `15` |  |
| postgres.probes.liveness.successThreshold | int | `1` |  |
| postgres.probes.liveness.timeoutSeconds | int | `3` |  |
| postgres.probes.liveness.type | string | `"exec"` |  |
| postgres.probes.readiness.command[0] | string | `"pg_isready"` |  |
| postgres.probes.readiness.command[1] | string | `"-U"` |  |
| postgres.probes.readiness.command[2] | string | `"$(POSTGRES_USER)"` |  |
| postgres.probes.readiness.failureThreshold | int | `3` |  |
| postgres.probes.readiness.initialDelaySeconds | int | `15` |  |
| postgres.probes.readiness.periodSeconds | int | `10` |  |
| postgres.probes.readiness.successThreshold | int | `1` |  |
| postgres.probes.readiness.timeoutSeconds | int | `3` |  |
| postgres.probes.readiness.type | string | `"exec"` |  |
| postgres.resources.limits.cpu | string | `"1000m"` |  |
| postgres.resources.limits.memory | string | `"1Gi"` |  |
| postgres.resources.requests.cpu | string | `"500m"` |  |
| postgres.resources.requests.memory | string | `"64Mi"` |  |
| postgres.service.port | int | `5432` |  |
| postgres.service.type | string | `"ClusterIP"` |  |
| postgres.upgrade.backupCompleted | bool | `false` |  |
| postgres.upgrade.enabled | bool | `false` |  |
| postgres.upgrade.targetVersion | string | `"18"` |  |
| pgbouncer.enabled | bool | `false` | Enable PgBouncer connection pooling |
| pgbouncer.image.repository | string | `"edoburu/pgbouncer"` | PgBouncer image repository |
| pgbouncer.image.tag | string | `"latest"` | PgBouncer image tag |
| pgbouncer.image.pullPolicy | string | `"IfNotPresent"` | Image pull policy |
| pgbouncer.service.type | string | `"ClusterIP"` | Service type |
| pgbouncer.service.port | int | `6432` | PgBouncer listen port |
| pgbouncer.pool.mode | string | `"transaction"` | Pool mode (transaction, session, statement) |
| pgbouncer.pool.maxClientConn | int | `3000` | Max connections from application |
| pgbouncer.pool.defaultPoolSize | int | `120` | Connections per user/database pair |
| pgbouncer.pool.minPoolSize | int | `10` | Minimum connections to keep open |
| pgbouncer.pool.reservePoolSize | int | `25` | Extra connections for burst traffic |
| pgbouncer.pool.reservePoolTimeout | int | `5` | Seconds before using reserve pool |
| pgbouncer.pool.maxDbConnections | int | `200` | Max connections to PostgreSQL |
| pgbouncer.pool.maxUserConnections | int | `200` | Max connections per user |
| pgbouncer.pool.serverLifetime | int | `3600` | Max server connection age (seconds) |
| pgbouncer.pool.serverIdleTimeout | int | `600` | Close idle connections after (seconds) |
| pgbouncer.authType | string | `"scram-sha-256"` | Authentication type |
| pgbouncer.resources.limits.cpu | string | `"500m"` | CPU limit |
| pgbouncer.resources.limits.memory | string | `"256Mi"` | Memory limit |
| pgbouncer.resources.requests.cpu | string | `"100m"` | CPU request |
| pgbouncer.resources.requests.memory | string | `"128Mi"` | Memory request |
| redis.enabled | bool | `true` |  |
| redis.image.pullPolicy | string | `"IfNotPresent"` |  |
| redis.image.repository | string | `"redis"` |  |
| redis.image.tag | string | `"latest"` |  |
| redis.persistence.accessModes[0] | string | `"ReadWriteOnce"` |  |
| redis.persistence.annotations | object | `{}` |  |
| redis.persistence.enabled | bool | `false` |  |
| redis.persistence.reclaimPolicy | string | `"Retain"` |  |
| redis.persistence.size | string | `"1Gi"` |  |
| redis.persistence.storageClassName | string | `""` |  |
| redis.probes.liveness.command[0] | string | `"redis-cli"` |  |
| redis.probes.liveness.command[1] | string | `"PING"` |  |
| redis.probes.liveness.failureThreshold | int | `5` |  |
| redis.probes.liveness.initialDelaySeconds | int | `5` |  |
| redis.probes.liveness.periodSeconds | int | `15` |  |
| redis.probes.liveness.successThreshold | int | `1` |  |
| redis.probes.liveness.timeoutSeconds | int | `2` |  |
| redis.probes.liveness.type | string | `"exec"` |  |
| redis.probes.readiness.command[0] | string | `"redis-cli"` |  |
| redis.probes.readiness.command[1] | string | `"PING"` |  |
| redis.probes.readiness.failureThreshold | int | `3` |  |
| redis.probes.readiness.initialDelaySeconds | int | `10` |  |
| redis.probes.readiness.periodSeconds | int | `10` |  |
| redis.probes.readiness.successThreshold | int | `1` |  |
| redis.probes.readiness.timeoutSeconds | int | `2` |  |
| redis.probes.readiness.type | string | `"exec"` |  |
| redis.resources.limits.cpu | string | `"100m"` |  |
| redis.resources.limits.memory | string | `"256Mi"` |  |
| redis.resources.requests.cpu | string | `"50m"` |  |
| redis.resources.requests.memory | string | `"16Mi"` |  |
| redis.service.port | int | `6379` |  |
| redis.service.type | string | `"ClusterIP"` |  |
| redisCommander.enabled | bool | `true` |  |
| redisCommander.image.pullPolicy | string | `"IfNotPresent"` |  |
| redisCommander.image.repository | string | `"rediscommander/redis-commander"` |  |
| redisCommander.image.tag | string | `"latest"` |  |
| redisCommander.probes.liveness.failureThreshold | int | `5` |  |
| redisCommander.probes.liveness.initialDelaySeconds | int | `10` |  |
| redisCommander.probes.liveness.path | string | `"/"` |  |
| redisCommander.probes.liveness.periodSeconds | int | `15` |  |
| redisCommander.probes.liveness.port | int | `8081` |  |
| redisCommander.probes.liveness.successThreshold | int | `1` |  |
| redisCommander.probes.liveness.timeoutSeconds | int | `2` |  |
| redisCommander.probes.liveness.type | string | `"http"` |  |
| redisCommander.probes.readiness.failureThreshold | int | `3` |  |
| redisCommander.probes.readiness.initialDelaySeconds | int | `15` |  |
| redisCommander.probes.readiness.path | string | `"/"` |  |
| redisCommander.probes.readiness.periodSeconds | int | `10` |  |
| redisCommander.probes.readiness.port | int | `8081` |  |
| redisCommander.probes.readiness.successThreshold | int | `1` |  |
| redisCommander.probes.readiness.timeoutSeconds | int | `2` |  |
| redisCommander.probes.readiness.type | string | `"http"` |  |
| redisCommander.resources.limits.cpu | string | `"100m"` |  |
| redisCommander.resources.limits.memory | string | `"256Mi"` |  |
| redisCommander.resources.requests.cpu | string | `"50m"` |  |
| redisCommander.resources.requests.memory | string | `"128Mi"` |  |
| redisCommander.service.port | int | `8081` |  |
| redisCommander.service.type | string | `"ClusterIP"` |  |
