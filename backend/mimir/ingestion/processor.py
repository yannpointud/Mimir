"""
Document Ingestion Processor
Orchestrates the complete pipeline: extraction → chunking → embedding → indexing
"""

import asyncio
import time
from pathlib import Path
from typing import Any

import numpy as np

from mimir.config import settings
from mimir.cost.budget_guard import BudgetGuard
from mimir.cost.budget_guard import budget_guard as default_budget_guard
from mimir.cost.usage_tracker import UsageTracker
from mimir.cost.usage_tracker import usage_tracker as default_usage_tracker
from mimir.database.repository import DocumentRepository
from mimir.ingestion.async_queue_manager import AsyncQueueManager
from mimir.ingestion.chunking import ChunkingConfig, ChunkingStrategy
from mimir.ingestion.extractors import ExtractionError, ExtractorFactory, UnsupportedFormatError
from mimir.ingestion.queue_manager import IngestionTask
from mimir.llm_interface.interfaces import AbstractLLMService, EmbeddingResponse, LLMException
from mimir.monitoring.logger import setup_logger
from mimir.rag_core.interfaces import AbstractVectorStore, Chunk, LexicalIndex
from mimir.shared.errors import BudgetExceeded, IngestionError, NotFoundError

logger = setup_logger(__name__)


class ProcessingError(IngestionError):
    """Base exception for processing errors"""

    pass


class NoExtractableTextError(ProcessingError):
    """The document yields no text: an empty file or a scan without a text layer.

    Every attempt extracts the same empty text, so the task is not retried.
    """


# Stored on the document and shown in the admin documents list
NO_TEXT_ERROR_MESSAGE = (
    "No extractable text: empty document or scan without a text layer (OCR is not supported)"
)


class IngestionProcessor:
    """
    Main processor for document ingestion pipeline
    Coordinates extraction, chunking, embedding, and indexing
    """

    def __init__(
        self,
        llm_service: AbstractLLMService,
        vector_store: AbstractVectorStore,
        document_repository: DocumentRepository,
        chunking_config: ChunkingConfig | None = None,
        max_file_size_mb: int = 100,
        max_chunks_per_doc: int = 2000,
        budget_guard: BudgetGuard | None = None,
        usage_tracker: UsageTracker | None = None,
        bm25_store: LexicalIndex | None = None,
    ) -> None:
        """Initialize ingestion processor.

        ``budget_guard`` and ``usage_tracker`` default to the module-level
        singletons (injectable for tests). When ``bm25_store`` is provided, the
        lexical index is rebuilt from the FAISS source of truth after successful
        upserts (coalesced once the queue drains), keeping both indexes
        synchronized through this single-writer worker. None disables the
        hybrid sync (dense-only behavior unchanged).
        """
        self.llm_service = llm_service
        self.vector_store = vector_store
        self.document_repository = document_repository
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.max_chunks_per_doc = max_chunks_per_doc
        self.budget_guard = budget_guard or default_budget_guard
        self.usage_tracker = usage_tracker or default_usage_tracker
        self.bm25_store = bm25_store
        # Set by every successful FAISS upsert, cleared only by a successful BM25
        # rebuild: the drain rebuild fires whenever the queue empties after an
        # upsert, even when the last document of a batch fails.
        self._bm25_dirty = False

        # Initialize components
        self.extractor_factory = ExtractorFactory()
        self.chunking_strategy = ChunkingStrategy(chunking_config)

        # Async queue manager for sequential processing with configurable max size
        # and retry backoff (mitigates Mistral 429 bursts during batch upload).
        self.queue_manager = AsyncQueueManager(
            max_size=settings.ingestion_queue_max_size,
            retry_base_delay=settings.ingestion_retry_base_delay,
            retry_max_delay=settings.ingestion_retry_max_delay,
        )

        logger.info(
            f"Ingestion processor initialized (max_file_size={max_file_size_mb}MB, "
            f"max_chunks={max_chunks_per_doc})"
        )

    async def start(self) -> None:
        """Start the ingestion processor"""
        await self.queue_manager.start(self._process_task)
        logger.info("Ingestion processor started")

    async def stop(self, timeout: float = 30.0) -> bool:
        """Stop the ingestion processor"""
        success = await self.queue_manager.stop(timeout)
        logger.info("Ingestion processor stopped")
        return success

    def queue_document(
        self, file_path: str, document_id: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """Queue a stored document for ingestion; return False when the queue is full.

        Raises:
            NotFoundError: If the file or the document record does not exist
            IngestionError: If the file exceeds the maximum size
        """
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise NotFoundError(f"File does not exist: {file_path}")
        file_size = file_path_obj.stat().st_size
        if file_size > self.max_file_size_bytes:
            raise IngestionError(
                f"File too large: {file_size / 1024 / 1024:.1f}MB > "
                f"{self.max_file_size_bytes / 1024 / 1024}MB"
            )
        if self.document_repository.get_by_id(int(document_id)) is None:
            raise NotFoundError(f"Document {document_id} not found")

        task = IngestionTask(
            file_path=file_path,
            document_id=document_id,
            metadata=metadata or {},
            max_retries=settings.ingestion_max_retries,
        )
        queued = self.queue_manager.add_task(task)
        if queued:
            logger.info(
                f"Queued document for processing: {file_path_obj.name}",
                extra={
                    "extra_fields": {
                        "file_path": file_path,
                        "document_id": document_id,
                        "file_size_mb": file_size / 1024 / 1024,
                        "type": "document_queued",
                    }
                },
            )
        return queued

    async def _process_task(self, task: IngestionTask) -> bool:
        """Process a single ingestion task"""
        try:
            # Update status to indexing
            self.document_repository.update_status(
                int(task.document_id), "indexing", error_message=None
            )

            # Run the processing pipeline - Full async now
            success = await self._process_document_pipeline(task)

            if success:
                # Update status to indexed
                # Note: chunk_count will be updated by the pipeline
                self.document_repository.update_status(
                    int(task.document_id), "indexed", error_message=None
                )
                logger.info(f"Document processing completed: {task.file_path}")
            else:
                # Update status to error
                self.document_repository.update_status(
                    int(task.document_id), "error", error_message="Processing pipeline failed"
                )

            return success

        except BudgetExceeded:
            # Fail-closed, non-retriable: budget exhaustion is not a
            # transient failure and a retry cannot succeed before the next
            # day's ledger reset. Exhaust the task's retry
            # budget so the async queue worker loop does not re-queue it.
            logger.warning(
                f"Ingestion stopped (fail-closed): daily budget exceeded for document {task.document_id}",
                extra={
                    "extra_fields": {
                        "document_id": task.document_id,
                        "file_path": task.file_path,
                        "type": "budget_exceeded_ingestion",
                    }
                },
            )

            self._fail_without_retry(task, "Daily budget exceeded")
            return False

        except NoExtractableTextError as e:
            logger.warning(f"Ingestion stopped (not retried): {e!s}")
            self._fail_without_retry(task, NO_TEXT_ERROR_MESSAGE)
            return False

        except Exception as e:  # noqa: BLE001 - worker boundary: a failing document must not stop the worker
            error_msg = f"Task processing failed: {e!s}"
            logger.error(error_msg)

            try:
                # Update status to error
                self.document_repository.update_status(
                    int(task.document_id),
                    "error",
                    error_message=error_msg[:500],  # Limit error message length
                )
            except Exception as db_error:  # noqa: BLE001 - worker boundary: a status write failure is only logged
                logger.error(f"Failed to update document status: {db_error!s}")

            return False

        finally:
            # Fire the coalesced BM25 drain rebuild on EVERY terminal path
            # (success, budget-exceeded, or generic failure). When the last
            # document of a batch fails before Step 8, this rebuilds BM25 for the
            # earlier successfully-upserted documents instead of leaving the
            # lexical index stale vs FAISS. Idempotent with the Step 8 call via the
            # _bm25_dirty guard; never allowed to mask the task result.
            try:
                await self._maybe_rebuild_bm25_on_drain()
            except Exception as drain_error:  # noqa: BLE001 - worker boundary: never mask the task result
                logger.warning(f"BM25 drain rebuild raised unexpectedly - ignoring: {drain_error}")

    def _fail_without_retry(self, task: IngestionTask, error_message: str) -> None:
        """Mark the document as failed and exhaust the task's retries.

        The async queue worker loop then does not re-queue the task.
        """
        try:
            self.document_repository.update_status(
                int(task.document_id), "error", error_message=error_message
            )
        except Exception as db_error:  # noqa: BLE001 - worker boundary: a status write failure is only logged
            logger.error(f"Failed to update document status: {db_error!s}")
        task.retry_count = task.max_retries

    async def _process_document_pipeline(self, task: IngestionTask) -> bool:
        """Extract, chunk, embed and index one document; False when it yields nothing."""
        start_time = time.time()
        try:
            extracted_text = self._extract_text(task.file_path)
            chunks_data = self._chunk(extracted_text, task.file_path)
            if not chunks_data:
                return False

            embeddings = await self._embed_within_budget(chunks_data, task.document_id)
            if len(embeddings) != len(chunks_data):
                logger.error(f"Embedding count mismatch: {len(embeddings)} != {len(chunks_data)}")
                return False

            chunks = self._create_chunks(
                chunks_data, embeddings, task.document_id, task.file_path, task.metadata
            )
            await self._index_chunks(chunks, task.document_id)
            # Coalesced to the queue drain; also called from _process_task's
            # finally block so a failing last document still triggers it.
            await self._maybe_rebuild_bm25_on_drain()
        except (BudgetExceeded, NoExtractableTextError):
            # Not retried: _process_task stops the document
            raise
        except Exception as e:  # noqa: BLE001 - worker boundary: any failure marks the document as failed
            processing_time = time.time() - start_time
            logger.error(
                f"Document processing pipeline failed after {processing_time:.2f}s: {e!s}",
                extra={
                    "extra_fields": {
                        "file_path": task.file_path,
                        "document_id": task.document_id,
                        "processing_time": processing_time,
                        "error": str(e),
                        "type": "pipeline_failed",
                    }
                },
            )
            return False

        processing_time = time.time() - start_time
        logger.info(
            f"Document processing pipeline completed in {processing_time:.2f}s: "
            f"{len(chunks)} chunks indexed",
            extra={
                "extra_fields": {
                    "file_path": task.file_path,
                    "document_id": task.document_id,
                    "chunks": len(chunks),
                    "characters": len(extracted_text),
                    "processing_time": processing_time,
                    "type": "pipeline_completed",
                }
            },
        )
        return True

    def _chunk(self, text: str, file_path: str) -> list[dict[str, Any]]:
        """Chunks of the text, capped at max_chunks_per_doc.

        Raises:
            NoExtractableTextError: If the extracted text is empty
        """
        if not text.strip():
            raise NoExtractableTextError(f"No text extracted from: {file_path}")
        chunks_data = self.chunking_strategy.chunk_text(text, source=file_path)
        if not chunks_data:
            logger.warning(f"No chunks created from: {file_path}")
        if len(chunks_data) > self.max_chunks_per_doc:
            logger.warning(
                f"Too many chunks ({len(chunks_data)} > {self.max_chunks_per_doc}), "
                f"truncating: {file_path}"
            )
            chunks_data = chunks_data[: self.max_chunks_per_doc]
        return chunks_data

    async def _embed_within_budget(
        self, chunks_data: list[dict[str, Any]], document_id: str
    ) -> list[list[float]]:
        """Embed the chunks under a budget reservation, then record the real cost.

        Raises:
            BudgetExceeded: If the daily cap is already exhausted (fail-closed)
        """
        # Budget and usage calls are blocking SQLite writes: off the event loop
        reservation = await asyncio.to_thread(self.budget_guard.reserve, "embedding")
        if reservation is None:
            raise BudgetExceeded("Daily budget exceeded")
        try:
            embedding_response = await self._generate_embeddings(chunks_data)
        except BaseException:
            # No embedding call was billed: refund the reservation
            await asyncio.to_thread(self.budget_guard.release, reservation)
            raise

        # Ingestion has no user session: usage is keyed by document
        actual_cost_eur = await asyncio.to_thread(
            self.usage_tracker.record,
            "embedding",
            embedding_response.model,
            embedding_response.prompt_tokens,
            embedding_response.completion_tokens,
            estimated=False,
            session_id=f"doc:{document_id}",
        )
        await asyncio.to_thread(self.budget_guard.finalize, reservation, actual_cost_eur)
        return embedding_response.embeddings

    async def _index_chunks(self, chunks: list[Chunk], document_id: str) -> None:
        """Upsert the chunks in FAISS, record their count and persist the index."""
        await asyncio.to_thread(self.vector_store.upsert, chunks)
        # BM25 is now stale until the next drain rebuild, whatever document
        # ends the batch
        self._bm25_dirty = True
        self.document_repository.update_status(
            int(document_id), "indexing", chunk_count=len(chunks)
        )
        await asyncio.to_thread(self.vector_store.persist)

    async def _maybe_rebuild_bm25_on_drain(self) -> None:
        """
        Rebuild the BM25 lexical index from the FAISS source of truth
        when the ingestion queue has drained, IF any document was upserted since
        the last rebuild (the _bm25_dirty signal).

        Coalescing: gating on an empty queue means a bulk-load rebuilds
        BM25 ONCE at drain instead of once per document (the per-doc rebuild was
        measured quadratic: ~28h for 10k docs). A single-document ingestion still
        rebuilds once (queue empty after its own task is dequeued). During a bulk
        batch BM25 lags FAISS until the final drain rebuild; that eventual
        consistency window is accepted (hybrid retrieval degrades gracefully to
        dense-only).

        Called from TWO places so the rebuild is owed on every terminal path:
        Step 8 of the success pipeline, and _process_task's finally block. The
        _bm25_dirty guard makes the pair idempotent -- whichever runs first clears
        the flag and the second is a no-op. Firing from the finally block keeps
        the documents of a batch whose last document failed in BM25.

        A BM25 failure is non-fatal (FAISS already holds the chunks): log and keep
        _bm25_dirty set so a later drain retries. The blocking rebuild is offloaded
        via asyncio.to_thread so it never stalls the event loop. Runs in
        the single-writer ingestion worker, so no second concurrent writer races.
        """
        if self.bm25_store is None or not self._bm25_dirty:
            return
        if not self.queue_manager.is_empty():
            return

        try:
            # Snapshot active chunks UNDER the FAISS lock so the rebuild never
            # races with a concurrent mutation.
            active_chunks = self.vector_store.snapshot_active_chunks()
            await asyncio.to_thread(self.bm25_store.rebuild, active_chunks)
            self._bm25_dirty = False
        except OSError as bm25_error:
            logger.warning(f"BM25 rebuild failed at drain - continuing anyway: {bm25_error}")

    def _extract_text(self, file_path: str) -> str:
        """Extract text from file

        Raises:
            ProcessingError: If extraction fails
        """
        try:
            return self.extractor_factory.extract_text(file_path)
        except (ExtractionError, UnsupportedFormatError) as e:
            raise ProcessingError(f"Text extraction failed: {e!s}") from e

    async def _generate_embeddings(self, chunks_data: list[dict[str, Any]]) -> EmbeddingResponse:
        """Generate embeddings for chunks

        Returns:
            EmbeddingResponse carrying both the embedding vectors and the
            usage metadata (model, prompt_tokens, completion_tokens) needed
            for cost accounting

        Raises:
            ProcessingError: If embedding generation fails
        """
        try:
            texts = [chunk["text"] for chunk in chunks_data]

            response = await self.llm_service.embed(texts)
            return response

        except LLMException as e:
            raise ProcessingError(f"Embedding generation failed: {e!s}") from e

    def _create_chunks(
        self,
        chunks_data: list[dict[str, Any]],
        embeddings: list[list[float]],
        document_id: str,
        source: str,
        metadata: dict[str, Any],
    ) -> list[Chunk]:
        """Create Chunk objects from data"""
        chunks = []

        for chunk_data, embedding in zip(chunks_data, embeddings, strict=False):
            chunk = Chunk(
                text=chunk_data["text"],
                embedding=np.array(embedding, dtype=np.float32),
                document_id=document_id,
                chunk_index=chunk_data["chunk_index"],
                total_chunks=chunk_data["total_chunks"],
                source=source,
                metadata={
                    **metadata,
                    "start_char": chunk_data.get("start_char", 0),
                    "end_char": chunk_data.get("end_char", 0),
                    "word_count": chunk_data.get("word_count", 0),
                    "char_count": chunk_data.get("char_count", 0),
                    # Structure-aware chunking. `.get()` keeps the
                    # flag-off path safe: no section_title key in the chunk dict
                    # yields None here (open metadata dict, no schema migration).
                    "section_title": chunk_data.get("section_title"),
                },
                preserve=metadata.get("preserve", False),
            )
            chunks.append(chunk)

        return chunks

    def get_stats(self) -> dict[str, Any]:
        """Get processing statistics"""
        queue_stats = self.queue_manager.get_stats()

        return {
            "processor_running": self.queue_manager.is_running(),
            "supported_extensions": self.extractor_factory.get_supported_extensions(),
            "max_file_size_mb": self.max_file_size_bytes / 1024 / 1024,
            "max_chunks_per_doc": self.max_chunks_per_doc,
            "queue_stats": queue_stats,
        }

    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self.queue_manager.get_queue_size()

    def is_running(self) -> bool:
        """Check if processor is running"""
        return self.queue_manager.is_running()

    async def clear_queue(self) -> int:
        """Clear pending tasks"""
        return await self.queue_manager.clear_queue()
