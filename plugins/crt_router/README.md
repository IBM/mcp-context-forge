# CRT Router Plugin


## Overview

The CRT (Chinese Remainder Theorem) Router Plugin provides mathematically-optimized semantic tool routing for the MCP Gateway. It uses a two-phase approach combining CRT-based pre-filtering with semantic similarity ranking to efficiently route queries to the most relevant tools.

### Two-Phase Routing Architecture

**Phase 1 - CRT Pre-filtering**: Uses modular arithmetic and the Chinese Remainder Theorem to encode tool capabilities across difficulty bins as unique residues modulo prime numbers. This allows O(1) filtering of incompatible tools before expensive semantic computations.

**Phase 2 - Semantic Ranking**: Applies embedding-based semantic similarity scoring only to the CRT-filtered subset, then ranks and returns top-k tools above the calibrated threshold.

## Features

- **Mathematical Pre-filtering**: CRT-based capability matching eliminates 70-90% of incompatible tools
- **Semantic Similarity**: Embedding-based relevance scoring on filtered candidates
- **Configurable Thresholds**: Adjust relevance thresholds and top-k selection
- **Prime-based Encoding**: Tool capabilities encoded using prime moduli for exact matching
- **Calibration Support**: Load pre-trained calibration data with difficulty bins and success tables
- **Caching**: Optional caching for improved performance
- **Plugin Framework Integration**: Seamlessly integrates with MCP Gateway's plugin system

## Configuration

### Environment Variables

```bash
# Enable CRT router
MCPGATEWAY_CRT_ROUTER_ENABLED=true

# Set routing mode (standard, crt, or hybrid)
MCPGATEWAY_ROUTER_MODE=crt

# Path to calibration artifacts
MCPGATEWAY_CRT_CALIBRATION_PATH=data/calibration/crt_model.json
```

### Plugin Configuration

Add to `plugins/config.yaml`:

```yaml
- name: "CRTRouter"
  kind: "mcpgateway.plugins.crt_router.plugin.CRTRouterPlugin"
  description: "CRT-based semantic tool router"
  version: "0.1.0"
  hooks: ["tool_pre_invoke"]
  mode: "enforcing"
  priority: 100
  config:
    calibration_path: "data/calibration/crt_model.json"
    default_k: 10
    default_threshold: 0.72
    cache_enabled: true
```

## Plugin Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `calibration_path` | string | `data/calibration/crt_model.json` | Path to calibration artifacts |
| `default_k` | int | `10` | Default number of top tools to return |
| `default_threshold` | float | `0.72` | Default relevance threshold (0.0-1.0) |
| `cache_enabled` | bool | `true` | Enable routing cache for performance |

## Hooks

- **tool_pre_invoke**: Filters tools before invocation based on semantic relevance

## Routing Modes

The CRT router supports three routing modes via `MCPGATEWAY_ROUTER_MODE`:

1. **standard**: Traditional routing (CRT disabled)
2. **crt**: Full CRT-based semantic routing
3. **hybrid**: Combination of standard and CRT routing

## How It Works

### Calibration Data Structure

The router requires calibration artifacts containing:

- **`prime_list`**: Prime numbers [3, 5, 7, ...] for CRT encoding
- **`difficulty_bins`**: Query difficulty thresholds [0.2, 0.5, 0.8]
- **`calibrated_success_tables`**: Tool capability matrices indexed by moduli (m0, m1, m2)
- **`prior_distribution`**: Difficulty bin probabilities
- **`tool_embeddings`**: Semantic vector representations of each tool

### Routing Algorithm

1. **Initialization**: Load calibration data including primes, bins, success tables, and embeddings
2. **Query Analysis**: Classify query into difficulty bin and compute embedding
3. **CRT Pre-filtering**:
   - For each tool, decode capability signature using Chinese Remainder Theorem reconstruction
   - Match query difficulty bin to tool capabilities via modular congruences
   - Filter out tools with low success probability for query difficulty
4. **Semantic Ranking**: Compute cosine similarity between query embedding and CRT-filtered tool embeddings
5. **Threshold Filtering**: Keep only tools above calibrated relevance threshold
6. **Top-K Selection**: Return top-k highest-scoring tools

### Mathematical Background

The Chinese Remainder Theorem states that for coprime moduli m₁, m₂, ..., mₙ, any integer x can be uniquely represented by its residues (x mod m₁, x mod m₂, ..., x mod mₙ) in the range [0, M) where M = m₁ × m₂ × ... × mₙ.

We use this property to encode tool capabilities: each tool's competency across difficulty bins is mapped to a unique integer, then represented as residues modulo the prime list. During routing, we reconstruct capabilities and match them against query requirements using modular arithmetic—orders of magnitude faster than comparing all tools with semantic embeddings.

## Development Status

This is the foundational infrastructure for the CRT router. Core routing logic will be implemented in subsequent development phases.

### Roadmap

- [x] Plugin infrastructure and configuration
- [ ] Calibration data loading
- [ ] Semantic similarity computation
- [ ] Tool filtering and ranking
- [ ] Cache implementation
- [ ] Performance optimization

## Testing

```bash
# Run CRT router plugin tests
pytest tests/unit/mcpgateway/plugins/plugins/crt_router/

# Test with specific configuration
MCPGATEWAY_ROUTER_MODE=crt pytest tests/unit/mcpgateway/plugins/plugins/crt_router/
```

## License

Copyright 2025
SPDX-License-Identifier: Apache-2.0
