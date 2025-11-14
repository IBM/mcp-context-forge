 
### Starting MCP context forge from git repo 
* Install dependencies using `pip install .'[dev-all,toolops]'`
* `uvicorn mcpgateway.main:app --host 0.0.0.0 --port 4444 --workers 4 --env-file .env` will start Context forge UI and APIs at http://localhost:4444/docs and toolops API endpoints will be shown.

### Testing toolops requires MCP server running to set up MCP server using OAPI specification
* `pip install fastmcp` to install library dependency.
* `source mcpgateway/toolops/testing/mcp-server-setup/mcp_server_setup.sh` running this script will start `salesloft get all actions` MCP server at port 9009 , which can be used for testing.