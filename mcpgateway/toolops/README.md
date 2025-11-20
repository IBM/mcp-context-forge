
### Starting MCP context forge from git repo
* Use `make venv` to create virtual environment (tested with python 3.12)
* Install MCP-CF and toolops dependencies using `make install install-dev install-altk install-toolops`. Please check if all the packages are installed in the created virtual environment.
* `uvicorn mcpgateway.main:app --host 0.0.0.0 --port 4444 --workers 2 --env-file .env` will start Context forge UI and APIs at http://localhost:4444/docs and toolops API endpoints will be shown.

### Important NOTE:
* Please provide all configurations such as LLM provider, api keys etc., in `.env` file. And you need to set `TOOLOPS_ENABLED=true` for enabling toolops functionality`
* Toolops depends on `agent life cycle toolkit(ALTK)` which is specified in `pyproject.toml` required packages, to install ALTK please set-up github public key SSH if required.
* Caution : Only if required to re-install of latest version of `agent life cycle toolkit(ALTK)` from git repo in case of fixes/updates please use pip install via git ssh url.

### Testing toolops requires MCP server running to set up MCP server using OAPI specification
* `source mcpgateway/toolops/testing/mcp-server-setup/mcp_server_setup.sh` running this script will start `salesloft get all actions` MCP server at port 9009 , which can be used for testing.
