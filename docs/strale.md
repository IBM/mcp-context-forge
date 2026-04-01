# Strale Integration

[Strale](https://strale.dev) is trust and quality infrastructure for AI agents. It provides 250+ quality-scored data capabilities — IBAN validation, company registry lookups across 27 countries, sanctions and PEP screening, web scraping, lead enrichment, Web3 risk analysis — each continuously tested and assigned a dual-profile quality score. Every execution returns structured JSON with data provenance and an audit trail.

## Register Strale as a Remote MCP Server

### Prerequisites

1. A running ContextForge gateway
2. A Strale API key — sign up at [strale.dev/signup](https://strale.dev/signup) (free EUR 2.00 trial credits, no card required)

### Register via API

```bash
export STRALE_API_KEY=sk_live_your_key_here

curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -d '{
    "name": "strale",
    "url": "https://api.strale.io/mcp",
    "transport": "STREAMABLEHTTP",
    "description": "Trust and quality infrastructure for AI agents — 250+ quality-scored capabilities",
    "auth_config": {
      "type": "bearer",
      "token": "'"${STRALE_API_KEY}"'"
    },
    "tags": ["compliance", "validation", "company-data", "sanctions", "kyb", "web3"]
  }'
```

ContextForge will automatically discover all 8 meta-tools from Strale's MCP endpoint.

### Discovered Tools

After registration, these tools become available through the gateway:

| Tool | Auth Required | Description |
|------|:---:|---|
| `strale_search` | No | Search 250+ capabilities by keyword or category |
| `strale_execute` | Yes | Run any capability by slug |
| `strale_trust_profile` | No | Check quality score before calling a capability |
| `strale_balance` | Yes | Check wallet balance |
| `strale_ping` | No | Health check |
| `strale_getting_started` | No | Free capabilities with example inputs |
| `strale_methodology` | No | Quality scoring methodology |
| `strale_transaction` | Partial | Retrieve past execution records |

### Verify

Search for capabilities through the gateway:

```bash
curl -X POST http://localhost:4444/servers/{SERVER_ID}/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "strale_search",
      "arguments": {"query": "IBAN validation"}
    },
    "id": 1
  }'
```

Execute a free capability (no API key needed for IBAN validation):

```bash
curl -X POST http://localhost:4444/servers/{SERVER_ID}/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "strale_execute",
      "arguments": {
        "slug": "iban-validate",
        "inputs": {"iban": "DE89370400440532013000"}
      }
    },
    "id": 2
  }'
```

### Create a Virtual Server

Compose Strale tools with other sources into a single MCP endpoint:

```bash
# Get tool IDs after registration
TOOL_IDS=$(curl -s http://localhost:4444/tools | python3 -c "
import sys, json
tools = json.load(sys.stdin)
strale_tools = [t['id'] for t in tools if 'strale' in t.get('name', '')]
print(json.dumps(strale_tools))
")

# Create a virtual server combining Strale with other tools
curl -X POST http://localhost:4444/servers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  -d '{
    "server": {
      "name": "compliance-toolkit",
      "description": "Compliance and validation tools powered by Strale",
      "associated_tools": '"$TOOL_IDS"'
    }
  }'
```

## Free Tier

Five capabilities work without an API key (10 calls/day per IP):

- `email-validate` — verify email deliverability
- `iban-validate` — validate international bank account numbers
- `dns-lookup` — DNS records for any domain
- `url-to-markdown` — convert any URL to markdown
- `json-repair` — fix malformed JSON

## Links

- [Strale Documentation](https://strale.dev/docs)
- [Capability Catalog](https://api.strale.io/v1/capabilities)
- [Quality Methodology](https://strale.dev/trust/methodology)
- [MCP Server on npm](https://www.npmjs.com/package/strale-mcp)
