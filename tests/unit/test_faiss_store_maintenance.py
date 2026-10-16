"""
More FaissVectorStore unit tests
Edge cases
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

from mimir.rag_core.implementations.faiss_store import FaissVectorStore
from mimir.rag_core.interfaces import Chunk, VectorStoreOperationError


class TestFaissVectorStoreEdgeCases:
    """Edge-case tests"""

    @pytest.fixture
    def temp_store(self):
        """Temporary store"""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "test.index"
            metadata_path = Path(temp_dir) / "test.metadata"
            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )
            yield store

    def test_faiss_store_add_chunks_basic(self, temp_store):
        """Test d'ajout de base de chunks"""
        # Create test chunks with the right signature
        chunks = [
            Chunk(
                text="Test chunk 1",
                embedding=np.random.random(128).astype(np.float32),
                document_id="doc_1",
                chunk_index=0,
                total_chunks=2,
                source="test_source",
                metadata={"id": "1"},
            ),
            Chunk(
                text="Test chunk 2",
                embedding=np.random.random(128).astype(np.float32),
                document_id="doc_1",
                chunk_index=1,
                total_chunks=2,
                source="test_source",
                metadata={"id": "2"},
            ),
        ]

        assert temp_store.upsert(chunks) is True

    def test_faiss_store_search_basic(self, temp_store):
        """Test de recherche de base"""
        # Add a few vectors
        chunks = [
            Chunk(
                text=f"Test chunk {i}",
                embedding=np.random.random(128).astype(np.float32),
                document_id=f"doc_{i}",
                chunk_index=0,
                total_chunks=1,
                source="test_source",
                metadata={"id": str(i)},
            )
            for i in range(5)
        ]

        temp_store.upsert(chunks)

        # Run a search
        query_vector = np.random.random(128).astype(np.float32)
        results = temp_store.query(query_vector, top_k=3)

        assert isinstance(results, list)
        assert len(results) <= 3

    def test_faiss_store_get_stats(self, temp_store):
        # Initially 0
        stats = temp_store.get_stats()
        assert stats["total_vectors"] == 0

        # Add chunks
        chunks = [
            Chunk(
                text="Test",
                embedding=np.random.random(128).astype(np.float32),
                document_id="doc_1",
                chunk_index=0,
                total_chunks=1,
                source="test_source",
                metadata={"id": "1"},
            )
        ]
        temp_store.upsert(chunks)

        # Now 1
        stats = temp_store.get_stats()
        assert stats["total_vectors"] == 1

    def test_faiss_store_delete_documents(self, temp_store):
        """Test de suppression de documents"""
        # Add several chunks to avoid the automatic optimization (>25% deleted)
        chunks = [
            Chunk(
                text=f"Test {i}",
                embedding=np.random.random(128).astype(np.float32),
                document_id=f"doc_{i}",
                chunk_index=0,
                total_chunks=1,
                source="test_source",
                metadata={"id": str(i)},
            )
            for i in range(5)  # 5 chunks, supprimer 1 = 20% < 25%
        ]
        temp_store.upsert(chunks)
        stats = temp_store.get_stats()
        initial_total = stats["total_vectors"]
        assert initial_total == 5

        # Delete a document (no optimization: <25%)
        temp_store.delete("doc_1")
        stats_after = temp_store.get_stats()

        # Check that the document was marked as deleted
        # No optimization: 1/5 = 20% < 25%
        assert stats_after["deleted_vectors"] == 1
        assert stats_after["active_vectors"] == 4
        assert stats_after["total_vectors"] == initial_total  # Index pas reconstruit

    def test_faiss_store_empty_search(self, temp_store):
        query_vector = np.random.random(128).astype(np.float32)
        results = temp_store.query(query_vector, top_k=5)

        assert isinstance(results, list)
        assert len(results) == 0

    def test_faiss_store_large_batch(self, temp_store):
        # Create a batch of 100 chunks
        chunks = [
            Chunk(
                text=f"Large batch chunk {i}",
                embedding=np.random.random(128).astype(np.float32),
                document_id=f"doc_{i}",
                chunk_index=0,
                total_chunks=1,
                source="test_source",
                metadata={"id": str(i), "batch": "large"},
            )
            for i in range(100)
        ]

        temp_store.upsert(chunks)
        stats = temp_store.get_stats()
        assert stats["total_vectors"] == 100

        # Recherche
        # Query with one of the added vectors to guarantee results
        query_vector = chunks[0].embedding
        results = temp_store.query(query_vector, top_k=10)
        assert len(results) > 0  # At least a few results


class TestFaissStoreFunctionality:
    """Advanced feature tests"""

    @pytest.fixture
    def populated_store(self):
        """Pre-filled store"""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "populated.index"
            metadata_path = Path(temp_dir) / "populated.metadata"

            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )

            # Add test data
            chunks = [
                Chunk(
                    text=f"Content {i}",
                    embedding=np.random.random(128).astype(np.float32),
                    document_id=f"doc_{i}",
                    chunk_index=0,
                    total_chunks=1,
                    source="test_source",
                    metadata={"id": str(i)},
                )
                for i in range(10)
            ]
            store.upsert(chunks)
            yield store

    def test_faiss_store_consistent_search(self, populated_store):
        query_vector = np.random.random(128).astype(np.float32)

        # Run the same search several times
        results1 = populated_store.query(query_vector, top_k=5)
        results2 = populated_store.query(query_vector, top_k=5)

        # The results must be identical
        assert len(results1) == len(results2)
        for i in range(len(results1)):
            assert results1[i].text == results2[i].text

    def test_faiss_store_vector_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "validation.index"
            metadata_path = Path(temp_dir) / "validation.metadata"

            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )

            # Wrong dimension
            invalid_chunk = Chunk(
                text="Invalid dimension",
                embedding=np.random.random(64).astype(np.float32),  # Wrong dimension
                document_id="doc_invalid",
                chunk_index=0,
                total_chunks=1,
                source="test_source",
                metadata={"id": "invalid"},
            )

            with pytest.raises(VectorStoreOperationError, match="Invalid embedding dimension"):
                store.upsert([invalid_chunk])

    def test_faiss_store_search_top_k_variations(self, populated_store):
        query_vector = np.random.random(128).astype(np.float32)

        # Use an existing vector to guarantee results
        # Get a test vector from the stats and the metadata
        test_chunks = [
            Chunk(
                text="Test query",
                embedding=np.random.random(128).astype(np.float32),
                document_id="test_query_doc",
                chunk_index=0,
                total_chunks=1,
                source="test_source",
                metadata={"id": "test_query"},
            )
        ]
        populated_store.upsert(test_chunks)
        query_vector = test_chunks[0].embedding

        for k in [1, 3, 5, 10, 15]:
            results = populated_store.query(query_vector, top_k=k)
            stats = populated_store.get_stats()
            min(k, stats["total_vectors"])
            # An identical vector should give at least one result
            assert len(results) >= 1


class TestBackupRotation:
    """Tests for FAISS backup creation and rotation logic"""

    @pytest.fixture
    def store_with_data(self):
        """Store with saved index/metadata files on disk"""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "index.bin"
            metadata_path = Path(temp_dir) / "metadata.json"
            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )
            # Add a chunk so save creates real files
            chunk = Chunk(
                text="Backup test",
                embedding=np.random.random(128).astype(np.float32),
                document_id="doc_backup",
                chunk_index=0,
                total_chunks=1,
                source="test",
                metadata={"id": "1"},
            )
            store.upsert([chunk])
            store.persist()
            yield store, Path(temp_dir)

    def test_create_backup_creates_files(self, store_with_data):
        """Backup should create both index and metadata backup files"""
        store, temp_dir = store_with_data
        store._create_backup("20260101_120000")

        index_backups = list(temp_dir.glob("index*.backup_*"))
        metadata_backups = list(temp_dir.glob("metadata*.backup_*"))
        assert len(index_backups) == 1
        assert len(metadata_backups) == 1

    def test_rotate_backups_removes_excess(self, store_with_data):
        """Rotation should keep only max_backups most recent files"""
        store, temp_dir = store_with_data

        # Create 6 backups manually (disable rotation during creation)
        import time as _time

        with patch.object(store, "_rotate_backups"):
            for i in range(6):
                ts = f"20260101_12000{i}"
                store._create_backup(ts)
                # Ensure different mtime for reliable sorting
                for f in temp_dir.glob(f"*backup_{ts}"):
                    f.touch()
                _time.sleep(0.05)

        # Before rotation: 6 of each
        assert len(list(temp_dir.glob("index*.backup_*"))) == 6
        assert len(list(temp_dir.glob("metadata*.backup_*"))) == 6

        # Rotate with max_backups=2
        mock_settings = Mock()
        mock_settings.faiss_max_backups = 2
        with patch("mimir.rag_core.implementations.faiss_store.settings", mock_settings):
            store._rotate_backups()

        assert len(list(temp_dir.glob("index*.backup_*"))) == 2
        assert len(list(temp_dir.glob("metadata*.backup_*"))) == 2

    def test_rotate_keeps_newest(self, store_with_data):
        """Rotation should keep the most recent backups"""
        store, temp_dir = store_with_data

        import time as _time

        timestamps = []
        with patch.object(store, "_rotate_backups"):
            for i in range(4):
                ts = f"2026010{i}_120000"
                timestamps.append(ts)
                store._create_backup(ts)
                for f in temp_dir.glob(f"*backup_{ts}"):
                    f.touch()
                _time.sleep(0.05)

        mock_settings = Mock()
        mock_settings.faiss_max_backups = 2
        with patch("mimir.rag_core.implementations.faiss_store.settings", mock_settings):
            store._rotate_backups()

        remaining = sorted(temp_dir.glob("index*.backup_*"), key=lambda f: f.stat().st_mtime)
        # The 2 newest should remain (timestamps[2] and timestamps[3])
        assert len(remaining) == 2
        assert timestamps[-1] in remaining[-1].name
        assert timestamps[-2] in remaining[-2].name

    def test_rotate_no_op_when_under_limit(self, store_with_data):
        """Rotation should not remove anything if under the limit"""
        store, temp_dir = store_with_data

        with patch.object(store, "_rotate_backups"):
            store._create_backup("20260101_120000")
            store._create_backup("20260102_120000")

        mock_settings = Mock()
        mock_settings.faiss_max_backups = 4
        with patch("mimir.rag_core.implementations.faiss_store.settings", mock_settings):
            store._rotate_backups()

        assert len(list(temp_dir.glob("index*.backup_*"))) == 2
        assert len(list(temp_dir.glob("metadata*.backup_*"))) == 2


class TestMetadataPersistence:
    """JSON metadata persistence"""

    def test_round_trip_json(self):
        """A new instance on the same paths loads the persisted metadata identically."""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "index.bin"
            metadata_path = Path(temp_dir) / "metadata.json"

            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )

            chunk = Chunk(
                text="Round trip chunk",
                embedding=np.random.rand(128).astype(np.float32),
                document_id="doc_roundtrip",
                chunk_index=0,
                total_chunks=1,
                source="roundtrip.txt",
                metadata={"k": "v"},
            )
            store.upsert([chunk])
            assert store.persist() is True

            assert store.metadata_path.exists()

            new_store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )

            assert new_store.document_to_chunks == store.document_to_chunks
            assert len(new_store.metadata) == len(store.metadata)
            assert new_store.metadata[0]["document_id"] == "doc_roundtrip"
