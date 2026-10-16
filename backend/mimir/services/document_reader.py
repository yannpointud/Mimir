"""
Reader view of a document: its record, its indexed chunks and the text of the
original file, as shown to the chat users who open a cited source.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

from mimir.ingestion.extractors import ExtractionError, ExtractorFactory
from mimir.services.errors import RequestRejectedError
from mimir.shared.models import ChunkResponse, DocumentWithChunksResponse

logger = logging.getLogger(__name__)

_MIME_TYPES = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".html": "text/html",
}


@dataclass
class _StoredFile:
    content: str | None = None
    file_size: int | None = None
    mime_type: str | None = None


async def build_document_view(
    document_id: int, doc_repo: Any, vector_store: Any
) -> DocumentWithChunksResponse:
    """The document with its chunks and content; 404 if it does not exist.

    Chunks and content are best effort: the view is served without them when
    the index or the file cannot be read.
    """
    document = doc_repo.get_by_id(document_id)
    if not document:
        raise RequestRejectedError(
            HTTPStatus.NOT_FOUND, f"Document with ID {document_id} not found"
        )

    chunks = await _load_chunks(vector_store, document_id)
    stored_file = _read_stored_file(document.path, document_id)
    return DocumentWithChunksResponse(
        id=document.id,
        filename=document.filename,
        path=document.path,
        preserve=document.preserve,
        file_hash=document.file_hash,
        status=document.status,
        error_message=document.error_message,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        indexed_at=document.indexed_at,
        chunks=chunks,
        content=stored_file.content,
        file_size=stored_file.file_size,
        mime_type=stored_file.mime_type,
    )


async def _load_chunks(vector_store: Any, document_id: int) -> list[ChunkResponse]:
    """Chunks of the document in index order; those built before a failure are kept."""
    chunk_responses: list[ChunkResponse] = []
    all_chunks = await asyncio.to_thread(vector_store.get_document_chunks, str(document_id))
    chunk_indexes = []
    for i, chunk in enumerate(all_chunks):
        # The original chunk_index is always present in the FAISS metadata
        chunk_indexes.append(chunk.chunk_index)
        chunk_responses.append(
            ChunkResponse(
                id=i,  # Position only: chunks have no database id
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                metadata=chunk.metadata if hasattr(chunk, "metadata") else {},
            )
        )

    if chunk_indexes:
        logger.info(
            f"Document {document_id} chunks loaded: {len(chunk_indexes)} chunks, chunk_indexes: {chunk_indexes[:10]}"
        )
    else:
        logger.warning(f"Document {document_id}: No chunks found in vector store")
    return chunk_responses


def _read_stored_file(path: str | None, document_id: int) -> _StoredFile:
    """Size, MIME type and extracted text of the original file, when readable."""
    stored_file = _StoredFile()
    if not (path and os.path.exists(path)):
        return stored_file
    try:
        stored_file.file_size = os.path.getsize(path)
        stored_file.mime_type = _MIME_TYPES.get(
            Path(path).suffix.lower(), "application/octet-stream"
        )
        # Same extractors as during indexing
        stored_file.content = _extract_text(ExtractorFactory(), path)
    except OSError as e:
        logger.warning(f"Could not read file metadata for document {document_id}: {e}")
    return stored_file


def _extract_text(extractor_factory: ExtractorFactory, path: str) -> str | None:
    try:
        content = extractor_factory.extract_text(path)
        logger.debug(
            f"Successfully extracted text from {path} ({len(content) if content else 0} characters)"
        )
        return content
    except ExtractionError as extraction_error:
        logger.warning(f"Could not extract text from {path}: {extraction_error}")
        return None
