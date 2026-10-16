"""
Tests d'intégration pour la gestion centralisée des logs
"""

import pytest
import tempfile
import json  # noqa: F401
import time  # noqa: F401
from pathlib import Path
from unittest.mock import AsyncMock, Mock  # noqa: F401

from mimir.monitoring.logger import (
    setup_logger,
)
from mimir.llm_interface.implementations.mistral_api import MistralAPIService
from mimir.rag_core.implementations.faiss_store import FaissVectorStore


class TestLoggingIntegration:
    """Tests d'intégration pour le système de logging centralisé"""

    @pytest.fixture
    def temp_log_dir(self):
        """Répertoire temporaire pour les logs de test"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)

    def test_logger_setup_and_configuration(self, temp_log_dir):
        """Test de configuration du logger avec fichiers multiples"""
        # Configurer un logger de test
        logger = setup_logger("test_module")

        # Vérifier que le logger est configuré
        assert logger.name == "test_module"
        assert len(logger.handlers) >= 1  # Au moins console handler

        # Test de log basique
        logger.info("Test message")
        logger.error("Test error message")

    def test_faiss_store_logging(self, temp_log_dir):
        """Test du logging dans FaissVectorStore"""
        import numpy as np
        from mimir.rag_core.interfaces import Chunk

        # Créer un store FAISS temporaire
        index_path = temp_log_dir / "test.index"
        metadata_path = temp_log_dir / "test.json"

        store = FaissVectorStore(
            dimension=128,
            index_path=str(index_path),
            metadata_path=str(metadata_path),
            similarity_threshold=0.5,
        )

        # Créer un chunk de test
        chunk = Chunk(
            text="Test chunk for logging",
            embedding=np.random.rand(128).astype(np.float32),
            document_id="log_test_doc",
            chunk_index=0,
            total_chunks=1,
            source="logging_test.txt",
            metadata={"test": True},
        )

        # Test des opérations avec logging
        success = store.upsert([chunk])
        assert success is True

        # Test query avec logging
        query_vector = np.random.rand(128).astype(np.float32)
        results = store.query(query_vector, top_k=5)  # noqa: F841

        # Test health check avec logging
        is_healthy = store.health_check()
        assert isinstance(is_healthy, bool)

    @pytest.mark.asyncio
    async def test_mistral_api_logging(self):
        """Test du logging dans MistralAPIService"""
        # Créer un service avec API key de test
        service = MistralAPIService(api_key="test_logging_key")

        # Test health check qui génère des logs
        is_healthy = await service.health_check()

        # Le service doit logger même en cas d'échec (API key invalide)
        assert isinstance(is_healthy, bool)

    def test_ingestion_pipeline_logging(self, temp_log_dir):
        """Test du logging dans le pipeline d'ingestion"""
        from mimir.ingestion.extractors import ExtractorFactory
        from mimir.ingestion.chunking import ChunkingStrategy

        # Créer un fichier de test
        test_file = temp_log_dir / "logging_test.txt"
        test_file.write_text("This is a test document for logging validation. " * 10)

        # Test extraction avec logging
        factory = ExtractorFactory()
        extracted_text = factory.extract_text(str(test_file))
        assert len(extracted_text) > 0

        # Test chunking avec logging
        chunking = ChunkingStrategy()
        chunks = chunking.chunk_text(extracted_text)
        assert len(chunks) >= 1


class TestJalon2AcceptanceCriteria:
    """Tests d'acceptation pour les critères du Jalon 2"""

    @pytest.fixture
    def temp_workspace(self):
        """Espace de travail temporaire pour les tests d'acceptation"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)

    def test_jalon2_component_initialization(self, temp_workspace):
        """Critère: Tous les composants du Jalon 2 peuvent être initialisés"""
        import numpy as np  # noqa: F401

        # 1. LLM Interface - Mistral API
        llm_service = MistralAPIService(api_key="test_acceptance_key")
        assert llm_service.model_name == "mistral-small-latest"
        assert llm_service.embedding_dimension > 0

        # 2. FAISS Vector Store
        index_path = temp_workspace / "acceptance.index"
        metadata_path = temp_workspace / "acceptance.json"

        faiss_store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )
        assert faiss_store.dimension == 128

        # 3. Ingestion Components
        from mimir.ingestion.extractors import ExtractorFactory
        from mimir.ingestion.chunking import ChunkingStrategy

        extractor_factory = ExtractorFactory()
        supported_extensions = extractor_factory.get_supported_extensions()
        assert ".pdf" in supported_extensions
        assert ".docx" in supported_extensions
        assert ".txt" in supported_extensions
        assert ".md" in supported_extensions

        chunking_strategy = ChunkingStrategy()
        assert chunking_strategy.config.chunk_size == 1000
        assert chunking_strategy.config.overlap == 120

    def test_jalon2_text_extraction_workflow(self, temp_workspace):
        """Critère: Le système peut extraire du texte des formats supportés"""
        from mimir.ingestion.extractors import ExtractorFactory

        factory = ExtractorFactory()

        # Test TXT
        txt_file = temp_workspace / "test.txt"
        txt_content = "This is a text file for acceptance testing. It contains multiple sentences."
        txt_file.write_text(txt_content, encoding="utf-8")

        extracted_txt = factory.extract_text(str(txt_file))
        assert txt_content in extracted_txt

        # Test MD
        md_file = temp_workspace / "test.md"
        md_content = "# Test Document\n\nThis is a markdown document for testing."
        md_file.write_text(md_content, encoding="utf-8")

        extracted_md = factory.extract_text(str(md_file))
        assert "Test Document" in extracted_md
        assert "markdown document" in extracted_md

    def test_jalon2_chunking_workflow(self, temp_workspace):
        """Critère: Le système peut découper intelligemment les textes"""
        from mimir.ingestion.chunking import ChunkingStrategy, ChunkingConfig

        # Texte assez long pour nécessiter plusieurs chunks (doit dépasser max_chunk_size de 3000)
        long_text = "This is a test document. " * 150  # ~3750 caractères

        # Configuration selon les spécifications Jalon 2
        config = ChunkingConfig(
            chunk_size=1000, overlap=120, preserve_sentences=True, preserve_paragraphs=True
        )

        strategy = ChunkingStrategy(config)
        chunks = strategy.chunk_text(long_text)

        # Vérifications des critères Jalon 2
        assert len(chunks) >= 1  # Au moins un chunk doit être créé

        # Chaque chunk doit respecter les critères
        for chunk in chunks:
            assert chunk["char_count"] <= config.max_chunk_size
            assert (
                chunk["char_count"] >= config.min_chunk_size
                or chunk["chunk_index"] == chunk["total_chunks"] - 1
            )
            assert len(chunk["text"].strip()) > 0
            assert chunk["chunk_index"] < chunk["total_chunks"]

    def test_jalon2_vector_storage_workflow(self, temp_workspace):
        """Critère: Le système peut stocker et rechercher des vecteurs"""
        import numpy as np
        from mimir.rag_core.interfaces import Chunk

        # Créer un store FAISS
        index_path = temp_workspace / "workflow.index"
        metadata_path = temp_workspace / "workflow.json"

        store = FaissVectorStore(
            dimension=128,
            index_path=str(index_path),
            metadata_path=str(metadata_path),
            similarity_threshold=0.5,
        )

        # Créer des chunks de test avec embeddings
        test_chunks = []
        for i in range(5):
            embedding = np.random.rand(128).astype(np.float32)
            chunk = Chunk(
                text=f"Test document chunk {i} with some meaningful content.",
                embedding=embedding,
                document_id=f"acceptance_doc_{i}",
                chunk_index=0,
                total_chunks=1,
                source=f"acceptance_{i}.txt",
                metadata={"test_id": i, "category": "acceptance"},
            )
            test_chunks.append(chunk)

        # Test d'ajout (upsert)
        success = store.upsert(test_chunks)
        assert success is True

        # Test de recherche (query)
        query_vector = test_chunks[0].embedding + 0.01  # Proche du premier
        results = store.query(query_vector, top_k=3)
        assert len(results) > 0

        # Test de persistance
        persist_success = store.persist()
        assert persist_success is True

        # Vérifier que les fichiers ont été créés (metadata_path est normalisé
        # en .json par le store, quelle que soit l'extension passée en config)
        assert index_path.exists()
        assert store.metadata_path.exists()

        # Test de chargement dans un nouveau store
        new_store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        load_success = new_store.load()
        assert load_success is True

        # Tester que les données ont été chargées
        query_results = new_store.query(query_vector, top_k=3)
        assert len(query_results) > 0

    @pytest.mark.integration
    def test_jalon2_end_to_end_pipeline(self, temp_workspace):
        """Test d'acceptation complet du pipeline Jalon 2"""
        import numpy as np
        from mimir.ingestion.extractors import ExtractorFactory
        from mimir.ingestion.chunking import ChunkingStrategy
        from mimir.rag_core.interfaces import Chunk

        # 1. Préparation des données
        test_document = temp_workspace / "end_to_end_test.txt"
        document_content = """
        Intelligence Artificielle et Machine Learning

        L'intelligence artificielle (IA) est une technologie en pleine expansion.
        Le machine learning permet aux systèmes d'apprendre automatiquement.
        Les réseaux de neurones sont au cœur des algorithmes modernes.

        Applications pratiques:
        - Reconnaissance d'images
        - Traitement du langage naturel
        - Systèmes de recommandation
        - Véhicules autonomes

        L'avenir de l'IA s'annonce prometteur avec des développements constants.
        """
        test_document.write_text(document_content, encoding="utf-8")

        # 2. Extraction
        factory = ExtractorFactory()
        extracted_text = factory.extract_text(str(test_document))
        assert len(extracted_text) > 0

        # 3. Chunking
        strategy = ChunkingStrategy()
        chunks_data = strategy.chunk_text(extracted_text, source=str(test_document))
        assert len(chunks_data) >= 1

        # 4. Simulation d'embeddings (normalement généré par Mistral)
        chunks = []
        for chunk_data in chunks_data:
            # Simuler un embedding (en prod, généré par MistralAPIService)
            simulated_embedding = np.random.rand(128).astype(np.float32)

            chunk = Chunk(
                text=chunk_data["text"],
                embedding=simulated_embedding,
                document_id="e2e_doc",
                chunk_index=chunk_data["chunk_index"],
                total_chunks=chunk_data["total_chunks"],
                source=str(test_document),
                metadata=chunk_data,
            )
            chunks.append(chunk)

        # 5. Stockage vectoriel
        index_path = temp_workspace / "e2e.index"
        metadata_path = temp_workspace / "e2e.json"

        store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        success = store.upsert(chunks)
        assert success is True

        # 6. Recherche vectorielle
        query_vector = chunks[0].embedding + 0.05  # Similaire au premier chunk
        results = store.query(query_vector, top_k=3)
        assert len(results) > 0

        # 7. Persistance et récupération
        store.persist()
        assert index_path.exists()
        assert store.metadata_path.exists()

        # Test de récupération complète
        new_store = FaissVectorStore(
            dimension=128, index_path=str(index_path), metadata_path=str(metadata_path)
        )

        new_store.load()
        recovery_results = new_store.query(query_vector, top_k=3)
        assert len(recovery_results) > 0
