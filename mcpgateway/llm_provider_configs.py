# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/llm_provider_configs.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

LLM Provider-Specific Configuration Definitions.

This module contains Pydantic models that define configuration parameters
required for different LLM providers. Each provider
has its own configuration schema to capture authentication details,
regional settings, deployment identifiers, and provider-specific options.

These configuration objects are intended to be used by the MCP Gateway
to initialize and manage provider clients in a consistent and type-safe
manner.
"""

# Standard
from typing import Any, Dict, List, Optional

# Third-Party
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Provider-Specific Configuration Models
# ---------------------------------------------------------------------------


class AWSBedrockConfig(BaseModel):
    """AWS Bedrock-specific configuration.

    Attributes:
        region: AWS region where Bedrock is hosted (e.g., "us-east-1").
        access_key_id: AWS access key ID. Optional if using IAM roles.
        secret_access_key: AWS secret access key. Optional if using IAM roles.
        session_token: AWS session token for temporary credentials.
        profile_name: AWS profile name from ~/.aws/credentials.

    """

    region: str = Field(..., description="AWS region (e.g., us-east-1)")
    access_key_id: Optional[str] = Field(None, description="AWS access key ID (optional if using IAM role)")
    secret_access_key: Optional[str] = Field(None, description="AWS secret access key (optional if using IAM role)")
    session_token: Optional[str] = Field(None, description="AWS session token for temporary credentials")
    profile_name: Optional[str] = Field(None, description="AWS profile name from ~/.aws/credentials")


class IBMWatsonXConfig(BaseModel):
    """IBM Watson X AI-specific configuration.

    Attributes:
        project_id: Watson X project ID.
        space_id: Watson X deployment space ID.
        deployment_id: Deployment ID for a specific model deployment.
        instance_id: Watson X service instance ID.
        version: Watson X API version string.
        url: Watson X service URL, overriding the default API base.
    """

    project_id: Optional[str] = Field(None, description="Watson X project ID")
    space_id: Optional[str] = Field(None, description="Watson X deployment space ID")
    deployment_id: Optional[str] = Field(None, description="Deployment ID for specific model deployment")
    instance_id: Optional[str] = Field(None, description="Watson X instance ID")
    version: str = Field(default="2023-05-29", description="Watson X API version")
    url: Optional[str] = Field(None, description="Watson X service URL (overrides api_base)")


class AzureOpenAIConfig(BaseModel):
    """Azure OpenAI-specific configuration.

    Attributes:
        deployment_name: Azure OpenAI deployment name.
        resource_name: Azure OpenAI resource name.
        api_version: Azure OpenAI API version.
    """

    deployment_name: str = Field(..., description="Azure OpenAI deployment name")
    resource_name: str = Field(..., description="Azure resource name")
    api_version: str = Field(default="2024-02-15-preview", description="Azure OpenAI API version")


class GoogleVertexAIConfig(BaseModel):
    """Google Vertex AI-specific configuration.

    Attributes:
        project_id: Google Cloud project ID.
        location: Google Cloud region or location.
        credentials_path: Path to a service account JSON credentials file.
        credentials_json: Service account credentials as a JSON string.
    """

    project_id: str = Field(..., description="Google Cloud project ID")
    location: str = Field(default="us-central1", description="Google Cloud region/location")
    credentials_path: Optional[str] = Field(None, description="Path to service account JSON file")
    credentials_json: Optional[str] = Field(None, description="Service account JSON as string")


class AnthropicConfig(BaseModel):
    """Anthropic-specific configuration.

    Attributes:
        anthropic_version: Anthropic API version identifier.
    """

    anthropic_version: str = Field(default="2023-06-01", description="Anthropic API version header")


class CohereConfig(BaseModel):
    """Cohere-specific configuration.

    Attributes:
        truncate: Truncation strategy to apply. Valid values include
            "NONE", "START", or "END".
    """

    truncate: Optional[str] = Field(None, description="Truncation strategy: NONE, START, END")


class HuggingFaceConfig(BaseModel):
    """Hugging Face-specific configuration.

    Attributes:
        task: Task type (e.g., "text-generation", "conversational").
        use_cache: Whether to use cached inference results.
        wait_for_model: Whether to wait if the model is still loading.
    """

    task: Optional[str] = Field(None, description="Task type (e.g., text-generation, conversational)")
    use_cache: bool = Field(default=True, description="Whether to use cached results")
    wait_for_model: bool = Field(default=False, description="Wait if model is loading")


# ---------------------------------------------------------------------------
# Provider Field Definitions for UI
# ---------------------------------------------------------------------------


class ProviderFieldDefinition(BaseModel):
    """Definition of a provider-specific configuration field for UI rendering.

    This model represents metadata for a single configuration field used
    by a provider. It is primarily intended to drive dynamic UI generation
    and validation for provider configuration forms.

    Attributes:
        name: Field name used as the key in the provider configuration dict.
        label: Human-readable display label for the field.
        field_type: Input type for the field (e.g., "text", "password",
            "number", "select", "textarea").
        required: Whether this field is mandatory.
        default_value: Default value for the field, if any.
        placeholder: Placeholder text shown in the input field.
        help_text: Additional help or description displayed to the user.
        options: List of selectable options for "select" field types.
            Each option is typically a dict with keys like "label" and "value".
        validation_pattern: Regular expression used to validate input.
        min_value: Minimum allowed value for numeric fields.
        max_value: Maximum allowed value for numeric fields.
    """

    name: str = Field(..., description="Field name (key in config dict)")
    label: str = Field(..., description="Display label for the field")
    field_type: str = Field(..., description="Input type: text, password, number, select, textarea")
    required: bool = Field(default=False, description="Whether field is required")
    default_value: Optional[Any] = Field(None, description="Default value")
    placeholder: Optional[str] = Field(None, description="Placeholder text")
    help_text: Optional[str] = Field(None, description="Help text to display")
    options: Optional[List[Dict[str, str]]] = Field(None, description="Options for select fields")
    validation_pattern: Optional[str] = Field(None, description="Regex pattern for validation")
    min_value: Optional[float] = Field(None, description="Minimum value for number fields")
    max_value: Optional[float] = Field(None, description="Maximum value for number fields")


class ProviderConfigDefinition(BaseModel):
    """Complete configuration definition for an LLM provider type.

    This model defines all metadata required to describe how a provider
    should be configured, including API requirements and provider-specific
    configuration fields. It is commonly used to drive UI rendering,
    validation, and onboarding flows for new providers.

    Attributes:
        provider_type: Unique identifier for the provider (e.g., "openai",
            "azure_openai", "aws_bedrock").
        display_name: Human-readable provider name displayed in the UI.
        description: Short description of the provider and its purpose.
        requires_api_key: Whether the provider requires an API key.
        api_key_label: Label used when displaying the API key input field.
        api_key_help: Help text shown alongside the API key input field.
        requires_api_base: Whether the provider requires an API base URL.
        api_base_default: Default API base URL, if applicable.
        api_base_help: Help text shown for the API base URL field.
        config_fields: List of provider-specific configuration field
            definitions used for UI rendering and validation.
    """

    provider_type: str
    display_name: str
    description: str
    requires_api_key: bool
    api_key_label: str = "API Key"
    api_key_help: Optional[str] = None
    requires_api_base: bool = True
    api_base_default: Optional[str] = None
    api_base_help: Optional[str] = None
    config_fields: List[ProviderFieldDefinition] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider Configuration Registry
# ---------------------------------------------------------------------------


PROVIDER_CONFIGS: Dict[str, ProviderConfigDefinition] = {
    "openai": ProviderConfigDefinition(
        provider_type="openai",
        display_name="OpenAI",
        description="OpenAI GPT models (GPT-4, GPT-4o, etc.)",
        requires_api_key=True,
        api_key_label="OpenAI API Key",
        api_key_help="Get your API key from https://platform.openai.com/api-keys",
        requires_api_base=True,
        api_base_default="https://api.openai.com/v1",
        api_base_help="Default: https://api.openai.com/v1",
        config_fields=[],
    ),
    "azure_openai": ProviderConfigDefinition(
        provider_type="azure_openai",
        display_name="Azure OpenAI",
        description="Azure OpenAI Service",
        requires_api_key=True,
        api_key_label="Azure API Key",
        api_key_help="Azure OpenAI API key from Azure Portal",
        requires_api_base=True,
        api_base_default="https://{resource}.openai.azure.com",
        api_base_help="Format: https://{resource-name}.openai.azure.com",
        config_fields=[
            ProviderFieldDefinition(
                name="deployment_name",
                label="Deployment Name",
                field_type="text",
                required=True,
                placeholder="my-gpt4-deployment",
                help_text="The name of your Azure OpenAI deployment",
            ),
            ProviderFieldDefinition(
                name="resource_name",
                label="Resource Name",
                field_type="text",
                required=True,
                placeholder="my-openai-resource",
                help_text="Your Azure OpenAI resource name",
            ),
            ProviderFieldDefinition(
                name="api_version",
                label="API Version",
                field_type="text",
                required=False,
                default_value="2024-02-15-preview",
                placeholder="2024-02-15-preview",
                help_text="Azure OpenAI API version",
            ),
        ],
    ),
    "anthropic": ProviderConfigDefinition(
        provider_type="anthropic",
        display_name="Anthropic",
        description="Anthropic Claude models",
        requires_api_key=True,
        api_key_label="Anthropic API Key",
        api_key_help="Get your API key from https://console.anthropic.com/",
        requires_api_base=True,
        api_base_default="https://api.anthropic.com",
        config_fields=[
            ProviderFieldDefinition(
                name="anthropic_version",
                label="Anthropic Version",
                field_type="text",
                required=False,
                default_value="2023-06-01",
                placeholder="2023-06-01",
                help_text="Anthropic API version header",
            ),
        ],
    ),
    "bedrock": ProviderConfigDefinition(
        provider_type="bedrock",
        display_name="AWS Bedrock",
        description="AWS Bedrock (uses IAM credentials)",
        requires_api_key=False,
        requires_api_base=False,
        config_fields=[
            ProviderFieldDefinition(
                name="region",
                label="AWS Region",
                field_type="text",
                required=True,
                default_value="us-east-1",
                placeholder="us-east-1",
                help_text="AWS region where Bedrock is available",
            ),
            ProviderFieldDefinition(
                name="access_key_id",
                label="AWS Access Key ID",
                field_type="text",
                required=False,
                placeholder="AKIAIOSFODNN7EXAMPLE",
                help_text="Optional: Leave empty to use IAM role or default credentials",
            ),
            ProviderFieldDefinition(
                name="secret_access_key",
                label="AWS Secret Access Key",
                field_type="password",
                required=False,
                placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                help_text="Optional: Leave empty to use IAM role or default credentials",
            ),
            ProviderFieldDefinition(
                name="session_token",
                label="AWS Session Token",
                field_type="password",
                required=False,
                help_text="Optional: For temporary credentials",
            ),
            ProviderFieldDefinition(
                name="profile_name",
                label="AWS Profile Name",
                field_type="text",
                required=False,
                placeholder="default",
                help_text="Optional: AWS profile from ~/.aws/credentials",
            ),
        ],
    ),
    "google_vertex": ProviderConfigDefinition(
        provider_type="google_vertex",
        display_name="Google Vertex AI",
        description="Google Vertex AI (uses service account)",
        requires_api_key=False,
        requires_api_base=False,
        config_fields=[
            ProviderFieldDefinition(
                name="project_id",
                label="Project ID",
                field_type="text",
                required=True,
                placeholder="my-gcp-project",
                help_text="Google Cloud project ID",
            ),
            ProviderFieldDefinition(
                name="location",
                label="Location",
                field_type="text",
                required=True,
                default_value="us-central1",
                placeholder="us-central1",
                help_text="Google Cloud region/location",
            ),
            ProviderFieldDefinition(
                name="credentials_path",
                label="Credentials File Path",
                field_type="text",
                required=False,
                placeholder="/path/to/service-account.json",
                help_text="Path to service account JSON file (leave empty to use default credentials)",
            ),
            ProviderFieldDefinition(
                name="credentials_json",
                label="Credentials JSON",
                field_type="textarea",
                required=False,
                placeholder='{"type": "service_account", ...}',
                help_text="Service account JSON content (alternative to file path)",
            ),
        ],
    ),
    "watsonx": ProviderConfigDefinition(
        provider_type="watsonx",
        display_name="IBM watsonx.ai",
        description="IBM watsonx.ai",
        requires_api_key=True,
        api_key_label="IBM Cloud API Key",
        api_key_help="IBM Cloud API key or Watson X API key",
        requires_api_base=True,
        api_base_default="https://us-south.ml.cloud.ibm.com",
        api_base_help="Watson X service URL",
        config_fields=[
            ProviderFieldDefinition(
                name="project_id",
                label="Project ID",
                field_type="text",
                required=False,
                placeholder="12345678-1234-1234-1234-123456789012",
                help_text="Watson X project ID (required if not using space_id)",
            ),
            ProviderFieldDefinition(
                name="space_id",
                label="Space ID",
                field_type="text",
                required=False,
                placeholder="12345678-1234-1234-1234-123456789012",
                help_text="Watson X deployment space ID (required if not using project_id)",
            ),
            ProviderFieldDefinition(
                name="deployment_id",
                label="Deployment ID",
                field_type="text",
                required=False,
                placeholder="12345678-1234-1234-1234-123456789012",
                help_text="Optional: Specific deployment ID",
            ),
            ProviderFieldDefinition(
                name="instance_id",
                label="Instance ID",
                field_type="text",
                required=False,
                help_text="Optional: Watson X instance ID",
            ),
            ProviderFieldDefinition(
                name="version",
                label="API Version",
                field_type="text",
                required=False,
                default_value="2023-05-29",
                placeholder="2023-05-29",
                help_text="Watson X API version",
            ),
        ],
    ),
    "ollama": ProviderConfigDefinition(
        provider_type="ollama",
        display_name="Ollama",
        description="Local Ollama server (OpenAI-compatible)",
        requires_api_key=False,
        requires_api_base=True,
        api_base_default="http://localhost:11434/v1",
        api_base_help="Ollama server URL (use /v1 suffix for OpenAI compatibility)",
        config_fields=[],
    ),
    "openai_compatible": ProviderConfigDefinition(
        provider_type="openai_compatible",
        display_name="OpenAI Compatible",
        description="Any OpenAI-compatible API server",
        requires_api_key=False,
        requires_api_base=True,
        api_base_default="http://localhost:8080/v1",
        api_base_help="Base URL of your OpenAI-compatible server",
        config_fields=[],
    ),
    "cohere": ProviderConfigDefinition(
        provider_type="cohere",
        display_name="Cohere",
        description="Cohere Command models",
        requires_api_key=True,
        api_key_label="Cohere API Key",
        api_key_help="Get your API key from https://dashboard.cohere.com/api-keys",
        requires_api_base=True,
        api_base_default="https://api.cohere.ai/v1",
        config_fields=[
            ProviderFieldDefinition(
                name="truncate",
                label="Truncate Strategy",
                field_type="select",
                required=False,
                help_text="How to handle inputs that exceed the model's context length",
                options=[
                    {"value": "NONE", "label": "None - Return error"},
                    {"value": "START", "label": "Start - Truncate from start"},
                    {"value": "END", "label": "End - Truncate from end"},
                ],
            ),
        ],
    ),
    "mistral": ProviderConfigDefinition(
        provider_type="mistral",
        display_name="Mistral AI",
        description="Mistral AI models",
        requires_api_key=True,
        api_key_label="Mistral API Key",
        api_key_help="Get your API key from https://console.mistral.ai/",
        requires_api_base=True,
        api_base_default="https://api.mistral.ai/v1",
        config_fields=[],
    ),
    "groq": ProviderConfigDefinition(
        provider_type="groq",
        display_name="Groq",
        description="Groq high-speed inference",
        requires_api_key=True,
        api_key_label="Groq API Key",
        api_key_help="Get your API key from https://console.groq.com/keys",
        requires_api_base=True,
        api_base_default="https://api.groq.com/openai/v1",
        config_fields=[],
    ),
    "together": ProviderConfigDefinition(
        provider_type="together",
        display_name="Together AI",
        description="Together AI inference",
        requires_api_key=True,
        api_key_label="Together API Key",
        api_key_help="Get your API key from https://api.together.xyz/settings/api-keys",
        requires_api_base=True,
        api_base_default="https://api.together.xyz/v1",
        config_fields=[],
    ),
}


def get_provider_config(provider_type: str) -> Optional[ProviderConfigDefinition]:
    """Get configuration definition for a provider type.

    Args:
        provider_type: Provider type string.

    Returns:
        ProviderConfigDefinition or None if not found.
    """
    return PROVIDER_CONFIGS.get(provider_type)


def get_all_provider_configs() -> Dict[str, ProviderConfigDefinition]:
    """Get all provider configuration definitions.

    Returns:
        Dictionary of provider type to configuration definition.
    """
    return PROVIDER_CONFIGS
