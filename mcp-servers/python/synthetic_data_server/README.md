# Synthetic Data FastMCP Server

> Author: Mihai Criveti

Generate high-quality synthetic tabular datasets on demand using the FastMCP 2 framework. The
server ships with curated presets, configurable column primitives, deterministic seeding, and
multiple output formats to accelerate prototyping, testing, and analytics workflows.

## Features

- FastMCP 2 server with stdio and native HTTP transports
- 12+ column types: integer, float, boolean, categorical, date, datetime, text, pattern, name, email, address, company, UUID
- Curated presets: customer profiles, transactions, IoT telemetry, products catalog, employee records
- Pattern-based string generation for SKUs, product codes, employee IDs (e.g., "PROD-{:04d}")
- Flexible text generation modes: word, sentence, or paragraph
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
python -m synthetic_data_server.server_fastmcp --transport http --host localhost --port 9018
```

## Available Column Types

| Type | Description | Key Parameters |
| --- | --- | --- |
| `integer` | Integer values within a range | `minimum`, `maximum`, `step` |
| `float` | Floating-point numbers | `minimum`, `maximum`, `precision` |
| `boolean` | True/false values | `true_probability` |
| `categorical` | Random selection from list | `categories`, `weights` (optional) |
| `date` | Date values | `start_date`, `end_date`, `date_format` |
| `datetime` | Timestamp values | `start_datetime`, `end_datetime`, `output_format` |
| `text` | Generated text content | `mode` (word/sentence/paragraph), `word_count`, `min_sentences`, `max_sentences` |
| `pattern` | Formatted strings with patterns | `pattern` (e.g., "SKU-{:05d}"), `sequence_start`, `random_choices` |
| `name` | Realistic person names | `locale` (optional) |
| `email` | Email addresses | `locale` (optional) |
| `address` | Street addresses | `locale` (optional) |
| `company` | Company names | `locale` (optional) |
| `uuid` | UUID v4 identifiers | `uppercase` |

All column types support `nullable` and `null_probability` for generating null values.

## Available Presets

- **customer_profiles**: Customer data with IDs, names, emails, signup dates, and lifetime values
- **transactions**: Financial transactions with amounts, timestamps, statuses, and payment methods
- **iot_telemetry**: IoT sensor readings with device IDs, timestamps, temperatures, and battery levels
- **products**: Product catalog with SKUs, names, prices, categories, and stock status
- **employees**: Employee records with IDs, names, departments, salaries, and hire dates

## Available Tools

| Tool | Description |
| --- | --- |
| `list_presets` | Return bundled presets and their column definitions |
| `generate_dataset` | Generate a synthetic dataset, compute summary stats, and persist artifacts |
| `list_generated_datasets` | Enumerate cached datasets with metadata |
| `summarize_dataset` | Retrieve cached summary statistics for a dataset |
| `retrieve_dataset` | Download persisted CSV/JSONL artifacts |

### Example Requests

#### Using a Preset
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

#### Custom Dataset with Pattern Column
```json
{
  "rows": 500,
  "columns": [
    {
      "name": "product_id",
      "type": "pattern",
      "pattern": "SKU-{:05d}",
      "sequence_start": 10000
    },
    {
      "name": "product_name",
      "type": "text",
      "mode": "word",
      "word_count": 3
    },
    {
      "name": "price",
      "type": "float",
      "minimum": 9.99,
      "maximum": 999.99,
      "precision": 2
    },
    {
      "name": "in_stock",
      "type": "boolean",
      "true_probability": 0.8
    }
  ],
  "seed": 456
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
docker run --rm -p 9018:9018 synthetic-data-server python -m synthetic_data_server.server_fastmcp --transport http --host 0.0.0.0 --port 9018
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

For HTTP clients, invoke `make serve-http` and target `http://localhost:9018/mcp/`.
