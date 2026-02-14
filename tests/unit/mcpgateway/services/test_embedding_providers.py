# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_embedding_providers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for embedding providers and factory in mcp_client_chat_service.
"""

import pytest
from unittest.mock import MagicMock, patch

import mcpgateway.services.mcp_client_chat_service as svc


# Patch LoggingService globally so logging doesn't pollute test outputs
@pytest.fixture(autouse=True)
def patch_logger(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(svc, "logger", mock)
    monkeypatch.setattr(svc.logging_service, "get_logger", lambda _: mock)
    return mock


# --------------------------------------------------------------------------- #
# EMBEDDING CONFIGURATION TESTS
# --------------------------------------------------------------------------- #


class TestOpenAIEmbeddingConfig:
    """Tests for OpenAIEmbeddingConfig class."""

    def test_default_values(self):
        """Test default configuration values."""
        config = svc.OpenAIEmbeddingConfig(api_key="sk-test-key")
        assert config.api_key == "sk-test-key"
        assert config.model == "text-embedding-3-small"
        assert config.dimensions is None
        assert config.base_url is None
        assert config.timeout is None
        assert config.max_retries == 2

    def test_custom_values(self):
        """Test custom configuration values."""
        config = svc.OpenAIEmbeddingConfig(
            api_key="sk-custom-key",
            model="text-embedding-3-large",
            dimensions=1024,
            base_url="https://custom.openai.com/v1",
            timeout=30.0,
            max_retries=5,
        )
        assert config.api_key == "sk-custom-key"
        assert config.model == "text-embedding-3-large"
        assert config.dimensions == 1024
        assert config.base_url == "https://custom.openai.com/v1"
        assert config.timeout == 30.0
        assert config.max_retries == 5

    def test_dimensions_must_be_positive(self):
        """Test that dimensions must be positive if provided."""
        with pytest.raises(ValueError):
            svc.OpenAIEmbeddingConfig(api_key="sk-test", dimensions=0)

    def test_timeout_must_be_positive(self):
        """Test that timeout must be positive if provided."""
        with pytest.raises(ValueError):
            svc.OpenAIEmbeddingConfig(api_key="sk-test", timeout=0)

    def test_max_retries_cannot_be_negative(self):
        """Test that max_retries cannot be negative."""
        with pytest.raises(ValueError):
            svc.OpenAIEmbeddingConfig(api_key="sk-test", max_retries=-1)


class TestOllamaEmbeddingConfig:
    """Tests for OllamaEmbeddingConfig class."""

    def test_default_values(self):
        """Test default configuration values."""
        config = svc.OllamaEmbeddingConfig()
        assert config.base_url == "http://localhost:11434"
        assert config.model == "nomic-embed-text"
        assert config.timeout is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = svc.OllamaEmbeddingConfig(
            base_url="http://remote-ollama:11434",
            model="mxbai-embed-large",
            timeout=30.0,
        )
        assert config.base_url == "http://remote-ollama:11434"
        assert config.model == "mxbai-embed-large"
        assert config.timeout == 30.0

    def test_timeout_must_be_positive(self):
        """Test that timeout must be positive if provided."""
        with pytest.raises(ValueError):
            svc.OllamaEmbeddingConfig(timeout=0)


class TestMistralEmbeddingConfig:
    """Tests for MistralEmbeddingConfig class."""

    def test_default_values(self):
        """Test default configuration values."""
        config = svc.MistralEmbeddingConfig(api_key="mistral-key")
        assert config.api_key == "mistral-key"
        assert config.model == "mistral-embed"
        assert config.timeout is None
        assert config.max_retries == 2

    def test_custom_values(self):
        """Test custom configuration values."""
        config = svc.MistralEmbeddingConfig(
            api_key="custom-key",
            model="mistral-embed-v2",
            timeout=45.0,
            max_retries=5,
        )
        assert config.api_key == "custom-key"
        assert config.model == "mistral-embed-v2"
        assert config.timeout == 45.0
        assert config.max_retries == 5

    def test_timeout_must_be_positive(self):
        """Test that timeout must be positive if provided."""
        with pytest.raises(ValueError):
            svc.MistralEmbeddingConfig(api_key="key", timeout=0)

    def test_max_retries_cannot_be_negative(self):
        """Test that max_retries cannot be negative."""
        with pytest.raises(ValueError):
            svc.MistralEmbeddingConfig(api_key="key", max_retries=-1)


class TestLiteLLMEmbeddingConfig:
    """Tests for LiteLLMEmbeddingConfig class."""

    def test_default_values(self):
        """Test default configuration values."""
        config = svc.LiteLLMEmbeddingConfig(base_url="http://localhost:4000")
        assert config.base_url == "http://localhost:4000"
        assert config.api_key is None
        assert config.model == "text-embedding-3-small"
        assert config.timeout is None
        assert config.max_retries == 2

    def test_custom_values(self):
        """Test custom configuration values."""
        config = svc.LiteLLMEmbeddingConfig(
            base_url="http://litellm-proxy:8000",
            api_key="proxy-key",
            model="text-embedding-3-large",
            timeout=60.0,
            max_retries=3,
        )
        assert config.base_url == "http://litellm-proxy:8000"
        assert config.api_key == "proxy-key"
        assert config.model == "text-embedding-3-large"
        assert config.timeout == 60.0
        assert config.max_retries == 3

    def test_base_url_is_required(self):
        """Test that base_url is required."""
        with pytest.raises(ValueError):
            svc.LiteLLMEmbeddingConfig()  # type: ignore

    def test_timeout_must_be_positive(self):
        """Test that timeout must be positive if provided."""
        with pytest.raises(ValueError):
            svc.LiteLLMEmbeddingConfig(base_url="http://localhost:4000", timeout=0)


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig class."""

    def test_openai_provider_with_config_object(self):
        """Test creating EmbeddingConfig with OpenAI provider using config object."""
        openai_config = svc.OpenAIEmbeddingConfig(
            api_key="sk-test",
            model="text-embedding-3-small",
        )
        config = svc.EmbeddingConfig(provider="openai", config=openai_config)
        assert config.provider == "openai"
        assert isinstance(config.config, svc.OpenAIEmbeddingConfig)
        assert config.config.api_key == "sk-test"

    def test_openai_provider_with_dict_config(self):
        """Test creating EmbeddingConfig with OpenAI provider using dict."""
        config = svc.EmbeddingConfig(
            provider="openai",
            config={
                "api_key": "sk-test",
                "model": "text-embedding-3-large",
                "dimensions": 512,
            },
        )
        assert config.provider == "openai"
        assert isinstance(config.config, svc.OpenAIEmbeddingConfig)
        assert config.config.api_key == "sk-test"
        assert config.config.model == "text-embedding-3-large"
        assert config.config.dimensions == 512

    def test_ollama_provider_with_config_object(self):
        """Test creating EmbeddingConfig with Ollama provider using config object."""
        ollama_config = svc.OllamaEmbeddingConfig(model="nomic-embed-text")
        config = svc.EmbeddingConfig(provider="ollama", config=ollama_config)
        assert config.provider == "ollama"
        assert isinstance(config.config, svc.OllamaEmbeddingConfig)
        assert config.config.model == "nomic-embed-text"

    def test_ollama_provider_with_dict_config(self):
        """Test creating EmbeddingConfig with Ollama provider using dict."""
        config = svc.EmbeddingConfig(
            provider="ollama",
            config={"model": "mxbai-embed-large", "base_url": "http://gpu-host:11434"},
        )
        assert config.provider == "ollama"
        assert isinstance(config.config, svc.OllamaEmbeddingConfig)
        assert config.config.model == "mxbai-embed-large"
        assert config.config.base_url == "http://gpu-host:11434"

    def test_mistral_provider_with_dict_config(self):
        """Test creating EmbeddingConfig with Mistral provider using dict."""
        config = svc.EmbeddingConfig(
            provider="mistral",
            config={"api_key": "mistral-key", "model": "mistral-embed"},
        )
        assert config.provider == "mistral"
        assert isinstance(config.config, svc.MistralEmbeddingConfig)
        assert config.config.api_key == "mistral-key"

    def test_litellm_provider_with_dict_config(self):
        """Test creating EmbeddingConfig with LiteLLM provider using dict."""
        config = svc.EmbeddingConfig(
            provider="litellm",
            config={"base_url": "http://localhost:4000", "model": "text-embedding-3-small"},
        )
        assert config.provider == "litellm"
        assert isinstance(config.config, svc.LiteLLMEmbeddingConfig)
        assert config.config.base_url == "http://localhost:4000"

    def test_invalid_provider_rejected(self):
        """Test that invalid provider type is rejected."""
        with pytest.raises(ValueError):
            svc.EmbeddingConfig(
                provider="invalid_provider",  # type: ignore
                config={"api_key": "test"},
            )


# --------------------------------------------------------------------------- #
# EMBEDDING PROVIDER TESTS
# --------------------------------------------------------------------------- #


class TestOpenAIEmbeddingProvider:
    """Tests for OpenAIEmbeddingProvider class."""

    def test_provider_initialization(self, monkeypatch):
        """Test provider initializes correctly."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        config = svc.OpenAIEmbeddingConfig(
            api_key="sk-test",
            model="text-embedding-3-small",
        )
        provider = svc.OpenAIEmbeddingProvider(config)

        assert provider.config == config
        assert provider._embedding_model is None
        assert provider.get_model_name() == "text-embedding-3-small"

    def test_provider_raises_import_error_when_not_available(self, monkeypatch):
        """Test provider raises ImportError when langchain-openai not installed."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", False)

        config = svc.OpenAIEmbeddingConfig(api_key="sk-test")

        with pytest.raises(ImportError) as exc_info:
            svc.OpenAIEmbeddingProvider(config)

        assert "langchain-openai" in str(exc_info.value)

    def test_get_embedding_model_creates_instance(self, monkeypatch):
        """Test get_embedding_model creates and caches OpenAIEmbeddings."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings = MagicMock()
        mock_embeddings_class = MagicMock(return_value=mock_embeddings)
        monkeypatch.setattr(svc, "OpenAIEmbeddings", mock_embeddings_class)

        config = svc.OpenAIEmbeddingConfig(
            api_key="sk-test",
            model="text-embedding-3-small",
        )
        provider = svc.OpenAIEmbeddingProvider(config)

        # First call should create instance
        result = provider.get_embedding_model()
        assert result == mock_embeddings
        mock_embeddings_class.assert_called_once()

        # Second call should return cached instance
        result2 = provider.get_embedding_model()
        assert result2 == mock_embeddings
        # Still only called once (cached)
        mock_embeddings_class.assert_called_once()

    def test_get_embedding_model_with_all_options(self, monkeypatch):
        """Test get_embedding_model passes all config options."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings_class = MagicMock()
        monkeypatch.setattr(svc, "OpenAIEmbeddings", mock_embeddings_class)

        config = svc.OpenAIEmbeddingConfig(
            api_key="sk-test",
            model="text-embedding-3-large",
            dimensions=1024,
            base_url="https://custom.api.com",
            timeout=60.0,
            max_retries=3,
        )
        provider = svc.OpenAIEmbeddingProvider(config)
        provider.get_embedding_model()

        mock_embeddings_class.assert_called_once_with(
            api_key="sk-test",
            model="text-embedding-3-large",
            max_retries=3,
            base_url="https://custom.api.com",
            dimensions=1024,
            timeout=60.0,
        )

    def test_get_embedding_model_handles_exception(self, monkeypatch):
        """Test get_embedding_model re-raises exceptions."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings_class = MagicMock(side_effect=Exception("API Error"))
        monkeypatch.setattr(svc, "OpenAIEmbeddings", mock_embeddings_class)

        config = svc.OpenAIEmbeddingConfig(api_key="sk-test")
        provider = svc.OpenAIEmbeddingProvider(config)

        with pytest.raises(Exception) as exc_info:
            provider.get_embedding_model()

        assert "API Error" in str(exc_info.value)


class TestOllamaEmbeddingProvider:
    """Tests for OllamaEmbeddingProvider class."""

    def test_provider_initialization(self, monkeypatch):
        """Test provider initializes correctly."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        config = svc.OllamaEmbeddingConfig(model="nomic-embed-text")
        provider = svc.OllamaEmbeddingProvider(config)

        assert provider.config == config
        assert provider._embedding_model is None
        assert provider.get_model_name() == "nomic-embed-text"

    def test_provider_raises_import_error_when_not_available(self, monkeypatch):
        """Test provider raises ImportError when langchain-ollama not installed."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", False)

        config = svc.OllamaEmbeddingConfig()

        with pytest.raises(ImportError) as exc_info:
            svc.OllamaEmbeddingProvider(config)

        assert "langchain-ollama" in str(exc_info.value)

    def test_get_embedding_model_creates_instance(self, monkeypatch):
        """Test get_embedding_model creates and caches OllamaEmbeddings."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings = MagicMock()
        mock_embeddings_class = MagicMock(return_value=mock_embeddings)
        monkeypatch.setattr(svc, "OllamaEmbeddings", mock_embeddings_class)

        config = svc.OllamaEmbeddingConfig(model="nomic-embed-text")
        provider = svc.OllamaEmbeddingProvider(config)

        result = provider.get_embedding_model()
        assert result == mock_embeddings
        mock_embeddings_class.assert_called_once_with(
            model="nomic-embed-text",
            base_url="http://localhost:11434",
        )

        # Second call returns cached
        result2 = provider.get_embedding_model()
        assert result2 == mock_embeddings
        mock_embeddings_class.assert_called_once()

    def test_get_embedding_model_with_timeout(self, monkeypatch):
        """Test get_embedding_model passes timeout when set."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings_class = MagicMock()
        monkeypatch.setattr(svc, "OllamaEmbeddings", mock_embeddings_class)

        config = svc.OllamaEmbeddingConfig(
            model="mxbai-embed-large",
            base_url="http://gpu-host:11434",
            timeout=30.0,
        )
        provider = svc.OllamaEmbeddingProvider(config)
        provider.get_embedding_model()

        mock_embeddings_class.assert_called_once_with(
            model="mxbai-embed-large",
            base_url="http://gpu-host:11434",
            timeout=30.0,
        )

    def test_get_embedding_model_handles_exception(self, monkeypatch):
        """Test get_embedding_model re-raises exceptions."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings_class = MagicMock(side_effect=Exception("Connection refused"))
        monkeypatch.setattr(svc, "OllamaEmbeddings", mock_embeddings_class)

        config = svc.OllamaEmbeddingConfig()
        provider = svc.OllamaEmbeddingProvider(config)

        with pytest.raises(Exception) as exc_info:
            provider.get_embedding_model()

        assert "Connection refused" in str(exc_info.value)


class TestMistralEmbeddingProvider:
    """Tests for MistralEmbeddingProvider class."""

    def test_provider_initialization(self, monkeypatch):
        """Test provider initializes correctly."""
        monkeypatch.setattr(svc, "_MISTRAL_AVAILABLE", True)

        config = svc.MistralEmbeddingConfig(api_key="mistral-key")
        provider = svc.MistralEmbeddingProvider(config)

        assert provider.config == config
        assert provider._embedding_model is None
        assert provider.get_model_name() == "mistral-embed"

    def test_provider_raises_import_error_when_not_available(self, monkeypatch):
        """Test provider raises ImportError when langchain-mistralai not installed."""
        monkeypatch.setattr(svc, "_MISTRAL_AVAILABLE", False)

        config = svc.MistralEmbeddingConfig(api_key="key")

        with pytest.raises(ImportError) as exc_info:
            svc.MistralEmbeddingProvider(config)

        assert "langchain-mistralai" in str(exc_info.value)

    def test_get_embedding_model_creates_instance(self, monkeypatch):
        """Test get_embedding_model creates and caches MistralAIEmbeddings."""
        monkeypatch.setattr(svc, "_MISTRAL_AVAILABLE", True)

        mock_embeddings = MagicMock()
        mock_embeddings_class = MagicMock(return_value=mock_embeddings)
        monkeypatch.setattr(svc, "MistralAIEmbeddings", mock_embeddings_class)

        config = svc.MistralEmbeddingConfig(api_key="mistral-key")
        provider = svc.MistralEmbeddingProvider(config)

        result = provider.get_embedding_model()
        assert result == mock_embeddings
        mock_embeddings_class.assert_called_once_with(
            model="mistral-embed",
            api_key="mistral-key",
            max_retries=2,
        )

        # Second call returns cached
        result2 = provider.get_embedding_model()
        assert result2 == mock_embeddings
        mock_embeddings_class.assert_called_once()

    def test_get_embedding_model_with_all_options(self, monkeypatch):
        """Test get_embedding_model passes all config options."""
        monkeypatch.setattr(svc, "_MISTRAL_AVAILABLE", True)

        mock_embeddings_class = MagicMock()
        monkeypatch.setattr(svc, "MistralAIEmbeddings", mock_embeddings_class)

        config = svc.MistralEmbeddingConfig(
            api_key="mistral-key",
            model="mistral-embed-v2",
            timeout=45.0,
            max_retries=5,
        )
        provider = svc.MistralEmbeddingProvider(config)
        provider.get_embedding_model()

        mock_embeddings_class.assert_called_once_with(
            model="mistral-embed-v2",
            api_key="mistral-key",
            timeout=45,
            max_retries=5,
        )

    def test_get_embedding_model_handles_exception(self, monkeypatch):
        """Test get_embedding_model re-raises exceptions."""
        monkeypatch.setattr(svc, "_MISTRAL_AVAILABLE", True)

        mock_embeddings_class = MagicMock(side_effect=Exception("Auth Error"))
        monkeypatch.setattr(svc, "MistralAIEmbeddings", mock_embeddings_class)

        config = svc.MistralEmbeddingConfig(api_key="bad-key")
        provider = svc.MistralEmbeddingProvider(config)

        with pytest.raises(Exception) as exc_info:
            provider.get_embedding_model()

        assert "Auth Error" in str(exc_info.value)


class TestLiteLLMEmbeddingProvider:
    """Tests for LiteLLMEmbeddingProvider class."""

    def test_provider_initialization(self, monkeypatch):
        """Test provider initializes correctly."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        config = svc.LiteLLMEmbeddingConfig(
            base_url="http://localhost:4000",
            model="text-embedding-3-small",
        )
        provider = svc.LiteLLMEmbeddingProvider(config)

        assert provider.config == config
        assert provider._embedding_model is None
        assert provider.get_model_name() == "text-embedding-3-small"

    def test_provider_raises_import_error_when_not_available(self, monkeypatch):
        """Test provider raises ImportError when langchain-openai not installed."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", False)

        config = svc.LiteLLMEmbeddingConfig(base_url="http://localhost:4000")

        with pytest.raises(ImportError) as exc_info:
            svc.LiteLLMEmbeddingProvider(config)

        assert "langchain-openai" in str(exc_info.value)

    def test_get_embedding_model_creates_instance_with_api_key(self, monkeypatch):
        """Test get_embedding_model passes api_key when provided."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings = MagicMock()
        mock_embeddings_class = MagicMock(return_value=mock_embeddings)
        monkeypatch.setattr(svc, "OpenAIEmbeddings", mock_embeddings_class)

        config = svc.LiteLLMEmbeddingConfig(
            base_url="http://localhost:4000",
            api_key="proxy-secret",
            model="text-embedding-3-large",
        )
        provider = svc.LiteLLMEmbeddingProvider(config)

        result = provider.get_embedding_model()
        assert result == mock_embeddings
        mock_embeddings_class.assert_called_once_with(
            model="text-embedding-3-large",
            base_url="http://localhost:4000",
            max_retries=2,
            api_key="proxy-secret",
        )

    def test_get_embedding_model_uses_placeholder_key_when_none(self, monkeypatch):
        """Test get_embedding_model uses placeholder api_key when none provided."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings_class = MagicMock()
        monkeypatch.setattr(svc, "OpenAIEmbeddings", mock_embeddings_class)

        config = svc.LiteLLMEmbeddingConfig(
            base_url="http://localhost:4000",
        )
        provider = svc.LiteLLMEmbeddingProvider(config)
        provider.get_embedding_model()

        call_kwargs = mock_embeddings_class.call_args[1]
        assert call_kwargs["api_key"] == "litellm-proxy"
        assert call_kwargs["base_url"] == "http://localhost:4000"

    def test_get_embedding_model_caches_instance(self, monkeypatch):
        """Test that get_embedding_model caches the instance."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings = MagicMock()
        mock_embeddings_class = MagicMock(return_value=mock_embeddings)
        monkeypatch.setattr(svc, "OpenAIEmbeddings", mock_embeddings_class)

        config = svc.LiteLLMEmbeddingConfig(base_url="http://localhost:4000")
        provider = svc.LiteLLMEmbeddingProvider(config)

        result1 = provider.get_embedding_model()
        result2 = provider.get_embedding_model()
        assert result1 is result2
        mock_embeddings_class.assert_called_once()

    def test_get_embedding_model_handles_exception(self, monkeypatch):
        """Test get_embedding_model re-raises exceptions."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings_class = MagicMock(side_effect=Exception("Proxy unreachable"))
        monkeypatch.setattr(svc, "OpenAIEmbeddings", mock_embeddings_class)

        config = svc.LiteLLMEmbeddingConfig(base_url="http://localhost:4000")
        provider = svc.LiteLLMEmbeddingProvider(config)

        with pytest.raises(Exception) as exc_info:
            provider.get_embedding_model()

        assert "Proxy unreachable" in str(exc_info.value)


# --------------------------------------------------------------------------- #
# EMBEDDING PROVIDER FACTORY TESTS
# --------------------------------------------------------------------------- #


class TestEmbeddingProviderFactory:
    """Tests for EmbeddingProviderFactory class."""

    def test_create_openai_provider(self, monkeypatch):
        """Test factory creates OpenAI embedding provider."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        config = svc.EmbeddingConfig(
            provider="openai",
            config=svc.OpenAIEmbeddingConfig(
                api_key="sk-test",
                model="text-embedding-3-small",
            ),
        )

        provider = svc.EmbeddingProviderFactory.create(config)

        assert isinstance(provider, svc.OpenAIEmbeddingProvider)
        assert provider.get_model_name() == "text-embedding-3-small"

    def test_create_ollama_provider(self, monkeypatch):
        """Test factory creates Ollama embedding provider."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        config = svc.EmbeddingConfig(
            provider="ollama",
            config=svc.OllamaEmbeddingConfig(model="nomic-embed-text"),
        )

        provider = svc.EmbeddingProviderFactory.create(config)

        assert isinstance(provider, svc.OllamaEmbeddingProvider)
        assert provider.get_model_name() == "nomic-embed-text"

    def test_create_mistral_provider(self, monkeypatch):
        """Test factory creates Mistral embedding provider."""
        monkeypatch.setattr(svc, "_MISTRAL_AVAILABLE", True)

        config = svc.EmbeddingConfig(
            provider="mistral",
            config=svc.MistralEmbeddingConfig(api_key="mistral-key"),
        )

        provider = svc.EmbeddingProviderFactory.create(config)

        assert isinstance(provider, svc.MistralEmbeddingProvider)
        assert provider.get_model_name() == "mistral-embed"

    def test_create_litellm_provider(self, monkeypatch):
        """Test factory creates LiteLLM embedding provider."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        config = svc.EmbeddingConfig(
            provider="litellm",
            config=svc.LiteLLMEmbeddingConfig(
                base_url="http://localhost:4000",
                model="text-embedding-3-small",
            ),
        )

        provider = svc.EmbeddingProviderFactory.create(config)

        assert isinstance(provider, svc.LiteLLMEmbeddingProvider)
        assert provider.get_model_name() == "text-embedding-3-small"

    def test_create_with_mock(self, monkeypatch):
        """Test factory creates provider using mock to verify call."""
        mock_provider_class = MagicMock()
        monkeypatch.setattr(svc, "OpenAIEmbeddingProvider", mock_provider_class)

        config = svc.EmbeddingConfig(
            provider="openai",
            config=svc.OpenAIEmbeddingConfig(api_key="sk-test"),
        )

        svc.EmbeddingProviderFactory.create(config)

        mock_provider_class.assert_called_once_with(config.config)

    def test_unsupported_provider_raises_error(self, monkeypatch):
        """Test factory raises ValueError for unsupported provider."""
        # Create a mock config with an unsupported provider
        mock_config = MagicMock()
        mock_config.provider = "unsupported_provider"

        with pytest.raises(ValueError) as exc_info:
            svc.EmbeddingProviderFactory.create(mock_config)

        assert "Unsupported embedding provider" in str(exc_info.value)
        assert "unsupported_provider" in str(exc_info.value)


# --------------------------------------------------------------------------- #
# INTEGRATION-STYLE TESTS (with mocks)
# --------------------------------------------------------------------------- #


class TestEmbeddingIntegration:
    """Integration-style tests for the embedding workflow."""

    def test_full_workflow_with_mocks(self, monkeypatch):
        """Test complete workflow: config -> factory -> provider -> model."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        # Mock the OpenAIEmbeddings class
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query = MagicMock(return_value=[0.1, 0.2, 0.3])
        mock_embeddings_class = MagicMock(return_value=mock_embeddings)
        monkeypatch.setattr(svc, "OpenAIEmbeddings", mock_embeddings_class)

        # Create config
        config = svc.EmbeddingConfig(
            provider="openai",
            config={
                "api_key": "sk-test-key",
                "model": "text-embedding-3-small",
            },
        )

        # Create provider via factory
        provider = svc.EmbeddingProviderFactory.create(config)
        assert isinstance(provider, svc.OpenAIEmbeddingProvider)

        # Get embedding model
        embedding_model = provider.get_embedding_model()
        assert embedding_model == mock_embeddings

        # Simulate using the model
        result = embedding_model.embed_query("test text")
        assert result == [0.1, 0.2, 0.3]
        mock_embeddings.embed_query.assert_called_once_with("test text")

    def test_ollama_workflow_with_mocks(self, monkeypatch):
        """Test Ollama workflow: config -> factory -> provider -> model."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings = MagicMock()
        mock_embeddings.embed_query = MagicMock(return_value=[0.4, 0.5, 0.6])
        monkeypatch.setattr(svc, "OllamaEmbeddings", MagicMock(return_value=mock_embeddings))

        config = svc.EmbeddingConfig(
            provider="ollama",
            config={"model": "nomic-embed-text"},
        )

        provider = svc.EmbeddingProviderFactory.create(config)
        assert isinstance(provider, svc.OllamaEmbeddingProvider)

        model = provider.get_embedding_model()
        result = model.embed_query("local test")
        assert result == [0.4, 0.5, 0.6]

    def test_litellm_workflow_with_mocks(self, monkeypatch):
        """Test LiteLLM proxy workflow: config -> factory -> provider -> model."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents = MagicMock(return_value=[[0.7, 0.8], [0.9, 1.0]])
        monkeypatch.setattr(svc, "OpenAIEmbeddings", MagicMock(return_value=mock_embeddings))

        config = svc.EmbeddingConfig(
            provider="litellm",
            config={
                "base_url": "http://localhost:4000",
                "model": "text-embedding-3-small",
            },
        )

        provider = svc.EmbeddingProviderFactory.create(config)
        assert isinstance(provider, svc.LiteLLMEmbeddingProvider)

        model = provider.get_embedding_model()
        result = model.embed_documents(["doc1", "doc2"])
        assert len(result) == 2

    def test_config_from_dict_to_embeddings(self, monkeypatch):
        """Test creating embeddings from dictionary config."""
        monkeypatch.setattr(svc, "_LLMCHAT_AVAILABLE", True)

        mock_embeddings = MagicMock()
        monkeypatch.setattr(svc, "OpenAIEmbeddings", MagicMock(return_value=mock_embeddings))

        # Simulating how a user might pass config from JSON/YAML
        raw_config = {
            "provider": "openai",
            "config": {
                "api_key": "sk-from-env",
                "model": "text-embedding-3-large",
                "dimensions": 256,
            },
        }

        # Parse with Pydantic
        config = svc.EmbeddingConfig(**raw_config)

        # Create provider and get model
        provider = svc.EmbeddingProviderFactory.create(config)
        model = provider.get_embedding_model()

        assert model == mock_embeddings
        assert provider.get_model_name() == "text-embedding-3-large"
