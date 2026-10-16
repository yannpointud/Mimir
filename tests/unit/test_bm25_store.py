"""
Unit tests for the BM25 lexical store and the light French tokenizer.

Covers:
- light_french_tokenizer: accent folding (café == cafe == CAFÉ) and exact
  identifier/acronym preservation with no stemming/stopwords.
- Bm25LexicalStore: rebuild + query returning the right chunk_ids, save/load
  round-trip (allow_pickle=False, no arbitrary deserialization), and a rebuild
  from a subset (simulating a document delete) that drops the removed chunks.

Fixture style mirrors tests/unit/test_faiss_vector_store.py (tempdir persistence,
absolute mimir.* imports, pytest.raises for error paths).
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from mimir.rag_core.implementations.bm25_store import Bm25LexicalStore
from mimir.rag_core.interfaces import VectorStoreOperationError
from mimir.rag_core.tokenizer_fr import light_french_tokenizer

# --------------------------------------------------------------------------- #
# Light French tokenizer                                                      #
# --------------------------------------------------------------------------- #


class TestLightFrenchTokenizer:
    """Tokenizer: accent fold + exact-term preservation, no stemming/stopwords."""

    def test_accent_fold_produces_matching_tokens(self):
        assert light_french_tokenizer(["Café", "cafe", "CAFÉ"]) == [["cafe"], ["cafe"], ["cafe"]]

    def test_exact_identifier_preserved_no_stemming(self):
        """Identifiers/acronyms are preserved verbatim, split on non-alnum."""
        tokens = light_french_tokenizer(["Le ticket JIRA-4521 concerne l'API REST"])
        assert "4521" in tokens[0]
        assert "jira" in tokens[0]
        assert "api" in tokens[0]

    def test_no_stopwords_removed(self):
        """No stopword filtering: common French words stay in the token list."""
        tokens = light_french_tokenizer(["le la les de des un une et"])[0]
        for word in ["le", "la", "les", "de", "des", "un", "une", "et"]:
            assert word in tokens

    def test_various_accents_folded(self):
        tokens = light_french_tokenizer(["àçèêïôù"])[0]
        assert tokens == ["aceeiou"]

    def test_empty_string_yields_empty_tokens(self):
        """Empty / punctuation-only inputs yield an empty token list."""
        assert light_french_tokenizer(["", "   ", "!!!"]) == [[], [], []]


# --------------------------------------------------------------------------- #
# Bm25LexicalStore                                                            #
# --------------------------------------------------------------------------- #


def _make_chunks():
    """A small corpus where each doc has a distinctive exact term."""
    return [
        {"chunk_id": 10, "text": "Le café est servi le matin dans la salle commune"},
        {"chunk_id": 20, "text": "Le ticket JIRA-4521 concerne l'API REST de facturation"},
        {"chunk_id": 30, "text": "La procédure de sauvegarde SQLite utilise le mode WAL"},
    ]


class TestBm25LexicalStore:
    """rebuild / query / persistence for the lexical store."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.index_path = str(Path(self.tmpdir) / "bm25" / "index")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rebuild_then_query_returns_expected_chunk_id(self):
        """An exact-term query returns the right chunk_id at the top."""
        store = Bm25LexicalStore(self.index_path)
        store.rebuild(_make_chunks())

        results = store.query("JIRA-4521", top_k=3)
        assert results, "expected at least one hit for an exact identifier"
        top_chunk_id, top_score = results[0]
        assert top_chunk_id == 20
        assert top_score > 0.0

    def test_query_maps_index_position_to_real_chunk_id(self):
        """Returned ids are the real chunk_ids, not corpus positions."""
        store = Bm25LexicalStore(self.index_path)
        store.rebuild(_make_chunks())

        results = store.query("café matin", top_k=3)
        assert results[0][0] == 10  # the café chunk, real id 10 (not position 0)

    def test_query_top_k_bounded_by_corpus_size(self):
        """top_k larger than the corpus does not raise and is clamped."""
        store = Bm25LexicalStore(self.index_path)
        store.rebuild(_make_chunks())

        results = store.query("café", top_k=100)
        assert len(results) <= 3

    def test_save_load_round_trip_gives_same_results(self):
        """Reloading the index from disk reproduces the same query results."""
        store = Bm25LexicalStore(self.index_path)
        store.rebuild(_make_chunks())
        before = store.query("WAL SQLite", top_k=3)

        # Fresh instance, load from disk (allow_pickle=False, JSON + .npy).
        reloaded = Bm25LexicalStore(self.index_path)
        assert reloaded.load() is True
        after = reloaded.query("WAL SQLite", top_k=3)

        assert before == after
        assert after[0][0] == 30

    def test_rebuild_from_subset_drops_deleted_document(self):
        """A rebuild from a subset (deleted doc) removes it from results."""
        store = Bm25LexicalStore(self.index_path)
        store.rebuild(_make_chunks())
        assert store.query("JIRA-4521", top_k=3)[0][0] == 20

        # Simulate deleting the JIRA document: rebuild from the remaining chunks.
        remaining = [c for c in _make_chunks() if c["chunk_id"] != 20]
        store.rebuild(remaining)

        results = store.query("JIRA-4521", top_k=3)
        returned_ids = [cid for cid, _ in results]
        assert 20 not in returned_ids

    def test_query_before_rebuild_raises(self):
        """Querying an unbuilt / unloaded store raises an operation error."""
        store = Bm25LexicalStore(self.index_path)
        with pytest.raises(VectorStoreOperationError):
            store.query("anything", top_k=3)

    def test_load_missing_index_returns_false(self):
        """load() on a non-existent path returns False (no crash)."""
        store = Bm25LexicalStore(self.index_path)
        assert store.load() is False

    def test_rebuild_empty_corpus_is_safe(self):
        """Rebuilding from an empty corpus yields empty query results."""
        store = Bm25LexicalStore(self.index_path)
        store.rebuild([])
        assert store.query("café", top_k=3) == []
