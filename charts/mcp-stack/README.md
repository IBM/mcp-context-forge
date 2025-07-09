# mcp-stack

![Version: 0.3.0](https://img.shields.io/badge/Version-0.3.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 0.3.0](https://img.shields.io/badge/AppVersion-0.3.0-informational?style=flat-square)

A full-stack Helm chart for IBM's **Model Context Protocol (MCP) Gateway
& Registry - Context-Forge**.  It bundles:
  - MCP Gateway application (HTTP / WebSocket server)
  - PostgreSQL database with persistent storage
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

Kubernetes: `>=1.21.0`

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| global.fullnameOverride | string | `""` |  |
| global.imagePullSecrets | list | `[]` |  |
| global.nameOverride | string | `""` |  |
| mcpContextForge.config.ALLOWED_ORIGINS | string | `"[\"http://localhost\",\"http://localhost:4444\"]"` |  |
| mcpContextForge.config.APP_NAME | string | `"MCP_Gateway"` |  |
| mcpContextForge.config.APP_ROOT_PATH | string | `""` |  |
| mcpContextForge.config.CACHE_PREFIX | string | `"mcpgw"` |  |
| mcpContextForge.config.CACHE_TYPE | string | `"redis"` |  |
| mcpContextForge.config.CORS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.DB_MAX_OVERFLOW | string | `"10"` |  |
| mcpContextForge.config.DB_MAX_RETRIES | string | `"3"` |  |
| mcpContextForge.config.DB_POOL_RECYCLE | string | `"3600"` |  |
| mcpContextForge.config.DB_POOL_SIZE | string | `"200"` |  |
| mcpContextForge.config.DB_POOL_TIMEOUT | string | `"30"` |  |
| mcpContextForge.config.DB_RETRY_INTERVAL_MS | string | `"2000"` |  |
| mcpContextForge.config.DEBUG | string | `"false"` |  |
| mcpContextForge.config.DEV_MODE | string | `"false"` |  |
| mcpContextForge.config.FEDERATION_DISCOVERY | string | `"false"` |  |
| mcpContextForge.config.FEDERATION_ENABLED | string | `"true"` |  |
| mcpContextForge.config.FEDERATION_PEERS | string | `"[]"` |  |
| mcpContextForge.config.FEDERATION_SYNC_INTERVAL | string | `"300"` |  |
| mcpContextForge.config.FEDERATION_TIMEOUT | string | `"30"` |  |
| mcpContextForge.config.FILELOCK_NAME | string | `"gateway_healthcheck_init.lock"` |  |
| mcpContextForge.config.GUNICORN_MAX_REQUESTS | string | `"10000"` |  |
| mcpContextForge.config.GUNICORN_MAX_REQUESTS_JITTER | string | `"100"` |  |
| mcpContextForge.config.GUNICORN_PRELOAD_APP | string | `"true"` |  |
| mcpContextForge.config.GUNICORN_TIMEOUT | string | `"600"` |  |
| mcpContextForge.config.GUNICORN_WORKERS | string | `"2"` |  |
| mcpContextForge.config.HEALTH_CHECK_INTERVAL | string | `"60"` |  |
| mcpContextForge.config.HEALTH_CHECK_TIMEOUT | string | `"10"` |  |
| mcpContextForge.config.HOST | string | `"0.0.0.0"` |  |
| mcpContextForge.config.JSON_RESPONSE_ENABLED | string | `"true"` |  |
| mcpContextForge.config.LOG_FORMAT | string | `"json"` |  |
| mcpContextForge.config.LOG_LEVEL | string | `"INFO"` |  |
| mcpContextForge.config.MAX_PROMPT_SIZE | string | `"102400"` |  |
| mcpContextForge.config.MAX_RESOURCE_SIZE | string | `"10485760"` |  |
| mcpContextForge.config.MAX_TOOL_RETRIES | string | `"3"` |  |
| mcpContextForge.config.MCPGATEWAY_ADMIN_API_ENABLED | string | `"true"` |  |
| mcpContextForge.config.MCPGATEWAY_UI_ENABLED | string | `"true"` |  |
| mcpContextForge.config.MESSAGE_TTL | string | `"600"` |  |
| mcpContextForge.config.PORT | string | `"4444"` |  |
| mcpContextForge.config.PROMPT_CACHE_SIZE | string | `"100"` |  |
| mcpContextForge.config.PROMPT_RENDER_TIMEOUT | string | `"10"` |  |
| mcpContextForge.config.PROTOCOL_VERSION | string | `"2025-03-26"` |  |
| mcpContextForge.config.REDIS_MAX_RETRIES | string | `"3"` |  |
| mcpContextForge.config.REDIS_RETRY_INTERVAL_MS | string | `"2000"` |  |
| mcpContextForge.config.RELOAD | string | `"false"` |  |
| mcpContextForge.config.RESOURCE_CACHE_SIZE | string | `"1000"` |  |
| mcpContextForge.config.RESOURCE_CACHE_TTL | string | `"3600"` |  |
| mcpContextForge.config.SESSION_TTL | string | `"3600"` |  |
| mcpContextForge.config.SKIP_SSL_VERIFY | string | `"false"` |  |
| mcpContextForge.config.SSE_RETRY_TIMEOUT | string | `"5000"` |  |
| mcpContextForge.config.TOOL_CONCURRENT_LIMIT | string | `"10"` |  |
| mcpContextForge.config.TOOL_RATE_LIMIT | string | `"100"` |  |
| mcpContextForge.config.TOOL_TIMEOUT | string | `"60"` |  |
| mcpContextForge.config.TRANSPORT_TYPE | string | `"all"` |  |
| mcpContextForge.config.UNHEALTHY_THRESHOLD | string | `"3"` |  |
| mcpContextForge.config.USE_STATEFUL_SESSIONS | string | `"false"` |  |
| mcpContextForge.config.WEBSOCKET_PING_INTERVAL | string | `"30"` |  |
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
| mcpContextForge.ingress.annotations."nginx.ingress.kubernetes.io/rewrite-target" | string | `"/"` |  |
| mcpContextForge.ingress.className | string | `"nginx"` |  |
| mcpContextForge.ingress.enabled | bool | `true` |  |
| mcpContextForge.ingress.host | string | `"gateway.local"` |  |
| mcpContextForge.ingress.path | string | `"/"` |  |
| mcpContextForge.ingress.pathType | string | `"Prefix"` |  |
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
| mcpContextForge.secret.AUTH_ENCRYPTION_SECRET | string | `"my-test-salt"` |  |
| mcpContextForge.secret.AUTH_REQUIRED | string | `"true"` |  |
| mcpContextForge.secret.BASIC_AUTH_PASSWORD | string | `"changeme"` |  |
| mcpContextForge.secret.BASIC_AUTH_USER | string | `"admin"` |  |
| mcpContextForge.secret.JWT_ALGORITHM | string | `"HS256"` |  |
| mcpContextForge.secret.JWT_SECRET_KEY | string | `"my-test-key"` |  |
| mcpContextForge.secret.TOKEN_EXPIRY | string | `"10080"` |  |
| mcpContextForge.service.port | int | `80` |  |
| mcpContextForge.service.type | string | `"ClusterIP"` |  |
| mcpFastTimeServer.enabled | bool | `true` |  |
| mcpFastTimeServer.image.pullPolicy | string | `"IfNotPresent"` |  |
| mcpFastTimeServer.image.repository | string | `"ghcr.io/ibm/fast-time-server"` |  |
| mcpFastTimeServer.image.tag | string | `"0.3.0"` |  |
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
| migration.command.waitForDb | string | `"python /app/mcpgateway/utils/db_isready.py --max-tries 30 --interval 2 --timeout 5"` |  |
| migration.enabled | bool | `true` |  |
| migration.image.pullPolicy | string | `"Always"` |  |
| migration.image.repository | string | `"ghcr.io/ibm/mcp-context-forge"` |  |
| migration.image.tag | string | `"latest"` |  |
| migration.resources.limits.cpu | string | `"200m"` |  |
| migration.resources.limits.memory | string | `"512Mi"` |  |
| migration.resources.requests.cpu | string | `"100m"` |  |
| migration.resources.requests.memory | string | `"256Mi"` |  |
| migration.restartPolicy | string | `"Never"` |  |
| pgadmin.enabled | bool | `true` |  |
| pgadmin.env.email | string | `"admin@example.com"` |  |
| pgadmin.env.password | string | `"admin123"` |  |
| pgadmin.image.pullPolicy | string | `"IfNotPresent"` |  |
| pgadmin.image.repository | string | `"dpage/pgadmin4"` |  |
| pgadmin.image.tag | string | `"latest"` |  |
| pgadmin.probes.liveness.failureThreshold | int | `5` |  |
| pgadmin.probes.liveness.initialDelaySeconds | int | `10` |  |
| pgadmin.probes.liveness.path | string | `"/misc/ping"` |  |
| pgadmin.probes.liveness.periodSeconds | int | `15` |  |
| pgadmin.probes.liveness.port | int | `80` |  |
| pgadmin.probes.liveness.successThreshold | int | `1` |  |
| pgadmin.probes.liveness.timeoutSeconds | int | `2` |  |
| pgadmin.probes.liveness.type | string | `"http"` |  |
| pgadmin.probes.readiness.failureThreshold | int | `3` |  |
| pgadmin.probes.readiness.initialDelaySeconds | int | `15` |  |
| pgadmin.probes.readiness.path | string | `"/misc/ping"` |  |
| pgadmin.probes.readiness.periodSeconds | int | `10` |  |
| pgadmin.probes.readiness.port | int | `80` |  |
| pgadmin.probes.readiness.successThreshold | int | `1` |  |
| pgadmin.probes.readiness.timeoutSeconds | int | `2` |  |
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
| postgres.persistence.accessModes[0] | string | `"ReadWriteMany"` |  |
| postgres.persistence.enabled | bool | `true` |  |
| postgres.persistence.size | string | `"5Gi"` |  |
| postgres.persistence.storageClassName | string | `"manual"` |  |
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
| redis.enabled | bool | `true` |  |
| redis.image.pullPolicy | string | `"IfNotPresent"` |  |
| redis.image.repository | string | `"redis"` |  |
| redis.image.tag | string | `"latest"` |  |
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
