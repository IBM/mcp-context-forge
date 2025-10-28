import httpx
import json
from fastmcp import FastMCP
api_url = "https://api.salesloft.com"
api_spec_path = "./mcpgateway/toolops/mcp-server-setup/api_specs/Wipro_Salesloft_Get_all_actions_short.json"
mcp_server_name = "salesloft get all actions."
client = httpx.AsyncClient(base_url=api_url,headers={"Authorization": "Bearer ***REMOVED***"})
openapi_spec=json.load(open(api_spec_path,'r'))
# Create the MCP server
mcp = FastMCP.from_openapi(openapi_spec=openapi_spec, client=client, name=mcp_server_name)

if __name__ == "__main__":
    mcp.run()


'''
nohup python -m mcpgateway.translate      --stdio "python ./toolops_fastmcp_server.py"      --expose-streamable-http      --expose-sse      --port 8001 &
'''



# npx @modelcontextprotocol/inspector 

# Authorization: Bearer "***REMOVED***"

'''

[
    {
        "name": "salesloft all actions",
        "displayName": "salesloft actions",
        "url": "https://api.salesloft.com/v2/actions",
        "integration_type": "REST",
        "request_type": "GET",
        "description": "Get all actions in salesloft",
        "auth_type": "bearer",
        "auth_value": "***REMOVED***",
        "headers": {
            "Accept": "application/json",
            "User-Agent": "MCP-Gateway/1.0"
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "string",
                    "description": "the ids of actions"
                },
                "step_id": {
                    "type": "string",
                    "description": "The ID of the step to retrieve. If not provided, all steps for the pipeline will be returned."
                },
                "type": {
                    "type": "string",
                    "description": "Filter actions by type. email, phone, integration etc."
                }
            },
            "required": ["ids"]
        },
        "jsonpath_filter": "$.main",
        "tags": [
            "salesloft","api"
        ]
    }
]


'''