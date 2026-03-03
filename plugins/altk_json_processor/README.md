# ALTKJsonProcessor for ContextForge

> Author: Jason Tsay
> Version: 0.1.0

Uses JSON Processor from ALTK to extract data from long JSON responses. See the [ALTK](https://altk.ai/) and the [JSON Processor component in the ALTK repo](https://github.com/AgentToolkit/agent-lifecycle-toolkit/tree/main/altk/post_tool/code_generation) for more details on how the component works.

Note that this plugin will require calling an LLM and will therefore require configuring an LLM provider as described below. This plugin will also incure some cost in terms of time and money to do its LLM calls. This can be adjusted via the length threshold in the configuration, such that the plugin only activates and calls an LLM on JSON responses of a particular length (default: 100,000 characters).

## Hooks
- `tool_post_invoke` - Detects long JSON responses and processes as necessary

## Installation

1. Enable the "ALTKJsonProcessor" plugin in `plugins/config.yaml`.
2. Install the optional dependency `altk` (i.e. `pip install mcp-context-forge[altk]`)
3. Configure a LLM provider as described below.

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
      watsonx: # each section of providers is optional
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

### LLM Provider Configuration

In the configuration, select an LLM Provider via `llm_provider`, the current options are WatsonX, Ollama, OpenAI, or Anthropic.
Then fill out the corresponding provider section in the plugin config. For many of the api key-related fields, an environment variable
can also be used instead. If the field is set in both the plugin config and in an environment variable, the plugin config takes priority.

### JSON Processor Query

To guide the JSON Processor, an optional but recommended `jsonprocessor_query` can be provided that is a natural language statement of what the long response should be processed for.

Example queries:

- For an API endpoint such as [this Spotify artist overview](https://rapidapi.com/DataFanatic/api/spotify-scraper/playground/apiendpoint_fd33b4eb-d258-437e-af85-c244904acefc) that returns a large response, if you only want the discography of the artist, use a query such as: "get full metadata for all albums from the artist's discography in json format"
- For a shopping API endpoint that returns a [response like this](https://raw.githubusercontent.com/AgentToolkit/agent-lifecycle-toolkit/refs/heads/main/examples/codegen_long_response_example.json), if you only want the sizes of hte sneakers, use a query such as: "get the sizes for all products"

## Testing

Unit tests: `tests/unit/mcpgateway/plugins/plugins/altk_json_processor/test_json_processor.py`
