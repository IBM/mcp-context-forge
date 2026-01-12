# -*- coding: utf-8 -*-
"""Location: ./plugins/summarizer/summarizer.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Summarizer Plugin.

Summarizes long text content using configurable LLM providers (OpenAI initially).

Hooks: resource_post_fetch, tool_post_invoke
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, Optional

# Third-Party
import orjson
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)
from mcpgateway.utils.retry_manager import ResilientHttpClient


class OpenAIConfig(BaseModel):
    """Configuration for OpenAI summarization provider.

    Attributes:
        api_base: Base URL for OpenAI API.
        api_key_env: Environment variable containing API key.
        model: OpenAI model to use.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in summary.
        use_responses_api: Whether to use Responses API format.
    """

    api_base: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_tokens: int = 512
    use_responses_api: bool = False


class AnthropicConfig(BaseModel):
    """Configuration for Anthropic summarization provider.

    Attributes:
        api_base: Base URL for Anthropic API.
        api_key_env: Environment variable containing API key.
        model: Anthropic model to use.
        max_tokens: Maximum tokens in summary.
        temperature: Sampling temperature.
    """

    api_base: str = "https://api.anthropic.com/v1"
    api_key_env: str = "ANTHROPIC_API_KEY"
    model: str = "claude-3-5-sonnet-latest"
    max_tokens: int = 512
    temperature: float = 0.2


class SummarizerConfig(BaseModel):
    """Configuration for summarizer plugin.

    Attributes:
        provider: LLM provider to use (openai or anthropic).
        openai: OpenAI-specific configuration.
        anthropic: Anthropic-specific configuration.
        prompt_template: Template for summarization prompt.
        include_bullets: Whether to request bullet points in summary.
        language: Target language for summary (None for autodetect).
        threshold_chars: Minimum content length to trigger summarization.
        hard_truncate_chars: Maximum input characters before truncation.
        tool_allowlist: Optional list of tools to apply summarization to.
        resource_uri_prefixes: Optional URI prefixes to filter resources.
    """

    provider: str = "openai"  # openai | anthropic
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    prompt_template: str = (
        "You are a helpful assistant. Summarize the following content succinctly in no more than {max_tokens} tokens. Focus on key points, remove redundancy, and preserve critical details."
    )
    include_bullets: bool = True
    language: Optional[str] = None  # e.g., "en", "de"; None = autodetect by model
    threshold_chars: int = 800  # Only summarize when content length >= threshold
    hard_truncate_chars: int = 24000  # Truncate input text to this size before sending to LLM
    # Optional gating
    tool_allowlist: Optional[list[str]] = None
    resource_uri_prefixes: Optional[list[str]] = None


async def _summarize_openai(cfg: OpenAIConfig, system_prompt: str, user_text: str) -> str:
    """Summarize text using OpenAI API.

    Args:
        cfg: OpenAI configuration.
        system_prompt: System prompt for the model.
        user_text: Text to summarize.

    Returns:
        Summarized text.

    Raises:
        RuntimeError: If API key is missing or response parsing fails.
    """
    # Standard
    import os

    api_key = os.getenv(cfg.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing OpenAI API key in env var {cfg.api_key_env}")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if cfg.use_responses_api:
        url = f"{cfg.api_base}/responses"
        body = {
            "model": cfg.model,
            "temperature": cfg.temperature,
            "max_output_tokens": cfg.max_tokens,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        }
    else:
        url = f"{cfg.api_base}/chat/completions"
        body = {
            "model": cfg.model,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        }
    async with ResilientHttpClient(client_args={"headers": headers, "timeout": 30.0}) as client:
        resp = await client.post(url, json=body)
        data = resp.json()
    try:
        if cfg.use_responses_api:
            # Responses API
            return data["output"][0]["content"][0]["text"]
        else:
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        raise RuntimeError(f"OpenAI response parse error: {e}; raw: {orjson.dumps(data).decode()[:500]}")


async def _summarize_anthropic(cfg: AnthropicConfig, system_prompt: str, user_text: str) -> str:
    """Summarize text using Anthropic API.

    Args:
        cfg: Anthropic configuration.
        system_prompt: System prompt for the model.
        user_text: Text to summarize.

    Returns:
        Summarized text.

    Raises:
        RuntimeError: If API key is missing or response parsing fails.
    """
    # Standard
    import os

    api_key = os.getenv(cfg.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing Anthropic API key in env var {cfg.api_key_env}")
    url = f"{cfg.api_base}/messages"
    headers = {
        "x-api-key": api_key,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    body = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_text}],
    }
    async with ResilientHttpClient(client_args={"headers": headers, "timeout": 30.0}) as client:
        resp = await client.post(url, json=body)
        data = resp.json()
    try:
        # content is a list of blocks; take concatenated text
        blocks = data.get("content", [])
        texts = []
        for b in blocks:
            if b.get("type") == "text" and "text" in b:
                texts.append(b["text"])
        return "\n".join(texts) if texts else ""
    except Exception as e:
        raise RuntimeError(f"Anthropic response parse error: {e}; raw: {orjson.dumps(data).decode()[:500]}")


def _build_prompt(base: SummarizerConfig, text: str) -> tuple[str, str]:
    """Build system and user prompts for summarization.

    Args:
        base: Summarizer configuration.
        text: Text to summarize.

    Returns:
        Tuple of (system_prompt, user_text).
    """
    bullets = "Provide a bullet list when helpful." if base.include_bullets else ""
    lang = f"Write in {base.language}." if base.language else ""
    sys = base.prompt_template.format(max_tokens=base.openai.max_tokens)
    system_prompt = f"{sys}\n{bullets} {lang}".strip()
    user_text = text
    return system_prompt, user_text


async def _summarize_text(cfg: SummarizerConfig, text: str) -> str:
    """Summarize text using the configured provider.

    Args:
        cfg: Summarizer configuration.
        text: Text to summarize.

    Returns:
        Summarized text.

    Raises:
        RuntimeError: If provider is unsupported or API call fails.
    """
    system_prompt, user_text = _build_prompt(cfg, text)
    if cfg.provider == "openai":
        return await _summarize_openai(cfg.openai, system_prompt, user_text)
    if cfg.provider == "anthropic":
        return await _summarize_anthropic(cfg.anthropic, system_prompt, user_text)
    raise RuntimeError(f"Unsupported provider: {cfg.provider}")


def _maybe_get_text_from_result(result: Any) -> Optional[str]:
    """Extract text from a tool result if it's a string.

    Args:
        result: Tool invocation result.

    Returns:
        Text content if result is a string, None otherwise.
    """
    # Only support plain string outputs by default.
    return result if isinstance(result, str) else None


class SummarizerPlugin(Plugin):
    """Plugin to summarize long text content using LLM providers."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the summarizer plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = SummarizerConfig(**(config.config or {}))

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Summarize resource text content if it exceeds threshold.

        Args:
            payload: Resource fetch result payload.
            context: Plugin execution context.

        Returns:
            Result with summarized content or original if below threshold.
        """
        content = payload.content
        if not hasattr(content, "text") or not isinstance(content.text, str) or not content.text:
            return ResourcePostFetchResult(continue_processing=True)
        # Optional gating by URI prefix
        uri_prefixes = self._cfg.resource_uri_prefixes
        if uri_prefixes is not None:
            uri = payload.uri or ""
            if not any(uri.startswith(p) for p in uri_prefixes):
                return ResourcePostFetchResult(continue_processing=True)
        text = content.text
        if len(text) < self._cfg.threshold_chars:
            return ResourcePostFetchResult(continue_processing=True)
        text = text[: self._cfg.hard_truncate_chars]
        try:
            summary = await _summarize_text(self._cfg, text)
        except Exception as e:
            return ResourcePostFetchResult(metadata={"summarize_error": str(e)})
        new_text = summary
        new_payload = ResourcePostFetchPayload(uri=payload.uri, content=type(content)(**{**content.model_dump(), "text": new_text}))
        return ResourcePostFetchResult(modified_payload=new_payload, metadata={"summarized": True})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Summarize tool result text if it exceeds threshold.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with summarized content or original if below threshold.
        """
        # Optional gating by tool name
        if self._cfg.tool_allowlist and payload.name not in set(self._cfg.tool_allowlist):
            return ToolPostInvokeResult(continue_processing=True)
        text = _maybe_get_text_from_result(payload.result)
        if not text or len(text) < self._cfg.threshold_chars:
            return ToolPostInvokeResult(continue_processing=True)
        text = text[: self._cfg.hard_truncate_chars]
        try:
            summary = await _summarize_text(self._cfg, text)
        except Exception as e:
            return ToolPostInvokeResult(metadata={"summarize_error": str(e)})
        return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=summary), metadata={"summarized": True})
