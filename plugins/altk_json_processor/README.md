# ALTKJsonProcessor for Context Forge MCP Gateway

> Author: Jason Tsay
> Version: 0.1.0

Uses JSON Processor from ALTK to extract data from long JSON responses. See the [ALTK](https://altk.ai/) and the [JSON Processor component in the ALTK repo](https://github.com/AgentToolkit/agent-lifecycle-toolkit/tree/main/altk/post_tool/code_generation) for more details on how the component works.

## Hooks
- `tool_post_invoke` - Detects long JSON responses and processes as necessary

## Installation

1. Copy .env.example .env
2. Enable plugins in `.env`
3. Enable the "ALTKJsonProcessor" plugin in `plugins/config.yaml`.
4. Install the optional dependency `altk` (i.e. `pip install mcp-context-forge[altk]`)

## Configuration

```yaml
 - name: "ALTKJsonProcessor"
    kind: "plugins.altk_json_processor.json_processor.ALTKJsonProcessor"
    description: "Uses JSON Processor from ALTK to extract data from long JSON responses"
    hooks: ["tool_post_invoke"]
    tags: ["plugin"]
    mode: "enforce"
    priority: 150
    conditions: []
    config:
      jsonprocessor_query: ""
      llm_provider: "watsonx" # one of watsonx, ollama, openai, anthropic
      watsonx:
        wx_api_key: "" # optional, can define WX_API_KEY instead
        wx_project_id: "" # optional, can define WX_PROJECT_ID instead
        wx_url: "https://us-south.ml.cloud.ibm.com"
      ollama:
        ollama_url: "http://localhost:11434"
      openai:
        api_key: "" # optional, can define OPENAI_API_KEY instead
      anthropic:
        api_key: "" # optional, can define ANTHROPIC_API_KEY instead
      length_threshold: 100000
      model_id: "ibm/granite-3-3-8b-instruct" # note that this changes depending on provider
```

- `length_threshold` is the minimum number of characters before activating this component
- `jsonprocessor_query` is a natural language statement of what the long response should be processed for. For an example of a long response for a musical artist: "get full metadata for all albums from the artist's discography in json format"
