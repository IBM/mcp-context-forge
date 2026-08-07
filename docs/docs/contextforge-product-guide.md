# ContextForge 产品功能使用文档

> 适用版本：fork + 上游 1.0.7 合并版（v5 部署，codex-15 `mcpgateway:local-v5`）
> 默认管理地址：`http://localhost:4444/admin`

---

## 目录

1. [产品简介](#1-产品简介)
2. [快速上手](#2-快速上手)
3. [管理后台 Admin UI](#3-管理后台-admin-ui)
4. [gRPC 服务管理](#4-grpc-服务管理)
5. [SQL 数据 API](#5-sql-数据-api)
6. [统一 API 调试平台](#6-统一-api-调试平台)
7. [核心功能：工具与服务器注册](#7-核心功能工具与服务器注册)
8. [LLM 网关与聊天](#8-llm-网关与聊天)
9. [安全与访问控制](#9-安全与访问控制)
10. [运维与可观测](#10-运维与可观测)
11. [常见问题（FAQ）](#11-常见问题faq)

---

## 1. 产品简介

**ContextForge** 是一个开源的 **MCP 工具注册表与代理网关**，将 MCP、A2A、REST/gRPC API 统一汇聚到一个面向 AI 客户端的端点，提供集中式的治理、发现与可观测能力。

### 1.1 核心能力

| 能力 | 说明 |
|------|------|
| **工具网关** | MCP、REST、gRPC-to-MCP 翻译、TOON 压缩 |
| **Agent 网关** | A2A 协议、OpenAI 兼容与 Anthropic agent 路由 |
| **API 网关** | 限流、认证、重试、REST 服务反向代理 |
| **插件扩展** | 40+ 插件支持更多传输协议与集成 |
| **可观测** | OpenTelemetry 追踪（Phoenix、Jaeger、Zipkin、OTLP） |

### 1.2 多传输支持

| 传输 | 说明 | 典型场景 |
|------|------|----------|
| HTTP / JSON-RPC | 低延迟请求-响应 | 大多数 REST 客户端 |
| WebSocket | 双向全双工 | 流式对话、增量结果 |
| SSE | 服务端 → 客户端单向流 | LLM 补全、实时更新 |
| STDIO | 本地进程管道（`mcpgateway-wrapper`） | 编辑器插件、headless CLI |

### 1.3 本部署的新增功能（合并版）

本版本在 fork 开发基础上合并了上游 1.0.7，新增三个生产级模块：

- **gRPC 服务管理**（`MCPGATEWAY_GRPC_ENABLED`）— gRPC 服务注册、反射发现、健康检查、proto 扫描
- **SQL 数据 API**（`MCPGATEWAY_SQL_API_ENABLED`）— 受治理的外部 SQL 数据源发现与数据 API
- **统一 API 调试平台**（`MCPGATEWAY_API_DEBUG_ENABLED`）— 工具调用目录、调用、流式调试

三个模块均 **失败安全（默认关闭）**，需显式设置环境变量开启。

---

## 2. 快速上手

### 2.1 登录管理后台

1. 浏览器访问 `http://localhost:4444/admin`
2. 未登录会 307 重定向到 `/admin/login`
3. 使用平台管理员账号登录：

| 字段 | 本部署默认值 |
|------|--------------|
| Email | `admin@example.com` |
| 密码 | `zeta@2026` |

登录成功后写入两个 cookie：
- `jwt_token`（HttpOnly，JWT 会话）
- `mcpgateway_csrf_token`（CSRF 防护）

### 2.2 获取 API 访问令牌

API 端点**不接受 cookie 认证**，需在请求头携带 JWT Bearer token：

```bash
# 方式一：登录接口拿 JWT（返回 303 与 set-cookie）
curl -c /tmp/cf-cookies.txt -X POST http://localhost:4444/admin/login \
  -d "email=admin@example.com&password=zeta@2026"

# 从 set-cookie 中提取 jwt_token，用于 API 调用
JWT=$(curl -s -X POST http://localhost:4444/admin/login \
  -d "email=admin@example.com&password=zeta@2026" -D - -o /dev/null \
  | grep -i set-cookie | grep jwt_token | sed -E 's/.*jwt_token=([^;]*);.*/\1/')

# API 调用示例
curl -H "Authorization: Bearer $JWT" http://localhost:4444/admin/grpc
```

### 2.3 生成独立访问令牌

```bash
python3 -m mcpgateway.utils.create_jwt_token \
  --username alice --exp 1440 --secret "$JWT_SECRET_KEY"
```

### 2.4 健康检查

```bash
curl http://localhost:4444/health
# → 200，含依赖检测结果
```

---

## 3. 管理后台 Admin UI

Admin UI 基于 FastAPI + Jinja2 + HTMX + Alpine.js + Tailwind 构建，侧边栏按功能分组：

| 分组 | 功能 |
|------|------|
| **概览** | 仪表盘、服务器、工具、提示词、资源、Roots、MCP 注册表 |
| **Agent & gRPC** | A2A Agents、**gRPC Services** |
| **数据** | **SQL Data** 目录 |
| **调试** | **API Debug** |
| **设置** | LLM 设置、管理配置 |

三个新模块标签（gRPC Services / SQL Data / API Debug）仅在对应 feature flag 开启时显示。

### 3.1 仪表盘

首页概览展示：服务器健康、工具统计、调用量、成本（ToolOps 开启时）、最近活动。

### 3.2 隐藏模块

管理员可通过 `UI_HIDDEN_SECTIONS` 配置隐藏侧边栏模块（如 `UI_HIDDEN_SECTIONS=grpc-services,sql-sources`）。

---

## 4. gRPC 服务管理

### 4.1 开启功能

```env
MCPGATEWAY_GRPC_ENABLED=true
```

### 4.2 注册 gRPC 服务

**方式一：Admin UI**

侧边栏 **🔌 gRPC Services** → 添加服务，填写名称、目标地址（`host:port`）、是否启用反射。

**方式二：REST API**

```bash
# 注册（返回 201 与完整服务对象）
curl -X POST http://localhost:4444/admin/grpc \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{
    "name": "payment-service",
    "target": "localhost:50051",
    "description": "支付服务",
    "reflection_enabled": true,
    "tls_enabled": false
  }'
```

### 4.3 服务发现（反射）

开启 `reflection_enabled` 后，网关自动通过 [Server Reflection Protocol](https://grpc.io/docs/guides/reflection/) 连接 gRPC 服务器，发现全部服务与方法：

1. 网关连接 gRPC 服务器
2. 自动发现服务与方法
3. Protobuf 消息 ↔ JSON 转换
4. 每个 gRPC 方法暴露为受治理的 MCP 工具
5. 支持 unary 与服务端流式

### 4.4 导入 schema 工件

反射不可用时，可导入 `.proto`、安全 ZIP 或二进制 `FileDescriptorSet`：

```bash
curl -X POST http://localhost:4444/admin/grpc/{service_id}/schemas/import \
  -H "Authorization: Bearer $JWT" \
  -F "artifact=@service.proto" -F "activate=true"
```

每个规范化后的描述符按 SHA-256 版本存储为**不可变快照**，支持版本管理与回滚。

### 4.5 健康检查

```bash
# 立即执行健康检查（返回 200 或 503）
curl -X POST http://localhost:4444/admin/grpc/{service_id}/health \
  -H "Authorization: Bearer $JWT"

# 查看历史健康采样
curl http://localhost:4444/admin/grpc/{service_id}/health/samples \
  -H "Authorization: Bearer $JWT"
```

健康检查返回 `healthy` / `degraded` 状态、`status_code`、`latency_ms` 与错误详情。示例：

```json
{
  "status": "degraded",
  "healthy": false,
  "check_type": "health",
  "status_code": "UNAVAILABLE",
  "latency_ms": 19.76,
  "error": "failed to connect to all addresses; last error: ..."
}
```

### 4.6 Proto 目录扫描

基于 `grpc-service.yaml` manifest 的目录扫描（可选开启）：

```env
MCPGATEWAY_PROTO_SCAN_ENABLED=true
MCPGATEWAY_PROTO_SCAN_ROOTS=/path/to/roots
MCPGATEWAY_PROTO_SCAN_INTERVAL=60
```

```bash
# 手动触发一次扫描
curl -X POST http://localhost:4444/admin/grpc/scan \
  -H "Authorization: Bearer $JWT"
# 关闭时返回 422 "Proto directory scanning is disabled"
```

### 4.7 管理操作

```bash
# 列表（分页）
curl "http://localhost:4444/admin/grpc?page=1&per_page=10" -H "Authorization: Bearer $JWT"

# 详情
curl http://localhost:4444/admin/grpc/{service_id} -H "Authorization: Bearer $JWT"

# 更新
curl -X PATCH http://localhost:4444/admin/grpc/{service_id} -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" -d '{"description":"更新"}'

# 启用/停用
curl -X POST http://localhost:4444/admin/grpc/{service_id}/state \
  -H "Authorization: Bearer $JWT" -d 'activate=false'

# 删除
curl -X POST http://localhost:4444/admin/grpc/{service_id}/delete \
  -H "Authorization: Bearer $JWT"   # 返回 204
```

### 4.8 团队可见性

gRPC 服务支持 `visibility`（public / team / private）+ `team_id` + `owner_email` 三列访问控制：

- **public** — 所有用户可见
- **team** — 团队成员可见（需匹配 `team_id`）
- **private** — 仅 `owner_email` 本人可见

列表与详情端点自动按当前用户身份应用可见性过滤。

---

## 5. SQL 数据 API

受治理的外部 SQL 数据访问，**默认关闭**（`MCPGATEWAY_SQL_API_ENABLED=true` 开启）。

### 5.1 开启功能

```env
MCPGATEWAY_SQL_API_ENABLED=true
MCPGATEWAY_SQLITE_ALLOWED_ROOTS=/data   # SQLite 数据源允许的根目录（可选）
```

### 5.2 安全模型

- **加密连接** — 数据源连接串加密存储
- **失败安全** — 发现的表默认**私密、不暴露、只读**
- **显式策略** — 只有保存操作策略后表才对外可查询
- **拒绝危险操作** — 任意 SQL、DDL、存储过程、批量写入、多跳 include 一律拒绝
- **视图只读** — 数据库视图永远只读
- **写入需主键** — update/delete 需要反射主键或显式唯一键
- **deadline 强制** — 数据库驱动层强制执行超时，超时写入不会在调用方收到错误后于后台 worker 提交

### 5.3 创建与测试数据源

```bash
# 创建数据源（平台管理员）
curl -X POST http://localhost:4444/admin/sql/sources \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"name":"inventory","connection_url":"postgresql+psycopg://user@db.example.com/inventory"}'

# 测试连接
curl -X POST http://localhost:4444/admin/sql/sources/{source_id}/test \
  -H "Authorization: Bearer $JWT"

# 发现元数据（表/列）
curl -X POST http://localhost:4444/admin/sql/sources/{source_id}/discover \
  -H "Authorization: Bearer $JWT"
```

### 5.4 暴露表并授权

```bash
# 分配团队 + 设置可见性 + 开启查询（只有这一步才让表对外可查）
curl -X PATCH http://localhost:4444/admin/sql/tables/{table_id} \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"team_id":"TEAM_ID","visibility":"team","exposed":true,"allow_query":true}'
```

### 5.5 数据查询 API

暴露后，REST 与生成的 MCP 工具共享同一 ToolService 权限、插件、审计与指标流水线：

```bash
# 等值过滤 + 字段选择 + 降序排序 + 一个已启用关联 + 限制条数
curl -G "http://localhost:4444/api/v1/data/inventory/public/orders" \
  -H "Authorization: Bearer $JWT" \
  --data-urlencode 'filter={"state":"open"}' \
  --data-urlencode 'fields=id,state,total' \
  --data-urlencode 'sort=-id' \
  --data-urlencode 'include=customer' \
  --data-urlencode 'limit=100'

# 复合主键需 URL-encoded JSON；PATCH/DELETE 需完整主键
curl -X PATCH "http://localhost:4444/api/v1/data/inventory/public/order_lines?key=%7B%22order_id%22%3A10%2C%22line_id%22%3A2%7D" \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"quantity":3}'
```

> **注意**：`key` 参数必须是 URL 编码的 JSON **对象**（如 `?key={"id":5}`）。裸值或非对象返回 422 `"key must be a non-empty JSON object"`。

### 5.6 数据源管理

```bash
# 列出数据源
curl http://localhost:4444/admin/sql/sources -H "Authorization: Bearer $JWT"

# 删除数据源
curl -X DELETE http://localhost:4444/admin/sql/sources/{source_id} \
  -H "Authorization: Bearer $JWT"
```

---

## 6. 统一 API 调试平台

**默认关闭**（`MCPGATEWAY_API_DEBUG_ENABLED=true` 开启）。基于真实 ToolService 流水线调用工具。

### 6.1 开启功能

```env
MCPGATEWAY_API_DEBUG_ENABLED=true
```

### 6.2 目录与调用

```bash
# 权限：目录读取需 tools.read，调用需 tools.execute

# 按协议查看工具目录
curl -H "Authorization: Bearer $JWT" \
  "http://localhost:4444/admin/debug/catalog?protocol=gRPC"

# 调用工具（一次调用）
curl -X POST http://localhost:4444/admin/debug/invoke \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{
    "tool_id":"TOOL_ID",
    "arguments":{"id":"42"},
    "headers":{},
    "metadata":{"x-tenant":"demo"},
    "deadline_seconds":10
  }'

# 流式调用（SSE）
curl -X POST -N http://localhost:4444/admin/debug/stream \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"tool_id":"TOOL_ID","arguments":{},"headers":{},"metadata":{},"deadline_seconds":30}'
```

### 6.3 调试平台特性

- **Admin UI 渲染**：根据每个工具的 JSON Schema 渲染可编辑控件，可将生成值复制进原始 JSON 编辑器
- **历史记录**：仅对调用者私密；只保存脱敏的请求预览 + 结果元数据，**永不保存响应体或凭据**
- **保留策略**：默认 7 天 + 每用户最近 100 条
- **输出治理**：若配置了 output-governance 插件，服务端流式条目会缓冲至 `TOOL_POST_INVOKE` 批准/转换后发出；否则实时发出

### 6.4 统计

```bash
# 调试调用统计
curl http://localhost:4444/admin/debug/stats -H "Authorization: Bearer $JWT"
# → {"total_calls":0,"success_count":0,"failure_count":0,"error_rate":0.0,"p50":null,...}

# 历史记录
curl http://localhost:4444/admin/debug/history -H "Authorization: Bearer $JWT"
```

---

## 7. 核心功能：工具与服务器注册

### 7.1 注册实体类型

| 实体 | 说明 |
|------|------|
| **工具** | 原生 MCP 工具，或包装后的 REST/CLI 函数（JSON Schema 输入校验） |
| **资源** | URI 指向 blob、文本、图片（可选 SSE 变更通知） |
| **提示词** | Jinja2 模板 + 多模态内容（支持版本与回滚） |
| **服务器** | 工具/提示词/资源的虚拟集合，暴露为完整 MCP 服务器 |
| **gRPC 服务** | 通过自动反射发现的 gRPC 微服务 |

### 7.2 注册 REST 工具

```bash
curl -X POST -H "Authorization: Bearer $JWT" \
     -H "Content-Type: application/json" \
     -d '{
           "name": "joke_api",
           "url": "https://icanhazdadjoke.com/",
           "requestType": "GET",
           "integrationType": "REST",
           "headers": {"Accept":"application/json"}
         }' \
     http://localhost:4444/tools
```

### 7.3 通过 SSE 访问 MCP 服务器

```bash
curl -N -H "Accept: text/event-stream" \
     -H "Authorization: Bearer $JWT" \
     http://localhost:4444/servers/UUID_OF_SERVER_1/sse
```

### 7.4 元数据追踪

所有实体（工具/资源/提示词/服务器/网关）自动记录：
- **创建来源** — 谁、何时、从哪、如何创建
- **修改历史** — 变更归属与版本
- **Federation 来源** — MCP 服务器实体的来源追踪
- **批量导入批次** — 批量导入标识
- **兼容回退** — 旧实体优雅降级显示

---

## 8. LLM 网关与聊天

由 `LLMCHAT_ENABLED`（默认 `true`）控制，三个组成部分：

### 8.1 Provider 注册表

- 12 种 provider 类型：OpenAI、Azure OpenAI、Anthropic、AWS Bedrock、Google Vertex、WatsonX、Ollama、OpenAI-compatible、Cohere、Mistral、Groq、Together
- API key 加密存储
- 一键自动同步上游可用模型
- 健康检查验证连接与凭据
- 开关控制 provider 与单模型

管理入口：**Settings → LLM Settings**

### 8.2 OpenAI 兼容代理

```bash
# 标准 OpenAI 请求体，返回 Chat Completion / Chunk 响应
POST http://localhost:4444/v1/chat/completions
GET  http://localhost:4444/v1/models
```

- 客户端无需 provider 专属 key 或 URL，网关根据模型 ID 解析目标 provider
- 支持流式（SSE）
- RBAC：completions 需 `llm.invoke`，models 需 `llm.read`

### 8.3 聊天 Agent（可选）

- `POST /llmchat/connect` — 选择 MCP 虚拟服务器 + 模型，创建 LangChain ReAct agent
- `POST /llmchat/chat` — 发送消息，工具执行反馈交织在对话中
- 会话状态与历史按用户存储（多 worker 部署 Redis 后端，断开自动清理）

### 8.4 成本控制（ToolOps）

```env
TOOLOPS_ENABLED=true
TOOLOPS_AUTHORIZATION=<token>
```

- 按模型定价的逐调用成本计算
- 提示/补全 token 用量追踪
- 工具级与总额成本汇总
- 成本阈值防止失控支出
- 逐工具节流控制昂贵操作
- 历史数据优化 + 预算告警

---

## 9. 安全与访问控制

### 9.1 认证机制

| 机制 | 说明 |
|------|------|
| **JWT bearer** | 默认，`JWT_SECRET_KEY` 签名 |
| **Email/password** | Admin UI（`PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD`） |
| **HTTP Basic** | 可选（`API_ALLOW_BASIC_AUTH=true` 或 `DOCS_ALLOW_BASIC_AUTH=true`） |
| **自定义头** | 每个工具/网关的 API key 等 |

### 9.2 RBAC 权限

- 权限基于 token scoping + 会话 token 团队列表
- 新功能端点权限：
  - `/api/v1/data/*` — 数据查询权限
  - `/admin/sql/*` — SQL 管理权限
  - `/admin/debug/*` — catalog 需 `tools.read`、invoke 需 `tools.execute`
- **团队可见性**：工具/服务器/gRPC 服务/数据表均支持 public / team / private 三层可见性

### 9.3 CSRF 防护

PATCH/DELETE 等请求需携带 CSRF 头（`Origin` + `Referer` + `X-CSRF-Token`），否则返回 `"CSRF origin validation failed"`。

### 9.4 SSRF 防护

- `SSRF_ALLOW_LOCALHOST` — 是否允许访问 localhost
- `SSRF_ALLOWED_NETWORKS` — 允许的网络白名单
- gRPC 目标地址与 SQL 连接串均经过 SSRF 校验

### 9.5 安全默认

- 三个新模块默认关闭（失败安全）
- 未认证时 Admin UI 有安全告警日志
- `UAID_ALLOWED_DOMAINS` 为空时跨网关路由禁用（安全默认）

---

## 10. 运维与可观测

### 10.1 健康端点

```bash
curl http://localhost:4444/health   # 就绪 + 依赖检测
```

### 10.2 指标

```bash
curl http://localhost:4444/metrics   # Prometheus 友好计数器
# tool_calls_total, gateway_up ...
```

### 10.3 结构化日志

JSON 格式结构化日志，可 `jq` 解析。启动时注意两类告警（非故障）：

- `INSECURE CONFIGURATION: UAID_ALLOWED_DOMAINS is empty AND AUTH_REQUIRED=false` — 跨网关路由未配置域名白名单且未启用认证
- `Admin UI is enabled without authentication` — Admin UI 未配置认证（本部署 AUTH_REQUIRED=false）

### 10.4 数据库与迁移

- 默认 SQLite（`DATABASE_URL=sqlite:////data/mcp.db`），生产建议 PostgreSQL
- 启动时自动执行 `alembic upgrade head`，本部署当前版本 `f000baa38a15`
- 数据卷 `mcpgateway-data:/data`，DB 位于 `/data/mcp.db`

### 10.5 备份

```bash
docker cp mcpgateway:/data/mcp.db /tmp/mcp.db.bak.$(date +%F)
```

### 10.6 容器运维

```bash
docker ps | grep mcpgateway                 # 状态
docker logs -f mcpgateway                   # 日志
docker restart mcpgateway                   # 重启
```

---

## 11. 常见问题（FAQ）

### 11.1 为什么 `/admin/grpc/health` 返回 404？

`health` 被匹配为 `{service_id}` 路径参数。健康检查的正确路径是：
- `POST /admin/grpc/{service_id}/health`（按服务 ID 检查）
- `GET /admin/grpc/{service_id}/health/samples`（历史采样）

### 11.2 为什么 `POST /admin/grpc/scan` 返回 422？

Proto 目录扫描默认关闭（`MCPGATEWAY_PROTO_SCAN_ENABLED` 未开启），返回 `"Proto directory scanning is disabled"`。属预期行为，开启该 flag 即可。

### 11.3 为什么 PATCH/DELETE 报 "CSRF origin validation failed"？

需要携带 `Origin`、`Referer`、`X-CSRF-Token` 三个头。用 curl 调试时：

```bash
curl -X PATCH URL \
  -H "Authorization: Bearer $JWT" \
  -H "Origin: http://localhost:4444" \
  -H "Referer: http://localhost:4444/admin" \
  -H "X-CSRF-Token: $CSRF_TOKEN"
```

### 11.4 API 用 cookie 认证报 "Cookie authentication not allowed for API requests"？

API 端点只接受 `Authorization: Bearer <JWT>` 头，cookie 仅用于浏览器会话。从登录 set-cookie 中提取 JWT 作为 Bearer 头即可。

### 11.5 SQL 查询 key 参数报 422 "key must be a non-empty JSON object"？

`key` 必须是 URL 编码的 JSON **对象**：`?key=%7B%22id%22%3A5%7D`（即 `?key={"id":5}`）。裸值（如 `?key=5`）会被拒绝。

### 11.6 登录接口返回 missing_fields？

登录表单字段名是 `email` + `password`（不是 `username`）。

### 11.7 如何确认前端 bundle 加载正常？

```bash
# bundle 文件名从 vite manifest 解析，默认 bundle-Cd0-6Pu4.js
curl -o /dev/null -w "%{http_code}\n" http://localhost:4444/static/bundle-Cd0-6Pu4.js
# → 200
```

---

## 附录：本部署关键环境变量

| 变量 | 值 | 说明 |
|------|-----|------|
| `MCPGATEWAY_GRPC_ENABLED` | `true` | gRPC 服务管理开启 |
| `MCPGATEWAY_SQL_API_ENABLED` | `true` | SQL 数据 API 开启 |
| `MCPGATEWAY_API_DEBUG_ENABLED` | `true` | API 调试平台开启 |
| `MCPGATEWAY_SQLITE_ALLOWED_ROOTS` | `/data` | SQLite 数据源允许根目录 |
| `SSRF_ALLOW_LOCALHOST` | `true` | 允许 localhost SSRF 目标 |
| `AUTH_REQUIRED` | `false` | 认证未强制（测试部署） |
| `MCPGATEWAY_PROTO_SCAN_ENABLED` | （未设） | proto 扫描默认关闭 |
| `LLMCHAT_ENABLED` | （默认 true） | LLM 网关总开关 |
| `TOOLOPS_ENABLED` | （未设） | 成本控制默认关闭 |
