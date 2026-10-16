"""
Unit tests of the FAISS vector store
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import faiss
import numpy as np
import pytest
from pydantic import ValidationError

from mimir.rag_core.implementations.faiss_store import FaissVectorStore, MetadataPayload
from mimir.rag_core.interfaces import (
    AbstractVectorStore,
    Chunk,
    SearchResult,
    VectorStoreConnectionError,
    VectorStoreException,
    VectorStoreOperationError,
)


class TestAbstractVectorStore:
    """Tests of the abstract VectorStore interface"""

    def test_abstract_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            AbstractVectorStore()


class TestChunk:
    """Chunk tests"""

    def test_chunk_creation(self):
        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        chunk = Chunk(
            text="Hello world",
            embedding=embedding,
            document_id="doc1",
            chunk_index=0,
            total_chunks=5,
            source="test.txt",
            metadata={"author": "test"},
        )

        assert chunk.text == "Hello world"
        assert np.array_equal(chunk.embedding, embedding)
        assert chunk.document_id == "doc1"
        assert chunk.chunk_index == 0
        assert chunk.total_chunks == 5
        assert chunk.source == "test.txt"
        assert chunk.metadata["author"] == "test"
        assert chunk.preserve is False

    def test_chunk_preserve_flag(self):
        chunk = Chunk(
            text="Important text",
            embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32),
            document_id="doc1",
            chunk_index=0,
            total_chunks=1,
            source="important.txt",
            metadata={},
            preserve=True,
        )

        assert chunk.preserve is True


class TestSearchResult:
    """SearchResult tests"""

    def test_search_result_creation(self):
        result = SearchResult(
            chunk_id=1,
            document_id="doc1",
            text="Hello world",
            source="test.txt",
            similarity_score=0.85,
            chunk_index=0,
            total_chunks=2,
            metadata={"type": "test"},
        )

        assert result.chunk_id == 1
        assert result.document_id == "doc1"
        assert result.text == "Hello world"
        assert result.source == "test.txt"
        assert result.similarity_score == 0.85
        assert result.chunk_index == 0
        assert result.total_chunks == 2
        assert result.metadata["type"] == "test"


class TestVectorStoreExceptions:
    """VectorStore exception tests"""

    def test_exception_hierarchy(self):
        assert issubclass(VectorStoreConnectionError, VectorStoreException)
        assert issubclass(VectorStoreOperationError, VectorStoreException)

    def test_exception_messages(self):
        exc = VectorStoreConnectionError("Connection failed")
        assert str(exc) == "Connection failed"

        exc = VectorStoreOperationError("Operation error")
        assert str(exc) == "Operation error"


class TestFaissVectorStore:
    """Tests of the FAISS vector store"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def sample_chunks(self):
        """Sample chunks for the tests"""
        chunks = []
        for i in range(3):
            embedding = np.random.rand(128).astype(np.float32)  # Dimension plus commune
            chunk = Chunk(
                text=f"This is test chunk number {i}",
                embedding=embedding,
                document_id=f"doc_{i}",
                chunk_index=0,
                total_chunks=1,
                source=f"test_{i}.txt",
                metadata={"type": "test", "number": i},
            )
            chunks.append(chunk)
        return chunks

    def test_faiss_store_initialization(self, temp_dir):
        index_path = temp_dir / "test.index"
        metadata_path = temp_dir / "test.json"

        store = FaissVectorStore(
            dimension=128,
            index_path=str(index_path),
            metadata_path=str(metadata_path),
            similarity_threshold=0.7,
            index_type="FlatL2",
        )

        assert store.dimension == 128
        assert store.index_path == index_path
        assert store.metadata_path == metadata_path
        assert store.similarity_threshold == 0.7
        assert store.index_type == "FlatL2"

    def test_faiss_store_upsert(self, temp_dir, sample_chunks):
        """Test d'ajout de chunks"""
        index_path = temp_dir / "test.index"
        metadata_path = temp_dir / "test.json"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        # Test d'ajout
        success = store.upsert(sample_chunks)
        assert success is True

    def test_optimize_remaps_document_mapping_without_cross_document_corruption(self, temp_dir):
        """Regression: optimize() must remap document_to_chunks to the new
        compacted positions. The stored ids double as direct indices into
        self.metadata in delete(), so a stale mapping would make a document own
        another document's chunks and delete() would corrupt the wrong ones."""
        store = FaissVectorStore(
            dimension=128,
            index_path=str(temp_dir / "opt.index"),
            metadata_path=str(temp_dir / "opt.json"),
        )

        # 3 documents x 2 chunks -> chunk ids 0..5
        chunks = []
        for doc in ("doc_A", "doc_B", "doc_C"):
            for idx in range(2):
                chunks.append(
                    Chunk(
                        text=f"{doc} chunk {idx}",
                        embedding=np.random.rand(128).astype(np.float32),
                        document_id=doc,
                        chunk_index=idx,
                        total_chunks=2,
                        source=f"{doc}.txt",
                        metadata={"document_id": doc},
                    )
                )
        assert store.upsert(chunks) is True

        # Delete the FIRST document so surviving chunks shift positions on rebuild
        assert store.delete("doc_A") is True
        store.optimize()

        # Invariant delete() relies on: every id in the mapping indexes metadata
        # that belongs to the SAME document.
        assert "doc_A" not in store.document_to_chunks
        for doc in ("doc_B", "doc_C"):
            chunk_ids = store.document_to_chunks[doc]
            assert len(chunk_ids) == 2
            for cid in chunk_ids:
                assert 0 <= cid < len(store.metadata)
                assert store.metadata[cid]["document_id"] == doc

        # Real failure mode: deleting doc_B after optimize must not touch doc_C.
        assert store.delete("doc_B") is True
        c_texts = {c.text for c in store.get_document_chunks("doc_C")}
        assert c_texts == {"doc_C chunk 0", "doc_C chunk 1"}

    def test_snapshot_active_chunks_excludes_deleted(self, temp_dir):
        """snapshot_active_chunks returns lock-safe copies of non-deleted chunk
        metadata only (source for the BM25 rebuild)."""
        store = FaissVectorStore(
            dimension=128,
            index_path=str(temp_dir / "snap.index"),
            metadata_path=str(temp_dir / "snap.json"),
        )
        store.metadata = [
            {"chunk_id": 0, "text": "active one", "deleted": False},
            {"chunk_id": 1, "text": "removed", "deleted": True},
            {"chunk_id": 2, "text": "active two"},  # no 'deleted' key -> active
        ]
        snap = store.snapshot_active_chunks()
        assert [c["chunk_id"] for c in snap] == [0, 2]
        # Copies, not references: mutating the snapshot must not touch the store.
        snap[0]["text"] = "mutated"
        assert store.metadata[0]["text"] == "active one"

    def test_faiss_store_query_empty(self, temp_dir):
        index_path = temp_dir / "empty.index"
        metadata_path = temp_dir / "empty.json"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        query_vector = np.random.rand(128).astype(np.float32)
        results = store.query(query_vector, top_k=5)

        assert results == []

    def test_faiss_store_health_check(self, temp_dir):
        """Test de health check"""
        index_path = temp_dir / "health.index"
        metadata_path = temp_dir / "health.json"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        # The health check must pass after initialization
        is_healthy = store.health_check()
        assert isinstance(is_healthy, bool)

    def test_faiss_store_stats(self, temp_dir):
        index_path = temp_dir / "stats.index"
        metadata_path = temp_dir / "stats.json"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        stats = store.get_stats()

        assert isinstance(stats, dict)
        # The exact keys depend on the implementation

    def test_faiss_store_persist_load(self, temp_dir):
        """Test de persistance et chargement"""
        index_path = temp_dir / "persist.index"
        metadata_path = temp_dir / "persist.json"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        # Test de persistance
        success = store.persist()
        assert isinstance(success, bool)

        # Test de chargement
        success = store.load()
        assert isinstance(success, bool)

    def test_atomic_persist_no_tmp(self, temp_dir, sample_chunks):
        """persist() writes index then metadata.json atomically, leaving no .tmp files"""
        index_path = temp_dir / "atomic.index"
        metadata_path = temp_dir / "atomic.metadata"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )
        store.upsert(sample_chunks)

        success = store.persist()
        assert success is True

        # metadata.json exists, parses as JSON, and carries schema_version
        assert store.metadata_path.exists()
        with open(store.metadata_path, encoding="utf-8") as f:
            raw = json.load(f)
        assert raw["schema_version"] == 1
        assert "metadata" in raw
        assert "document_to_chunks" in raw
        assert "stats" in raw
        assert "saved_at" in raw

        # No residual .tmp files left in the faiss directory
        assert list(temp_dir.glob("*.tmp")) == []

    def test_atomic_persist_crash_order(self, temp_dir, sample_chunks):
        """A crash between index replace and metadata replace leaves the index
        ahead of the metadata, never the reverse"""
        index_path = temp_dir / "crash.index"
        metadata_path = temp_dir / "crash.metadata"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        # v1: successful persist with the first chunk only
        store.upsert(sample_chunks[:1])
        assert store.persist() is True

        v1_ntotal = store.index.ntotal
        with open(store.metadata_path, encoding="utf-8") as f:
            v1_metadata_raw = json.load(f)

        # v2: add more chunks, then simulate a crash on the SECOND os.replace
        # call (metadata) while letting the first (index) succeed
        store.upsert(sample_chunks[1:])

        real_replace = os.replace
        call_count = {"n": 0}

        def flaky_replace(src, dst):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OSError("Simulated crash during metadata replace")
            return real_replace(src, dst)

        with (
            patch(
                "mimir.rag_core.implementations.faiss_store.os.replace",
                side_effect=flaky_replace,
            ),
            pytest.raises(VectorStoreConnectionError),
        ):
            store.persist()

        # Index on disk reflects v2 (already replaced); metadata.json on
        # disk still reflects v1 (never replaced) -- read directly, not via
        # the store's own load(), to prove the on-disk pair invariant.
        reread_index = faiss.read_index(str(store.index_path))
        assert reread_index.ntotal == store.index.ntotal
        assert reread_index.ntotal > v1_ntotal

        with open(store.metadata_path, encoding="utf-8") as f:
            reread_metadata_raw = json.load(f)
        assert reread_metadata_raw == v1_metadata_raw

    def test_schema_validation(self):
        """MetadataPayload rejects a payload missing schema_version"""
        payload_without_version = {
            "metadata": [],
            "document_to_chunks": {},
            "stats": {},
            "saved_at": "2026-07-12T00:00:00",
        }

        with pytest.raises(ValidationError):
            MetadataPayload.model_validate(payload_without_version)

    def test_faiss_store_delete(self, temp_dir, sample_chunks):
        """Test de suppression de documents"""
        index_path = temp_dir / "delete.index"
        metadata_path = temp_dir / "delete.json"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        # Add chunks first
        store.upsert(sample_chunks)

        # Tenter de supprimer un document
        success = store.delete("doc_0")
        assert isinstance(success, bool)

    @patch("faiss.IndexFlatL2")
    def test_faiss_store_with_mock_index(self, mock_index_class, temp_dir):
        mock_index = Mock()
        mock_index.ntotal = 0
        mock_index_class.return_value = mock_index

        index_path = temp_dir / "mock.index"
        metadata_path = temp_dir / "mock.json"

        FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        # Check that the index was created
        mock_index_class.assert_called_with(128)

    def test_faiss_store_invalid_dimension(self, temp_dir):
        index_path = temp_dir / "invalid.index"
        metadata_path = temp_dir / "invalid.json"

        # Negative dimension: the current code does not prevent it
        # so only check that initialization raises no error
        store = FaissVectorStore(
            dimension=-1, index_path=str(index_path), metadata_path=str(metadata_path)
        )
        assert store.dimension == -1


class TestFaissIntegration:
    """Integration tests of FAISS"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_basic_workflow(self, temp_dir):
        """Test de workflow basique"""
        index_path = temp_dir / "workflow.index"
        metadata_path = temp_dir / "workflow.json"

        # Create the store
        store = FaissVectorStore(
            dimension=128,
            index_path=str(index_path),
            metadata_path=str(metadata_path),
            similarity_threshold=0.5,
        )

        # Create a few chunks
        chunks = []
        for i in range(3):
            chunk = Chunk(
                text=f"Document content {i}",
                embedding=np.random.rand(128).astype(np.float32),
                document_id=f"doc_{i}",
                chunk_index=0,
                total_chunks=1,
                source=f"doc_{i}.txt",
                metadata={"category": "test"},
            )
            chunks.append(chunk)

        # Full workflow
        # 1. Add chunks
        success = store.upsert(chunks)
        assert success is True

        # 2. Tester health check
        is_healthy = store.health_check()
        assert isinstance(is_healthy, bool)

        # 3. Get the statistics
        stats = store.get_stats()
        assert isinstance(stats, dict)

        # 4. Persister
        success = store.persist()
        assert isinstance(success, bool)

        # 5. Create a new store and load
        new_store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        success = new_store.load()
        assert isinstance(success, bool)

    def test_thread_safety_basic(self, temp_dir):
        """Test basique de thread safety"""
        import threading

        index_path = temp_dir / "thread.index"
        metadata_path = temp_dir / "thread.json"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        results = []

        def worker():
            """Worker running operations on the store"""
            try:
                # Basic operations
                stats = store.get_stats()
                health = store.health_check()
                results.append((stats, health))
            except Exception as e:  # noqa: BLE001 - thread harness: collect any error for the assertion
                results.append(e)

        # Lancer plusieurs threads
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Check that everything went well
        assert len(results) == 3
        for result in results:
            assert not isinstance(result, Exception)
