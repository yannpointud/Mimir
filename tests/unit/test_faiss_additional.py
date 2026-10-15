"""
Tests unitaires supplémentaires pour FaissVectorStore
Focus sur l'amélioration de la couverture
"""

import pytest
import numpy as np
import faiss
import pickle
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from backend.src.rag_core.implementations.faiss_store import FaissVectorStore
from backend.src.rag_core.interfaces import Chunk, VectorStoreOperationError


class TestFaissVectorStoreAdditional:
    """Tests supplémentaires pour améliorer la couverture"""

    @pytest.fixture
    def temp_store(self):
        """Fixture pour créer un store temporaire"""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "test.index"
            metadata_path = Path(temp_dir) / "test.metadata"
            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )
            yield store

    def test_faiss_store_add_chunks_basic(self, temp_store):
        """Test d'ajout de base de chunks"""
        # Créer des chunks de test avec la bonne signature
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
        # Ajouter quelques vecteurs
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

        # Effectuer une recherche
        query_vector = np.random.random(128).astype(np.float32)
        results = temp_store.query(query_vector, top_k=3)

        assert isinstance(results, list)
        assert len(results) <= 3

    def test_faiss_store_get_stats(self, temp_store):
        """Test des statistiques du store"""
        # Au début, doit être 0
        stats = temp_store.get_stats()
        assert stats["total_vectors"] == 0

        # Ajouter des chunks
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

        # Maintenant doit être 1
        stats = temp_store.get_stats()
        assert stats["total_vectors"] == 1

    def test_faiss_store_delete_documents(self, temp_store):
        """Test de suppression de documents"""
        # Ajouter plusieurs chunks pour éviter l'optimisation automatique (>25% supprimés)
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

        # Supprimer un document (ne déclenche pas l'optimisation car <25%)
        temp_store.delete("doc_1")
        stats_after = temp_store.get_stats()

        # Vérifier que le document a été marqué comme supprimé
        # L'optimisation ne se déclenche pas car 1/5 = 20% < 25%
        assert stats_after["deleted_vectors"] == 1
        assert stats_after["active_vectors"] == 4
        assert stats_after["total_vectors"] == initial_total  # Index pas reconstruit

    def test_faiss_store_empty_search(self, temp_store):
        """Test de recherche sur un store vide"""
        query_vector = np.random.random(128).astype(np.float32)
        results = temp_store.query(query_vector, top_k=5)

        assert isinstance(results, list)
        assert len(results) == 0

    def test_faiss_store_large_batch(self, temp_store):
        """Test avec un lot important de données"""
        # Créer un lot de 100 chunks
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
        # Utiliser un des vecteurs ajoutés comme query pour garantir des résultats
        query_vector = chunks[0].embedding
        results = temp_store.query(query_vector, top_k=10)
        assert len(results) > 0  # Au moins quelques résultats


class TestFaissStoreFunctionality:
    """Tests de fonctionnalité avancée"""

    @pytest.fixture
    def populated_store(self):
        """Store pré-rempli pour les tests"""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "populated.index"
            metadata_path = Path(temp_dir) / "populated.metadata"

            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )

            # Ajouter des données de test
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
        """Test de cohérence des résultats de recherche"""
        query_vector = np.random.random(128).astype(np.float32)

        # Effectuer la même recherche plusieurs fois
        results1 = populated_store.query(query_vector, top_k=5)
        results2 = populated_store.query(query_vector, top_k=5)

        # Les résultats doivent être identiques
        assert len(results1) == len(results2)
        for i in range(len(results1)):
            assert results1[i].text == results2[i].text

    def test_faiss_store_vector_validation(self):
        """Test de validation des vecteurs"""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "validation.index"
            metadata_path = Path(temp_dir) / "validation.metadata"

            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )

            # Test avec dimension incorrecte
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
        """Test avec différentes valeurs de top_k"""
        query_vector = np.random.random(128).astype(np.float32)

        # Utiliser un vecteur existant pour garantir des résultats
        # Récupérer un vecteur de test via les stats et les métadonnées
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
            # Avec un vecteur identique, on devrait avoir au moins 1 résultat
            assert len(results) >= 1


class TestBackupRotation:
    """Tests for FAISS backup creation and rotation logic"""

    @pytest.fixture
    def store_with_data(self):
        """Store with saved index/metadata files on disk"""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "index.bin"
            metadata_path = Path(temp_dir) / "metadata.pkl"
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
        with patch("backend.src.config.settings", mock_settings):
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
        with patch("backend.src.config.settings", mock_settings):
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
        with patch("backend.src.config.settings", mock_settings):
            store._rotate_backups()

        assert len(list(temp_dir.glob("index*.backup_*"))) == 2
        assert len(list(temp_dir.glob("metadata*.backup_*"))) == 2

    def test_rotate_failure_does_not_raise(self, store_with_data):
        """Rotation failure should be logged but not propagate"""
        store, _ = store_with_data

        with patch("backend.src.config.settings", None):
            # settings=None triggers AttributeError, should not propagate
            store._rotate_backups()


class TestMetadataMigration:
    """Tests for transparent pickle -> JSON metadata migration on load()"""

    def test_migration_pickle_to_json(self):
        """A legacy metadata.pkl (no metadata.json yet) loads without data
        loss, and the .pkl file is NOT deleted after the migration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "index.bin"
            legacy_pkl_path = Path(temp_dir) / "metadata.pkl"

            # Write a minimal real FAISS index directly (no store yet)
            index = faiss.IndexFlatL2(128)
            vector = np.random.rand(128).astype(np.float32).reshape(1, -1)
            index.add(vector)
            faiss.write_index(index, str(index_path))

            # Hand-write a legacy pickle metadata file, matching the old
            # persist() format (metadata/document_to_chunks/stats/version/saved_at)
            legacy_payload = {
                "metadata": [
                    {
                        "document_id": "doc_legacy",
                        "text": "Legacy chunk text",
                        "source": "legacy.txt",
                        "chunk_index": 0,
                        "total_chunks": 1,
                        "preserve": False,
                        "indexed_at": "2026-07-01T00:00:00",
                        "metadata": {},
                        "chunk_id": 0,
                    }
                ],
                "document_to_chunks": {"doc_legacy": [0]},
                "stats": {
                    "total_vectors": 1,
                    "total_documents": 1,
                    "last_updated": "2026-07-01T00:00:00",
                },
                "version": "1.0",
                "saved_at": "2026-07-01T00:00:00",
            }
            with open(legacy_pkl_path, "wb") as f:
                pickle.dump(legacy_payload, f, protocol=pickle.HIGHEST_PROTOCOL)

            # Instantiate the store pointing at these legacy files (passing
            # the .pkl path as metadata_path, as an old config.json would)
            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(legacy_pkl_path)
            )

            # Data loaded without loss from the legacy pickle
            assert len(store.metadata) == 1
            assert store.metadata[0]["document_id"] == "doc_legacy"
            assert store.document_to_chunks == {"doc_legacy": [0]}

            # The .pkl file was NOT deleted/rewritten by the migration
            assert legacy_pkl_path.exists()
            # No metadata.json was written by load() itself (only the next
            # persist() call would write it)
            assert not store.metadata_path.exists()

    def test_pickle_retired_after_first_persist(self):
        """After a pickle migration, the first successful persist() renames
        the legacy .pkl to .pkl.migrated so the unsafe pickle.load() path
        can never be re-executed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "index.bin"
            legacy_pkl_path = Path(temp_dir) / "metadata.pkl"

            index = faiss.IndexFlatL2(128)
            vector = np.random.rand(128).astype(np.float32).reshape(1, -1)
            index.add(vector)
            faiss.write_index(index, str(index_path))

            legacy_payload = {
                "metadata": [
                    {
                        "document_id": "doc_legacy",
                        "text": "Legacy chunk text",
                        "source": "legacy.txt",
                        "chunk_index": 0,
                        "total_chunks": 1,
                        "preserve": False,
                        "indexed_at": "2026-07-01T00:00:00",
                        "metadata": {},
                        "chunk_id": 0,
                    }
                ],
                "document_to_chunks": {"doc_legacy": [0]},
                "stats": {
                    "total_vectors": 1,
                    "total_documents": 1,
                    "last_updated": "2026-07-01T00:00:00",
                },
                "version": "1.0",
                "saved_at": "2026-07-01T00:00:00",
            }
            with open(legacy_pkl_path, "wb") as f:
                pickle.dump(legacy_payload, f, protocol=pickle.HIGHEST_PROTOCOL)

            store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(legacy_pkl_path)
            )

            # Migration happened, pickle still in place before persist()
            assert legacy_pkl_path.exists()

            assert store.persist() is True

            # JSON metadata written; legacy pickle retired (renamed)
            assert store.metadata_path.exists()
            assert not legacy_pkl_path.exists()
            assert Path(str(legacy_pkl_path) + ".migrated").exists()

            # A new store on the same paths loads from JSON without the
            # pickle fallback ever being reachable again
            new_store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(legacy_pkl_path)
            )
            assert new_store.document_to_chunks == {"doc_legacy": [0]}

    def test_round_trip_json(self):
        """A fresh store persists to JSON; a new instance on the same paths
        loads metadata/document_to_chunks identically, with no .pkl present."""
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

            # No legacy pickle file exists at all
            assert not store.legacy_metadata_path.exists()
            assert store.metadata_path.exists()

            new_store = FaissVectorStore(
                dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
            )

            assert new_store.document_to_chunks == store.document_to_chunks
            assert len(new_store.metadata) == len(store.metadata)
            assert new_store.metadata[0]["document_id"] == "doc_roundtrip"
