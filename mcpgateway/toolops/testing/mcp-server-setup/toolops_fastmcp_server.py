import httpx
import json
import os
from fastmcp import FastMCP
api_url = "https://api.salesloft.com"
api_spec_path = "./mcpgateway/toolops/mcp-server-setup/api_specs/Wipro_Salesloft_Get_all_actions_short.json"
mcp_server_name = "salesloft get all actions"
SALESLOFT_BEARER_TOKEN = os.environ.get("SALESLOFT_BEARER_TOKEN","")
client = httpx.AsyncClient(base_url=api_url,headers={"Authorization": "Bearer "+SALESLOFT_BEARER_TOKEN})
openapi_spec=json.load(open(api_spec_path,'r'))
# Create the MCP server
mcp = FastMCP.from_openapi(openapi_spec=openapi_spec, client=client, name=mcp_server_name)

if __name__ == "__main__":
    if SALESLOFT_BEARER_TOKEN == "":
        print("Please set SALESLOFT_BEARER_TOKEN asn env variable")
    else:
        print("SALESLOFT_BEARER_TOKEN",SALESLOFT_BEARER_TOKEN)
        mcp.run()


'''
nohup python -m mcpgateway.translate      --stdio "python ./toolops_fastmcp_server.py"      --expose-streamable-http      --expose-sse      --port 8001 &
'''



# npx @modelcontextprotocol/inspector 



