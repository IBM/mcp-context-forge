#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/chunker_server/src/chunker_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Chunker FastMCP Server

Advanced text chunking and splitting server with multiple strategies using FastMCP framework.
Supports semantic chunking, recursive splitting, markdown-aware chunking, and more.
"""

import logging
import re
import sys
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

# Configure logging to stderr to avoid MCP protocol interference
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Create FastMCP server instance
mcp = FastMCP(name="chunker-server", version="2.0.0")


class TextChunker:
    """Advanced text chunking with multiple strategies."""

    def __init__(self):
        """Initialize the chunker."""
        self.available_strategies = self._check_available_strategies()

    def _check_available_strategies(self) -> dict[str, bool]:
        """Check which chunking libraries are available."""
        strategies = {}

        try:
            from langchain_text_splitters import (
                MarkdownHeaderTextSplitter,
                RecursiveCharacterTextSplitter,
            )

            strategies["langchain"] = True
        except ImportError:
            strategies["langchain"] = False

        try:
            import nltk

            strategies["nltk"] = True
        except ImportError:
            strategies["nltk"] = False

        try:
            import spacy

            strategies["spacy"] = True
        except ImportError:
            strategies["spacy"] = False

        strategies["basic"] = True  # Always available

        return strategies

    def recursive_chunk(
        self,
        text: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: list[str] | None = None,
    ) -> dict[str, Any]:
        """Recursive character-based chunking."""
        try:
            if self.available_strategies.get("langchain"):
                from langchain_text_splitters import RecursiveCharacterTextSplitter

                if separators is None:
                    separators = ["\n\n", "\n", ". ", " ", ""]

                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    separators=separators,
                    length_function=len,
                    is_separator_regex=False,
                )

                chunks = splitter.split_text(text)
            else:
                # Fallback to basic implementation
                chunks = self._basic_recursive_chunk(text, chunk_size, chunk_overlap, separators)

            return {
                "success": True,
                "strategy": "recursive",
                "chunks": chunks,
                "chunk_count": len(chunks),
                "total_length": sum(len(chunk) for chunk in chunks),
                "average_chunk_size": sum(len(chunk) for chunk in chunks) / len(chunks)
                if chunks
                else 0,
            }

        except Exception as e:
            logger.error(f"Error in recursive chunking: {e}")
            return {"success": False, "error": str(e)}

    def _basic_recursive_chunk(
        self, text: str, chunk_size: int, chunk_overlap: int, separators: list[str] | None = None
    ) -> list[str]:
        """Basic recursive chunking implementation."""
        if separators is None:
            separators = ["\n\n", "\n", ". ", " "]

        def split_text_recursive(text: str, separators: list[str]) -> list[str]:
            if not separators or len(text) <= chunk_size:
                return [text] if text else []

            separator = separators[0]
            remaining_separators = separators[1:]

            parts = text.split(separator)
            chunks = []
            current_chunk = ""

            for part in parts:
                test_chunk = current_chunk + (separator if current_chunk else "") + part

                if len(test_chunk) <= chunk_size:
                    current_chunk = test_chunk
                else:
                    if current_chunk:
                        chunks.append(current_chunk)

                    if len(part) > chunk_size:
                        # Recursively split large parts
                        sub_chunks = split_text_recursive(part, remaining_separators)
                        chunks.extend(sub_chunks)
                        current_chunk = ""
                    else:
                        current_chunk = part

            if current_chunk:
                chunks.append(current_chunk)

            return chunks

        chunks = split_text_recursive(text, separators)

        # Add overlap if specified
        if chunk_overlap > 0 and len(chunks) > 1:
            overlapped_chunks = []
            for i, chunk in enumerate(chunks):
                if i == 0:
                    overlapped_chunks.append(chunk)
                else:
                    # Add overlap from previous chunk
                    prev_chunk = chunks[i - 1]
                    overlap_text = (
                        prev_chunk[-chunk_overlap:]
                        if len(prev_chunk) > chunk_overlap
                        else prev_chunk
                    )
                    overlapped_chunks.append(overlap_text + " " + chunk)

            return overlapped_chunks

        return chunks

    def markdown_chunk(
        self,
        text: str,
        headers_to_split_on: list[str] = ["#", "##", "###"],
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
    ) -> dict[str, Any]:
        """Markdown-aware chunking that respects header structure."""
        try:
            if self.available_strategies.get("langchain"):
                from langchain_text_splitters import (
                    MarkdownHeaderTextSplitter,
                    RecursiveCharacterTextSplitter,
                )

                # First split by headers
                headers = [(header, header) for header in headers_to_split_on]
                header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
                header_chunks = header_splitter.split_text(text)

                # Then split large chunks further
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=chunk_size, chunk_overlap=chunk_overlap
                )

                final_chunks = []
                for doc in header_chunks:
                    if len(doc.page_content) > chunk_size:
                        sub_chunks = text_splitter.split_text(doc.page_content)
                        for sub_chunk in sub_chunks:
                            final_chunks.append({"content": sub_chunk, "metadata": doc.metadata})
                    else:
                        final_chunks.append({"content": doc.page_content, "metadata": doc.metadata})

                chunks = [chunk["content"] for chunk in final_chunks]
                metadata = [chunk["metadata"] for chunk in final_chunks]

            else:
                # Basic markdown chunking
                chunks, metadata = self._basic_markdown_chunk(text, headers_to_split_on, chunk_size)

            return {
                "success": True,
                "strategy": "markdown",
                "chunks": chunks,
                "metadata": metadata,
                "chunk_count": len(chunks),
                "headers_used": headers_to_split_on,
            }

        except Exception as e:
            logger.error(f"Error in markdown chunking: {e}")
            return {"success": False, "error": str(e)}

    def _basic_markdown_chunk(
        self, text: str, headers: list[str], chunk_size: int
    ) -> tuple[list[str], list[dict]]:
        """Basic markdown chunking implementation."""
        sections = []
        current_section = ""
        current_headers = {}

        lines = text.split("\n")

        for line in lines:
            # Check if line is a header
            is_header = False
            for header in headers:
                if line.strip().startswith(header + " "):
                    # Start new section
                    if current_section:
                        sections.append(
                            {"content": current_section.strip(), "headers": current_headers.copy()}
                        )

                    current_section = line + "\n"
                    header_text = line.strip()[len(header) :].strip()
                    current_headers[header] = header_text
                    is_header = True
                    break

            if not is_header:
                current_section += line + "\n"

        # Add final section
        if current_section:
            sections.append({"content": current_section.strip(), "headers": current_headers.copy()})

        # Split large sections further
        final_chunks = []
        final_metadata = []

        for section in sections:
            if len(section["content"]) > chunk_size:
                # Split large sections
                sub_chunks = self._basic_recursive_chunk(section["content"], chunk_size, 100)
                for sub_chunk in sub_chunks:
                    final_chunks.append(sub_chunk)
                    final_metadata.append(section["headers"])
            else:
                final_chunks.append(section["content"])
                final_metadata.append(section["headers"])

        return final_chunks, final_metadata

    def sentence_chunk(
        self, text: str, sentences_per_chunk: int = 5, overlap_sentences: int = 1
    ) -> dict[str, Any]:
        """Sentence-based chunking."""
        try:
            # Basic sentence splitting (can be enhanced with NLTK)
            if self.available_strategies.get("nltk"):
                import nltk

                try:
                    nltk.data.find("tokenizers/punkt")
                except LookupError:
                    nltk.download("punkt", quiet=True)

                sentences = nltk.sent_tokenize(text)
            else:
                # Basic sentence splitting with regex
                sentences = self._basic_sentence_split(text)

            chunks = []
            for i in range(0, len(sentences), sentences_per_chunk - overlap_sentences):
                chunk_sentences = sentences[i : i + sentences_per_chunk]
                chunk = " ".join(chunk_sentences)
                chunks.append(chunk)

                # Stop if we've reached the end
                if i + sentences_per_chunk >= len(sentences):
                    break

            return {
                "success": True,
                "strategy": "sentence",
                "chunks": chunks,
                "chunk_count": len(chunks),
                "total_sentences": len(sentences),
                "sentences_per_chunk": sentences_per_chunk,
            }

        except Exception as e:
            logger.error(f"Error in sentence chunking: {e}")
            return {"success": False, "error": str(e)}

    def _basic_sentence_split(self, text: str) -> list[str]:
        """Basic sentence splitting using regex."""
        # Split on sentence endings
        sentences = re.split(r"[.!?]+\s+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        return sentences

    def fixed_size_chunk(
        self,
        text: str,
        chunk_size: int = 1000,
        overlap: int = 0,
        split_on_word_boundary: bool = True,
    ) -> dict[str, Any]:
        """Fixed-size chunking with optional word boundary preservation."""
        try:
            chunks = []
            start = 0

            while start < len(text):
                end = start + chunk_size

                if end >= len(text):
                    # Last chunk
                    chunk = text[start:]
                    if chunk.strip():
                        chunks.append(chunk)
                    break

                chunk = text[start:end]

                # Adjust to word boundary if requested
                if split_on_word_boundary and end < len(text):
                    # Find last space within chunk
                    last_space = chunk.rfind(" ")
                    if last_space > chunk_size * 0.8:  # Don't go too far back
                        chunk = chunk[:last_space]
                        end = start + last_space

                chunks.append(chunk)
                start = end - overlap

            return {
                "success": True,
                "strategy": "fixed_size",
                "chunks": chunks,
                "chunk_count": len(chunks),
                "chunk_size": chunk_size,
                "overlap": overlap,
            }

        except Exception as e:
            logger.error(f"Error in fixed-size chunking: {e}")
            return {"success": False, "error": str(e)}

    def semantic_chunk(
        self,
        text: str,
        min_chunk_size: int = 200,
        max_chunk_size: int = 2000,
        similarity_threshold: float = 0.8,
    ) -> dict[str, Any]:
        """Semantic chunking based on content similarity."""
        try:
            # For now, implement a simple semantic chunking based on paragraphs
            # This can be enhanced with embeddings and similarity measures

            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

            chunks = []
            current_chunk = ""

            for paragraph in paragraphs:
                test_chunk = current_chunk + ("\n\n" if current_chunk else "") + paragraph

                if len(test_chunk) <= max_chunk_size:
                    current_chunk = test_chunk
                elif len(current_chunk) >= min_chunk_size:
                    chunks.append(current_chunk)
                    current_chunk = paragraph
                else:
                    # Current chunk too small, but adding would make it too big
                    if len(paragraph) > max_chunk_size:
                        # Split the large paragraph
                        if current_chunk:
                            chunks.append(current_chunk)
                        sub_chunks = self._split_large_text(
                            paragraph, max_chunk_size, min_chunk_size
                        )
                        chunks.extend(sub_chunks)
                        current_chunk = ""
                    else:
                        current_chunk = test_chunk

            if current_chunk:
                chunks.append(current_chunk)

            return {
                "success": True,
                "strategy": "semantic",
                "chunks": chunks,
                "chunk_count": len(chunks),
                "min_chunk_size": min_chunk_size,
                "max_chunk_size": max_chunk_size,
                "average_chunk_size": sum(len(chunk) for chunk in chunks) / len(chunks)
                if chunks
                else 0,
            }

        except Exception as e:
            logger.error(f"Error in semantic chunking: {e}")
            return {"success": False, "error": str(e)}

    def _split_large_text(self, text: str, max_size: int, min_size: int) -> list[str]:
        """Split large text into smaller chunks."""
        chunks = []
        words = text.split()
        current_chunk = ""

        for word in words:
            test_chunk = current_chunk + (" " if current_chunk else "") + word

            if len(test_chunk) <= max_size:
                current_chunk = test_chunk
            else:
                if len(current_chunk) >= min_size:
                    chunks.append(current_chunk)
                    current_chunk = word
                else:
                    current_chunk = test_chunk  # Keep growing if below minimum

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def analyze_text(self, text: str) -> dict[str, Any]:
        """Analyze text to recommend optimal chunking strategy."""
        try:
            analysis = {
                "total_length": len(text),
                "line_count": len(text.split("\n")),
                "paragraph_count": len([p for p in text.split("\n\n") if p.strip()]),
                "word_count": len(text.split()),
                "has_markdown_headers": bool(re.search(r"^#+\s", text, re.MULTILINE)),
                "has_numbered_sections": bool(re.search(r"^\d+\.", text, re.MULTILINE)),
                "has_bullet_points": bool(re.search(r"^[\*\-\+]\s", text, re.MULTILINE)),
                "average_paragraph_length": 0,
                "average_sentence_length": 0,
            }

            # Calculate average paragraph length
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            if paragraphs:
                analysis["average_paragraph_length"] = sum(len(p) for p in paragraphs) / len(
                    paragraphs
                )

            # Calculate average sentence length (basic)
            sentences = self._basic_sentence_split(text)
            if sentences:
                analysis["average_sentence_length"] = sum(len(s) for s in sentences) / len(
                    sentences
                )

            # Recommend chunking strategy
            recommendations = []

            if analysis["has_markdown_headers"]:
                recommendations.append(
                    {
                        "strategy": "markdown",
                        "reason": "Text contains markdown headers - use markdown-aware chunking",
                        "suggested_params": {
                            "headers_to_split_on": ["#", "##", "###"],
                            "chunk_size": 1500,
                        },
                    }
                )

            if analysis["average_paragraph_length"] > 500:
                recommendations.append(
                    {
                        "strategy": "semantic",
                        "reason": "Large paragraphs detected - semantic chunking recommended",
                        "suggested_params": {"min_chunk_size": 300, "max_chunk_size": 2000},
                    }
                )

            if analysis["total_length"] > 10000:
                recommendations.append(
                    {
                        "strategy": "recursive",
                        "reason": "Large document - recursive chunking with overlap recommended",
                        "suggested_params": {"chunk_size": 1000, "chunk_overlap": 200},
                    }
                )

            if not recommendations:
                recommendations.append(
                    {
                        "strategy": "fixed_size",
                        "reason": "Standard text - fixed-size chunking suitable",
                        "suggested_params": {"chunk_size": 1000, "split_on_word_boundary": True},
                    }
                )

            analysis["recommendations"] = recommendations

            return {"success": True, "analysis": analysis}

        except Exception as e:
            logger.error(f"Error analyzing text: {e}")
            return {"success": False, "error": str(e)}

    def get_chunking_strategies(self) -> dict[str, Any]:
        """Get available chunking strategies and their capabilities."""
        return {
            "available_strategies": self.available_strategies,
            "strategies": {
                "recursive": {
                    "description": "Hierarchical splitting with multiple separators",
                    "best_for": "General text, mixed content",
                    "parameters": ["chunk_size", "chunk_overlap", "separators"],
                    "available": self.available_strategies.get("langchain", True),
                },
                "markdown": {
                    "description": "Header-aware chunking for markdown documents",
                    "best_for": "Markdown documents, structured content",
                    "parameters": ["headers_to_split_on", "chunk_size", "chunk_overlap"],
                    "available": self.available_strategies.get("langchain", True),
                },
                "semantic": {
                    "description": "Content-aware chunking based on semantic boundaries",
                    "best_for": "Articles, essays, narrative text",
                    "parameters": ["min_chunk_size", "max_chunk_size", "similarity_threshold"],
                    "available": True,
                },
                "sentence": {
                    "description": "Sentence-based chunking with overlap",
                    "best_for": "Precise sentence-level processing",
                    "parameters": ["sentences_per_chunk", "overlap_sentences"],
                    "available": True,
                },
                "fixed_size": {
                    "description": "Fixed character count chunking",
                    "best_for": "Uniform chunk sizes, simple splitting",
                    "parameters": ["chunk_size", "overlap", "split_on_word_boundary"],
                    "available": True,
                },
            },
            "libraries": {
                "langchain": self.available_strategies.get("langchain", False),
                "nltk": self.available_strategies.get("nltk", False),
                "spacy": self.available_strategies.get("spacy", False),
            },
        }


# Initialize chunker
chunker = TextChunker()


# Tool definitions using FastMCP
@mcp.tool(
    description="Chunk text using various strategies (recursive, semantic, sentence, fixed_size)",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def chunk_text(
    text: str = Field(..., description="Text to chunk"),
    chunk_size: int = Field(
        1000, ge=100, le=100000, description="Maximum chunk size in characters"
    ),
    chunk_overlap: int = Field(200, ge=0, description="Overlap between chunks in characters"),
    chunking_strategy: str = Field(
        "recursive",
        pattern="^(recursive|semantic|sentence|fixed_size)$",
        description="Chunking strategy to use",
    ),
    separators: list[str] | None = Field(None, description="Custom separators for splitting"),
    preserve_structure: bool = Field(True, description="Preserve document structure when possible"),
) -> dict[str, Any]:
    """Chunk text using the specified strategy."""

    if chunking_strategy == "recursive":
        return chunker.recursive_chunk(
            text=text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=separators
        )
    elif chunking_strategy == "semantic":
        return chunker.semantic_chunk(text=text, max_chunk_size=chunk_size)
    elif chunking_strategy == "sentence":
        return chunker.sentence_chunk(text=text)
    elif chunking_strategy == "fixed_size":
        return chunker.fixed_size_chunk(text=text, chunk_size=chunk_size, overlap=chunk_overlap)
    else:
        return {"success": False, "error": f"Unknown strategy: {chunking_strategy}"}


@mcp.tool(
    description="Chunk markdown text with header awareness",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def chunk_markdown(
    text: str = Field(..., description="Markdown text to chunk"),
    headers_to_split_on: list[str] = Field(["#", "##", "###"], description="Headers to split on"),
    chunk_size: int = Field(1000, ge=100, le=100000, description="Maximum chunk size"),
    chunk_overlap: int = Field(100, ge=0, description="Overlap between chunks"),
) -> dict[str, Any]:
    """Chunk markdown text with awareness of header structure."""
    return chunker.markdown_chunk(
        text=text,
        headers_to_split_on=headers_to_split_on,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


@mcp.tool(
    description="Semantic chunking based on content similarity",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def semantic_chunk(
    text: str = Field(..., description="Text to chunk semantically"),
    min_chunk_size: int = Field(200, ge=50, description="Minimum chunk size"),
    max_chunk_size: int = Field(2000, ge=100, le=100000, description="Maximum chunk size"),
    similarity_threshold: float = Field(
        0.8, ge=0.0, le=1.0, description="Similarity threshold for grouping"
    ),
) -> dict[str, Any]:
    """Perform semantic chunking based on content boundaries."""
    return chunker.semantic_chunk(
        text=text,
        min_chunk_size=min_chunk_size,
        max_chunk_size=max_chunk_size,
        similarity_threshold=similarity_threshold,
    )


@mcp.tool(
    description="Sentence-based chunking with configurable grouping",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def sentence_chunk(
    text: str = Field(..., description="Text to chunk by sentences"),
    sentences_per_chunk: int = Field(5, ge=1, le=50, description="Target sentences per chunk"),
    overlap_sentences: int = Field(
        1, ge=0, le=10, description="Overlapping sentences between chunks"
    ),
) -> dict[str, Any]:
    """Chunk text by grouping sentences."""
    return chunker.sentence_chunk(
        text=text, sentences_per_chunk=sentences_per_chunk, overlap_sentences=overlap_sentences
    )


@mcp.tool(
    description="Fixed-size chunking with word boundary options",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def fixed_size_chunk(
    text: str = Field(..., description="Text to chunk"),
    chunk_size: int = Field(1000, ge=100, le=100000, description="Fixed chunk size in characters"),
    overlap: int = Field(0, ge=0, description="Overlap between chunks"),
    split_on_word_boundary: bool = Field(
        True, description="Split on word boundaries to avoid breaking words"
    ),
) -> dict[str, Any]:
    """Chunk text into fixed-size pieces."""
    return chunker.fixed_size_chunk(
        text=text,
        chunk_size=chunk_size,
        overlap=overlap,
        split_on_word_boundary=split_on_word_boundary,
    )


@mcp.tool(
    description="Analyze text and recommend optimal chunking strategy",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def analyze_text(
    text: str = Field(..., description="Text to analyze for chunking recommendations"),
) -> dict[str, Any]:
    """Analyze text characteristics and recommend optimal chunking strategy."""
    return chunker.analyze_text(text)


@mcp.tool(
    description="List available chunking strategies and capabilities",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def get_strategies() -> dict[str, Any]:
    """Get information about available chunking strategies and libraries."""
    return chunker.get_chunking_strategies()


def main():
    """Main server entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Chunker FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9001, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting Chunker FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting Chunker FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
