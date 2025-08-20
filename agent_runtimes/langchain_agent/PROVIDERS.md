# Multi-LLM Provider Guide

The MCP LangChain Agent supports multiple LLM providers through a unified configuration system. This guide shows you how to configure and use each supported provider.

## 🎯 Quick Setup by Provider

### 🟢 OpenAI (Recommended for beginners)

**Setup:**
```bash
cd agent_runtimes/langchain_agent
make setup-env install-dev
```

**Configuration (.env):**
```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-api-key
DEFAULT_MODEL=gpt-4o-mini
MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
```

**Popular Models:**
- `gpt-4o-mini` - Fast and cost-effective
- `gpt-4o` - Most capable GPT-4 model
- `gpt-4-turbo` - High performance
- `gpt-3.5-turbo` - Budget-friendly

---

### 🔷 Azure OpenAI (Enterprise)

**Setup:**
```bash
cd agent_runtimes/langchain_agent
make setup-azure install-azure
```

**Configuration (.env):**
```bash
LLM_PROVIDER=azure
AZURE_OPENAI_API_KEY=your-azure-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_DEPLOYMENT_NAME=your-gpt-4-deployment
AZURE_OPENAI_API_VERSION=2024-02-15-preview
DEFAULT_MODEL=your-gpt-4-deployment
MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
```

**Note:** For Azure, use your deployment name as the model name, not the underlying model name.

**Azure Setup Steps:**
1. Create Azure OpenAI resource in Azure Portal
2. Deploy a model (e.g., GPT-4) with a custom deployment name
3. Get API key and endpoint from Azure Portal
4. Use deployment name in `DEFAULT_MODEL`

---

### 🟠 AWS Bedrock (Serverless)

**Setup:**
```bash
cd agent_runtimes/langchain_agent
make setup-bedrock install-bedrock
```

**Configuration (.env):**
```bash
LLM_PROVIDER=bedrock
AWS_ACCESS_KEY_ID=your-access-key-id
AWS_SECRET_ACCESS_KEY=your-secret-access-key
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
DEFAULT_MODEL=claude-3-sonnet
MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
```

**Popular Bedrock Models:**
- `anthropic.claude-3-sonnet-20240229-v1:0` - Balanced performance
- `anthropic.claude-3-haiku-20240307-v1:0` - Fast and efficient
- `amazon.titan-text-express-v1` - Amazon's foundation model
- `meta.llama2-70b-chat-v1` - Open source Llama

**AWS Setup:**
1. Enable Bedrock access in AWS Console
2. Request model access for your desired models
3. Create IAM user with Bedrock permissions
4. Use IAM credentials or instance roles

---

### 🦙 OLLAMA (Self-hosted/Local)

**Setup:**
```bash
# Install OLLAMA first: https://ollama.ai/
curl -fsSL https://ollama.ai/install.sh | sh

# Setup agent
cd agent_runtimes/langchain_agent
make setup-ollama install-ollama
```

**Start OLLAMA:**
```bash
# Start OLLAMA service
ollama serve

# Pull a model (in another terminal)
ollama pull llama2:7b
```

**Configuration (.env):**
```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama2:7b
DEFAULT_MODEL=llama2:7b
MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
```

**Popular OLLAMA Models:**
- `llama2:7b`, `llama2:13b` - Meta's Llama 2
- `llama3:8b`, `llama3:70b` - Meta's Llama 3
- `codellama:7b` - Code-specialized Llama
- `mistral:7b` - Mistral AI model
- `gemma:7b` - Google's Gemma
- `phi3:mini` - Microsoft's Phi-3

---

### 🟣 Anthropic Claude (Direct API)

**Setup:**
```bash
cd agent_runtimes/langchain_agent
make setup-anthropic install-anthropic
```

**Configuration (.env):**
```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-anthropic-api-key
DEFAULT_MODEL=claude-3-sonnet-20240229
MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret my-test-key)
```

**Anthropic Models:**
- `claude-3-sonnet-20240229` - Balanced performance
- `claude-3-haiku-20240307` - Fast and efficient
- `claude-3-opus-20240229` - Most capable (expensive)

---

## 🔧 Installation Commands by Provider

```bash
# Install base dependencies
make install-dev

# Add specific provider support
make install-azure      # Azure OpenAI
make install-bedrock     # AWS Bedrock
make install-ollama      # OLLAMA
make install-anthropic   # Anthropic

# Install all providers (development)
make install-all-providers
```

## 🧪 Testing with Different Providers

```bash
# Validate your configuration
make check-env

# Test the agent
make dev  # Start agent

# In another terminal:
make health ready tools  # Health checks
make test-chat          # Test chat completion
make test-a2a           # Test A2A endpoint
```

## 💡 Provider Selection Guide

| Provider | Best For | Cost | Setup Complexity | Local Hosting |
|----------|----------|------|------------------|---------------|
| **OpenAI** | General use, quick start | $$$ | Easy | No |
| **Azure OpenAI** | Enterprise, compliance | $$$ | Medium | No |
| **AWS Bedrock** | AWS ecosystem, serverless | $$ | Medium | No |
| **OLLAMA** | Privacy, experimentation | Free | Easy | Yes |
| **Anthropic** | Advanced reasoning | $$$ | Easy | No |

## 🔒 Security Considerations

- **API Keys**: Store in environment variables, never in code
- **Azure**: Use managed identity when possible
- **AWS**: Use IAM roles for EC2/ECS deployments
- **OLLAMA**: Secure your local instance if exposed
- **Tool Allowlists**: Use `TOOLS=` for production security

## 🐛 Troubleshooting

### Common Issues

**Import Errors:**
```bash
# Install missing provider dependencies
make install-azure     # for Azure
make install-bedrock    # for Bedrock
make install-ollama     # for OLLAMA
make install-anthropic  # for Anthropic
```

**Configuration Errors:**
```bash
# Check your configuration
make check-env

# See example for your provider
ls examples/  # Browse provider-specific examples
```

**OLLAMA Connection Issues:**
```bash
# Check OLLAMA is running
curl http://localhost:11434/api/tags

# Pull model if not available
ollama pull llama2:7b
```

**AWS Bedrock Access:**
```bash
# Check AWS credentials
aws sts get-caller-identity

# Check Bedrock access
aws bedrock list-foundation-models --region us-east-1
```

### Provider-Specific Debugging

Enable debug mode for detailed logging:
```bash
DEBUG_MODE=true
```

Check agent logs for provider-specific errors and authentication issues.

## 📊 Performance Recommendations

| Provider | Timeout | Max Tokens | Best For |
|----------|---------|------------|----------|
| **OpenAI** | 30s | 1000-4000 | General purpose |
| **Azure** | 30s | 1000-4000 | Enterprise workloads |
| **Bedrock** | 60s | 1000-2000 | AWS integration |
| **OLLAMA** | 60s | 500-1000 | Local development |
| **Anthropic** | 30s | 1000-4000 | Complex reasoning |

Configure these in your `.env`:
```bash
REQUEST_TIMEOUT=30
MAX_TOKENS=1000
TOP_P=0.9
```
