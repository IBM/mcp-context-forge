# 🏷️ Tags System

MCP Gateway provides a comprehensive tag system for organizing and filtering entities. Tags help categorize tools, resources, prompts, servers, and gateways, making them easier to discover and manage.

---

## 📋 Overview

Tags are metadata labels that can be attached to any entity in MCP Gateway:

- **Tools** - Categorize by functionality (e.g., `api`, `database`, `utility`)
- **Resources** - Group by content type (e.g., `documentation`, `config`, `data`)
- **Prompts** - Organize by purpose (e.g., `coding`, `analysis`, `creative`)
- **Servers** - Tag by environment (e.g., `production`, `development`, `testing`)
- **Gateways** - Label federated gateways (e.g., `cloud`, `on-premise`, `partner`)
- **A2A Agents** - Classify AI agents (e.g., `openai`, `anthropic`, `assistant`, `custom`)

!!! info "Tag Format"

    - Tags are automatically normalized to lowercase
    - Length: 2-50 characters
    - Allowed characters: letters, numbers, hyphens, colons, dots
    - Spaces and underscores automatically converted to hyphens
    - Stored as JSON arrays in the database
    - Displayed as comma-separated values in forms

---

## 🎯 Quick Start

### Using the Admin UI

1. **View Tags**: All entity tables display tags as blue badges
2. **Filter by Tags**: Use the tag filter boxes to find entities
3. **Add Tags**: Include tags when creating entities (comma-separated)
4. **Edit Tags**: Modify tags through edit modals
5. **Browse All Tags**: Visit `/admin/tags` to see all tags and their usage

### Using the REST API

All CRUD operations support tags through the REST API with JWT authentication.

---

## 🔍 Tag Discovery API

### List All Tags

Get all unique tags across the system with statistics:

=== "Request"
    ```bash
    GET /tags
    ```

=== "Parameters"
    | Parameter | Type | Description | Default |
    |-----------|------|-------------|---------|
    | `entity_types` | string | Comma-separated: tools, resources, prompts, servers, gateways | All |
    | `include_entities` | boolean | Include entities that have each tag | false |

=== "Response (Statistics Only)"
    ```json
    [
      {
        "name": "api",
        "stats": {
          "tools": 5,
          "resources": 2,
          "prompts": 1,
          "servers": 3,
          "gateways": 0,
          "total": 11
        },
        "entities": []
      }
    ]
    ```

=== "Response (With Entities)"
    ```json
    [
      {
        "name": "api",
        "stats": {
          "tools": 2,
          "resources": 1,
          "prompts": 0,
          "servers": 1,
          "gateways": 0,
          "total": 4
        },
        "entities": [
          {
            "id": "tool-123",
            "name": "REST Client",
            "type": "tool",
            "description": "Make HTTP requests"
          },
          {
            "id": "resource://api-docs",
            "name": "API Documentation",
            "type": "resource",
            "description": null
          }
        ]
      }
    ]
    ```

### Get Entities by Tag

Retrieve all entities that have a specific tag:

=== "Request"
    ```bash
    GET /tags/{tag_name}/entities
    ```

=== "Parameters"
    | Parameter | Type | Description | Default |
    |-----------|------|-------------|---------|
    | `tag_name` | string | The tag to search for (path parameter) | Required |
    | `entity_types` | string | Comma-separated entity types to filter | All |

=== "Response"
    ```json
    [
      {
        "id": "tool-123",
        "name": "REST Client",
        "type": "tool",
        "description": "Make HTTP requests to REST APIs"
      },
      {
        "id": "server-789",
        "name": "API Gateway Server",
        "type": "server",
        "description": "Central API gateway"
      }
    ]
    ```

### Admin Tags Endpoint

The admin endpoint provides UI-optimized formatting:

```bash
GET /admin/tags?include_entities=true
```

Returns the same data in a flattened structure for easier UI rendering.

---

## ✨ Tag Normalization

MCP Gateway automatically normalizes tags to ensure consistency and prevent duplicates:

### **Automatic Transformations**

- **Case Conversion**: `"Finance"` → `"finance"`
- **Space Replacement**: `"Machine Learning"` → `"machine-learning"`
- **Underscore Replacement**: `"web_development"` → `"web-development"`
- **Whitespace Trimming**: `"  api  "` → `"api"`
- **Multiple Hyphen Reduction**: `"a--b---c"` → `"a-b-c"`
- **Invalid Character Removal**: `"api@#$"` → `"api"`

### **Validation Rules**

| Rule | Description | Example |
|------|-------------|---------|
| **Minimum Length** | Tags must be at least 2 characters | ❌ `"a"` → Error |
| **Maximum Length** | Tags cannot exceed 50 characters | ❌ `"this-is-a-very-long-tag-that-exceeds-fifty-chars"` → Error |
| **Allowed Characters** | Letters, numbers, hyphens, colons, dots | ✅ `"api:v2.0"` |
| **No Leading/Trailing Hyphens** | Hyphens removed from edges | `"-api-"` → `"api"` |

---

## 📝 Examples

### Creating Entities with Tags

=== "Tools"
    ```bash
    curl -X POST http://localhost:4444/tools \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "Database Query Tool",
        "description": "Execute SQL queries",
        "input_schema": {...},
        "tags": ["database", "sql", "query"]
      }'
    ```

=== "Resources"
    ```bash
    curl -X POST http://localhost:4444/resources \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "uri": "resource://config/database",
        "name": "Database Configuration",
        "content": "...",
        "tags": ["config", "database", "settings"]
      }'
    ```

=== "Prompts"
    ```bash
    curl -X POST http://localhost:4444/prompts \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "SQL Generator",
        "template": "Generate SQL for: {query}",
        "arguments": [...],
        "tags": ["sql", "generation", "database"]
      }'
    ```

=== "Servers"
    ```bash
    curl -X POST http://localhost:4444/servers \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "Development Server",
        "description": "Local development environment",
        "tags": ["development", "local", "testing"]
      }'
    ```

### Filtering by Tags

When listing entities, filter by tags using the `tags` parameter:

=== "List Tools"
    ```bash
    # Get tools with "api" OR "database" tags
    curl -H "Authorization: Bearer $TOKEN" \
      "http://localhost:4444/tools?tags=api,database"
    ```

=== "List Resources"
    ```bash
    # Get resources with "config" tag
    curl -H "Authorization: Bearer $TOKEN" \
      "http://localhost:4444/resources?tags=config"
    ```

=== "List Prompts"
    ```bash
    # Get prompts with "generation" tag
    curl -H "Authorization: Bearer $TOKEN" \
      "http://localhost:4444/prompts?tags=generation"
    ```

### Tag Discovery Examples

=== "Find All Database Tools"
    ```bash
    # Get all entities tagged with "database"
    curl -H "Authorization: Bearer $TOKEN" \
      "http://localhost:4444/tags/database/entities?entity_types=tools"
    ```

=== "Get Tag Statistics"
    ```bash
    # See how many entities use each tag
    curl -H "Authorization: Bearer $TOKEN" \
      "http://localhost:4444/tags" | jq '.[] | {name: .name, total: .stats.total}'
    ```

=== "Find Popular Tags"
    ```bash
    # Get top 10 most used tags
    curl -H "Authorization: Bearer $TOKEN" \
      "http://localhost:4444/tags" | \
      jq 'sort_by(-.stats.total) | .[0:10] | .[] | {name: .name, count: .stats.total}'
    ```

---

## 🏆 Best Practices

### Naming Conventions

!!! tip "Recommended Tag Patterns"

    - **Functionality**: `auth`, `database`, `api`, `file-system`
    - **Environment**: `dev`, `test`, `staging`, `prod`
    - **Domain**: `finance`, `hr`, `sales`, `engineering`
    - **Access Level**: `public`, `internal`, `restricted`, `admin`
    - **Version**: `v1`, `v2`, `beta`, `deprecated`

### Tag Strategies

=== "By Functionality"
    Group entities by what they do:

    - `auth` - Authentication/authorization
    - `database` - Database operations
    - `api` - External API interactions
    - `file` - File system operations
    - `cache` - Caching mechanisms

=== "By Environment"
    Separate by deployment environment:

    - `dev` - Development only
    - `test` - Testing environment
    - `staging` - Pre-production
    - `prod` - Production ready
    - `local` - Local development

=== "By Access Control"
    Control visibility and access:

    - `public` - Available to all users
    - `internal` - Internal use only
    - `restricted` - Requires special permissions
    - `admin` - Administrator only
    - `beta` - Beta features

### Tag Management Guidelines

| Guideline | Description | Example |
|-----------|-------------|---------|
| **Keep it Simple** | Use clear, descriptive tags | ✅ `database` ❌ `db-stuff` |
| **Be Consistent** | Use the same tag across entities | ✅ All use `api` ❌ Mix of `api`, `API`, `apis` |
| **Limit Quantity** | 3-5 tags per entity is optimal | ✅ `[api, auth, v2]` ❌ 10+ tags |
| **Document Tags** | Maintain a tag glossary | Create a reference document |
| **Regular Review** | Audit and clean up unused tags | Quarterly tag review |

---

## 🔧 Integration Examples

### Python Client

```python
import httpx
from typing import List, Dict, Any, Optional

class MCPTagClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {token}"}

    def get_tags(
        self,
        entity_types: Optional[List[str]] = None,
        include_entities: bool = False
    ) -> List[Dict[str, Any]]:
        """Get all tags with optional filtering."""
        params = {}
        if entity_types:
            params["entity_types"] = ",".join(entity_types)
        if include_entities:
            params["include_entities"] = "true"

        response = httpx.get(
            f"{self.base_url}/tags",
            params=params,
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

    def get_entities_by_tag(
        self,
        tag: str,
        entity_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get all entities with a specific tag."""
        params = {}
        if entity_types:
            params["entity_types"] = ",".join(entity_types)

        response = httpx.get(
            f"{self.base_url}/tags/{tag}/entities",
            params=params,
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

    def find_related_entities(
        self,
        entity_id: str,
        entity_type: str
    ) -> List[Dict[str, Any]]:
        """Find entities with similar tags."""
        # First, get the entity's tags
        entity = httpx.get(
            f"{self.base_url}/{entity_type}s/{entity_id}",
            headers=self.headers
        ).json()

        # Then find entities with those tags
        related = []
        for tag in entity.get("tags", []):
            entities = self.get_entities_by_tag(tag)
            related.extend([
                e for e in entities
                if e["id"] != entity_id
            ])

        # Deduplicate by ID
        seen = set()
        unique = []
        for e in related:
            if e["id"] not in seen:
                seen.add(e["id"])
                unique.append(e)

        return unique

# Usage
client = MCPTagClient(
    base_url="http://localhost:4444",
    token="your-jwt-token"
)

# Get all tags with statistics
tags = client.get_tags()

# Get all database tools
db_tools = client.get_entities_by_tag(
    "database",
    entity_types=["tools"]
)

# Find related entities
related = client.find_related_entities(
    entity_id="tool-123",
    entity_type="tool"
)
```

### JavaScript/TypeScript

```typescript
interface TagStats {
  tools: number;
  resources: number;
  prompts: number;
  servers: number;
  gateways: number;
  total: number;
}

interface TaggedEntity {
  id: string;
  name: string;
  type: string;
  description?: string;
}

interface TagInfo {
  name: string;
  stats: TagStats;
  entities: TaggedEntity[];
}

class MCPTagClient {
  constructor(
    private baseUrl: string,
    private token: string
  ) {}

  private get headers() {
    return {
      'Authorization': `Bearer ${this.token}`,
      'Content-Type': 'application/json'
    };
  }

  async getTags(
    entityTypes?: string[],
    includeEntities = false
  ): Promise<TagInfo[]> {
    const params = new URLSearchParams();
    if (entityTypes?.length) {
      params.append('entity_types', entityTypes.join(','));
    }
    if (includeEntities) {
      params.append('include_entities', 'true');
    }

    const response = await fetch(
      `${this.baseUrl}/tags?${params}`,
      { headers: this.headers }
    );

    if (!response.ok) {
      throw new Error(`Failed to get tags: ${response.statusText}`);
    }

    return response.json();
  }

  async getEntitiesByTag(
    tag: string,
    entityTypes?: string[]
  ): Promise<TaggedEntity[]> {
    const params = new URLSearchParams();
    if (entityTypes?.length) {
      params.append('entity_types', entityTypes.join(','));
    }

    const response = await fetch(
      `${this.baseUrl}/tags/${tag}/entities?${params}`,
      { headers: this.headers }
    );

    if (!response.ok) {
      throw new Error(`Failed to get entities: ${response.statusText}`);
    }

    return response.json();
  }

  async createTaggedTool(
    name: string,
    tags: string[],
    inputSchema: any
  ): Promise<any> {
    const response = await fetch(
      `${this.baseUrl}/tools`,
      {
        method: 'POST',
        headers: this.headers,
        body: JSON.stringify({
          name,
          tags,
          input_schema: inputSchema
        })
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to create tool: ${response.statusText}`);
    }

    return response.json();
  }
}

// Usage
async function example() {
  const client = new MCPTagClient(
    'http://localhost:4444',
    'your-jwt-token'
  );

  // Get all tags with entities
  const tags = await client.getTags(
    undefined,
    true // include entities
  );

  // Find all API tools
  const apiTools = await client.getEntitiesByTag(
    'api',
    ['tools']
  );

  // Create a new tagged tool
  const newTool = await client.createTaggedTool(
    'My API Tool',
    ['api', 'rest', 'v2'],
    { type: 'object', properties: {} }
  );
}
```

---

## 🐛 Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| **Tags not appearing** | Incorrect JSON format | Ensure tags are JSON arrays: `["tag1", "tag2"]` |
| **Duplicate tags** | Case differences | Tags are normalized to lowercase automatically |
| **Tag validation errors** | Invalid characters | Use only letters, numbers, hyphens, colons, dots |
| **Empty tag results** | No entities with tag | Verify tag exists with `/tags` endpoint |
| **Tag not updating** | Cache issue | Clear Redis cache if using distributed caching |

### Debugging Commands

```bash
# List all unique tags in the system
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tags | jq '.[].name'

# Count total entities per tag
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/tags | \
  jq 'map({(.name): .stats.total}) | add'

# Find entities without tags (database query)
psql -d mcp_gateway -c \
  "SELECT id, name FROM tools WHERE tags IS NULL OR tags = '[]';"

# Validate tag format
echo "My_Tag Name" | \
  python3 -c "from mcpgateway.validation.tags import TagValidator; \
  import sys; print(TagValidator.normalize_tag(sys.stdin.read().strip()))"
```

---

## 📚 Advanced Use Cases

### Virtual Server Composition

Create virtual servers that bundle tools by tags:

```python
async def create_tag_based_server(tag: str, db: Session):
    """Create a virtual server with all tools having a specific tag."""

    # Get all tools with the tag
    tools = await tool_service.list_tools(db, tags=[tag])
    tool_ids = [tool.id for tool in tools]

    # Create virtual server
    server = await server_service.create_server(
        db,
        ServerCreate(
            name=f"{tag.title()} Tools Server",
            description=f"Virtual server for {tag} tools",
            tags=["virtual", tag],
            tool_ids=tool_ids
        )
    )

    return server
```

### Access Control by Tags

Implement tag-based access control:

```python
from typing import List, Set

class TagBasedAccessControl:
    """Control access to entities based on tags."""

    ROLE_PERMISSIONS = {
        "admin": {"*"},  # Access all tags
        "developer": {"dev", "test", "internal", "public"},
        "user": {"public"},
        "guest": {"public", "demo"}
    }

    @classmethod
    def filter_by_access(
        cls,
        entities: List[dict],
        user_role: str
    ) -> List[dict]:
        """Filter entities based on user's tag permissions."""
        allowed_tags = cls.ROLE_PERMISSIONS.get(user_role, {"public"})

        if "*" in allowed_tags:
            return entities

        filtered = []
        for entity in entities:
            entity_tags = set(entity.get("tags", []))
            if entity_tags & allowed_tags:  # Has at least one allowed tag
                filtered.append(entity)

        return filtered
```

### Tag-Based Discovery

Discover related entities through shared tags:

```python
async def discover_related(
    entity_type: str,
    entity_id: str,
    db: Session
) -> Dict[str, List]:
    """Find related entities based on shared tags."""

    # Get the source entity
    if entity_type == "tool":
        entity = await tool_service.get_tool(db, entity_id)
    elif entity_type == "resource":
        entity = await resource_service.get_resource(db, entity_id)
    # ... handle other types

    if not entity or not entity.tags:
        return {}

    # Find entities with overlapping tags
    related = {}
    for tag in entity.tags:
        entities = await tag_service.get_entities_by_tag(
            db,
            tag_name=tag
        )

        for e in entities:
            if e.id != entity_id:  # Exclude self
                if e.type not in related:
                    related[e.type] = []
                related[e.type].append(e)

    # Deduplicate and sort by relevance
    for entity_type in related:
        # Count tag overlaps
        overlap_counts = {}
        for e in related[entity_type]:
            overlap = len(set(e.tags) & set(entity.tags))
            overlap_counts[e.id] = overlap

        # Sort by overlap count
        related[entity_type] = sorted(
            related[entity_type],
            key=lambda e: overlap_counts[e.id],
            reverse=True
        )

    return related
```

---

## 🔗 Related Documentation

- [REST API Reference](https://ibm.github.io/mcp-context-forge/api/) - Complete API documentation
- [Admin UI Guide](./ui.md) - Using the web interface
- [Virtual Servers](../architecture/index.md) - Composing servers with tags
- [Federation](../architecture/index.md) - Tag-based gateway discovery
