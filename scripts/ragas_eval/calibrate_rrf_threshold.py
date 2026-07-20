#!/usr/bin/env python
"""Calibrate rrf_score_threshold on the REAL RRF score distribution (RAG-02, venv principal).

Why this exists: ``settings.rrf_score_threshold`` starts at 0.015 (06-03), an
ASSUMED value. Before the hybrid-vs-baseline comparative run (plan 06-07 Task 3),
that threshold MUST be confronted with the actual RRF scores produced on the
FROZEN golden set -- a threshold set too high silently empties the hybrid mode
(RESEARCH Pitfall #2: RRF scores peak around 0.033 at k=60), while one set too
low filters nothing. This script runs the hybrid RRF fusion over every golden
question WITHOUT applying the threshold filter, aggregates the score
distribution (min/max/mean/median/percentiles), recommends a data-driven
threshold, and flags whether the 0.015 starting value is coherent.

Design choices:
  - It consumes ONLY query embeddings (one Mistral embedding per question) -- no
    LLM generation, no RAGAS judge. It reuses the REAL production fusion
    (``reciprocal_rank_fusion``) and dense/BM25 pools so the measured scores match
    what the live hybrid pipeline computes, minus the final threshold filter.
  - Mistral free tier allows ~1 request/second; the loop throttles to <= 1
    call/sec (``THROTTLE_SECONDS``) IN ADDITION to the budget reservation.
  - ``MISTRAL_API_KEY`` transits ONLY via environment; never logged or written.
  - It does NOT rewrite config.py: source edits from a script are fragile. It
    emits a clear recommendation in the JSON and on stdout; applying the
    calibrated value to ``settings.rrf_score_threshold`` is a deliberate operator
    step (plan 06-07 Task 3), keeping the conservative posture explicit.

The aggregation/recommendation helpers are pure (no I/O, no network) so the
output-shape contract is verifiable offline. The real run against the ingested
corpus is a separate, budget-consuming step (plan 06-07 Task 3).
"""

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# sys.path bootstrap (same discipline as generate_golden_set.py): make the
# project root and the backend package importable whether this file is run as a
# script or imported as the package module.
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
_BACKEND_DIR = _PROJECT_ROOT / "backend"
for _path in (_PROJECT_ROOT, _BACKEND_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# Mistral free-tier rate limit is ~1 request/second. Throttle the query loop
# below this ceiling so a real run never hits HTTP 429. This is on TOP of the
# budget_guard reservation, which bounds spend, not request rate.
THROTTLE_SECONDS = 1.1

# The starting value seeded in 06-03; calibration confirms or replaces it.
_STARTING_THRESHOLD = 0.015

_DEFAULT_GOLDEN_SET = _SCRIPT_DIR / "golden_set" / "golden_set_v1.jsonl"
_DEFAULT_OUT = _SCRIPT_DIR / "results" / "rrf_score_distribution.json"
# How many top RRF scores to keep per query in the report (traceability).
_TOP_SCORES_PER_QUERY = 5


def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile of an already-sorted ascending sequence.

    Pure and stdlib-only (no numpy) so the aggregation stays trivially testable.

    Args:
        sorted_values: Values sorted in ascending order.
        pct: Percentile in [0, 100].

    Returns:
        The interpolated percentile, or 0.0 for an empty sequence.
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(sorted_values[low])
    frac = rank - low
    return float(sorted_values[low]) * (1.0 - frac) + float(sorted_values[high]) * frac


def summarize_rrf_scores(scores: Sequence[float]) -> Dict[str, Any]:
    """Aggregate a flat list of RRF hit scores into a distribution summary (pure).

    Args:
        scores: Every RRF score collected across all golden queries' hits.

    Returns:
        Dict with count, min, max, mean, median and p10/p25/p50/p75/p90. On an
        empty input every statistic is 0.0 and count is 0.
    """
    count = len(scores)
    if count == 0:
        return {
            "count": 0, "min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0,
            "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0,
        }
    ordered = sorted(float(s) for s in scores)
    return {
        "count": count,
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / count,
        "median": _percentile(ordered, 50),
        "p10": _percentile(ordered, 10),
        "p25": _percentile(ordered, 25),
        "p50": _percentile(ordered, 50),
        "p75": _percentile(ordered, 75),
        "p90": _percentile(ordered, 90),
    }


def recommend_rrf_threshold(per_query_top_scores: Sequence[float]) -> float:
    """Recommend a data-driven rrf_score_threshold (pure).

    Strategy: a LOW percentile (p10) of the per-query BEST RRF scores. Keeping the
    threshold below ~90% of queries' top score guarantees the hybrid mode almost
    never returns zero sources, while still trimming the long tail of weak
    single-retriever hits. Returns 0.0 when there is no data.

    Args:
        per_query_top_scores: The best RRF score of each golden query.

    Returns:
        The recommended threshold value.
    """
    if not per_query_top_scores:
        return 0.0
    ordered = sorted(float(s) for s in per_query_top_scores)
    return _percentile(ordered, 10)


def assess_starting_value(
    starting_value: float,
    per_query_top_scores: Sequence[float],
    all_scores: Sequence[float],
) -> Tuple[bool, str]:
    """Judge whether ``starting_value`` is coherent with the observed scores (pure).

    Two failure modes (RESEARCH Pitfall #2):
      - TOO HIGH: above at least one query's best score -> that query would be
        emptied of every hybrid source.
      - TOO LOW: at or below every observed score -> the threshold filters
        nothing at all.

    Args:
        starting_value: The threshold under test (e.g. 0.015).
        per_query_top_scores: The best RRF score of each golden query.
        all_scores: Every RRF hit score across all queries.

    Returns:
        (coherent, assessment_message).
    """
    if not per_query_top_scores or not all_scores:
        return False, "Aucune donnée de score RRF: distribution vide, calibration impossible."

    min_top = min(per_query_top_scores)
    overall_min = min(all_scores)

    if starting_value > min_top:
        return False, (
            f"Valeur de départ {starting_value} TROP HAUTE: au moins une requête a "
            f"un meilleur score RRF de {min_top:.5f}, elle serait vidée de toute "
            "source en mode hybride (Pitfall #2)."
        )
    if starting_value <= overall_min:
        return False, (
            f"Valeur de départ {starting_value} TROP BASSE: elle est sous le score "
            f"RRF minimal observé ({overall_min:.5f}), elle ne filtrerait aucune "
            "source (aucun effet de seuil)."
        )
    return True, (
        f"Valeur de départ {starting_value} COHÉRENTE: sous le meilleur score de "
        f"chaque requête (min top = {min_top:.5f}) et au-dessus du plancher "
        f"observé ({overall_min:.5f})."
    )


def build_distribution_report(
    all_scores: Sequence[float],
    per_query_top_scores: Sequence[float],
    *,
    starting_value: float,
    rrf_k: int,
    num_queries: int,
) -> Dict[str, Any]:
    """Assemble the full rrf_score_distribution report (pure, no I/O).

    Combines the flat-score distribution, the per-query top scores, the
    data-driven recommendation and the coherence verdict on ``starting_value``.
    Kept pure so the output-shape contract is verifiable without a Mistral run.
    """
    report = summarize_rrf_scores(all_scores)
    recommended = recommend_rrf_threshold(per_query_top_scores)
    coherent, assessment = assess_starting_value(
        starting_value, per_query_top_scores, all_scores
    )
    report.update({
        "num_queries": num_queries,
        "rrf_k": rrf_k,
        "per_query_top_scores": [float(s) for s in per_query_top_scores],
        "recommended_rrf_score_threshold": recommended,
        "starting_value": starting_value,
        "starting_value_coherent": coherent,
        "starting_value_assessment": assessment,
    })
    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    """CLI parser. Kept separate so ``--help`` needs no heavy imports."""
    parser = argparse.ArgumentParser(
        description=(
            "Calibre rrf_score_threshold sur la distribution réelle des scores "
            "RRF du golden set gelé (RAG-02). Un appel embedding Mistral par "
            "question, throttlé <= 1/s. N'affiche jamais MISTRAL_API_KEY."
        )
    )
    parser.add_argument(
        "--golden-set", type=Path, default=_DEFAULT_GOLDEN_SET,
        help="Chemin du golden set JSONL gelé (source des questions).",
    )
    parser.add_argument(
        "--out", type=Path, default=_DEFAULT_OUT,
        help="Chemin de sortie de la distribution des scores RRF.",
    )
    parser.add_argument(
        "--top-k", type=int, default=None,
        help="Taille du pool candidat par retriever (défaut: _HYBRID_POOL_SIZE).",
    )
    return parser


async def _embed_question(
    question: str,
    *,
    llm_service,
    budget_guard,
    usage_tracker,
    session_id: str,
):
    """Embed one question, reserving budget BEFORE the call (fail-closed).

    Returns the numpy embedding vector, or None when the daily budget cap is
    reached. The Mistral key is never logged here.
    """
    import numpy as np

    reservation = None
    if budget_guard is not None:
        reservation = budget_guard.reserve("embedding")
        if reservation is None:
            print("Budget quotidien atteint -- arrêt de la calibration.", file=sys.stderr)
            return None

    try:
        response = await llm_service.embed([question], session_id=session_id)
    except Exception:
        if budget_guard is not None and reservation is not None:
            budget_guard.release(reservation)
        raise

    if usage_tracker is not None and budget_guard is not None and reservation is not None:
        cost_eur = usage_tracker.record(
            call_type="embedding",
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            session_id=session_id,
        )
        budget_guard.finalize(reservation, cost_eur)

    return np.array(response.embeddings[0], dtype=np.float32)


def _fused_scores_for_query(question: str, embedding, vector_store, bm25_store,
                            *, top_k: int, rrf_k: int) -> List[float]:
    """Compute the RRF fused scores for one query WITHOUT the threshold filter.

    Mirrors ``_hybrid_retrieve`` (raw dense pool at similarity_floor=0.0 + BM25
    pool, fused via ``reciprocal_rank_fusion``) but returns the raw fused score
    values, so the distribution reflects the pre-filter reality.
    """
    from src.rag_core.fusion import reciprocal_rank_fusion

    dense_pool = vector_store.query(
        vector=embedding,
        top_k=top_k,
        filter_dict=None,
        similarity_floor=0.0,
    )
    lexical_pool = bm25_store.query(question, top_k)

    rank_lists = [
        [r.chunk_id for r in dense_pool],
        [chunk_id for chunk_id, _ in lexical_pool],
    ]
    fused_scores = reciprocal_rank_fusion(rank_lists, k=rrf_k)
    return list(fused_scores.values())


async def _run(entries: List[str], *, llm_service, vector_store, bm25_store,
               budget_guard, usage_tracker, top_k: int, rrf_k: int) -> Dict[str, Any]:
    """Run the throttled fusion loop and assemble the distribution report.

    One embedding call per question, throttled to <= 1 call/sec.
    """
    all_scores: List[float] = []
    per_query_top_scores: List[float] = []
    processed = 0

    for index, question in enumerate(entries):
        # Throttle to stay under the Mistral free-tier 1 req/s ceiling.
        if index > 0:
            await asyncio.sleep(THROTTLE_SECONDS)

        embedding = await _embed_question(
            question,
            llm_service=llm_service,
            budget_guard=budget_guard,
            usage_tracker=usage_tracker,
            session_id=f"rrf-calibration-{index}",
        )
        if embedding is None:
            break  # Budget cap reached (fail-closed).

        fused = _fused_scores_for_query(
            question, embedding, vector_store, bm25_store, top_k=top_k, rrf_k=rrf_k
        )
        processed += 1
        if fused:
            all_scores.extend(fused)
            top_sorted = sorted(fused, reverse=True)[:_TOP_SCORES_PER_QUERY]
            per_query_top_scores.append(top_sorted[0])

    return build_distribution_report(
        all_scores,
        per_query_top_scores,
        starting_value=_STARTING_THRESHOLD,
        rrf_k=rrf_k,
        num_queries=processed,
    )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Heavy service imports are deferred past argument parsing
    so ``--help`` never imports FastAPI nor touches any secret."""
    args = _build_arg_parser().parse_args(argv)

    if not Path(args.golden_set).exists():
        print(
            f"Golden set introuvable: {args.golden_set}\n"
            "Geler d'abord golden_set_v1.jsonl (plan 06-01) puis relancer.",
            file=sys.stderr,
        )
        return 1

    # Deferred imports: pulling these at module top would drag the backend
    # service stack in for a bare --help.
    from src.config import settings
    from src.services.rag_service import _HYBRID_POOL_SIZE
    from src.api.dependencies import (
        get_budget_guard,
        get_bm25_store,
        get_llm_service,
        get_usage_tracker,
        get_vector_store,
    )
    from scripts.ragas_eval.golden_set_schema import load_golden_set

    top_k = args.top_k if args.top_k is not None else _HYBRID_POOL_SIZE

    golden_entries = load_golden_set(args.golden_set)
    questions = [entry.user_input for entry in golden_entries]
    if not questions:
        print("Golden set vide -- rien à calibrer.", file=sys.stderr)
        return 1

    vector_store = get_vector_store()
    vector_store.load()
    bm25_store = get_bm25_store()

    report = asyncio.run(_run(
        questions,
        llm_service=get_llm_service(),
        vector_store=vector_store,
        bm25_store=bm25_store,
        budget_guard=get_budget_guard(),
        usage_tracker=get_usage_tracker(),
        top_k=top_k,
        rrf_k=settings.rrf_k,
    ))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"Distribution RRF écrite: {out_path} "
        f"(count={report['count']}, median={report['median']:.5f}, "
        f"p10={report['p10']:.5f})"
    )
    print(
        f"Seuil recommandé (data-driven): "
        f"{report['recommended_rrf_score_threshold']:.5f}"
    )
    print(f"Valeur de départ 0.015 -> {report['starting_value_assessment']}")
    if not report["starting_value_coherent"]:
        print(
            "ACTION: mettre à jour settings.rrf_score_threshold (config.py) avec la "
            "valeur recommandée AVANT le run comparatif (plan 06-07 Task 3).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
