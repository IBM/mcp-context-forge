# Python MCP Evaluation Server

## Overview

The **Ultimate AI Evaluation Platform** providing the most comprehensive AI assessment tools in the MCP ecosystem. Features **63 specialized tools** across **14 categories** for complete AI system evaluation using **LLM-as-a-judge techniques** combined with rule-based metrics.

**Author:** Mihai Criveti

**Key Highlights:**

- 🤖 63 specialized evaluation tools
- 📊 14 distinct tool categories
- 🎯 LLM-as-a-judge with bias mitigation
- 📈 Statistical rigor with confidence intervals
- 🌐 Multi-modal assessment capabilities
- 🔄 Extensible rubric system
- 🚀 Multiple server modes (MCP, REST, HTTP Bridge)

## Quick Start

### Installation

```bash
# Navigate to server directory
cd mcp-servers/python/mcp_eval_server

# Install with development dependencies
pip install -e ".[dev]"
```

### Running the Server

#### MCP Server Mode (stdio)
```bash
# Launch MCP server for Claude Desktop, MCP clients
python -m mcp_eval_server.server

# Or use make command
make dev
```

#### REST API Server Mode
```bash
# Launch FastAPI REST server
python -m mcp_eval_server.rest_server --port 8080 --host 0.0.0.0

# Or use make command
make serve-rest

# Access interactive docs
open http://localhost:8080/docs
```

#### HTTP Bridge Mode
```bash
# MCP protocol over HTTP with Server-Sent Events
make serve-http

# Access via JSON-RPC on port 9000
curl -X POST -H 'Content-Type: application/json' \
     -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' \
     http://localhost:9000/
```

### Health Monitoring

```bash
# Liveness probe
curl http://localhost:8080/health

# Readiness probe
curl http://localhost:8080/ready

# Performance metrics
curl http://localhost:8080/metrics
```

## Tool Categories

### 🤖 LLM-as-a-Judge Tools (5 tools)

#### evaluate_single
Evaluate a single response with customizable criteria.

```json
{
  "tool": "evaluate_single",
  "arguments": {
    "response": "The capital of France is Paris.",
    "criteria": ["accuracy", "clarity", "completeness"],
    "weights": {"accuracy": 0.5, "clarity": 0.3, "completeness": 0.2},
    "judge_model": "gpt-4"
  }
}
```

#### compare_pairwise
Compare two responses head-to-head with position bias mitigation.

```json
{
  "tool": "compare_pairwise",
  "arguments": {
    "response_a": "Response 1 text",
    "response_b": "Response 2 text",
    "criteria": ["relevance", "coherence"],
    "mitigate_position_bias": true
  }
}
```

#### rank_multiple
Rank multiple responses using tournament or scoring algorithms.

```json
{
  "tool": "rank_multiple",
  "arguments": {
    "responses": ["Response 1", "Response 2", "Response 3"],
    "method": "tournament",
    "criteria": ["quality", "accuracy"]
  }
}
```

### 📝 Prompt Evaluation Tools (4 tools)

#### analyze_prompt_clarity
Detect ambiguity and provide improvement recommendations.

```json
{
  "tool": "analyze_prompt_clarity",
  "arguments": {
    "prompt": "Write a story about a bank",
    "context": "creative writing",
    "suggest_improvements": true
  }
}
```

#### test_prompt_consistency
Analyze variance across multiple runs.

```json
{
  "tool": "test_prompt_consistency",
  "arguments": {
    "prompt": "Generate a product description",
    "num_runs": 10,
    "temperature_range": [0.3, 0.7, 1.0]
  }
}
```

### 🛠️ Agent Evaluation Tools (4 tools)

#### evaluate_tool_usage
Assess agent tool selection and usage patterns.

```json
{
  "tool": "evaluate_tool_usage",
  "arguments": {
    "agent_trace": [...],
    "available_tools": ["search", "calculate", "summarize"],
    "task_requirements": ["find information", "compute result"]
  }
}
```

#### assess_reasoning_chain
Evaluate logical reasoning and coherence.

```json
{
  "tool": "assess_reasoning_chain",
  "arguments": {
    "reasoning_steps": [...],
    "expected_logic": "deductive",
    "check_consistency": true
  }
}
```

### 🔗 RAG Evaluation Tools (8 tools)

#### evaluate_retrieval
Assess retrieval relevance and precision.

```json
{
  "tool": "evaluate_retrieval",
  "arguments": {
    "query": "What is quantum computing?",
    "retrieved_docs": [...],
    "relevance_threshold": 0.7,
    "use_reranking": true
  }
}
```

#### check_grounding
Verify response grounding in source documents.

```json
{
  "tool": "check_grounding",
  "arguments": {
    "response": "Generated answer",
    "source_docs": [...],
    "require_citations": true
  }
}
```

### ⚖️ Bias & Fairness Tools (6 tools)

#### detect_demographic_bias
Identify demographic biases in responses.

```json
{
  "tool": "detect_demographic_bias",
  "arguments": {
    "responses": [...],
    "demographics": ["gender", "age", "ethnicity"],
    "baseline_comparison": true
  }
}
```

#### analyze_representation
Check representation equity across groups.

```json
{
  "tool": "analyze_representation",
  "arguments": {
    "content": "Generated text",
    "groups": ["professional", "cultural", "geographic"],
    "expected_distribution": {...}
  }
}
```

### 🛡️ Robustness Tools (5 tools)

#### test_adversarial
Test against adversarial inputs.

```json
{
  "tool": "test_adversarial",
  "arguments": {
    "base_input": "Original prompt",
    "attack_types": ["typo", "semantic", "injection"],
    "num_variants": 20
  }
}
```

#### check_stability
Analyze output stability across variations.

```json
{
  "tool": "check_stability",
  "arguments": {
    "prompt_template": "Explain {topic} in simple terms",
    "variations": ["quantum physics", "machine learning"],
    "stability_threshold": 0.8
  }
}
```

### 🔒 Safety & Alignment Tools (4 tools)

#### detect_harmful_content
Identify potentially harmful content.

```json
{
  "tool": "detect_harmful_content",
  "arguments": {
    "content": "Generated text",
    "categories": ["violence", "bias", "misinformation"],
    "sensitivity": "high"
  }
}
```

#### check_instruction_adherence
Verify alignment with instructions.

```json
{
  "tool": "check_instruction_adherence",
  "arguments": {
    "instructions": ["Be concise", "Use examples"],
    "response": "Generated response",
    "strict_mode": true
  }
}
```

### 🌍 Multilingual Tools (4 tools)

#### evaluate_translation
Assess translation quality across languages.

```json
{
  "tool": "evaluate_translation",
  "arguments": {
    "source_text": "Hello world",
    "translated_text": "Bonjour le monde",
    "source_lang": "en",
    "target_lang": "fr",
    "check_fluency": true
  }
}
```

#### check_cross_lingual_consistency
Verify consistency across languages.

```json
{
  "tool": "check_cross_lingual_consistency",
  "arguments": {
    "responses": {
      "en": "English response",
      "fr": "Réponse française",
      "es": "Respuesta española"
    },
    "check_semantic": true
  }
}
```

### ⚡ Performance Tools (4 tools)

#### measure_latency
Track response latency metrics.

```json
{
  "tool": "measure_latency",
  "arguments": {
    "operation": "text_generation",
    "input_size": 1000,
    "num_samples": 100,
    "percentiles": [50, 90, 95, 99]
  }
}
```

#### analyze_efficiency
Evaluate computational efficiency.

```json
{
  "tool": "analyze_efficiency",
  "arguments": {
    "model": "gpt-3.5-turbo",
    "task": "summarization",
    "input_tokens": 500,
    "measure_memory": true
  }
}
```

### 🔐 Privacy Tools (8 tools)

#### detect_pii
Identify personally identifiable information.

```json
{
  "tool": "detect_pii",
  "arguments": {
    "text": "John Doe lives at 123 Main St",
    "pii_types": ["name", "address", "phone", "email"],
    "redact": true
  }
}
```

#### check_data_minimization
Verify data minimization practices.

```json
{
  "tool": "check_data_minimization",
  "arguments": {
    "collected_fields": [...],
    "required_fields": [...],
    "purpose": "user_registration"
  }
}
```

### 🔄 Workflow Tools (3 tools)

#### run_evaluation_suite
Execute comprehensive evaluation suites.

```json
{
  "tool": "run_evaluation_suite",
  "arguments": {
    "suite_name": "production_readiness",
    "components": ["safety", "performance", "quality"],
    "parallel": true
  }
}
```

#### compare_results
Compare evaluation results across versions.

```json
{
  "tool": "compare_results",
  "arguments": {
    "baseline_results": {...},
    "current_results": {...},
    "significance_level": 0.05
  }
}
```

## Configuration

### Environment Variables

```bash
# LLM Configuration
OPENAI_API_KEY=your-key-here
AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com
ANTHROPIC_API_KEY=your-anthropic-key

# Server Configuration
EVAL_SERVER_PORT=8080
EVAL_SERVER_HOST=0.0.0.0
EVAL_CACHE_SIZE=1000
EVAL_MAX_WORKERS=4

# Evaluation Settings
DEFAULT_JUDGE_MODEL=gpt-4
CONFIDENCE_LEVEL=0.95
POSITION_BIAS_MITIGATION=true
```

### Configuration File

Create `config.yaml`:

```yaml
evaluation:
  default_judge: gpt-4
  temperature: 0.0
  max_retries: 3
  timeout: 30

  criteria_weights:
    accuracy: 0.3
    relevance: 0.3
    coherence: 0.2
    safety: 0.2

caching:
  enabled: true
  ttl: 3600
  max_size: 1000

logging:
  level: INFO
  format: json
  output: stdout
```

## Advanced Usage

### Custom Rubrics

```python
# Define custom evaluation rubric
{
  "tool": "evaluate_with_rubric",
  "arguments": {
    "response": "AI-generated content",
    "rubric": {
      "technical_accuracy": {
        "weight": 0.4,
        "criteria": "Factually correct technical details"
      },
      "clarity": {
        "weight": 0.3,
        "criteria": "Clear and understandable explanation"
      },
      "completeness": {
        "weight": 0.3,
        "criteria": "Covers all required aspects"
      }
    }
  }
}
```

### Batch Evaluation

```python
# Evaluate multiple samples in parallel
{
  "tool": "batch_evaluate",
  "arguments": {
    "samples": [
      {"id": "1", "response": "Response 1"},
      {"id": "2", "response": "Response 2"}
    ],
    "evaluation_type": "quality",
    "parallel_workers": 4
  }
}
```

### Multi-Judge Consensus

```python
# Use multiple judges for consensus
{
  "tool": "multi_judge_consensus",
  "arguments": {
    "response": "Content to evaluate",
    "judges": ["gpt-4", "claude-3", "gemini-pro"],
    "aggregation": "weighted_average",
    "confidence_threshold": 0.8
  }
}
```

## Example Workflows

### Complete Model Evaluation Pipeline

```bash
# 1. Quality evaluation
{
  "tool": "evaluate_single",
  "arguments": {
    "response": "Model output",
    "criteria": ["quality", "accuracy", "relevance"]
  }
}

# 2. Safety check
{
  "tool": "detect_harmful_content",
  "arguments": {
    "content": "Model output",
    "categories": ["all"]
  }
}

# 3. Bias detection
{
  "tool": "detect_demographic_bias",
  "arguments": {
    "responses": ["Model output"],
    "demographics": ["all"]
  }
}

# 4. Performance measurement
{
  "tool": "measure_latency",
  "arguments": {
    "operation": "inference",
    "num_samples": 100
  }
}

# 5. Generate report
{
  "tool": "generate_evaluation_report",
  "arguments": {
    "include_all_metrics": true
  }
}
```

### A/B Testing Workflow

```bash
# Compare two model versions
{
  "tool": "run_ab_test",
  "arguments": {
    "model_a": "v1.0",
    "model_b": "v2.0",
    "test_cases": [...],
    "metrics": ["quality", "latency", "safety"],
    "sample_size": 1000,
    "confidence_level": 0.95
  }
}
```

## Performance Optimization

- **Caching**: Results are cached to avoid redundant evaluations
- **Parallel Processing**: Multi-threaded evaluation for batch operations
- **Lazy Loading**: Models loaded on-demand
- **Connection Pooling**: Efficient API connection management
- **Async Operations**: Non-blocking I/O for improved throughput

## Troubleshooting

### API Key Issues

```bash
# Check API keys are set
echo $OPENAI_API_KEY
echo $ANTHROPIC_API_KEY

# Test API connectivity
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

### Memory Issues

```yaml
# Reduce cache size in config.yaml
caching:
  max_size: 100
  ttl: 600
```

### Timeout Errors

```yaml
# Increase timeouts in config.yaml
evaluation:
  timeout: 60
  max_retries: 5
```

## Related Resources

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [LLM Evaluation Best Practices](https://github.com/openai/evals)
- [Evaluation Server Source](https://github.com/IBM/mcp-context-forge/tree/main/mcp-servers/python/mcp_eval_server)

## Author

**Mihai Criveti**

- GitHub: [cmihai](https://github.com/cmihai)
- Project: IBM ContextForge
