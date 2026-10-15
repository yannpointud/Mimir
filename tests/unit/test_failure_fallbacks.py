"""Regression tests: failure paths keep their pre-cleanup fallbacks.

Each test injects an exception type that is NOT in the narrowed lists pass 2
had introduced (docs/cleanup/REVIEW.md, DECISIONS DF.x) and checks the
original fallback: the BM25 drain rebuild stays best effort (B1), a truncated
BM25 index never blocks startup or ingestion (B2), a broken PDF page is
skipped (B3), the analytics endpoints keep their defaults (M2), and the other
best-effort, degradation and wrapping contracts restored after the review.

Everything is imported through the ``src.`` namespace, like the modules under
test import each other, so patches and singletons hit the same module objects.
"""

import asyncio
import json
from datetime import datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pypdf
import pytest

from src.cost.budget_guard import BudgetReservation
from src.ingestion.chunking import ChunkingConfig
from src.ingestion.extractors import DOCXExtractor, ExtractionError, PDFExtractor
from src.ingestion.processor import IngestionProcessor
from src.ingestion.queue_manager import IngestionTask
from src.llm_interface.implementations.mistral_api import MistralAPIService
from src.llm_interface.interfaces import EmbeddingResponse, LLMAPIError
from src.rag_core.implementations.bm25_store import Bm25LexicalStore
from src.rag_core.implementations.faiss_store import FaissVectorStore
from src.rag_core.interfaces import Chunk, SearchResult, VectorStoreConnectionError
from src.services import index_maintenance
from src.services.document_upload import DocumentUpload, UploadPolicy
from src.services.errors import RequestRejectedError


# ---------------------------------------------------------------- B1


def _ingestion_processor(vector_store):
    llm = AsyncMock()
    llm.embed.return_value = EmbeddingResponse(
        embeddings=[[0.1, 0.2, 0.3]], model="test-embed", usage_tokens=10
    )
    guard = Mock()
    guard.reserve.return_value = BudgetReservation(today="2024-01-01", estimate_eur=0.001)
    tracker = Mock()
    tracker.record.return_value = 0.001
    return IngestionProcessor(
        llm_service=llm,
        vector_store=vector_store,
        document_repository=Mock(),
        chunking_config=ChunkingConfig(chunk_size=100, overlap=10),
        budget_guard=guard,
        usage_tracker=tracker,
    )


async def _run_pipeline(processor):
    task = IngestionTask(file_path="dummy_path", document_id="123", metadata={})
    chunk = {
        "text": "Sample text",
        "chunk_index": 0,
        "total_chunks": 1,
        "start_char": 0,
        "end_char": 11,
        "word_count": 2,
        "char_count": 11,
    }
    with (
        patch.object(processor, "_extract_text", return_value="Sample text"),
        patch.object(processor.chunking_strategy, "chunk_text", return_value=[chunk]),
    ):
        return await processor._process_document_pipeline(task)


class TestBm25DrainIsBestEffort:
    """B1: once FAISS holds the chunks, no BM25 failure fails the ingestion."""

    @pytest.mark.asyncio
    async def test_unlisted_rebuild_error_keeps_the_ingestion(self):
        vector_store = Mock()
        vector_store.upsert.return_value = True
        vector_store.persist.return_value = True
        vector_store.snapshot_active_chunks.return_value = [{"chunk_id": 0, "text": "active"}]
        processor = _ingestion_processor(vector_store)
        processor.bm25_store = Mock()
        processor.bm25_store.rebuild.side_effect = MemoryError("bm25 index too large")

        assert await _run_pipeline(processor) is True
        vector_store.upsert.assert_called_once()
        # The rebuild is still owed: a later drain retries it.
        assert processor._bm25_dirty is True

    @pytest.mark.asyncio
    async def test_snapshot_error_keeps_the_ingestion(self):
        vector_store = Mock()
        vector_store.upsert.return_value = True
        vector_store.persist.return_value = True
        vector_store.snapshot_active_chunks.side_effect = ArithmeticError("snapshot")
        processor = _ingestion_processor(vector_store)
        processor.bm25_store = Mock()

        assert await _run_pipeline(processor) is True
        processor.bm25_store.rebuild.assert_not_called()
        assert processor._bm25_dirty is True


# ---------------------------------------------------------------- B2


def _truncated_bm25_index(tmp_path: Path) -> Path:
    """A persisted BM25 index whose first .npy array file is empty (truncated)."""
    index_dir = tmp_path / "bm25"
    Bm25LexicalStore(str(index_dir)).rebuild(
        [
            {"chunk_id": 0, "text": "politique de télétravail"},
            {"chunk_id": 1, "text": "notes de frais"},
        ]
    )
    npy_files = sorted(index_dir.glob("*.npy"))
    assert npy_files
    npy_files[0].write_bytes(b"")
    return index_dir


class TestTruncatedBm25Index:
    """B2: a truncated BM25 index degrades to an empty store, never blocks startup."""

    def test_load_wraps_the_eof_error(self, tmp_path):
        index_dir = _truncated_bm25_index(tmp_path)

        with pytest.raises(VectorStoreConnectionError, match="Failed to load BM25 lexical index"):
            Bm25LexicalStore(str(index_dir)).load()

    def test_get_bm25_store_returns_a_usable_store(self, tmp_path, monkeypatch):
        from src.api import dependencies
        from src.config import settings

        monkeypatch.setattr(settings, "bm25_index_path", str(_truncated_bm25_index(tmp_path)))
        monkeypatch.setattr(dependencies, "_bm25_store", None)

        store = dependencies.get_bm25_store()

        assert isinstance(store, Bm25LexicalStore)
        # The ingestion drain can rebuild it from FAISS and query it again.
        store.rebuild([{"chunk_id": 7, "text": "politique de télétravail"}])
        assert store.query("télétravail", top_k=5)[0][0] == 7

    def test_get_bm25_store_survives_any_load_error(self, monkeypatch):
        from src.api import dependencies

        monkeypatch.setattr(dependencies, "_bm25_store", None)
        monkeypatch.setattr(Bm25LexicalStore, "load", Mock(side_effect=EOFError("No data")))

        assert isinstance(dependencies.get_bm25_store(), Bm25LexicalStore)

    def test_ensure_bm25_index_never_raises(self, monkeypatch):
        import backend.main as main_module

        broken = Mock()
        broken.load.side_effect = EOFError("No data left in file")
        monkeypatch.setattr(main_module, "get_bm25_store", lambda: broken)
        monkeypatch.setattr(main_module, "get_vector_store", Mock())

        main_module._ensure_bm25_index()

    @pytest.mark.asyncio
    async def test_ingestion_still_starts(self, tmp_path, monkeypatch):
        import backend.main as main_module
        from src.api import dependencies
        from src.config import settings
        from src.database.connection import db_manager

        monkeypatch.setattr(settings, "bm25_index_path", str(_truncated_bm25_index(tmp_path)))
        monkeypatch.setattr(dependencies, "_bm25_store", None)
        monkeypatch.setattr(main_module, "ingestion_processor", None)
        processor = Mock()
        processor.start = AsyncMock()
        monkeypatch.setattr(main_module, "IngestionProcessor", Mock(return_value=processor))
        monkeypatch.setattr(main_module, "get_llm_service", Mock())
        vector_store = Mock()
        vector_store.snapshot_active_chunks.return_value = []
        monkeypatch.setattr(main_module, "get_vector_store", lambda: vector_store)
        monkeypatch.setattr(main_module, "_queue_pending_documents", Mock())
        set_processor = Mock()
        monkeypatch.setattr(main_module, "set_ingestion_processor", set_processor)
        monkeypatch.setattr(db_manager, "get_session_context", lambda: MagicMock())

        await main_module._start_ingestion()

        set_processor.assert_called_once_with(processor)


# ---------------------------------------------------------------- B3


def _two_page_pdf(tmp_path: Path) -> str:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    pdf_path = tmp_path / "two_pages.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return str(pdf_path)


class TestParserFailures:
    """B3: a broken page is skipped; any other parser failure is an ExtractionError."""

    def test_failing_page_is_skipped(self, tmp_path):
        pdf_path = _two_page_pdf(tmp_path)
        pages = ["Texte de la page un.", ZeroDivisionError("float division by zero")]

        with patch.object(pypdf.PageObject, "extract_text", side_effect=pages):
            assert PDFExtractor().extract(pdf_path) == "Texte de la page un."

    def test_unlisted_pdf_error_becomes_extraction_error(self, tmp_path):
        pdf_path = _two_page_pdf(tmp_path)

        with (
            patch("pypdf.PdfReader", side_effect=AssertionError("broken xref")),
            pytest.raises(ExtractionError, match="broken xref"),
        ):
            PDFExtractor().extract(pdf_path)

    def test_unlisted_docx_error_becomes_extraction_error(self):
        with (
            patch("src.ingestion.extractors.DocxDocument", side_effect=OverflowError("bad")),
            pytest.raises(ExtractionError, match="Failed to extract text from DOCX"),
        ):
            DOCXExtractor().extract("broken.docx")


# ---------------------------------------------------------------- M2


class TestAnalyticsFallbacks:
    """M2: a JSON line that is not an object never turns analytics into a 500."""

    @pytest.fixture
    def app_log(self, tmp_path, monkeypatch):
        import src.utils.log_parser as log_parser

        recent = (datetime.utcnow() - timedelta(minutes=10)).isoformat() + "Z"
        entry = {
            "timestamp": recent,
            "module": "mistral_api",
            "message": "Text generation successful: 10 tokens",
            "type": "text_generation",
            "tokens": 10,
            "duration_ms": 120,
        }
        app_log = tmp_path / "app.log"
        app_log.write_text(json.dumps(entry) + "\n123\n", encoding="utf-8")
        monkeypatch.setattr(log_parser, "APP_LOG", app_log)
        monkeypatch.setattr(log_parser, "UVICORN_LOG", tmp_path / "missing_uvicorn.log")
        monkeypatch.setattr(log_parser, "ERROR_LOG", tmp_path / "missing_error.log")
        return app_log

    def test_chat_metrics_skip_the_bad_line(self, app_log):
        import src.utils.log_parser as log_parser

        metrics = log_parser.get_chat_metrics()

        assert metrics["requests_last_hour"] == 1
        assert metrics["avg_tokens_per_request"] == 10 + 150 // 4

    def test_period_metrics_fall_back_to_their_default(self, app_log):
        import src.utils.log_parser as log_parser

        assert log_parser._count_requests_in_period(timedelta(hours=24)) == 0
        assert log_parser._estimate_system_uptime() == "N/A"

    def test_usage_analytics_endpoint_answers(self, app_log):
        from src.api.endpoints import admin

        analytics = asyncio.run(admin.get_usage_analytics(current_user={"sub": "admin"}))

        assert analytics["overview"]["total_requests_24h"] == 0
        assert analytics["system"]["health_score"] == 100
        assert "timestamp" in analytics

    def test_usage_analytics_default_payload(self, monkeypatch):
        import src.utils.log_parser as log_parser

        monkeypatch.setattr(log_parser, "_get_log_file_sizes", Mock(side_effect=RuntimeError()))

        analytics = log_parser.get_usage_analytics()

        assert analytics["system"] == {
            "log_file_sizes": {},
            "uptime_estimate": "N/A",
            "error_rate_24h": 0,
            "health_score": 85,
        }

    def test_logs_summary_default_payload(self, monkeypatch):
        import src.utils.logs_reader as logs_reader

        monkeypatch.setattr(logs_reader, "_read_log_file", Mock(side_effect=RuntimeError()))

        summary = logs_reader.get_logs_summary()

        assert summary["total_logs_count"] == 0
        assert summary["modules_available"] == []


# ---------------------------------------------------------------- I1 to I4


class TestRestoredBestEffortBlocks:
    @pytest.mark.asyncio
    async def test_bm25_query_failure_degrades_to_dense_only(self):
        """I1: any BM25 query failure falls back to the dense pool."""
        from src.services.rag_service import _hybrid_retrieve

        dense_pool = [
            SearchResult(
                chunk_id=i,
                document_id="10",
                text=f"dense hit {i}",
                source="a.txt",
                similarity_score=0.4,
                chunk_index=0,
                total_chunks=1,
                metadata={},
            )
            for i in (1, 2)
        ]
        vector_store = Mock()
        vector_store.query.return_value = dense_pool
        vector_store.snapshot_active_chunks.return_value = []
        bm25_store = Mock()
        bm25_store.query.side_effect = ArithmeticError("degenerate corpus")

        with patch("src.services.rag_service.settings") as mock_settings:
            mock_settings.rrf_k = 60
            results = await _hybrid_retrieve(
                "question", np.zeros(3), vector_store, bm25_store, [], Mock(), "s1", 10
            )

        assert [r.chunk_id for r in results] == [1, 2]

    @pytest.mark.asyncio
    async def test_failed_orphan_cleanup_still_resyncs_bm25(self):
        """I2: the orphan cleanup and the BM25 resync are independent."""
        vector_store = Mock()
        vector_store.delete.return_value = True
        vector_store.get_stats.return_value = {"deleted_vectors": 5, "total_vectors": 10}
        vector_store.clean_orphans.side_effect = RuntimeError("persist failed")
        vector_store.snapshot_active_chunks.return_value = [{"chunk_id": 0, "text": "kept"}]
        bm25_store = Mock()

        await index_maintenance.remove_document_from_indexes(vector_store, bm25_store, 1, "a.txt")

        bm25_store.rebuild.assert_called_once_with([{"chunk_id": 0, "text": "kept"}])

    def test_failed_cleanup_after_full_queue_still_answers_503(self, tmp_path):
        """I3: a cleanup failure never turns the queue-full 503 into a 500."""
        upload = DocumentUpload(
            Mock(filename="a.txt", size=10),
            UploadPolicy(upload_dir=str(tmp_path), max_file_size_mb=1, invalid_filename_detail="x"),
        )
        upload.filename = "a.txt"
        doc_repo = Mock()
        doc_repo.delete.side_effect = RuntimeError("database is locked")

        with pytest.raises(RequestRejectedError) as exc_info:
            upload._reject_queue_full(
                Mock(get_queue_size=Mock(return_value=0)), doc_repo, Mock(id=1), tmp_path / "a.txt"
            )

        assert exc_info.value.status_code == HTTPStatus.SERVICE_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_notification_email_never_raises(self):
        """I4: /admin/test-email keeps its 200 {success: false} on any send error."""
        from src.email_service.smtp_client import EmailService

        service = EmailService()
        service.smtp_host, service.smtp_user, service.escalation_email = "h", "u", "e"

        with patch.object(service, "_send_email", side_effect=RuntimeError("boom")):
            assert await service.send_notification_email("to@example.com", "s", "m") is False


# ---------------------------------------------------------------- M3 to M5


class TestRestoredFallbacks:
    def test_disk_usage_reports_the_failing_directory_only(self, tmp_path):
        """M3: an unexpected error in one directory fills in that entry."""
        from src.api.endpoints import health

        with (
            patch("src.api.endpoints.health.settings") as mock_settings,
            patch("shutil.disk_usage", side_effect=ZeroDivisionError("boom")),
        ):
            mock_settings.data_dir = str(tmp_path)
            mock_settings.upload_dir = str(tmp_path)
            mock_settings.faiss_index_path = str(tmp_path / "index.bin")
            result = asyncio.run(health.disk_usage())

        assert result["healthy"] is True
        assert result["disk_usage"]["data_dir"] == {"path": str(tmp_path), "error": "boom"}

    def test_audit_failure_of_a_failed_rebuild_is_only_logged(self):
        """M4: record_rebuild_failure never raises."""
        audit_repo = Mock()
        audit_repo.create_log.side_effect = RuntimeError("audit down")

        index_maintenance.record_rebuild_failure(audit_repo, ValueError("x"), "admin")

    def test_unreadable_faiss_index_starts_empty(self, tmp_path):
        """M4: any load failure (e.g. a legacy pickle module) gives an empty index."""
        paths = {"index_path": str(tmp_path / "i.bin"), "metadata_path": str(tmp_path / "m.json")}
        store = FaissVectorStore(dimension=3, **paths)
        store.upsert(
            [
                Chunk(
                    text="t",
                    embedding=np.ones(3, dtype=np.float32),
                    document_id="1",
                    chunk_index=0,
                    total_chunks=1,
                    source="s",
                    metadata={},
                )
            ]
        )
        store.persist()

        with patch(
            "src.rag_core.implementations.faiss_store.faiss.read_index",
            side_effect=ModuleNotFoundError("legacy_module"),
        ):
            reloaded = FaissVectorStore(dimension=3, **paths)
            with pytest.raises(VectorStoreConnectionError):
                reloaded.load()

        assert reloaded.index.ntotal == 0

    def test_existing_document_ids_fall_back_to_the_faiss_mapping(self, tmp_path):
        """M4: any database failure falls back to the ids known to FAISS."""
        store = FaissVectorStore(
            dimension=3, index_path=str(tmp_path / "i.bin"), metadata_path=str(tmp_path / "m.json")
        )
        store.document_to_chunks = {"7": [0]}

        with patch(
            "src.database.connection.DatabaseManager", side_effect=RuntimeError("no database")
        ):
            assert store._get_existing_document_ids() == {"7"}

    @pytest.mark.asyncio
    async def test_unexpected_request_error_becomes_llm_api_error(self):
        """M5: _make_request wraps any unexpected error into LLMAPIError."""
        service = MistralAPIService(api_key="test-key", max_retries=0)
        session = Mock()
        session.post.side_effect = TypeError("payload is not JSON serializable")

        with (
            patch.object(service, "_get_session", return_value=session),
            pytest.raises(LLMAPIError, match="Unexpected error"),
        ):
            await service._make_request("chat/completions", {"model": "m"})

    @pytest.mark.asyncio
    async def test_health_check_reports_any_failure_as_unavailable(self):
        """M5: health_check returns False on any error."""
        service = MistralAPIService(api_key="test-key")

        with patch.object(service, "_make_request", side_effect=RuntimeError("boom")):
            assert await service.health_check() is False

    @pytest.mark.asyncio
    async def test_failing_embedding_batch_becomes_llm_api_error(self):
        """M5: the batching loop wraps any batch failure into LLMAPIError."""
        service = MistralAPIService(api_key="test-key")

        with (
            patch("src.config.settings.embedding_batch_size", 1),
            patch.object(service, "_embed_batch", side_effect=RuntimeError("boom")),
            pytest.raises(LLMAPIError, match="Embedding batch 1/2 failed: boom"),
        ):
            await service.embed(["a", "b"])
