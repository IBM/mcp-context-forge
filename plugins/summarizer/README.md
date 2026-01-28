# Summarizer Plugin

Summarizes long text content using an LLM (OpenAI supported). Applies to resource content and tool outputs when they exceed a configurable length threshold.

Hooks
- resource_post_fetch
- tool_post_invoke

Configuration (example)
```yaml
- name: "Summarizer"
  kind: "plugins.summarizer.summarizer.SummarizerPlugin"
  hooks: ["resource_post_fetch", "tool_post_invoke"]
  mode: "permissive"
  priority: 170
  config:
    provider: "openai"
    openai:
      api_base: "https://api.openai.com/v1"
      api_key_env: "OPENAI_API_KEY"
      model: "gpt-4o-mini"
      temperature: 0.2
      max_tokens: 512
      use_responses_api: true    # default: use the Responses API
    anthropic:
      api_base: "https://api.anthropic.com/v1"
      api_key_env: "ANTHROPIC_API_KEY"
      model: "claude-3-5-sonnet-latest"
      max_tokens: 512
      temperature: 0.2
    prompt_template: |
      You are a helpful assistant. Summarize the following content succinctly
      in no more than {max_tokens} tokens. Focus on key points, remove
      redundancy, and preserve critical details.
    include_bullets: true
    language: "en"          # null to let the model pick
    threshold_chars: 800    # only summarize when input >= this length
    hard_truncate_chars: 24000
    tool_allowlist: ["search", "retrieve"]           # optional: restrict by tool
    resource_uri_prefixes: ["http://", "https://"]    # default: restrict to web URIs
```

Environment
- Set the OpenAI API key via `OPENAI_API_KEY` (or change `api_key_env`).
 - For Anthropic, set `ANTHROPIC_API_KEY`.

Providers
- OpenAI (default): Uses the Responses API by default (`use_responses_api: true`). To switch back to Chat Completions, set it to `false`.
- Anthropic: Set `provider: "anthropic"` and ensure `ANTHROPIC_API_KEY` is configured. Adjust `anthropic.model`, `max_tokens`, and `temperature` as needed.

Notes
- Input is truncated to `hard_truncate_chars` before sending to the LLM to constrain cost.
- Summaries replace the text field (for `ResourceContent.text` and plain string tool results).

Notes
- The plugin truncates input to `hard_truncate_chars` before calling the LLM.
- Summaries replace the text field (for `ResourceContent.text` and plain string tool results).
