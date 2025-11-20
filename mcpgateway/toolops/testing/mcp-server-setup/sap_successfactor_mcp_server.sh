echo "setting up MCP server for sap successfactore time off OAPI at port 9008"
nohup python ./mcpgateway/toolops/testing/mcp-server-setup/time_off.py &> ./mcpgateway/toolops/testing/mcp-server-setup/time_off_server.log &
python -m mcpgateway.translate      --stdio "python ./mcpgateway/toolops/testing/mcp-server-setup/sap_successfactor_mcp_server.py"      --expose-streamable-http      --expose-sse      --port 9008
