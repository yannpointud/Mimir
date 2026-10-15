"""
Document Ingestion Processor
Orchestrates the complete pipeline: extraction → chunking → embedding → indexing
"""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple  # noqa: F401
from datetime import datetime  # noqa: F401
import numpy as np

from .extractors import ExtractorFactory, ExtractionError, UnsupportedFormatError
from .chunking import ChunkingStrategy, ChunkingConfig
from .async_queue_manager import AsyncQueueManager
from .queue_manager import IngestionTask

from ..llm_interface.interfaces import AbstractLLMService, LLMException, EmbeddingResponse
from ..rag_core.interfaces import AbstractVectorStore, Chunk, VectorStoreException  # noqa: F401
from ..database.repository import DocumentRepository
from ..database.models import Document  # noqa: F401
from ..monitoring.logger import setup_logger
from ..config import settings
from ..cost.budget_guard import BudgetExceededError, budget_guard as default_budget_guard
from ..cost.usage_tracker import usage_tracker as default_usage_tracker

logger = setup_logger(__name__)

class ProcessingError(Exception):
    """Base exception for processing errors"""
    pass

class IngestionProcessor:
    """
    Main processor for document ingestion pipeline
    Coordinates extraction, chunking, embedding, and indexing
    """

    def __init__(self,
                 llm_service: AbstractLLMService,
                 vector_store: AbstractVectorStore,
                 document_repository: DocumentRepository,
                 chunking_config: Optional[ChunkingConfig] = None,
                 max_file_size_mb: int = 100,
                 max_chunks_per_doc: int = 2000,
                 budget_guard=None,
                 usage_tracker=None,
                 bm25_store=None):
        """
        Initialize ingestion processor

        Args:
            llm_service: LLM service for embeddings
            vector_store: Vector store for indexing
            document_repository: Database repository for documents
            chunking_config: Configuration for text chunking
            max_file_size_mb: Maximum file size in MB
            max_chunks_per_doc: Maximum chunks per document
            budget_guard: Optional BudgetGuard override (defaults to the
                module-level singleton); injectable for tests
            usage_tracker: Optional UsageTracker override (defaults to the
                module-level singleton); injectable for tests
            bm25_store: Optional BM25 lexical store. When provided, the
                lexical index is rebuilt from the FAISS source of truth after
                each successful upsert, keeping both indexes synchronized
                through this single-writer worker. None disables the hybrid
                sync (dense-only behavior unchanged).
        """
        self.llm_service = llm_service
        self.vector_store = vector_store
        self.document_repository = document_repository
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.max_chunks_per_doc = max_chunks_per_doc
        self.budget_guard = budget_guard or default_budget_guard
        self.usage_tracker = usage_tracker or default_usage_tracker
        self.bm25_store = bm25_store
        # "Dirty" signal set on every successful FAISS upsert and cleared
        # only by a successful BM25 rebuild. Lets the coalesced drain rebuild fire
        # whenever the ingestion queue empties IF any document was upserted since
        # the last rebuild -- even when the LAST document of a batch fails before
        # Step 8, which previously left earlier docs' chunks permanently absent
        # from BM25 until the next successful ingestion.
        self._bm25_dirty = False

        # Initialize components
        self.extractor_factory = ExtractorFactory()
        self.chunking_strategy = ChunkingStrategy(chunking_config)

        # Async queue manager for sequential processing with configurable max size
        # and retry backoff (mitigates Mistral 429 bursts during batch upload).
        self.queue_manager = AsyncQueueManager(
            max_size=settings.ingestion_queue_max_size,
            retry_base_delay=settings.ingestion_retry_base_delay,
            retry_max_delay=settings.ingestion_retry_max_delay
        )

        logger.info(
            f"Ingestion processor initialized (max_file_size={max_file_size_mb}MB, "
            f"max_chunks={max_chunks_per_doc})"
        )

    async def start(self):
        """Start the ingestion processor"""
        await self.queue_manager.start(self._process_task)
        logger.info("Ingestion processor started")

    async def stop(self, timeout: float = 30.0) -> bool:
        """Stop the ingestion processor"""
        success = await self.queue_manager.stop(timeout)
        logger.info("Ingestion processor stopped")
        return success

    def queue_document(self,
                      file_path: str,
                      document_id: Optional[str] = None,
                      preserve: bool = False,
                      metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Queue a document for processing

        Args:
            file_path: Path to the document file
            document_id: Optional document ID, will be generated if None
            preserve: Whether to protect from deletion
            metadata: Additional metadata

        Returns:
            True if queued successfully
        """
        try:
            # Validate file
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                logger.error(f"File does not exist: {file_path}")
                return False

            # Check file size
            file_size = file_path_obj.stat().st_size
            if file_size > self.max_file_size_bytes:
                logger.error(
                    f"File too large: {file_size / 1024 / 1024:.1f}MB > "
                    f"{self.max_file_size_bytes / 1024 / 1024}MB"
                )
                return False

            # Handle document creation/reprocessing
            if document_id is None:
                # New document - generate ID and create database record
                document_id = self._generate_document_id(file_path)
                file_hash = self._calculate_file_hash(file_path)

                try:
                    document = self.document_repository.create(
                        filename=file_path_obj.name,
                        file_hash=file_hash,
                        path=str(file_path_obj.absolute()),
                        preserve=preserve
                    )
                    document_id = str(document.id)
                except Exception as e:
                    if "already exists" in str(e).lower():
                        logger.warning(f"Document already exists with hash: {file_hash}")
                        return False
                    raise
            else:
                # Reprocessing existing document - validate it exists
                try:
                    document = self.document_repository.get_by_id(int(document_id))
                    if not document:
                        logger.error(f"Document ID {document_id} not found for reprocessing")
                        return False
                    logger.info(f"Reprocessing existing document: {document.filename} (ID: {document_id})")
                except Exception as e:
                    logger.error(f"Failed to retrieve document {document_id} for reprocessing: {str(e)}")
                    return False

            # Create ingestion task
            task = IngestionTask(
                file_path=file_path,
                document_id=document_id,
                metadata=metadata or {},
                max_retries=settings.ingestion_max_retries
            )

            # Queue the task
            success = self.queue_manager.add_task(task)

            if success:
                logger.info(
                    f"Queued document for processing: {file_path_obj.name}",
                    extra={'extra_fields': {
                        'file_path': file_path,
                        'document_id': document_id,
                        'file_size_mb': file_size / 1024 / 1024,
                        'type': 'document_queued'
                    }}
                )

            return success

        except Exception as e:
            logger.error(f"Failed to queue document {file_path}: {str(e)}")
            return False

    async def _process_task(self, task: IngestionTask) -> bool:
        """
        Process a single ingestion task

        Args:
            task: Ingestion task to process

        Returns:
            True if processing succeeded
        """
        try:
            # Update status to indexing
            self.document_repository.update_status(
                int(task.document_id),
                'indexing',
                error_message=None
            )

            # Run the processing pipeline - Full async now
            success = await self._process_document_pipeline(task)

            if success:
                # Update status to indexed
                # Note: chunk_count will be updated by the pipeline
                self.document_repository.update_status(
                    int(task.document_id),
                    'indexed',
                    error_message=None
                )
                logger.info(f"Document processing completed: {task.file_path}")
            else:
                # Update status to error
                self.document_repository.update_status(
                    int(task.document_id),
                    'error',
                    error_message="Processing pipeline failed"
                )

            return success

        except BudgetExceededError:
            # Fail-closed, non-retriable: budget exhaustion is not a
            # transient failure and a retry cannot succeed before the next
            # day's ledger reset. Exhaust the task's retry
            # budget so the async queue worker loop does not re-queue it.
            logger.warning(
                f"Ingestion stopped (fail-closed): daily budget exceeded for document {task.document_id}",
                extra={'extra_fields': {
                    'document_id': task.document_id,
                    'file_path': task.file_path,
                    'type': 'budget_exceeded_ingestion'
                }}
            )

            try:
                self.document_repository.update_status(
                    int(task.document_id),
                    'error',
                    error_message="Daily budget exceeded"
                )
            except Exception as db_error:
                logger.error(f"Failed to update document status: {str(db_error)}")

            task.retry_count = task.max_retries
            return False

        except Exception as e:
            error_msg = f"Task processing failed: {str(e)}"
            logger.error(error_msg)

            try:
                # Update status to error
                self.document_repository.update_status(
                    int(task.document_id),
                    'error',
                    error_message=error_msg[:500]  # Limit error message length
                )
            except Exception as db_error:
                logger.error(f"Failed to update document status: {str(db_error)}")

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
            except Exception as drain_error:
                logger.warning(
                    f"BM25 drain rebuild raised unexpectedly - ignoring: {drain_error}"
                )

    async def _process_document_pipeline(self, task: IngestionTask) -> bool:
        """
        Execute the complete processing pipeline

        Args:
            task: Ingestion task

        Returns:
            True if pipeline succeeded
        """
        start_time = time.time()

        try:
            # Step 1: Extract text
            logger.debug(f"Extracting text from: {task.file_path}")
            extracted_text = self._extract_text(task.file_path)

            if not extracted_text.strip():
                logger.warning(f"No text extracted from: {task.file_path}")
                return False

            # Step 2: Chunk text
            logger.debug(f"Chunking text: {len(extracted_text)} characters")
            chunks_data = self.chunking_strategy.chunk_text(
                extracted_text,
                source=task.file_path
            )

            if not chunks_data:
                logger.warning(f"No chunks created from: {task.file_path}")
                return False

            # Check chunk limit
            if len(chunks_data) > self.max_chunks_per_doc:
                logger.warning(
                    f"Too many chunks ({len(chunks_data)} > {self.max_chunks_per_doc}), "
                    f"truncating: {task.file_path}"
                )
                chunks_data = chunks_data[:self.max_chunks_per_doc]

            # Step 3: Generate embeddings
            # Reserve the daily budget BEFORE the paid Mistral embedding call
            # (fail-closed): None means the effective daily cap is already
            # exhausted, so raise a non-retriable BudgetExceededError instead
            # of ever calling embed().
            #
            # asyncio.to_thread on every reserve/release/record/finalize call
            # below: these are blocking SQLite writes (WAL serializes
            # writers) and must never stall the shared event loop -- same
            # rationale as the vector_store.upsert/persist wrapping.
            reservation = await asyncio.to_thread(self.budget_guard.reserve, "embedding")
            if reservation is None:
                raise BudgetExceededError("Daily budget exceeded")

            logger.debug(f"Generating embeddings for {len(chunks_data)} chunks")
            try:
                embedding_response = await self._generate_embeddings(chunks_data)
            except Exception:
                # No embedding call actually succeeded -- refund the
                # reservation and let the original error propagate to the
                # outer except blocks below.
                await asyncio.to_thread(self.budget_guard.release, reservation)
                raise

            embeddings = embedding_response.embeddings

            # A real embedding call succeeded and was billed by Mistral:
            # record its usage (keyed by doc:{document_id}, since ingestion
            # has no user session) and finalize the reservation with the
            # real cost, regardless of downstream chunk-count validation.
            actual_cost_eur = await asyncio.to_thread(
                self.usage_tracker.record,
                "embedding",
                embedding_response.model,
                embedding_response.prompt_tokens,
                embedding_response.completion_tokens,
                estimated=False,
                session_id=f"doc:{task.document_id}"
            )
            await asyncio.to_thread(self.budget_guard.finalize, reservation, actual_cost_eur)

            if len(embeddings) != len(chunks_data):
                logger.error(
                    f"Embedding count mismatch: {len(embeddings)} != {len(chunks_data)}"
                )
                return False

            # Step 4: Create chunk objects
            chunks = self._create_chunks(
                chunks_data,
                embeddings,
                task.document_id,
                task.file_path,
                task.metadata
            )

            # Step 5: Index in vector store
            logger.debug(f"Indexing {len(chunks)} chunks in vector store")
            index_success = await asyncio.to_thread(self.vector_store.upsert, chunks)

            if not index_success:
                logger.error("Failed to index chunks in vector store")
                return False

            # Mark BM25 stale vs FAISS as soon as the upsert succeeds, so a
            # later drain (success OR failure path) knows a coalesced rebuild is
            # owed regardless of which document happens to be last in the batch.
            self._bm25_dirty = True

            # Step 6: Update document chunk count
            self.document_repository.update_status(
                int(task.document_id),
                'indexing',  # Still processing
                chunk_count=len(chunks)
            )

            # Step 7: Persist vector store
            persist_success = await asyncio.to_thread(self.vector_store.persist)
            if not persist_success:
                logger.warning("Failed to persist vector store - continuing anyway")

            # Step 8: Rebuild the BM25 lexical index from the FAISS source of
            # truth, coalesced to the queue-drain point. The
            # rebuild itself lives in _maybe_rebuild_bm25_on_drain, which is ALSO
            # called from _process_task's finally block so a batch whose last
            # document fails still rebuilds for the earlier successful docs.
            await self._maybe_rebuild_bm25_on_drain()

            processing_time = time.time() - start_time

            logger.info(
                f"Document processing pipeline completed in {processing_time:.2f}s: "
                f"{len(chunks)} chunks indexed",
                extra={'extra_fields': {
                    'file_path': task.file_path,
                    'document_id': task.document_id,
                    'chunks': len(chunks),
                    'characters': len(extracted_text),
                    'processing_time': processing_time,
                    'type': 'pipeline_completed'
                }}
            )

            return True

        except BudgetExceededError:
            # Non-retriable fail-closed stop: propagate to _process_task's
            # dedicated except BudgetExceededError branch, bypassing the
            # retry loop entirely (a retry cannot succeed before the next reset).
            raise

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(
                f"Document processing pipeline failed after {processing_time:.2f}s: {str(e)}",
                extra={'extra_fields': {
                    'file_path': task.file_path,
                    'document_id': task.document_id,
                    'processing_time': processing_time,
                    'error': str(e),
                    'type': 'pipeline_failed'
                }}
            )
            return False

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
        the flag and the second is a no-op. Previously the
        rebuild was gated only inside the success path, so if the LAST document of
        a multi-doc batch failed before Step 8, the earlier successfully-upserted
        documents never got their coalesced rebuild and stayed absent from BM25
        (hybrid retrieval silently lost them from the lexical pool) until the next
        successful ingestion. Firing from the finally block on the failure path
        fixes that.

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
        except Exception as bm25_error:
            logger.warning(
                f"BM25 rebuild failed at drain - continuing anyway: {bm25_error}"
            )

    def _extract_text(self, file_path: str) -> str:
        """
        Extract text from file

        Args:
            file_path: Path to file

        Returns:
            Extracted text

        Raises:
            ProcessingError: If extraction fails
        """
        try:
            return self.extractor_factory.extract_text(file_path)
        except (ExtractionError, UnsupportedFormatError) as e:
            raise ProcessingError(f"Text extraction failed: {str(e)}")

    async def _generate_embeddings(self, chunks_data: List[Dict[str, Any]]) -> EmbeddingResponse:
        """
        Generate embeddings for chunks

        Args:
            chunks_data: List of chunk dictionaries

        Returns:
            EmbeddingResponse carrying both the embedding vectors and the
            usage metadata (model, prompt_tokens, completion_tokens) needed
            for cost accounting

        Raises:
            ProcessingError: If embedding generation fails
        """
        try:
            texts = [chunk['text'] for chunk in chunks_data]

            response = await self.llm_service.embed(texts)
            return response

        except LLMException as e:
            raise ProcessingError(f"Embedding generation failed: {str(e)}")

    def _create_chunks(self,
                      chunks_data: List[Dict[str, Any]],
                      embeddings: List[List[float]],
                      document_id: str,
                      source: str,
                      metadata: Dict[str, Any]) -> List[Chunk]:
        """
        Create Chunk objects from data

        Args:
            chunks_data: Chunk data dictionaries
            embeddings: Embedding vectors
            document_id: Document identifier
            source: Source file path
            metadata: Additional metadata

        Returns:
            List of Chunk objects
        """
        chunks = []

        for i, (chunk_data, embedding) in enumerate(zip(chunks_data, embeddings)):
            chunk = Chunk(
                text=chunk_data['text'],
                embedding=np.array(embedding, dtype=np.float32),
                document_id=document_id,
                chunk_index=chunk_data['chunk_index'],
                total_chunks=chunk_data['total_chunks'],
                source=source,
                metadata={
                    **metadata,
                    'start_char': chunk_data.get('start_char', 0),
                    'end_char': chunk_data.get('end_char', 0),
                    'word_count': chunk_data.get('word_count', 0),
                    'char_count': chunk_data.get('char_count', 0),
                    # Structure-aware chunking. `.get()` keeps the
                    # flag-off path safe: no section_title key in the chunk dict
                    # yields None here (open metadata dict, no schema migration).
                    'section_title': chunk_data.get('section_title')
                },
                preserve=metadata.get('preserve', False)
            )
            chunks.append(chunk)

        return chunks

    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file"""
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _generate_document_id(self, file_path: str) -> str:
        """Generate document ID from file path and timestamp"""
        file_path_obj = Path(file_path)
        timestamp = int(time.time())
        return f"{file_path_obj.stem}_{timestamp}"

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        queue_stats = self.queue_manager.get_stats()

        return {
            'processor_running': self.queue_manager.is_running(),
            'supported_extensions': self.extractor_factory.get_supported_extensions(),
            'max_file_size_mb': self.max_file_size_bytes / 1024 / 1024,
            'max_chunks_per_doc': self.max_chunks_per_doc,
            'queue_stats': queue_stats
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
