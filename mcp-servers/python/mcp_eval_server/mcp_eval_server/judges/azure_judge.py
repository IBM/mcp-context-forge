# -*- coding: utf-8 -*-
"""Azure OpenAI judge implementation for LLM-as-a-judge evaluation."""

# Standard
import os
from typing import Any, Dict

# Third-Party
from openai import AsyncAzureOpenAI

# Local
from .openai_judge import OpenAIJudge


class AzureOpenAIJudge(OpenAIJudge):
    """Judge implementation using Azure OpenAI Service."""

    def __init__(self, config: Dict[str, Any]) -> None:  # pylint: disable=super-init-not-called
        """Initialize Azure OpenAI judge.

        Args:
            config: Configuration dictionary with Azure OpenAI settings

        Raises:
            ValueError: If API key or API base are not found in environment variables
        """
        # Initialize configuration manually (avoid inheritance chain issues)
        self.config = config
        self.model_name = config.get("model_name", "unknown")
        self.temperature = config.get("default_temperature", 0.3)
        self.max_tokens = config.get("max_tokens", 2000)

        # Azure-specific client setup
        api_key = os.getenv(config["api_key_env"])
        if not api_key:
            raise ValueError(f"API key not found in environment variable: {config['api_key_env']}")

        api_base = os.getenv(config["api_base_env"])
        if not api_base:
            raise ValueError(f"API base not found in environment variable: {config['api_base_env']}")

        self.client = AsyncAzureOpenAI(azure_endpoint=api_base, api_key=api_key, api_version=config.get("api_version", "2024-02-01"))

        # Use deployment name instead of model name for Azure
        self.model = config.get("deployment_name", config["model_name"])
