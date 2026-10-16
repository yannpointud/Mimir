"""
Performance tests for the orphan chunk cleanup system
"""

import pytest
import tempfile
import shutil
import os
import time
import statistics
from pathlib import Path
import numpy as np
from datetime import datetime
from unittest.mock import Mock

# System imports
from mimir.rag_core.implementations.faiss_store import FaissVectorStore
from mimir.rag_core.interfaces import Chunk
from mimir.rag_core.implementations.validation_utils import VectorStoreValidator


class TestCleanupPerformance:
    """Performance tests for orphan cleanup"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory for tests"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def vector_store(self, temp_dir):
        """FaissVectorStore instance for tests"""
        index_path = os.path.join(temp_dir, "perf_index.bin")
        metadata_path = os.path.join(temp_dir, "perf_metadata.json")

        store = FaissVectorStore(
            dimension=384,
            index_path=index_path,
            metadata_path=metadata_path,
            similarity_threshold=0.5,
        )
        return store

    def create_test_chunks(self, num_docs: int, chunks_per_doc: int) -> list:
        """Create test chunks in bulk"""
        chunks = []
        for doc_id in range(num_docs):
            for chunk_idx in range(chunks_per_doc):
                chunk = Chunk(
                    text=f"Test content for doc {doc_id} chunk {chunk_idx}",
                    embedding=np.random.rand(384).tolist(),
                    document_id=str(doc_id),
                    chunk_index=chunk_idx,
                    total_chunks=chunks_per_doc,
                    source=f"doc_{doc_id}.txt",
                    metadata={"doc_type": "test", "size": "medium"},
                    preserve=False,
                )
                chunks.append(chunk)
        return chunks

    def benchmark_cleanup(
        self, vector_store, num_docs: int, chunks_per_doc: int, orphan_ratio: float = 0.8
    ) -> dict:
        """
        Benchmark cleanup with different dataset sizes

        Args:
            vector_store: Store instance
            num_docs: Number of documents
            chunks_per_doc: Chunks per document
            orphan_ratio: Orphan document ratio (0.0 to 1.0)
        """
        # Create and insert chunks
        chunks = self.create_test_chunks(num_docs, chunks_per_doc)
        total_chunks = len(chunks)

        print(
            f"\\nBenchmarking cleanup with {num_docs} docs, {chunks_per_doc} chunks/doc, {orphan_ratio:.1%} orphan ratio"
        )

        # Measure insertion time
        start_time = time.time()
        vector_store.upsert(chunks)
        upsert_time = time.time() - start_time

        # Determine which documents are "existing" vs orphans
        num_existing = int(num_docs * (1 - orphan_ratio))
        existing_doc_ids = {str(i) for i in range(num_existing)}

        # Measure cleanup time
        start_time = time.time()
        cleanup_result = vector_store.clean_orphans(
            existing_document_ids=existing_doc_ids,
            create_backup=False,  # No backup for benchmarks
        )
        cleanup_time = time.time() - start_time

        # Calculate metrics
        orphan_chunks = (num_docs - num_existing) * chunks_per_doc
        chunks_per_second = total_chunks / upsert_time if upsert_time > 0 else 0
        cleanup_rate = cleanup_result["cleaned_chunks"] / cleanup_time if cleanup_time > 0 else 0

        return {
            "total_docs": num_docs,
            "chunks_per_doc": chunks_per_doc,
            "total_chunks": total_chunks,
            "orphan_ratio": orphan_ratio,
            "expected_orphan_chunks": orphan_chunks,
            "upsert_time": upsert_time,
            "cleanup_time": cleanup_time,
            "chunks_per_second_upsert": chunks_per_second,
            "chunks_per_second_cleanup": cleanup_rate,
            "cleanup_result": cleanup_result,
            "memory_usage_mb": vector_store.get_stats().get("memory_usage_mb", 0),
        }

    @pytest.mark.performance
    def test_small_dataset_performance(self, vector_store):
        """Performance test on a small dataset (100 docs)"""
        result = self.benchmark_cleanup(vector_store, num_docs=100, chunks_per_doc=5)

        # Performance assertions for small dataset
        assert result["cleanup_time"] < 2.0, f"Cleanup too slow: {result['cleanup_time']:.2f}s"
        assert result["chunks_per_second_cleanup"] > 50, (
            f"Cleanup rate too low: {result['chunks_per_second_cleanup']:.1f} chunks/s"
        )

        print(
            f"Small dataset results: {result['cleanup_time']:.2f}s, {result['chunks_per_second_cleanup']:.1f} chunks/s"
        )

    @pytest.mark.performance
    def test_medium_dataset_performance(self, vector_store):
        """Performance test on a medium dataset (1000 docs)"""
        result = self.benchmark_cleanup(vector_store, num_docs=1000, chunks_per_doc=10)

        # Performance assertions for medium dataset
        assert result["cleanup_time"] < 10.0, f"Cleanup too slow: {result['cleanup_time']:.2f}s"
        assert result["chunks_per_second_cleanup"] > 100, (
            f"Cleanup rate too low: {result['chunks_per_second_cleanup']:.1f} chunks/s"
        )

        print(
            f"Medium dataset results: {result['cleanup_time']:.2f}s, {result['chunks_per_second_cleanup']:.1f} chunks/s"
        )

    @pytest.mark.performance
    @pytest.mark.slow
    def test_large_dataset_performance(self, vector_store):
        """Performance test on a large dataset (5000 docs)"""
        result = self.benchmark_cleanup(vector_store, num_docs=5000, chunks_per_doc=15)

        # Performance assertions for large dataset
        assert result["cleanup_time"] < 120.0, f"Cleanup too slow: {result['cleanup_time']:.2f}s"
        assert result["chunks_per_second_cleanup"] > 50, (
            f"Cleanup rate too low: {result['chunks_per_second_cleanup']:.1f} chunks/s"
        )

        print(
            f"Large dataset results: {result['cleanup_time']:.2f}s, {result['chunks_per_second_cleanup']:.1f} chunks/s"
        )

    @pytest.mark.performance
    def test_varying_orphan_ratios(self, vector_store):
        """Performance test with varying orphan ratios"""
        num_docs = 500
        chunks_per_doc = 8
        orphan_ratios = [0.1, 0.3, 0.5, 0.7, 0.9]

        results = []
        for ratio in orphan_ratios:
            # Reset the store for each test
            vector_store.metadata.clear()
            vector_store.document_to_chunks.clear()
            vector_store._create_new_index()

            result = self.benchmark_cleanup(vector_store, num_docs, chunks_per_doc, ratio)
            results.append(result)

            print(
                f"Orphan ratio {ratio:.1%}: {result['cleanup_time']:.2f}s, {result['chunks_per_second_cleanup']:.1f} chunks/s"
            )

        # Analyze trends
        cleanup_times = [r["cleanup_time"] for r in results]
        assert max(cleanup_times) < 15.0, "Cleanup time too high for any orphan ratio"

        # Cleanup time should increase with orphan ratio
        # but not linearly (internal optimizations)
        print(f"Cleanup time range: {min(cleanup_times):.2f}s - {max(cleanup_times):.2f}s")

    @pytest.mark.performance
    def test_memory_usage_scaling(self, vector_store):
        """Test memory usage with different sizes"""
        dataset_sizes = [
            (100, 5),  # 500 chunks
            (500, 10),  # 5000 chunks
            (1000, 15),  # 15000 chunks
        ]

        memory_usage = []

        for num_docs, chunks_per_doc in dataset_sizes:
            # Reset
            vector_store.metadata.clear()
            vector_store.document_to_chunks.clear()
            vector_store._create_new_index()

            # Benchmark
            result = self.benchmark_cleanup(vector_store, num_docs, chunks_per_doc)
            memory_usage.append(result["memory_usage_mb"])

            print(f"Dataset {num_docs}x{chunks_per_doc}: {result['memory_usage_mb']:.1f} MB")

        # Verify memory usage stays reasonable
        assert all(mem < 500 for mem in memory_usage), "Memory usage too high"

        # Memory usage should increase with dataset size
        assert memory_usage[-1] > memory_usage[0], "Memory usage should scale with dataset size"

    @pytest.mark.performance
    def test_validation_performance(self, vector_store):
        """Performance test for validation"""
        # Create a medium-sized dataset
        chunks = self.create_test_chunks(num_docs=1000, chunks_per_doc=8)
        vector_store.upsert(chunks)

        # Mock the repository
        mock_repo = Mock()
        mock_docs = []
        for i in range(500):  # 50% of documents exist
            doc = Mock()
            doc.id = i
            doc.status = "indexed"
            doc.filename = f"doc_{i}.txt"
            doc.chunk_count = 8
            doc.created_at = datetime.utcnow()
            doc.indexed_at = datetime.utcnow()
            doc.preserve = False
            doc.path = f"/test/doc_{i}.txt"
            mock_docs.append(doc)

        mock_repo.get_all.return_value = mock_docs

        # Measure validation performance
        validator = VectorStoreValidator(vector_store, mock_repo)

        start_time = time.time()
        result = validator.validate_consistency(fix_issues=False)
        validation_time = time.time() - start_time

        print(f"Validation of 8000 chunks in {validation_time:.2f}s")
        print(f"Issues found: {result['issues_found']['total_issues']}")
        print(f"Consistency score: {result['consistency_score']:.2%}")

        # Performance assertions
        assert validation_time < 30.0, f"Validation too slow: {validation_time:.2f}s"
        assert result["issues_found"]["total_issues"] > 0, "Should detect orphans"

    @pytest.mark.performance
    def test_backup_creation_performance(self, vector_store, temp_dir):
        """Performance test for backup creation"""
        # Create a dataset
        chunks = self.create_test_chunks(num_docs=1000, chunks_per_doc=10)
        vector_store.upsert(chunks)
        vector_store.persist()

        # Measure backup creation time
        start_time = time.time()
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        vector_store._create_backup(timestamp)
        backup_time = time.time() - start_time

        print(f"Backup creation for 10000 chunks in {backup_time:.2f}s")

        # Verify backup files exist
        backup_files = list(Path(temp_dir).glob(f"*.backup_{timestamp}"))
        assert len(backup_files) == 2, "Should create index and metadata backups"

        # Performance assertions
        assert backup_time < 3.0, f"Backup too slow: {backup_time:.2f}s"

    @pytest.mark.performance
    def test_rebuild_optimization_performance(self, vector_store):
        """Performance test for optimization/rebuild"""
        # Create a dataset avec beaucoup de chunks supprimés
        chunks = self.create_test_chunks(num_docs=2000, chunks_per_doc=5)
        vector_store.upsert(chunks)

        # Mark 60% of chunks as deleted
        deleted_count = 0
        target_deleted = int(len(vector_store.metadata) * 0.6)

        for meta in vector_store.metadata:
            if deleted_count < target_deleted:
                meta["deleted"] = True
                meta["deleted_at"] = datetime.utcnow().isoformat()
                deleted_count += 1

        # Measure optimization performance
        start_time = time.time()
        vector_store.optimize()
        optimization_time = time.time() - start_time

        print(f"Optimization removed {deleted_count} chunks in {optimization_time:.2f}s")

        # Verify final state
        final_stats = vector_store.get_stats()
        assert final_stats["deleted_vectors"] == 0, "All deleted chunks should be removed"
        assert final_stats["active_vectors"] == len(chunks) - deleted_count

        # Performance assertions
        assert optimization_time < 60.0, f"Optimization too slow: {optimization_time:.2f}s"

        optimization_rate = deleted_count / optimization_time if optimization_time > 0 else 0
        print(f"Optimization rate: {optimization_rate:.1f} chunks/s")
        assert optimization_rate > 20, (
            f"Optimization rate too low: {optimization_rate:.1f} chunks/s"
        )


class TestCleanupStressTest:
    """Stress tests for the cleanup system"""

    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def vector_store(self, temp_dir):
        index_path = os.path.join(temp_dir, "stress_index.bin")
        metadata_path = os.path.join(temp_dir, "stress_metadata.json")

        store = FaissVectorStore(
            dimension=384,
            index_path=index_path,
            metadata_path=metadata_path,
            similarity_threshold=0.5,
        )
        return store

    @pytest.mark.stress
    @pytest.mark.slow
    def test_repeated_cleanup_cycles(self, vector_store):
        """Test repeated cleanup cycles"""
        num_cycles = 10
        docs_per_cycle = 200
        chunks_per_doc = 5

        cleanup_times = []

        for cycle in range(num_cycles):
            print(f"\\nStress test cycle {cycle + 1}/{num_cycles}")

            # Ajouter de nouveaux documents
            chunks = []
            for doc_id in range(cycle * docs_per_cycle, (cycle + 1) * docs_per_cycle):
                for chunk_idx in range(chunks_per_doc):
                    chunk = Chunk(
                        text=f"Stress test content cycle {cycle} doc {doc_id} chunk {chunk_idx}",
                        embedding=np.random.rand(384).tolist(),
                        document_id=str(doc_id),
                        chunk_index=chunk_idx,
                        total_chunks=chunks_per_doc,
                        source=f"stress_doc_{doc_id}.txt",
                        metadata={"cycle": cycle},
                        preserve=False,
                    )
                    chunks.append(chunk)

            vector_store.upsert(chunks)

            # Nettoyer les documents des cycles précédents (les rendre orphelins)
            if cycle > 0:
                # Garder seulement les documents du cycle actuel
                existing_docs = {
                    str(i) for i in range(cycle * docs_per_cycle, (cycle + 1) * docs_per_cycle)
                }

                start_time = time.time()
                result = vector_store.clean_orphans(
                    existing_document_ids=existing_docs, create_backup=False
                )
                cleanup_time = time.time() - start_time
                cleanup_times.append(cleanup_time)

                print(
                    f"Cycle {cycle}: cleaned {result['cleaned_chunks']} chunks in {cleanup_time:.2f}s"
                )

        # Analyser les résultats
        if cleanup_times:
            avg_cleanup_time = statistics.mean(cleanup_times)
            max_cleanup_time = max(cleanup_times)

            print("\\nStress test results:")
            print(f"Average cleanup time: {avg_cleanup_time:.2f}s")
            print(f"Max cleanup time: {max_cleanup_time:.2f}s")
            print(f"Total cycles: {num_cycles}")

            # Assertions de stress
            assert max_cleanup_time < 10.0, f"Cleanup time degraded: {max_cleanup_time:.2f}s"
            assert avg_cleanup_time < 5.0, f"Average cleanup time too high: {avg_cleanup_time:.2f}s"


if __name__ == "__main__":
    # Lancer les tests de performance
    pytest.main([__file__, "-v", "-m", "performance", "--tb=short"])
