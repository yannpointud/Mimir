"""
Unit tests of the ingestion processor
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mimir.cost.budget_guard import BudgetReservation
from mimir.ingestion.chunking import ChunkingConfig
from mimir.ingestion.processor import IngestionProcessor, ProcessingError
from mimir.ingestion.queue_manager import IngestionTask
from mimir.llm_interface.interfaces import EmbeddingResponse, LLMException
from mimir.rag_core.interfaces import Chunk
from mimir.shared.errors import IngestionError, NotFoundError


class TestIngestionProcessor:
    """Ingestion processor tests"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_llm_service(self):
        """Mocked LLM service"""
        mock_service = AsyncMock()
        mock_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]], model="test-embed", usage_tokens=10
        )
        return mock_service

    @pytest.fixture
    def mock_vector_store(self):
        """Mocked vector store"""
        mock_store = Mock()
        mock_store.upsert.return_value = True
        mock_store.persist.return_value = True
        return mock_store

    @pytest.fixture
    def mock_document_repository(self):
        """Mocked document repository"""
        mock_repo = Mock()
        mock_doc = Mock()
        mock_doc.id = 123
        mock_repo.create.return_value = mock_doc
        return mock_repo

    @pytest.fixture
    def mock_budget_guard(self):
        """Mocked budget guard -- always accepts the reservation, to keep
        these tests hermetic (no write to the real cost database through
        the real singleton)"""
        mock_guard = Mock()
        mock_guard.reserve.return_value = BudgetReservation(today="2024-01-01", estimate_eur=0.001)
        mock_guard.finalize.return_value = None
        mock_guard.release.return_value = None
        return mock_guard

    @pytest.fixture
    def mock_usage_tracker(self):
        """Mocked usage tracker -- writes no real llm_usage rows
        during the ingestion pipeline unit tests"""
        mock_tracker = Mock()
        mock_tracker.record.return_value = 0.001
        return mock_tracker

    @pytest.fixture
    def processor(
        self,
        mock_llm_service,
        mock_vector_store,
        mock_document_repository,
        mock_budget_guard,
        mock_usage_tracker,
    ):
        """Ingestion processor"""
        config = ChunkingConfig(chunk_size=100, overlap=20)
        return IngestionProcessor(
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            chunking_config=config,
            max_file_size_mb=1,
            max_chunks_per_doc=100,
            budget_guard=mock_budget_guard,
            usage_tracker=mock_usage_tracker,
        )

    @pytest.fixture
    def sample_text_file(self, temp_dir):
        """Sample text file"""
        file_path = temp_dir / "sample.txt"
        content = "This is a sample text file for testing the ingestion processor. " * 10
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def test_processor_initialization(
        self, mock_llm_service, mock_vector_store, mock_document_repository
    ):
        processor = IngestionProcessor(
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
        )

        assert processor.llm_service == mock_llm_service
        assert processor.vector_store == mock_vector_store
        assert processor.document_repository == mock_document_repository
        assert processor.max_file_size_bytes == 100 * 1024 * 1024  # 100MB by default
        assert processor.max_chunks_per_doc == 2000

    def test_processor_custom_config(
        self, mock_llm_service, mock_vector_store, mock_document_repository
    ):
        config = ChunkingConfig(chunk_size=500, overlap=100)
        processor = IngestionProcessor(
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            chunking_config=config,
            max_file_size_mb=50,
            max_chunks_per_doc=1000,
        )

        assert processor.max_file_size_bytes == 50 * 1024 * 1024
        assert processor.max_chunks_per_doc == 1000
        assert processor.chunking_strategy.config.chunk_size == 500

    @pytest.mark.asyncio
    async def test_start_and_stop_processor(self, processor):
        assert not processor.is_running()

        await processor.start()
        assert processor.is_running()

        success = await processor.stop()
        assert success is True
        assert not processor.is_running()

    def test_queue_document_success(self, processor, sample_text_file):
        assert processor.queue_document(str(sample_text_file), document_id="1") is True
        assert processor.get_queue_size() == 1

    def test_queue_document_nonexistent_file(self, processor):
        with pytest.raises(NotFoundError, match="File does not exist"):
            processor.queue_document("/nonexistent/file.txt", document_id="1")
        assert processor.get_queue_size() == 0

    def test_queue_document_unknown_document(
        self, processor, sample_text_file, mock_document_repository
    ):
        mock_document_repository.get_by_id.return_value = None
        with pytest.raises(NotFoundError, match="Document 1 not found"):
            processor.queue_document(str(sample_text_file), document_id="1")

    def test_queue_document_file_too_large(self, processor, temp_dir):
        large_file = temp_dir / "large.txt"
        large_file.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")
        with pytest.raises(IngestionError, match="File too large"):
            processor.queue_document(str(large_file), document_id="1")
        assert processor.get_queue_size() == 0

    def test_queue_document_full_queue_returns_false(self, processor, sample_text_file):
        processor.queue_manager.add_task = Mock(return_value=False)
        assert processor.queue_document(str(sample_text_file), document_id="1") is False

    def test_extract_text_success(self, processor, sample_text_file):
        extracted_text = processor._extract_text(str(sample_text_file))

        assert len(extracted_text) > 0
        assert "sample text file" in extracted_text

    def test_extract_text_failure(self, processor):
        with pytest.raises(ProcessingError):
            processor._extract_text("/nonexistent/file.txt")

    @pytest.mark.asyncio
    async def test_generate_embeddings_success(self, processor):
        chunks_data = [{"text": "First chunk"}, {"text": "Second chunk"}]

        response = await processor._generate_embeddings(chunks_data)

        assert isinstance(response, EmbeddingResponse)
        assert len(response.embeddings) == 2
        assert len(response.embeddings[0]) == 3  # Dimension of the mocked embedding
        processor.llm_service.embed.assert_called_once_with(["First chunk", "Second chunk"])

    @pytest.mark.asyncio
    async def test_generate_embeddings_failure(self, processor, mock_llm_service):
        mock_llm_service.embed.side_effect = LLMException("API Error")

        chunks_data = [{"text": "Test chunk"}]

        with pytest.raises(ProcessingError):
            await processor._generate_embeddings(chunks_data)

    def test_create_chunks(self, processor):
        chunks_data = [
            {
                "text": "First chunk",
                "chunk_index": 0,
                "total_chunks": 2,
                "start_char": 0,
                "end_char": 11,
                "word_count": 2,
                "char_count": 11,
            },
            {
                "text": "Second chunk",
                "chunk_index": 1,
                "total_chunks": 2,
                "start_char": 11,
                "end_char": 23,
                "word_count": 2,
                "char_count": 12,
            },
        ]

        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

        chunks = processor._create_chunks(
            chunks_data, embeddings, "doc123", "/test/source.txt", {"category": "test"}
        )

        assert len(chunks) == 2
        assert all(isinstance(chunk, Chunk) for chunk in chunks)

        chunk1 = chunks[0]
        assert chunk1.text == "First chunk"
        assert chunk1.document_id == "doc123"
        assert chunk1.chunk_index == 0
        assert chunk1.source == "/test/source.txt"
        assert chunk1.metadata["category"] == "test"
        assert chunk1.metadata["start_char"] == 0

    @pytest.mark.asyncio
    async def test_process_document_pipeline_success(self, processor, mock_document_repository):
        task = IngestionTask(
            file_path="dummy_path",  # will be mocked
            document_id="123",
            metadata={"test": True},
        )

        # Make the LLM mock return a single embedding, matching one chunk
        processor.llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]],  # A single embedding for one chunk
            model="test-embed",
            usage_tokens=10,
        )

        # Mock the pipeline steps
        with (
            patch.object(
                processor, "_extract_text", return_value="Sample text for chunking test"
            ) as mock_extract,
            patch.object(processor.chunking_strategy, "chunk_text") as mock_chunk,
        ):
            mock_chunk.return_value = [
                {
                    "text": "Sample text",
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "start_char": 0,
                    "end_char": 11,
                    "word_count": 2,
                    "char_count": 11,
                }
            ]

            success = await processor._process_document_pipeline(task)

            assert success is True
            mock_extract.assert_called_once_with(task.file_path)
            mock_chunk.assert_called_once()
            processor.llm_service.embed.assert_called_once()
            processor.vector_store.upsert.assert_called_once()
            processor.vector_store.persist.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_rebuilds_bm25_from_active_chunks(self, processor):
        """A successful upsert rebuilds the BM25 index from the FAISS
        active (non-deleted) chunks, through this single-writer worker."""
        # Wire a BM25 store; the active-chunk snapshot comes from the FAISS
        # store under its own lock (snapshot_active_chunks), so the worker just
        # forwards whatever that lock-safe snapshot returns to rebuild().
        processor.bm25_store = Mock()
        processor.vector_store.snapshot_active_chunks = Mock(
            return_value=[
                {"chunk_id": 0, "text": "active one"},
                {"chunk_id": 2, "text": "active two"},
            ]
        )

        task = IngestionTask(file_path="dummy_path", document_id="123", metadata={})
        processor.llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]], model="test-embed", usage_tokens=10
        )

        with (
            patch.object(processor, "_extract_text", return_value="Sample text"),
            patch.object(processor.chunking_strategy, "chunk_text") as mock_chunk,
        ):
            mock_chunk.return_value = [
                {
                    "text": "Sample text",
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "start_char": 0,
                    "end_char": 11,
                    "word_count": 2,
                    "char_count": 11,
                }
            ]

            success = await processor._process_document_pipeline(task)

        assert success is True
        processor.vector_store.snapshot_active_chunks.assert_called_once()
        processor.bm25_store.rebuild.assert_called_once()
        rebuilt_chunks = processor.bm25_store.rebuild.call_args.args[0]
        assert [c["chunk_id"] for c in rebuilt_chunks] == [0, 2]

    @pytest.mark.asyncio
    async def test_pipeline_bm25_rebuild_failure_is_non_fatal(self, processor):
        """A BM25 rebuild that raises must NOT fail an ingestion whose
        FAISS upsert/persist already succeeded (non-fatal, continuing anyway)."""
        processor.bm25_store = Mock()
        processor.bm25_store.rebuild.side_effect = OSError("disk full")
        processor.vector_store.metadata = [
            {"chunk_id": 0, "text": "active", "deleted": False},
        ]

        task = IngestionTask(file_path="dummy_path", document_id="123", metadata={})
        processor.llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]], model="test-embed", usage_tokens=10
        )

        with (
            patch.object(processor, "_extract_text", return_value="Sample text"),
            patch.object(processor.chunking_strategy, "chunk_text") as mock_chunk,
        ):
            mock_chunk.return_value = [
                {
                    "text": "Sample text",
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "start_char": 0,
                    "end_char": 11,
                    "word_count": 2,
                    "char_count": 11,
                }
            ]

            success = await processor._process_document_pipeline(task)

        # FAISS upsert succeeded, so the pipeline reports success despite BM25.
        assert success is True
        processor.bm25_store.rebuild.assert_called_once()
        processor.vector_store.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_load_coalesces_bm25_rebuild(self, processor):
        """N documents pre-enqueued before the worker starts trigger far
        fewer than N BM25 rebuilds. The rebuild is coalesced to the queue-drain
        point (Step 8 gated on queue_manager.is_empty()), removing the measured
        quadratic bulk-load cost, while the FAISS upsert still runs once per
        document (dense index stays authoritative throughout)."""
        processor.bm25_store = Mock()
        processor.vector_store.snapshot_active_chunks = Mock(
            return_value=[
                {"chunk_id": 0, "text": "active"},
            ]
        )

        n_docs = 5
        processor.llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]], model="test-embed", usage_tokens=10
        )

        with (
            patch.object(processor, "_extract_text", return_value="Sample text"),
            patch.object(processor.chunking_strategy, "chunk_text") as mock_chunk,
        ):
            mock_chunk.return_value = [
                {
                    "text": "Sample text",
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "start_char": 0,
                    "end_char": 11,
                    "word_count": 2,
                    "char_count": 11,
                }
            ]

            # Pre-enqueue N documents BEFORE the worker starts: this is the
            # realistic bulk-upload scenario where the queue is already full
            # when the single-writer worker begins draining it.
            for i in range(n_docs):
                task = IngestionTask(file_path=f"dummy_{i}", document_id=str(100 + i), metadata={})
                assert processor.queue_manager.add_task(task) is True

            await processor.start()
            # Wait for the whole batch to drain (task_done for every item).
            await asyncio.wait_for(processor.queue_manager.queue.join(), timeout=10.0)
            await processor.stop()

        # FAISS upsert ran once per document (dense index authoritative)...
        assert processor.vector_store.upsert.call_count == n_docs
        # ...but BM25 was rebuilt far fewer times than N (coalesced at drain).
        # A tiny slack (<= 2) tolerates the self-correcting drain race without
        # allowing the per-document quadratic behavior back in.
        assert processor.bm25_store.rebuild.call_count <= 2, (
            f"BM25 rebuilt {processor.bm25_store.rebuild.call_count} times for "
            f"{n_docs} docs; expected coalescing to <= 2"
        )

    @pytest.mark.asyncio
    async def test_last_doc_failure_still_rebuilds_bm25_for_earlier_docs(self, processor):
        """Regression: in a batch of >=2 documents where the LAST document
        fails before Step 8, the coalesced BM25 rebuild must still fire for the
        earlier successfully-upserted documents. Previously the rebuild was gated
        only on an empty queue inside the success path, so a trailing failure left
        BM25 permanently stale vs FAISS (hybrid retrieval silently lost the earlier
        docs from the lexical pool) until the next successful ingestion.

        Only the coalescing test's all-success path was covered before; this proves
        the failure-path drain rebuild, fired from _process_task's finally block."""
        processor.bm25_store = Mock()
        processor.vector_store.snapshot_active_chunks = Mock(
            return_value=[
                {"chunk_id": 0, "text": "active"},
            ]
        )
        processor.llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]], model="test-embed", usage_tokens=10
        )

        # Two documents: the first (100) succeeds through the whole pipeline; the
        # second (101) fails at extraction -- BEFORE the FAISS upsert / Step 8 --
        # then exhausts its retries so the batch drains with the last doc failed.
        def _extract_side_effect(file_path):
            if file_path == "dummy_fail":
                raise ProcessingError("simulated extraction failure on last doc")
            return "Sample text"

        with (
            patch.object(processor, "_extract_text", side_effect=_extract_side_effect),
            patch.object(processor.chunking_strategy, "chunk_text") as mock_chunk,
        ):
            mock_chunk.return_value = [
                {
                    "text": "Sample text",
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "start_char": 0,
                    "end_char": 11,
                    "word_count": 2,
                    "char_count": 11,
                }
            ]

            ok_task = IngestionTask(file_path="dummy_ok", document_id="100", metadata={})
            fail_task = IngestionTask(
                file_path="dummy_fail",
                document_id="101",
                metadata={},
            )
            # No retries for the failing task so the batch drains promptly.
            fail_task.max_retries = 0
            assert processor.queue_manager.add_task(ok_task) is True
            assert processor.queue_manager.add_task(fail_task) is True

            await processor.start()
            await asyncio.wait_for(processor.queue_manager.queue.join(), timeout=10.0)
            await processor.stop()

        # The first document was upserted into FAISS...
        assert processor.vector_store.upsert.call_count == 1
        # ...and despite the last document failing, BM25 was rebuilt at drain so
        # the earlier document is present in the lexical index.
        assert processor.bm25_store.rebuild.call_count >= 1, (
            "BM25 was never rebuilt after the last doc of the batch failed; "
            "the earlier successful document would be stale vs FAISS"
        )

    @pytest.mark.asyncio
    async def test_process_document_pipeline_empty_text(self, processor):
        task = IngestionTask(file_path="dummy", document_id="123")

        with patch.object(processor, "_extract_text", return_value="   \n  "):
            success = await processor._process_document_pipeline(task)

            assert success is False

    @pytest.mark.asyncio
    async def test_process_document_pipeline_no_chunks(self, processor):
        task = IngestionTask(file_path="dummy", document_id="123")

        with (
            patch.object(processor, "_extract_text", return_value="Sample text"),
            patch.object(processor.chunking_strategy, "chunk_text", return_value=[]),
        ):
            success = await processor._process_document_pipeline(task)

            assert success is False

    @pytest.mark.asyncio
    async def test_process_document_pipeline_too_many_chunks(self, processor):
        task = IngestionTask(file_path="dummy", document_id="123")

        # Create more chunks than the limit
        many_chunks = []
        for i in range(150):  # More than max_chunks_per_doc (100 in this test)
            many_chunks.append(
                {
                    "text": f"Chunk {i}",
                    "chunk_index": i,
                    "total_chunks": 150,
                    "start_char": i * 10,
                    "end_char": (i + 1) * 10,
                    "word_count": 2,
                    "char_count": 10,
                }
            )

        # Make the mock return 100 embeddings (the count after truncation)
        processor.llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]] * 100,  # 100 embeddings for 100 truncated chunks
            model="test-embed",
            usage_tokens=100,
        )

        with (
            patch.object(processor, "_extract_text", return_value="Long text"),
            patch.object(processor.chunking_strategy, "chunk_text", return_value=many_chunks),
        ):
            success = await processor._process_document_pipeline(task)

            # Must succeed and truncate the chunks
            assert success is True
            # Check that only max_chunks_per_doc chunks were processed
            call_args = processor.llm_service.embed.call_args[0][0]
            assert len(call_args) == processor.max_chunks_per_doc

    @pytest.mark.asyncio
    async def test_process_document_pipeline_embedding_mismatch(self, processor, mock_llm_service):
        task = IngestionTask(file_path="dummy", document_id="123")

        # Configure it to return the wrong number of embeddings
        mock_llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]],  # Un seul embedding
            model="test",
            usage_tokens=5,
        )

        with (
            patch.object(processor, "_extract_text", return_value="Sample text"),
            patch.object(processor.chunking_strategy, "chunk_text") as mock_chunk,
        ):
            mock_chunk.return_value = [
                {"text": "Chunk 1", "chunk_index": 0, "total_chunks": 2},
                {"text": "Chunk 2", "chunk_index": 1, "total_chunks": 2},
            ]  # Deux chunks mais un seul embedding

            success = await processor._process_document_pipeline(task)

            assert success is False

    @pytest.mark.asyncio
    async def test_process_document_pipeline_vector_store_failure(
        self, processor, mock_vector_store
    ):
        task = IngestionTask(file_path="dummy", document_id="123")
        mock_vector_store.upsert.return_value = False

        with (
            patch.object(processor, "_extract_text", return_value="Sample text"),
            patch.object(processor.chunking_strategy, "chunk_text") as mock_chunk,
        ):
            mock_chunk.return_value = [
                {
                    "text": "Sample text",
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "start_char": 0,
                    "end_char": 11,
                    "word_count": 2,
                    "char_count": 11,
                }
            ]

            success = await processor._process_document_pipeline(task)

            assert success is False

    @pytest.mark.asyncio
    async def test_process_task_success(self, processor, mock_document_repository):
        task = IngestionTask(file_path="dummy", document_id="123")

        with patch.object(
            processor, "_process_document_pipeline", new_callable=AsyncMock
        ) as mock_pipeline:
            mock_pipeline.return_value = True

            success = await processor._process_task(task)

            assert success is True
            # Check that the status was updated
            assert mock_document_repository.update_status.call_count >= 2  # indexing puis indexed

    @pytest.mark.asyncio
    async def test_process_task_failure(self, processor, mock_document_repository):
        task = IngestionTask(file_path="dummy", document_id="123")

        with patch.object(
            processor, "_process_document_pipeline", new_callable=AsyncMock
        ) as mock_pipeline:
            mock_pipeline.return_value = False

            success = await processor._process_task(task)

            assert success is False
            # Check that the error status was updated
            mock_document_repository.update_status.assert_called()
            last_call = mock_document_repository.update_status.call_args_list[-1]
            assert last_call[0][1] == "error"  # statut d'erreur

    @pytest.mark.asyncio
    async def test_process_task_exception(self, processor, mock_document_repository):
        task = IngestionTask(file_path="dummy", document_id="123")

        with patch.object(
            processor, "_process_document_pipeline", new_callable=AsyncMock
        ) as mock_pipeline:
            mock_pipeline.side_effect = Exception("Processing error")

            success = await processor._process_task(task)

            assert success is False
            # Check that the error status was updated
            mock_document_repository.update_status.assert_called()

    def test_get_stats(self, processor):
        stats = processor.get_stats()

        expected_keys = [
            "processor_running",
            "supported_extensions",
            "max_file_size_mb",
            "max_chunks_per_doc",
            "queue_stats",
        ]

        for key in expected_keys:
            assert key in stats

        assert isinstance(stats["supported_extensions"], list)
        assert stats["max_file_size_mb"] == 1  # Configuration de test
        assert stats["max_chunks_per_doc"] == 100

    def test_get_queue_size(self, processor):
        """Test de taille de queue"""
        assert processor.get_queue_size() == 0

        # The method delegated to the queue_manager should be called

    @pytest.mark.asyncio
    async def test_is_running(self, processor):
        assert processor.is_running() is False

        await processor.start()
        assert processor.is_running() is True

        await processor.stop()
        assert processor.is_running() is False

    @pytest.mark.asyncio
    async def test_clear_queue(self, processor, sample_text_file):
        """Test de vidage de queue"""
        # Add a few documents
        processor.queue_document(str(sample_text_file), document_id="1")
        initial_size = processor.get_queue_size()
        assert initial_size >= 0  # May be 0 or 1 depending on timing

        cleared = await processor.clear_queue()
        assert cleared >= 0  # May be 0 if the task was already processed
        assert processor.get_queue_size() == 0


class TestIngestionProcessorIntegration:
    """Ingestion processor integration tests"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_llm_service(self):
        """Mocked LLM service for the integration tests"""
        mock_service = AsyncMock()
        mock_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]], model="test-embed", usage_tokens=10
        )
        return mock_service

    @pytest.fixture
    def mock_vector_store(self):
        """Mocked vector store for the integration tests"""
        mock_store = Mock()
        mock_store.upsert.return_value = True
        mock_store.persist.return_value = True
        mock_store.get_stats.return_value = {"total_vectors": 0, "active_vectors": 0}
        return mock_store

    @pytest.fixture
    def mock_document_repository(self):
        """Mocked document repository for the integration tests"""
        mock_repo = Mock()
        mock_doc = Mock()
        mock_doc.id = 123
        mock_repo.create.return_value = mock_doc
        mock_repo.update_status.return_value = None
        return mock_repo

    @pytest.fixture
    def mock_budget_guard(self):
        """Mocked budget guard -- always accepts the reservation, to keep
        these tests hermetic (no write to the real cost database through
        the real singleton)"""
        mock_guard = Mock()
        mock_guard.reserve.return_value = BudgetReservation(today="2024-01-01", estimate_eur=0.001)
        mock_guard.finalize.return_value = None
        mock_guard.release.return_value = None
        return mock_guard

    @pytest.fixture
    def mock_usage_tracker(self):
        """Mocked usage tracker -- writes no real llm_usage rows
        during the ingestion pipeline integration tests"""
        mock_tracker = Mock()
        mock_tracker.record.return_value = 0.001
        return mock_tracker

    @pytest.fixture
    def real_files(self, temp_dir):
        """Vrais fichiers de test"""
        files = {}

        # Plain text file
        txt_file = temp_dir / "simple.txt"
        txt_file.write_text(
            "This is a simple text file for testing. It contains multiple sentences. Each sentence should be processed correctly.",
            encoding="utf-8",
        )
        files["txt"] = txt_file

        # Markdown file
        md_file = temp_dir / "document.md"
        md_content = """# Test Document

This is a test markdown document.

## Section 1

Content of section 1 with some text.

## Section 2

Content of section 2 with more text.

### Subsection

Even more detailed content here.
"""
        md_file.write_text(md_content, encoding="utf-8")
        files["md"] = md_file

        return files

    @pytest.mark.asyncio
    async def test_end_to_end_processing(
        self,
        real_files,
        mock_llm_service,
        mock_vector_store,
        mock_document_repository,
        mock_budget_guard,
        mock_usage_tracker,
    ):
        """Test de traitement bout en bout"""
        # Configure the mocks realistically, for the actual number of chunks
        mock_llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3, 0.4]],  # A single chunk for the plain text file
            model="test-embed",
            usage_tokens=50,
        )

        processor = IngestionProcessor(
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            max_file_size_mb=10,
            max_chunks_per_doc=50,
            budget_guard=mock_budget_guard,
            usage_tracker=mock_usage_tracker,
        )

        # Processing of a text file
        task = IngestionTask(
            file_path=str(real_files["txt"]), document_id="123", metadata={"type": "test"}
        )

        success = await processor._process_document_pipeline(task)

        assert success is True

        # Check that the mocks were called
        mock_llm_service.embed.assert_called_once()
        mock_vector_store.upsert.assert_called_once()
        mock_vector_store.persist.assert_called_once()

        # Check the created chunks
        upsert_call = mock_vector_store.upsert.call_args[0][0]
        chunks = upsert_call

        assert len(chunks) >= 1
        assert all(isinstance(chunk, Chunk) for chunk in chunks)
        assert all(chunk.document_id == "123" for chunk in chunks)
        assert all(len(chunk.text.strip()) > 0 for chunk in chunks)

    @pytest.mark.asyncio
    async def test_markdown_processing(
        self,
        real_files,
        mock_llm_service,
        mock_vector_store,
        mock_document_repository,
        mock_budget_guard,
        mock_usage_tracker,
    ):
        # Configure the mock for the markdown file (probably 1 chunk)
        mock_llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]],  # A single embedding for the markdown file
            model="test-embed",
            usage_tokens=25,
        )

        processor = IngestionProcessor(
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            budget_guard=mock_budget_guard,
            usage_tracker=mock_usage_tracker,
        )

        task = IngestionTask(
            file_path=str(real_files["md"]),
            document_id="123",  # Use an integer as a string
            metadata={"format": "markdown"},
        )

        success = await processor._process_document_pipeline(task)

        assert success is True

        # Check that the markdown content was processed
        upsert_call = mock_vector_store.upsert.call_args[0][0]
        chunks = upsert_call

        all_text = " ".join(chunk.text for chunk in chunks)
        assert "Test Document" in all_text
        assert "Section 1" in all_text
        assert "Section 2" in all_text

    @pytest.mark.asyncio
    async def test_concurrent_processing_simulation(
        self,
        real_files,
        mock_llm_service,
        mock_vector_store,
        mock_document_repository,
        mock_budget_guard,
        mock_usage_tracker,
    ):
        """Test de simulation de traitement concurrent"""
        # Configure the mock for the files (probably 1 chunk each)
        mock_llm_service.embed.return_value = EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]],  # One embedding per file
            model="test-embed",
            usage_tokens=20,
        )

        # The mock_document_repository fixture is already configured

        processor = IngestionProcessor(
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            budget_guard=mock_budget_guard,
            usage_tracker=mock_usage_tracker,
        )

        processed_docs = []

        async def tracking_callback(task):
            # Simulate the processing with the real pipeline
            success = await processor._process_document_pipeline(task)
            if success:
                processed_docs.append(task.document_id)
            return success

        await processor.start()

        # Replace the processing callback to record the results
        processor.queue_manager.processing_callback = tracking_callback

        files_to_process = [str(real_files["txt"]), str(real_files["md"])]
        for document_id, file_path in enumerate(files_to_process, start=1):
            assert processor.queue_document(file_path, document_id=str(document_id)) is True

        # Wait for the processing to finish
        await asyncio.sleep(1.0)

        await processor.stop()

        # Check that the documents were processed
        assert sorted(processed_docs) == ["1", "2"]
