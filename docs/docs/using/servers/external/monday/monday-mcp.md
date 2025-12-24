# monday.com MCP Server

## Overview

The monday.com MCP Server provides seamless integration with monday.com's Work OS platform through the Model Context Protocol. This official server enables AI applications to interact with monday.com's project management, productivity, and collaboration features, allowing for automated workflows, real-time updates, and comprehensive team coordination.

monday.com is a flexible Work Operating System (Work OS) that powers teams to run projects and workflows with confidence. Through this MCP integration, you can leverage AI to manage boards, items, columns, teams, and automate complex workflows across your organization.

**Category:** Productivity / Project Management

**Provider:** monday.com

**Endpoint:** `https://mcp.monday.com/sse`

**Transport:** Server-Sent Events (SSE)

**Authentication:** OAuth2.1

## Features

- 📋 **Board Management**: Create, update, and manage boards and workspaces
- 📝 **Item Operations**: Add, modify, and track work items across boards
- 👥 **Team Collaboration**: Manage users, teams, and permissions
- 🔄 **Workflow Automation**: Automate status updates and notifications
- ⏱️ **Time Tracking**: Track time spent on tasks and projects
- 📊 **Reporting & Analytics**: Generate insights and custom reports
- 📎 **File Management**: Handle attachments and assets
- 🔔 **Real-time Updates**: Receive live notifications via webhooks
- 🎯 **Custom Fields**: Work with custom columns and data types
- 🔗 **Integration Support**: Connect with other tools and services

## Prerequisites

Before integrating monday.com MCP Server with MCP Gateway, ensure you have:

### monday.com Account Setup

1. **Active monday.com Account**: Sign up at [monday.com](https://monday.com) if you don't have an account
2. **Workspace Access**: Access to at least one workspace where you can create and manage boards
3. **Admin Permissions**: Admin or owner permissions for OAuth app registration and workspace-level operations

### OAuth Application Registration

1. Navigate to your monday.com account settings
2. Go to **Developers** → **My Apps** → **Create App**
3. Configure your OAuth application:
   - **App Name**: Choose a descriptive name (e.g., "MCP Gateway Integration")
   - **Redirect URI**: Set to your MCP Gateway callback URL (e.g., `https://your-gateway.com/oauth/callback`)
   - **Scopes**: Select required permissions (see [Required Permissions](#required-permissions))
4. Save your **Client ID** and **Client Secret** securely

### Required Permissions

The following OAuth scopes are recommended for full functionality:

- `boards:read` - Read board information and structure
- `boards:write` - Create and modify boards
- `users:read` - Access user information
- `teams:read` - Read team and workspace data
- `workspaces:read` - Access workspace information
- `workspaces:write` - Modify workspace settings
- `webhooks:write` - Create and manage webhooks for real-time updates

### Environment Variables

Set the following environment variables in your `.env` file:

```bash
# monday.com OAuth Credentials
MONDAY_CLIENT_ID=your_client_id_here
MONDAY_CLIENT_SECRET=your_client_secret_here
MONDAY_WORKSPACE_ID=your_workspace_id_here

# Webhook Configuration (optional)
MONDAY_WEBHOOK_SECRET=your_webhook_secret_here
```

## Authentication Setup

### OAuth2.1 Flow Configuration

monday.com uses OAuth2.1 for secure authentication. The MCP Gateway handles the OAuth flow automatically when properly configured.

#### Step 1: Configure OAuth Endpoints

```yaml
# config/servers.yaml
servers:
  - id: "monday-official"
    name: "monday.com MCP Server"
    description: "Official monday.com productivity and project management tools"
    transport:
      type: "sse"
      endpoint: "https://mcp.monday.com/sse"
      auth:
        type: "oauth2"
        client_id: "${MONDAY_CLIENT_ID}"
        client_secret: "${MONDAY_CLIENT_SECRET}"
        token_endpoint: "https://auth.monday.com/oauth2/token"
        authorize_endpoint: "https://auth.monday.com/oauth2/authorize"
        scopes:
          - "boards:read"
          - "boards:write"
          - "users:read"
          - "teams:read"
          - "workspaces:read"
          - "workspaces:write"
          - "webhooks:write"
```

#### Step 2: Initiate OAuth Flow

```bash
# Start OAuth authorization
curl -X POST http://localhost:4444/oauth/authorize \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "monday-official",
    "redirect_uri": "https://your-gateway.com/oauth/callback"
  }'
```

The response will include an authorization URL. Direct users to this URL to grant permissions.

#### Step 3: Handle OAuth Callback

After user authorization, monday.com redirects to your callback URL with an authorization code. The MCP Gateway automatically exchanges this for access and refresh tokens.

### Token Management

The MCP Gateway automatically handles:

- **Token Storage**: Securely stores access and refresh tokens
- **Token Refresh**: Automatically refreshes expired tokens
- **Token Expiration**: Monitors token validity and renews before expiration
- **Scope Validation**: Ensures requested scopes are granted

### Manual Token Configuration

For testing or development, you can manually configure tokens:

```bash
# Set access token directly
export MONDAY_ACCESS_TOKEN="your_access_token_here"

# Register server with manual token
curl -X POST http://localhost:4444/servers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "id": "monday-official",
    "name": "monday.com MCP Server",
    "url": "https://mcp.monday.com/sse",
    "transport": "sse",
    "auth": {
      "type": "bearer",
      "token": "'${MONDAY_ACCESS_TOKEN}'"
    }
  }'
```

## MCP Gateway Integration

### Server Registration

Register the monday.com MCP Server with your MCP Gateway instance:

```bash
# Using OAuth2.1 (Recommended)
curl -X POST http://localhost:4444/servers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "id": "monday-official",
    "name": "monday.com MCP Server",
    "description": "Official monday.com productivity and project management tools",
    "url": "https://mcp.monday.com/sse",
    "transport": "sse",
    "auth": {
      "type": "oauth2",
      "client_id": "'${MONDAY_CLIENT_ID}'",
      "client_secret": "'${MONDAY_CLIENT_SECRET}'",
      "token_endpoint": "https://auth.monday.com/oauth2/token",
      "authorize_endpoint": "https://auth.monday.com/oauth2/authorize",
      "scopes": ["boards:read", "boards:write", "users:read", "teams:read"]
    },
    "settings": {
      "timeout": 60,
      "retry_attempts": 3,
      "rate_limit_handling": true,
      "workspace_id": "'${MONDAY_WORKSPACE_ID}'"
    },
    "tags": ["productivity", "project-management", "collaboration"]
  }'
```

### SSE Endpoint Configuration

The monday.com MCP Server uses Server-Sent Events (SSE) for real-time communication:

```python
# Python example: Connect to monday.com via MCP Gateway
import asyncio
from mcp_gateway_client import MCPGatewayClient

async def connect_monday():
    # Initialize gateway client
    gateway = MCPGatewayClient(
        base_url="http://localhost:4444",
        bearer_token=os.getenv("MCPGATEWAY_BEARER_TOKEN")
    )

    # Connect to monday.com server
    await gateway.connect_server("monday-official")

    # List available tools
    tools = await gateway.list_tools("monday-official")
    print(f"Available monday.com tools: {len(tools)}")

    return gateway

# Run connection
gateway = asyncio.run(connect_monday())
```

### Webhook Integration

Configure webhooks for real-time updates from monday.com:

```yaml
# config/webhooks.yaml
webhooks:
  - id: "monday-webhooks"
    server_id: "monday-official"
    endpoint: "https://mcp.monday.com/webhooks"
    events:
      - "item_created"
      - "item_updated"
      - "item_deleted"
      - "board_changed"
      - "column_value_changed"
      - "status_changed"
    auth:
      type: "signature"
      secret: "${MONDAY_WEBHOOK_SECRET}"
      header: "X-Monday-Signature"
    settings:
      retry_attempts: 3
      timeout: 30
      verify_ssl: true
```

Register webhook endpoint:

```bash
curl -X POST http://localhost:4444/webhooks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "server_id": "monday-official",
    "events": ["item_created", "item_updated", "board_changed"],
    "callback_url": "https://your-gateway.com/webhooks/monday",
    "secret": "'${MONDAY_WEBHOOK_SECRET}'"
  }'
```

### Health Checks and Monitoring

Configure health checks to monitor monday.com server availability:

```yaml
# config/health_checks.yaml
health_checks:
  - server_id: "monday-official"
    interval: 60  # seconds
    timeout: 10
    failure_threshold: 3
    success_threshold: 1
    endpoint: "https://mcp.monday.com/health"
```

## Available Tools

The monday.com MCP Server provides comprehensive tools for managing your Work OS:

### Board Management

#### create_board

Create a new board in a workspace.

```json
{
  "tool": "create_board",
  "arguments": {
    "workspace_id": "12345678",
    "board_name": "Q4 Marketing Campaign",
    "board_kind": "public",
    "description": "Marketing initiatives for Q4 2024",
    "template_id": null
  }
}
```

**Parameters:**

- `workspace_id` (required): Target workspace ID
- `board_name` (required): Name of the new board
- `board_kind` (optional): Board visibility - "public", "private", or "share"
- `description` (optional): Board description
- `template_id` (optional): Template to use for board creation

#### get_board

Retrieve board information and structure.

```json
{
  "tool": "get_board",
  "arguments": {
    "board_id": "987654321",
    "include_columns": true,
    "include_items": true,
    "limit": 50
  }
}
```

#### update_board

Update board properties.

```json
{
  "tool": "update_board",
  "arguments": {
    "board_id": "987654321",
    "name": "Q4 Marketing Campaign - Updated",
    "description": "Updated marketing initiatives",
    "communication": "Slack channel: #marketing-q4"
  }
}
```

#### delete_board

Delete a board (requires admin permissions).

```json
{
  "tool": "delete_board",
  "arguments": {
    "board_id": "987654321"
  }
}
```

### Item Operations

#### create_item

Add a new item to a board.

```json
{
  "tool": "create_item",
  "arguments": {
    "board_id": "987654321",
    "group_id": "topics",
    "item_name": "Launch social media campaign",
    "column_values": {
      "status": "Working on it",
      "person": {"id": 12345},
      "date": "2024-12-15",
      "text": "Focus on Instagram and LinkedIn"
    }
  }
}
```

**Parameters:**

- `board_id` (required): Target board ID
- `group_id` (optional): Group/section to add item to
- `item_name` (required): Name of the item
- `column_values` (optional): Initial column values as key-value pairs

#### get_item

Retrieve item details.

```json
{
  "tool": "get_item",
  "arguments": {
    "item_id": "123456789",
    "include_column_values": true,
    "include_updates": true
  }
}
```

#### update_item

Update item properties and column values.

```json
{
  "tool": "update_item",
  "arguments": {
    "item_id": "123456789",
    "column_values": {
      "status": "Done",
      "progress": 100,
      "notes": "Campaign successfully launched"
    }
  }
}
```

#### move_item_to_group

Move an item to a different group within the same board.

```json
{
  "tool": "move_item_to_group",
  "arguments": {
    "item_id": "123456789",
    "group_id": "completed_tasks"
  }
}
```

#### duplicate_item

Create a copy of an existing item.

```json
{
  "tool": "duplicate_item",
  "arguments": {
    "item_id": "123456789",
    "board_id": "987654321",
    "with_updates": false
  }
}
```

### Column Management

#### create_column

Add a new column to a board.

```json
{
  "tool": "create_column",
  "arguments": {
    "board_id": "987654321",
    "title": "Priority",
    "column_type": "status",
    "defaults": {
      "labels": {
        "0": "Low",
        "1": "Medium",
        "2": "High",
        "3": "Critical"
      }
    }
  }
}
```

**Column Types:**

- `text` - Simple text field
- `status` - Status labels with colors
- `date` - Date picker
- `timeline` - Date range
- `people` - User assignment
- `numbers` - Numeric values
- `rating` - Star rating
- `dropdown` - Single select dropdown
- `checkbox` - Boolean checkbox
- `email` - Email address
- `phone` - Phone number
- `link` - URL link
- `file` - File attachments

#### update_column

Modify column properties.

```json
{
  "tool": "update_column",
  "arguments": {
    "board_id": "987654321",
    "column_id": "status_1",
    "title": "Task Status",
    "settings": {
      "labels": {
        "0": "Not Started",
        "1": "In Progress",
        "2": "Review",
        "3": "Completed"
      }
    }
  }
}
```

#### delete_column

Remove a column from a board.

```json
{
  "tool": "delete_column",
  "arguments": {
    "board_id": "987654321",
    "column_id": "status_1"
  }
}
```

### User and Team Management

#### get_users

List users in the workspace.

```json
{
  "tool": "get_users",
  "arguments": {
    "workspace_id": "12345678",
    "kind": "all",
    "limit": 100
  }
}
```

**Parameters:**

- `workspace_id` (optional): Filter by workspace
- `kind` (optional): "all", "non_guests", "guests"
- `limit` (optional): Maximum number of users to return

#### get_teams

Retrieve team information.

```json
{
  "tool": "get_teams",
  "arguments": {
    "workspace_id": "12345678"
  }
}
```

#### assign_user_to_item

Assign a user to an item.

```json
{
  "tool": "assign_user_to_item",
  "arguments": {
    "item_id": "123456789",
    "user_id": "12345",
    "column_id": "person"
  }
}
```

### Workflow Automation

#### create_automation

Set up automated workflows.

```json
{
  "tool": "create_automation",
  "arguments": {
    "board_id": "987654321",
    "trigger": {
      "type": "status_changed",
      "column_id": "status",
      "value": "Done"
    },
    "action": {
      "type": "notify_user",
      "user_id": "12345",
      "message": "Task completed: {item_name}"
    }
  }
}
```

#### get_automations

List board automations.

```json
{
  "tool": "get_automations",
  "arguments": {
    "board_id": "987654321"
  }
}
```

### Time Tracking

#### log_time

Track time spent on an item.

```json
{
  "tool": "log_time",
  "arguments": {
    "item_id": "123456789",
    "hours": 3.5,
    "date": "2024-12-10",
    "user_id": "12345",
    "notes": "Campaign planning and design"
  }
}
```

#### get_time_tracking

Retrieve time tracking data.

```json
{
  "tool": "get_time_tracking",
  "arguments": {
    "item_id": "123456789",
    "start_date": "2024-12-01",
    "end_date": "2024-12-31"
  }
}
```

### File Management

#### upload_file

Upload a file to an item.

```json
{
  "tool": "upload_file",
  "arguments": {
    "item_id": "123456789",
    "file_path": "/path/to/document.pdf",
    "column_id": "files"
  }
}
```

#### get_assets

Retrieve files attached to an item.

```json
{
  "tool": "get_assets",
  "arguments": {
    "item_id": "123456789"
  }
}
```

### Reporting and Analytics

#### generate_report

Create custom reports.

```json
{
  "tool": "generate_report",
  "arguments": {
    "board_id": "987654321",
    "report_type": "status_summary",
    "date_range": {
      "start": "2024-12-01",
      "end": "2024-12-31"
    },
    "group_by": "status",
    "include_charts": true
  }
}
```

#### get_board_activity

Retrieve board activity log.

```json
{
  "tool": "get_board_activity",
  "arguments": {
    "board_id": "987654321",
    "limit": 50,
    "from_date": "2024-12-01"
  }
}
```

## Usage Examples

### Example 1: Creating and Managing a Project Board

```python
import asyncio
from mcp_gateway_client import MCPGatewayClient

async def setup_project_board():
    """Create a new project board with items and team assignments"""
    gateway = MCPGatewayClient(
        base_url="http://localhost:4444",
        bearer_token=os.getenv("MCPGATEWAY_BEARER_TOKEN")
    )

    # Create a new board
    board = await gateway.call_tool(
        server="monday-official",
        tool="create_board",
        arguments={
            "workspace_id": "12345678",
            "board_name": "Website Redesign Project",
            "board_kind": "public",
            "description": "Complete website redesign for Q1 2025"
        }
    )

    board_id = board["id"]
    print(f"Created board: {board_id}")

    # Add custom columns
    await gateway.call_tool(
        server="monday-official",
        tool="create_column",
        arguments={
            "board_id": board_id,
            "title": "Priority",
            "column_type": "status",
            "defaults": {
                "labels": {
                    "0": "Low",
                    "1": "Medium",
                    "2": "High"
                }
            }
        }
    )

    # Create project tasks
    tasks = [
        "Design mockups",
        "Develop frontend",
        "Backend API integration",
        "Testing and QA",
        "Deployment"
    ]

    for task_name in tasks:
        item = await gateway.call_tool(
            server="monday-official",
            tool="create_item",
            arguments={
                "board_id": board_id,
                "item_name": task_name,
                "column_values": {
                    "status": "Not Started",
                    "priority": "Medium"
                }
            }
        )
        print(f"Created task: {item['name']}")

    return board_id

# Run the setup
board_id = asyncio.run(setup_project_board())
```

### Example 2: Automated Status Updates

```python
async def automate_status_workflow(board_id):
    """Set up automated notifications when tasks are completed"""
    gateway = MCPGatewayClient(
        base_url="http://localhost:4444",
        bearer_token=os.getenv("MCPGATEWAY_BEARER_TOKEN")
    )

    # Create automation: notify team when status changes to "Done"
    automation = await gateway.call_tool(
        server="monday-official",
        tool="create_automation",
        arguments={
            "board_id": board_id,
            "trigger": {
                "type": "status_changed",
                "column_id": "status",
                "value": "Done"
            },
            "action": {
                "type": "notify_team",
                "message": "🎉 Task completed: {item_name} by {person}"
            }
        }
    )

    print(f"Automation created: {automation['id']}")

    # Create automation: move to "Completed" group when done
    await gateway.call_tool(
        server="monday-official",
        tool="create_automation",
        arguments={
            "board_id": board_id,
            "trigger": {
                "type": "status_changed",
                "column_id": "status",
                "value": "Done"
            },
            "action": {
                "type": "move_item_to_group",
                "group_id": "completed_tasks"
            }
        }
    )
```

### Example 3: Team Collaboration and Time Tracking

```python
async def track_team_progress(board_id):
    """Monitor team progress and log time"""
    gateway = MCPGatewayClient(
        base_url="http://localhost:4444",
        bearer_token=os.getenv("MCPGATEWAY_BEARER_TOKEN")
    )

    # Get all items from the board
    board = await gateway.call_tool(
        server="monday-official",
        tool="get_board",
        arguments={
            "board_id": board_id,
            "include_items": True
        }
    )

    # Track time for each in-progress item
    for item in board["items"]:
        if item["column_values"]["status"] == "Working on it":
            # Log time
            await gateway.call_tool(
                server="monday-official",
                tool="log_time",
                arguments={
                    "item_id": item["id"],
                    "hours": 2.0,
                    "date": "2024-12-10",
                    "notes": "Development work"
                }
            )

            # Update progress
            await gateway.call_tool(
                server="monday-official",
                tool="update_item",
                arguments={
                    "item_id": item["id"],
                    "column_values": {
                        "progress": 50
                    }
                }
            )

    # Generate progress report
    report = await gateway.call_tool(
        server="monday-official",
        tool="generate_report",
        arguments={
            "board_id": board_id,
            "report_type": "status_summary",
            "include_charts": True
        }
    )

    print(f"Team Progress Report:")
    print(f"- Total Items: {report['total_items']}")
    print(f"- Completed: {report['completed_items']}")
    print(f"- In Progress: {report['in_progress_items']}")
    print(f"- Not Started: {report['not_started_items']}")
```

### Example 4: Webhook Event Handling

```python
from fastapi import FastAPI, Request, HTTPException
import hmac
import hashlib

app = FastAPI()

async def verify_monday_signature(request: Request, secret: str) -> bool:
    """Verify webhook signature from monday.com"""
    signature = request.headers.get("X-Monday-Signature")
    if not signature:
        return False

    body = await request.body()
    expected_signature = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature, expected_signature)

@app.post("/webhooks/monday")
async def handle_monday_webhook(request: Request):
    """Handle incoming webhooks from monday.com"""
    # Verify signature
    secret = os.getenv("MONDAY_WEBHOOK_SECRET")
    if not await verify_monday_signature(request, secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse webhook payload
    payload = await request.json()
    event_type = payload.get("event", {}).get("type")

    # Handle different event types
    if event_type == "item_created":
        item = payload["event"]["pulseId"]
        print(f"New item created: {item}")

        # Automatically assign to team member
        gateway = MCPGatewayClient(
            base_url="http://localhost:4444",
            bearer_token=os.getenv("MCPGATEWAY_BEARER_TOKEN")
        )

        await gateway.call_tool(
            server="monday-official",
            tool="assign_user_to_item",
            arguments={
                "item_id": item,
                "user_id": "12345"
            }
        )

    elif event_type == "status_changed":
        item_id = payload["event"]["pulseId"]
        new_status = payload["event"]["value"]["label"]["text"]
        print(f"Status changed to: {new_status}")

        # Send notification or trigger other actions
        if new_status == "Done":
            # Archive completed item
            pass

    return {"status": "processed"}
```

### Example 5: Bulk Operations and Reporting

```python
async def generate_monthly_report(workspace_id: str, month: str):
    """Generate comprehensive monthly report across all boards"""
    gateway = MCPGatewayClient(
        base_url="http://localhost:4444",
        bearer_token=os.getenv("MCPGATEWAY_BEARER_TOKEN")
    )

    # Get all boards in workspace
    boards = await gateway.call_tool(
        server="monday-official",
        tool="get_boards",
        arguments={
            "workspace_id": workspace_id
        }
    )

    report_data = {
        "month": month,
        "boards": [],
        "total_items": 0,
        "completed_items": 0,
        "total_hours": 0
    }

    # Analyze each board
    for board in boards:
        board_report = await gateway.call_tool(
            server="monday-official",
            tool="generate_report",
            arguments={
                "board_id": board["id"],
                "report_type": "status_summary",
                "date_range": {
                    "start": f"{month}-01",
                    "end": f"{month}-31"
                }
            }
        )

        # Get time tracking data
        time_data = await gateway.call_tool(
            server="monday-official",
            tool="get_time_tracking",
            arguments={
                "board_id": board["id"],
                "start_date": f"{month}-01",
                "end_date": f"{month}-31"
            }
        )

        report_data["boards"].append({
            "name": board["name"],
            "items": board_report["total_items"],
            "completed": board_report["completed_items"],
            "hours": sum(entry["hours"] for entry in time_data)
        })

        report_data["total_items"] += board_report["total_items"]
        report_data["completed_items"] += board_report["completed_items"]
        report_data["total_hours"] += sum(entry["hours"] for entry in time_data)

    # Calculate metrics
    report_data["completion_rate"] = (
        report_data["completed_items"] / report_data["total_items"] * 100
        if report_data["total_items"] > 0 else 0
    )

    print(f"\n📊 Monthly Report for {month}")
    print(f"{'='*50}")
    print(f"Total Items: {report_data['total_items']}")
    print(f"Completed: {report_data['completed_items']}")
    print(f"Completion Rate: {report_data['completion_rate']:.1f}%")
    print(f"Total Hours: {report_data['total_hours']:.1f}")
    print(f"\nBoard Breakdown:")
    for board in report_data["boards"]:
        print(f"  - {board['name']}: {board['completed']}/{board['items']} items, {board['hours']:.1f} hours")

    return report_data

# Generate report
report = asyncio.run(generate_monthly_report("12345678", "2024-12"))
```

## Troubleshooting

### OAuth Setup and Permission Issues

#### Problem: Authorization fails with "insufficient_scope" error

**Solution:**

1. Verify that all required scopes are included in your OAuth configuration
2. Re-authorize the application with updated scopes
3. Check that your monday.com account has the necessary permissions

```bash
# Check current scopes
curl -X GET http://localhost:4444/servers/monday-official/auth/scopes \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}"

# Update scopes
curl -X PATCH http://localhost:4444/servers/monday-official \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "auth": {
      "scopes": ["boards:read", "boards:write", "users:read", "teams:read", "workspaces:write"]
    }
  }'
```

#### Problem: "invalid_client" error during OAuth flow

**Solution:**

1. Verify `MONDAY_CLIENT_ID` and `MONDAY_CLIENT_SECRET` are correct
2. Ensure redirect URI matches exactly what's configured in monday.com
3. Check that the OAuth app is active in your monday.com account

### SSE Connection and Timeout Problems

#### Problem: SSE connection drops frequently

**Solution:**

1. Increase timeout settings in server configuration
2. Implement reconnection logic with exponential backoff
3. Check network stability and firewall rules

```yaml
# Increase timeout in config
servers:
  - id: "monday-official"
    transport:
      type: "sse"
      endpoint: "https://mcp.monday.com/sse"
    settings:
      timeout: 120  # Increase from default 60
      retry_attempts: 5
      retry_delay: 2
```

```python
# Implement reconnection logic
async def connect_with_retry(gateway, server_id, max_retries=5):
    """Connect to server with exponential backoff"""
    for attempt in range(max_retries):
        try:
            await gateway.connect_server(server_id)
            print(f"Connected to {server_id}")
            return True
        except ConnectionError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"Connection failed, retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                print(f"Failed to connect after {max_retries} attempts")
                raise
```

#### Problem: "Connection timeout" errors

**Solution:**

1. Check monday.com service status at [status.monday.com](https://status.monday.com)
2. Verify network connectivity to `mcp.monday.com`
3. Review MCP Gateway logs for detailed error messages

```bash
# Test connectivity
curl -v https://mcp.monday.com/sse

# Check MCP Gateway logs
docker logs mcp-gateway --tail 100 | grep monday
```

### Rate Limiting and API Quotas

#### Problem: "rate_limit_exceeded" errors

**Solution:**

1. Implement request throttling in your application
2. Use batch operations where possible
3. Cache frequently accessed data
4. Consider upgrading your monday.com plan for higher limits

```python
from asyncio import Semaphore
import time

class RateLimitedMondayClient:
    """Client with built-in rate limiting"""

    def __init__(self, gateway, requests_per_minute=60):
        self.gateway = gateway
        self.semaphore = Semaphore(requests_per_minute)
        self.request_times = []

    async def call_tool(self, tool, arguments):
        """Call tool with rate limiting"""
        async with self.semaphore:
            # Remove old timestamps
            current_time = time.time()
            self.request_times = [
                t for t in self.request_times
                if current_time - t < 60
            ]

            # Wait if at limit
            if len(self.request_times) >= 60:
                wait_time = 60 - (current_time - self.request_times[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)

            # Make request
            self.request_times.append(time.time())
            return await self.gateway.call_tool(
                server="monday-official",
                tool=tool,
                arguments=arguments
            )
```

#### Problem: Quota exceeded for workspace

**Solution:**

1. Review your monday.com plan limits
2. Optimize queries to reduce API calls
3. Use webhooks instead of polling for updates
4. Contact monday.com support for quota increase

### Workspace Access and Visibility Issues

#### Problem: "board_not_found" or "access_denied" errors

**Solution:**

1. Verify the user has access to the workspace and board
2. Check board visibility settings (public vs. private)
3. Ensure the OAuth token has the correct workspace scope

```python
async def verify_board_access(gateway, board_id):
    """Check if current user can access a board"""
    try:
        board = await gateway.call_tool(
            server="monday-official",
            tool="get_board",
            arguments={"board_id": board_id}
        )
        print(f"✓ Access granted to board: {board['name']}")
        return True
    except Exception as e:
        if "not_found" in str(e):
            print(f"✗ Board {board_id} not found or no access")
        elif "access_denied" in str(e):
            print(f"✗ Access denied to board {board_id}")
        return False
```

#### Problem: Webhook events not received

**Solution:**

1. Verify webhook endpoint is publicly accessible
2. Check webhook signature validation
3. Ensure webhook is properly registered in monday.com
4. Review webhook logs for delivery failures

```bash
# Test webhook endpoint
curl -X POST https://your-gateway.com/webhooks/monday \
  -H "Content-Type: application/json" \
  -H "X-Monday-Signature: test" \
  -d '{"event": {"type": "test"}}'

# List registered webhooks
curl -X GET http://localhost:4444/webhooks?server_id=monday-official \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}"
```

### Common Error Codes

| Error Code | Description | Solution |
|------------|-------------|----------|
| `invalid_token` | OAuth token is invalid or expired | Refresh token or re-authorize |
| `insufficient_scope` | Missing required OAuth scopes | Update scopes and re-authorize |
| `rate_limit_exceeded` | Too many requests | Implement rate limiting |
| `board_not_found` | Board doesn't exist or no access | Verify board ID and permissions |
| `column_not_found` | Column doesn't exist on board | Check column ID or create column |
| `invalid_column_value` | Column value format is incorrect | Review column type and format |
| `workspace_access_denied` | No access to workspace | Request workspace access |
| `automation_limit_reached` | Maximum automations exceeded | Remove unused automations |

## Configuration Examples

### Complete Server Configuration

```yaml
# config/servers.yaml
servers:
  - id: "monday-official"
    name: "monday.com MCP Server"
    description: "Official monday.com productivity and project management tools"
    enabled: true

    # Transport configuration
    transport:
      type: "sse"
      endpoint: "https://mcp.monday.com/sse"

      # OAuth2.1 authentication
      auth:
        type: "oauth2"
        client_id: "${MONDAY_CLIENT_ID}"
        client_secret: "${MONDAY_CLIENT_SECRET}"
        token_endpoint: "https://auth.monday.com/oauth2/token"
        authorize_endpoint: "https://auth.monday.com/oauth2/authorize"
        scopes:
          - "boards:read"
          - "boards:write"
          - "users:read"
          - "teams:read"
          - "workspaces:read"
          - "workspaces:write"
          - "webhooks:write"

        # Token refresh settings
        refresh_before_expiry: 300  # Refresh 5 minutes before expiry
        auto_refresh: true

    # Server settings
    settings:
      timeout: 60
      retry_attempts: 3
      retry_delay: 2
      rate_limit_handling: true
      workspace_id: "${MONDAY_WORKSPACE_ID}"

      # Connection pool
      max_connections: 10
      connection_timeout: 30

      # Caching
      cache_enabled: true
      cache_ttl: 300

    # Tags for organization
    tags:
      - "productivity"
      - "project-management"
      - "collaboration"
      - "official"

    # Metadata
    metadata:
      provider: "monday.com"
      category: "Productivity"
      documentation: "https://developer.monday.com/apps/docs/mcp"
      support: "https://support.monday.com"
```

### Webhook Configuration

```yaml
# config/webhooks.yaml
webhooks:
  - id: "monday-item-events"
    server_id: "monday-official"
    endpoint: "https://mcp.monday.com/webhooks"

    # Events to subscribe to
    events:
      - "item_created"
      - "item_updated"
      - "item_deleted"
      - "item_moved"

    # Authentication
    auth:
      type: "signature"
      secret: "${MONDAY_WEBHOOK_SECRET}"
      header: "X-Monday-Signature"
      algorithm: "sha256"

    # Delivery settings
    settings:
      retry_attempts: 3
      retry_delay: 5
      timeout: 30
      verify_ssl: true

      # Batch settings
      batch_enabled: false
      batch_size: 10
      batch_timeout: 5

  - id: "monday-board-events"
    server_id: "monday-official"
    endpoint: "https://mcp.monday.com/webhooks"

    events:
      - "board_created"
      - "board_updated"
      - "board_deleted"
      - "column_created"
      - "column_updated"

    auth:
      type: "signature"
      secret: "${MONDAY_WEBHOOK_SECRET}"
      header: "X-Monday-Signature"
      algorithm: "sha256"

    settings:
      retry_attempts: 3
      timeout: 30
```

### Environment Variables Template

```bash
# .env.monday
# monday.com OAuth Configuration
MONDAY_CLIENT_ID=your_client_id_here
MONDAY_CLIENT_SECRET=your_client_secret_here
MONDAY_WORKSPACE_ID=your_workspace_id_here

# Webhook Configuration
MONDAY_WEBHOOK_SECRET=your_webhook_secret_here

# Optional: Direct token (for testing)
MONDAY_ACCESS_TOKEN=your_access_token_here

# MCP Gateway Configuration
MCPGATEWAY_BEARER_TOKEN=your_gateway_token_here
MCPGATEWAY_BASE_URL=http://localhost:4444

# Logging
MONDAY_LOG_LEVEL=INFO
MONDAY_DEBUG=false
```

### Docker Compose Configuration

```yaml
# docker-compose.yml
version: '3.8'

services:
  mcp-gateway:
    image: mcpgateway/gateway:latest
    ports:
      - "4444:4444"
    environment:
      - MONDAY_CLIENT_ID=${MONDAY_CLIENT_ID}
      - MONDAY_CLIENT_SECRET=${MONDAY_CLIENT_SECRET}
      - MONDAY_WORKSPACE_ID=${MONDAY_WORKSPACE_ID}
      - MONDAY_WEBHOOK_SECRET=${MONDAY_WEBHOOK_SECRET}
    volumes:
      - ./config:/app/config
      - ./data:/app/data
    networks:
      - mcp-network
    restart: unless-stopped

    # Health check
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4444/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

networks:
  mcp-network:
    driver: bridge
```

## Best Practices

### 1. Security

- **Never commit credentials**: Use environment variables for all sensitive data
- **Rotate secrets regularly**: Update OAuth secrets and webhook secrets periodically
- **Validate webhooks**: Always verify webhook signatures before processing
- **Use HTTPS**: Ensure all webhook endpoints use HTTPS
- **Limit scopes**: Request only the OAuth scopes you need

### 2. Performance

- **Cache frequently accessed data**: Reduce API calls by caching board structures
- **Use batch operations**: Combine multiple updates into single requests when possible
- **Implement rate limiting**: Respect monday.com's rate limits
- **Use webhooks**: Prefer webhooks over polling for real-time updates
- **Optimize queries**: Request only the fields you need

### 3. Error Handling

- **Implement retries**: Use exponential backoff for transient failures
- **Log errors**: Maintain detailed logs for debugging
- **Handle rate limits**: Implement proper rate limit handling
- **Validate inputs**: Check data before sending to monday.com API
- **Monitor health**: Set up health checks and alerts

### 4. Development

- **Use test workspaces**: Create separate workspaces for development and testing
- **Version control configs**: Keep configuration files in version control
- **Document workflows**: Maintain documentation for custom automations
- **Test webhooks**: Use tools like ngrok for local webhook testing
- **Follow conventions**: Use consistent naming for boards, columns, and items

## Related Resources

### Official Documentation

- [monday.com MCP Server](https://developer.monday.com/apps/docs/mcp) - Official MCP server documentation
- [monday.com API Documentation](https://developer.monday.com/api-reference/docs) - Complete API reference
- [OAuth Setup Guide](https://developer.monday.com/apps/docs/oauth) - OAuth 2.1 implementation guide
- [Webhooks Documentation](https://developer.monday.com/apps/docs/webhooks) - Webhook setup and events
- [monday.com Developer Portal](https://developer.monday.com) - Developer resources and tools

### Community and Support

- [monday.com Community](https://community.monday.com) - Community forum and discussions
- [monday.com Support](https://support.monday.com) - Official support portal
- [MCP Gateway GitHub](https://github.com/IBM/mcp-context-forge) - Report issues and contribute
- [monday.com Status](https://status.monday.com) - Service status and incidents

### Tutorials and Examples

- [MCP Gateway Tutorials](../../../../tutorials/index.md) - Getting started guides
- [API Usage Examples](../../../../manage/api-usage.md) - API integration examples
- [Deployment Guide](../../../../deployment/index.md) - Deployment best practices

## Next Steps

1. **Set up OAuth**: Register your application in monday.com
2. **Configure MCP Gateway**: Add monday.com server to your gateway
3. **Test connection**: Verify authentication and basic operations
4. **Explore tools**: Try different tools to understand capabilities
5. **Build workflows**: Create custom automations for your use cases
6. **Set up webhooks**: Enable real-time updates for your application
7. **Monitor and optimize**: Track usage and optimize performance

For additional help, consult the [FAQ](../../../../faq/index.md) or reach out to the community.
