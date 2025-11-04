from datetime import datetime
import random
import json

from fastapi import APIRouter
from pydantic import BaseModel
import time

router = APIRouter()

# @router.post("/enrich_tools")
# async def enrich_tools(tools):
#     # your enrichment logic here
#     enrich_tools_fun(tools)
#     return {"message": "Tools enriched successfully!"}

# @router.post("/tool_validation")
# async def tool_validation(tools):
#     # your validation logic here
#     validate_tools_fun(tools)
#     return {"message": "Tool validation completed successfully!"}

class ToolList(BaseModel):
    tools: list[str]

@router.post("/enrich_tools_util")
async def enrich_tools(payload: ToolList):
    enriched = []
    for tool in payload.tools:
        # placeholder enrichment logic
        with open('./mcpgateway/enrich_out.json') as json_data:
            d = json.load(json_data)
            enriched.append(d)
    time.sleep(10)
    return {"message": f"Enriched {len(enriched)} tools successfully.", "details": enriched}

@router.post("/tool_validation_util")
async def tool_validation(payload: ToolList):
    validated = []
    for tool in payload.tools:
        # placeholder validation logic
        with open('./mcpgateway/test_cases.json') as json_data:
            d = json.load(json_data)
            validated.append(d)
    time.sleep(10)
    return {"message": f"Validated {len(validated)} tools successfully.", "details": validated}

TOOLS = [
    {"name": "everything-echo", "type": "MCP", "status": "Active", "desc": "Echoes input back as output."},
    {"name": "everything-add", "type": "MCP", "status": "Active", "desc": "Adds numbers and returns sum."},
    {"name": "everything-random", "type": "MCP", "status": "Active", "desc": "Generates a random value."},
    {"name": "everything-summary", "type": "MCP", "status": "Inactive", "desc": "Summarizes given text."},
]


def enrich_tools_fun(tools: list[dict]) -> list[dict]:
    """
    Enrich tools with metadata like version, owner, and last_updated.
    This simulates a backend enrichment process.
    """
    enriched = []
    for tool in tools:
        enriched_tool = tool.copy()
        enriched_tool["version"] = f"v{random.randint(1, 5)}.{random.randint(0, 9)}"
        enriched_tool["owner"] = random.choice(["Team Alpha", "Team Beta", "Team Gamma"])
        enriched_tool["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        enriched.append(enriched_tool)
    return enriched


def validate_tools_fun(tools: list[dict]) -> dict:
    """
    Validate tool configurations and return summary of validation results.
    A valid tool must have: name, type, desc, and an 'Active' status.
    """
    results = {"valid": [], "invalid": []}

    for tool in tools:
        missing_fields = [f for f in ["name", "type", "desc"] if f not in tool or not tool[f]]
        if missing_fields:
            results["invalid"].append({
                "tool": tool.get("name", "Unknown"),
                "error": f"Missing fields: {', '.join(missing_fields)}"
            })
        elif tool.get("status", "").lower() != "active":
            results["invalid"].append({
                "tool": tool["name"],
                "error": "Tool is inactive"
            })
        else:
            results["valid"].append({
                "tool": tool["name"],
                "message": "Validation passed"
            })

    results["summary"] = {
        "total": len(tools),
        "valid": len(results["valid"]),
        "invalid": len(results["invalid"]),
    }
    return results


def get_tools(query: str = "", selected: str = ""):
    """
    Filter tools based on query and return selected tools.
    """
    selected_tools = selected.split(",") if selected else []
    filtered_tools = (
        [t for t in TOOLS if query.lower() in t["name"].lower()]
        if query else TOOLS
    )
    return filtered_tools, selected_tools


def handle_selection(tool: str, selected: str, action: str):
    """
    Add, remove, or clear selected tools list.
    """
    selected_tools = selected.split(",") if selected else []

    if action == "add" and tool not in selected_tools:
        selected_tools.append(tool)
    elif action == "remove" and tool in selected_tools:
        selected_tools.remove(tool)
    elif action == "clear":
        selected_tools = []

    return selected_tools
