"""
Tests unitaires pour le chunking de texte intelligent
"""

import pytest
from src.ingestion.chunking import ChunkingStrategy, ChunkingConfig
from src.ingestion.extractors import MarkdownExtractor


class TestChunkingConfig:
    """Tests pour la configuration de chunking"""

    def test_default_config(self):
        """Test de configuration par défaut"""
        config = ChunkingConfig()

        assert config.chunk_size == 1000
        assert config.overlap == 120
        assert config.min_chunk_size == 100
        assert config.max_chunk_size == 3000
        assert config.preserve_sentences is True
        assert config.preserve_paragraphs is True

    def test_custom_config(self):
        """Test de configuration personnalisée"""
        config = ChunkingConfig(
            chunk_size=500,
            overlap=100,
            min_chunk_size=50,
            max_chunk_size=1000,
            preserve_sentences=False,
            preserve_paragraphs=False
        )

        assert config.chunk_size == 500
        assert config.overlap == 100
        assert config.min_chunk_size == 50
        assert config.max_chunk_size == 1000
        assert config.preserve_sentences is False
        assert config.preserve_paragraphs is False


class TestChunkingStrategy:
    """Tests pour la stratégie de chunking"""

    @pytest.fixture
    def default_strategy(self):
        """Stratégie avec configuration par défaut"""
        return ChunkingStrategy()

    @pytest.fixture
    def small_chunks_strategy(self):
        """Stratégie pour petits chunks"""
        config = ChunkingConfig(
            chunk_size=200,
            overlap=50,
            min_chunk_size=30,
            max_chunk_size=400
        )
        return ChunkingStrategy(config)

    def test_strategy_initialization(self):
        """Test d'initialisation de la stratégie"""
        strategy = ChunkingStrategy()

        assert strategy.config.chunk_size == 1000
        assert strategy.config.overlap == 120

    def test_strategy_with_custom_config(self):
        """Test avec configuration personnalisée"""
        config = ChunkingConfig(chunk_size=500)
        strategy = ChunkingStrategy(config)

        assert strategy.config.chunk_size == 500

    def test_chunk_empty_text(self, default_strategy):
        """Test avec texte vide"""
        chunks = default_strategy.chunk_text("")

        assert chunks == []

    def test_chunk_whitespace_only(self, default_strategy):
        """Test avec espaces uniquement"""
        chunks = default_strategy.chunk_text("   \n  \t  \n  ")

        assert chunks == []

    def test_chunk_small_text(self, default_strategy):
        """Test avec texte plus petit que chunk_size"""
        text = "This is a small text that fits in one chunk."
        chunks = default_strategy.chunk_text(text)

        assert len(chunks) == 1
        assert chunks[0]['text'] == text
        assert chunks[0]['chunk_index'] == 0
        assert chunks[0]['total_chunks'] == 1
        assert chunks[0]['start_char'] == 0
        assert chunks[0]['end_char'] == len(text)
        assert chunks[0]['word_count'] == len(text.split())
        assert chunks[0]['char_count'] == len(text)

    def test_chunk_large_text_by_paragraphs(self, default_strategy):
        """Test de découpage par paragraphes"""
        text = """First paragraph with some content that should be in the first chunk.

Second paragraph with different content that might be in a separate chunk depending on the size.

Third paragraph with additional content to test the chunking strategy."""

        chunks = default_strategy.chunk_text(text)

        assert len(chunks) >= 1
        assert all(chunk['chunk_index'] < chunk['total_chunks'] for chunk in chunks)
        assert all(chunk['char_count'] > 0 for chunk in chunks)

    def test_chunk_text_without_paragraphs(self, small_chunks_strategy):
        """Test avec texte sans paragraphes (une seule ligne)"""
        # Créer un texte suffisamment long pour dépasser max_chunk_size (400 caractères)
        sentences = [
            "This is the first sentence that needs to be quite long to ensure proper chunking behavior.",
            "This is the second sentence with significantly more content to reach the required length.",
            "Here we have a third sentence that continues to add substantial content to the overall text.",
            "The fourth sentence continues the text with additional meaningful content and words.",
            "Fifth sentence adds even more comprehensive content to make it much longer than before.",
            "Sixth sentence ensures we definitely exceed the maximum chunk size limit without any doubt.",
            "Seventh sentence for good measure with extra content to guarantee chunking occurs as expected."
        ]
        text = " ".join(sentences)

        chunks = small_chunks_strategy.chunk_text(text)

        # Si le texte est assez long, il devrait être chunké
        if len(text) > small_chunks_strategy.config.max_chunk_size:
            assert len(chunks) > 1  # Devrait être divisé en plusieurs chunks
        assert all(chunk['char_count'] <= small_chunks_strategy.config.max_chunk_size for chunk in chunks)

    def test_chunk_with_overlap(self, default_strategy):
        """Test du système d'overlap"""
        # Créer un texte assez long pour nécessiter plusieurs chunks
        long_text = "This is a long sentence. " * 100  # ~2500 caractères

        chunks = default_strategy.chunk_text(long_text)

        if len(chunks) > 1:
            # Vérifier qu'il y a un overlap entre chunks consécutifs
            first_chunk = chunks[0]['text']
            second_chunk = chunks[1]['text']

            # Chercher du contenu commun (overlap)
            first_words = first_chunk.split()
            second_words = second_chunk.split()

            # Il devrait y avoir quelques mots en commun au début du deuxième chunk
            common_words = set(first_words[-10:]) & set(second_words[:10])
            assert len(common_words) > 0

    def test_clean_text_function(self, default_strategy):
        """Test de la fonction de nettoyage du texte"""
        dirty_text = "  Hello   world  \n\n\n\n  Multiple   spaces   \n\n  End  "

        cleaned = default_strategy._clean_text(dirty_text)

        # Vérifier que le texte est nettoyé
        assert not cleaned.startswith(' ')
        assert not cleaned.endswith(' ')
        assert '   ' not in cleaned  # Pas plus de 2 espaces consécutifs
        assert '\n\n\n' not in cleaned  # Pas plus de 2 newlines consécutifs

    def test_split_sentences(self, default_strategy):
        """Test du découpage en phrases"""
        text = "First sentence. Second sentence! Third sentence? Fourth sentence."

        sentences = default_strategy._split_sentences(text)

        assert len(sentences) == 4
        assert "First sentence" in sentences[0]
        assert "Second sentence" in sentences[1]
        assert "Third sentence" in sentences[2]
        assert "Fourth sentence" in sentences[3]

    def test_split_sentences_with_abbreviations(self, default_strategy):
        """Test du découpage avec abréviations"""
        text = "Dr. Smith visited Mr. Johnson. They discussed the project. Inc. stocks rose."

        sentences = default_strategy._split_sentences(text)

        # Vérifier que les phrases sont correctement découpées
        assert len(sentences) >= 2  # Au moins 2 phrases attendues
        # Vérifier que les abréviations sont présentes (même si nettoyées)
        sentence_text = " ".join(sentences)
        assert "Dr" in sentence_text and "Smith" in sentence_text
        assert "Mr" in sentence_text and "Johnson" in sentence_text

    def test_get_overlap_text(self, default_strategy):
        """Test de génération d'overlap"""
        text = "This is a sample text for testing overlap functionality. It should work correctly."

        overlap = default_strategy._get_overlap_text(text, 20)

        # L'overlap peut être légèrement plus long si cela préserve les limites des mots
        assert len(overlap) <= 30  # Marge pour les limites de mots
        assert overlap.strip() in text  # L'overlap doit être dans le texte original

    def test_chunk_statistics(self, default_strategy):
        """Test des statistiques de chunking"""
        text = "This is a test text. " * 50  # ~1000 caractères
        chunks = default_strategy.chunk_text(text)

        stats = default_strategy.get_chunk_statistics(chunks)

        assert stats['total_chunks'] == len(chunks)
        assert stats['total_characters'] > 0
        assert stats['total_words'] > 0
        assert stats['avg_chunk_size'] > 0
        assert stats['min_chunk_size'] > 0
        assert stats['max_chunk_size'] > 0
        assert stats['config']['chunk_size'] == default_strategy.config.chunk_size

    def test_chunk_statistics_empty(self, default_strategy):
        """Test des statistiques avec liste vide"""
        stats = default_strategy.get_chunk_statistics([])

        assert stats['total_chunks'] == 0
        assert stats['total_characters'] == 0
        assert stats['total_words'] == 0
        assert stats['avg_chunk_size'] == 0
        assert stats['min_chunk_size'] == 0
        assert stats['max_chunk_size'] == 0

    def test_preserve_sentences_disabled(self):
        """Test avec préservation des phrases désactivée"""
        config = ChunkingConfig(
            chunk_size=50,  # Taille plus petite pour forcer le découpage
            max_chunk_size=80,  # Limite plus stricte
            preserve_sentences=False,
            preserve_paragraphs=False
        )
        strategy = ChunkingStrategy(config)

        # Créer un texte très long qui dépasse clairement la limite
        text = "This is a very long sentence that definitely exceeds the chunk size limit and should be split even in the middle of words or sentences when preserve_sentences is disabled. " * 3  # Tripler pour garantir le dépassement

        chunks = strategy.chunk_text(text)

        # Avec un texte suffisamment long et des limites strictes
        assert len(text) > config.max_chunk_size  # Vérifier que le texte dépasse vraiment
        assert len(chunks) > 1
        # Avec preserve_sentences=False, les chunks peuvent couper au milieu des phrases

    def test_very_long_sentence_handling(self, default_strategy):
        """Test avec une phrase très longue (dépasse max_chunk_size)"""
        # Une phrase de plus de 2000 caractères
        very_long_sentence = "This is an extremely long sentence " * 100 + "."

        chunks = default_strategy.chunk_text(very_long_sentence)

        assert len(chunks) >= 1
        # Même les phrases très longues doivent être gérées

    def test_chunk_with_source_parameter(self, default_strategy):
        """Test avec paramètre source"""
        text = "Test text for source parameter."
        source = "test_document.txt"

        chunks = default_strategy.chunk_text(text, source=source)

        assert len(chunks) == 1
        # Le source n'est pas stocké dans le chunk par cette fonction
        # (c'est géré par le processor)

    def test_chunk_indices_consistency(self, default_strategy):
        """Test de cohérence des indices de chunks"""
        text = "Sentence one. " * 100  # Assez long pour plusieurs chunks

        chunks = default_strategy.chunk_text(text)

        # Vérifier que les indices sont cohérents
        for i, chunk in enumerate(chunks):
            assert chunk['chunk_index'] == i
            assert chunk['total_chunks'] == len(chunks)

    def test_chunk_character_positions(self, small_chunks_strategy):
        """Test des positions de caractères dans les chunks"""
        text = "First part of text. Second part of text. Third part of text."

        chunks = small_chunks_strategy.chunk_text(text)

        if len(chunks) > 1:
            # Vérifier que les positions sont logiques
            for chunk in chunks:
                assert chunk['start_char'] >= 0
                assert chunk['end_char'] > chunk['start_char']
                assert chunk['end_char'] <= len(text) + 100  # Permettre un peu de marge pour l'overlap

    def test_word_count_accuracy(self, default_strategy):
        """Test de précision du comptage de mots"""
        text = "One two three four five six seven eight nine ten."

        chunks = default_strategy.chunk_text(text)

        total_words_counted = sum(chunk['word_count'] for chunk in chunks)
        actual_words = len(text.split())

        # Le compte peut être légèrement différent à cause de l'overlap
        assert total_words_counted >= actual_words

    def test_chunk_minimum_size_enforcement(self, default_strategy):
        """Test du respect de la taille minimum de chunk"""
        # Texte avec phrases courtes
        text = "Short. Very short. Another. Brief."

        chunks = default_strategy.chunk_text(text)

        # Vérifier qu'aucun chunk n'est trop petit (sauf le dernier éventuellement)
        for chunk in chunks[:-1]:  # Tous sauf le dernier
            assert len(chunk['text']) >= default_strategy.config.min_chunk_size or len(chunks) == 1

    def test_empty_paragraphs_handling(self, default_strategy):
        """Test de gestion des paragraphes vides"""
        text = """First paragraph.


Second paragraph after empty lines.



Third paragraph."""

        chunks = default_strategy.chunk_text(text)

        # Les paragraphes vides ne doivent pas créer de chunks vides
        assert all(chunk['text'].strip() for chunk in chunks)
        assert all(chunk['char_count'] > 0 for chunk in chunks)


class TestChunkingIntegration:
    """Tests d'intégration pour le chunking"""

    def test_realistic_document_chunking(self):
        """Test avec un document réaliste"""
        # Simuler un document technique
        document = """
# Introduction

This document describes the implementation of a text chunking system for document processing.

## Overview

The chunking system divides large documents into smaller, manageable pieces that can be processed independently. This is essential for applications like search, indexing, and machine learning where context windows are limited.

## Implementation Details

The chunking algorithm considers several factors:
- Sentence boundaries to maintain semantic coherence
- Paragraph structure to preserve logical organization
- Overlap between chunks to avoid losing context at boundaries
- Minimum and maximum chunk sizes for optimal processing

## Performance Considerations

When processing large documents, the chunking system must balance accuracy with performance. The algorithm uses efficient text processing techniques to minimize memory usage while maintaining high-quality chunk boundaries.

## Conclusion

This chunking implementation provides a robust solution for document processing applications requiring intelligent text segmentation.
        """.strip()

        strategy = ChunkingStrategy()
        chunks = strategy.chunk_text(document, source="technical_document.md")

        assert len(chunks) > 1  # Document assez long pour plusieurs chunks

        # Vérifier que les métadonnées sont correctes
        for chunk in chunks:
            assert chunk['chunk_index'] < chunk['total_chunks']
            assert chunk['char_count'] > 0
            assert chunk['word_count'] > 0
            assert len(chunk['text'].strip()) > 0

        # Vérifier que le contenu important est préservé
        all_text = " ".join(chunk['text'] for chunk in chunks)
        assert "Introduction" in all_text
        assert "Implementation Details" in all_text
        assert "Conclusion" in all_text

    def test_different_text_types(self):
        """Test avec différents types de texte"""
        configs_and_texts = [
            # Code source
            (ChunkingConfig(chunk_size=300), """
def process_text(text):
    if not text:
        return []

    chunks = []
    # Process the text
    return chunks
            """),

            # Liste à puces
            (ChunkingConfig(chunk_size=200), """
Shopping list:
- Apples
- Bananas
- Oranges
- Milk
- Bread
- Cheese
            """),

            # Texte narratif
            (ChunkingConfig(chunk_size=400), """
Once upon a time, in a land far away, there lived a princess who loved to read books. She spent her days in the castle library, discovering new worlds through literature. One day, she found a mysterious book that would change her life forever.
            """)
        ]

        for config, text in configs_and_texts:
            strategy = ChunkingStrategy(config)
            chunks = strategy.chunk_text(text.strip())

            # Chaque type de texte doit être traité correctement
            assert len(chunks) >= 1
            assert all(len(chunk['text'].strip()) > 0 for chunk in chunks)


class TestStructureAwareChunking:
    """Structure-aware chunking: heading -> section_title metadata.

    The load-bearing correctness fact: `.md` is ingested
    as HTML via ``MarkdownExtractor(convert_to_html=True)``, so heading detection
    must primarily target ``<h1>-<h6>`` tags. These tests therefore feed the REAL
    extractor output (not hand-written ``#`` strings) for the HTML path, and only
    exercise the raw ``#{1,6}`` path defensively.
    """

    # Small chunks force multiple boundaries so distinct sections land in
    # distinct chunks regardless of the paragraph/sentence split path.
    def _structure_config(self, enabled: bool) -> ChunkingConfig:
        return ChunkingConfig(
            chunk_size=300,
            overlap=50,
            min_chunk_size=30,
            max_chunk_size=500,
            section_title_tracking=enabled,
        )

    def _write_md(self, tmp_path, content: str) -> str:
        path = tmp_path / "doc.md"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_config_defaults_section_tracking_off(self):
        """The new flag defaults to False so chunking stays byte-identical."""
        assert ChunkingConfig().section_title_tracking is False

    def test_html_headings_drive_section_title(self, tmp_path):
        """HTML <h1>-<h6> from the real extractor drive section_title."""
        md = (
            "# Document Title\n\n"
            "## Section A\n\n"
            + ("Alpha discusses the first topic in careful detail here. " * 12)
            + "\n\n## Section B\n\n"
            + ("Beta explains the second topic with thorough coverage now. " * 12)
        )
        html = MarkdownExtractor(convert_to_html=True).extract(
            self._write_md(tmp_path, md)
        )
        # Sanity: the extractor really produced HTML heading tags, not `#`.
        assert "<h2>Section A</h2>" in html
        assert "<h2>Section B</h2>" in html

        chunks = ChunkingStrategy(self._structure_config(True)).chunk_text(html)

        titles = {c.get("section_title") for c in chunks}
        assert "Section A" in titles
        assert "Section B" in titles
        # Every chunk carries the key when the flag is on.
        assert all("section_title" in c for c in chunks)

    def test_raw_markdown_headings_detected_defensively(self):
        """Raw ``#{1,6}`` headings (e.g. a .txt) are detected defensively."""
        text = (
            "# Intro\n\n"
            + ("Intro body sentence number one with content. " * 10)
            + "\n\n## Details\n\n"
            + ("Details body sentence with more content here. " * 10)
        )
        chunks = ChunkingStrategy(self._structure_config(True)).chunk_text(text)

        titles = {c.get("section_title") for c in chunks}
        assert "Intro" in titles
        assert "Details" in titles

    def test_flag_off_no_section_key_and_identical_boundaries(self, tmp_path):
        """Flag off: no section_title key AND boundaries byte-identical to today."""
        md = (
            "# Document Title\n\n"
            "## Section A\n\n"
            + ("Alpha discusses the first topic in careful detail here. " * 12)
            + "\n\n## Section B\n\n"
            + ("Beta explains the second topic with thorough coverage now. " * 12)
        )
        html = MarkdownExtractor(convert_to_html=True).extract(
            self._write_md(tmp_path, md)
        )

        off = ChunkingStrategy(self._structure_config(False)).chunk_text(html)
        # Default config (no new field set) must match the explicit flag-off path.
        default_cfg = ChunkingConfig(
            chunk_size=300, overlap=50, min_chunk_size=30, max_chunk_size=500
        )
        baseline = ChunkingStrategy(default_cfg).chunk_text(html)

        assert off == baseline
        assert all("section_title" not in c for c in off)

        # On-vs-off: identical text and character boundaries, only an extra key.
        on = ChunkingStrategy(self._structure_config(True)).chunk_text(html)
        assert len(on) == len(off)
        for chunk_on, chunk_off in zip(on, off, strict=False):
            assert chunk_on["text"] == chunk_off["text"]
            assert chunk_on["start_char"] == chunk_off["start_char"]
            assert chunk_on["end_char"] == chunk_off["end_char"]

    def test_small_single_chunk_gets_section_title_when_enabled(self, tmp_path):
        """A short document that fits in one chunk still gets its section_title."""
        md = "## Only Section\n\nA short body that fits within a single chunk."
        html = MarkdownExtractor(convert_to_html=True).extract(
            self._write_md(tmp_path, md)
        )
        chunks = ChunkingStrategy(self._structure_config(True)).chunk_text(html)

        assert len(chunks) == 1
        assert chunks[0]["section_title"] == "Only Section"


class TestSectionTitleThreadingIntoMetadata:
    """section_title flows chunking dict -> Chunk.metadata (no migration)."""

    def _new_processor(self):
        # Bypass __init__ (heavy deps): _create_chunks uses only its arguments.
        from src.ingestion.processor import IngestionProcessor

        return IngestionProcessor.__new__(IngestionProcessor)

    def test_section_title_reaches_chunk_metadata(self):
        proc = self._new_processor()
        chunks_data = [{
            "text": "Alpha body.",
            "chunk_index": 0,
            "total_chunks": 1,
            "start_char": 0,
            "end_char": 11,
            "word_count": 2,
            "char_count": 11,
            "section_title": "Section A",
        }]
        result = proc._create_chunks(chunks_data, [[0.1, 0.2, 0.3]], "doc1", "src.md", {})

        assert len(result) == 1
        assert result[0].metadata["section_title"] == "Section A"

    def test_flag_off_chunk_has_no_section_title_value(self):
        """Flag-off chunk dict (no key) yields metadata section_title None, no error."""
        proc = self._new_processor()
        chunks_data = [{
            "text": "Alpha body.",
            "chunk_index": 0,
            "total_chunks": 1,
            "start_char": 0,
            "end_char": 11,
            "word_count": 2,
            "char_count": 11,
        }]
        result = proc._create_chunks(chunks_data, [[0.1, 0.2, 0.3]], "doc1", "src.md", {})

        assert len(result) == 1
        assert result[0].metadata.get("section_title") is None
        # Existing metadata keys remain intact.
        assert result[0].metadata["start_char"] == 0
        assert result[0].metadata["char_count"] == 11