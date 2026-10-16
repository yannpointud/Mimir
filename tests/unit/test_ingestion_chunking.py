"""
Unit tests of the text chunking
"""

import pytest

from mimir.ingestion.chunking import ChunkingConfig, ChunkingStrategy
from mimir.ingestion.extractors import MarkdownExtractor


class TestChunkingConfig:
    """Chunking configuration tests"""

    def test_default_config(self):
        config = ChunkingConfig()

        assert config.chunk_size == 1000
        assert config.overlap == 120
        assert config.min_chunk_size == 100
        assert config.max_chunk_size == 3000
        assert config.preserve_sentences is True
        assert config.preserve_paragraphs is True

    def test_custom_config(self):
        config = ChunkingConfig(
            chunk_size=500,
            overlap=100,
            min_chunk_size=50,
            max_chunk_size=1000,
            preserve_sentences=False,
            preserve_paragraphs=False,
        )

        assert config.chunk_size == 500
        assert config.overlap == 100
        assert config.min_chunk_size == 50
        assert config.max_chunk_size == 1000
        assert config.preserve_sentences is False
        assert config.preserve_paragraphs is False


class TestChunkingStrategy:
    """Chunking strategy tests"""

    @pytest.fixture
    def default_strategy(self):
        """Strategy with the default configuration"""
        return ChunkingStrategy()

    @pytest.fixture
    def small_chunks_strategy(self):
        """Strategy for small chunks"""
        config = ChunkingConfig(chunk_size=200, overlap=50, min_chunk_size=30, max_chunk_size=400)
        return ChunkingStrategy(config)

    def test_strategy_initialization(self):
        strategy = ChunkingStrategy()

        assert strategy.config.chunk_size == 1000
        assert strategy.config.overlap == 120

    def test_strategy_with_custom_config(self):
        config = ChunkingConfig(chunk_size=500)
        strategy = ChunkingStrategy(config)

        assert strategy.config.chunk_size == 500

    def test_chunk_empty_text(self, default_strategy):
        chunks = default_strategy.chunk_text("")

        assert chunks == []

    def test_chunk_whitespace_only(self, default_strategy):
        chunks = default_strategy.chunk_text("   \n  \t  \n  ")

        assert chunks == []

    def test_chunk_small_text(self, default_strategy):
        text = "This is a small text that fits in one chunk."
        chunks = default_strategy.chunk_text(text)

        assert len(chunks) == 1
        assert chunks[0]["text"] == text
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["total_chunks"] == 1
        assert chunks[0]["start_char"] == 0
        assert chunks[0]["end_char"] == len(text)
        assert chunks[0]["word_count"] == len(text.split())
        assert chunks[0]["char_count"] == len(text)

    def test_chunk_large_text_by_paragraphs(self, default_strategy):
        text = """First paragraph with some content that should be in the first chunk.

Second paragraph with different content that might be in a separate chunk depending on the size.

Third paragraph with additional content to test the chunking strategy."""

        chunks = default_strategy.chunk_text(text)

        assert len(chunks) >= 1
        assert all(chunk["chunk_index"] < chunk["total_chunks"] for chunk in chunks)
        assert all(chunk["char_count"] > 0 for chunk in chunks)

    def test_chunk_text_without_paragraphs(self, small_chunks_strategy):
        # Create a text longer than max_chunk_size (400 characters)
        sentences = [
            "This is the first sentence that needs to be quite long to ensure proper chunking behavior.",
            "This is the second sentence with significantly more content to reach the required length.",
            "Here we have a third sentence that continues to add substantial content to the overall text.",
            "The fourth sentence continues the text with additional meaningful content and words.",
            "Fifth sentence adds even more comprehensive content to make it much longer than before.",
            "Sixth sentence ensures we definitely exceed the maximum chunk size limit without any doubt.",
            "Seventh sentence for good measure with extra content to guarantee chunking occurs as expected.",
        ]
        text = " ".join(sentences)

        chunks = small_chunks_strategy.chunk_text(text)

        # A long enough text should be chunked
        if len(text) > small_chunks_strategy.config.max_chunk_size:
            assert len(chunks) > 1  # Should be split into several chunks
        assert all(
            chunk["char_count"] <= small_chunks_strategy.config.max_chunk_size for chunk in chunks
        )

    def test_chunk_with_overlap(self, default_strategy):
        # Create a text long enough to need several chunks
        long_text = "This is a long sentence. " * 100  # ~2500 characters

        chunks = default_strategy.chunk_text(long_text)

        if len(chunks) > 1:
            # Check the overlap between consecutive chunks
            first_chunk = chunks[0]["text"]
            second_chunk = chunks[1]["text"]

            # Look for shared content (overlap)
            first_words = first_chunk.split()
            second_words = second_chunk.split()

            # The second chunk should start with a few words of the first one
            common_words = set(first_words[-10:]) & set(second_words[:10])
            assert len(common_words) > 0

    def test_clean_text_function(self, default_strategy):
        dirty_text = "  Hello   world  \n\n\n\n  Multiple   spaces   \n\n  End  "

        cleaned = default_strategy._clean_text(dirty_text)

        # Check that the text is cleaned
        assert not cleaned.startswith(" ")
        assert not cleaned.endswith(" ")
        assert "   " not in cleaned  # At most 2 consecutive spaces
        assert "\n\n\n" not in cleaned  # At most 2 consecutive newlines

    def test_split_sentences(self, default_strategy):
        text = "First sentence. Second sentence! Third sentence? Fourth sentence."

        sentences = default_strategy._split_sentences(text)

        assert len(sentences) == 4
        assert "First sentence" in sentences[0]
        assert "Second sentence" in sentences[1]
        assert "Third sentence" in sentences[2]
        assert "Fourth sentence" in sentences[3]

    def test_split_sentences_with_abbreviations(self, default_strategy):
        text = "Dr. Smith visited Mr. Johnson. They discussed the project. Inc. stocks rose."

        sentences = default_strategy._split_sentences(text)

        # Check that the sentences are split correctly
        assert len(sentences) >= 2  # Au moins 2 phrases attendues
        # Check that the abbreviations are present (even if cleaned)
        sentence_text = " ".join(sentences)
        assert "Dr" in sentence_text and "Smith" in sentence_text
        assert "Mr" in sentence_text and "Johnson" in sentence_text

    def test_get_overlap_text(self, default_strategy):
        text = "This is a sample text for testing overlap functionality. It should work correctly."

        overlap = default_strategy._get_overlap_text(text, 20)

        # The overlap may be slightly longer to keep word boundaries
        assert len(overlap) <= 30  # Margin for word boundaries
        assert overlap.strip() in text  # The overlap must come from the original text

    def test_chunk_statistics(self, default_strategy):
        text = "This is a test text. " * 50  # ~1000 characters
        chunks = default_strategy.chunk_text(text)

        stats = default_strategy.get_chunk_statistics(chunks)

        assert stats["total_chunks"] == len(chunks)
        assert stats["total_characters"] > 0
        assert stats["total_words"] > 0
        assert stats["avg_chunk_size"] > 0
        assert stats["min_chunk_size"] > 0
        assert stats["max_chunk_size"] > 0
        assert stats["config"]["chunk_size"] == default_strategy.config.chunk_size

    def test_chunk_statistics_empty(self, default_strategy):
        stats = default_strategy.get_chunk_statistics([])

        assert stats["total_chunks"] == 0
        assert stats["total_characters"] == 0
        assert stats["total_words"] == 0
        assert stats["avg_chunk_size"] == 0
        assert stats["min_chunk_size"] == 0
        assert stats["max_chunk_size"] == 0

    def test_preserve_sentences_disabled(self):
        config = ChunkingConfig(
            chunk_size=50,  # Smaller size to force the split
            max_chunk_size=80,  # Limite plus stricte
            preserve_sentences=False,
            preserve_paragraphs=False,
        )
        strategy = ChunkingStrategy(config)

        # Create a very long text, clearly over the limit
        text = (
            "This is a very long sentence that definitely exceeds the chunk size limit and should be split even in the middle of words or sentences when preserve_sentences is disabled. "
            * 3
        )  # Triple it to be sure to exceed the limit

        chunks = strategy.chunk_text(text)

        # With a long enough text and strict limits
        assert len(text) > config.max_chunk_size  # Check that the text really exceeds the limit
        assert len(chunks) > 1
        # With preserve_sentences=False, chunks may split sentences

    def test_very_long_sentence_handling(self, default_strategy):
        # A sentence over 2000 characters
        very_long_sentence = "This is an extremely long sentence " * 100 + "."

        chunks = default_strategy.chunk_text(very_long_sentence)

        assert len(chunks) >= 1
        # Even very long sentences must be handled

    def test_chunk_with_source_parameter(self, default_strategy):
        text = "Test text for source parameter."
        source = "test_document.txt"

        chunks = default_strategy.chunk_text(text, source=source)

        assert len(chunks) == 1
        # This function does not store the source in the chunk
        # (the processor handles it)

    def test_chunk_indices_consistency(self, default_strategy):
        text = "Sentence one. " * 100  # Long enough for several chunks

        chunks = default_strategy.chunk_text(text)

        # Check that the indices are consistent
        for i, chunk in enumerate(chunks):
            assert chunk["chunk_index"] == i
            assert chunk["total_chunks"] == len(chunks)

    def test_word_count_accuracy(self, default_strategy):
        text = "One two three four five six seven eight nine ten."

        chunks = default_strategy.chunk_text(text)

        total_words_counted = sum(chunk["word_count"] for chunk in chunks)
        actual_words = len(text.split())

        # The count may differ slightly because of the overlap
        assert total_words_counted >= actual_words

    def test_empty_paragraphs_handling(self, default_strategy):
        text = """First paragraph.


Second paragraph after empty lines.



Third paragraph."""

        chunks = default_strategy.chunk_text(text)

        # Empty paragraphs must not create empty chunks
        assert all(chunk["text"].strip() for chunk in chunks)
        assert all(chunk["char_count"] > 0 for chunk in chunks)


class TestChunkingIntegration:
    """Chunking integration tests"""

    def test_realistic_document_chunking(self):
        # Simulate a technical document
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

        assert len(chunks) > 1  # Document long enough for several chunks

        # Check that the metadata is correct
        for chunk in chunks:
            assert chunk["chunk_index"] < chunk["total_chunks"]
            assert chunk["char_count"] > 0
            assert chunk["word_count"] > 0
            assert len(chunk["text"].strip()) > 0

        # Check that the important content is kept
        all_text = " ".join(chunk["text"] for chunk in chunks)
        assert "Introduction" in all_text
        assert "Implementation Details" in all_text
        assert "Conclusion" in all_text

    def test_different_text_types(self):
        configs_and_texts = [
            # Code source
            (
                ChunkingConfig(chunk_size=300),
                """
def process_text(text):
    if not text:
        return []

    chunks = []
    # Process the text
    return chunks
            """,
            ),
            # Bullet list
            (
                ChunkingConfig(chunk_size=200),
                """
Shopping list:
- Apples
- Bananas
- Oranges
- Milk
- Bread
- Cheese
            """,
            ),
            # Texte narratif
            (
                ChunkingConfig(chunk_size=400),
                """
Once upon a time, in a land far away, there lived a princess who loved to read books. She spent her days in the castle library, discovering new worlds through literature. One day, she found a mysterious book that would change her life forever.
            """,
            ),
        ]

        for config, text in configs_and_texts:
            strategy = ChunkingStrategy(config)
            chunks = strategy.chunk_text(text.strip())

            # Every kind of text must be processed correctly
            assert len(chunks) >= 1
            assert all(len(chunk["text"].strip()) > 0 for chunk in chunks)


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
        html = MarkdownExtractor(convert_to_html=True).extract(self._write_md(tmp_path, md))
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
        html = MarkdownExtractor(convert_to_html=True).extract(self._write_md(tmp_path, md))

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
        html = MarkdownExtractor(convert_to_html=True).extract(self._write_md(tmp_path, md))
        chunks = ChunkingStrategy(self._structure_config(True)).chunk_text(html)

        assert len(chunks) == 1
        assert chunks[0]["section_title"] == "Only Section"


class TestSectionTitleThreadingIntoMetadata:
    """section_title flows chunking dict -> Chunk.metadata (no migration)."""

    def _new_processor(self):
        # Bypass __init__ (heavy deps): _create_chunks uses only its arguments.
        from mimir.ingestion.processor import IngestionProcessor

        return IngestionProcessor.__new__(IngestionProcessor)

    def test_section_title_reaches_chunk_metadata(self):
        proc = self._new_processor()
        chunks_data = [
            {
                "text": "Alpha body.",
                "chunk_index": 0,
                "total_chunks": 1,
                "start_char": 0,
                "end_char": 11,
                "word_count": 2,
                "char_count": 11,
                "section_title": "Section A",
            }
        ]
        result = proc._create_chunks(chunks_data, [[0.1, 0.2, 0.3]], "doc1", "mimir.md", {})

        assert len(result) == 1
        assert result[0].metadata["section_title"] == "Section A"

    def test_flag_off_chunk_has_no_section_title_value(self):
        """Flag-off chunk dict (no key) yields metadata section_title None, no error."""
        proc = self._new_processor()
        chunks_data = [
            {
                "text": "Alpha body.",
                "chunk_index": 0,
                "total_chunks": 1,
                "start_char": 0,
                "end_char": 11,
                "word_count": 2,
                "char_count": 11,
            }
        ]
        result = proc._create_chunks(chunks_data, [[0.1, 0.2, 0.3]], "doc1", "mimir.md", {})

        assert len(result) == 1
        assert result[0].metadata.get("section_title") is None
        # Existing metadata keys remain intact.
        assert result[0].metadata["start_char"] == 0
        assert result[0].metadata["char_count"] == 11


# Exact-output tests below pin the current splitter behaviour (they were
# written against surviving mutmut mutants of chunking.py).
# Known quirks are pinned as they are, except chunk positions: start_char
# never advances past the first chunk, so only position invariants are checked.


def _texts(chunks):
    return [chunk["text"] for chunk in chunks]


def _assert_positions(chunks):
    """First chunk starts at 0 and every span is as long as its text."""
    assert chunks[0]["start_char"] == 0
    for chunk in chunks:
        assert chunk["start_char"] >= 0
        assert chunk["end_char"] - chunk["start_char"] == len(chunk["text"])


class TestCleanTextExact:
    def test_clean_text_exact_output(self):
        dirty = "  Hello   world  \n\n\n\n  Multiple   spaces   \n\n  End  "

        assert ChunkingStrategy()._clean_text(dirty) == "Hello world\n\nMultiple spaces\n\nEnd"


class TestParagraphChunkingExact:
    PARAGRAPHS = ("Alpha one. Alpha two.", "Beta one. Beta two.", "Gamma one. Gamma two.")

    def _strategy(self, chunk_size, max_chunk_size=200):
        return ChunkingStrategy(
            ChunkingConfig(
                chunk_size=chunk_size,
                overlap=12,
                min_chunk_size=5,
                max_chunk_size=max_chunk_size,
            )
        )

    def test_paragraphs_fill_a_chunk_up_to_chunk_size_inclusive(self):
        # len("Alpha one. Alpha two.\n\nBeta one. Beta two.") == 42 == chunk_size
        chunks = self._strategy(42).chunk_text("\n\n".join(self.PARAGRAPHS))

        assert _texts(chunks) == [
            "Alpha one. Alpha two.\n\nBeta one. Beta two.",
            "Beta two. Gamma one. Gamma two.",
        ]
        assert [c["chunk_index"] for c in chunks] == [0, 1]
        assert all(c["total_chunks"] == 2 for c in chunks)
        _assert_positions(chunks)

    def test_paragraph_one_char_over_chunk_size_starts_a_new_chunk(self):
        chunks = self._strategy(41).chunk_text("\n\n".join(self.PARAGRAPHS))

        # Each new chunk starts with the last sentence of the previous one.
        assert _texts(chunks) == [
            "Alpha one. Alpha two.",
            "Alpha two. Beta one. Beta two.",
            "Beta two. Gamma one. Gamma two.",
        ]
        _assert_positions(chunks)

    def test_paragraph_of_exactly_max_chunk_size_is_not_resplit(self):
        text = "Short one is here. Another short one ok."  # 40 characters

        chunks = self._strategy(20, max_chunk_size=40).chunk_text(text)

        assert _texts(chunks) == [text]
        _assert_positions(chunks)


class TestSentenceChunkingExact:
    """preserve_paragraphs=False: sentence path (terminators are dropped by the split)."""

    TEXT = "First one here. Second one here. Third one here."

    def _strategy(self, chunk_size, min_chunk_size=5, overlap=12):
        return ChunkingStrategy(
            ChunkingConfig(
                chunk_size=chunk_size,
                overlap=overlap,
                min_chunk_size=min_chunk_size,
                max_chunk_size=2000,
                preserve_paragraphs=False,
            )
        )

    def test_sentences_fill_a_chunk_up_to_chunk_size_inclusive(self):
        # 14 + 1 + 15 == 30 == chunk_size: the first two sentences share a chunk.
        chunks = self._strategy(30).chunk_text(self.TEXT)

        assert _texts(chunks) == ["First one here Second one here", "ond one here Third one here."]
        _assert_positions(chunks)

    def test_chunk_of_exactly_min_size_is_closed_when_next_sentence_overflows(self):
        chunks = self._strategy(29, min_chunk_size=14).chunk_text(self.TEXT)

        assert _texts(chunks) == [
            "First one here",
            "rst one here Second one here",
            "ond one here Third one here.",
        ]
        _assert_positions(chunks)

    def test_chunk_below_min_size_absorbs_the_next_sentence(self):
        text = "One two three. Four five six. Seven eight nine."

        chunks = self._strategy(20, min_chunk_size=24, overlap=6).chunk_text(text)

        # The 24-character tail equals min_chunk_size, so it is kept.
        assert _texts(chunks) == ["One two three Four five six", "ve six Seven eight nine."]
        _assert_positions(chunks)

    def test_zero_min_chunk_size_never_emits_an_empty_chunk(self):
        chunks = self._strategy(10, min_chunk_size=0, overlap=3).chunk_text(
            "First one here. Second one here."
        )

        assert _texts(chunks) == ["First one here", "ere Second one here."]
        _assert_positions(chunks)

    def test_text_never_reaching_min_size_becomes_a_single_chunk(self):
        chunks = self._strategy(20, min_chunk_size=1000, overlap=6).chunk_text(self.TEXT)

        assert len(chunks) == 1
        assert chunks[0]["text"] == self.TEXT
        assert chunks[0]["start_char"] == 0
        assert chunks[0]["end_char"] == len(self.TEXT)

    def test_text_of_exactly_chunk_size_is_kept_verbatim(self):
        text = "First one here. Second one here."  # 32 characters

        chunks = self._strategy(32).chunk_text(text)

        assert _texts(chunks) == [text]


class TestSplitSentencesExact:
    def test_regex_split_is_kept_when_it_finds_several_sentences(self):
        # Only ". G" is a regex boundary; the fallback would also split at ". e".
        strategy = ChunkingStrategy(ChunkingConfig(chunk_size=20))

        sentences = strategy._split_sentences("alpha beta. Gamma delta. epsilon zeta.")

        assert sentences == ["alpha beta", "Gamma delta. epsilon zeta."]

    def test_fallback_split_when_a_long_text_has_a_single_regex_sentence(self):
        strategy = ChunkingStrategy(ChunkingConfig(chunk_size=20))

        sentences = strategy._split_sentences("alpha beta. gamma delta. epsilon zeta.")

        assert sentences == ["alpha beta", "gamma delta", "epsilon zeta."]

    def test_no_fallback_for_a_text_of_exactly_chunk_size(self):
        strategy = ChunkingStrategy(ChunkingConfig(chunk_size=24))

        sentences = strategy._split_sentences("alpha beta. gamma delta.")  # 24 characters

        assert sentences == ["alpha beta. gamma delta."]


class TestOverlapTextExact:
    def test_no_overlap_for_empty_text(self):
        assert ChunkingStrategy()._get_overlap_text("", 10) == ""

    def test_no_overlap_for_zero_size(self):
        assert ChunkingStrategy()._get_overlap_text("One. Two.", 0) == ""

    def test_overlap_starts_after_the_last_sentence_boundary(self):
        assert ChunkingStrategy()._get_overlap_text("One. Two", 1) == "Two "

    def test_boundary_is_searched_up_to_100_chars_before_the_overlap(self):
        text = "a" * 198 + ". " + "b" * 100

        assert ChunkingStrategy()._get_overlap_text(text, 20) == "b" * 100 + " "

    def test_boundary_before_the_lookback_window_is_ignored(self):
        # The window starts at len - size - 100 == 180, one char after the ".".
        text = "a" * 179 + ". " + "b" * 119

        assert ChunkingStrategy()._get_overlap_text(text, 20) == "b" * 20 + " "

    def test_boundary_at_the_start_of_the_window_is_found(self):
        assert ChunkingStrategy()._get_overlap_text("! abc", 4) == "abc "

    def test_boundary_at_the_very_end_falls_back_to_characters(self):
        assert ChunkingStrategy()._get_overlap_text("Hello world. ", 5) == "rld.  "

    def test_overlap_as_long_as_the_text_returns_the_whole_text(self):
        assert ChunkingStrategy()._get_overlap_text("One. Two", 8) == "One. Two "

    def test_character_overlap_when_sentences_are_not_preserved(self):
        strategy = ChunkingStrategy(ChunkingConfig(preserve_sentences=False))

        assert strategy._get_overlap_text("One. Two three", 5) == "three "

    def test_overlap_longer_than_the_text_returns_the_whole_text(self):
        strategy = ChunkingStrategy(ChunkingConfig(preserve_sentences=False))

        assert strategy._get_overlap_text("abc", 10) == "abc "


class TestChunkStatisticsExact:
    def test_statistics_prefer_the_stored_word_count(self):
        chunks = [{"text": "a b c", "word_count": 10}, {"text": "d e"}]

        stats = ChunkingStrategy().get_chunk_statistics(chunks)

        assert stats["total_chunks"] == 2
        assert stats["total_characters"] == 8
        assert stats["total_words"] == 12
        assert stats["avg_chunk_size"] == 4.0
        assert stats["min_chunk_size"] == 3
        assert stats["max_chunk_size"] == 5
        assert stats["avg_words_per_chunk"] == 6.0


class TestSectionTitlesExact:
    def test_preamble_has_no_section_and_each_heading_tags_its_chunk(self):
        text = (
            "An introduction without a heading.\n\n# Alpha\n\nAlpha body.\n\n"
            "# Beta\n\nBeta body.\n\n# Gamma\n\nGamma body."
        )
        config = ChunkingConfig(
            chunk_size=22,
            overlap=0,
            min_chunk_size=5,
            max_chunk_size=200,
            section_title_tracking=True,
        )

        chunks = ChunkingStrategy(config).chunk_text(text)

        assert [(c["text"], c["section_title"]) for c in chunks] == [
            ("An introduction without a heading.", None),
            ("# Alpha\n\nAlpha body.", "Alpha"),
            ("# Beta\n\nBeta body.", "Beta"),
            ("# Gamma\n\nGamma body.", "Gamma"),
        ]

    def test_inline_markup_is_stripped_from_heading_titles(self):
        headings = ChunkingStrategy()._detect_headings(
            "<h2><em>Intro</em> part</h2>\n\n<h3>Next</h3>"
        )

        assert [title for _, title in headings] == ["Intro part", "Next"]
