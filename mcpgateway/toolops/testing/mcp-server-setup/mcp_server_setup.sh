# Script to start MCP server using OAPI speficifciation , this server is used for toolops testing purposes.
echo "setting up MCP server for salesloft get all actions OAPI at port 9009"
python -m mcpgateway.translate      --stdio "python ./mcpgateway/toolops/testing/mcp-server-setup/toolops_fastmcp_server.py"   --expose-streamable-http   --expose-sse      --port 9009
