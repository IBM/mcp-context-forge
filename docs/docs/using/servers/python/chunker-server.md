# Chunker Server

## Overview

The Chunker MCP Server provides advanced text chunking capabilities with multiple strategies and configurable options. It supports recursive, semantic, sentence-based, fixed-size, and markdown-aware chunking methods to meet different text processing needs. The server is now available in both original MCP and FastMCP implementations, with FastMCP offering enhanced type safety and automatic validation.

### Key Features

- **Multiple Chunking Strategies**: Recursive, semantic, sentence-based, fixed-size, markdown-aware
- **Markdown Support**: Intelligent markdown chunking respecting header structure
- **Configurable Parameters**: Chunk size, overlap, separators, and more
- **Text Analysis**: Analyze text to recommend optimal chunking strategy
- **Library Integration**: Supports LangChain text splitters, NLTK, and spaCy
- **FastMCP Implementation**: Modern decorator-based tool definitions with automatic validation

## Quick Start

### Installation

```bash
# Basic installation with core functionality
make install

# With NLP libraries (NLTK and spaCy)
make install-nlp

# With LangChain support
make install-langchain

# Full installation (recommended - includes all features)
make install-full
```

### Running the Server

```bash
# FastMCP server (recommended)
make dev-fastmcp

# Original MCP server
make dev

# HTTP bridge for REST API access
make serve-http-fastmcp  # FastMCP version
make serve-http          # Original version
```

## Available Tools

### chunk_text
Universal text chunking with multiple strategies.

**Parameters:**

- `text` (required): Text to chunk
- `chunk_size`: Maximum chunk size (default: 1000, range: 100-100000)
- `chunk_overlap`: Overlap between chunks (default: 200)
- `chunking_strategy`: "recursive", "semantic", "sentence", or "fixed_size"
- `separators`: Custom separators for splitting
- `preserve_structure`: Preserve document structure when possible

### chunk_markdown
Markdown-aware chunking that respects header structure.

**Parameters:**

- `text` (required): Markdown text to chunk
- `headers_to_split_on`: Headers to use as boundaries (default: ["#", "##", "###"])
- `chunk_size`: Maximum chunk size (default: 1000)
- `chunk_overlap`: Overlap between chunks (default: 100)

### semantic_chunk
Content-aware chunking based on semantic boundaries.

**Parameters:**

- `text` (required): Text to chunk
- `min_chunk_size`: Minimum chunk size (default: 200)
- `max_chunk_size`: Maximum chunk size (default: 2000)
- `similarity_threshold`: Threshold for semantic grouping (default: 0.8)

### sentence_chunk
Sentence-based chunking with configurable grouping.

**Parameters:**

- `text` (required): Text to chunk
- `sentences_per_chunk`: Sentences per chunk (default: 5, range: 1-50)
- `overlap_sentences`: Overlapping sentences (default: 1, range: 0-10)

### fixed_size_chunk
Fixed-size chunking with word boundary preservation.

**Parameters:**

- `text` (required): Text to chunk
- `chunk_size`: Fixed chunk size (default: 1000)
- `overlap`: Overlap between chunks (default: 0)
- `split_on_word_boundary`: Avoid breaking words (default: true)

### analyze_text
Analyze text characteristics and get chunking recommendations.

**Parameters:**

- `text` (required): Text to analyze

**Returns:**

- Text statistics (length, word count, paragraph count)
- Structure detection (markdown headers, lists, etc.)
- Recommended chunking strategies with parameters

### get_strategies
Get information about available chunking strategies and libraries.

**Returns:**

- Available strategies and their descriptions
- Best use cases for each strategy
- Library availability status

## Configuration

### MCP Client Configuration

#### FastMCP Server (Recommended)
```json
{
  "mcpServers": {
    "chunker": {
      "command": "python",
      "args": ["-m", "chunker_server.server_fastmcp"]
    }
  }
}
```

#### Original Server
```json
{
  "mcpServers": {
    "chunker": {
      "command": "python",
      "args": ["-m", "chunker_server.server"]
    }
  }
}
```

## Examples

### Basic Text Chunking
```json
{
  "text": "Your long text here...",
  "chunk_size": 1000,
  "chunk_overlap": 200,
  "chunking_strategy": "recursive"
}
```

### Markdown Documentation Processing
```json
{
  "text": "# API Reference\n\n## Authentication\n\n...",
  "headers_to_split_on": ["#", "##"],
  "chunk_size": 2000,
  "chunk_overlap": 100
}
```

### Semantic Chunking for Articles
```json
{
  "text": "Article content with multiple paragraphs...",
  "min_chunk_size": 500,
  "max_chunk_size": 3000,
  "similarity_threshold": 0.7
}
```

### Preparing Text for Embeddings
```json
{
  "text": "Text to be embedded...",
  "chunk_size": 512,
  "chunk_overlap": 50,
  "chunking_strategy": "recursive"
}
```

## Integration

### With MCP Gateway

To integrate with MCP Gateway, expose the server over HTTP:

```bash
# Start the chunker server via HTTP
make serve-http-fastmcp

# Register with MCP Gateway
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "chunker-server",
    "url": "http://localhost:9000",
    "description": "Text chunking server"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def chunk_text():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "chunker_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the client
            await session.initialize()

            # List available tools
            tools = await session.list_tools()

            # Call chunk_text tool
            result = await session.call_tool("chunk_text", {
                "text": "Your text here...",
                "chunk_size": 1000,
                "chunking_strategy": "recursive"
            })

            print(result.content[0].text)

asyncio.run(chunk_text())
```

### Response Format

All tools return a JSON response with:

- `success`: Boolean indicating success/failure
- `strategy`: The chunking strategy used
- `chunks`: Array of text chunks
- `chunk_count`: Number of chunks created
- Additional metadata specific to each strategy

**Example Response:**
```json
{
  "success": true,
  "strategy": "recursive",
  "chunks": [
    "First chunk of text...",
    "Second chunk of text..."
  ],
  "chunk_count": 2,
  "total_length": 2000,
  "average_chunk_size": 1000
}
```

## Chunking Strategies Guide

### Recursive Chunking
- **Best for**: General text, mixed content
- **How it works**: Hierarchically splits using multiple separators
- **Use cases**: Books, articles, documentation

### Markdown Chunking
- **Best for**: Markdown documents, structured content
- **How it works**: Splits on markdown headers, preserves structure
- **Use cases**: Technical documentation, READMEs, wiki pages

### Semantic Chunking
- **Best for**: Articles, essays, narrative text
- **How it works**: Groups content by semantic boundaries
- **Use cases**: Research papers, blog posts, news articles

### Sentence Chunking
- **Best for**: Precise sentence-level processing
- **How it works**: Groups sentences with optional overlap
- **Use cases**: Translation, summarization, sentence analysis

### Fixed-Size Chunking
- **Best for**: Uniform chunk sizes, simple splitting
- **How it works**: Splits at fixed character counts
- **Use cases**: Token limits, consistent processing windows
