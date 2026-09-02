# ContextForge

> 🌏 **语言 / Language:** **简体中文（当前）** | [English](./README.en.md)

> 一个开源注册表与代理，将 MCP、A2A 与 REST/gRPC API 统一联邦到一个端点，提供集中式治理、发现与可观测性。优化 Agent 与 Tool 调用，并支持插件。

![ContextForge Banner](docs/docs/images/contextforge-logo_horizontal_black.png)

**ContextForge** 是一个开源的注册表与代理，把各类工具、Agent 和 API 联邦到统一的干净端点，为你的 AI 客户端提供服务。它横跨整个 AI 基础设施提供集中式治理、发现与可观测性：

- **工具网关（Tools Gateway）** —— MCP、REST、gRPC 转 MCP 翻译，以及 TOON 压缩
- **Agent 网关（Agent Gateway）** —— A2A 协议、兼容 OpenAI 与 Anthropic 的 Agent 路由
- **API 网关（API Gateway）** —— 限流、认证、重试，以及 REST 服务的反向代理
- **插件扩展（Plugin Extensibility）** —— 40+ 插件，支持额外的传输层、协议与集成
- **可观测性（Observability）** —— 通过 Phoenix、Jaeger、Zipkin 等 OTLP 后端实现 OpenTelemetry 链路追踪

它作为完全合规的 MCP 服务器运行，可通过 PyPI 或 Docker 部署，并可借助 Redis 联邦与缓存扩展到 Kubernetes 多集群环境。

---

## 目录

- [项目概览与目标](#项目概览与目标)
- [快速开始 —— PyPI](#快速开始--pypi)
- [快速开始 —— 容器](#快速开始--容器)
- [安装](#安装)
- [升级](#升级)
- [配置](#配置)
- [运行](#运行)
- [新增功能](#新增功能)
- [云部署](#云部署)
- [API 参考](#api-参考)
- [测试](#测试)
- [项目结构](#项目结构)
- [开发](#开发)
- [故障排查](#故障排查)
- [参与贡献](#参与贡献)
- [更新日志](#更新日志)
- [许可证](#许可证)

---

## 项目概览与目标

**ContextForge** 是一个开源注册表与代理，联邦任何遵循[模型上下文协议（Model Context Protocol, MCP）](https://modelcontextprotocol.io)的 MCP 服务器、A2A 服务器，或 REST/gRPC API，提供集中式治理、发现与可观测性。它优化 Agent 和 Tool 调用，并支持插件。

当前支持的功能：

- 跨多个 MCP 与 REST 服务的联邦
- **A2A（Agent-to-Agent）集成**，用于外部 AI Agent（OpenAI、Anthropic、自定义）
- **gRPC 转 MCP 翻译**，基于自动的 reflection 服务发现
- 将遗留 API 虚拟化为符合 MCP 规范的 Tool 与服务器
- 多种传输层：HTTP、JSON-RPC、WebSocket、SSE（可配置 keepalive）、stdio 与 streamable-HTTP
- 管理界面 Admin UI，支持实时管理、配置与日志监控（支持离线部署）
- 内置认证、重试与限流，支持用户级 OAuth Token 与无条件 X-Upstream-Authorization 头
- **OpenTelemetry 可观测性**，支持 Phoenix、Jaeger、Zipkin 等 OTLP 后端
- 通过 Docker 或 PyPI 扩展部署、Redis 缓存与多集群联邦

---

## 快速开始 —— PyPI

ContextForge 已发布到 [PyPI](https://pypi.org/project/mcp-contextforge-gateway/)，包名为 `mcp-contextforge-gateway`。

> ⚠️ **每个环境都必须配置 `JWT_SECRET_KEY` 与 `AUTH_ENCRYPTION_SECRET` —— 包括本地开发环境。** 缺少它们网关无法启动。首次运行前请用 `python3 -m mcpgateway.scripts.init_secrets` 生成真实密钥。

**TLDR** —— 使用 [uv](https://docs.astral.sh/uv/) 单条命令：

```bash
# 1️⃣  生成安全密钥（创建 .env.secrets）
python3 -m mcpgateway.scripts.init_secrets

# 2️⃣  导出生成的值
export JWT_SECRET_KEY="$(grep '^JWT_SECRET_KEY=' .env.secrets | cut -d= -f2)"
export AUTH_ENCRYPTION_SECRET="$(grep '^AUTH_ENCRYPTION_SECRET=' .env.secrets | cut -d= -f2)"

# 3️⃣  启动网关
JWT_SECRET_KEY="$JWT_SECRET_KEY" \
AUTH_ENCRYPTION_SECRET="$AUTH_ENCRYPTION_SECRET" \
MCPGATEWAY_UI_ENABLED=true \
MCPGATEWAY_ADMIN_API_ENABLED=true \
PLATFORM_ADMIN_EMAIL=admin@example.com \
uvx --from mcp-contextforge-gateway mcpgateway --host 0.0.0.0 --port 4444
```

<details>
<summary><strong>📋 前置条件</strong></summary>

* **Python ≥ 3.11**
* **curl + jq** —— 仅最后一步冒烟测试需要

</details>

### 1 - 安装并运行（可直接复制粘贴）

```bash
# 1️⃣  创建隔离环境并从 PyPI 安装
mkdir mcpgateway && cd mcpgateway
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install mcp-contextforge-gateway

# 2️⃣  下载 .env.example 并生成真实密钥
curl -O https://raw.githubusercontent.com/IBM/mcp-context-forge/main/.env.example
cp .env.example .env

# 生成密码学安全密钥到 .env.secrets
python3 -m mcpgateway.scripts.init_secrets

# 把生成的密钥回填到 .env（替换 __REPLACE_ME__ 占位符）
python3 -m mcpgateway.scripts.init_secrets --patch-env .env

# 3️⃣  启动网关
mcpgateway --host 0.0.0.0 --port 4444 &

# 4️⃣  生成 bearer token 并冒烟测试
export JWT_SECRET_KEY=$(grep '^JWT_SECRET_KEY=' .env | cut -d= -f2)
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --exp 10080 --secret "$JWT_SECRET_KEY")

curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://127.0.0.1:4444/version | jq
```

### 端到端演示（注册本地 MCP 服务器）

```bash
# 1️⃣  用 mcpgateway.translate 启动示例 MCP time server
python3 -m mcpgateway.translate \
     --stdio "docker run --rm -i ghcr.io/ibm/fast-time-server:latest -transport=stdio" \
     --expose-sse \
     --port 8003

# 或使用 uvx 跑官方 mcp-server-git：
pip install uv # 如尚未安装 uvx
python3 -m mcpgateway.translate --stdio "uvx mcp-server-git" --expose-sse --port 9000

# 2️⃣  注册到网关
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"fast_time","url":"http://localhost:8003/sse"}' \
     http://localhost:4444/gateways

# 3️⃣  查看 Tool 目录
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/tools | jq

# 4️⃣  创建虚拟服务器，把这些 Tool 打包进去
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"server":{"name":"time_server","description":"Fast time tools","associated_tools":[<TOOL_ID>]}}' \
     http://localhost:4444/servers | jq

# 5️⃣  列出服务器（应包含新创建的虚拟服务器 UUID）
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/servers | jq
```

---

## 快速开始 —— 容器

使用 GHCR 官方 OCI 镜像，配合 **Docker** 或 **Podman**。

> 注意：目前生产环境不支持 arm64。如果在 Apple Silicon（M1、M2 等）Mac 上运行，可以通过 Rosetta 运行容器，或改用 PyPI 安装。

### 🚀 Docker Compose 快速开始

> **重要提示：** `docker compose up -d` 默认不会本地构建网关镜像 —— 它使用 GHCR 预构建镜像。compose 文件包含 `build:` 块作为后备，但本地构建需要 CI 流水线产生的封闭 wheel 集合。如果在构建过程中遇到 `cryptography` 或依赖解析错误，说明命中了这一点 —— 直接拉取镜像即可（第 2 步会自动处理）。
>
> 运行 `docker compose up -d` 之前**必须**有带真实密钥的 `.env` 文件。使用占位值网关不会启动。

搭建带 PostgreSQL 与 Redis 的完整栈：

```bash
# 1️⃣  克隆仓库
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge

# 2️⃣  用真实密钥设置 .env，并拉取预构建镜像
cp .env.example .env
python3 -m mcpgateway.scripts.init_secrets --patch-env .env

# 拉取 GHCR 预构建镜像（完全避免本地构建）
docker pull ghcr.io/ibm/mcp-context-forge:latest
echo 'IMAGE_LOCAL=ghcr.io/ibm/mcp-context-forge:latest' >> .env

# 仅本地构建 nginx 镜像（小而快，仅本地用）
docker compose build nginx

# 3️⃣  启动完整栈
docker compose up -d

# 4️⃣  查看状态
docker compose ps

# 5️⃣  查看日志
docker compose logs -f gateway

# 6️⃣  访问 Admin UI: http://localhost:8080/admin
#     登录: PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASSWORD（来自 .env）
```

**你获得的内容：**
- 🗄️ **PostgreSQL** —— 生产级数据库，55+ 张表
- 🚀 **ContextForge** —— 带 Admin UI 的全功能网关
- 📊 **Redis** —— 高性能缓存与会话存储
- 🔧 **Admin Tools** —— 用于数据库管理的 pgAdmin、Redis Insight
- 🌐 **Nginx 代理** —— 8080 端口的缓存反向代理

### ☸️ Kubernetes (Helm)

```bash
# Add Helm repository (when available)
# helm repo add mcp-context-forge https://ibm.github.io/mcp-context-forge
# helm repo update

# For now, use local chart
git clone https://github.com/IBM/mcp-context-forge.git
cd mcp-context-forge/charts/mcp-stack

# Generate secrets first
python3 -m mcpgateway.scripts.init_secrets
JWT_SECRET=$(grep '^JWT_SECRET_KEY=' .env.secrets | cut -d= -f2)
ENC_SECRET=$(grep '^AUTH_ENCRYPTION_SECRET=' .env.secrets | cut -d= -f2)

# Install with PostgreSQL (default)
# IMPORTANT: replace <strong-password> with a real password — do not use 'changeme' in production
helm install mcp-gateway . \
  --set mcpContextForge.secret.PLATFORM_ADMIN_EMAIL=admin@yourcompany.com \
  --set mcpContextForge.secret.PLATFORM_ADMIN_PASSWORD=<strong-password> \
  --set mcpContextForge.secret.BASIC_AUTH_PASSWORD=<strong-password> \
  --set "mcpContextForge.secret.JWT_SECRET_KEY=${JWT_SECRET}" \
  --set "mcpContextForge.secret.AUTH_ENCRYPTION_SECRET=${ENC_SECRET}"

# Check deployment status
kubectl get pods -l app.kubernetes.io/name=mcp-context-forge

# Port forward to access Admin UI
kubectl port-forward svc/mcp-gateway-mcp-context-forge 4444:80
# Access: http://localhost:4444/admin

# Generate API token (reads JWT_SECRET_KEY from the pod's environment)
kubectl exec deployment/mcp-gateway-mcp-context-forge -- \
  python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@yourcompany.com --exp 10080 --secret "${JWT_SECRET}"
```

> SSRF note: Helm defaults to strict SSRF settings (`SSRF_ALLOW_PRIVATE_NETWORKS=false`).
> If you register in-cluster tool URLs, allow only your cluster CIDRs via
> `mcpContextForge.config.SSRF_ALLOWED_NETWORKS` or, for local-only benchmark
> setups, temporarily set `SSRF_ALLOW_PRIVATE_NETWORKS=true`.
> See `docs/docs/manage/configuration.md#ssrf-protection` and `docs/docs/deployment/helm.md`.

**Enterprise Features:**
- 🔄 **Auto-scaling** - HPA with CPU/memory targets
- 🗄️ **Database Choice** - PostgreSQL (prod), SQLite (dev)
- 📊 **Observability** - Prometheus metrics, OpenTelemetry tracing
- 🔒 **Security** - RBAC, network policies, secret management
- 🚀 **High Availability** - Multi-replica deployments with Redis clustering
- 📈 **Monitoring** - Built-in Grafana dashboards and alerting

---

### 🐳 Docker（单容器）

```bash
# 先生成密钥（创建 .env.secrets）
python3 -m mcpgateway.scripts.init_secrets
export JWT_SECRET_KEY="$(grep '^JWT_SECRET_KEY=' .env.secrets | cut -d= -f2)"
export AUTH_ENCRYPTION_SECRET="$(grep '^AUTH_ENCRYPTION_SECRET=' .env.secrets | cut -d= -f2)"

docker run -d --name mcpgateway \
  -p 4444:4444 \
  -e MCPGATEWAY_UI_ENABLED=true \
  -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e HOST=0.0.0.0 \
  -e JWT_SECRET_KEY="${JWT_SECRET_KEY}" \
  -e AUTH_ENCRYPTION_SECRET="${AUTH_ENCRYPTION_SECRET}" \
  -e AUTH_REQUIRED=true \
  -e PLATFORM_ADMIN_EMAIL=admin@example.com \
  -e PLATFORM_ADMIN_PASSWORD=<强密码> \
  -e DATABASE_URL=sqlite:///./mcp.db \
  -e SECURE_COOKIES=false \
  ghcr.io/ibm/mcp-context-forge:latest

# 跟踪日志
docker logs -f mcpgateway
```

浏览器访问 **[http://localhost:4444/admin](http://localhost:4444/admin)**，用 `PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD` 登录。

<details>
<summary><strong>高级：持久化存储、host 网络、离线部署</strong></summary>

**持久化 SQLite 数据库：**
```bash
mkdir -p $(pwd)/data && touch $(pwd)/data/mcp.db && chmod 777 $(pwd)/data
docker run -d --name mcpgateway --restart unless-stopped \
  -p 4444:4444 -v $(pwd)/data:/data \
  -e DATABASE_URL=sqlite:////data/mcp.db \
  -e MCPGATEWAY_UI_ENABLED=true -e MCPGATEWAY_ADMIN_API_ENABLED=true \
  -e HOST=0.0.0.0 -e JWT_SECRET_KEY="${JWT_SECRET_KEY}" \
  -e AUTH_ENCRYPTION_SECRET="${AUTH_ENCRYPTION_SECRET}" \
  -e PLATFORM_ADMIN_EMAIL=admin@example.com -e PLATFORM_ADMIN_PASSWORD=<强密码> \
  ghcr.io/ibm/mcp-context-forge:latest
```

**Host 网络**（访问本地 MCP 服务器）：
```bash
docker run -d --name mcpgateway --network=host \
  -v $(pwd)/data:/data -e DATABASE_URL=sqlite:////data/mcp.db \
  -e MCPGATEWAY_UI_ENABLED=true -e HOST=0.0.0.0 -e PORT=4444 \
  -e JWT_SECRET_KEY="${JWT_SECRET_KEY}" -e AUTH_ENCRYPTION_SECRET="${AUTH_ENCRYPTION_SECRET}" \
  ghcr.io/ibm/mcp-context-forge:latest
```

**离线部署（无网络）**：
```bash
docker build -f Containerfile -t mcpgateway:airgapped .
docker run -d --name mcpgateway -p 4444:4444 \
  -e MCPGATEWAY_UI_AIRGAPPED=true -e MCPGATEWAY_UI_ENABLED=true \
  -e HOST=0.0.0.0 -e JWT_SECRET_KEY="${JWT_SECRET_KEY}" \
  -e AUTH_ENCRYPTION_SECRET="${AUTH_ENCRYPTION_SECRET}" \
  mcpgateway:airgapped
```

</details>

---

## 安装

```bash
make venv install-dev      # 创建 .venv + 安装依赖 + 构建 Admin UI
make serve                 # gunicorn 监听 :4444
```

<details>
<summary><strong>备选：UV 或 pip</strong></summary>

```bash
# UV（更快）
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'

# pip
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

</details>

<details>
<summary><strong>PostgreSQL 适配器配置</strong></summary>

为 PostgreSQL 安装 `psycopg` 驱动：

```bash
# 先安装系统依赖
# Debian/Ubuntu: sudo apt-get install libpq-dev
# macOS: brew install libpq

uv pip install 'psycopg[binary]'   # 开发（预构建 wheel）
# 或: uv pip install 'psycopg[c]'  # 生产（需要编译器）
```

连接 URL 格式：
```bash
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/mcp
```

</details>

---

## 升级

升级说明、迁移指南与回滚步骤，请参见：

- **[升级指南](https://ibm.github.io/mcp-context-forge/manage/upgrade/)** —— 通用升级流程
- **[MIGRATION.md](./MIGRATION.md)** —— 破坏性变更与分步升级说明
- **[CHANGELOG.md](./CHANGELOG.md)** —— 版本历史与破坏性变更

---

## 配置

> ⚠️ 如果 `.env` 缺少必需变量或值无效，网关会在启动时通过 Pydantic 快速失败并报错。

复制[.env.example](https://github.com/IBM/mcp-context-forge/blob/main/.env.example)到 `.env`，并更新以下安全敏感的值。

### 🔐 必需：启动前设置

以下变量**必须在网关启动前设置**。没有可用默认值 —— 缺失或为占位值时应用启动即失败：

| 变量 | 说明 | 如何生成 |
|----------|-------------|----------|
| `JWT_SECRET_KEY` | 用于签名 JWT 的 HMAC 密钥（32+ 字符） | `python3 -m mcpgateway.scripts.init_secrets` |
| `AUTH_ENCRYPTION_SECRET` | 加密存储凭据的口令 | `python3 -m mcpgateway.scripts.init_secrets` |

以下变量有非安全默认值，**生产环境应修改**：

| 变量 | 说明 | 默认值 |
|----------|-------------|---------|
| `BASIC_AUTH_USER` | HTTP Basic 认证用户名 | `admin` |
| `BASIC_AUTH_PASSWORD` | HTTP Basic 认证密码 | **必填 —— 无默认值；通过 `make init-secrets-patch-env` 设置** |
| `PLATFORM_ADMIN_EMAIL` | bootstrap 管理员邮箱 | `admin@example.com` |
| `PLATFORM_ADMIN_PASSWORD` | bootstrap 管理员密码 | **必填 —— 首次运行前设置强密码** |
| `PLATFORM_ADMIN_FULL_NAME` | bootstrap 管理员显示名 | `Admin User` |

### 🔒 安全默认（默认即安全）

这些设置出于安全考虑默认启用，仅向后兼容时关闭：

| 变量 | 说明 | 默认值 |
|----------|-------------|---------|
| `REQUIRE_JTI` | 要求 Token 带 JTI 声明以支持撤销 | `true` |
| `REQUIRE_TOKEN_EXPIRATION` | 要求 Token 带 exp 声明 | `true` |
| `PUBLIC_REGISTRATION_ENABLED` | 允许公开用户自助注册 | `false` |

### 🌐 UAID 跨网关路由安全

跨网关 UAID 路由需要显式安全配置：

1. **配置域名白名单：**
   ```bash
   UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]
   ```

2. **确保 JWT 互信：**
   - 两个网关必须信任同一个 JWT 签发方
   - 方案 A：共享密钥（所有网关使用相同的 `JWT_SECRET_KEY`）
   - 方案 B：联邦 SSO（Google、GitHub、Entra ID）

3. **启用认证：**
   ```bash
   AUTH_REQUIRED=true
   UAID_FORWARD_AUTH=true
   ```

**安全特性：**
- ✅ 失败安全默认：空白名单会阻断所有跨网关路由
- ✅ Bearer Token 转发：跨跳保持用户认证
- ✅ 审计追踪：在头中记录源网关与用户
- ✅ 清晰的错误信息：配置错误在启动和运行时都会被捕获

---

## 运行

### 快速参考

| 命令 | 服务器 | 端口 | 数据库 | 用途 |
|---------|--------|------|----------|----------|
| `make dev` | Uvicorn | **8000** | SQLite | 开发（单实例，自动重载） |
| `make serve` | Gunicorn | **4444** | SQLite | 生产单节点（多 worker） |
| `make serve-ssl` | Gunicorn | **4444** | SQLite | 生产单节点 HTTPS |
| `make compose-up` | Docker Compose + Nginx | **8080** | PostgreSQL + Redis | 完整栈（3 副本，负载均衡） |

### 开发服务器（Uvicorn）

```bash
make dev                 # Uvicorn 监听 :8000，自动重载，SQLite
# 或
./run.sh --reload --log debug --workers 2
```

### 生产服务器（Gunicorn）

```bash
make serve               # Gunicorn 监听 :4444，多 worker
make serve-ssl           # Gunicorn 在 HTTPS 之后监听 :4444（使用 ./certs）
```

### 手动（Uvicorn）

```bash
uvicorn mcpgateway.main:app --host 0.0.0.0 --port 4444 --workers 4
```

---

## 新增功能

本仓库基于上游 ContextForge 增强的三大功能模块：**gRPC 增强（Schema 服务与健康监控）**、**受管外部 SQL 数据 API**、以及**统一 API 调试平台**。源码安全兜底默认关闭这些实验功能；本项目的内网发行镜像、Compose 和 Helm 配置会显式启用 gRPC，SQL 与统一 API 调试平台仍需显式开启。

### gRPC Schema 服务与健康监控

| 环境变量 | 说明 | 默认 |
|----------|------|------|
| `MCPGATEWAY_GRPC_ENABLED` | 启用 gRPC 转 MCP 翻译（实验特性） | 源码 `false`；发行镜像 `true` |
| `MCPGATEWAY_GRPC_REFLECTION_ENABLED` | 默认启用 gRPC server reflection | `true` |
| `MCPGATEWAY_GRPC_HEALTH_ENABLED` | 启用 gRPC 健康监控 | `true` |
| `MCPGATEWAY_GRPC_HEALTH_INTERVAL` | 健康检查间隔（秒，10–3600） | `60` |
| `MCPGATEWAY_GRPC_HEALTH_TIMEOUT` | 健康检查超时（秒，1–60） | `5` |
| `MCPGATEWAY_GRPC_HEALTH_FAILURE_THRESHOLD` | 判定不健康的连续失败次数（1–20） | `3` |
| `MCPGATEWAY_GRPC_MAX_MESSAGE_SIZE` | gRPC 最大消息字节（默认 4MB） | `4194304` |
| `MCPGATEWAY_GRPC_TIMEOUT` | gRPC 调用默认超时（秒） | `30` |
| `MCPGATEWAY_GRPC_TLS_ENABLED` | gRPC 连接默认启用 TLS | `false` |

**Schema 管理端点**（`/admin/grpc/*`）：
- `GET  /admin/grpc` —— 列出 gRPC 服务
- `POST /admin/grpc` —— 注册 gRPC 服务
- `POST /admin/grpc/{service_id}/reflect` —— 反射发现方法
- `POST /admin/grpc/{service_id}/schemas/import` —— 导入 .proto/zip 产物
- `POST /admin/grpc/{service_id}/schemas/{artifact_id}/activate` —— 激活已导入 schema
- `GET  /admin/grpc/{service_id}/schemas/diff` —— 对比 schema 指纹
- `POST /admin/grpc/{service_id}/health` —— 触发健康检查
- `GET  /admin/grpc/{service_id}/health/samples` —— 健康样本历史
- `GET  /admin/grpc/{service_id}/metrics` —— gRPC 健康指标
- `POST /admin/grpc/{service_id}/delete` —— 删除 gRPC 服务

健康监控在后台按间隔探测，将样本持久化到数据库，并暴露 Prometheus 指标。连续失败达到阈值后服务标记为 `unhealthy`。

### Proto 目录扫描（离线 .proto 发现）

| 环境变量 | 说明 | 默认 |
|----------|------|------|
| `MCPGATEWAY_PROTO_SCAN_ENABLED` | 启用基于 manifest 的 Proto 目录扫描 | `false` |
| `MCPGATEWAY_PROTO_SCAN_ROOTS` | 允许扫描的根目录（含 grpc-service.yaml manifest 的 CSV/JSON 列表） | `[]`（空则禁用） |
| `MCPGATEWAY_PROTO_SCAN_INTERVAL` | 扫描间隔（秒，10–3600） | `60` |
| `MCPGATEWAY_PROTO_MAX_UPLOAD_BYTES` | 单个 Proto ZIP/protoset 上传上限 | `8388608` (8MB) |
| `MCPGATEWAY_PROTO_MAX_ZIP_ENTRIES` | 单个 ZIP 允许的最大条目数 | `1024` |
| `MCPGATEWAY_PROTO_MAX_UNCOMPRESSED_BYTES` | ZIP 展开后的最大体积 | `33554432` (32MB) |

该功能扫描配置根目录下的 `grpc-service.yaml` manifest，把 .proto 编译为 descriptor 并注入网关 —— 适用于**未启用 gRPC reflection** 的服务器。

### 受管外部 SQL 数据 API

| 环境变量 | 说明 | 默认 |
|----------|------|------|
| `MCPGATEWAY_SQL_API_ENABLED` | 启用受管外部 SQL 发现与数据 API | `false` |
| `MCPGATEWAY_SQL_DEFAULT_LIMIT` | 查询默认行数上限（1–1000） | `100` |
| `MCPGATEWAY_SQL_MAX_LIMIT` | 查询最大行数上限（1–1000） | `1000` |
| `MCPGATEWAY_SQL_TIMEOUT` | 外部 SQL 语句超时（秒，1–300） | `30` |
| `MCPGATEWAY_SQL_MAX_RESPONSE_BYTES` | 序列化响应最大字节 | `4194304` (4MB) |
| `MCPGATEWAY_SQL_MAX_INCLUDES` | 每次查询最多展开的一跳关联关系（0–5） | `5` |
| `MCPGATEWAY_SQLITE_ALLOWED_ROOTS` | 允许作为外部 SQLite 数据源的根目录（CSV/JSON）；**空则禁止 file-backed SQLite（失败安全）** | `[]` |

**管理端点**（`/admin/sql/*`）：
- `GET   /admin/sql/sources` —— 列出数据源
- `POST  /admin/sql/sources` —— 注册数据源（连接串加密存储）
- `PUT   /admin/sql/sources/{source_id}` —— 更新数据源
- `DELETE /admin/sql/sources/{source_id}` —— 删除数据源
- `POST  /admin/sql/sources/{source_id}/test` —— 测试连通性
- `POST  /admin/sql/sources/{source_id}/discover` —— 发现表结构
- `GET   /admin/sql/tables` —— 列出已发现表
- `PATCH /admin/sql/tables/{table_id}` —— 调整表暴露/操作策略
- `GET   /admin/sql/relations` —— 列出表关系
- `GET   /admin/sql/bindings` —— 列出 API 绑定

**数据端点**（`/api/v1/data/{source_slug}/{schema_slug}/{table_slug}`，需权限 `tools.execute`）：
- `GET   ...` —— 查询（支持 `filter`、`limit`、`offset` 等 URL 参数）
- `POST  ...` —— 插入一行，body 为 `{"values": {...}}`
- `PATCH ...` —— 更新一行，URL 参数 `key` 传 URL-encoded JSON 对象（如 `?key={"id":5}`），body 为 `{"values": {...}}`
- `DELETE ...` —— 删除一行，URL 参数 `key` 传 URL-encoded JSON 对象

> **key 参数契约**：更新/删除必须提供**完整主键或显式唯一键**的 JSON 对象。传裸值或非对象会报 `422 "key must be a non-empty JSON object"`。示例见 `docs/docs/manage/api-usage.md`。

### 统一 API 调试平台

| 环境变量 | 说明 | 默认 |
|----------|------|------|
| `MCPGATEWAY_API_DEBUG_ENABLED` | 启用统一 API 调试器 | `false` |
| `MCPGATEWAY_API_DEBUG_RETENTION_DAYS` | 调试历史保留天数（1–90） | `7` |
| `MCPGATEWAY_API_DEBUG_MAX_HISTORY` | 每用户最多保留的历史条目（1–1000） | `100` |

**端点**（`/admin/debug/*`）：
- `GET /admin/debug/stats` —— 调试调用统计
- `GET /admin/debug/history` —— 调试历史
- 调起任意已注册 Tool 进行真实调用验证

> 三个新功能（SQL、Debugger、Proto 扫描）默认关闭（`false`），未开启时对应端点返回 404。gRPC 健康监控在 `MCPGATEWAY_GRPC_ENABLED=true` 时默认开启。

---

## 云部署

ContextForge 可以部署到任意主流云平台：

| 平台 | 指南 |
|----------|-------|
| **AWS** | [ECS/EKS 部署](https://ibm.github.io/mcp-context-forge/deployment/aws/) |
| **Azure** | [AKS 部署](https://ibm.github.io/mcp-context-forge/deployment/azure/) |
| **Google Cloud** | [Cloud Run](https://ibm.github.io/mcp-context-forge/deployment/google-cloud-run/) |
| **IBM Cloud** | [Code Engine](https://ibm.github.io/mcp-context-forge/deployment/ibm-code-engine/) |
| **Kubernetes** | [Helm Charts](https://ibm.github.io/mcp-context-forge/deployment/minikube/) |
| **OpenShift** | [OpenShift 部署](https://ibm.github.io/mcp-context-forge/deployment/openshift/) |

---

## API 参考

服务器运行时提供交互式 API 文档：

- **[Swagger UI](http://localhost:4444/docs)** —— 直接在浏览器中调用 API
- **[ReDoc](http://localhost:4444/redoc)** —— 浏览完整端点参考

**快速认证：**
```bash
# 从 .env 读取 JWT_SECRET_KEY
export JWT_SECRET_KEY=$(grep '^JWT_SECRET_KEY=' .env | cut -d= -f2)

# 生成 JWT Token
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 10080 --secret "$JWT_SECRET_KEY")

# 测试 API 访问
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/health
```

---

## 测试

```bash
make test            # 运行单元测试
make lint            # 运行所有 linter
make doctest         # 运行 doctest
make coverage        # 生成覆盖率报告
```

---

## 项目结构

```
mcpgateway/          # 核心 FastAPI 应用
├── main.py          # 入口
├── config.py        # Pydantic Settings 配置
├── db.py            # SQLAlchemy ORM 模型
├── schemas.py       # Pydantic 校验 schema
├── services/        # 业务逻辑层（50+ 服务）
├── routers/         # HTTP 端点定义
├── middleware/      # 横切关注点
└── transports/      # SSE、WebSocket、stdio、streamable HTTP

tests/               # 测试套件（7,000+ 测试）
docs/docs/           # 完整文档（MkDocs）
charts/              # Kubernetes/Helm charts
plugins/             # 插件框架与实现
mcp-servers/         # 示例/测试用 MCP 服务器（见下）
```

> **注意：** `mcp-servers/` 目录包含**不受支持的示例和测试服务器**，仅供演示与集成测试使用。它们通常缺少会话管理、持久状态、多租户、认证等生产关注点，未经过与核心 ContextForge 代码库同等严格的审查，**不应在生产中运行**。
>
> **安全提示：** 绝不要在本地文件系统直接运行不可信的 MCP 服务器。务必使用沙箱、容器或 microVM（如 gVisor、Firecracker）并限制能力。注册任何远程 MCP 服务器前请自行进行安全评估。

---

## 开发

```bash
make dev             # 开发服务器，自动重载（:8000）
make test            # 运行测试套件
make lint            # 运行所有 linter
make coverage        # 生成覆盖率报告
```

运行 `make` 查看所有可用目标。

---

## 故障排查

常见问题与解决办法：

| 问题 | 快速解决 |
|-------|-----------|
| `docker compose up` 报 `cryptography` 或依赖解析错误 | 本地构建需要 CI 生产的 wheel 闭包。运行 `docker pull ghcr.io/ibm/mcp-context-forge:latest && echo 'IMAGE_LOCAL=ghcr.io/ibm/mcp-context-forge:latest' >> .env` 后重试 |
| `docker compose up` 报 `SecurityConfigurationError: jwt_secret_key` | `.env` 缺失或含 `__REPLACE_ME__` 占位符。运行 `cp .env.example .env && python3 -m mcpgateway.scripts.init_secrets --patch-env .env` |
| `make dev` —— 8000 端口无响应 | 检查终端是否报 `SecurityConfigurationError` —— 运行 `make ensure-secrets` 后重试。WSL2 上用 `http://127.0.0.1:8000` 而非 `localhost` |
| SQLite "disk I/O error"（macOS） | 避免 iCloud 同步目录；改用 `~/mcp-context-forge/data` |
| 网关立即退出 | 运行 `cp .env.example .env && python3 -m mcpgateway.scripts.init_secrets --patch-env .env` |
| `ModuleNotFoundError` | 运行 `make install-dev` |

---

## 参与贡献

1. Fork 仓库，创建功能分支。
2. 运行 `make lint` 并修复问题。
3. 保持 `make test` 通过。
4. 提交带签名的 PR（`git commit -s`）。

详见 **[CONTRIBUTING.md](CONTRIBUTING.md)** 与 **[Issue Guide #2502](https://github.com/IBM/mcp-context-forge/issues/2502)**。

---

## 更新日志

完整更新日志见：[CHANGELOG.md](./CHANGELOG.md)

## 许可证

基于 **Apache License 2.0** 许可 —— 详见 [LICENSE](./LICENSE)

## 核心作者与维护者

- [Mihai Criveti](https://www.linkedin.com/in/crivetimihai) —— 杰出工程师，Agentic AI
