"""
Integration tests of the orphan chunk cleanup
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

from mimir.database.models import Document  # noqa: F401
from mimir.database.repository import DocumentRepository

# Application imports
from mimir.rag_core.implementations.faiss_store import FaissVectorStore
from mimir.rag_core.implementations.validation_utils import VectorStoreValidator
from mimir.rag_core.interfaces import Chunk
from mimir.shared.clock import utc_now


class TestOrphanCleanupIntegration:
    """Orphan cleanup integration tests"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def vector_store(self, temp_dir):
        """FaissVectorStore instance"""
        index_path = os.path.join(temp_dir, "test_index.bin")
        metadata_path = os.path.join(temp_dir, "test_metadata.json")

        store = FaissVectorStore(
            dimension=384,
            index_path=index_path,
            metadata_path=metadata_path,
            similarity_threshold=0.5,
        )
        return store

    @pytest.fixture
    def mock_doc_repo(self):
        """Document repository mock"""
        repo = Mock(spec=DocumentRepository)
        return repo

    def create_test_chunk(
        self, doc_id: str, chunk_index: int = 0, text: str = "Test content"
    ) -> Chunk:
        """Create a test chunk"""
        return Chunk(
            text=text,
            embedding=np.random.rand(384).tolist(),
            document_id=doc_id,
            chunk_index=chunk_index,
            total_chunks=1,
            source=f"test_doc_{doc_id}.txt",
            metadata={"test": True},
            preserve=False,
        )

    def test_clean_orphans_basic_functionality(self, vector_store, mock_doc_repo):
        # Prepare the test data
        # Document present in the database (string id: FAISS stores document ids as strings)
        existing_doc_id = "1"
        # Document orphelin (pas en DB)
        orphan_doc_id = "2"

        # Configure the repository mock
        mock_doc_repo.get_all.return_value = [
            Mock(id=1, status="indexed")  # Only document 1 exists
        ]

        # Add chunks to the vector store
        existing_chunks = [self.create_test_chunk(existing_doc_id, i) for i in range(3)]
        orphan_chunks = [self.create_test_chunk(orphan_doc_id, i) for i in range(2)]

        vector_store.upsert(existing_chunks + orphan_chunks)

        # Check the initial state
        initial_stats = vector_store.get_stats()
        assert initial_stats["active_vectors"] == 5
        assert len(vector_store.document_to_chunks) == 2

        # Run the cleanup with the existing document ids
        existing_doc_ids = {"1"}  # Only document 1 exists
        result = vector_store.clean_orphans(existing_document_ids=existing_doc_ids)

        # Check the results
        assert result["orphaned_chunks_found"] == 2  # The 2 chunks of doc_2
        assert result["cleaned_chunks"] == 2
        assert result["orphaned_documents"] == 1

        # Check the final state
        final_stats = vector_store.get_stats()
        assert final_stats["active_vectors"] == 3  # Only the chunks of doc_1
        # If the optimization ran, the deleted chunks are physically removed
        if result["optimization_triggered"]:
            assert (
                final_stats["deleted_vectors"] == 0
            )  # No deleted chunks left after the optimization
        else:
            assert final_stats["deleted_vectors"] == 2  # The orphan chunks
        assert len(vector_store.document_to_chunks) == 1  # Seul doc_1
        assert orphan_doc_id not in vector_store.document_to_chunks

    def test_clean_orphans_no_orphans(self, vector_store):
        # Add chunks for an existing document
        doc_id = "doc_1"
        chunks = [self.create_test_chunk(doc_id, i) for i in range(3)]
        vector_store.upsert(chunks)

        # Run the cleanup (every document exists)
        existing_doc_ids = {doc_id}
        result = vector_store.clean_orphans(existing_document_ids=existing_doc_ids)

        # Check that no cleanup ran
        assert result["orphaned_chunks_found"] == 0
        assert result["cleaned_chunks"] == 0
        assert result["optimization_triggered"] == False

    def test_clean_orphans_with_backup(self, vector_store, temp_dir):
        # Add chunks
        chunks = [self.create_test_chunk("orphan_doc", i) for i in range(2)]
        vector_store.upsert(chunks)

        # Save the initial state
        vector_store.persist()

        # Run the cleanup with a backup
        result = vector_store.clean_orphans(
            existing_document_ids=set(),  # Aucun document existant
            create_backup=True,
        )

        # Check that a backup was created
        backup_files = list(Path(temp_dir).glob("*.backup_*"))
        assert len(backup_files) >= 2  # Index et metadata backups

        # Check the cleanup
        assert result["cleaned_chunks"] == 2

    def test_clean_orphans_triggers_optimization(self, vector_store):
        # Create many orphan chunks to exceed the 25% threshold
        orphan_chunks = []
        for i in range(10):
            orphan_chunks.extend([self.create_test_chunk(f"orphan_{i}", j) for j in range(3)])

        # Add a few valid chunks
        valid_chunks = [self.create_test_chunk("valid_doc", i) for i in range(5)]

        vector_store.upsert(orphan_chunks + valid_chunks)

        # Total: 30 orphelins + 5 valides = 35 chunks
        # After cleanup: 30 deleted / 35 total = 85% > 25%

        # Run the cleanup
        result = vector_store.clean_orphans(
            existing_document_ids={"valid_doc"}, create_backup=False
        )

        # Check that the optimization ran
        assert result["optimization_triggered"] == True
        assert result["cleaned_chunks"] == 30

    def test_validation_detects_orphans(self, vector_store, mock_doc_repo):
        # Prepare the data
        existing_doc = Mock()
        existing_doc.id = 1
        existing_doc.status = "indexed"
        existing_doc.filename = "test.txt"
        existing_doc.chunk_count = 3
        existing_doc.created_at = utc_now()
        existing_doc.indexed_at = utc_now()
        existing_doc.preserve = False
        existing_doc.path = "/test/path"

        mock_doc_repo.get_all.return_value = [existing_doc]

        # Add chunks: some for the existing document, others orphaned
        existing_chunks = [self.create_test_chunk("1", i) for i in range(3)]
        orphan_chunks = [self.create_test_chunk("999", i) for i in range(2)]

        vector_store.upsert(existing_chunks + orphan_chunks)

        # Create the validator and run the validation
        validator = VectorStoreValidator(vector_store, mock_doc_repo)
        result = validator.validate_consistency(fix_issues=False)

        # Check that the orphans are detected
        issues = result["issues_found"]
        assert len(issues["orphaned_chunks"]) == 1
        assert issues["orphaned_chunks"][0]["document_id"] == "999"
        assert issues["orphaned_chunks"][0]["chunk_count"] == 2

        # The consistency score must be degraded
        assert result["consistency_score"] < 1.0

    def test_validation_fixes_orphans(self, vector_store, mock_doc_repo):
        # Prepare the data
        mock_doc_repo.get_all.return_value = []  # Aucun document en DB

        # Add orphan chunks only
        orphan_chunks = [self.create_test_chunk("orphan", i) for i in range(3)]
        vector_store.upsert(orphan_chunks)

        # Create the validator and run the validation with fixes
        validator = VectorStoreValidator(vector_store, mock_doc_repo)
        result = validator.validate_consistency(fix_issues=True)

        # Check that the orphans were detected and fixed
        issues = result["issues_found"]
        assert len(issues["orphaned_chunks"]) == 1

        fixes = result["fixes_applied"]
        assert len(fixes) > 0
        assert any(fix["type"] == "orphaned_chunks_cleanup" for fix in fixes)

        # Check the final state
        final_stats = vector_store.get_stats()
        assert final_stats["active_vectors"] == 0  # All deleted

    def test_rebuild_vector_store_with_cleanup(self, vector_store):
        # Add valid and orphan chunks
        valid_chunks = [self.create_test_chunk("valid", i) for i in range(3)]
        orphan_chunks = [self.create_test_chunk("orphan", i) for i in range(2)]

        vector_store.upsert(valid_chunks + orphan_chunks)

        # Mark some chunks as deleted
        for meta in vector_store.metadata:
            if meta.get("document_id") == "orphan":
                meta["deleted"] = True

        result = vector_store.rebuild_vector_store(
            {"valid"}, force_rebuild=True, cleanup_orphans=True
        )

        # Check the results
        assert result["rebuild_performed"] == True
        assert "cleanup_result" in result

        # Check the final state
        final_stats = vector_store.get_stats()
        assert final_stats["active_vectors"] == 3  # Only the valid chunks
        assert final_stats["deleted_vectors"] == 0  # No deleted chunks left after the rebuild

    def test_error_handling_during_cleanup(self, vector_store):
        # Add chunks
        chunks = [self.create_test_chunk("test", i) for i in range(2)]
        vector_store.upsert(chunks)

        # No cleanup without its backup: the chunks stay untouched
        with (
            patch.object(vector_store, "_create_backup", side_effect=OSError("disk full")),
            pytest.raises(OSError),
        ):
            vector_store.clean_orphans(existing_document_ids=set(), create_backup=True)
        assert vector_store.get_stats()["active_vectors"] == 2

    def test_concurrent_access_safety(self, vector_store):
        from concurrent.futures import ThreadPoolExecutor

        chunks = [self.create_test_chunk("test", i) for i in range(10)]
        vector_store.upsert(chunks)

        def cleanup_worker():
            return vector_store.clean_orphans(existing_document_ids=set(), create_backup=False)

        # result() re-raises any exception a worker hit
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(cleanup_worker) for _ in range(3)]
            results = [future.result() for future in futures]

        # Only one thread finds the orphans; the others find none left
        cleanup_counts = [r["cleaned_chunks"] for r in results]
        assert sum(cleanup_counts) == 10, "Inconsistent cleanup across threads"

    def test_performance_with_large_dataset(self, vector_store):
        # Create a large number of chunks
        chunks = []
        for doc_id in range(100):
            for chunk_idx in range(10):  # 10 chunks par document
                chunks.append(self.create_test_chunk(str(doc_id), chunk_idx))

        # Total: 1000 chunks
        vector_store.upsert(chunks)

        # Measure the cleanup time
        start_time = utc_now()

        # Supposer que seuls 10 documents existent (90% d'orphelins)
        existing_docs = {str(i) for i in range(10)}
        result = vector_store.clean_orphans(
            existing_document_ids=existing_docs, create_backup=False
        )

        end_time = utc_now()
        duration = (end_time - start_time).total_seconds()

        # Check the results
        assert result["cleaned_chunks"] == 900  # 90 docs * 10 chunks
        assert result["orphaned_documents"] == 90

        # Check that the cleanup is reasonably fast (< 10 seconds)
        assert duration < 10.0, f"Cleanup too slow: {duration}s for 1000 chunks"

        print(f"Performance test: cleaned 900 orphan chunks in {duration:.2f}s")


class TestOrphanCleanupEdgeCases:
    """Edge cases of the orphan cleanup"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def vector_store(self, temp_dir):
        """FaissVectorStore instance"""
        index_path = os.path.join(temp_dir, "test_index.bin")
        metadata_path = os.path.join(temp_dir, "test_metadata.json")

        store = FaissVectorStore(
            dimension=384,
            index_path=index_path,
            metadata_path=metadata_path,
            similarity_threshold=0.5,
        )
        return store

    def test_empty_vector_store(self, vector_store):
        result = vector_store.clean_orphans(existing_document_ids=set())

        assert result["orphaned_chunks_found"] == 0
        assert result["cleaned_chunks"] == 0
        assert result["optimization_triggered"] == False

    def test_all_chunks_are_orphans(self, vector_store):
        # Add chunks
        chunks = []
        for i in range(5):
            chunk = Chunk(
                text=f"Test content {i}",
                embedding=np.random.rand(384).tolist(),
                document_id=f"doc_{i}",
                chunk_index=0,
                total_chunks=1,
                source=f"test_{i}.txt",
                metadata={},
                preserve=False,
            )
            chunks.append(chunk)

        vector_store.upsert(chunks)

        # Aucun document n'existe en DB
        result = vector_store.clean_orphans(existing_document_ids=set())

        assert result["orphaned_chunks_found"] == 5
        assert result["cleaned_chunks"] == 5
        assert result["orphaned_documents"] == 5

    def test_malformed_metadata(self, vector_store):
        # Add a regular chunk
        chunk = Chunk(
            text="Normal chunk",
            embedding=np.random.rand(384).tolist(),
            document_id="doc_1",
            chunk_index=0,
            total_chunks=1,
            source="test.txt",
            metadata={},
            preserve=False,
        )
        vector_store.upsert([chunk])

        # Corrupt the metadata by hand
        vector_store.metadata[0]["document_id"] = None  # Document ID manquant

        # The cleanup must handle malformed metadata
        result = vector_store.clean_orphans(existing_document_ids={"doc_1"})

        # No error must be raised
        assert "orphaned_chunks_found" in result

    def test_cleanup_with_preserve_flag(self, vector_store):
        # Add chunks with and without preserve
        regular_chunk = Chunk(
            text="Regular chunk",
            embedding=np.random.rand(384).tolist(),
            document_id="orphan_doc",
            chunk_index=0,
            total_chunks=2,
            source="test.txt",
            metadata={},
            preserve=False,
        )

        preserved_chunk = Chunk(
            text="Preserved chunk",
            embedding=np.random.rand(384).tolist(),
            document_id="orphan_doc",
            chunk_index=1,
            total_chunks=2,
            source="test.txt",
            metadata={},
            preserve=True,
        )

        vector_store.upsert([regular_chunk, preserved_chunk])

        # Aucun document n'existe
        result = vector_store.clean_orphans(existing_document_ids=set())

        # Every orphan chunk must be deleted, even with preserve=True
        # (preserve protects against manual deletion, not against orphan cleanup)
        assert result["cleaned_chunks"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
