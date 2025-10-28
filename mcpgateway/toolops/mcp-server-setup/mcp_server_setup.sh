echo "setting up MCP server for salesloft get all actions OAPI at port 9009"
nohup python -m mcpgateway.translate      --stdio "python ./toolops_fastmcp_server.py"      --expose-streamable-http      --expose-sse      --port 9009 &
