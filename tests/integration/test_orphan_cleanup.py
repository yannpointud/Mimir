"""
Tests d'intégration pour le système de nettoyage des chunks orphelins
"""

import pytest
import tempfile
import shutil
import os
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
from datetime import datetime

# Imports du système
from mimir.rag_core.implementations.faiss_store import FaissVectorStore
from mimir.rag_core.interfaces import Chunk
from mimir.rag_core.implementations.validation_utils import VectorStoreValidator
from mimir.database.repository import DocumentRepository
from mimir.database.models import Document  # noqa: F401


class TestOrphanCleanupIntegration:
    """Tests d'intégration pour le nettoyage des orphelins"""

    @pytest.fixture
    def temp_dir(self):
        """Répertoire temporaire pour les tests"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def vector_store(self, temp_dir):
        """Instance de FaissVectorStore pour les tests"""
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
        """Mock du repository de documents"""
        repo = Mock(spec=DocumentRepository)
        return repo

    def create_test_chunk(
        self, doc_id: str, chunk_index: int = 0, text: str = "Test content"
    ) -> Chunk:
        """Crée un chunk de test"""
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
        """Test de base du nettoyage des orphelins"""
        # Préparer les données de test
        # Document existant en DB (utiliser l'ID comme string car FAISS stocke les document_ids comme strings)
        existing_doc_id = "1"
        # Document orphelin (pas en DB)
        orphan_doc_id = "2"

        # Configurer le mock repository
        mock_doc_repo.get_all.return_value = [
            Mock(id=1, status="indexed")  # Seul le document 1 existe
        ]

        # Ajouter des chunks au vector store
        existing_chunks = [self.create_test_chunk(existing_doc_id, i) for i in range(3)]
        orphan_chunks = [self.create_test_chunk(orphan_doc_id, i) for i in range(2)]

        vector_store.upsert(existing_chunks + orphan_chunks)

        # Vérifier l'état initial
        initial_stats = vector_store.get_stats()
        assert initial_stats["active_vectors"] == 5
        assert len(vector_store.document_to_chunks) == 2

        # Exécuter le nettoyage avec les IDs de documents existants
        existing_doc_ids = {"1"}  # Seul le document 1 existe
        result = vector_store.clean_orphans(existing_document_ids=existing_doc_ids)

        # Vérifier les résultats
        assert result["orphaned_chunks_found"] == 2  # Les 2 chunks du doc_2
        assert result["cleaned_chunks"] == 2
        assert result["orphaned_documents"] == 1

        # Vérifier l'état final
        final_stats = vector_store.get_stats()
        assert final_stats["active_vectors"] == 3  # Seuls les chunks du doc_1
        # Si l'optimisation a été déclenchée, les chunks supprimés sont physiquement supprimés
        if result["optimization_triggered"]:
            assert (
                final_stats["deleted_vectors"] == 0
            )  # Plus de chunks supprimés après optimisation
        else:
            assert final_stats["deleted_vectors"] == 2  # Les chunks orphelins
        assert len(vector_store.document_to_chunks) == 1  # Seul doc_1
        assert orphan_doc_id not in vector_store.document_to_chunks

    def test_clean_orphans_no_orphans(self, vector_store):
        """Test quand il n'y a pas de chunks orphelins"""
        # Ajouter des chunks pour un document existant
        doc_id = "doc_1"
        chunks = [self.create_test_chunk(doc_id, i) for i in range(3)]
        vector_store.upsert(chunks)

        # Exécuter le nettoyage (tous les documents existent)
        existing_doc_ids = {doc_id}
        result = vector_store.clean_orphans(existing_document_ids=existing_doc_ids)

        # Vérifier qu'aucun nettoyage n'a été effectué
        assert result["orphaned_chunks_found"] == 0
        assert result["cleaned_chunks"] == 0
        assert result["optimization_triggered"] == False

    def test_clean_orphans_with_backup(self, vector_store, temp_dir):
        """Test du nettoyage avec création de backup"""
        # Ajouter des chunks
        chunks = [self.create_test_chunk("orphan_doc", i) for i in range(2)]
        vector_store.upsert(chunks)

        # Sauvegarder l'état initial
        vector_store.persist()

        # Exécuter le nettoyage avec backup
        result = vector_store.clean_orphans(
            existing_document_ids=set(),  # Aucun document existant
            create_backup=True,
        )

        # Vérifier qu'un backup a été créé
        backup_files = list(Path(temp_dir).glob("*.backup_*"))
        assert len(backup_files) >= 2  # Index et metadata backups

        # Vérifier le nettoyage
        assert result["cleaned_chunks"] == 2

    def test_clean_orphans_triggers_optimization(self, vector_store):
        """Test que le nettoyage déclenche l'optimisation si nécessaire"""
        # Créer beaucoup de chunks orphelins pour dépasser le seuil de 25%
        orphan_chunks = []
        for i in range(10):
            orphan_chunks.extend([self.create_test_chunk(f"orphan_{i}", j) for j in range(3)])

        # Ajouter quelques chunks valides
        valid_chunks = [self.create_test_chunk("valid_doc", i) for i in range(5)]

        vector_store.upsert(orphan_chunks + valid_chunks)

        # Total: 30 orphelins + 5 valides = 35 chunks
        # Après nettoyage: 30 supprimés / 35 total = 85% > 25%

        # Exécuter le nettoyage
        result = vector_store.clean_orphans(
            existing_document_ids={"valid_doc"}, create_backup=False
        )

        # Vérifier que l'optimisation a été déclenchée
        assert result["optimization_triggered"] == True
        assert result["cleaned_chunks"] == 30

    def test_validation_detects_orphans(self, vector_store, mock_doc_repo):
        """Test que la validation détecte les chunks orphelins"""
        # Préparer les données
        existing_doc = Mock()
        existing_doc.id = 1
        existing_doc.status = "indexed"
        existing_doc.filename = "test.txt"
        existing_doc.chunk_count = 3
        existing_doc.created_at = datetime.utcnow()
        existing_doc.indexed_at = datetime.utcnow()
        existing_doc.preserve = False
        existing_doc.path = "/test/path"

        mock_doc_repo.get_all.return_value = [existing_doc]

        # Ajouter des chunks: certains pour le doc existant, d'autres orphelins
        existing_chunks = [self.create_test_chunk("1", i) for i in range(3)]
        orphan_chunks = [self.create_test_chunk("999", i) for i in range(2)]

        vector_store.upsert(existing_chunks + orphan_chunks)

        # Créer le validateur et exécuter la validation
        validator = VectorStoreValidator(vector_store, mock_doc_repo)
        result = validator.validate_consistency(fix_issues=False)

        # Vérifier que les orphelins sont détectés
        issues = result["issues_found"]
        assert len(issues["orphaned_chunks"]) == 1
        assert issues["orphaned_chunks"][0]["document_id"] == "999"
        assert issues["orphaned_chunks"][0]["chunk_count"] == 2

        # Score de cohérence doit être dégradé
        assert result["consistency_score"] < 1.0

    def test_validation_fixes_orphans(self, vector_store, mock_doc_repo):
        """Test que la validation peut corriger automatiquement les orphelins"""
        # Préparer les données
        mock_doc_repo.get_all.return_value = []  # Aucun document en DB

        # Ajouter uniquement des chunks orphelins
        orphan_chunks = [self.create_test_chunk("orphan", i) for i in range(3)]
        vector_store.upsert(orphan_chunks)

        # Créer le validateur et exécuter la validation avec correction
        validator = VectorStoreValidator(vector_store, mock_doc_repo)
        result = validator.validate_consistency(fix_issues=True)

        # Vérifier que les orphelins ont été détectés et corrigés
        issues = result["issues_found"]
        assert len(issues["orphaned_chunks"]) == 1

        fixes = result["fixes_applied"]
        assert len(fixes) > 0
        assert any(fix["type"] == "orphaned_chunks_cleanup" for fix in fixes)

        # Vérifier l'état final
        final_stats = vector_store.get_stats()
        assert final_stats["active_vectors"] == 0  # Tous supprimés

    def test_rebuild_vector_store_with_cleanup(self, vector_store):
        """Test de la reconstruction avec nettoyage intégré"""
        # Ajouter des chunks valides et orphelins
        valid_chunks = [self.create_test_chunk("valid", i) for i in range(3)]
        orphan_chunks = [self.create_test_chunk("orphan", i) for i in range(2)]

        vector_store.upsert(valid_chunks + orphan_chunks)

        # Marquer certains chunks comme supprimés
        for meta in vector_store.metadata:
            if meta.get("document_id") == "orphan":
                meta["deleted"] = True

        result = vector_store.rebuild_vector_store(
            {"valid"}, force_rebuild=True, cleanup_orphans=True
        )

        # Vérifier les résultats
        assert result["rebuild_performed"] == True
        assert "cleanup_result" in result

        # Vérifier l'état final
        final_stats = vector_store.get_stats()
        assert final_stats["active_vectors"] == 3  # Seuls les chunks valides
        assert final_stats["deleted_vectors"] == 0  # Plus de chunks supprimés après rebuild

    def test_error_handling_during_cleanup(self, vector_store):
        """Test de la gestion d'erreurs pendant le nettoyage"""
        # Ajouter des chunks
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
        """Test de la sécurité en cas d'accès concurrent (thread-safety)"""
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
        """Test de performance avec un grand dataset"""
        # Créer un grand nombre de chunks
        chunks = []
        for doc_id in range(100):
            for chunk_idx in range(10):  # 10 chunks par document
                chunks.append(self.create_test_chunk(str(doc_id), chunk_idx))

        # Total: 1000 chunks
        vector_store.upsert(chunks)

        # Mesurer le temps de nettoyage
        start_time = datetime.utcnow()

        # Supposer que seuls 10 documents existent (90% d'orphelins)
        existing_docs = {str(i) for i in range(10)}
        result = vector_store.clean_orphans(
            existing_document_ids=existing_docs, create_backup=False
        )

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        # Vérifier les résultats
        assert result["cleaned_chunks"] == 900  # 90 docs * 10 chunks
        assert result["orphaned_documents"] == 90

        # Vérifier que le nettoyage est raisonnablement rapide (< 10 secondes)
        assert duration < 10.0, f"Cleanup too slow: {duration}s for 1000 chunks"

        print(f"Performance test: cleaned 900 orphan chunks in {duration:.2f}s")


class TestOrphanCleanupEdgeCases:
    """Tests des cas limites pour le nettoyage des orphelins"""

    @pytest.fixture
    def temp_dir(self):
        """Répertoire temporaire pour les tests"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def vector_store(self, temp_dir):
        """Instance de FaissVectorStore pour les tests"""
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
        """Test avec un vector store vide"""
        result = vector_store.clean_orphans(existing_document_ids=set())

        assert result["orphaned_chunks_found"] == 0
        assert result["cleaned_chunks"] == 0
        assert result["optimization_triggered"] == False

    def test_all_chunks_are_orphans(self, vector_store):
        """Test quand tous les chunks sont orphelins"""
        # Ajouter des chunks
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
        """Test avec des métadonnées malformées"""
        # Ajouter un chunk normal
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

        # Corrompre les métadonnées manuellement
        vector_store.metadata[0]["document_id"] = None  # Document ID manquant

        # Le nettoyage doit gérer gracieusement les métadonnées malformées
        result = vector_store.clean_orphans(existing_document_ids={"doc_1"})

        # Aucune erreur ne doit être levée
        assert "orphaned_chunks_found" in result

    def test_cleanup_with_preserve_flag(self, vector_store):
        """Test que les chunks avec preserve=True sont respectés"""
        # Ajouter des chunks avec et sans preserve
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

        # Tous les chunks orphelins doivent être supprimés, même avec preserve=True
        # (preserve protège contre la suppression manuelle, pas contre le nettoyage d'orphelins)
        assert result["cleaned_chunks"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
