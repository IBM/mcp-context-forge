# Synthetic Data FastMCP Server

Generate high-quality synthetic tabular datasets on demand using the FastMCP 2 framework. The
server ships with curated presets, configurable column primitives, deterministic seeding, and
multiple output formats to accelerate prototyping, testing, and analytics workflows.

## Features

- FastMCP 2 server with stdio and native HTTP transports
- Ten+ column primitives including numeric, boolean, categorical, temporal, text, and Faker-backed entities
- Curated presets for customer profiles, transactions, and IoT telemetry
- Deterministic generation with per-request seeds and Faker locale overrides
- Built-in dataset catalog with summaries, preview rows, and reusable resources (CSV / JSONL)
- In-memory cache for recently generated datasets with LRU eviction
- Comprehensive unit tests and ready-to-use Makefile/Containerfile

## Quick Start

```bash
uv pip install -e .[dev]
python -m synthetic_data_server.server_fastmcp
```

Invoke over HTTP:

```bash
python -m synthetic_data_server.server_fastmcp --transport http --host 0.0.0.0 --port 8000
```

## Available Tools

| Tool | Description |
| --- | --- |
| `list_presets` | Return bundled presets and their column definitions |
| `generate_dataset` | Generate a synthetic dataset, compute summary stats, and persist artifacts |
| `list_generated_datasets` | Enumerate cached datasets with metadata |
| `summarize_dataset` | Retrieve cached summary statistics for a dataset |
| `retrieve_dataset` | Download persisted CSV/JSONL artifacts |

### Example `generate_dataset` Payload

```json
{
  "rows": 1000,
  "preset": "customer_profiles",
  "seed": 123,
  "preview_rows": 5,
  "output_formats": ["csv", "jsonl"],
  "include_summary": true
}
```

### Sample Response

```json
{
  "dataset_id": "4f86a6a9-9d05-4b86-8f25-2ab861924c70",
  "rows": 1000,
  "preview": [{"customer_id": "...", "full_name": "..."}],
  "summary": {
    "row_count": 1000,
    "column_count": 7,
    "columns": [{"name": "lifetime_value", "stats": {"mean": 9450.71}}]
  },
  "metadata": {
    "preset": "customer_profiles",
    "seed": 123,
    "output_formats": ["csv", "jsonl"],
    "created_at": "2025-01-15T12:45:21.000000+00:00"
  },
  "resources": {
    "csv": "dataset://4f86a6a9-9d05-4b86-8f25-2ab861924c70.csv"
  }
}
```

## Makefile Targets

- `make install` — Install in editable mode with development dependencies (requires `uv`)
- `make lint` — Run Ruff + MyPy
- `make test` — Execute pytest suite with coverage
- `make dev` — Run the FastMCP server over stdio
- `make serve-http` — Run with the built-in HTTP transport on `/mcp`
- `make serve-sse` — Expose an SSE bridge using `mcpgateway.translate`

## Container Usage

Build and run the container image:

```bash
docker build -t synthetic-data-server .
docker run --rm -p 8000:8000 synthetic-data-server python -m synthetic_data_server.server_fastmcp --transport http --host 0.0.0.0 --port 8000
```

## Testing

```bash
make test
```

The unit tests cover deterministic generation, preset usage, and artifact persistence.

## MCP Client Configuration

```json
{
  "command": "python",
  "args": ["-m", "synthetic_data_server.server_fastmcp"]
}
```

For HTTP clients, invoke `make serve-http` and target `http://localhost:8000/mcp/`.
