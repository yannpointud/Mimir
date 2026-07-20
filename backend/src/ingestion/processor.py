"""
Document Ingestion Processor
Orchestrates the complete pipeline: extraction → chunking → embedding → indexing
"""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import numpy as np

from .extractors import ExtractorFactory, ExtractionError, UnsupportedFormatError
from .chunking import ChunkingStrategy, ChunkingConfig
from .async_queue_manager import AsyncQueueManager
from .queue_manager import IngestionTask, TaskPriority

from ..llm_interface.interfaces import AbstractLLMService, LLMException, EmbeddingResponse
from ..rag_core.interfaces import AbstractVectorStore, Chunk, VectorStoreException
from ..database.repository import DocumentRepository
from ..database.models import Document
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
                 usage_tracker=None):
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
        """
        self.llm_service = llm_service
        self.vector_store = vector_store
        self.document_repository = document_repository
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.max_chunks_per_doc = max_chunks_per_doc
        self.budget_guard = budget_guard or default_budget_guard
        self.usage_tracker = usage_tracker or default_usage_tracker

        # Initialize components
        self.extractor_factory = ExtractorFactory()
        self.chunking_strategy = ChunkingStrategy(chunking_config)

        # Async queue manager for sequential processing with configurable max size
        self.queue_manager = AsyncQueueManager(max_size=settings.ingestion_queue_max_size)

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
                      priority: TaskPriority = TaskPriority.NORMAL,
                      preserve: bool = False,
                      metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Queue a document for processing

        Args:
            file_path: Path to the document file
            document_id: Optional document ID, will be generated if None
            priority: Processing priority
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
                priority=priority,
                metadata=metadata or {}
            )

            # Queue the task
            success = self.queue_manager.add_task(task)

            if success:
                logger.info(
                    f"Queued document for processing: {file_path_obj.name}",
                    extra={'extra_fields': {
                        'file_path': file_path,
                        'document_id': document_id,
                        'priority': priority.name,
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
            # day's ledger reset (Pitfall 5). Exhaust the task's retry
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
            # retry loop entirely (Pitfall 5).
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
                    'char_count': chunk_data.get('char_count', 0)
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

    def clear_queue(self) -> int:
        """Clear pending tasks"""
        return self.queue_manager.clear_queue()
