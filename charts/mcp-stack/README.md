# mcp-stack

![Version: 0.9.0](https://img.shields.io/badge/Version-0.9.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 0.9.0](https://img.shields.io/badge/AppVersion-0.9.0-informational?style=flat-square)

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
| global.imagePullSecrets | list | `[]` |  |
| global.nameOverride | string | `""` |  |
| global.fullnameOverride | string | `""` |  |
| mcpContextForge.replicaCount | int | `2` |  |
| mcpContextForge.hpa | object | `{"enabled":true,"maxReplicas":10,"minReplicas":2,"targetCPUUtilizationPercentage":90,"targetMemoryUtilizationPercentage":90}` | ------------------------------------------------------------------ |
| mcpContextForge.image.repository | string | `"ghcr.io/ibm/mcp-context-forge"` |  |
| mcpContextForge.image.tag | string | `"latest"` |  |
| mcpContextForge.image.pullPolicy | string | `"Always"` |  |
| mcpContextForge.service.type | string | `"ClusterIP"` |  |
| mcpContextForge.service.port | int | `80` |  |
| mcpContextForge.containerPort | int | `4444` |  |
| mcpContextForge.probes.startup.type | string | `"exec"` |  |
| mcpContextForge.probes.startup.command[0] | string | `"sh"` |  |
| mcpContextForge.probes.startup.command[1] | string | `"-c"` |  |
| mcpContextForge.probes.startup.command[2] | string | `"sleep 10"` |  |
| mcpContextForge.probes.startup.timeoutSeconds | int | `15` |  |
| mcpContextForge.probes.startup.periodSeconds | int | `5` |  |
| mcpContextForge.probes.startup.failureThreshold | int | `1` |  |
| mcpContextForge.probes.readiness.type | string | `"http"` |  |
| mcpContextForge.probes.readiness.path | string | `"/ready"` |  |
| mcpContextForge.probes.readiness.port | int | `4444` |  |
| mcpContextForge.probes.readiness.initialDelaySeconds | int | `15` |  |
| mcpContextForge.probes.readiness.periodSeconds | int | `10` |  |
| mcpContextForge.probes.readiness.timeoutSeconds | int | `2` |  |
| mcpContextForge.probes.readiness.successThreshold | int | `1` |  |
| mcpContextForge.probes.readiness.failureThreshold | int | `3` |  |
| mcpContextForge.probes.liveness.type | string | `"http"` |  |
| mcpContextForge.probes.liveness.path | string | `"/health"` |  |
| mcpContextForge.probes.liveness.port | int | `4444` |  |
| mcpContextForge.probes.liveness.initialDelaySeconds | int | `10` |  |
| mcpContextForge.probes.liveness.periodSeconds | int | `15` |  |
| mcpContextForge.probes.liveness.timeoutSeconds | int | `2` |  |
| mcpContextForge.probes.liveness.successThreshold | int | `1` |  |
| mcpContextForge.probes.liveness.failureThreshold | int | `3` |  |
| mcpContextForge.resources.limits.cpu | string | `"200m"` |  |
| mcpContextForge.resources.limits.memory | string | `"1024Mi"` |  |
| mcpContextForge.resources.requests.cpu | string | `"100m"` |  |
| mcpContextForge.resources.requests.memory | string | `"512Mi"` |  |
| mcpContextForge.ingress.enabled | bool | `true` |  |
| mcpContextForge.ingress.className | string | `"nginx"` |  |
| mcpContextForge.ingress.host | string | `"gateway.local"` |  |
| mcpContextForge.ingress.path | string | `"/"` |  |
| mcpContextForge.ingress.pathType | string | `"Prefix"` |  |
| mcpContextForge.ingress.annotations."nginx.ingress.kubernetes.io/rewrite-target" | string | `"/"` |  |
| mcpContextForge.env.host | string | `"0.0.0.0"` |  |
| mcpContextForge.env.postgres.port | int | `5432` |  |
| mcpContextForge.env.postgres.db | string | `"postgresdb"` |  |
| mcpContextForge.env.postgres.userKey | string | `"POSTGRES_USER"` |  |
| mcpContextForge.env.postgres.passwordKey | string | `"POSTGRES_PASSWORD"` |  |
| mcpContextForge.env.redis.port | int | `6379` |  |
| mcpContextForge.config.GUNICORN_WORKERS | string | `"2"` |  |
| mcpContextForge.config.GUNICORN_TIMEOUT | string | `"600"` |  |
| mcpContextForge.config.GUNICORN_MAX_REQUESTS | string | `"10000"` |  |
| mcpContextForge.config.GUNICORN_MAX_REQUESTS_JITTER | string | `"100"` |  |
| mcpContextForge.config.GUNICORN_PRELOAD_APP | string | `"true"` |  |
| mcpContextForge.config.APP_NAME | string | `"MCP_Gateway"` |  |
| mcpContextForge.config.HOST | string | `"0.0.0.0"` |  |
| mcpContextForge.config.PORT | string | `"4444"` |  |
| mcpContextForge.config.APP_ROOT_PATH | string | `""` |  |
| mcpContextForge.config.DB_POOL_SIZE | string | `"200"` |  |
| mcpContextForge.config.DB_MAX_OVERFLOW | string | `"10"` |  |
| mcpContextForge.config.DB_POOL_TIMEOUT | string | `"30"` |  |
| mcpContextForge.config.DB_POOL_RECYCLE | string | `"3600"` |  |
| mcpContextForge.config.CACHE_TYPE | string | `"redis"` |  |
| mcpContextForge.config.CACHE_PREFIX | string | `"mcpgw"` |  |
| mcpContextForge.config.SESSION_TTL | string | `"3600"` |  |
| mcpContextForge.config.MESSAGE_TTL | string | `"600"` |  |
| mcpContextForge.config.REDIS_MAX_RETRIES | string | `"3"` |  |
| mcpContextForge.config.REDIS_RETRY_INTERVAL_MS | string | `"2000"` |  |
| mcpContextForge.config.DB_MAX_RETRIES | string | `"3"` |  |
| mcpContextForge.config.DB_RETRY_INTERVAL_MS | string | `"2000"` |  |
| mcpContextForge.config.PROTOCOL_VERSION | string | `"2025-03-26"` |  |
| mcpContextForge.config.MCPGATEWAY_UI_ENABLED | string | `"true"` |  |
| mcpContextForge.config.MCPGATEWAY_UI_AIRGAPPED | string | `"false"` |  |
| mcpContextForge.config.MCPGATEWAY_ADMIN_API_ENABLED | string | `"true"` |  |
| mcpContextForge.config.ENVIRONMENT | string | `"development"` |  |
| mcpContextForge.config.APP_DOMAIN | string | `"localhost"` |  |
| mcpContextForge.config.CORS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.CORS_ALLOW_CREDENTIALS | string | `"true"` |  |
| mcpContextForge.config.ALLOWED_ORIGINS | string | `"[\"http://localhost\",\"http://localhost:4444\"]"` |  |
| mcpContextForge.config.SKIP_SSL_VERIFY | string | `"false"` |  |
| mcpContextForge.config.SECURITY_HEADERS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.X_FRAME_OPTIONS | string | `"DENY"` |  |
| mcpContextForge.config.X_CONTENT_TYPE_OPTIONS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.X_XSS_PROTECTION_ENABLED | string | `"true"` |  |
| mcpContextForge.config.X_DOWNLOAD_OPTIONS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.HSTS_ENABLED | string | `"true"` |  |
| mcpContextForge.config.HSTS_MAX_AGE | string | `"31536000"` |  |
| mcpContextForge.config.HSTS_INCLUDE_SUBDOMAINS | string | `"true"` |  |
| mcpContextForge.config.REMOVE_SERVER_HEADERS | string | `"true"` |  |
| mcpContextForge.config.SECURE_COOKIES | string | `"true"` |  |
| mcpContextForge.config.COOKIE_SAMESITE | string | `"lax"` |  |
| mcpContextForge.config.LOG_LEVEL | string | `"INFO"` |  |
| mcpContextForge.config.LOG_FORMAT | string | `"json"` |  |
| mcpContextForge.config.TRANSPORT_TYPE | string | `"all"` |  |
| mcpContextForge.config.WEBSOCKET_PING_INTERVAL | string | `"30"` |  |
| mcpContextForge.config.SSE_RETRY_TIMEOUT | string | `"5000"` |  |
| mcpContextForge.config.USE_STATEFUL_SESSIONS | string | `"false"` |  |
| mcpContextForge.config.JSON_RESPONSE_ENABLED | string | `"true"` |  |
| mcpContextForge.config.FEDERATION_ENABLED | string | `"true"` |  |
| mcpContextForge.config.FEDERATION_DISCOVERY | string | `"false"` |  |
| mcpContextForge.config.FEDERATION_PEERS | string | `"[]"` |  |
| mcpContextForge.config.FEDERATION_TIMEOUT | string | `"30"` |  |
| mcpContextForge.config.FEDERATION_SYNC_INTERVAL | string | `"300"` |  |
| mcpContextForge.config.RESOURCE_CACHE_SIZE | string | `"1000"` |  |
| mcpContextForge.config.RESOURCE_CACHE_TTL | string | `"3600"` |  |
| mcpContextForge.config.MAX_RESOURCE_SIZE | string | `"10485760"` |  |
| mcpContextForge.config.TOOL_TIMEOUT | string | `"60"` |  |
| mcpContextForge.config.MAX_TOOL_RETRIES | string | `"3"` |  |
| mcpContextForge.config.TOOL_RATE_LIMIT | string | `"100"` |  |
| mcpContextForge.config.TOOL_CONCURRENT_LIMIT | string | `"10"` |  |
| mcpContextForge.config.PROMPT_CACHE_SIZE | string | `"100"` |  |
| mcpContextForge.config.MAX_PROMPT_SIZE | string | `"102400"` |  |
| mcpContextForge.config.PROMPT_RENDER_TIMEOUT | string | `"10"` |  |
| mcpContextForge.config.HEALTH_CHECK_INTERVAL | string | `"60"` |  |
| mcpContextForge.config.HEALTH_CHECK_TIMEOUT | string | `"10"` |  |
| mcpContextForge.config.UNHEALTHY_THRESHOLD | string | `"3"` |  |
| mcpContextForge.config.FILELOCK_NAME | string | `"gateway_healthcheck_init.lock"` |  |
| mcpContextForge.config.DEV_MODE | string | `"false"` |  |
| mcpContextForge.config.RELOAD | string | `"false"` |  |
| mcpContextForge.config.DEBUG | string | `"false"` |  |
| mcpContextForge.secret.BASIC_AUTH_USER | string | `"admin"` |  |
| mcpContextForge.secret.BASIC_AUTH_PASSWORD | string | `"changeme"` |  |
| mcpContextForge.secret.AUTH_REQUIRED | string | `"true"` |  |
| mcpContextForge.secret.JWT_SECRET_KEY | string | `"my-test-key"` |  |
| mcpContextForge.secret.JWT_ALGORITHM | string | `"HS256"` |  |
| mcpContextForge.secret.TOKEN_EXPIRY | string | `"10080"` |  |
| mcpContextForge.secret.AUTH_ENCRYPTION_SECRET | string | `"my-test-salt"` |  |
| mcpContextForge.secret.ENABLE_ED25519_SIGNING | string | `"false"` | Enable Ed25519 signing for certificates |
| mcpContextForge.secret.ED25519_PRIVATE_KEY | string | `""` | Ed25519 private key for signing (PEM format) |
| mcpContextForge.secret.PREV_ED25519_PRIVATE_KEY | string | `""` | Previous Ed25519 private key for key rotation |
| mcpContextForge.envFrom[0].secretRef.name | string | `"mcp-gateway-secret"` |  |
| mcpContextForge.envFrom[1].configMapRef.name | string | `"mcp-gateway-config"` |  |
| migration.enabled | bool | `true` |  |
| migration.restartPolicy | string | `"Never"` |  |
| migration.backoffLimit | int | `3` |  |
| migration.activeDeadlineSeconds | int | `600` |  |
| migration.image.repository | string | `"ghcr.io/ibm/mcp-context-forge"` |  |
| migration.image.tag | string | `"latest"` |  |
| migration.image.pullPolicy | string | `"Always"` |  |
| migration.resources.limits.cpu | string | `"200m"` |  |
| migration.resources.limits.memory | string | `"512Mi"` |  |
| migration.resources.requests.cpu | string | `"100m"` |  |
| migration.resources.requests.memory | string | `"256Mi"` |  |
| migration.command.waitForDb | string | `"python3 /app/mcpgateway/utils/db_isready.py --max-tries 30 --interval 2 --timeout 5"` |  |
| migration.command.migrate | string | `"alembic upgrade head || echo '⚠️ Migration check failed'"` |  |
| postgres.enabled | bool | `true` |  |
| postgres.image.repository | string | `"postgres"` |  |
| postgres.image.tag | string | `"17"` |  |
| postgres.image.pullPolicy | string | `"IfNotPresent"` |  |
| postgres.service.type | string | `"ClusterIP"` |  |
| postgres.service.port | int | `5432` |  |
| postgres.persistence.enabled | bool | `true` |  |
| postgres.persistence.storageClassName | string | `"manual"` |  |
| postgres.persistence.accessModes[0] | string | `"ReadWriteMany"` |  |
| postgres.persistence.size | string | `"5Gi"` |  |
| postgres.existingSecret | string | `""` |  |
| postgres.credentials.database | string | `"postgresdb"` |  |
| postgres.credentials.user | string | `"admin"` |  |
| postgres.credentials.password | string | `"test123"` |  |
| postgres.resources.limits.cpu | string | `"1000m"` |  |
| postgres.resources.limits.memory | string | `"1Gi"` |  |
| postgres.resources.requests.cpu | string | `"500m"` |  |
| postgres.resources.requests.memory | string | `"64Mi"` |  |
| postgres.probes.readiness.type | string | `"exec"` |  |
| postgres.probes.readiness.command[0] | string | `"pg_isready"` |  |
| postgres.probes.readiness.command[1] | string | `"-U"` |  |
| postgres.probes.readiness.command[2] | string | `"$(POSTGRES_USER)"` |  |
| postgres.probes.readiness.initialDelaySeconds | int | `15` |  |
| postgres.probes.readiness.periodSeconds | int | `10` |  |
| postgres.probes.readiness.timeoutSeconds | int | `3` |  |
| postgres.probes.readiness.successThreshold | int | `1` |  |
| postgres.probes.readiness.failureThreshold | int | `3` |  |
| postgres.probes.liveness.type | string | `"exec"` |  |
| postgres.probes.liveness.command[0] | string | `"pg_isready"` |  |
| postgres.probes.liveness.command[1] | string | `"-U"` |  |
| postgres.probes.liveness.command[2] | string | `"$(POSTGRES_USER)"` |  |
| postgres.probes.liveness.initialDelaySeconds | int | `10` |  |
| postgres.probes.liveness.periodSeconds | int | `15` |  |
| postgres.probes.liveness.timeoutSeconds | int | `3` |  |
| postgres.probes.liveness.successThreshold | int | `1` |  |
| postgres.probes.liveness.failureThreshold | int | `5` |  |
| redis.enabled | bool | `true` |  |
| redis.image.repository | string | `"redis"` |  |
| redis.image.tag | string | `"latest"` |  |
| redis.image.pullPolicy | string | `"IfNotPresent"` |  |
| redis.service.type | string | `"ClusterIP"` |  |
| redis.service.port | int | `6379` |  |
| redis.resources.limits.cpu | string | `"100m"` |  |
| redis.resources.limits.memory | string | `"256Mi"` |  |
| redis.resources.requests.cpu | string | `"50m"` |  |
| redis.resources.requests.memory | string | `"16Mi"` |  |
| redis.probes.readiness.type | string | `"exec"` |  |
| redis.probes.readiness.command[0] | string | `"redis-cli"` |  |
| redis.probes.readiness.command[1] | string | `"PING"` |  |
| redis.probes.readiness.initialDelaySeconds | int | `10` |  |
| redis.probes.readiness.periodSeconds | int | `10` |  |
| redis.probes.readiness.timeoutSeconds | int | `2` |  |
| redis.probes.readiness.successThreshold | int | `1` |  |
| redis.probes.readiness.failureThreshold | int | `3` |  |
| redis.probes.liveness.type | string | `"exec"` |  |
| redis.probes.liveness.command[0] | string | `"redis-cli"` |  |
| redis.probes.liveness.command[1] | string | `"PING"` |  |
| redis.probes.liveness.initialDelaySeconds | int | `5` |  |
| redis.probes.liveness.periodSeconds | int | `15` |  |
| redis.probes.liveness.timeoutSeconds | int | `2` |  |
| redis.probes.liveness.successThreshold | int | `1` |  |
| redis.probes.liveness.failureThreshold | int | `5` |  |
| pgadmin.enabled | bool | `true` |  |
| pgadmin.image.repository | string | `"dpage/pgadmin4"` |  |
| pgadmin.image.tag | string | `"latest"` |  |
| pgadmin.image.pullPolicy | string | `"IfNotPresent"` |  |
| pgadmin.service.type | string | `"ClusterIP"` |  |
| pgadmin.service.port | int | `80` |  |
| pgadmin.env.email | string | `"admin@example.com"` |  |
| pgadmin.env.password | string | `"admin123"` |  |
| pgadmin.resources.limits.cpu | string | `"200m"` |  |
| pgadmin.resources.limits.memory | string | `"256Mi"` |  |
| pgadmin.resources.requests.cpu | string | `"100m"` |  |
| pgadmin.resources.requests.memory | string | `"128Mi"` |  |
| pgadmin.probes.readiness.type | string | `"http"` |  |
| pgadmin.probes.readiness.path | string | `"/misc/ping"` |  |
| pgadmin.probes.readiness.port | int | `80` |  |
| pgadmin.probes.readiness.initialDelaySeconds | int | `15` |  |
| pgadmin.probes.readiness.periodSeconds | int | `10` |  |
| pgadmin.probes.readiness.timeoutSeconds | int | `2` |  |
| pgadmin.probes.readiness.successThreshold | int | `1` |  |
| pgadmin.probes.readiness.failureThreshold | int | `3` |  |
| pgadmin.probes.liveness.type | string | `"http"` |  |
| pgadmin.probes.liveness.path | string | `"/misc/ping"` |  |
| pgadmin.probes.liveness.port | int | `80` |  |
| pgadmin.probes.liveness.initialDelaySeconds | int | `10` |  |
| pgadmin.probes.liveness.periodSeconds | int | `15` |  |
| pgadmin.probes.liveness.timeoutSeconds | int | `2` |  |
| pgadmin.probes.liveness.successThreshold | int | `1` |  |
| pgadmin.probes.liveness.failureThreshold | int | `5` |  |
| redisCommander.enabled | bool | `true` |  |
| redisCommander.image.repository | string | `"rediscommander/redis-commander"` |  |
| redisCommander.image.tag | string | `"latest"` |  |
| redisCommander.image.pullPolicy | string | `"IfNotPresent"` |  |
| redisCommander.service.type | string | `"ClusterIP"` |  |
| redisCommander.service.port | int | `8081` |  |
| redisCommander.resources.limits.cpu | string | `"100m"` |  |
| redisCommander.resources.limits.memory | string | `"256Mi"` |  |
| redisCommander.resources.requests.cpu | string | `"50m"` |  |
| redisCommander.resources.requests.memory | string | `"128Mi"` |  |
| redisCommander.probes.readiness.type | string | `"http"` |  |
| redisCommander.probes.readiness.path | string | `"/"` |  |
| redisCommander.probes.readiness.port | int | `8081` |  |
| redisCommander.probes.readiness.initialDelaySeconds | int | `15` |  |
| redisCommander.probes.readiness.periodSeconds | int | `10` |  |
| redisCommander.probes.readiness.timeoutSeconds | int | `2` |  |
| redisCommander.probes.readiness.successThreshold | int | `1` |  |
| redisCommander.probes.readiness.failureThreshold | int | `3` |  |
| redisCommander.probes.liveness.type | string | `"http"` |  |
| redisCommander.probes.liveness.path | string | `"/"` |  |
| redisCommander.probes.liveness.port | int | `8081` |  |
| redisCommander.probes.liveness.initialDelaySeconds | int | `10` |  |
| redisCommander.probes.liveness.periodSeconds | int | `15` |  |
| redisCommander.probes.liveness.timeoutSeconds | int | `2` |  |
| redisCommander.probes.liveness.successThreshold | int | `1` |  |
| redisCommander.probes.liveness.failureThreshold | int | `5` |  |
| mcpFastTimeServer.enabled | bool | `true` |  |
| mcpFastTimeServer.replicaCount | int | `2` |  |
| mcpFastTimeServer.image.repository | string | `"ghcr.io/ibm/fast-time-server"` |  |
| mcpFastTimeServer.image.tag | string | `"0.9.0"` |  |
| mcpFastTimeServer.image.pullPolicy | string | `"IfNotPresent"` |  |
| mcpFastTimeServer.port | int | `8080` |  |
| mcpFastTimeServer.ingress.enabled | bool | `true` |  |
| mcpFastTimeServer.ingress.path | string | `"/fast-time"` |  |
| mcpFastTimeServer.ingress.pathType | string | `"Prefix"` |  |
| mcpFastTimeServer.ingress.servicePort | int | `80` |  |
| mcpFastTimeServer.probes.readiness.type | string | `"http"` |  |
| mcpFastTimeServer.probes.readiness.path | string | `"/health"` |  |
| mcpFastTimeServer.probes.readiness.port | int | `8080` |  |
| mcpFastTimeServer.probes.readiness.initialDelaySeconds | int | `3` |  |
| mcpFastTimeServer.probes.readiness.periodSeconds | int | `10` |  |
| mcpFastTimeServer.probes.readiness.timeoutSeconds | int | `2` |  |
| mcpFastTimeServer.probes.readiness.successThreshold | int | `1` |  |
| mcpFastTimeServer.probes.readiness.failureThreshold | int | `3` |  |
| mcpFastTimeServer.probes.liveness.type | string | `"http"` |  |
| mcpFastTimeServer.probes.liveness.path | string | `"/health"` |  |
| mcpFastTimeServer.probes.liveness.port | int | `8080` |  |
| mcpFastTimeServer.probes.liveness.initialDelaySeconds | int | `3` |  |
| mcpFastTimeServer.probes.liveness.periodSeconds | int | `15` |  |
| mcpFastTimeServer.probes.liveness.timeoutSeconds | int | `2` |  |
| mcpFastTimeServer.probes.liveness.successThreshold | int | `1` |  |
| mcpFastTimeServer.probes.liveness.failureThreshold | int | `3` |  |
| mcpFastTimeServer.resources.limits.cpu | string | `"50m"` |  |
| mcpFastTimeServer.resources.limits.memory | string | `"64Mi"` |  |
| mcpFastTimeServer.resources.requests.cpu | string | `"25m"` |  |
| mcpFastTimeServer.resources.requests.memory | string | `"10Mi"` |  |

----------------------------------------------

## Ed25519 Certificate Signing

The MCP Gateway supports **Ed25519 digital signatures** for certificate validation and integrity verification. This ensures that CA certificates used by the gateway are authentic and haven't been tampered with.

### Configuration

Ed25519 signing is configured through secret values in `mcpContextForge.secret`:

```yaml
mcpContextForge:
  secret:
    # Enable Ed25519 signing
    ENABLE_ED25519_SIGNING: "true"

    # Current signing key (PEM format)
    ED25519_PRIVATE_KEY: |
      -----BEGIN PRIVATE KEY-----
      MC4CAQAwBQYDK2VwBCIEIJ5pW... (your key here)
      -----END PRIVATE KEY-----

    # Previous key for rotation (optional)
    PREV_ED25519_PRIVATE_KEY: |
      -----BEGIN PRIVATE KEY-----
      MC4CAQAwBQYDK2VwBCIEIOld... (old key here)
      -----END PRIVATE KEY-----
```

### How It Works

1. **Certificate Signing** - When `ENABLE_ED25519_SIGNING=true`, the gateway signs the CA certificate of each MCP server/gateway using the Ed25519 private key.

2. **Certificate Validation** - Before using a CA certificate for subsequent calls, the gateway validates its signature to ensure authenticity and integrity.

3. **Disabled Mode** - When `ENABLE_ED25519_SIGNING=false` (default), certificates are neither signed nor validated.

### Key Generation

Generate a new Ed25519 key pair:

```bash
# Using the gateway's built-in utility
kubectl exec -it deployment/mcp-context-forge -- \
  python mcpgateway/utils/generate_keys.py

# Or using a running pod
kubectl exec -it <pod-name> -- \
  python mcpgateway/utils/generate_keys.py
```

The output will show:
- Private key (set this to `ED25519_PRIVATE_KEY`)
- Public key (derived automatically from private key)

### Key Rotation

To rotate keys without invalidating existing signed certificates:

1. Move the current `ED25519_PRIVATE_KEY` value to `PREV_ED25519_PRIVATE_KEY`
2. Generate a new key pair using the command above
3. Set the new private key to `ED25519_PRIVATE_KEY`
4. Apply the updated Helm values

The gateway will automatically re-sign valid certificates at the point of key change.

### Best Practices

- **Store keys securely**: Use Kubernetes Secrets or external secret management (Vault, AWS Secrets Manager, etc.)
- **Rotate keys periodically**: Recommended every 90-180 days
- **Never commit keys to Git**: Use encrypted values files or external secret injection
- **Use separate keys per environment**: Development, staging, and production should have different keys

### Example with External Secrets

Using [External Secrets Operator](https://external-secrets.io/):

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: mcp-gateway-ed25519-keys
spec:
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: mcp-gateway-secret
    template:
      mergePolicy: Merge
  data:
    - secretKey: ED25519_PRIVATE_KEY
      remoteRef:
        key: mcp-gateway/ed25519
        property: private_key
    - secretKey: PREV_ED25519_PRIVATE_KEY
      remoteRef:
        key: mcp-gateway/ed25519
        property: prev_private_key
```

----------------------------------------------
