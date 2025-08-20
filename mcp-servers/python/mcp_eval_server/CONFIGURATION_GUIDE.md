# MCP Eval Server - Configuration & Customization Guide

This guide explains how to customize the MCP Evaluation Server configuration, including models, rubrics, benchmarks, and prompts.

## 🔧 Configuration Files Overview

The MCP Eval Server uses YAML configuration files for all customizable components:

```
mcp_eval_server/config/
├── models.yaml         # LLM judge model configurations
├── rubrics.yaml        # Evaluation rubrics and criteria
├── benchmarks.yaml     # Performance benchmarks and test suites
├── judge_prompts.yaml  # Judge prompt templates
└── __init__.py
```

## 📄 Custom Configuration Paths

### Environment Variables for Custom Configs

```bash
# Custom model configuration
export MCP_EVAL_MODELS_CONFIG="/path/to/custom/models.yaml"

# Custom configuration directory (for all config files)
export MCP_EVAL_CONFIG_DIR="/path/to/custom/config/"

# Individual custom configs (future enhancement)
export MCP_EVAL_RUBRICS_CONFIG="/path/to/custom/rubrics.yaml"
export MCP_EVAL_BENCHMARKS_CONFIG="/path/to/custom/benchmarks.yaml"
```

### Server Startup with Custom Config

```bash
# Using custom models.yaml
export MCP_EVAL_MODELS_CONFIG="./my-custom-models.yaml"
python -m mcp_eval_server.server

# Startup log will show:
# 📄 Using custom models config: ./my-custom-models.yaml
```

## 🎯 Model Configuration Customization

### Creating Custom models.yaml

Create your own `my-models.yaml`:

```yaml
# Custom Model Configuration for MCP Eval Server
models:
  # Your OpenAI models
  openai:
    my-gpt4:
      provider: "openai"
      model_name: "gpt-4"
      api_key_env: "MY_OPENAI_KEY"
      organization_env: "MY_OPENAI_ORG"
      default_temperature: 0.1  # Custom temperature
      max_tokens: 4000
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 8192
        optimal_temperature: 0.1
        consistency_level: "high"

  # Your Azure deployments
  azure:
    my-enterprise-gpt4:
      provider: "azure"
      deployment_name: "my-gpt4-deployment"
      model_name: "gpt-4"
      api_base_env: "MY_AZURE_ENDPOINT"
      api_key_env: "MY_AZURE_KEY"
      api_version_env: "MY_AZURE_VERSION"
      deployment_name_env: "MY_AZURE_DEPLOYMENT"
      default_temperature: 0.2
      max_tokens: 3000

  # Your Anthropic models
  anthropic:
    my-claude:
      provider: "anthropic"
      model_name: "claude-3-opus-20240229"
      api_key_env: "MY_ANTHROPIC_KEY"
      default_temperature: 0.3
      max_tokens: 4000

  # Your OLLAMA models
  ollama:
    my-local-llama:
      provider: "ollama"
      model_name: "llama3:70b"  # Your specific model
      base_url_env: "MY_OLLAMA_URL"
      default_temperature: 0.4
      max_tokens: 2000
      request_timeout: 120  # Longer timeout for large models

# Custom defaults
defaults:
  primary_judge: "my-enterprise-gpt4"
  fallback_judge: "my-gpt4"
  fast_judge: "my-claude"
  consensus_judges: ["my-enterprise-gpt4", "my-claude", "my-gpt4"]

# Custom recommendations
recommendations:
  production_evaluation: ["my-enterprise-gpt4", "my-claude"]
  development_testing: ["my-gpt4", "my-local-llama"]
  cost_optimization: ["my-local-llama"]
```

### Environment Setup for Custom Configuration

```bash
# Your custom environment variables
export MY_OPENAI_KEY="sk-your-key"
export MY_AZURE_ENDPOINT="https://your-company.openai.azure.com/"
export MY_AZURE_KEY="your-azure-key"
export MY_AZURE_VERSION="2025-01-01-preview"
export MY_AZURE_DEPLOYMENT="your-gpt4-deployment"
export MY_ANTHROPIC_KEY="sk-ant-your-key"
export MY_OLLAMA_URL="http://your-ollama-server:11434"

# Point to your custom config
export MCP_EVAL_MODELS_CONFIG="./my-models.yaml"
export DEFAULT_JUDGE_MODEL="my-enterprise-gpt4"
```

## 🏢 Enterprise Configuration Examples

### Multi-Environment Setup

**Production models.yaml:**
```yaml
models:
  openai:
    prod-gpt4-turbo:
      provider: "openai"
      model_name: "gpt-4-turbo-preview"
      api_key_env: "PROD_OPENAI_API_KEY"
      default_temperature: 0.1  # Lower temperature for consistency
      max_tokens: 4000

  azure:
    prod-azure-gpt4:
      provider: "azure"
      deployment_name: "prod-gpt4-deployment"
      model_name: "gpt-4"
      api_base_env: "PROD_AZURE_ENDPOINT"
      api_key_env: "PROD_AZURE_API_KEY"
      api_version: "2024-02-15-preview"
      default_temperature: 0.1
      max_tokens: 4000

defaults:
  primary_judge: "prod-azure-gpt4"
  fallback_judge: "prod-gpt4-turbo"

recommendations:
  high_stakes_evaluation: ["prod-azure-gpt4", "prod-gpt4-turbo"]
```

**Development models.yaml:**
```yaml
models:
  openai:
    dev-gpt35:
      provider: "openai"
      model_name: "gpt-3.5-turbo"
      api_key_env: "DEV_OPENAI_API_KEY"
      default_temperature: 0.3
      max_tokens: 2000

  ollama:
    dev-llama:
      provider: "ollama"
      model_name: "llama3:8b"
      base_url_env: "DEV_OLLAMA_URL"
      default_temperature: 0.5
      max_tokens: 1000
      request_timeout: 60

defaults:
  primary_judge: "dev-llama"  # Use local model for development
  fallback_judge: "dev-gpt35"
```

### Department-Specific Configurations

**Research Department:**
```yaml
models:
  anthropic:
    research-claude-opus:
      provider: "anthropic"
      model_name: "claude-3-opus-20240229"
      api_key_env: "RESEARCH_ANTHROPIC_KEY"
      default_temperature: 0.2  # Low temp for research consistency
      max_tokens: 4000

    research-claude-sonnet:
      provider: "anthropic"
      model_name: "claude-3-sonnet-20240229"
      api_key_env: "RESEARCH_ANTHROPIC_KEY"
      default_temperature: 0.2
      max_tokens: 4000

defaults:
  primary_judge: "research-claude-opus"
  consensus_judges: ["research-claude-opus", "research-claude-sonnet"]

recommendations:
  research_evaluation: ["research-claude-opus", "research-claude-sonnet"]
  peer_review: ["research-claude-opus"]
```

**QA Department:**
```yaml
models:
  azure:
    qa-gpt4-strict:
      provider: "azure"
      deployment_name: "qa-gpt4-deployment"
      model_name: "gpt-4"
      api_base_env: "QA_AZURE_ENDPOINT"
      api_key_env: "QA_AZURE_API_KEY"
      default_temperature: 0.0  # Zero temperature for strict evaluation
      max_tokens: 2000

  openai:
    qa-gpt4-turbo:
      provider: "openai"
      model_name: "gpt-4-turbo-preview"
      api_key_env: "QA_OPENAI_KEY"
      default_temperature: 0.0
      max_tokens: 3000

defaults:
  primary_judge: "qa-gpt4-strict"
  consensus_judges: ["qa-gpt4-strict", "qa-gpt4-turbo"]

recommendations:
  quality_assurance: ["qa-gpt4-strict", "qa-gpt4-turbo"]
  strict_evaluation: ["qa-gpt4-strict"]
```

## 🎨 Advanced Customization Features

### Model-Specific Parameters

```yaml
models:
  openai:
    creative-gpt4:
      provider: "openai"
      model_name: "gpt-4"
      api_key_env: "OPENAI_API_KEY"
      default_temperature: 0.9  # High creativity
      max_tokens: 4000
      # Custom parameters for this judge
      custom_params:
        top_p: 0.95
        frequency_penalty: 0.2
        presence_penalty: 0.1
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 8192
        optimal_temperature: 0.9  # Match default
        consistency_level: "medium"  # Lower due to high temperature

    analytical-gpt4:
      provider: "openai"
      model_name: "gpt-4"
      api_key_env: "OPENAI_API_KEY"
      default_temperature: 0.1  # Very analytical
      max_tokens: 4000
      custom_params:
        top_p: 0.8
        frequency_penalty: 0.0
        presence_penalty: 0.0
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 8192
        optimal_temperature: 0.1
        consistency_level: "very_high"
```

### Regional/Language-Specific Models

```yaml
models:
  azure:
    europe-gpt4:
      provider: "azure"
      deployment_name: "eu-gpt4-deployment"
      model_name: "gpt-4"
      api_base_env: "EU_AZURE_ENDPOINT"  # European endpoint
      api_key_env: "EU_AZURE_API_KEY"
      api_version: "2024-02-15-preview"
      default_temperature: 0.3
      max_tokens: 2000
      metadata:
        region: "europe"
        language_focus: "multilingual"

    asia-gpt4:
      provider: "azure"
      deployment_name: "asia-gpt4-deployment"
      model_name: "gpt-4"
      api_base_env: "ASIA_AZURE_ENDPOINT"  # Asian endpoint
      api_key_env: "ASIA_AZURE_API_KEY"
      api_version: "2024-02-15-preview"
      default_temperature: 0.3
      max_tokens: 2000
      metadata:
        region: "asia"
        language_focus: "japanese,chinese,korean"
```

### Custom OLLAMA Models

```yaml
models:
  ollama:
    my-custom-model:
      provider: "ollama"
      model_name: "my-custom-model:latest"  # Your fine-tuned model
      base_url_env: "OLLAMA_BASE_URL"
      default_temperature: 0.3
      max_tokens: 2000
      request_timeout: 90
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: false  # May not be good at ranking
        supports_reference: true
        max_context_length: 4096
        consistency_level: "medium"
      metadata:
        fine_tuned_for: "technical_evaluation"
        training_data: "code_reviews"

    codellama-specialized:
      provider: "ollama"
      model_name: "codellama:13b-instruct"
      base_url_env: "OLLAMA_BASE_URL"
      default_temperature: 0.2  # Lower for code evaluation
      max_tokens: 3000
      request_timeout: 120
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: false
        supports_reference: true
        max_context_length: 8192
        consistency_level: "high"
      metadata:
        specialization: "code_evaluation"
        use_cases: ["code_quality", "technical_accuracy"]
```

## 📊 Configuration Validation

### Built-in Validation Commands

```bash
# Validate your custom configuration
export MCP_EVAL_MODELS_CONFIG="./my-models.yaml"
make validate-models

# Check specific aspects
export MCP_EVAL_MODELS_CONFIG="./my-models.yaml"
python3 -c "
from mcp_eval_server.tools.judge_tools import JudgeTools
jt = JudgeTools()
print('Available judges:', jt.get_available_judges())
"
```

### Configuration Validation Script

Create `validate_config.py`:

```python
#!/usr/bin/env python3
import os
import yaml
import sys

def validate_models_config(config_path):
    """Validate models.yaml configuration."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return False

    # Validate structure
    if 'models' not in config:
        print("❌ Missing 'models' section")
        return False

    issues = []
    warnings = []

    for provider, models in config['models'].items():
        for model_name, model_config in models.items():
            # Check required fields
            required_fields = ['provider', 'model_name']
            for field in required_fields:
                if field not in model_config:
                    issues.append(f"Model {model_name}: missing {field}")

            # Check environment variables exist
            if 'api_key_env' in model_config:
                if not os.getenv(model_config['api_key_env']):
                    warnings.append(f"Model {model_name}: {model_config['api_key_env']} not set")

    # Report results
    print(f"✅ Configuration validation completed")
    print(f"   Issues: {len(issues)}")
    print(f"   Warnings: {len(warnings)}")

    for issue in issues:
        print(f"   ❌ {issue}")
    for warning in warnings:
        print(f"   ⚠️  {warning}")

    return len(issues) == 0

if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "./models.yaml"
    success = validate_models_config(config_path)
    sys.exit(0 if success else 1)
```

## 🎛️ Provider-Specific Configuration Examples

### OpenAI Advanced Configuration

```yaml
models:
  openai:
    # High-performance evaluation
    gpt4-turbo-eval:
      provider: "openai"
      model_name: "gpt-4-turbo-preview"
      api_key_env: "OPENAI_API_KEY"
      organization_env: "OPENAI_ORGANIZATION"
      base_url_env: "OPENAI_BASE_URL"  # Optional custom endpoint
      default_temperature: 0.1
      max_tokens: 4000
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 128000
        optimal_temperature: 0.1
        consistency_level: "very_high"
      metadata:
        cost_tier: "premium"
        use_case: "production_evaluation"

    # Creative evaluation
    gpt4-creative:
      provider: "openai"
      model_name: "gpt-4"
      api_key_env: "OPENAI_API_KEY"
      default_temperature: 0.8  # Higher creativity
      max_tokens: 3000
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: false  # Less reliable at high temperature
        supports_reference: true
        max_context_length: 8192
        optimal_temperature: 0.8
        consistency_level: "medium"
      metadata:
        specialization: "creative_content"
        use_case: "creative_evaluation"
```

### Azure Multi-Region Configuration

```yaml
models:
  azure:
    # US East region
    azure-us-gpt4:
      provider: "azure"
      deployment_name: "us-gpt4-deployment"
      model_name: "gpt-4"
      api_base_env: "AZURE_US_ENDPOINT"
      api_key_env: "AZURE_US_API_KEY"
      api_version: "2024-02-15-preview"
      deployment_name_env: "AZURE_US_DEPLOYMENT"
      default_temperature: 0.3
      max_tokens: 2000
      metadata:
        region: "us-east"
        latency: "low"

    # Europe region
    azure-eu-gpt4:
      provider: "azure"
      deployment_name: "eu-gpt4-deployment"
      model_name: "gpt-4"
      api_base_env: "AZURE_EU_ENDPOINT"
      api_key_env: "AZURE_EU_API_KEY"
      api_version: "2024-02-15-preview"
      deployment_name_env: "AZURE_EU_DEPLOYMENT"
      default_temperature: 0.3
      max_tokens: 2000
      metadata:
        region: "europe"
        compliance: "gdpr"
```

### Google Gemini Configuration

```yaml
models:
  gemini:
    # High-performance Gemini Pro
    gemini-1-5-pro-eval:
      provider: "gemini"
      model_name: "gemini-1.5-pro-latest"
      api_key_env: "GOOGLE_API_KEY"
      default_temperature: 0.1  # Conservative for evaluation
      max_tokens: 4000
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 2000000  # 2M tokens!
        optimal_temperature: 0.1
        consistency_level: "very_high"
      metadata:
        provider: "google"
        context_window: "2M_tokens"

    # Fast Gemini Flash
    gemini-flash-eval:
      provider: "gemini"
      model_name: "gemini-1.5-flash-latest"
      api_key_env: "GOOGLE_API_KEY"
      default_temperature: 0.3
      max_tokens: 3000
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 1000000  # 1M tokens
        optimal_temperature: 0.3
        consistency_level: "high"
      metadata:
        provider: "google"
        optimized_for: "speed"
```

### IBM Watsonx.ai Configuration

```yaml
models:
  watsonx:
    # Llama 3.1 70B on Watsonx
    llama-3-1-70b-enterprise:
      provider: "watsonx"
      model_id: "meta-llama/llama-3-1-70b-instruct"
      model_name: "llama-3.1-70b-enterprise"
      api_key_env: "WATSONX_API_KEY"
      project_id_env: "WATSONX_PROJECT_ID"
      url_env: "WATSONX_URL"
      default_temperature: 0.2
      max_tokens: 2000
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 128000
        optimal_temperature: 0.2
        consistency_level: "high"
      metadata:
        provider: "ibm"
        model_family: "llama"
        enterprise: true

    # IBM Granite models
    granite-3-0-8b-enterprise:
      provider: "watsonx"
      model_id: "ibm/granite-3-0-8b-instruct"
      model_name: "granite-3.0-8b-enterprise"
      api_key_env: "WATSONX_API_KEY"
      project_id_env: "WATSONX_PROJECT_ID"
      url_env: "WATSONX_URL"
      default_temperature: 0.3
      max_tokens: 2000
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 8192
        optimal_temperature: 0.3
        consistency_level: "high"
      metadata:
        provider: "ibm"
        model_family: "granite"
        enterprise: true
        optimized_for: "enterprise_use"
```

### AWS Bedrock with Claude 4.1

```yaml
models:
  bedrock:
    # Claude 4.1 on AWS Bedrock
    claude-4-1-production:
      provider: "bedrock"
      model_id: "anthropic.claude-3-5-sonnet-20241022-v2:0"
      model_name: "claude-4.1-production"
      aws_access_key_env: "AWS_ACCESS_KEY_ID"
      aws_secret_key_env: "AWS_SECRET_ACCESS_KEY"
      aws_region_env: "AWS_REGION"
      default_temperature: 0.1  # Very conservative for production
      max_tokens: 4000
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 200000
        optimal_temperature: 0.1
        consistency_level: "very_high"
      metadata:
        provider: "aws"
        model_version: "4.1"
        enterprise: true
        compliance: "sox_gdpr"
```

### Custom OLLAMA Fleet

```yaml
models:
  ollama:
    # Code evaluation specialist
    codellama-eval:
      provider: "ollama"
      model_name: "codellama:13b-instruct"
      base_url_env: "CODE_OLLAMA_URL"
      default_temperature: 0.1
      max_tokens: 4000
      request_timeout: 120
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: false
        supports_reference: true
        max_context_length: 8192
        consistency_level: "high"
      metadata:
        specialization: "code_evaluation"

    # General purpose evaluation
    llama3-general:
      provider: "ollama"
      model_name: "llama3:70b"
      base_url_env: "GENERAL_OLLAMA_URL"
      default_temperature: 0.3
      max_tokens: 3000
      request_timeout: 180
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: true
        supports_reference: true
        max_context_length: 8192
        consistency_level: "high"
      metadata:
        specialization: "general_evaluation"

    # Fast evaluation
    phi3-fast:
      provider: "ollama"
      model_name: "phi3:medium"
      base_url_env: "FAST_OLLAMA_URL"
      default_temperature: 0.3
      max_tokens: 1000
      request_timeout: 30
      capabilities:
        supports_cot: true
        supports_pairwise: true
        supports_ranking: false
        supports_reference: true
        max_context_length: 4096
        consistency_level: "medium"
      metadata:
        specialization: "fast_evaluation"
```

## 🚀 Usage Examples

### Basic Custom Configuration

```bash
# 1. Create your custom models.yaml
cat > my-models.yaml << 'EOF'
models:
  azure:
    my-deployment:
      provider: "azure"
      deployment_name: "my-gpt4-deployment"
      model_name: "gpt-4"
      api_base_env: "AZURE_OPENAI_ENDPOINT"
      api_key_env: "AZURE_OPENAI_API_KEY"
      api_version_env: "AZURE_OPENAI_API_VERSION"
      deployment_name_env: "AZURE_DEPLOYMENT_NAME"
      default_temperature: 0.2
      max_tokens: 3000

defaults:
  primary_judge: "my-deployment"
EOF

# 2. Set environment variables
export MCP_EVAL_MODELS_CONFIG="./my-models.yaml"
export DEFAULT_JUDGE_MODEL="my-deployment"
export AZURE_OPENAI_API_KEY="your-key"
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_DEPLOYMENT_NAME="my-gpt4-deployment"

# 3. Start server
python -m mcp_eval_server.server

# Logs will show:
# 📄 Using custom models config: ./my-models.yaml
# 🎯 Primary judge selection: my-deployment
# 📊 my-deployment (azure): gpt-4 → https://your-resource.openai.azure.com/ (deployment: my-gpt4-deployment)
```

### Multi-Model Evaluation Setup

```bash
# Environment for multiple providers
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_ENDPOINT="..."
export OLLAMA_BASE_URL="http://localhost:11434"

# Custom models with all providers
export MCP_EVAL_MODELS_CONFIG="./multi-provider-models.yaml"
export DEFAULT_JUDGE_MODEL="consensus-primary"

python -m mcp_eval_server.server
```

## 📋 Configuration Best Practices

### Naming Conventions

```yaml
models:
  provider:
    # Use descriptive names indicating purpose
    prod-gpt4-strict:       # Production, strict evaluation
    dev-claude-creative:    # Development, creative evaluation
    qa-gpt35-fast:         # QA, fast evaluation
    research-opus-deep:    # Research, deep analysis

    # Include key characteristics
    gpt4-temp01-eval:      # Temperature 0.1 for evaluation
    claude-temp08-creative: # Temperature 0.8 for creativity
    llama-local-dev:       # Local OLLAMA for development
```

### Environment Variable Organization

```bash
# Group by environment
export PROD_OPENAI_API_KEY="..."
export DEV_OPENAI_API_KEY="..."
export QA_OPENAI_API_KEY="..."

# Group by provider
export OPENAI_API_KEY="..."
export OPENAI_ORG_PROD="..."
export OPENAI_ORG_DEV="..."

export AZURE_PROD_ENDPOINT="..."
export AZURE_DEV_ENDPOINT="..."

# Group by purpose
export EVAL_ANTHROPIC_KEY="..."     # For evaluation
export CREATIVE_ANTHROPIC_KEY="..." # For creative tasks
```

### Security Considerations

```yaml
models:
  azure:
    secure-eval:
      provider: "azure"
      # Use separate keys for different purposes
      api_key_env: "EVALUATION_AZURE_KEY"  # Not shared with other services
      # Separate endpoints for isolation
      api_base_env: "EVALUATION_AZURE_ENDPOINT"
      # Version pinning for stability
      api_version: "2024-02-15-preview"
      metadata:
        security_level: "high"
        purpose: "evaluation_only"
```

## 🔍 Troubleshooting Custom Configurations

### Common Issues

1. **Model Not Loading**
   ```bash
   # Check configuration syntax
   python3 -c "import yaml; yaml.safe_load(open('my-models.yaml'))"

   # Check environment variables
   make validate-models
   ```

2. **Wrong Environment Variables**
   ```bash
   # Enable debug logging to see exactly what's being loaded
   export LOG_LEVEL=DEBUG
   python -m mcp_eval_server.server
   ```

3. **API Key Issues**
   ```bash
   # Verify keys are actually set
   env | grep -E "(OPENAI|AZURE|ANTHROPIC|AWS)_"

   # Test with minimal config
   export MCP_EVAL_MODELS_CONFIG="./minimal-test.yaml"
   ```

### Minimal Test Configuration

```yaml
# minimal-test.yaml
models:
  openai:
    test-gpt35:
      provider: "openai"
      model_name: "gpt-3.5-turbo"
      api_key_env: "OPENAI_API_KEY"
      default_temperature: 0.3
      max_tokens: 1000

defaults:
  primary_judge: "test-gpt35"
```

## 🎯 Migration Guide

### From Default to Custom Configuration

1. **Copy default configuration**:
   ```bash
   cp mcp_eval_server/config/models.yaml ./my-models.yaml
   ```

2. **Modify for your needs**:
   - Update model names
   - Change environment variable names
   - Adjust temperature/token settings
   - Add custom metadata

3. **Set environment variables**:
   ```bash
   export MCP_EVAL_MODELS_CONFIG="./my-models.yaml"
   export DEFAULT_JUDGE_MODEL="your-primary-model"
   ```

4. **Validate and test**:
   ```bash
   make validate-models
   python -m mcp_eval_server.server
   ```

### Gradual Migration

```bash
# Start with existing config + your additions
export MCP_EVAL_MODELS_CONFIG="./extended-models.yaml"
```

```yaml
# extended-models.yaml - extends default config
models:
  # Include all default models
  openai:
    gpt-4:
      provider: "openai"
      model_name: "gpt-4"
      api_key_env: "OPENAI_API_KEY"
      # ... (copy from default)

  # Add your custom models
  azure:
    my-custom-deployment:
      provider: "azure"
      deployment_name: "my-deployment"
      # ... your configuration
```

## 📈 Advanced Use Cases

### A/B Testing Configuration

```yaml
models:
  openai:
    eval-variant-a:
      provider: "openai"
      model_name: "gpt-4"
      api_key_env: "OPENAI_API_KEY"
      default_temperature: 0.1
      max_tokens: 2000
      metadata:
        variant: "conservative"

    eval-variant-b:
      provider: "openai"
      model_name: "gpt-4"
      api_key_env: "OPENAI_API_KEY"
      default_temperature: 0.5
      max_tokens: 2000
      metadata:
        variant: "moderate"

defaults:
  consensus_judges: ["eval-variant-a", "eval-variant-b"]

recommendations:
  ab_testing: ["eval-variant-a", "eval-variant-b"]
```

### Domain-Specific Configurations

```yaml
models:
  anthropic:
    medical-claude:
      provider: "anthropic"
      model_name: "claude-3-opus-20240229"
      api_key_env: "MEDICAL_ANTHROPIC_KEY"
      default_temperature: 0.1  # Very conservative for medical
      max_tokens: 4000
      metadata:
        domain: "medical"
        compliance: "hipaa"

    legal-claude:
      provider: "anthropic"
      model_name: "claude-3-opus-20240229"
      api_key_env: "LEGAL_ANTHROPIC_KEY"
      default_temperature: 0.1
      max_tokens: 4000
      metadata:
        domain: "legal"
        compliance: "legal_review"

recommendations:
  medical_evaluation: ["medical-claude"]
  legal_evaluation: ["legal-claude"]
```

## 🔧 Configuration Management

### Environment-Specific Configs

```bash
# Development
export MCP_EVAL_MODELS_CONFIG="./config/dev-models.yaml"
export DEFAULT_JUDGE_MODEL="dev-fast-model"

# Staging
export MCP_EVAL_MODELS_CONFIG="./config/staging-models.yaml"
export DEFAULT_JUDGE_MODEL="staging-gpt4"

# Production
export MCP_EVAL_MODELS_CONFIG="./config/prod-models.yaml"
export DEFAULT_JUDGE_MODEL="prod-azure-gpt4"
```

### Docker Configuration

```dockerfile
# Dockerfile with custom config
FROM python:3.11-slim

COPY my-models.yaml /app/config/models.yaml
ENV MCP_EVAL_MODELS_CONFIG=/app/config/models.yaml

# Environment-specific configs
COPY config/ /app/config/
ENV MCP_EVAL_CONFIG_DIR=/app/config/
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  mcp-eval-server:
    build: .
    environment:
      - MCP_EVAL_MODELS_CONFIG=/app/config/prod-models.yaml
      - DEFAULT_JUDGE_MODEL=prod-azure-gpt4
      - AZURE_OPENAI_API_KEY=${AZURE_OPENAI_API_KEY}
      - AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}
    volumes:
      - ./config:/app/config:ro
```

## 📚 Additional Configuration Files

While `models.yaml` is the primary configuration file, you can also customize:

### Rubrics Configuration (Future Enhancement)
```yaml
# custom-rubrics.yaml
rubrics:
  technical_deep_dive:
    name: "Technical Deep Dive Assessment"
    criteria:
      - name: "technical_accuracy"
        description: "Correctness of technical information"
        scale: "1-10"
        weight: 0.4
      - name: "implementation_feasibility"
        description: "Practicality of suggested implementation"
        scale: "1-10"
        weight: 0.3
```

### Benchmarks Configuration (Future Enhancement)
```yaml
# custom-benchmarks.yaml
benchmarks:
  enterprise_code_review:
    name: "Enterprise Code Review Benchmark"
    category: "technical"
    tasks:
      - name: "security_analysis"
        description: "Security vulnerability assessment"
        expected_tools: ["security_scanner", "code_analyzer"]
```

## 💡 Pro Tips

### Configuration Testing
```bash
# Test configuration without full server startup
python3 -c "
import os
os.environ['MCP_EVAL_MODELS_CONFIG'] = './my-models.yaml'
from mcp_eval_server.tools.judge_tools import JudgeTools
jt = JudgeTools()
print('✅ Configuration loaded successfully')
print('Available judges:', jt.get_available_judges())
"
```

### Configuration Backup
```bash
# Backup current working config
cp mcp_eval_server/config/models.yaml ./backup-models-$(date +%Y%m%d).yaml

# Version control your custom configs
git add my-models.yaml .env.example
git commit -m "Add custom model configuration"
```

### Performance Optimization
```yaml
# Optimize for your use case
models:
  openai:
    fast-eval:
      model_name: "gpt-3.5-turbo"
      default_temperature: 0.2
      max_tokens: 1000  # Shorter responses = faster

    thorough-eval:
      model_name: "gpt-4-turbo-preview"
      default_temperature: 0.1
      max_tokens: 4000  # Longer responses = more detailed
```

This comprehensive configuration system allows you to tailor the MCP Eval Server exactly to your organization's needs, security requirements, and performance objectives.
