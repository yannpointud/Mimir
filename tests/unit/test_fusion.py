"""Unit tests for the pure Reciprocal Rank Fusion (RRF) function.

Covers the canonical RRF edge cases documented by Elasticsearch/Azure AI Search
and the SIGIR 2009 formulation (Cormack, Clarke & Buttcher): consensus ranking,
a doc absent from one retriever, and an empty list from one retriever.
"""

from src.rag_core.fusion import RankedResult, reciprocal_rank_fusion


def test_rrf_k60_consensus_top_doc_wins():
    # Doc 2 is ranked 1st by BOTH retrievers, so its summed RRF score beats
    # docs 1 and 3 (each ranked highly by a single list only). This is the
    # canonical "consensus wins" behavior of RRF (Elasticsearch/Azure AI Search).
    dense = [2, 1, 3]  # doc 2 = rank 1 dense
    lexical = [2, 3, 1]  # doc 2 = rank 1 lexical too -> wins over 1 and 3
    fused = reciprocal_rank_fusion([dense, lexical], k=60)
    assert max(fused, key=fused.get) == 2


def test_rrf_symmetric_extremes_beat_median_by_convexity():
    # Subtlety of the SIGIR-2009 formula: with the symmetric input
    # [1,2,3] / [3,2,1] every doc appears in both lists, so this is NOT a
    # consensus test. Because 1/(k+rank) is convex, the extreme doc
    # (rank 1 + rank 3) scores slightly ABOVE the median doc (rank 2 + rank 2):
    #   1/61 + 1/63  >  2/62.
    # This documents why a naive "median doc wins" assumption is false and
    # guards the pure formula against being "fixed" into a non-canonical variant.
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 2, 1]], k=60)
    assert fused[1] == fused[3] > fused[2]
    assert fused[1] == 1.0 / 61 + 1.0 / 63
    assert fused[2] == 2.0 / 62


def test_rrf_doc_absent_from_one_retriever_not_penalized_beyond_zero_contribution():
    # Doc 2 appears in both lists; doc 1 only in one. Doc 2 must score higher
    # because it accumulates a contribution from each retriever, while a doc
    # absent from a retriever simply contributes 0 there (no extra penalty).
    fused = reciprocal_rank_fusion([[1, 2], [2]], k=60)
    assert fused[2] > fused[1]


def test_rrf_empty_list_from_one_retriever():
    # An empty retriever list must not break fusion nor drop any key.
    fused = reciprocal_rank_fusion([[1, 2, 3], []], k=60)
    assert set(fused.keys()) == {1, 2, 3}


def test_rrf_empty_input_returns_empty_dict():
    assert reciprocal_rank_fusion([], k=60) == {}
    assert reciprocal_rank_fusion([[], []], k=60) == {}


def test_rrf_single_list_uses_rank_1_indexed():
    # With a single retriever, score(d) = 1/(k+rank), rank 1-indexed.
    fused = reciprocal_rank_fusion([[10, 20]], k=60)
    assert fused[10] == 1.0 / 61
    assert fused[20] == 1.0 / 62
    assert fused[10] > fused[20]


def test_rrf_overlapping_ranks_sum_contributions():
    # Doc 1 is rank 1 in both lists -> exactly 2 * 1/(k+1).
    fused = reciprocal_rank_fusion([[1, 2], [1, 3]], k=60)
    assert fused[1] == 2.0 * (1.0 / 61)
    assert fused[2] == 1.0 / 62
    assert fused[3] == 1.0 / 62


def test_ranked_result_dataclass_shape():
    # RankedResult keeps the original retriever score for debugging.
    r = RankedResult(chunk_id=7, score=0.83)
    assert r.chunk_id == 7
    assert r.score == 0.83


def test_rrf_default_k_is_60():
    assert reciprocal_rank_fusion([[1, 2]]) == {1: 1.0 / 61, 2: 1.0 / 62}
