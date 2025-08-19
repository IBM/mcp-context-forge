# MCP Evaluation Server

> Author: Mihai Criveti

A comprehensive MCP server for agent performance evaluation, prompt effectiveness testing, and LLM behavior analysis using LLM-as-a-judge techniques.

## Overview

The MCP Evaluation Server provides a complete suite of evaluation tools accessible via the Model Context Protocol (MCP). It combines rule-based metrics with LLM-as-a-judge approaches to offer:

- **LLM-as-a-Judge Evaluation**: Using GPT-4, GPT-3.5, and Azure OpenAI models
- **Prompt Quality Assessment**: Clarity, consistency, completeness, and relevance analysis
- **Agent Performance Evaluation**: Tool usage, task completion, reasoning analysis
- **Response Quality Metrics**: Factuality, coherence, toxicity detection
- **Evaluation Workflows**: End-to-end evaluation suites with statistical analysis
- **Judge Calibration**: Meta-evaluation and rubric optimization

## Features

### 🤖 LLM-as-a-Judge Tools
- Single response evaluation with customizable criteria
- Pairwise comparison with position bias mitigation
- Multi-response ranking using tournament or scoring methods
- Reference-based evaluation against gold standards
- Multi-judge consensus evaluation

### 📝 Prompt Evaluation Tools
- **Clarity Analysis**: Rule-based and LLM-based clarity assessment
- **Consistency Testing**: Multi-run consistency across temperature settings
- **Completeness Measurement**: Coverage of expected components
- **Relevance Assessment**: Semantic alignment using embeddings

### 🛠️ Agent Evaluation Tools
- **Tool Usage Evaluation**: Selection accuracy, sequence correctness, parameter validation
- **Task Completion Analysis**: Success criteria evaluation with partial credit
- **Reasoning Assessment**: Decision-making quality and logical coherence
- **Performance Benchmarking**: Comprehensive capability testing

### 🔍 Quality Assessment Tools
- **Factuality Checking**: Claims verification against knowledge bases
- **Coherence Analysis**: Logical flow and consistency evaluation
- **Toxicity Detection**: Harmful content identification with bias analysis

### 🔄 Workflow Management
- **Evaluation Suites**: Customizable multi-step evaluation pipelines
- **Results Comparison**: Statistical analysis across evaluation runs
- **Progress Tracking**: Real-time execution monitoring

### 📊 Judge Calibration
- **Agreement Testing**: Inter-judge and human-judge correlation analysis
- **Rubric Optimization**: Automatic tuning for better alignment
- **Bias Detection**: Systematic bias pattern identification

## Installation

1. Clone or download the server files
2. Install dependencies:

```bash
pip install -e .
```

3. Set up API keys:

```bash
# For OpenAI
export OPENAI_API_KEY="your-openai-api-key"

# For Azure OpenAI
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_KEY="your-azure-key"
```

## Quick Start

### Running the Server

```bash
# Run as MCP server
python -m mcp_eval_server.server

# Or using the entry point
mcp-eval-server
```

### Basic Usage Examples

#### 1. Evaluate Response Quality

```python
# Example tool call via MCP client
result = await mcp_client.call_tool("judge.evaluate_response", {
    "response": "The capital of France is Paris, which is located in the north-central part of the country.",
    "criteria": [
        {
            "name": "accuracy",
            "description": "Factual correctness of the information",
            "scale": "1-5",
            "weight": 0.4
        },
        {
            "name": "completeness",
            "description": "How thoroughly the question is answered",
            "scale": "1-5",
            "weight": 0.3
        },
        {
            "name": "clarity",
            "description": "Clarity and understandability",
            "scale": "1-5",
            "weight": 0.3
        }
    ],
    "rubric": {
        "criteria": [],
        "scale_description": {
            "1": "Very poor",
            "2": "Poor",
            "3": "Average",
            "4": "Good",
            "5": "Excellent"
        }
    },
    "judge_model": "gpt-4"
})
```

#### 2. Compare Two Responses

```python
comparison = await mcp_client.call_tool("judge.pairwise_comparison", {
    "response_a": "Paris is the capital of France.",
    "response_b": "The capital city of France is Paris, located in the Île-de-France region.",
    "criteria": [
        {
            "name": "informativeness",
            "description": "Amount of useful information provided",
            "scale": "1-5",
            "weight": 1.0
        }
    ],
    "judge_model": "gpt-4",
    "position_bias_mitigation": True
})
```

#### 3. Evaluate Prompt Clarity

```python
clarity_result = await mcp_client.call_tool("prompt.evaluate_clarity", {
    "prompt_text": "Write a summary of the main points in this article about climate change.",
    "target_model": "gpt-4",
    "domain_context": "scientific_writing"
})
```

#### 4. Analyze Agent Tool Usage

```python
tool_analysis = await mcp_client.call_tool("agent.evaluate_tool_use", {
    "agent_trace": {
        "tool_calls": [
            {
                "tool_name": "web_search",
                "parameters": {"query": "climate change effects"},
                "success": True
            },
            {
                "tool_name": "summarizer",
                "parameters": {"text": "search results..."},
                "success": True
            }
        ]
    },
    "expected_tools": ["web_search", "summarizer"],
    "tool_sequence_matters": True
})
```

#### 5. Create and Run Evaluation Suite

```python
# Create evaluation suite
suite = await mcp_client.call_tool("workflow.create_evaluation_suite", {
    "suite_name": "comprehensive_response_eval",
    "evaluation_steps": [
        {
            "tool": "judge.evaluate_response",
            "weight": 0.4,
            "parameters": {
                "criteria": [{"name": "quality", "description": "Overall quality", "scale": "1-5", "weight": 1.0}],
                "rubric": {"criteria": [], "scale_description": {"1": "Poor", "5": "Excellent"}}
            }
        },
        {
            "tool": "quality.evaluate_factuality",
            "weight": 0.3
        },
        {
            "tool": "quality.measure_coherence",
            "weight": 0.3
        }
    ],
    "success_thresholds": {
        "overall": 0.8,
        "quality.evaluate_factuality": 0.9
    }
})

# Run evaluation
results = await mcp_client.call_tool("workflow.run_evaluation", {
    "suite_id": suite["suite_id"],
    "test_data": {
        "response": "Your response text here...",
        "context": "Additional context..."
    }
})
```

## Configuration

### Model Configuration

Edit `config/models.yaml` to configure available judge models:

```yaml
models:
  openai:
    gpt-4:
      provider: "openai"
      model_name: "gpt-4"
      api_key_env: "OPENAI_API_KEY"
      default_temperature: 0.3
      max_tokens: 2000

  azure:
    gpt-4-azure:
      provider: "azure"
      deployment_name: "gpt-4"
      api_base_env: "AZURE_OPENAI_ENDPOINT"
      api_key_env: "AZURE_OPENAI_KEY"
      api_version: "2024-02-01"
```

### Custom Rubrics

Create custom evaluation rubrics in `config/rubrics.yaml`:

```yaml
rubrics:
  my_custom_rubric:
    name: "Custom Evaluation"
    criteria:
      - name: "creativity"
        description: "Originality and creative thinking"
        scale: "1-10"
        weight: 0.6
      - name: "practicality"
        description: "Real-world applicability"
        scale: "1-10"
        weight: 0.4
```

### Benchmarks

Define custom benchmarks in `config/benchmarks.yaml`:

```yaml
benchmarks:
  my_benchmark:
    name: "Custom Skills Test"
    tasks:
      - name: "problem_solving"
        type: "analytical_reasoning"
        difficulty: "medium"
        expected_tools: ["analyzer", "synthesizer"]
```

## Available Tools

### Judge Tools
- `judge.evaluate_response` - Single response evaluation
- `judge.pairwise_comparison` - Compare two responses
- `judge.rank_responses` - Rank multiple responses
- `judge.evaluate_with_reference` - Reference-based evaluation

### Prompt Tools
- `prompt.evaluate_clarity` - Assess prompt clarity
- `prompt.test_consistency` - Test consistency across runs
- `prompt.measure_completeness` - Check component coverage
- `prompt.assess_relevance` - Measure semantic alignment

### Agent Tools
- `agent.evaluate_tool_use` - Analyze tool usage patterns
- `agent.measure_task_completion` - Evaluate task success
- `agent.analyze_reasoning` - Assess decision-making quality
- `agent.benchmark_performance` - Run comprehensive benchmarks

### Quality Tools
- `quality.evaluate_factuality` - Check factual accuracy
- `quality.measure_coherence` - Analyze logical flow
- `quality.assess_toxicity` - Detect harmful content

### Workflow Tools
- `workflow.create_evaluation_suite` - Define evaluation pipelines
- `workflow.run_evaluation` - Execute evaluation suites
- `workflow.compare_evaluations` - Compare results across runs

### Calibration Tools
- `calibration.test_judge_agreement` - Test inter-judge agreement
- `calibration.optimize_rubrics` - Optimize evaluation rubrics

### Server Tools
- `server.get_available_judges` - List available judge models
- `server.get_evaluation_suites` - List created evaluation suites
- `server.get_evaluation_results` - Retrieve stored results
- `server.get_cache_stats` - View caching statistics

## Best Practices

### Judge Selection
- Use **GPT-4** or **GPT-4-Turbo** for high-stakes evaluations
- Use **GPT-3.5-Turbo** for cost-effective batch processing
- Consider **multi-judge consensus** for critical assessments

### Evaluation Design
- Use **1-5 integer scales** for consistent scoring
- Enable **chain-of-thought reasoning** for complex evaluations
- Implement **position bias mitigation** for comparisons
- **Cache results** to reduce costs and latency

### Rubric Development
- Start with standard rubrics and customize as needed
- Use **specific, actionable criteria descriptions**
- **Weight criteria** based on importance
- **Test and iterate** rubric effectiveness

### Performance Optimization
- Enable **parallel execution** for evaluation suites
- Use **appropriate caching strategies**
- **Batch similar evaluations** when possible
- **Monitor judge performance** and costs

## Integration Examples

### With LangChain Agents

```python
from langchain.agents import initialize_agent
from mcp import Client

# Initialize MCP client for evaluation
mcp_client = Client("mcp-eval-server")

# Your LangChain agent
agent = initialize_agent(tools, llm, agent="zero-shot-react-description")

# Run agent and capture trace
result = agent.run("Analyze climate change impacts")
agent_trace = agent.get_execution_trace()  # Custom method

# Evaluate agent performance
evaluation = await mcp_client.call_tool("agent.evaluate_tool_use", {
    "agent_trace": agent_trace,
    "expected_tools": ["web_search", "data_analyzer"]
})
```

### With Custom Applications

```python
class MyEvaluationPipeline:
    def __init__(self):
        self.mcp_client = Client("mcp-eval-server")

    async def evaluate_model_output(self, prompt, response):
        # Multi-faceted evaluation
        quality_eval = await self.mcp_client.call_tool("judge.evaluate_response", {
            "response": response,
            "criteria": self.get_quality_criteria(),
            "rubric": self.get_standard_rubric()
        })

        factuality_eval = await self.mcp_client.call_tool("quality.evaluate_factuality", {
            "response": response
        })

        return {
            "quality": quality_eval,
            "factuality": factuality_eval,
            "overall_score": (quality_eval["overall_score"] + factuality_eval["factuality_score"]) / 2
        }
```

## Troubleshooting

### Common Issues

**API Key Errors**
```
Error: API key not found in environment variable: OPENAI_API_KEY
```
Solution: Ensure environment variables are properly set.

**Judge Model Not Found**
```
Error: Judge model gpt-4 not configured
```
Solution: Check `config/models.yaml` and ensure the model is properly configured.

**Memory Issues with Large Evaluations**
```
Error: Out of memory during batch evaluation
```
Solution: Reduce `max_concurrent` parameter or enable disk caching.

### Performance Tips

1. **Use caching** for repeated evaluations
2. **Batch similar requests** when possible
3. **Choose appropriate judge models** for your use case
4. **Monitor and optimize** evaluation suite complexity

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## License

Apache 2 License - see LICENSE file for details.

## Support

For issues and questions:
- Create an issue in the repository
- Check the troubleshooting section
- Review the configuration files for examples

---

**Note**: This server requires API keys for OpenAI or Azure OpenAI services. Ensure you have appropriate access and have set up billing as needed.
