
### Starting MCP context forge from git repo
* Use `make venv` to create virtual environment (tested with python 3.12)
* Install MCP-CF and dependencies using `make install install-dev`
* Install toolops and other dependencies using `uv pip install .'[toolops,grpc]'`.Please check if all the packages are installed in the created virtual environment.
* `uvicorn mcpgateway.main:app --host 0.0.0.0 --port 4444 --workers 2 --env-file .env` will start Context forge UI and APIs at http://localhost:4444/docs and toolops API endpoints will be shown.

### Important NOTE:
* Please provide all configurations such as LLM provider, api keys etc., in `.env` file. And you need to set `TOOLOPS_ENABLED=true` for enabling toolops functionality`
* While selecting LLM model , please use the model that supports instruction following (IF) text generation tasks and tool-calling capabilities for executing tools in chat mode. For example `granite4:micro` , `llama-3-3-70b-instruct` etc.,
* Toolops depends on `agent life cycle toolkit(ALTK)` which is specified in `pyproject.toml` required packages, to install ALTK please set-up github public key SSH if required.
* For toolops developement (Caution) : Only if required to re-install of latest version of `agent life cycle toolkit(ALTK)` from git repo in case of fixes/updates please use pip install via git ssh url.

### Testing toolops requires MCP server running to set up MCP server using OAPI specification
```
python3 -m mcpgateway.translate \
     --stdio "uvx mcp-server-git" \
     --expose-sse \
     --expose-streamable-http \
     --port 9000
```
