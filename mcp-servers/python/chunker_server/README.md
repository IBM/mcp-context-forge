# Chunker MCP Server

> Author: Mihai Criveti

Advanced text chunking server with multiple strategies and configurable options. Now with **FastMCP implementation** for enhanced type safety and automatic validation!

## Features

- **Multiple Chunking Strategies**: Recursive, semantic, sentence-based, fixed-size, markdown-aware
- **Markdown Support**: Intelligent markdown chunking respecting header structure
- **Configurable Parameters**: Chunk size, overlap, separators, and more
- **Text Analysis**: Analyze text to recommend optimal chunking strategy
- **Library Integration**: Supports LangChain text splitters, NLTK, and spaCy
- **FastMCP Implementation**: Modern decorator-based tool definitions with automatic validation

## Installation

### Basic Installation
```bash
make install  # Core functionality with FastMCP
```

### With NLP Libraries
```bash
make install-nlp  # Includes NLTK and spaCy
```

### With LangChain Support
```bash
make install-langchain  # Includes LangChain text splitters
```

### Full Installation (Recommended)
```bash
make install-full  # All features including FastMCP, NLP, and LangChain
```

## Usage

### Running with FastMCP (Recommended)

```bash
make dev-fastmcp  # Run FastMCP server
```

### Running Original MCP Implementation

```bash
make dev  # Run original MCP server
```

### HTTP Bridge

Expose the server over HTTP for REST API access:

```bash
# FastMCP server over HTTP
make serve-http-fastmcp

# Original server over HTTP
make serve-http
```

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

**Example:**
```json
{
  "text": "Your long text here...",
  "chunk_size": 1000,
  "chunk_overlap": 200,
  "chunking_strategy": "recursive"
}
```

### chunk_markdown
Markdown-aware chunking that respects header structure.

**Parameters:**
- `text` (required): Markdown text to chunk
- `headers_to_split_on`: Headers to use as boundaries (default: ["#", "##", "###"])
- `chunk_size`: Maximum chunk size (default: 1000)
- `chunk_overlap`: Overlap between chunks (default: 100)

**Example:**
```json
{
  "text": "# Title\n\n## Section 1\n\nContent...",
  "headers_to_split_on": ["#", "##"],
  "chunk_size": 1500
}
```

### semantic_chunk
Content-aware chunking based on semantic boundaries.

**Parameters:**
- `text` (required): Text to chunk
- `min_chunk_size`: Minimum chunk size (default: 200)
- `max_chunk_size`: Maximum chunk size (default: 2000)
- `similarity_threshold`: Threshold for semantic grouping (default: 0.8)

**Example:**
```json
{
  "text": "Your article or essay text...",
  "min_chunk_size": 300,
  "max_chunk_size": 2500
}
```

### sentence_chunk
Sentence-based chunking with configurable grouping.

**Parameters:**
- `text` (required): Text to chunk
- `sentences_per_chunk`: Sentences per chunk (default: 5, range: 1-50)
- `overlap_sentences`: Overlapping sentences (default: 1, range: 0-10)

**Example:**
```json
{
  "text": "First sentence. Second sentence. Third sentence...",
  "sentences_per_chunk": 3,
  "overlap_sentences": 1
}
```

### fixed_size_chunk
Fixed-size chunking with word boundary preservation.

**Parameters:**
- `text` (required): Text to chunk
- `chunk_size`: Fixed chunk size (default: 1000)
- `overlap`: Overlap between chunks (default: 0)
- `split_on_word_boundary`: Avoid breaking words (default: true)

**Example:**
```json
{
  "text": "Your text content here...",
  "chunk_size": 500,
  "split_on_word_boundary": true
}
```

### analyze_text
Analyze text characteristics and get chunking recommendations.

**Parameters:**
- `text` (required): Text to analyze

**Returns:**
- Text statistics (length, word count, paragraph count)
- Structure detection (markdown headers, lists, etc.)
- Recommended chunking strategies with parameters

**Example:**
```json
{
  "text": "# Document\n\nParagraph 1...\n\n## Section\n\nParagraph 2..."
}
```

### get_strategies
Get information about available chunking strategies and libraries.

**Returns:**
- Available strategies and their descriptions
- Best use cases for each strategy
- Library availability status

## Chunking Strategies

### Recursive Chunking
- **Best for**: General text, mixed content
- **How it works**: Hierarchically splits using multiple separators
- **Parameters**: chunk_size, chunk_overlap, separators

### Markdown Chunking
- **Best for**: Markdown documents, structured content
- **How it works**: Splits on markdown headers, preserves structure
- **Parameters**: headers_to_split_on, chunk_size, chunk_overlap

### Semantic Chunking
- **Best for**: Articles, essays, narrative text
- **How it works**: Groups content by semantic boundaries
- **Parameters**: min_chunk_size, max_chunk_size, similarity_threshold

### Sentence Chunking
- **Best for**: Precise sentence-level processing
- **How it works**: Groups sentences with optional overlap
- **Parameters**: sentences_per_chunk, overlap_sentences

### Fixed-Size Chunking
- **Best for**: Uniform chunk sizes, simple splitting
- **How it works**: Splits at fixed character counts
- **Parameters**: chunk_size, overlap, split_on_word_boundary

## FastMCP vs Original Implementation

### Why Choose FastMCP?

1. **Type-Safe Parameters**: Automatic validation with Pydantic Field constraints
2. **Cleaner Code**: Decorator-based tool definitions (`@mcp.tool`)
3. **Better Error Handling**: Built-in exception management
4. **Automatic Schema Generation**: No manual JSON schema definitions
5. **Modern Async Patterns**: Improved async/await implementation

### Feature Comparison

| Feature | Original MCP | FastMCP |
|---------|-------------|---------|
| Tool Definition | Manual JSON schemas | `@mcp.tool` decorator |
| Parameter Validation | Manual checks | Automatic Pydantic validation |
| Type Hints | Basic | Full typing support |
| Error Handling | Manual try/catch | Built-in error management |
| Code Structure | Procedural | Object-oriented with decorators |

## Examples

### Chunking a Large Document
```python
{
  "text": "Your 10,000 word document...",
  "chunk_size": 1000,
  "chunk_overlap": 200,
  "chunking_strategy": "recursive",
  "separators": ["\n\n", "\n", ". ", " "]
}
```

### Processing Markdown Documentation
```python
{
  "text": "# API Reference\n\n## Authentication\n\n...",
  "headers_to_split_on": ["#", "##"],
  "chunk_size": 2000,
  "chunk_overlap": 100
}
```

### Semantic Chunking for Articles
```python
{
  "text": "Article content with multiple paragraphs...",
  "min_chunk_size": 500,
  "max_chunk_size": 3000,
  "similarity_threshold": 0.7
}
```

### Preparing Text for Embeddings
```python
{
  "text": "Text to be embedded...",
  "chunk_size": 512,  # Typical embedding model limit
  "chunk_overlap": 50,
  "chunking_strategy": "recursive"
}
```

## Response Format

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

## Development

### Running Tests
```bash
make test
```

### Formatting Code
```bash
make format
```

### Linting
```bash
make lint
```

### Example Chunking
```bash
make example-chunk
```

## Troubleshooting

### Missing Libraries

If certain strategies aren't available:

```bash
# Check available strategies
python -c "from chunker_server.server_fastmcp import chunker; print(chunker.get_chunking_strategies())"

# Install missing dependencies
pip install langchain-text-splitters  # For advanced chunking
pip install nltk  # For sentence tokenization
pip install spacy  # For NLP processing
```

### Performance Tips

- For large documents (>10MB), use `recursive` or `fixed_size` strategies
- Reduce `chunk_overlap` for faster processing
- Use `semantic_chunk` for quality over speed
- Enable `split_on_word_boundary` to avoid breaking words

## License

Apache-2.0 License - See LICENSE file for details

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request
