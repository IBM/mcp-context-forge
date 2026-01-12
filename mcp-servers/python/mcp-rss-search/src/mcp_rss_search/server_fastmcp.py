#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp-rss-search/src/mcp_rss_search/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: MCP Context Forge

MCP RSS Search Server - FastMCP Implementation

Advanced RSS feed parsing, searching, filtering, and statistical analysis server.
Filters out XML noise and provides clean, structured access to RSS feed content.
"""

import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx
import orjson
from fastmcp import FastMCP
from pydantic import Field

# Configure logging to stderr to avoid MCP protocol interference
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Create FastMCP server instance
mcp = FastMCP(name="mcp-rss-search", version="1.0.0")


def _dump_json(payload: Any) -> str:
    """Serialize payload as pretty JSON for MCP responses."""
    return orjson.dumps(payload, option=orjson.OPT_INDENT_2).decode()


class RSSParser:
    """Advanced RSS feed parser with search and analysis capabilities."""

    def __init__(self):
        """Initialize the RSS parser."""
        self.cache: dict[str, Any] = {}

    async def fetch_feed(self, url: str, use_cache: bool = True) -> dict[str, Any]:
        """
        Fetch and parse RSS feed from URL.

        Args:
            url: RSS feed URL
            use_cache: Use cached feed if available

        Returns:
            Parsed feed data with clean structure
        """
        try:
            # Check cache
            if use_cache and url in self.cache:
                logger.info(f"Using cached feed for {url}")
                return self.cache[url]

            # Fetch feed
            logger.info(f"Fetching RSS feed from {url}")
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                feed_content = response.text

            # Parse feed
            feed = feedparser.parse(feed_content)

            if feed.bozo:
                # Feed has issues but may still be parseable
                logger.warning(f"Feed parsing issues: {feed.bozo_exception}")

            # Extract clean feed data
            result = self._extract_feed_data(feed, url)

            # Cache the result
            self.cache[url] = result

            return result

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching feed: {e}")
            return {"success": False, "error": f"HTTP error: {str(e)}"}
        except Exception as e:
            logger.error(f"Error fetching feed: {e}")
            return {"success": False, "error": str(e)}

    def _extract_feed_data(self, feed: Any, url: str) -> dict[str, Any]:
        """Extract clean, structured data from feedparser feed object."""
        # Extract feed metadata
        feed_info = feed.get("feed", {})

        metadata = {
            "title": feed_info.get("title", ""),
            "description": feed_info.get("description", "") or feed_info.get("subtitle", ""),
            "link": feed_info.get("link", ""),
            "language": feed_info.get("language", ""),
            "author": feed_info.get("author", ""),
            "publisher": feed_info.get("publisher", ""),
            "updated": self._parse_date(feed_info.get("updated", "")),
            "image": feed_info.get("image", {}).get("href", ""),
            "categories": [cat.get("term", "") for cat in feed_info.get("categories", [])],
        }

        # Extract entries
        entries = []
        for entry in feed.get("entries", []):
            clean_entry = self._extract_entry_data(entry)
            entries.append(clean_entry)

        return {
            "success": True,
            "url": url,
            "metadata": metadata,
            "entries": entries,
            "entry_count": len(entries),
        }

    def _extract_entry_data(self, entry: Any) -> dict[str, Any]:
        """
        Extract clean entry data, filtering XML noise.

        Supports multiple podcast schemas:
        - iTunes (itunes:* tags)
        - Google Play (googleplay:* tags)
        - Standard RSS 2.0
        - Atom feeds
        """
        # Extract subtitle - check multiple sources
        # iTunes: itunes:subtitle
        # Google Play: googleplay:description (short)
        # Standard: subtitle field
        subtitle = ""
        if hasattr(entry, "itunes_subtitle"):
            subtitle = entry.itunes_subtitle
        elif hasattr(entry, "subtitle"):
            subtitle = entry.subtitle
        elif hasattr(entry, "googleplay_description"):
            # Google Play description is often shorter
            googleplay_desc = entry.googleplay_description
            if len(googleplay_desc) < 200:  # Likely a subtitle
                subtitle = googleplay_desc

        # Extract summary/description - with fallback hierarchy
        # Priority: itunes:summary > content > summary > description > googleplay:description
        summary = ""
        description = ""

        # iTunes summary (often longer, detailed)
        if hasattr(entry, "itunes_summary"):
            summary = entry.itunes_summary

        # Content (most detailed)
        if hasattr(entry, "content") and entry.content:
            description = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            description = entry.summary
        elif hasattr(entry, "description"):
            description = entry.description
        elif hasattr(entry, "googleplay_description"):
            description = entry.googleplay_description

        # Use summary as description if no description found
        if not description and summary:
            description = summary

        # Use description as summary if no summary found (truncated)
        if not summary and description:
            # Take first 300 chars as summary
            summary = description[:300] + "..." if len(description) > 300 else description

        # Clean HTML from both
        subtitle = self._clean_html(subtitle)
        summary = self._clean_html(summary)
        description = self._clean_html(description)

        # Extract author/speaker info - multiple sources
        # iTunes: itunes:author
        # Google Play: googleplay:author
        # Standard: author
        author = ""
        if hasattr(entry, "itunes_author"):
            author = entry.itunes_author
        elif hasattr(entry, "googleplay_author"):
            author = entry.googleplay_author
        elif entry.get("author"):
            author = entry.author

        # Extract episode/season info (podcasts)
        episode = ""
        season = ""
        if hasattr(entry, "itunes_episode"):
            episode = str(entry.itunes_episode)
        if hasattr(entry, "itunes_season"):
            season = str(entry.itunes_season)

        # Extract media info for podcasts
        media_url = ""
        media_type = ""
        media_duration = ""
        media_size = ""

        if hasattr(entry, "enclosures") and entry.enclosures:
            media_url = entry.enclosures[0].get("href", "")
            media_type = entry.enclosures[0].get("type", "")
            media_size = entry.enclosures[0].get("length", "")

        # iTunes duration (formatted as HH:MM:SS or seconds)
        if hasattr(entry, "itunes_duration"):
            media_duration = entry.itunes_duration

        # Extract image - multiple sources
        # iTunes: itunes:image
        # Google Play: googleplay:image
        # Media: media:thumbnail
        image = ""
        if hasattr(entry, "itunes_image"):
            if isinstance(entry.itunes_image, dict):
                image = entry.itunes_image.get("href", "")
            else:
                image = str(entry.itunes_image)
        elif hasattr(entry, "googleplay_image"):
            if isinstance(entry.googleplay_image, dict):
                image = entry.googleplay_image.get("href", "")
            else:
                image = str(entry.googleplay_image)
        elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            image = entry.media_thumbnail[0].get("url", "")
        elif hasattr(entry, "image"):
            if isinstance(entry.image, dict):
                image = entry.image.get("href", "")
            else:
                image = str(entry.image)

        # Extract categories/tags
        categories = []
        if hasattr(entry, "tags"):
            categories = [tag.get("term", "") for tag in entry.tags]

        # iTunes categories
        if hasattr(entry, "itunes_categories"):
            for cat in entry.itunes_categories:
                if isinstance(cat, dict):
                    categories.append(cat.get("term", ""))
                else:
                    categories.append(str(cat))

        # Extract explicit flag (podcasts)
        explicit = False
        if hasattr(entry, "itunes_explicit"):
            explicit = entry.itunes_explicit.lower() in ("yes", "true", "explicit")

        return {
            "title": entry.get("title", ""),
            "subtitle": subtitle,
            "summary": summary,
            "description": description,
            "link": entry.get("link", ""),
            "author": author,
            "published": self._parse_date(entry.get("published", "")),
            "updated": self._parse_date(entry.get("updated", "")),
            "categories": categories,
            "media_url": media_url,
            "media_type": media_type,
            "media_duration": media_duration,
            "media_size": media_size,
            "image": image,
            "episode": episode,
            "season": season,
            "explicit": explicit,
            "guid": entry.get("id", ""),
        }

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags and clean up text."""
        if not text:
            return ""

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # Decode HTML entities
        import html

        text = html.unescape(text)

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def _parse_date(self, date_str: str) -> str:
        """Parse and normalize date strings."""
        if not date_str:
            return ""

        try:
            # feedparser already handles most date parsing
            from dateutil import parser

            dt = parser.parse(date_str)
            return dt.isoformat()
        except Exception:
            # Return as-is if parsing fails
            return date_str

    def search_entries(
        self,
        feed_data: dict[str, Any],
        query: str,
        fields: list[str] | None = None,
        case_sensitive: bool = False,
        regex: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Search entries across specified fields.

        Args:
            feed_data: Parsed feed data
            query: Search query
            fields: Fields to search in (title, description, author, categories)
            case_sensitive: Case-sensitive search
            regex: Use regex pattern matching

        Returns:
            Matching entries
        """
        if not feed_data.get("success"):
            return []

        if fields is None:
            fields = ["title", "description", "author"]

        results = []
        entries = feed_data.get("entries", [])

        for entry in entries:
            match = False

            for field in fields:
                field_value = str(entry.get(field, ""))

                if not field_value:
                    continue

                if regex:
                    try:
                        flags = 0 if case_sensitive else re.IGNORECASE
                        if re.search(query, field_value, flags):
                            match = True
                            break
                    except re.error as e:
                        logger.error(f"Invalid regex pattern: {e}")
                        return []
                else:
                    search_value = field_value if case_sensitive else field_value.lower()
                    search_query = query if case_sensitive else query.lower()

                    if search_query in search_value:
                        match = True
                        break

            if match:
                results.append(entry)

        return results

    def filter_by_date(
        self,
        feed_data: dict[str, Any],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Filter entries by date range."""
        if not feed_data.get("success"):
            return []

        entries = feed_data.get("entries", [])
        results = []

        start_dt = None
        end_dt = None

        if start_date:
            try:
                from dateutil import parser

                start_dt = parser.parse(start_date)
            except Exception as e:
                logger.error(f"Invalid start date: {e}")
                return []

        if end_date:
            try:
                from dateutil import parser

                end_dt = parser.parse(end_date)
            except Exception as e:
                logger.error(f"Invalid end date: {e}")
                return []

        for entry in entries:
            published = entry.get("published", "")
            if not published:
                continue

            try:
                from dateutil import parser

                entry_dt = parser.parse(published)

                if start_dt and entry_dt < start_dt:
                    continue
                if end_dt and entry_dt > end_dt:
                    continue

                results.append(entry)
            except Exception:
                continue

        return results

    def get_statistics(self, feed_data: dict[str, Any]) -> dict[str, Any]:
        """Generate comprehensive feed statistics."""
        if not feed_data.get("success"):
            return {"success": False, "error": "Invalid feed data"}

        entries = feed_data.get("entries", [])
        metadata = feed_data.get("metadata", {})

        # Author statistics
        authors = [e.get("author", "") for e in entries if e.get("author")]
        author_counts = dict(Counter(authors).most_common())

        # Category statistics
        all_categories = []
        for entry in entries:
            all_categories.extend(entry.get("categories", []))
        category_counts = dict(Counter(all_categories).most_common())

        # Date statistics
        dates = [e.get("published", "") for e in entries if e.get("published")]
        earliest = min(dates) if dates else None
        latest = max(dates) if dates else None

        # Media statistics
        media_entries = [e for e in entries if e.get("media_url")]
        media_types = Counter([e.get("media_type", "") for e in media_entries])

        # Content statistics
        total_content_length = sum(len(e.get("description", "")) for e in entries)
        avg_content_length = total_content_length / len(entries) if entries else 0

        return {
            "success": True,
            "feed_title": metadata.get("title", ""),
            "total_entries": len(entries),
            "date_range": {"earliest": earliest, "latest": latest},
            "authors": {"count": len(set(authors)), "top_authors": author_counts},
            "categories": {"count": len(set(all_categories)), "distribution": category_counts},
            "media": {
                "entries_with_media": len(media_entries),
                "media_types": dict(media_types),
            },
            "content": {
                "total_length": total_content_length,
                "average_length": int(avg_content_length),
            },
        }

    def list_unique_values(
        self, feed_data: dict[str, Any], field: str
    ) -> dict[str, Any]:
        """List unique values for a field with counts."""
        if not feed_data.get("success"):
            return {"success": False, "error": "Invalid feed data"}

        entries = feed_data.get("entries", [])
        values: list[str] = []

        for entry in entries:
            value = entry.get(field)
            if isinstance(value, list):
                values.extend(value)
            elif value:
                values.append(str(value))

        counts = dict(Counter(values).most_common())

        return {
            "success": True,
            "field": field,
            "unique_count": len(counts),
            "total_count": len(values),
            "distribution": counts,
        }


# Initialize parser
rss_parser = RSSParser()


class SimilaritySearchEngine:
    """Semantic similarity search using sentence embeddings."""

    def __init__(self, model_name: str | None = None):
        """
        Initialize the similarity search engine.

        Args:
            model_name: Sentence transformer model name. If None, uses default.
                       Common models:
                       - "all-MiniLM-L6-v2" (default) - Fast, lightweight (80MB)
                       - "all-mpnet-base-v2" - Higher quality (420MB)
                       - "multi-qa-mpnet-base-dot-v1" - Best for Q&A
                       - "paraphrase-multilingual-MiniLM-L12-v2" - Multilingual
        """
        import os

        # Get model from env var or parameter or default
        self.model_name = model_name or os.getenv(
            "RSS_EMBEDDING_MODEL", "all-MiniLM-L6-v2"
        )
        self.model = None
        self.available = self._check_availability()

    def _check_availability(self) -> bool:
        """Check if sentence-transformers is available."""
        try:
            from sentence_transformers import SentenceTransformer

            return True
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Install with: pip install mcp-rss-search[similarity]"
            )
            return False

    def _load_model(self, model_name: str | None = None):
        """
        Lazy load the embedding model.

        Args:
            model_name: Override model name for this load
        """
        if not self.available:
            return None

        # Allow runtime model override
        target_model = model_name or self.model_name

        # Check if we need to reload (different model requested)
        if self.model is not None and target_model == self.model_name:
            return self.model

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {target_model}")
            logger.info("(This may take a moment on first use...)")
            self.model = SentenceTransformer(target_model)
            self.model_name = target_model
            logger.info(f"Model '{target_model}' loaded successfully")
            return self.model
        except Exception as e:
            logger.error(f"Failed to load embedding model '{target_model}': {e}")
            self.available = False
            return None

    def get_model_info(self) -> dict[str, Any]:
        """Get information about the current model."""
        if not self.available:
            return {
                "available": False,
                "error": "sentence-transformers not installed",
            }

        info = {
            "available": True,
            "configured_model": self.model_name,
            "loaded": self.model is not None,
        }

        if self.model is not None:
            info["model_name"] = self.model_name
            try:
                info["max_seq_length"] = self.model.max_seq_length
                info["embedding_dimension"] = self.model.get_sentence_embedding_dimension()
            except Exception:
                pass

        return info

    def generate_embeddings(self, texts: list[str]) -> Any:
        """Generate embeddings for a list of texts."""
        if not self.available:
            return None

        model = self._load_model()
        if model is None:
            return None

        try:
            import numpy as np

            embeddings = model.encode(texts, convert_to_numpy=True)
            return embeddings
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            return None

    def cosine_similarity(self, embedding1: Any, embedding2: Any) -> float:
        """Calculate cosine similarity between two embeddings."""
        try:
            import numpy as np

            # Normalize vectors
            norm1 = np.linalg.norm(embedding1)
            norm2 = np.linalg.norm(embedding2)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            similarity = np.dot(embedding1, embedding2) / (norm1 * norm2)
            return float(similarity)
        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {e}")
            return 0.0

    def similarity_search(
        self,
        query: str,
        entries: list[dict[str, Any]],
        top_k: int = 10,
        threshold: float = 0.0,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Perform semantic similarity search on entries.

        Args:
            query: Search query text
            entries: List of RSS entries
            top_k: Number of top results to return
            threshold: Minimum similarity score (0-1)
            fields: Fields to search (title, subtitle, summary, description, etc.)
                   If None, uses title + description

        Returns:
            List of entries with similarity scores
        """
        if not self.available:
            return []

        try:
            import numpy as np

            # Default fields if not specified
            if fields is None:
                fields = ["title", "description"]

            # Generate embeddings for entry texts
            entry_texts = []
            for entry in entries:
                # Combine specified fields for richer context
                text_parts = []
                for field in fields:
                    field_value = entry.get(field, "")
                    if field_value:
                        text_parts.append(str(field_value))

                text = " ".join(text_parts) if text_parts else ""
                entry_texts.append(text)

            if not entry_texts:
                return []

            # Generate embeddings
            query_embedding = self.generate_embeddings([query])
            entry_embeddings = self.generate_embeddings(entry_texts)

            if query_embedding is None or entry_embeddings is None:
                return []

            # Calculate similarities
            similarities = []
            for i, entry_emb in enumerate(entry_embeddings):
                if not entry_texts[i]:  # Skip empty entries
                    continue

                similarity = self.cosine_similarity(query_embedding[0], entry_emb)
                if similarity >= threshold:
                    similarities.append({"entry": entries[i], "similarity": similarity})

            # Sort by similarity (descending)
            similarities.sort(key=lambda x: x["similarity"], reverse=True)

            # Return top k results
            return similarities[:top_k]

        except Exception as e:
            logger.error(f"Error in similarity search: {e}")
            return []

    def find_duplicates(
        self, entries: list[dict[str, Any]], similarity_threshold: float = 0.85
    ) -> list[dict[str, Any]]:
        """
        Find duplicate or near-duplicate entries using semantic similarity.

        Args:
            entries: List of RSS entries
            similarity_threshold: Minimum similarity to consider duplicates (0-1)

        Returns:
            List of duplicate groups
        """
        if not self.available or not entries:
            return []

        try:
            import numpy as np

            # Generate embeddings for all entries
            entry_texts = []
            for entry in entries:
                text = f"{entry.get('title', '')} {entry.get('description', '')}"
                entry_texts.append(text)

            embeddings = self.generate_embeddings(entry_texts)
            if embeddings is None:
                return []

            # Find duplicates
            duplicates = []
            processed = set()

            for i in range(len(entries)):
                if i in processed:
                    continue

                group = [{"entry": entries[i], "index": i}]

                for j in range(i + 1, len(entries)):
                    if j in processed:
                        continue

                    similarity = self.cosine_similarity(embeddings[i], embeddings[j])

                    if similarity >= similarity_threshold:
                        group.append({"entry": entries[j], "index": j, "similarity": similarity})
                        processed.add(j)

                if len(group) > 1:
                    duplicates.append(group)
                    processed.add(i)

            return duplicates

        except Exception as e:
            logger.error(f"Error finding duplicates: {e}")
            return []

    def find_related(
        self, entry: dict[str, Any], all_entries: list[dict[str, Any]], top_k: int = 5
    ) -> list[dict[str, Any]]:
        """
        Find entries related to a given entry.

        Args:
            entry: Source entry
            all_entries: List of all entries to search
            top_k: Number of related entries to return

        Returns:
            List of related entries with similarity scores
        """
        if not self.available:
            return []

        try:
            # Create query from entry
            query = f"{entry.get('title', '')} {entry.get('description', '')}"

            # Filter out the source entry
            filtered_entries = [e for e in all_entries if e.get("guid") != entry.get("guid")]

            # Perform similarity search
            results = self.similarity_search(query, filtered_entries, top_k=top_k, threshold=0.3)

            return results

        except Exception as e:
            logger.error(f"Error finding related entries: {e}")
            return []

    def cluster_entries(
        self, entries: list[dict[str, Any]], n_clusters: int = 5
    ) -> dict[str, Any]:
        """
        Cluster entries by semantic similarity.

        Args:
            entries: List of RSS entries
            n_clusters: Number of clusters to create

        Returns:
            Dictionary with cluster assignments and statistics
        """
        if not self.available or not entries:
            return {"success": False, "error": "Similarity search not available"}

        try:
            import numpy as np
            from sklearn.cluster import KMeans

            # Generate embeddings
            entry_texts = []
            for entry in entries:
                text = f"{entry.get('title', '')} {entry.get('description', '')}"
                entry_texts.append(text)

            embeddings = self.generate_embeddings(entry_texts)
            if embeddings is None:
                return {"success": False, "error": "Failed to generate embeddings"}

            # Adjust n_clusters if we have fewer entries
            n_clusters = min(n_clusters, len(entries))

            # Perform clustering
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            cluster_labels = kmeans.fit_predict(embeddings)

            # Organize results
            clusters = {}
            for i, label in enumerate(cluster_labels):
                label_str = f"cluster_{label}"
                if label_str not in clusters:
                    clusters[label_str] = []
                clusters[label_str].append(entries[i])

            # Calculate cluster statistics
            cluster_stats = {}
            for cluster_id, cluster_entries in clusters.items():
                cluster_stats[cluster_id] = {
                    "size": len(cluster_entries),
                    "sample_titles": [e.get("title", "") for e in cluster_entries[:3]],
                }

            return {
                "success": True,
                "n_clusters": n_clusters,
                "clusters": clusters,
                "statistics": cluster_stats,
            }

        except Exception as e:
            logger.error(f"Error clustering entries: {e}")
            return {"success": False, "error": str(e)}


class HybridSearchEngine:
    """Hybrid search combining BM25 (keyword) and semantic search."""

    def __init__(self, semantic_engine: SimilaritySearchEngine):
        """
        Initialize hybrid search engine.

        Args:
            semantic_engine: SimilaritySearchEngine instance for semantic search
        """
        self.semantic_engine = semantic_engine
        self.bm25_available = self._check_bm25_availability()

    def _check_bm25_availability(self) -> bool:
        """Check if rank-bm25 is available."""
        try:
            from rank_bm25 import BM25Okapi

            return True
        except ImportError:
            logger.warning(
                "rank-bm25 not installed. Hybrid search requires: pip install rank-bm25"
            )
            return False

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization for BM25."""
        # Convert to lowercase and split on non-alphanumeric
        import re

        text = text.lower()
        tokens = re.findall(r"\w+", text)
        return tokens

    def _prepare_documents(
        self, entries: list[dict[str, Any]], fields: list[str]
    ) -> tuple[list[str], list[list[str]]]:
        """
        Prepare documents for BM25.

        Args:
            entries: List of RSS entries
            fields: Fields to include

        Returns:
            Tuple of (full_texts, tokenized_docs)
        """
        full_texts = []
        tokenized_docs = []

        for entry in entries:
            # Combine fields
            text_parts = []
            for field in fields:
                value = entry.get(field, "")
                if value:
                    text_parts.append(str(value))

            full_text = " ".join(text_parts)
            full_texts.append(full_text)
            tokenized_docs.append(self._tokenize(full_text))

        return full_texts, tokenized_docs

    def hybrid_search(
        self,
        query: str,
        entries: list[dict[str, Any]],
        fields: list[str] | None = None,
        top_k: int = 10,
        semantic_weight: float = 0.5,
        bm25_weight: float = 0.5,
        threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Hybrid search combining BM25 and semantic similarity.

        Args:
            query: Search query
            entries: List of RSS entries
            fields: Fields to search in
            top_k: Number of results
            semantic_weight: Weight for semantic scores (0-1)
            bm25_weight: Weight for BM25 scores (0-1)
            threshold: Minimum combined score (after normalization)

        Returns:
            List of results with hybrid scores
        """
        if not entries:
            return []

        if fields is None:
            fields = ["title", "description"]

        # Get semantic scores
        semantic_results = []
        if self.semantic_engine.available and semantic_weight > 0:
            semantic_results = self.semantic_engine.similarity_search(
                query, entries, top_k=len(entries), threshold=0.0, fields=fields
            )

        # Get BM25 scores
        bm25_scores = {}
        if self.bm25_available and bm25_weight > 0:
            try:
                from rank_bm25 import BM25Okapi

                # Prepare documents
                full_texts, tokenized_docs = self._prepare_documents(entries, fields)

                # Create BM25 index
                bm25 = BM25Okapi(tokenized_docs)

                # Score documents
                query_tokens = self._tokenize(query)
                scores = bm25.get_scores(query_tokens)

                # Store scores by entry index
                for i, score in enumerate(scores):
                    bm25_scores[i] = float(score)

            except Exception as e:
                logger.error(f"Error in BM25 search: {e}")

        # Combine scores
        hybrid_results = []

        # Create score mapping for semantic results
        semantic_score_map = {}
        if semantic_results:
            for result in semantic_results:
                # Find entry index
                for i, entry in enumerate(entries):
                    if entry.get("guid") == result["entry"].get("guid"):
                        semantic_score_map[i] = result["similarity"]
                        break

        # Normalize scores
        if semantic_score_map:
            max_semantic = max(semantic_score_map.values())
            if max_semantic > 0:
                semantic_score_map = {
                    k: v / max_semantic for k, v in semantic_score_map.items()
                }

        if bm25_scores:
            max_bm25 = max(bm25_scores.values())
            if max_bm25 > 0:
                bm25_scores = {k: v / max_bm25 for k, v in bm25_scores.items()}

        # Combine scores
        for i, entry in enumerate(entries):
            semantic_score = semantic_score_map.get(i, 0.0)
            bm25_score = bm25_scores.get(i, 0.0)

            # Calculate hybrid score
            hybrid_score = (semantic_weight * semantic_score) + (bm25_weight * bm25_score)

            if hybrid_score >= threshold:
                hybrid_results.append(
                    {
                        "entry": entry,
                        "hybrid_score": hybrid_score,
                        "semantic_score": semantic_score,
                        "bm25_score": bm25_score,
                    }
                )

        # Sort by hybrid score
        hybrid_results.sort(key=lambda x: x["hybrid_score"], reverse=True)

        return hybrid_results[:top_k]

    def document_search(
        self,
        query: str,
        entries: list[dict[str, Any]],
        top_k: int = 10,
        use_semantic: bool = True,
        use_bm25: bool = True,
    ) -> dict[str, Any]:
        """
        Document-wide search with full parsing and ranking.

        Args:
            query: Search query
            entries: RSS entries
            top_k: Number of results
            use_semantic: Use semantic search
            use_bm25: Use BM25 keyword search

        Returns:
            Search results with detailed scoring
        """
        if not entries:
            return {"success": True, "results": [], "query": query}

        # Determine weights
        if use_semantic and use_bm25:
            semantic_weight = 0.5
            bm25_weight = 0.5
        elif use_semantic:
            semantic_weight = 1.0
            bm25_weight = 0.0
        elif use_bm25:
            semantic_weight = 0.0
            bm25_weight = 1.0
        else:
            return {"success": False, "error": "Must enable at least one search method"}

        # Use all available fields for document-wide search
        fields = ["title", "subtitle", "summary", "description", "author"]

        # Perform hybrid search
        results = self.hybrid_search(
            query,
            entries,
            fields=fields,
            top_k=top_k,
            semantic_weight=semantic_weight,
            bm25_weight=bm25_weight,
            threshold=0.0,
        )

        return {
            "success": True,
            "query": query,
            "result_count": len(results),
            "results": results,
            "search_methods": {
                "semantic": use_semantic and self.semantic_engine.available,
                "bm25": use_bm25 and self.bm25_available,
            },
        }


# Initialize similarity search engine
similarity_engine = SimilaritySearchEngine()

# Initialize hybrid search engine
hybrid_engine = HybridSearchEngine(similarity_engine)


# Tool definitions using FastMCP
@mcp.tool(description="Fetch and parse an RSS feed from URL")
async def fetch_rss(
    url: str = Field(..., description="RSS feed URL to fetch"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Fetch and parse an RSS feed, returning clean structured data.

    Automatically filters out XML noise and provides easy access to:
    - Feed metadata (title, description, author, etc.)
    - Entries (articles/episodes) with clean content
    - Categories and tags

    Example URLs:
    - https://feeds.npr.org/1001/rss.xml
    - https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml
    """
    return await rss_parser.fetch_feed(url, use_cache)


@mcp.tool(description="Search RSS feed entries by title")
async def search_titles(
    url: str = Field(..., description="RSS feed URL"),
    query: str = Field(..., description="Search query for titles"),
    case_sensitive: bool = Field(False, description="Case-sensitive search"),
    regex: bool = Field(False, description="Use regex pattern matching"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """Search for entries matching the query in titles."""
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    results = rss_parser.search_entries(
        feed_data, query, fields=["title"], case_sensitive=case_sensitive, regex=regex
    )

    return {
        "success": True,
        "query": query,
        "field": "title",
        "match_count": len(results),
        "matches": results,
    }


@mcp.tool(description="Search RSS feed entries by description/content")
async def search_descriptions(
    url: str = Field(..., description="RSS feed URL"),
    query: str = Field(..., description="Search query for descriptions"),
    case_sensitive: bool = Field(False, description="Case-sensitive search"),
    regex: bool = Field(False, description="Use regex pattern matching"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """Search for entries matching the query in descriptions/content."""
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    results = rss_parser.search_entries(
        feed_data, query, fields=["description"], case_sensitive=case_sensitive, regex=regex
    )

    return {
        "success": True,
        "query": query,
        "field": "description",
        "match_count": len(results),
        "matches": results,
    }


@mcp.tool(description="Search across all fields (title, description, author, categories)")
async def search_all(
    url: str = Field(..., description="RSS feed URL"),
    query: str = Field(..., description="Search query"),
    case_sensitive: bool = Field(False, description="Case-sensitive search"),
    regex: bool = Field(False, description="Use regex pattern matching"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """Search for entries matching the query across all fields."""
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    results = rss_parser.search_entries(
        feed_data,
        query,
        fields=["title", "description", "author", "categories"],
        case_sensitive=case_sensitive,
        regex=regex,
    )

    return {
        "success": True,
        "query": query,
        "field": "all",
        "match_count": len(results),
        "matches": results,
    }


@mcp.tool(description="Find entries by author/speaker")
async def find_by_author(
    url: str = Field(..., description="RSS feed URL"),
    author: str = Field(..., description="Author/speaker name to search for"),
    exact_match: bool = Field(False, description="Require exact author name match"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """Find all entries by a specific author or speaker (useful for podcasts)."""
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])
    results = []

    for entry in entries:
        entry_author = entry.get("author", "")
        if not entry_author:
            continue

        if exact_match:
            if entry_author == author:
                results.append(entry)
        else:
            if author.lower() in entry_author.lower():
                results.append(entry)

    return {
        "success": True,
        "author": author,
        "match_count": len(results),
        "matches": results,
    }


@mcp.tool(description="List all unique authors/speakers with entry counts")
async def list_authors(
    url: str = Field(..., description="RSS feed URL"),
    min_count: int = Field(1, ge=1, description="Minimum number of entries per author"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    List all unique authors/speakers in the feed with their entry counts.

    Perfect for discovering who contributes to a podcast or blog.
    """
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    result = rss_parser.list_unique_values(feed_data, "author")

    if result.get("success") and min_count > 1:
        # Filter by minimum count
        distribution = result.get("distribution", {})
        filtered = {k: v for k, v in distribution.items() if v >= min_count}
        result["distribution"] = filtered
        result["unique_count"] = len(filtered)

    return result


@mcp.tool(description="List all categories/tags with entry counts")
async def list_categories(
    url: str = Field(..., description="RSS feed URL"),
    min_count: int = Field(1, ge=1, description="Minimum number of entries per category"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    List all unique categories/tags in the feed with their counts.

    Useful for understanding topic distribution.
    """
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])
    all_categories = []

    for entry in entries:
        all_categories.extend(entry.get("categories", []))

    counts = dict(Counter(all_categories).most_common())

    if min_count > 1:
        counts = {k: v for k, v in counts.items() if v >= min_count}

    return {
        "success": True,
        "field": "categories",
        "unique_count": len(counts),
        "total_count": len(all_categories),
        "distribution": counts,
    }


@mcp.tool(description="Get comprehensive feed statistics and analysis")
async def get_feed_statistics(
    url: str = Field(..., description="RSS feed URL"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Generate comprehensive statistics about the RSS feed.

    Includes:
    - Total entry count
    - Date range (earliest to latest)
    - Author statistics (count and distribution)
    - Category statistics
    - Media statistics (for podcasts)
    - Content length statistics
    """
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    return rss_parser.get_statistics(feed_data)


@mcp.tool(description="Filter entries by date range")
async def filter_by_date(
    url: str = Field(..., description="RSS feed URL"),
    start_date: str | None = Field(None, description="Start date (ISO format or natural)"),
    end_date: str | None = Field(None, description="End date (ISO format or natural)"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Filter feed entries by date range.

    Dates can be in ISO format (2024-01-01) or natural language that dateutil can parse.
    """
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    results = rss_parser.filter_by_date(feed_data, start_date, end_date)

    return {
        "success": True,
        "start_date": start_date,
        "end_date": end_date,
        "match_count": len(results),
        "matches": results,
    }


@mcp.tool(description="Get feed metadata (title, description, author, etc.)")
async def get_feed_metadata(
    url: str = Field(..., description="RSS feed URL"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Extract feed-level metadata.

    Returns information about the feed itself, not individual entries.
    """
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    return {
        "success": True,
        "url": feed_data.get("url"),
        "metadata": feed_data.get("metadata"),
    }


@mcp.tool(description="Get N most recent entries from feed")
async def get_latest_entries(
    url: str = Field(..., description="RSS feed URL"),
    count: int = Field(10, ge=1, le=100, description="Number of entries to retrieve"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """Get the N most recent entries from the feed."""
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])

    # Sort by published date (most recent first)
    sorted_entries = sorted(
        entries,
        key=lambda x: x.get("published", ""),
        reverse=True,
    )

    latest = sorted_entries[:count]

    return {
        "success": True,
        "count": len(latest),
        "entries": latest,
    }


@mcp.tool(description="Comprehensive feed analysis with recommendations")
async def analyze_feed(
    url: str = Field(..., description="RSS feed URL"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Perform comprehensive feed analysis.

    Provides insights, patterns, and recommendations about the feed content.
    """
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    stats = rss_parser.get_statistics(feed_data)
    metadata = feed_data.get("metadata", {})
    entries = feed_data.get("entries", [])

    # Analyze update frequency
    dates = [e.get("published", "") for e in entries if e.get("published")]
    update_frequency = "Unknown"

    if len(dates) >= 2:
        try:
            from dateutil import parser

            parsed_dates = sorted([parser.parse(d) for d in dates])
            if len(parsed_dates) >= 2:
                time_diff = (parsed_dates[-1] - parsed_dates[0]).days
                avg_days = time_diff / (len(parsed_dates) - 1) if len(parsed_dates) > 1 else 0

                if avg_days < 1:
                    update_frequency = "Multiple times daily"
                elif avg_days < 2:
                    update_frequency = "Daily"
                elif avg_days < 8:
                    update_frequency = "Weekly"
                elif avg_days < 32:
                    update_frequency = "Monthly"
                else:
                    update_frequency = "Infrequent"
        except Exception:
            pass

    # Detect feed type
    feed_type = "Unknown"
    has_media = any(e.get("media_url") for e in entries)

    if has_media:
        media_types = set(e.get("media_type", "") for e in entries if e.get("media_url"))
        if any("audio" in mt for mt in media_types):
            feed_type = "Podcast"
        elif any("video" in mt for mt in media_types):
            feed_type = "Video"
        else:
            feed_type = "Media"
    else:
        feed_type = "Blog/News"

    # Generate insights
    insights = []

    if stats.get("authors", {}).get("count", 0) > 10:
        insights.append("Multi-author publication with diverse contributors")
    elif stats.get("authors", {}).get("count", 0) == 1:
        insights.append("Single-author publication")

    if stats.get("media", {}).get("entries_with_media", 0) > 0:
        media_pct = (
            stats["media"]["entries_with_media"] / stats["total_entries"] * 100
        )
        insights.append(f"{media_pct:.1f}% of entries include media content")

    if len(stats.get("categories", {}).get("distribution", {})) > 20:
        insights.append("Highly categorized content with many topics")

    return {
        "success": True,
        "url": url,
        "feed_info": {
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "type": feed_type,
            "language": metadata.get("language"),
        },
        "statistics": stats,
        "patterns": {
            "update_frequency": update_frequency,
            "has_media": has_media,
            "has_categories": len(stats.get("categories", {}).get("distribution", {})) > 0,
        },
        "insights": insights,
    }


@mcp.tool(description="Clear the RSS feed cache")
async def clear_cache() -> dict[str, Any]:
    """Clear the internal RSS feed cache to force fresh fetches."""
    cache_size = len(rss_parser.cache)
    rss_parser.cache.clear()

    return {
        "success": True,
        "message": f"Cleared {cache_size} cached feeds",
    }


@mcp.tool(description="Semantic similarity search using AI embeddings")
async def similarity_search(
    url: str = Field(..., description="RSS feed URL"),
    query: str = Field(..., description="Search query text"),
    top_k: int = Field(10, ge=1, le=50, description="Number of top results to return"),
    threshold: float = Field(0.0, ge=0.0, le=1.0, description="Minimum similarity score (0-1)"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Perform semantic similarity search on feed entries using AI embeddings.

    Uses sentence transformers to find entries semantically similar to your query,
    even if they don't contain the exact keywords. More intelligent than keyword search.

    Example: Query "climate crisis" will find articles about "global warming",
    "environmental catastrophe", etc.

    Note: Requires sentence-transformers: pip install mcp-rss-search[similarity]
    """
    if not similarity_engine.available:
        return {
            "success": False,
            "error": "Similarity search not available. Install with: pip install mcp-rss-search[similarity]",
        }

    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])

    results = similarity_engine.similarity_search(query, entries, top_k=top_k, threshold=threshold)

    return {
        "success": True,
        "query": query,
        "match_count": len(results),
        "matches": results,
        "note": "Results ranked by semantic similarity (0-1)",
    }


@mcp.tool(description="Find duplicate or near-duplicate entries using semantic similarity")
async def find_duplicates(
    url: str = Field(..., description="RSS feed URL"),
    similarity_threshold: float = Field(
        0.85, ge=0.5, le=1.0, description="Similarity threshold for duplicates (0.5-1.0)"
    ),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Find duplicate or near-duplicate entries in the feed using semantic similarity.

    Useful for:
    - Detecting cross-posted content
    - Finding republished articles
    - Identifying content aggregation
    - Deduplicating multi-feed aggregators

    Note: Requires sentence-transformers: pip install mcp-rss-search[similarity]
    """
    if not similarity_engine.available:
        return {
            "success": False,
            "error": "Similarity search not available. Install with: pip install mcp-rss-search[similarity]",
        }

    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])

    duplicates = similarity_engine.find_duplicates(entries, similarity_threshold=similarity_threshold)

    return {
        "success": True,
        "duplicate_groups": len(duplicates),
        "duplicates": duplicates,
        "total_duplicates": sum(len(group) for group in duplicates),
    }


@mcp.tool(description="Find related entries to a specific entry")
async def find_related_entries(
    url: str = Field(..., description="RSS feed URL"),
    entry_index: int = Field(..., ge=0, description="Index of the entry to find related content for"),
    top_k: int = Field(5, ge=1, le=20, description="Number of related entries to return"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Find entries related to a specific entry using semantic similarity.

    Perfect for:
    - "Read more like this" recommendations
    - Topic exploration
    - Content discovery
    - Related article suggestions

    Note: Requires sentence-transformers: pip install mcp-rss-search[similarity]
    """
    if not similarity_engine.available:
        return {
            "success": False,
            "error": "Similarity search not available. Install with: pip install mcp-rss-search[similarity]",
        }

    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])

    if entry_index >= len(entries):
        return {
            "success": False,
            "error": f"Entry index {entry_index} out of range (max: {len(entries) - 1})",
        }

    source_entry = entries[entry_index]
    related = similarity_engine.find_related(source_entry, entries, top_k=top_k)

    return {
        "success": True,
        "source_entry": {
            "title": source_entry.get("title"),
            "index": entry_index,
        },
        "related_count": len(related),
        "related_entries": related,
    }


@mcp.tool(description="Cluster feed entries by semantic similarity")
async def cluster_by_topic(
    url: str = Field(..., description="RSS feed URL"),
    n_clusters: int = Field(5, ge=2, le=20, description="Number of topic clusters to create"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Automatically cluster feed entries into topic groups using semantic similarity.

    Uses K-means clustering on sentence embeddings to group related content.

    Use cases:
    - Topic discovery in news feeds
    - Content organization
    - Feed analysis
    - Automatic categorization

    Note: Requires sentence-transformers: pip install mcp-rss-search[similarity]
    """
    if not similarity_engine.available:
        return {
            "success": False,
            "error": "Similarity search not available. Install with: pip install mcp-rss-search[similarity]",
        }

    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])

    result = similarity_engine.cluster_entries(entries, n_clusters=n_clusters)

    return result


@mcp.tool(description="Semantic search in podcast subtitles (iTunes, Google Play, etc.)")
async def search_subtitles_semantic(
    url: str = Field(..., description="RSS feed URL"),
    query: str = Field(..., description="Search query text"),
    top_k: int = Field(10, ge=1, le=50, description="Number of top results"),
    threshold: float = Field(0.3, ge=0.0, le=1.0, description="Minimum similarity score"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Semantic similarity search specifically in podcast/episode subtitles.

    Searches the subtitle field which contains brief episode descriptions.
    Supports iTunes, Google Play, and standard podcast formats.

    Perfect for finding episodes by topic when you know the general subject.

    Note: Requires sentence-transformers: pip install mcp-rss-search[similarity]
    """
    if not similarity_engine.available:
        return {
            "success": False,
            "error": "Similarity search not available. Install with: pip install mcp-rss-search[similarity]",
        }

    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])

    # Search specifically in subtitle field
    results = similarity_engine.similarity_search(
        query, entries, top_k=top_k, threshold=threshold, fields=["subtitle"]
    )

    return {
        "success": True,
        "query": query,
        "field": "subtitle",
        "match_count": len(results),
        "matches": results,
        "note": "Searched in podcast subtitles (iTunes, Google Play, standard formats)",
    }


@mcp.tool(description="Semantic search in episode summaries/descriptions")
async def search_summaries_semantic(
    url: str = Field(..., description="RSS feed URL"),
    query: str = Field(..., description="Search query text"),
    top_k: int = Field(10, ge=1, le=50, description="Number of top results"),
    threshold: float = Field(0.3, ge=0.0, le=1.0, description="Minimum similarity score"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Semantic similarity search in episode summaries and descriptions.

    Searches both summary (short) and description (long) fields.
    Handles iTunes summary, Google Play descriptions, and standard RSS content.

    Best for finding episodes based on content topics and themes.

    Note: Requires sentence-transformers: pip install mcp-rss-search[similarity]
    """
    if not similarity_engine.available:
        return {
            "success": False,
            "error": "Similarity search not available. Install with: pip install mcp-rss-search[similarity]",
        }

    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])

    # Search in both summary and description fields
    results = similarity_engine.similarity_search(
        query, entries, top_k=top_k, threshold=threshold, fields=["summary", "description"]
    )

    return {
        "success": True,
        "query": query,
        "fields": ["summary", "description"],
        "match_count": len(results),
        "matches": results,
        "note": "Searched in summaries and descriptions across all podcast formats",
    }


@mcp.tool(description="Multi-field semantic search (custom field selection)")
async def search_multi_field_semantic(
    url: str = Field(..., description="RSS feed URL"),
    query: str = Field(..., description="Search query text"),
    fields: list[str] = Field(
        ["title", "subtitle", "summary"],
        description="Fields to search (title, subtitle, summary, description, author, etc.)",
    ),
    top_k: int = Field(10, ge=1, le=50, description="Number of top results"),
    threshold: float = Field(0.3, ge=0.0, le=1.0, description="Minimum similarity score"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Semantic search across multiple custom fields.

    Allows you to specify exactly which fields to search:
    - title: Episode/article title
    - subtitle: Brief episode description (podcasts)
    - summary: Short summary (iTunes, etc.)
    - description: Full description/content
    - author: Author/speaker name
    - categories: Tags/categories

    Useful when you know which fields are most relevant for your query.

    Note: Requires sentence-transformers: pip install mcp-rss-search[similarity]
    """
    if not similarity_engine.available:
        return {
            "success": False,
            "error": "Similarity search not available. Install with: pip install mcp-rss-search[similarity]",
        }

    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])

    # Search in specified fields
    results = similarity_engine.similarity_search(
        query, entries, top_k=top_k, threshold=threshold, fields=fields
    )

    return {
        "success": True,
        "query": query,
        "fields": fields,
        "match_count": len(results),
        "matches": results,
    }


@mcp.tool(description="Inspect feed schema and available fields")
async def inspect_feed_schema(
    url: str = Field(..., description="RSS feed URL"),
    use_cache: bool = Field(True, description="Use cached feed if available"),
) -> dict[str, Any]:
    """
    Inspect feed to see which fields are available.

    Shows:
    - Available fields per entry
    - Which schema types are detected (iTunes, Google Play, etc.)
    - Field coverage (how many entries have each field)
    - Sample values from each field

    Useful for understanding feed structure before doing targeted searches.
    """
    feed_data = await rss_parser.fetch_feed(url, use_cache)

    if not feed_data.get("success"):
        return feed_data

    entries = feed_data.get("entries", [])

    if not entries:
        return {
            "success": True,
            "message": "No entries in feed",
            "schemas": [],
        }

    # Detect which fields are present
    all_fields = set()
    field_counts = {}

    for entry in entries:
        for field, value in entry.items():
            all_fields.add(field)
            if value:  # Count non-empty values
                field_counts[field] = field_counts.get(field, 0) + 1

    # Calculate coverage
    total_entries = len(entries)
    field_coverage = {
        field: {"count": count, "percentage": round((count / total_entries) * 100, 1)}
        for field, count in field_counts.items()
    }

    # Get sample values
    sample_values = {}
    first_entry = entries[0]
    for field in all_fields:
        value = first_entry.get(field)
        if value:
            # Truncate long values
            value_str = str(value)
            if len(value_str) > 100:
                value_str = value_str[:100] + "..."
            sample_values[field] = value_str

    # Detect schemas
    schemas = []
    if any(entry.get("subtitle") or entry.get("episode") or entry.get("season") for entry in entries):
        schemas.append("iTunes Podcast")
    if any("explicit" in entry for entry in entries):
        schemas.append("iTunes (with explicit flag)")
    if field_counts.get("media_url", 0) > 0:
        schemas.append("Media RSS (enclosures)")
    if field_counts.get("summary", 0) > 0 and field_counts.get("description", 0) > 0:
        schemas.append("Enhanced RSS (summary + description)")

    # Identify best fields for semantic search
    searchable_fields = []
    if field_coverage.get("subtitle", {}).get("percentage", 0) > 50:
        searchable_fields.append("subtitle")
    if field_coverage.get("summary", {}).get("percentage", 0) > 50:
        searchable_fields.append("summary")
    if field_coverage.get("description", {}).get("percentage", 0) > 50:
        searchable_fields.append("description")
    if field_coverage.get("title", {}).get("percentage", 0) > 50:
        searchable_fields.append("title")

    return {
        "success": True,
        "total_entries": total_entries,
        "detected_schemas": schemas,
        "available_fields": sorted(all_fields),
        "field_coverage": field_coverage,
        "sample_values": sample_values,
        "recommended_search_fields": searchable_fields,
        "note": "Use 'search_multi_field_semantic' with recommended_search_fields for best results",
    }


@mcp.tool()
async def get_model_info() -> str:
    """
    Get information about the current embedding model.

    Returns model name, status, and configuration.

    Returns:
        JSON string with model information including:
        - available: Whether similarity search is available
        - configured_model: Model name configured
        - loaded: Whether model is currently loaded
        - model_name: Active model name
        - max_seq_length: Maximum sequence length
        - embedding_dimension: Embedding vector dimension

    Example:
        >>> info = await get_model_info()
        >>> # Returns: {"available": true, "configured_model": "all-MiniLM-L6-v2", ...}
    """
    info = similarity_engine.get_model_info()
    return _dump_json(info)


@mcp.tool()
async def configure_model(model_name: str) -> str:
    """
    Configure/change the embedding model for similarity search.

    Allows runtime configuration of the sentence transformer model.
    The model will be downloaded on first use if not cached.

    Args:
        model_name: Sentence transformer model name.
                   Common models:
                   - "all-MiniLM-L6-v2" (default) - Fast, lightweight (80MB)
                   - "all-mpnet-base-v2" - Higher quality (420MB)
                   - "multi-qa-mpnet-base-dot-v1" - Best for Q&A
                   - "paraphrase-multilingual-MiniLM-L12-v2" - Multilingual
                   - "all-distilroberta-v1" - Fast, good quality (290MB)
                   - "all-MiniLM-L12-v2" - Balanced (120MB)

    Returns:
        JSON string with configuration result including model info

    Example:
        >>> result = await configure_model("all-mpnet-base-v2")
        >>> # Changes model to higher quality version
    """
    if not similarity_engine.available:
        return _dump_json(
            {
                "success": False,
                "error": "Similarity search not available. Install with: pip install sentence-transformers",
            }
        )

    try:
        # Update model name and clear cached model to force reload
        similarity_engine.model_name = model_name
        similarity_engine.model = None

        # Get new model info (will trigger load on next use)
        info = similarity_engine.get_model_info()

        return _dump_json(
            {
                "success": True,
                "message": f"Model configured to: {model_name}",
                "model_info": info,
                "note": "Model will be loaded on first use",
            }
        )
    except Exception as e:
        return _dump_json({"success": False, "error": f"Failed to configure model: {str(e)}"})


@mcp.tool()
async def hybrid_search(
    url: str,
    query: str,
    fields: list[str] | None = None,
    top_k: int = 10,
    semantic_weight: float = 0.5,
    bm25_weight: float = 0.5,
    threshold: float = 0.0,
    use_cache: bool = True,
) -> str:
    """
    Hybrid search combining BM25 (keyword) and semantic similarity.

    Combines traditional keyword-based BM25 ranking with neural semantic similarity
    for more robust search results. Each result includes semantic_score, bm25_score,
    and hybrid_score.

    Args:
        url: RSS feed URL
        query: Search query
        fields: Fields to search (default: ["title", "description"])
               Available: title, subtitle, summary, description, author, categories
        top_k: Number of results to return (1-100)
        semantic_weight: Weight for semantic similarity (0-1, default: 0.5)
        bm25_weight: Weight for BM25 score (0-1, default: 0.5)
        threshold: Minimum hybrid score (0-1, default: 0.0)
        use_cache: Use cached feed if available

    Returns:
        JSON string with hybrid search results including separate scores

    Example:
        >>> results = await hybrid_search(
        ...     url="https://podcast-feed.xml",
        ...     query="machine learning ethics",
        ...     semantic_weight=0.6,
        ...     bm25_weight=0.4,
        ...     top_k=5
        ... )
    """
    if not hybrid_engine.semantic_engine.available:
        return _dump_json(
            {
                "success": False,
                "error": "Hybrid search requires similarity features. Install with: pip install 'mcp-rss-search[similarity]'",
            }
        )

    if not hybrid_engine.bm25_available:
        return _dump_json(
            {
                "success": False,
                "error": "Hybrid search requires BM25. Install with: pip install rank-bm25",
            }
        )

    # Validate weights
    if semantic_weight < 0 or semantic_weight > 1:
        return _dump_json({"success": False, "error": "semantic_weight must be between 0 and 1"})

    if bm25_weight < 0 or bm25_weight > 1:
        return _dump_json({"success": False, "error": "bm25_weight must be between 0 and 1"})

    # Validate top_k
    if top_k < 1 or top_k > 100:
        return _dump_json({"success": False, "error": "top_k must be between 1 and 100"})

    try:
        # Fetch feed
        feed_data = await rss_parser.fetch_feed(url, use_cache=use_cache)

        if not feed_data.get("success"):
            return _dump_json(feed_data)

        entries = feed_data.get("entries", [])

        if not entries:
            return _dump_json({"success": True, "matches": [], "match_count": 0, "query": query})

        # Perform hybrid search
        results = hybrid_engine.hybrid_search(
            query=query,
            entries=entries,
            fields=fields,
            top_k=top_k,
            semantic_weight=semantic_weight,
            bm25_weight=bm25_weight,
            threshold=threshold,
        )

        return _dump_json(
            {
                "success": True,
                "query": query,
                "fields": fields or ["title", "description"],
                "semantic_weight": semantic_weight,
                "bm25_weight": bm25_weight,
                "threshold": threshold,
                "match_count": len(results),
                "matches": results,
            }
        )

    except Exception as e:
        logger.error(f"Error in hybrid_search: {e}", exc_info=True)
        return _dump_json({"success": False, "error": str(e)})


@mcp.tool()
async def document_search(
    url: str,
    query: str,
    top_k: int = 10,
    use_semantic: bool = True,
    use_bm25: bool = True,
    use_cache: bool = True,
) -> str:
    """
    Document-wide search with full parsing across all available fields.

    Searches across ALL available fields: title, subtitle, summary, description, author.
    Automatically uses hybrid retrieval (BM25 + semantic) for best results.

    This is the most comprehensive search tool - perfect for finding content when you're
    not sure which field contains the information you need.

    Args:
        url: RSS feed URL
        query: Search query
        top_k: Number of results to return (1-100)
        use_semantic: Include semantic similarity scoring (default: True)
        use_bm25: Include BM25 keyword scoring (default: True)
        use_cache: Use cached feed if available

    Returns:
        JSON string with comprehensive search results including all scores

    Example:
        >>> results = await document_search(
        ...     url="https://podcast-feed.xml",
        ...     query="interview about quantum computing applications",
        ...     top_k=10
        ... )
        >>> # Searches: title, subtitle, summary, description, author
    """
    # Check requirements based on what's enabled
    if use_semantic and not hybrid_engine.semantic_engine.available:
        return _dump_json(
            {
                "success": False,
                "error": "Semantic search requires similarity features. Install with: pip install 'mcp-rss-search[similarity]'",
            }
        )

    if use_bm25 and not hybrid_engine.bm25_available:
        return _dump_json(
            {
                "success": False,
                "error": "BM25 search requires rank-bm25. Install with: pip install rank-bm25",
            }
        )

    # Validate top_k
    if top_k < 1 or top_k > 100:
        return _dump_json({"success": False, "error": "top_k must be between 1 and 100"})

    try:
        # Fetch feed
        feed_data = await rss_parser.fetch_feed(url, use_cache=use_cache)

        if not feed_data.get("success"):
            return _dump_json(feed_data)

        entries = feed_data.get("entries", [])

        if not entries:
            return _dump_json({"success": True, "matches": [], "match_count": 0, "query": query})

        # Perform document-wide search
        result = hybrid_engine.document_search(
            query=query,
            entries=entries,
            top_k=top_k,
            use_semantic=use_semantic,
            use_bm25=use_bm25,
        )

        return _dump_json(result)

    except Exception as e:
        logger.error(f"Error in document_search: {e}", exc_info=True)
        return _dump_json({"success": False, "error": str(e)})


def main():
    """Main server entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="MCP RSS Search Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9100, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting MCP RSS Search Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting MCP RSS Search Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
