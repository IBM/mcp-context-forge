# MCP RSS Search Server

**The ultimate RSS feed parser and search server for the Model Context Protocol (MCP)**

Advanced RSS feed parsing, searching, filtering, and statistical analysis server built with FastMCP. Features AI-powered semantic search, hybrid retrieval (BM25 + semantic), multi-schema podcast support, and comprehensive RSS analytics.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/FastMCP-2.11.3-green.svg)](https://gofastmcp.com/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

## Table of Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [Installation](#installation)
- [Quick Examples](#quick-examples)
- [All Tools (25 Total)](#all-tools-25-total)
- [Advanced Topics](#advanced-topics)
  - [Semantic Similarity Search](#semantic-similarity-search)
  - [Hybrid Search (BM25 + Semantic)](#hybrid-search-bm25--semantic)
  - [Podcast Schema Support](#podcast-schema-support)
- [JSON-RPC Usage](#json-rpc-usage)
- [Configuration](#configuration)
- [Development & Testing](#development--testing)
- [Troubleshooting](#troubleshooting)
- [Example RSS Feeds](#example-rss-feeds)
- [Performance](#performance)
- [Contributing](#contributing)
- [License](#license)

## Quick Start

### Installation

```bash
# Basic installation
cd mcp-servers/python/mcp-rss-search
make install

# With AI similarity and hybrid search (recommended!)
make install-similarity
```

### Running the Server

```bash
# Stdio mode (for Claude Desktop, Cursor, etc.)
make dev

# HTTP mode (REST API on port 9100)
make serve-http
```

### First Example

```python
import asyncio
from mcp_rss_search.server_fastmcp import rss_parser

async def main():
    # Fetch NPR News feed
    feed = await rss_parser.fetch_feed('https://feeds.npr.org/1001/rss.xml')
    print(f"Feed: {feed['metadata']['title']}")
    print(f"Entries: {feed['entry_count']}")

asyncio.run(main())
```

### Claude Desktop Configuration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rss-search": {
      "command": "python",
      "args": ["-m", "mcp_rss_search.server_fastmcp"]
    }
  }
}
```

## Features

### 🧠 AI-Powered Semantic & Hybrid Search
- **Hybrid Search**: Combines BM25 (keyword) and semantic similarity for best results
- **Document-Wide Search**: Search across all fields automatically
- **Configurable Models**: Change embedding models at runtime (6+ models supported)
- **Similarity Search**: Find content by meaning, not just keywords using sentence embeddings
- **Duplicate Detection**: Identify duplicate or near-duplicate content semantically
- **Related Content**: Discover "read more like this" recommendations
- **Topic Clustering**: Automatically group entries into topic clusters
- **BM25 + Semantic**: Best of both worlds - exact matching and meaning-based search

### 🎙️ Multi-Schema Podcast Support
- **iTunes Podcasts**: Full support for `itunes:*` namespace (subtitle, summary, episode, season, etc.)
- **Google Play**: Support for `googleplay:*` namespace
- **Standard RSS/Atom**: Universal RSS 2.0 and Atom feed support
- **Smart Field Detection**: Automatically extracts subtitles, summaries, descriptions across all formats
- **Schema Inspector**: Discover available fields in any feed
- **Semantic Search in Any Field**: Search subtitles, summaries, descriptions, or custom field combinations

### 🔍 Advanced Search Capabilities
- **Title Search**: Find entries by title with regex support
- **Content Search**: Search descriptions and full content
- **Multi-Field Search**: Search across titles, descriptions, authors, and categories
- **Author/Speaker Search**: Find all episodes by specific authors or podcast speakers
- **Regex Support**: Use powerful regular expressions for complex queries
- **Case-Sensitive Options**: Control search precision

### 📊 Statistical Analysis
- **Feed Statistics**: Comprehensive feed analytics (entry counts, date ranges, etc.)
- **Author Analytics**: Count and distribution of authors/speakers
- **Category Analytics**: Topic distribution and tag analysis
- **Content Metrics**: Average content length, total entries, etc.)
- **Media Analytics**: Track audio/video content in feeds

### 🎯 Filtering & Organization
- **Date Range Filtering**: Filter entries by publication date
- **Latest Entries**: Get N most recent entries
- **Author Filtering**: Find all content from specific authors
- **Category Browsing**: Explore content by tags and categories

### 🧹 Clean Data
- **Automatic HTML Removal**: Strips all HTML tags from content
- **XML Noise Filtering**: Clean, structured data without XML clutter
- **Entity Decoding**: Handles HTML entities correctly
- **Smart Caching**: Configurable caching for performance

## Installation

### Quick Install

```bash
cd mcp-servers/python/mcp-rss-search

# Basic installation (keyword search only)
make install

# With AI similarity and hybrid search
make install-similarity

# With development tools
make dev-install
```

### Using pip/uv directly

```bash
# Basic installation
pip install -e .

# With AI similarity and hybrid search features
pip install -e ".[similarity]"

# Full installation (similarity + dev tools)
pip install -e ".[full]"

# With uv (faster)
uv pip install -e ".[similarity]"
```

### Requirements

**Core Dependencies** (always installed):
- `fastmcp` >= 2.11.3
- `pydantic` >= 2.5.0
- `feedparser` >= 6.0.0
- `httpx` >= 0.27.0
- `python-dateutil` >= 2.8.0

**Similarity & Hybrid Search** (optional, install with `[similarity]`):
- `sentence-transformers` >= 2.2.0 (~80MB model, auto-downloaded)
- `numpy` >= 1.24.0
- `scikit-learn` >= 1.3.0
- `rank-bm25` >= 0.2.2 (for hybrid search with BM25 keyword matching)

**Environment Variables**:
- `RSS_EMBEDDING_MODEL` - Set default embedding model (default: `all-MiniLM-L6-v2`)

### Podcast Schema Support

The server automatically detects and extracts fields from:
- **iTunes Podcasts**: subtitle, summary, episode, season, duration, explicit flag
- **Google Play**: author, description, image
- **Standard RSS/Atom**: All standard fields

## Quick Examples

### 1. Fetch and Parse RSS Feed

```python
import asyncio
from mcp_rss_search.server_fastmcp import rss_parser

async def fetch_example():
    feed = await rss_parser.fetch_feed('https://feeds.npr.org/1001/rss.xml')
    print(f"Feed: {feed['metadata']['title']}")
    print(f"Entries: {feed['entry_count']}")

asyncio.run(fetch_example())
```

### 2. Search by Title

```python
async def search_example():
    feed = await rss_parser.fetch_feed('https://feeds.npr.org/1001/rss.xml')
    results = rss_parser.search_entries(feed, 'climate', fields=['title'])
    print(f"Found {len(results)} climate-related articles")
    for result in results[:3]:
        print(f"  - {result['title']}")

asyncio.run(search_example())
```

### 3. Semantic Search (AI-Powered)

```python
from mcp_rss_search.server_fastmcp import rss_parser, similarity_engine

async def semantic_search_example():
    feed = await rss_parser.fetch_feed('https://feeds.npr.org/1001/rss.xml')

    # Finds articles about AI, machine learning, automation, etc.
    results = similarity_engine.similarity_search(
        query="artificial intelligence and automation",
        entries=feed['entries'],
        top_k=5,
        threshold=0.5
    )

    for result in results:
        print(f"{result['entry']['title']} (score: {result['similarity']:.2f})")

asyncio.run(semantic_search_example())
```

### 4. Hybrid Search (BM25 + Semantic)

```python
from mcp_rss_search.server_fastmcp import rss_parser, hybrid_engine

async def hybrid_search_example():
    feed = await rss_parser.fetch_feed('https://podcast-feed.xml')

    # Combines keyword matching (BM25) with semantic similarity
    results = hybrid_engine.hybrid_search(
        query="machine learning ethics",
        entries=feed['entries'],
        semantic_weight=0.6,  # 60% semantic, 40% keyword
        bm25_weight=0.4,
        top_k=10
    )

    for result in results:
        print(f"{result['entry']['title']}")
        print(f"  Hybrid: {result['hybrid_score']:.2f} "
              f"(Semantic: {result['semantic_score']:.2f}, "
              f"BM25: {result['bm25_score']:.2f})")

asyncio.run(hybrid_search_example())
```

### 5. Find Podcast Episodes by Guest

```python
async def podcast_example():
    # Find episodes with specific guest
    results = rss_parser.find_by_author(
        feed,
        author="Neil deGrasse Tyson",
        exact_match=False
    )

    print(f"Found {len(results)} episodes with Neil deGrasse Tyson")

asyncio.run(podcast_example())
```

### 6. Get Feed Statistics

```python
async def stats_example():
    feed = await rss_parser.fetch_feed('https://blog-feed.xml')
    stats = rss_parser.get_statistics(feed)

    print(f"Total entries: {stats['total_entries']}")
    print(f"Unique authors: {stats['authors']['count']}")
    print(f"Date range: {stats['date_range']['earliest']} to {stats['date_range']['latest']}")

asyncio.run(stats_example())
```

## All Tools (25 Total)

The server provides 25 MCP tools organized into 5 categories:

### 🔬 Hybrid Search & Configuration (4 tools - NEWEST!)

#### 1. `get_model_info`
Get information about the current embedding model configuration.

**Returns**: Model name, status, embedding dimensions, max sequence length

**Example**: Check which model is currently configured and loaded.

#### 2. `configure_model`
Configure/change the embedding model at runtime.

**Parameters:**
- `model_name` (string, required): Sentence transformer model to use

**Common models**:
- `all-MiniLM-L6-v2` (default) - Fast, lightweight (80MB)
- `all-mpnet-base-v2` - Higher quality (420MB)
- `multi-qa-mpnet-base-dot-v1` - Best for Q&A
- `paraphrase-multilingual-MiniLM-L12-v2` - Multilingual

**Example**: `configure_model("all-mpnet-base-v2")` - Switch to higher quality model

#### 3. `hybrid_search`
Combine BM25 (keyword) and semantic similarity for robust search.

**Parameters:**
- `url` (string, required): RSS feed URL
- `query` (string, required): Search query
- `fields` (list, optional): Fields to search (default: title, description)
- `top_k` (integer, default: 10): Number of results
- `semantic_weight` (float, default: 0.5): Weight for semantic score (0-1)
- `bm25_weight` (float, default: 0.5): Weight for BM25 score (0-1)
- `threshold` (float, default: 0.0): Minimum hybrid score

**Returns**: Results with `hybrid_score`, `semantic_score`, and `bm25_score`

**Why Hybrid?**: Combines the best of both worlds - exact keyword matching (BM25) and meaning-based matching (semantic).

#### 4. `document_search`
Document-wide search across ALL fields with automatic hybrid retrieval.

**Parameters:**
- `url` (string, required): RSS feed URL
- `query` (string, required): Search query
- `top_k` (integer, default: 10): Number of results
- `use_semantic` (boolean, default: true): Enable semantic search
- `use_bm25` (boolean, default: true): Enable BM25 keyword search

**Searches**: title, subtitle, summary, description, author

**Perfect for**: When you don't know which field contains your information.

### 🎙️ Podcast-Specific Tools (4 tools)

#### 5. `inspect_feed_schema`
Inspect feed to discover available fields and podcast schema type.

**Returns**:
- Detected schemas (iTunes, Google Play, etc.)
- Available fields and coverage
- Recommended search fields
- Sample values

#### 6. `search_subtitles_semantic`
Search specifically in podcast episode subtitles (iTunes, Google Play formats).

**Perfect for**: Finding episodes by topic when subtitles are well-maintained.

#### 7. `search_summaries_semantic`
Search in episode summaries and descriptions (handles all podcast formats).

**Perfect for**: Deep content search across iTunes summary, descriptions, etc.

#### 8. `search_multi_field_semantic`
Custom multi-field semantic search - choose exactly which fields to search.

**Fields available**: title, subtitle, summary, description, author, categories, etc.

### 🧠 AI-Powered Semantic Search (4 tools)

#### 9. `similarity_search`
Semantic similarity search using AI embeddings. Finds content by *meaning*, not just keywords.

**Example**: Query "climate crisis" finds articles about "global warming", "environmental catastrophe", etc.

**Parameters:**
- `url` (string, required): RSS feed URL
- `query` (string, required): Natural language search query
- `top_k` (integer, default: 10): Number of results
- `threshold` (float, default: 0.0): Minimum similarity (0-1)
- `use_cache` (boolean, default: true)

#### 10. `find_duplicates`
Find duplicate or near-duplicate entries using semantic similarity.

**Use cases**: Cross-posted content, republished articles, feed deduplication

**Parameters:**
- `url` (string, required): RSS feed URL
- `similarity_threshold` (float, default: 0.85): Duplicate threshold
- `use_cache` (boolean, default: true)

#### 11. `find_related_entries`
Find entries related to a specific entry - perfect for "read more like this".

**Parameters:**
- `url` (string, required): RSS feed URL
- `entry_index` (integer, required): Index of source entry
- `top_k` (integer, default: 5): Number of related entries
- `use_cache` (boolean, default: true)

#### 12. `cluster_by_topic`
Automatically cluster entries into topic groups using K-means.

**Parameters:**
- `url` (string, required): RSS feed URL
- `n_clusters` (integer, default: 5): Number of clusters (2-20)
- `use_cache` (boolean, default: true)

### 🔍 Classic Search Tools (7 tools)

#### 13. `fetch_rss`
Fetch and parse an RSS feed from URL.

**Parameters:**
- `url` (string, required): RSS feed URL
- `use_cache` (boolean, default: true): Use cached feed if available

**Returns:** Complete feed data with metadata and entries

#### 14. `search_titles`
Search RSS feed entries by title.

**Parameters:**
- `url` (string, required): RSS feed URL
- `query` (string, required): Search query
- `case_sensitive` (boolean, default: false)
- `regex` (boolean, default: false): Use regex pattern matching
- `use_cache` (boolean, default: true)

#### 15. `search_descriptions`
Search in entry descriptions and content.

**Parameters:** Same as `search_titles`

#### 16. `search_all`
Search across all fields (title, description, author, categories).

**Parameters:** Same as `search_titles`

#### 17. `find_by_author`
Find all entries by a specific author or speaker.

**Parameters:**
- `url` (string, required): RSS feed URL
- `author` (string, required): Author/speaker name
- `exact_match` (boolean, default: false): Require exact name match
- `use_cache` (boolean, default: true)

#### 18. `list_authors`
List all unique authors/speakers with their entry counts.

**Parameters:**
- `url` (string, required): RSS feed URL
- `min_count` (integer, default: 1): Minimum entries per author
- `use_cache` (boolean, default: true)

#### 19. `list_categories`
List all unique categories/tags with counts.

**Parameters:**
- `url` (string, required): RSS feed URL
- `min_count` (integer, default: 1): Minimum entries per category
- `use_cache` (boolean, default: true)

### 📊 Analytics & Filtering (6 tools)

#### 20. `get_feed_statistics`
Get comprehensive feed statistics and analysis.

**Returns:**
- Total entry count
- Date range (earliest to latest)
- Author statistics (count and distribution)
- Category statistics
- Media statistics (for podcasts)
- Content length statistics

#### 21. `filter_by_date`
Filter entries by date range.

**Parameters:**
- `url` (string, required): RSS feed URL
- `start_date` (string, optional): Start date (ISO format or natural language)
- `end_date` (string, optional): End date
- `use_cache` (boolean, default: true)

**Example Dates:**
- ISO format: "2024-01-01"
- Natural: "last week", "January 2024"

#### 22. `get_feed_metadata`
Extract feed-level metadata (title, description, author, etc.).

#### 23. `get_latest_entries`
Get N most recent entries from the feed.

**Parameters:**
- `url` (string, required): RSS feed URL
- `count` (integer, default: 10, range: 1-100): Number of entries
- `use_cache` (boolean, default: true)

#### 24. `analyze_feed`
Comprehensive feed analysis with insights and recommendations.

**Returns:**
- Feed type detection (Podcast, Blog, News, etc.)
- Update frequency analysis
- Content patterns
- Automated insights
- Recommendations

#### 25. `clear_cache`
Clear the internal RSS feed cache.

## Advanced Topics

### Semantic Similarity Search

Semantic similarity search uses AI embeddings to find content by *meaning*, not just keywords.

#### How It Works

1. Text is converted to high-dimensional vectors (embeddings)
2. Similarity is computed using cosine similarity
3. Results are ranked by semantic similarity score (0-1)

#### When to Use

| Use Semantic Search When | Use Keyword Search When |
|--------------------------|-------------------------|
| Looking for concepts/ideas | Need exact phrase/term |
| Exploring related topics | Know specific keyword |
| Finding similar articles | Filtering by author/date |
| Duplicate detection | Precise field matching |
| Content recommendations | Fast, simple queries |

#### Understanding Similarity Scores

| Score | Meaning | Use Case |
|-------|---------|----------|
| 0.9-1.0 | Nearly identical | Duplicate detection |
| 0.7-0.9 | Very similar | Same topic/event |
| 0.5-0.7 | Related | Recommended reading |
| 0.3-0.5 | Loosely related | Topic exploration |
| < 0.3 | Minimal relation | Filter out |

#### Examples

```python
# High precision search
results = similarity_engine.similarity_search(
    query="quantum computing applications in drug discovery",
    entries=feed['entries'],
    threshold=0.7,  # High threshold
    top_k=5
)

# Discovery mode (find related concepts)
results = similarity_engine.similarity_search(
    query="climate change",
    entries=feed['entries'],
    threshold=0.3,  # Lower threshold
    top_k=20  # More results
)

# Find duplicates
duplicates = similarity_engine.find_duplicates(
    entries=feed['entries'],
    similarity_threshold=0.85
)

# Topic clustering
clusters = similarity_engine.cluster_entries(
    entries=feed['entries'],
    n_clusters=5
)
```

### Hybrid Search (BM25 + Semantic)

Hybrid search combines traditional keyword-based ranking (BM25) with semantic similarity for robust search results.

#### Why Hybrid Search?

**Problem with Pure Semantic Search**:
- May miss exact keyword matches
- Can be too "fuzzy" for specific queries

**Problem with Pure Keyword Search**:
- Misses synonyms and related concepts
- Requires exact word matches

**Solution: Hybrid Search**:
- Gets both exact matches AND semantic matches
- Configurable weights let you tune precision vs. recall

#### Weight Configuration Guidelines

| Use Case | Semantic Weight | BM25 Weight | Why |
|----------|----------------|-------------|-----|
| General search | 0.5 | 0.5 | Balanced |
| Concept discovery | 0.7 | 0.3 | Find related topics |
| Exact term search | 0.3 | 0.7 | Precise keyword matching |
| Technical docs | 0.4 | 0.6 | Technical terms matter |
| News articles | 0.6 | 0.4 | Concepts > exact words |

#### Examples

```python
# Balanced hybrid search
results = hybrid_engine.hybrid_search(
    query="artificial intelligence regulation",
    entries=feed['entries'],
    semantic_weight=0.5,
    bm25_weight=0.5,
    top_k=10
)

# Favor semantic (find related concepts)
results = hybrid_engine.hybrid_search(
    query="climate change policy",
    entries=feed['entries'],
    semantic_weight=0.7,
    bm25_weight=0.3,
    top_k=5
)

# Favor keyword (precise matching)
results = hybrid_engine.hybrid_search(
    query="Python 3.12 new features",
    entries=feed['entries'],
    semantic_weight=0.3,
    bm25_weight=0.7,
    fields=["title", "description"],
    top_k=10
)

# Document-wide search (all fields)
results = hybrid_engine.document_search(
    query="quantum computing interview",
    entries=feed['entries'],
    top_k=10
)
```

#### Result Format

```json
{
  "success": true,
  "query": "machine learning ethics",
  "semantic_weight": 0.5,
  "bm25_weight": 0.5,
  "match_count": 5,
  "matches": [
    {
      "hybrid_score": 0.82,
      "semantic_score": 0.75,
      "bm25_score": 0.89,
      "entry": {
        "title": "AI Ethics and Responsible Development",
        "description": "...",
        ...
      }
    }
  ]
}
```

### Model Configuration

#### Available Models

| Model | Size | Speed | Quality | Use Case |
|-------|------|-------|---------|----------|
| `all-MiniLM-L6-v2` | 80MB | ⚡⚡⚡ | Good | Default, fast |
| `all-MiniLM-L12-v2` | 120MB | ⚡⚡ | Better | Balanced |
| `all-mpnet-base-v2` | 420MB | ⚡ | Best | High quality |
| `multi-qa-mpnet-base-dot-v1` | 420MB | ⚡ | Best | Q&A, search |
| `all-distilroberta-v1` | 290MB | ⚡⚡ | Better | Fast, good quality |
| `paraphrase-multilingual-MiniLM-L12-v2` | 470MB | ⚡ | Good | Multilingual |

#### Change Model at Runtime

```python
# Get current model info
info = similarity_engine.get_model_info()
print(f"Current model: {info['configured_model']}")

# Switch to higher quality model
similarity_engine.model_name = "all-mpnet-base-v2"
similarity_engine.model = None  # Force reload

# Or via environment variable
import os
os.environ['RSS_EMBEDDING_MODEL'] = "all-mpnet-base-v2"
```

#### When to Change Models

**Use Larger Models When**:
- Search quality is critical
- You have time for slower processing
- You're doing offline batch processing
- You need best possible results

**Use Smaller Models When**:
- Speed is important
- You're running on limited hardware
- You need real-time responses
- Default quality is sufficient

**Use Specialized Models When**:
- Q&A format: `multi-qa-mpnet-base-dot-v1`
- Multilingual content: `paraphrase-multilingual-MiniLM-L12-v2`
- Code search: `all-mpnet-base-v2`

### Podcast Schema Support

The server automatically detects and extracts fields from multiple podcast formats.

#### Supported Schemas

1. **iTunes Podcast** - Full `itunes:*` namespace support
2. **Google Play Podcasts** - `googleplay:*` namespace
3. **Standard RSS 2.0** - All standard fields
4. **Atom Feeds** - Summary, content, author
5. **Media RSS** - Thumbnails, media content

#### Field Extraction Priority

**Subtitle**:
```
itunes:subtitle → subtitle → googleplay:description (if < 200 chars)
```

**Summary**:
```
itunes:summary → content → summary → description → googleplay:description
```

**Author**:
```
itunes:author → googleplay:author → author
```

**Image**:
```
itunes:image → googleplay:image → media:thumbnail → image
```

#### Extracted Fields (16 total)

- title, subtitle, summary, description
- link, author, published, updated
- categories, episode, season
- media_url, media_type, media_duration, media_size
- image, explicit, guid

#### Workflow Example

```python
# 1. Inspect feed schema
schema = rss_parser.inspect_feed_schema(feed_url)
print(f"Schemas: {schema['detected_schemas']}")
print(f"Best fields: {schema['recommended_search_fields']}")

# 2. Search subtitles (topic-focused)
if 'subtitle' in schema['available_fields']:
    results = similarity_engine.similarity_search(
        query="machine learning applications",
        entries=feed['entries'],
        fields=["subtitle"]
    )

# 3. Search summaries (deep content)
results = similarity_engine.similarity_search(
    query="discussion about quantum computing",
    entries=feed['entries'],
    fields=["summary", "description"]
)

# 4. Custom field search
results = similarity_engine.similarity_search(
    query="climate change policy",
    entries=feed['entries'],
    fields=schema['recommended_search_fields']
)
```

## JSON-RPC Usage

When running in HTTP mode, the server supports JSON-RPC 2.0 protocol.

### Start HTTP Server

```bash
make serve-http
# Server runs on http://0.0.0.0:9100/mcp/
```

### List All Tools

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  http://0.0.0.0:9100/mcp/ | python3 -m json.tool
```

### Fetch RSS Feed

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "fetch_rss",
      "arguments": {
        "url": "https://feeds.npr.org/1001/rss.xml",
        "use_cache": false
      }
    }
  }' \
  http://0.0.0.0:9100/mcp/ | python3 -m json.tool
```

### Search Titles

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "search_titles",
      "arguments": {
        "url": "https://feeds.npr.org/1001/rss.xml",
        "query": "climate",
        "case_sensitive": false,
        "regex": false
      }
    }
  }' \
  http://0.0.0.0:9100/mcp/ | python3 -m json.tool
```

### Hybrid Search

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "hybrid_search",
      "arguments": {
        "url": "https://feeds.npr.org/1001/rss.xml",
        "query": "artificial intelligence ethics",
        "semantic_weight": 0.6,
        "bm25_weight": 0.4,
        "top_k": 5
      }
    }
  }' \
  http://0.0.0.0:9100/mcp/ | python3 -m json.tool
```

## Configuration

### Environment Variables

```bash
# Set default embedding model
export RSS_EMBEDDING_MODEL="all-mpnet-base-v2"

# Set cache directory (optional)
export RSS_CACHE_DIR="/path/to/cache"
```

### Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rss-search": {
      "command": "python",
      "args": ["-m", "mcp_rss_search.server_fastmcp"],
      "env": {
        "RSS_EMBEDDING_MODEL": "all-MiniLM-L6-v2"
      }
    }
  }
}
```

### Cursor / Other MCP Clients

The server supports standard MCP protocol via stdio. Refer to your client's documentation for configuration.

## Development & Testing

### Running Tests

```bash
# Run all tests with coverage
make test

# Run specific test
pytest tests/test_server.py::TestRSSParser::test_fetch_feed_success -v

# Check coverage report
pytest --cov=mcp_rss_search --cov-report=html
open htmlcov/index.html
```

### Code Quality

```bash
# Format code
make format

# Lint code
make lint

# Type checking
mypy src/mcp_rss_search
```

### Development Workflow

```bash
# Create virtual environment
make venv

# Install development dependencies
make dev-install

# Run development server with auto-reload
make dev

# Run all quality checks
make test lint format
```

## Troubleshooting

### Issue: ModuleNotFoundError

**Solution**: Make sure the virtual environment is activated and the package is installed:

```bash
. /home/cmihai/.venv/mcpgateway/bin/activate
cd mcp-servers/python/mcp-rss-search
pip install -e .
```

### Issue: Similarity search not available

**Error**: "sentence-transformers not installed"

**Solution**: Install similarity dependencies:

```bash
pip install -e ".[similarity]"
# Or
make install-similarity
```

### Issue: Slow first run

**Reason**: Model needs to download (~80MB)

**Solution**: Wait 30-60 seconds on first use. Model is cached after that.

### Issue: Out of memory

**Solution**: Process fewer entries at once

```python
# Process in batches
batch_size = 50
for i in range(0, len(entries), batch_size):
    batch = entries[i:i+batch_size]
    results = similarity_engine.similarity_search(query, batch)
```

### Issue: Server won't start

**Solution**: Check if port 9100 is already in use:

```bash
lsof -i :9100
# Kill any process using the port
kill <PID>
```

### Issue: Tests failing

**Solution**: Reinstall dev dependencies:

```bash
pip install -e ".[dev]"
pytest -v
```

## Example RSS Feeds

### News Feeds
- **NPR News**: https://feeds.npr.org/1001/rss.xml
- **NY Times**: https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml
- **BBC News**: http://feeds.bbci.co.uk/news/rss.xml
- **Reuters**: http://feeds.reuters.com/reuters/topNews
- **The Guardian**: https://www.theguardian.com/world/rss

### Technology Feeds
- **Hacker News**: https://news.ycombinator.com/rss
- **TechCrunch**: https://techcrunch.com/feed/
- **Ars Technica**: http://feeds.arstechnica.com/arstechnica/index
- **Wired**: https://www.wired.com/feed/rss
- **The Verge**: https://www.theverge.com/rss/index.xml

### Podcast Feeds
- **The Daily (NYT)**: https://feeds.simplecast.com/54nAGcIl
- **Planet Money**: https://feeds.npr.org/510289/podcast.xml
- **Radiolab**: http://feeds.wnyc.org/radiolab
- **This American Life**: http://feed.thisamericanlife.org/talpodcast

## Performance

### Caching
- Feeds are cached by URL
- Cache persists for server lifetime
- Manual cache clearing with `clear_cache` tool
- Configurable via `use_cache` parameter

### Optimization
- Async HTTP requests
- Efficient feedparser usage
- Minimal memory footprint
- Fast regex-based text processing

### Performance Tips

1. **Use caching**: Set `use_cache=True` for frequently accessed feeds
2. **Filter early**: Use specific tools instead of fetching everything
3. **Regex carefully**: Simple string searches are faster than regex
4. **Clear cache**: Use `clear_cache()` when feeds update frequently
5. **Batch processing**: For large feeds, process entries in batches

## Contributing

Contributions welcome! Areas for enhancement:

- [ ] Persistent caching (Redis, SQLite)
- [ ] Feed autodiscovery from website URLs
- [ ] OPML import/export
- [ ] Multi-feed aggregation and deduplication
- [ ] Custom feed filters and transformations
- [ ] RSS feed creation/generation
- [ ] Webhook support for feed updates
- [ ] More embedding models support
- [ ] GraphQL API support

## License

Apache-2.0

## Credits

Built with:
- [FastMCP](https://gofastmcp.com/) - MCP protocol implementation
- [feedparser](https://feedparser.readthedocs.io/) - RSS/Atom parsing
- [httpx](https://www.python-httpx.org/) - HTTP client
- [sentence-transformers](https://www.sbert.net/) - Semantic embeddings
- [rank-bm25](https://github.com/dorianbrown/rank_bm25) - BM25 ranking
- [ContextForge](https://github.com/your-org/mcp-context-forge) - ContextForge ecosystem

---

**Happy RSS parsing with AI-powered search! 🎉🧠🔍✨**
