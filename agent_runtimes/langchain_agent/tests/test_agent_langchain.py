# -*- coding: utf-8 -*-
"""Tests for agent_langchain module."""

# Standard
from unittest.mock import Mock, patch

# Third-Party
import pytest

# First-Party
from agent_runtimes.langchain_agent.agent_langchain import (
    _create_anthropic_llm,
    _create_azure_llm,
    _create_bedrock_llm,
    _create_ollama_llm,
    _create_openai_llm,
    create_llm,
)
from agent_runtimes.langchain_agent.models import AgentConfig


class TestCreateLLM:
    """Tests for create_llm factory function."""

    def test_unsupported_provider_raises_error(self):
        """Test that unsupported provider raises ValueError."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "unsupported"

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            create_llm(config)

    def test_provider_case_insensitive(self):
        """Test that provider name is case-insensitive."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "OPENAI"
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None
        config.openai_base_url = None
        config.openai_organization = None

        with patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI") as mock_chat_openai:
            result = create_llm(config)
            mock_chat_openai.assert_called_once()
            assert result == mock_chat_openai.return_value

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_create_openai_llm(self, mock_chat_openai):
        """Test OpenAI LLM creation through factory."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "openai"
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None
        config.openai_base_url = None
        config.openai_organization = None

        result = create_llm(config)

        mock_chat_openai.assert_called_once()
        assert result == mock_chat_openai.return_value

    @patch("agent_runtimes.langchain_agent.agent_langchain.AzureChatOpenAI")
    def test_create_azure_llm(self, mock_azure_openai):
        """Test Azure OpenAI LLM creation through factory."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "azure"
        config.azure_openai_api_key = "azure-key"
        config.azure_openai_endpoint = "https://example.openai.azure.com/"
        config.azure_openai_api_version = "2024-02-15-preview"
        config.azure_deployment_name = "gpt-4"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None

        result = create_llm(config)

        mock_azure_openai.assert_called_once()
        assert result == mock_azure_openai.return_value

    @patch("agent_runtimes.langchain_agent.agent_langchain.BedrockChat", None)
    def test_create_bedrock_llm_missing_dependency(self):
        """Test Bedrock LLM raises ImportError when dependency missing."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "bedrock"
        config.aws_access_key_id = "test-key"
        config.aws_secret_access_key = "test-secret"
        config.bedrock_model_id = "anthropic.claude-v2"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None

        with pytest.raises(ImportError, match="langchain-aws"):
            create_llm(config)

    @patch("agent_runtimes.langchain_agent.agent_langchain.BedrockChat")
    def test_create_bedrock_llm(self, mock_bedrock_chat):
        """Test Bedrock LLM creation through factory."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "bedrock"
        config.aws_access_key_id = "test-key"
        config.aws_secret_access_key = "test-secret"
        config.bedrock_model_id = "anthropic.claude-v2"
        config.aws_region = "us-east-1"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None

        result = create_llm(config)

        mock_bedrock_chat.assert_called_once()
        assert result == mock_bedrock_chat.return_value

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOllama", None)
    def test_create_ollama_llm_missing_dependency(self):
        """Test Ollama LLM raises ImportError when dependency missing."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "ollama"
        config.ollama_model = "llama2"
        config.ollama_base_url = "http://localhost:11434"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None

        with pytest.raises(ImportError, match="langchain-community"):
            create_llm(config)

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOllama")
    def test_create_ollama_llm(self, mock_ollama):
        """Test Ollama LLM creation through factory."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "ollama"
        config.ollama_model = "llama2"
        config.ollama_base_url = "http://localhost:11434"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None

        result = create_llm(config)

        mock_ollama.assert_called_once()
        assert result == mock_ollama.return_value

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatAnthropic", None)
    def test_create_anthropic_llm_missing_dependency(self):
        """Test Anthropic LLM raises ImportError when dependency missing."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "anthropic"
        config.anthropic_api_key = "test-key"
        config.default_model = "claude-3-sonnet"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None

        with pytest.raises(ImportError, match="langchain-anthropic"):
            create_llm(config)

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatAnthropic")
    def test_create_anthropic_llm(self, mock_anthropic):
        """Test Anthropic LLM creation through factory."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "anthropic"
        config.anthropic_api_key = "test-key"
        config.default_model = "claude-3-sonnet"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None

        result = create_llm(config)

        mock_anthropic.assert_called_once()
        assert result == mock_anthropic.return_value


class TestCreateOpenAILLM:
    """Tests for _create_openai_llm helper."""

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_requires_api_key(self, mock_chat_openai):
        """Test that OpenAI requires API key."""
        config = Mock(spec=AgentConfig)
        config.openai_api_key = None

        with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
            _create_openai_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_creates_with_minimal_config(self, mock_chat_openai):
        """Test OpenAI LLM creation with minimal config."""
        config = Mock(spec=AgentConfig)
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.openai_base_url = None
        config.openai_organization = None

        common_args = {"temperature": 0.7, "streaming": True}

        _create_openai_llm(config, common_args)

        mock_chat_openai.assert_called_once_with(
            model="gpt-4",
            api_key="test-key",
            temperature=0.7,
            streaming=True,
        )

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_creates_with_optional_base_url(self, mock_chat_openai):
        """Test OpenAI LLM creation with optional base_url."""
        config = Mock(spec=AgentConfig)
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.openai_base_url = "https://custom.openai.com/v1"
        config.openai_organization = None

        common_args = {"temperature": 0.7}

        _create_openai_llm(config, common_args)

        mock_chat_openai.assert_called_once()
        call_kwargs = mock_chat_openai.call_args[1]
        assert call_kwargs["base_url"] == "https://custom.openai.com/v1"

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_creates_with_optional_organization(self, mock_chat_openai):
        """Test OpenAI LLM creation with optional organization."""
        config = Mock(spec=AgentConfig)
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.openai_base_url = None
        config.openai_organization = "my-org"

        common_args = {"temperature": 0.7}

        _create_openai_llm(config, common_args)

        mock_chat_openai.assert_called_once()
        call_kwargs = mock_chat_openai.call_args[1]
        assert call_kwargs["organization"] == "my-org"

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_creates_with_all_optional_fields(self, mock_chat_openai):
        """Test OpenAI LLM creation with all optional fields."""
        config = Mock(spec=AgentConfig)
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.openai_base_url = "https://custom.openai.com/v1"
        config.openai_organization = "my-org"

        common_args = {"temperature": 0.7, "max_tokens": 1000, "streaming": True}

        _create_openai_llm(config, common_args)

        mock_chat_openai.assert_called_once()
        call_kwargs = mock_chat_openai.call_args[1]
        assert call_kwargs["base_url"] == "https://custom.openai.com/v1"
        assert call_kwargs["organization"] == "my-org"
        assert call_kwargs["max_tokens"] == 1000


class TestCreateAzureLLM:
    """Tests for _create_azure_llm helper."""

    @patch("agent_runtimes.langchain_agent.agent_langchain.AzureChatOpenAI")
    def test_requires_all_credentials(self, mock_azure):
        """Test that Azure requires all credentials."""
        config = Mock(spec=AgentConfig)
        config.azure_openai_api_key = None
        config.azure_openai_endpoint = "https://example.openai.azure.com/"
        config.azure_deployment_name = "gpt-4"

        with pytest.raises(ValueError, match="Azure OpenAI requires"):
            _create_azure_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.AzureChatOpenAI")
    def test_requires_endpoint(self, mock_azure):
        """Test that Azure requires endpoint."""
        config = Mock(spec=AgentConfig)
        config.azure_openai_api_key = "key"
        config.azure_openai_endpoint = None
        config.azure_deployment_name = "gpt-4"

        with pytest.raises(ValueError, match="Azure OpenAI requires"):
            _create_azure_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.AzureChatOpenAI")
    def test_requires_deployment_name(self, mock_azure):
        """Test that Azure requires deployment name."""
        config = Mock(spec=AgentConfig)
        config.azure_openai_api_key = "key"
        config.azure_openai_endpoint = "https://example.openai.azure.com/"
        config.azure_deployment_name = None

        with pytest.raises(ValueError, match="Azure OpenAI requires"):
            _create_azure_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.AzureChatOpenAI")
    def test_creates_with_all_credentials(self, mock_azure):
        """Test Azure LLM creation with all credentials."""
        config = Mock(spec=AgentConfig)
        config.azure_openai_api_key = "azure-key"
        config.azure_openai_endpoint = "https://example.openai.azure.com/"
        config.azure_openai_api_version = "2024-02-15-preview"
        config.azure_deployment_name = "gpt-4"

        common_args = {"temperature": 0.7, "streaming": True}

        _create_azure_llm(config, common_args)

        mock_azure.assert_called_once_with(
            api_key="azure-key",
            azure_endpoint="https://example.openai.azure.com/",
            api_version="2024-02-15-preview",
            azure_deployment="gpt-4",
            temperature=0.7,
            streaming=True,
        )


class TestCreateBedrockLLM:
    """Tests for _create_bedrock_llm helper."""

    def test_requires_bedrock_dependency(self):
        """Test that Bedrock requires langchain-aws."""
        with patch("agent_runtimes.langchain_agent.agent_langchain.BedrockChat", None):
            config = Mock(spec=AgentConfig)
            config.aws_access_key_id = "key"
            config.aws_secret_access_key = "secret"
            config.bedrock_model_id = "anthropic.claude-v2"

            with pytest.raises(ImportError, match="langchain-aws"):
                _create_bedrock_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.BedrockChat")
    def test_requires_access_key(self, mock_bedrock):
        """Test that Bedrock requires AWS access key."""
        config = Mock(spec=AgentConfig)
        config.aws_access_key_id = None
        config.aws_secret_access_key = "secret"
        config.bedrock_model_id = "anthropic.claude-v2"

        with pytest.raises(ValueError, match="AWS Bedrock requires"):
            _create_bedrock_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.BedrockChat")
    def test_requires_secret_key(self, mock_bedrock):
        """Test that Bedrock requires AWS secret key."""
        config = Mock(spec=AgentConfig)
        config.aws_access_key_id = "key"
        config.aws_secret_access_key = None
        config.bedrock_model_id = "anthropic.claude-v2"

        with pytest.raises(ValueError, match="AWS Bedrock requires"):
            _create_bedrock_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.BedrockChat")
    def test_requires_model_id(self, mock_bedrock):
        """Test that Bedrock requires model ID."""
        config = Mock(spec=AgentConfig)
        config.aws_access_key_id = "key"
        config.aws_secret_access_key = "secret"
        config.bedrock_model_id = None

        with pytest.raises(ValueError, match="AWS Bedrock requires"):
            _create_bedrock_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.BedrockChat")
    def test_creates_with_all_credentials(self, mock_bedrock):
        """Test Bedrock LLM creation with all credentials."""
        config = Mock(spec=AgentConfig)
        config.aws_access_key_id = "key"
        config.aws_secret_access_key = "secret"
        config.bedrock_model_id = "anthropic.claude-v2"
        config.aws_region = "us-west-2"

        common_args = {"temperature": 0.7, "streaming": True}

        _create_bedrock_llm(config, common_args)

        mock_bedrock.assert_called_once_with(
            model_id="anthropic.claude-v2",
            region_name="us-west-2",
            credentials_profile_name=None,
            temperature=0.7,
            streaming=True,
        )


class TestCreateOllamaLLM:
    """Tests for _create_ollama_llm helper."""

    def test_requires_ollama_dependency(self):
        """Test that Ollama requires langchain-community."""
        with patch("agent_runtimes.langchain_agent.agent_langchain.ChatOllama", None):
            config = Mock(spec=AgentConfig)
            config.ollama_model = "llama2"
            config.ollama_base_url = "http://localhost:11434"

            with pytest.raises(ImportError, match="langchain-community"):
                _create_ollama_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOllama")
    def test_requires_model(self, mock_ollama):
        """Test that Ollama requires model."""
        config = Mock(spec=AgentConfig)
        config.ollama_model = None
        config.ollama_base_url = "http://localhost:11434"

        with pytest.raises(ValueError, match="OLLAMA_MODEL is required"):
            _create_ollama_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOllama")
    def test_creates_with_model_and_base_url(self, mock_ollama):
        """Test Ollama LLM creation with model and base URL."""
        config = Mock(spec=AgentConfig)
        config.ollama_model = "llama2"
        config.ollama_base_url = "http://localhost:11434"

        common_args = {"temperature": 0.7, "streaming": True}

        _create_ollama_llm(config, common_args)

        mock_ollama.assert_called_once_with(
            model="llama2",
            base_url="http://localhost:11434",
            temperature=0.7,
            streaming=True,
        )


class TestCreateAnthropicLLM:
    """Tests for _create_anthropic_llm helper."""

    def test_requires_anthropic_dependency(self):
        """Test that Anthropic requires langchain-anthropic."""
        with patch("agent_runtimes.langchain_agent.agent_langchain.ChatAnthropic", None):
            config = Mock(spec=AgentConfig)
            config.anthropic_api_key = "key"
            config.default_model = "claude-3-sonnet"

            with pytest.raises(ImportError, match="langchain-anthropic"):
                _create_anthropic_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatAnthropic")
    def test_requires_api_key(self, mock_anthropic):
        """Test that Anthropic requires API key."""
        config = Mock(spec=AgentConfig)
        config.anthropic_api_key = None
        config.default_model = "claude-3-sonnet"

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is required"):
            _create_anthropic_llm(config, {})

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatAnthropic")
    def test_creates_with_api_key_and_model(self, mock_anthropic):
        """Test Anthropic LLM creation with API key and model."""
        config = Mock(spec=AgentConfig)
        config.anthropic_api_key = "test-key"
        config.default_model = "claude-3-sonnet"

        common_args = {"temperature": 0.7, "streaming": True, "max_tokens": 2000}

        _create_anthropic_llm(config, common_args)

        mock_anthropic.assert_called_once_with(
            model="claude-3-sonnet",
            api_key="test-key",
            temperature=0.7,
            streaming=True,
            max_tokens=2000,
        )


class TestCommonArgs:
    """Tests for common_args construction in create_llm."""

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_common_args_include_temperature_and_streaming(self, mock_openai):
        """Test that common_args includes temperature and streaming."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "openai"
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.temperature = 0.5
        config.streaming_enabled = False
        config.max_tokens = None
        config.top_p = None
        config.openai_base_url = None
        config.openai_organization = None

        create_llm(config)

        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["streaming"] is False

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_common_args_include_max_tokens_when_set(self, mock_openai):
        """Test that common_args includes max_tokens when set."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "openai"
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = 2000
        config.top_p = None
        config.openai_base_url = None
        config.openai_organization = None

        create_llm(config)

        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs["max_tokens"] == 2000

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_common_args_exclude_max_tokens_when_none(self, mock_openai):
        """Test that common_args excludes max_tokens when None."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "openai"
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = None
        config.openai_base_url = None
        config.openai_organization = None

        create_llm(config)

        call_kwargs = mock_openai.call_args[1]
        assert "max_tokens" not in call_kwargs

    @patch("agent_runtimes.langchain_agent.agent_langchain.ChatOpenAI")
    def test_common_args_include_top_p_when_set(self, mock_openai):
        """Test that common_args includes top_p when set."""
        config = Mock(spec=AgentConfig)
        config.llm_provider = "openai"
        config.openai_api_key = "test-key"
        config.default_model = "gpt-4"
        config.temperature = 0.7
        config.streaming_enabled = True
        config.max_tokens = None
        config.top_p = 0.9
        config.openai_base_url = None
        config.openai_organization = None

        create_llm(config)

        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs["top_p"] == 0.9
