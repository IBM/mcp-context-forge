# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/tool_search_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Akshay Shinde

Tool Search Service — experimental tool discovery for large catalogs.

Provides BM25 and regex search over the gateway's tool catalog so LLMs can
discover tools on demand instead of receiving the full listing.

No external dependencies — the BM25 implementation is pure Python.

Examples:
    >>> svc = ToolSearchService()
    >>> tools = [
    ...     {"name": "send_email", "description": "Send an email", "inputSchema": {}},
    ...     {"name": "delete_record", "description": "Delete a DB record", "inputSchema": {}},
    ... ]
    >>> results = svc.bm25_search(tools, "email", limit=5)
    >>> results[0]["name"]
    'send_email'
    >>> results = svc.regex_search(tools, "delete", limit=5)
    >>> results[0]["name"]
    'delete_record'
"""

# Standard
import math
import re
from typing import Any, Dict, List


def _tokenize(text: str) -> List[str]:
    """Lowercase and split on non-alphanumeric characters."""
    return re.split(r"[^a-z0-9]+", text.lower().strip())


def _tool_corpus_text(tool: Dict[str, Any]) -> str:
    """Concatenate all searchable text fields for a tool."""
    parts: List[str] = []

    name = tool.get("name") or ""
    parts.append(name.replace("_", " "))

    desc = tool.get("description") or ""
    parts.append(desc)

    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") or {}
    for param_name, param_def in props.items():
        parts.append(param_name.replace("_", " "))
        if isinstance(param_def, dict):
            param_desc = param_def.get("description") or ""
            parts.append(param_desc)

    return " ".join(parts)


class ToolSearchService:
    """Stateless search helpers — instantiate per call or share as singleton."""

    def bm25_search(self, tools: List[Dict[str, Any]], query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Rank tools by BM25 Okapi relevance and return top *limit* results.

        Searches across tool name, description, parameter names, and parameter
        descriptions.  The index is built in-memory from *tools* on each call
        (no stale-index risk).

        Args:
            tools: List of tool dicts with at minimum ``name``, ``description``,
                and ``inputSchema`` keys.
            query: Natural-language or keyword search string.
            limit: Maximum number of results to return.

        Returns:
            Tools sorted by BM25 score (descending), truncated to *limit*.

        Examples:
            >>> svc = ToolSearchService()
            >>> tools = [
            ...     {"name": "send_email", "description": "Send email", "inputSchema": {}},
            ...     {"name": "query_db", "description": "Query database", "inputSchema": {}},
            ... ]
            >>> results = svc.bm25_search(tools, "email", limit=1)
            >>> results[0]["name"]
            'send_email'
        """
        if not tools or not query.strip():
            return []

        k1 = 1.5
        b = 0.75

        # Tokenize all documents
        corpus: List[List[str]] = [_tokenize(_tool_corpus_text(t)) for t in tools]

        # Compute document lengths and average
        doc_lengths = [len(doc) for doc in corpus]
        avg_dl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1.0

        # Build inverted index: term -> set of doc indices
        df: Dict[str, int] = {}
        for doc in corpus:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1

        n_docs = len(corpus)
        query_terms = _tokenize(query)

        scores: List[float] = []
        for doc_idx, doc in enumerate(corpus):
            tf_map: Dict[str, int] = {}
            for term in doc:
                tf_map[term] = tf_map.get(term, 0) + 1

            dl = doc_lengths[doc_idx]
            score = 0.0
            for term in query_terms:
                if term not in df:
                    continue
                tf = tf_map.get(term, 0)
                idf = math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1)
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * dl / avg_dl)
                score += idf * (numerator / denominator)
            scores.append(score)

        # Sort by score descending, filter zero scores
        ranked = sorted(
            ((score, idx) for idx, score in enumerate(scores) if score > 0),
            key=lambda x: x[0],
            reverse=True,
        )

        return [tools[idx] for _, idx in ranked[:limit]]

    def regex_search(self, tools: List[Dict[str, Any]], pattern: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Filter tools whose searchable text matches *pattern* (case-insensitive).

        Args:
            tools: List of tool dicts.
            pattern: Regex pattern string.  Invalid patterns return an empty list.
            limit: Maximum number of results to return.

        Returns:
            Matching tools in catalog order, truncated to *limit*.

        Examples:
            >>> svc = ToolSearchService()
            >>> tools = [
            ...     {"name": "send_email", "description": "Send email", "inputSchema": {}},
            ...     {"name": "query_db", "description": "Query database", "inputSchema": {}},
            ... ]
            >>> results = svc.regex_search(tools, "email", limit=5)
            >>> results[0]["name"]
            'send_email'
            >>> results = svc.regex_search(tools, "[invalid", limit=5)
            >>> results
            []
        """
        if not tools:
            return []

        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return []

        matches: List[Dict[str, Any]] = []
        for tool in tools:
            if compiled.search(_tool_corpus_text(tool)):
                matches.append(tool)
                if len(matches) >= limit:
                    break

        return matches
