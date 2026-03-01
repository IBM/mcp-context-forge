# A2A v1.0 Protocol Architecture

## Overview

ContextForge integrates A2A Protocol v1.0 RC1, enabling virtual servers to serve as A2A agents to external callers while proxying requests to downstream agents. This architecture federates agent-to-agent communication through ContextForge's governance layer, applying the same authentication, RBAC, team scoping, rate limiting, and observability that exist for MCP tool calls.

A single virtual server can expose both MCP and A2A protocol interfaces simultaneously. When `a2a_enabled=True` is set on a server, it auto-generates an `AgentCard` from its associated agents and begins accepting A2A JSON-RPC requests at its dedicated endpoint tree.

## Virtual Servers as A2A Agents

The `Server` model is the central entity for multi-protocol exposure. Rather than creating a separate A2A-specific model, the existing server is extended with A2A fields (see [ADR-0042](adr/042-virtual-server-multi-protocol.md)):

| Field | Type | Purpose |
|-------|------|---------|
| `a2a_enabled` | `bool` (default `false`) | Feature flag to activate A2A protocol endpoints |
| `a2a_tenant` | `str` (optional) | Default tenant label forwarded to downstream agents |
| `a2a_agent_card_override` | `JSON` (optional) | Manual overrides for the auto-generated AgentCard |
| `a2a_protocol_version` | `str` (default `v1.0`) | Protocol version for outbound wire format |

When `a2a_enabled=True`, the server exposes endpoints at:

```
/servers/{server_id}/a2a/            # JSON-RPC endpoint (SendMessage, GetTask, etc.)
/servers/{server_id}/a2a/agent-card  # AgentCard discovery
```

A server with no MCP gateways associated but `a2a_enabled=True` functions as an A2A-only server. A server with both MCP gateways and A2A agents associated serves both protocols.

## Request Routing

When a virtual server receives an A2A request (`SendMessage`, `GetTask`, `CancelTask`, etc.), the `A2AServerService` handles federation to an appropriate downstream agent.

```mermaid
sequenceDiagram
    participant C as External Caller
    participant S as Virtual Server<br/>(A2A Endpoint)
    participant SS as A2AServerService
    participant A as Downstream Agent
    participant DB as Database

    C->>S: JSON-RPC SendMessage
    S->>SS: Route request

    SS->>DB: Look up associated agents
    DB-->>SS: Agent list with skills

    SS->>SS: Match request to agent<br/>(skill-based selection)

    SS->>DB: Create ServerTaskMapping<br/>(server_task_id -> agent_task_id)

    SS->>A: Forward SendMessage<br/>(with tenant, protocol_version formatting)
    A-->>SS: Task response / streaming events

    SS->>DB: Update ServerTaskMapping status
    SS-->>S: Federated response
    S-->>C: JSON-RPC response
```

The `ServerTaskMapping` table maintains the federation relationship between the server-level task ID (visible to external callers) and the downstream agent task ID (used internally). This allows:

- **GetTask**: Callers query by the server task ID; the service translates to the downstream agent task ID.
- **CancelTask**: Cancellation propagates through the mapping to the correct downstream agent.
- **ListTasks**: The server aggregates task state across all associated agents, translating IDs back to server-level task IDs.
- **Streaming**: Server-Sent Events from downstream agents are relayed to the caller with server-level task IDs.

## Agent Card Generation

When `a2a_enabled=True`, the server automatically generates a composite `AgentCard` by aggregating metadata from all associated A2A agents.

```mermaid
flowchart TD
    subgraph "Server Configuration"
        S[Virtual Server<br/>name, description, URL]
        O[a2a_agent_card_override<br/>JSON overrides]
    end

    subgraph "Associated Agents"
        A1[Agent 1<br/>skills: code_review, testing<br/>caps: streaming=true, pushNotifications=false]
        A2[Agent 2<br/>skills: deployment, monitoring<br/>caps: streaming=false, pushNotifications=true]
    end

    subgraph "Composite AgentCard"
        AC[AgentCard]
        SK[Skills: code_review, testing,<br/>deployment, monitoring<br/>UNION of all agent skills]
        CP[Capabilities:<br/>streaming=false AND<br/>pushNotifications=false AND/OR logic]
        SI[supported_interfaces:<br/>protocol_binding for JSON-RPC]
    end

    S --> AC
    A1 --> SK
    A2 --> SK
    A1 --> CP
    A2 --> CP
    O -->|override| AC
    AC --> SK
    AC --> CP
    AC --> SI
```

### Aggregation Rules

| AgentCard Field | Aggregation Strategy | Rationale |
|-----------------|---------------------|-----------|
| `skills` | Union of all agent skills | Server can handle any skill its agents support |
| `capabilities.streaming` | Logical AND (all must support) | Server can only promise streaming if all agents support it |
| `capabilities.pushNotifications` | Logical AND | Same restrictive logic for push notifications |
| `capabilities.stateTransitionHistory` | Logical OR | Server can provide history if any agent supports it |
| `supported_interfaces` | Generated from server URL | Points callers to the server's A2A endpoint |
| `name`, `description` | From server metadata | Server identity, not individual agent identity |

The `a2a_agent_card_override` JSON allows operators to manually override any field in the generated AgentCard, for example to add custom skills, override the description, or set specific capability flags regardless of agent declarations.

## Tenant Forwarding

A2A v1.0 introduces a `tenant` field on all request messages. This is a **routing label** forwarded to downstream agents, distinct from the gateway's `team_id` which controls access authorization. See [ADR-0043](adr/043-tenant-vs-team.md) for the full design rationale.

```mermaid
flowchart TD
    REQ[Inbound A2A Request<br/>may contain tenant field] --> CHECK{allow_caller_tenant_override?}

    CHECK -->|yes| CALLER[Use caller-supplied tenant]
    CHECK -->|no| AGENT_CFG{Agent has tenant override?}

    CALLER --> VALIDATE{In tenant allowlist?}
    VALIDATE -->|yes| USE_CALLER[Forward caller tenant]
    VALIDATE -->|no| REJECT[Reject or fall through]

    AGENT_CFG -->|yes| USE_AGENT[Use per-agent tenant]
    AGENT_CFG -->|no| SERVER_CFG{Server has a2a_tenant?}

    SERVER_CFG -->|yes| USE_SERVER[Use server default tenant]
    SERVER_CFG -->|no| EMPTY[Forward with no tenant]

    USE_CALLER --> OUT[Outbound request to<br/>downstream agent]
    USE_AGENT --> OUT
    USE_SERVER --> OUT
    EMPTY --> OUT
```

### Precedence

1. **Caller-supplied** -- accepted only if `allow_caller_tenant_override=true` and the value passes the optional tenant allowlist.
2. **Per-agent override** -- a tenant value configured on the specific agent registration.
3. **Server default** -- the `a2a_tenant` field on the virtual server.
4. **Empty** -- no tenant is set in the outbound request.

Key invariants:

- `team_id` is never sent in A2A protocol messages.
- `tenant` is never used for gateway access control.
- Multiple servers in different teams can share the same downstream tenant.

## Backward Compatibility

ContextForge maintains a compatibility layer for v0.3.0 agents during the transition to v1.0 (see [ADR-0041](adr/041-a2a-v1-migration.md)). The `protocol_version` field on each agent registration determines the outbound wire format.

### Compatibility Mechanisms

- **Dual method name acceptance**: Both slash-style (`tasks/send`) and PascalCase (`SendMessage`) method names are accepted on inbound JSON-RPC requests.
- **Part normalization**: Parts with and without the `kind` discriminator field are accepted and normalized internally to v1.0 format.
- **`content`/`parts` field compatibility**: Either field name is accepted on inbound messages. Outbound messages use the field name matching the target agent's `protocol_version`.
- **Protocol version per agent**: Each agent carries a `protocol_version` field. When forwarding to a v0.3.0 agent, the service converts the request to v0.3.0 wire format (e.g., `parts` back to `content`, PascalCase back to slash-style).
- **Feature flag**: `A2A_V1_COMPAT_MODE` (default `true`) controls whether v0.3.0 conventions are accepted. Setting to `false` enforces strict v1.0-only processing.
- **Deprecation signals**: Responses served through v0.3.0 compatibility paths include `Deprecation` and `Sunset` headers per RFC 8594.

```mermaid
flowchart LR
    IN[Inbound Request] --> NORM[Normalize to v1.0<br/>internal representation]

    NORM --> SVC[Service Layer<br/>processes in v1.0 format]

    SVC --> FMT{Target agent<br/>protocol_version?}

    FMT -->|v1.0| V1[Emit v1.0 wire format<br/>PascalCase methods<br/>parts field<br/>kind discriminator]
    FMT -->|v0.3.0| V03[Emit v0.3.0 wire format<br/>slash-style methods<br/>content field<br/>wrapped Part types]

    V1 --> AGENT1[v1.0 Agent]
    V03 --> AGENT2[v0.3.0 Agent]
```

## Protocol Changes Summary

Key changes from A2A v0.3.0 to v1.0 RC1:

| Area | v0.3.0 | v1.0 RC1 | Impact |
|------|--------|----------|--------|
| **Part structure** | `FilePart`, `DataPart` wrapper types | Inline parts with `kind` discriminator | Schema migration, normalization logic |
| **Message field** | `Message.content` | `Message.parts` | Field rename, compat layer |
| **AgentCard endpoints** | `url`, `preferred_transport`, `additional_interfaces` | `supported_interfaces` with `protocol_binding` | Card generation rewrite |
| **Method names** | Slash-style (`tasks/send`, `tasks/get`) | PascalCase (`SendMessage`, `GetTask`) | Dual dispatch, outbound formatting |
| **TaskState** | `CANCELLED` | `CANCELED` | Enum mapping |
| **AuthenticationInfo** | `schemes` (repeated) | `scheme` (singular) | Schema update |
| **Security model** | `Security` | `SecurityRequirement` | Type rename |
| **Tenant** | Not present | `tenant` field on request messages | New routing concept |
| **Blocking** | Not present | `blocking` flag on `SendMessageConfiguration` | New execution mode |
| **ListTasks** | Not present | Full query support with filters | New RPC method |
| **GetExtendedAgentCard** | Not present | New RPC method | Extended card discovery |
| **TaskStatusUpdateEvent.final** | Present | Removed | Event handling update |
| **Extended card auth** | `supports_authenticated_extended_card` on card | Moved to `capabilities` | Card schema change |

## Plugin Hooks

The `agent_pre_invoke` and `agent_post_invoke` plugin hooks fire in the leaf A2A service layer (`a2a_service.py`), not in the server federation layer (`A2AServerService`). This prevents duplicate execution when a server federates to a downstream agent:

```mermaid
sequenceDiagram
    participant C as Caller
    participant SS as A2AServerService<br/>(server layer)
    participant AS as A2AAgentService<br/>(leaf layer)
    participant P as Plugin Hooks

    C->>SS: SendMessage (server endpoint)
    Note over SS: No plugin hooks fire here

    SS->>AS: Forward to matched agent
    AS->>P: agent_pre_invoke
    P-->>AS: (possibly modified request)

    AS->>AS: Execute agent logic

    AS->>P: agent_post_invoke
    P-->>AS: (possibly modified response)

    AS-->>SS: Agent response
    SS-->>C: Federated response
```

Hooks fire once per agent invocation regardless of whether the request arrives directly at an agent endpoint or is federated through a virtual server. This guarantees consistent plugin behavior (logging, policy enforcement, transformation) without duplication.
