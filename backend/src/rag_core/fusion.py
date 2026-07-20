"""Reciprocal Rank Fusion (RRF) — pure, stdlib-only rank aggregation.

Additive building block for hybrid retrieval (RAG-02). This module has NO I/O
and NO external dependency: it only merges pre-ranked chunk-id lists coming from
independent retrievers (dense/cosine and lexical/BM25) into a single fused score
map. It never touches the dense-only retrieval path, which keeps its cosine
`similarity_threshold` semantics unchanged.
"""

from dataclasses import dataclass
from typing import Dict, Sequence

__all__ = ["RankedResult", "reciprocal_rank_fusion"]


@dataclass
class RankedResult:
    """A single retriever hit.

    Attributes:
        chunk_id: Identifier of the retrieved chunk.
        score: Original retriever score (cosine similarity or BM25), kept for
            debugging/traceability — RRF itself only uses ranks, not this value.
    """

    chunk_id: int
    score: float


def reciprocal_rank_fusion(
    rank_lists: Sequence[Sequence[int]],
    k: int = 60,
) -> Dict[int, float]:
    """Fuse several ranked chunk-id lists with Reciprocal Rank Fusion.

    Standard RRF (Cormack, Clarke & Buttcher, "Reciprocal Rank Fusion
    outperforms Condorcet and individual Rank Learning Methods", SIGIR 2009):

        score(d) = sum over retrievers r of 1 / (k + rank_r(d))

    summed across every retriever where ``d`` appears. Ranks are 1-indexed. A
    document absent from a retriever's list simply contributes 0 for that
    retriever (it is not penalized beyond that missing contribution), so a doc
    ranked consistently by multiple retrievers accumulates the highest score.

    Args:
        rank_lists: One chunk-id list per retriever, already sorted by
            decreasing relevance. Empty lists are allowed and contribute nothing.
        k: RRF damping constant (default 60). Larger k flattens the weight
            difference between adjacent ranks.

    Returns:
        Mapping ``chunk_id -> fused RRF score``. Empty if no chunk appears in
        any list.
    """
    fused: Dict[int, float] = {}
    for rank_list in rank_lists:
        for rank, chunk_id in enumerate(rank_list, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return fused
