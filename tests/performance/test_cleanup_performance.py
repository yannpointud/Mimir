"""
Tests de performance pour le système de nettoyage des chunks orphelins
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

# Imports du système
from src.rag_core.implementations.faiss_store import FaissVectorStore
from src.rag_core.interfaces import Chunk
from src.rag_core.implementations.validation_utils import VectorStoreValidator


class TestCleanupPerformance:
    """Tests de performance pour le nettoyage des orphelins"""
    
    @pytest.fixture
    def temp_dir(self):
        """Répertoire temporaire pour les tests"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def vector_store(self, temp_dir):
        """Instance de FaissVectorStore pour les tests"""
        index_path = os.path.join(temp_dir, "perf_index.bin")
        metadata_path = os.path.join(temp_dir, "perf_metadata.pkl")
        
        store = FaissVectorStore(
            dimension=384,
            index_path=index_path,
            metadata_path=metadata_path,
            similarity_threshold=0.5
        )
        return store
    
    def create_test_chunks(self, num_docs: int, chunks_per_doc: int) -> list:
        """Crée des chunks de test en masse"""
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
                    preserve=False
                )
                chunks.append(chunk)
        return chunks
    
    def benchmark_cleanup(self, vector_store, num_docs: int, chunks_per_doc: int, 
                         orphan_ratio: float = 0.8) -> dict:
        """
        Benchmark du nettoyage avec différentes tailles de datasets
        
        Args:
            vector_store: Instance du store
            num_docs: Nombre de documents
            chunks_per_doc: Chunks par document
            orphan_ratio: Ratio de documents orphelins (0.0 à 1.0)
        """
        # Créer et insérer les chunks
        chunks = self.create_test_chunks(num_docs, chunks_per_doc)
        total_chunks = len(chunks)
        
        print(f"\\nBenchmarking cleanup with {num_docs} docs, {chunks_per_doc} chunks/doc, {orphan_ratio:.1%} orphan ratio")
        
        # Mesurer le temps d'insertion
        start_time = time.time()
        vector_store.upsert(chunks)
        upsert_time = time.time() - start_time
        
        # Déterminer quels documents sont "existants" vs orphelins
        num_existing = int(num_docs * (1 - orphan_ratio))
        existing_doc_ids = {str(i) for i in range(num_existing)}
        
        # Mesurer le temps de nettoyage
        start_time = time.time()
        cleanup_result = vector_store.clean_orphans(
            existing_document_ids=existing_doc_ids,
            create_backup=False  # Pas de backup pour les benchmarks
        )
        cleanup_time = time.time() - start_time
        
        # Calculer les métriques
        orphan_chunks = (num_docs - num_existing) * chunks_per_doc
        chunks_per_second = total_chunks / upsert_time if upsert_time > 0 else 0
        cleanup_rate = cleanup_result['cleaned_chunks'] / cleanup_time if cleanup_time > 0 else 0
        
        return {
            'total_docs': num_docs,
            'chunks_per_doc': chunks_per_doc,
            'total_chunks': total_chunks,
            'orphan_ratio': orphan_ratio,
            'expected_orphan_chunks': orphan_chunks,
            'upsert_time': upsert_time,
            'cleanup_time': cleanup_time,
            'chunks_per_second_upsert': chunks_per_second,
            'chunks_per_second_cleanup': cleanup_rate,
            'cleanup_result': cleanup_result,
            'memory_usage_mb': vector_store.get_stats().get('memory_usage_mb', 0)
        }
    
    @pytest.mark.performance
    def test_small_dataset_performance(self, vector_store):
        """Test de performance sur un petit dataset (100 docs)"""
        result = self.benchmark_cleanup(vector_store, num_docs=100, chunks_per_doc=5)
        
        # Assertions de performance pour petit dataset
        assert result['cleanup_time'] < 2.0, f"Cleanup too slow: {result['cleanup_time']:.2f}s"
        assert result['chunks_per_second_cleanup'] > 50, f"Cleanup rate too low: {result['chunks_per_second_cleanup']:.1f} chunks/s"
        
        print(f"Small dataset results: {result['cleanup_time']:.2f}s, {result['chunks_per_second_cleanup']:.1f} chunks/s")
    
    @pytest.mark.performance
    def test_medium_dataset_performance(self, vector_store):
        """Test de performance sur un dataset moyen (1000 docs)"""
        result = self.benchmark_cleanup(vector_store, num_docs=1000, chunks_per_doc=10)
        
        # Assertions de performance pour dataset moyen
        assert result['cleanup_time'] < 10.0, f"Cleanup too slow: {result['cleanup_time']:.2f}s"
        assert result['chunks_per_second_cleanup'] > 100, f"Cleanup rate too low: {result['chunks_per_second_cleanup']:.1f} chunks/s"
        
        print(f"Medium dataset results: {result['cleanup_time']:.2f}s, {result['chunks_per_second_cleanup']:.1f} chunks/s")
    
    @pytest.mark.performance
    @pytest.mark.slow
    def test_large_dataset_performance(self, vector_store):
        """Test de performance sur un grand dataset (5000 docs)"""
        result = self.benchmark_cleanup(vector_store, num_docs=5000, chunks_per_doc=15)
        
        # Assertions de performance pour grand dataset
        assert result['cleanup_time'] < 30.0, f"Cleanup too slow: {result['cleanup_time']:.2f}s"
        assert result['chunks_per_second_cleanup'] > 200, f"Cleanup rate too low: {result['chunks_per_second_cleanup']:.1f} chunks/s"
        
        print(f"Large dataset results: {result['cleanup_time']:.2f}s, {result['chunks_per_second_cleanup']:.1f} chunks/s")
    
    @pytest.mark.performance
    def test_varying_orphan_ratios(self, vector_store):
        """Test de performance avec différents ratios d'orphelins"""
        num_docs = 500
        chunks_per_doc = 8
        orphan_ratios = [0.1, 0.3, 0.5, 0.7, 0.9]
        
        results = []
        for ratio in orphan_ratios:
            # Réinitialiser le store pour chaque test
            vector_store.metadata.clear()
            vector_store.document_to_chunks.clear()
            vector_store._create_new_index()
            
            result = self.benchmark_cleanup(vector_store, num_docs, chunks_per_doc, ratio)
            results.append(result)
            
            print(f"Orphan ratio {ratio:.1%}: {result['cleanup_time']:.2f}s, {result['chunks_per_second_cleanup']:.1f} chunks/s")
        
        # Analyser les tendances
        cleanup_times = [r['cleanup_time'] for r in results]
        assert max(cleanup_times) < 15.0, "Cleanup time too high for any orphan ratio"
        
        # Le temps de nettoyage devrait augmenter avec le ratio d'orphelins
        # mais pas de façon linéaire (optimisations internes)
        print(f"Cleanup time range: {min(cleanup_times):.2f}s - {max(cleanup_times):.2f}s")
    
    @pytest.mark.performance
    def test_memory_usage_scaling(self, vector_store):
        """Test de l'utilisation mémoire avec différentes tailles"""
        dataset_sizes = [
            (100, 5),    # 500 chunks
            (500, 10),   # 5000 chunks
            (1000, 15),  # 15000 chunks
        ]
        
        memory_usage = []
        
        for num_docs, chunks_per_doc in dataset_sizes:
            # Réinitialiser
            vector_store.metadata.clear()
            vector_store.document_to_chunks.clear()
            vector_store._create_new_index()
            
            # Benchmark
            result = self.benchmark_cleanup(vector_store, num_docs, chunks_per_doc)
            memory_usage.append(result['memory_usage_mb'])
            
            print(f"Dataset {num_docs}x{chunks_per_doc}: {result['memory_usage_mb']:.1f} MB")
        
        # Vérifier que l'utilisation mémoire reste raisonnable
        assert all(mem < 500 for mem in memory_usage), "Memory usage too high"
        
        # L'utilisation mémoire devrait augmenter avec la taille du dataset
        assert memory_usage[-1] > memory_usage[0], "Memory usage should scale with dataset size"
    
    @pytest.mark.performance
    def test_validation_performance(self, vector_store):
        """Test de performance de la validation"""
        # Créer un dataset de taille moyenne
        chunks = self.create_test_chunks(num_docs=1000, chunks_per_doc=8)
        vector_store.upsert(chunks)
        
        # Mock du repository
        mock_repo = Mock()
        mock_docs = []
        for i in range(500):  # 50% des documents existent
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
        
        # Mesurer la performance de validation
        validator = VectorStoreValidator(vector_store, mock_repo)
        
        start_time = time.time()
        result = validator.validate_consistency(fix_issues=False)
        validation_time = time.time() - start_time
        
        print(f"Validation of 8000 chunks in {validation_time:.2f}s")
        print(f"Issues found: {result['issues_found']['total_issues']}")
        print(f"Consistency score: {result['consistency_score']:.2%}")
        
        # Assertions de performance
        assert validation_time < 5.0, f"Validation too slow: {validation_time:.2f}s"
        assert result['issues_found']['total_issues'] > 0, "Should detect orphans"
    
    @pytest.mark.performance
    def test_backup_creation_performance(self, vector_store, temp_dir):
        """Test de performance de création de backup"""
        # Créer un dataset
        chunks = self.create_test_chunks(num_docs=1000, chunks_per_doc=10)
        vector_store.upsert(chunks)
        vector_store.persist()
        
        # Mesurer le temps de création de backup
        start_time = time.time()
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        vector_store._create_backup(timestamp)
        backup_time = time.time() - start_time
        
        print(f"Backup creation for 10000 chunks in {backup_time:.2f}s")
        
        # Vérifier que les fichiers de backup existent
        backup_files = list(Path(temp_dir).glob(f"*.backup_{timestamp}"))
        assert len(backup_files) == 2, "Should create index and metadata backups"
        
        # Assertions de performance
        assert backup_time < 3.0, f"Backup too slow: {backup_time:.2f}s"
    
    @pytest.mark.performance
    def test_rebuild_optimization_performance(self, vector_store):
        """Test de performance de l'optimisation/reconstruction"""
        # Créer un dataset avec beaucoup de chunks supprimés
        chunks = self.create_test_chunks(num_docs=2000, chunks_per_doc=5)
        vector_store.upsert(chunks)
        
        # Marquer 60% des chunks comme supprimés
        deleted_count = 0
        target_deleted = int(len(vector_store.metadata) * 0.6)
        
        for meta in vector_store.metadata:
            if deleted_count < target_deleted:
                meta['deleted'] = True
                meta['deleted_at'] = datetime.utcnow().isoformat()
                deleted_count += 1
        
        # Mesurer la performance de l'optimisation
        start_time = time.time()
        vector_store.optimize()
        optimization_time = time.time() - start_time
        
        print(f"Optimization removed {deleted_count} chunks in {optimization_time:.2f}s")
        
        # Vérifier l'état final
        final_stats = vector_store.get_stats()
        assert final_stats['deleted_vectors'] == 0, "All deleted chunks should be removed"
        assert final_stats['active_vectors'] == len(chunks) - deleted_count
        
        # Assertions de performance
        assert optimization_time < 20.0, f"Optimization too slow: {optimization_time:.2f}s"
        
        optimization_rate = deleted_count / optimization_time if optimization_time > 0 else 0
        print(f"Optimization rate: {optimization_rate:.1f} chunks/s")
        assert optimization_rate > 100, f"Optimization rate too low: {optimization_rate:.1f} chunks/s"


class TestCleanupStressTest:
    """Tests de stress pour le système de nettoyage"""
    
    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def vector_store(self, temp_dir):
        index_path = os.path.join(temp_dir, "stress_index.bin")
        metadata_path = os.path.join(temp_dir, "stress_metadata.pkl")
        
        store = FaissVectorStore(
            dimension=384,
            index_path=index_path,
            metadata_path=metadata_path,
            similarity_threshold=0.5
        )
        return store
    
    @pytest.mark.stress
    @pytest.mark.slow
    def test_repeated_cleanup_cycles(self, vector_store):
        """Test de cycles répétés de nettoyage"""
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
                        preserve=False
                    )
                    chunks.append(chunk)
            
            vector_store.upsert(chunks)
            
            # Nettoyer les documents des cycles précédents (les rendre orphelins)
            if cycle > 0:
                # Garder seulement les documents du cycle actuel
                existing_docs = {str(i) for i in range(cycle * docs_per_cycle, (cycle + 1) * docs_per_cycle)}
                
                start_time = time.time()
                result = vector_store.clean_orphans(
                    existing_document_ids=existing_docs,
                    create_backup=False
                )
                cleanup_time = time.time() - start_time
                cleanup_times.append(cleanup_time)
                
                print(f"Cycle {cycle}: cleaned {result['cleaned_chunks']} chunks in {cleanup_time:.2f}s")
        
        # Analyser les résultats
        if cleanup_times:
            avg_cleanup_time = statistics.mean(cleanup_times)
            max_cleanup_time = max(cleanup_times)
            
            print(f"\\nStress test results:")
            print(f"Average cleanup time: {avg_cleanup_time:.2f}s")
            print(f"Max cleanup time: {max_cleanup_time:.2f}s")
            print(f"Total cycles: {num_cycles}")
            
            # Assertions de stress
            assert max_cleanup_time < 10.0, f"Cleanup time degraded: {max_cleanup_time:.2f}s"
            assert avg_cleanup_time < 5.0, f"Average cleanup time too high: {avg_cleanup_time:.2f}s"


if __name__ == "__main__":
    # Lancer les tests de performance
    pytest.main([
        __file__,
        "-v",
        "-m", "performance",
        "--tb=short"
    ])