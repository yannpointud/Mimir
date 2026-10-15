"""Unit tests for the exact-term retrieval regression helper.

Mock-based and offline: these tests exercise ONLY the pure comparison helper
``compare_exact_term_recall`` with simulated retrieval hits. They NEVER hit the
Mistral API, the vector store, nor the network -- the "hits" are plain integer
lists standing in for retrieved document_ids. This guards the
anti-regression rule (hybrid must not degrade exact-term recall vs dense).
"""

import pytest

from scripts.ragas_eval.exact_term_check import compare_exact_term_recall


def test_no_regression_when_hybrid_matches_or_beats_dense():
    """Hybrid recovers a doc dense missed -> hybrid_recall > dense_recall, no regression."""
    # Query 0: both modes retrieve the expected doc (12).
    # Query 1: dense MISSES the expected doc (99), hybrid RESCUES it via BM25.
    dense_hits = [[12, 5], [7, 8]]
    hybrid_hits = [[12, 5], [99, 7]]
    expected_doc_ids = [12, 99]

    result = compare_exact_term_recall(dense_hits, hybrid_hits, expected_doc_ids)

    assert result["dense_recall"] == pytest.approx(0.5)   # 1/2 queries hit
    assert result["hybrid_recall"] == pytest.approx(1.0)  # 2/2 queries hit
    assert result["no_regression"] is True
    assert len(result["per_query"]) == 2
    # Query 1 is exactly the exact-term rescue case.
    assert result["per_query"][1]["dense_hit"] is False
    assert result["per_query"][1]["hybrid_hit"] is True


def test_equal_recall_is_still_no_regression():
    """Identical recall (hybrid == dense) must count as no regression."""
    dense_hits = [[12], [99]]
    hybrid_hits = [[12, 3], [99, 4]]  # same expected docs found, extra noise ignored
    expected_doc_ids = [12, 99]

    result = compare_exact_term_recall(dense_hits, hybrid_hits, expected_doc_ids)

    assert result["dense_recall"] == pytest.approx(1.0)
    assert result["hybrid_recall"] == pytest.approx(1.0)
    assert result["no_regression"] is True


def test_regression_detected_when_hybrid_drops_an_exact_term_doc():
    """Hybrid loses a doc dense had -> hybrid_recall < dense_recall, regression flagged."""
    # Query 0: both find the expected doc.
    # Query 1: dense FINDS 99 but hybrid does NOT -> exact-term regression.
    dense_hits = [[12], [99, 8]]
    hybrid_hits = [[12], [8, 7]]
    expected_doc_ids = [12, 99]

    result = compare_exact_term_recall(dense_hits, hybrid_hits, expected_doc_ids)

    assert result["dense_recall"] == pytest.approx(1.0)
    assert result["hybrid_recall"] == pytest.approx(0.5)
    assert result["no_regression"] is False
    assert result["per_query"][1]["dense_hit"] is True
    assert result["per_query"][1]["hybrid_hit"] is False


def test_empty_query_set_is_vacuous_pass():
    """No queries -> zero recall both sides, no_regression vacuously True."""
    result = compare_exact_term_recall([], [], [])

    assert result["dense_recall"] == 0.0
    assert result["hybrid_recall"] == 0.0
    assert result["no_regression"] is True
    assert result["per_query"] == []


def test_mismatched_lengths_raise():
    """Guard against silently comparing misaligned query sets."""
    with pytest.raises(ValueError):
        compare_exact_term_recall([[1]], [[1], [2]], [1])
