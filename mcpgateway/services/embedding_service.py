"""Embedding service stub.

Full implementation requires an embedding model (e.g. OpenAI text-embedding-3-small)
and pgvector. This stub is a no-op so the application starts without those dependencies.
"""


async def index_tool_fire_and_forget(tool_id: str) -> None:
    """Index a tool's embedding in the background. No-op stub."""
