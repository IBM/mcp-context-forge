### Setup toolops SDK in MCP context forge environment
* `git clone git@github.ibm.com:research-toolops/toolops-sdk.git` clone toolops SDK repo
* Now install toolops SDK using `pip install .` (there are package version differences between MCP-CF and ToolOps , fix is required for the PR)
* Now set environment variables required for LLM configuration
    ```
    export WATSONX_APIKEY=xxxxxxxxxxxxxxxxxxxxx
    export WATSONX_PROJECT_ID=xxxxxxxxxxxxxxxxxx
    ``` 

### Starting MCP context forge from git repo 
* Install dependencies using `pip install .`
* `uvicorn mcpgateway.main:app --host 0.0.0.0 --port 4444 --workers 4` will start Context forge UI and APIs at http://localhost:4444/docs and toolops API endpoints will be shown.