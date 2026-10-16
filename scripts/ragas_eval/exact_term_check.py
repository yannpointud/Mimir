#!/usr/bin/env python
"""Exact-term retrieval regression check: dense vs hybrid (main venv).

Why this exists: the hybrid adoption gate may only flip
``hybrid_search_enabled`` on if, among other conditions, hybrid retrieval does
NOT regress on exact-term queries (identifiers, acronyms) -- the very case a
lexical BM25 signal is meant to rescue. This script is a
TARGETED RETRIEVAL check (not a generation/RAGAS run): for a small list of
exact-term queries with their expected document, it collects the document_ids
retrieved in dense mode and in hybrid mode, then asserts hybrid recall never
falls below dense recall.

Design choices:
  - It is a RETRIEVAL check, so it never calls the LLM generation step: each
    query costs exactly ONE Mistral embedding call. Dense and hybrid share that
    single embedding, then reuse the REAL production fusion/filter helpers from
    ``rag_service`` (``_filter_dynamic_sources``, ``reciprocal_rank_fusion``,
    ``_merge_and_attach_rrf_scores``) so this check can never drift from what the
    live pipeline actually returns to a user.
  - Mistral free tier allows ~1 request/second; the loop throttles to <= 1
    call/sec (``THROTTLE_SECONDS``) IN ADDITION to the budget reservation, so a
    real run never trips HTTP 429.
  - ``MISTRAL_API_KEY`` transits ONLY via environment (read by settings); it is
    never interpolated into a log line, a print, or the output file.

The pure comparison helper ``compare_exact_term_recall`` has no I/O and no
network, so it is fully unit-tested (tests/unit/test_exact_term_check.py). The
real run against the ingested corpus is a separate, budget-consuming step
-- this module provides the tested helper plus a runnable
CLI entry point.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from collections.abc import Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent

# Mistral free-tier rate limit is ~1 request/second. Throttle the query loop
# below this ceiling so a real run never hits HTTP 429. This is on TOP of the
# budget_guard reservation, which bounds spend, not request rate.
THROTTLE_SECONDS = 1.1

_DEFAULT_QUERIES = _SCRIPT_DIR / "exact_term_queries.json"
_DEFAULT_OUT = _SCRIPT_DIR / "results" / "exact_term_check.json"


def compare_exact_term_recall(
    dense_hits: Sequence[Sequence[int]],
    hybrid_hits: Sequence[Sequence[int]],
    expected_doc_ids: Sequence[int],
) -> dict[str, Any]:
    """Compare dense vs hybrid exact-term recall (pure, no network).

    For each exact-term query, the query "hits" if its expected document_id is
    among the retrieved document_ids. Recall is the fraction of queries that hit,
    computed independently for the dense and the hybrid retrieval modes.

    ``no_regression`` is True iff ``hybrid_recall >= dense_recall`` over the whole
    query set -- i.e. adding the lexical BM25 signal never degrades exact-term
    retrieval (anti-regression guard). An empty query set is treated as a
    vacuous pass (no evidence of regression).

    Args:
        dense_hits: One list of retrieved document_ids per query, dense mode.
        hybrid_hits: One list of retrieved document_ids per query, hybrid mode.
            Must be the same length as ``dense_hits``.
        expected_doc_ids: The expected document_id for each query (same length).

    Returns:
        Dict with keys:
            no_regression: bool -- hybrid_recall >= dense_recall.
            dense_recall: float in [0, 1].
            hybrid_recall: float in [0, 1].
            per_query: list of per-query {expected_doc_id, dense_hit, hybrid_hit,
                dense_doc_ids, hybrid_doc_ids}.

    Raises:
        ValueError: If the three sequences do not share the same length.
    """
    if not (len(dense_hits) == len(hybrid_hits) == len(expected_doc_ids)):
        raise ValueError(
            "dense_hits, hybrid_hits and expected_doc_ids must have the same "
            f"length (got {len(dense_hits)}, {len(hybrid_hits)}, "
            f"{len(expected_doc_ids)})"
        )

    per_query: list[dict[str, Any]] = []
    dense_hit_count = 0
    hybrid_hit_count = 0

    for dense_ids, hybrid_ids, expected in zip(
        dense_hits, hybrid_hits, expected_doc_ids, strict=False
    ):
        dense_ids_list = [int(x) for x in dense_ids]
        hybrid_ids_list = [int(x) for x in hybrid_ids]
        expected_id = int(expected)

        dense_hit = expected_id in dense_ids_list
        hybrid_hit = expected_id in hybrid_ids_list
        dense_hit_count += int(dense_hit)
        hybrid_hit_count += int(hybrid_hit)

        per_query.append(
            {
                "expected_doc_id": expected_id,
                "dense_hit": dense_hit,
                "hybrid_hit": hybrid_hit,
                "dense_doc_ids": dense_ids_list,
                "hybrid_doc_ids": hybrid_ids_list,
            }
        )

    total = len(expected_doc_ids)
    # Empty set: recall is 0.0 and no_regression is a vacuous True.
    dense_recall = dense_hit_count / total if total else 0.0
    hybrid_recall = hybrid_hit_count / total if total else 0.0

    return {
        "no_regression": hybrid_recall >= dense_recall,
        "dense_recall": dense_recall,
        "hybrid_recall": hybrid_recall,
        "per_query": per_query,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    """CLI parser. Kept separate so ``--help`` needs no heavy imports."""
    parser = argparse.ArgumentParser(
        description=(
            "Vérifie l'absence de régression retrieval sur les requêtes à terme "
            "exact (dense vs hybride). Un appel embedding Mistral par "
            "requête, throttlé <= 1/s. N'affiche jamais MISTRAL_API_KEY."
        )
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=_DEFAULT_QUERIES,
        help=(
            'Fichier JSON: liste d\'objets {"query": str, "expected_doc_id": '
            "int} de requêtes à terme exact (identifiants/sigles du corpus)."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help="Chemin de sortie du résultat JSON de la vérification.",
    )
    return parser


def _load_exact_term_queries(path: Path) -> list[dict[str, Any]]:
    """Load exact-term queries from a JSON file (file I/O only, no network).

    Each item must carry a non-empty ``query`` string and an integer
    ``expected_doc_id``. Raises ValueError on a malformed file so a bad input
    fails loudly rather than silently checking nothing.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError(f"Exact-term queries file {path} must be a non-empty JSON list")
    queries: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict) or "query" not in item or "expected_doc_id" not in item:
            raise ValueError(f"Entry {index} of {path} must have 'query' and 'expected_doc_id'")
        query = str(item["query"]).strip()
        if not query:
            raise ValueError(f"Entry {index} of {path} has an empty 'query'")
        queries.append({"query": query, "expected_doc_id": int(item["expected_doc_id"])})
    return queries


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
    reached (fail-closed). The Mistral key is never logged here.
    """
    import numpy as np

    reservation = None
    if budget_guard is not None:
        reservation = budget_guard.reserve("embedding")
        if reservation is None:
            print("Budget quotidien atteint -- arrêt de la vérification.", file=sys.stderr)
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


def _dense_document_ids(question: str, embedding, vector_store, settings) -> list[int]:
    """Retrieve document_ids in DENSE mode, reusing the production filter.

    Mirrors the dense branch of ``_process_question_with_rag_stream`` (top_k = max
    sources x2, then ``_filter_dynamic_sources(mode="dense")``) so the collected
    document_ids match what the live dense pipeline would surface.
    """
    from mimir.services.rag_service import _filter_dynamic_sources

    search_results = vector_store.query(
        vector=embedding,
        top_k=settings.max_sources * 2,
        filter_dict=None,
    )
    if search_results:
        search_results = _filter_dynamic_sources(search_results, settings, question, mode="dense")
    return [int(r.document_id) for r in search_results]


def _hybrid_document_ids(question: str, embedding, vector_store, bm25_store, settings) -> list[int]:
    """Retrieve document_ids in HYBRID mode, reusing the production fusion+filter.

    Mirrors ``_hybrid_retrieve`` (raw dense pool at similarity_floor=0.0 + BM25
    pool, fused via RRF, merged, then ``_filter_dynamic_sources(mode="hybrid")``)
    without the generation step, so the collected document_ids match the live
    hybrid pipeline's sources.
    """
    from mimir.services.rag_service import (
        _HYBRID_POOL_SIZE,
        _filter_dynamic_sources,
        _merge_and_attach_rrf_scores,
    )
    from mimir.rag_core.fusion import reciprocal_rank_fusion

    dense_pool = vector_store.query(
        vector=embedding,
        top_k=_HYBRID_POOL_SIZE,
        filter_dict=None,
        similarity_floor=0.0,
    )
    lexical_pool = bm25_store.query(question, _HYBRID_POOL_SIZE)

    rank_lists = [
        [r.chunk_id for r in dense_pool],
        [chunk_id for chunk_id, _ in lexical_pool],
    ]
    fused_scores = reciprocal_rank_fusion(rank_lists, k=settings.rrf_k)
    search_results = _merge_and_attach_rrf_scores(dense_pool, [], fused_scores, vector_store)
    if search_results:
        search_results = _filter_dynamic_sources(search_results, settings, question, mode="hybrid")
    return [int(r.document_id) for r in search_results]


async def _run(
    queries: list[dict[str, Any]],
    *,
    llm_service,
    vector_store,
    bm25_store,
    budget_guard,
    usage_tracker,
    settings,
) -> dict[str, Any] | None:
    """Run the throttled dense+hybrid retrieval loop and compare recall.

    One embedding call per query (shared by both modes), throttled to
    <= 1 call/sec. Returns the comparison dict, or None if the budget cap was
    hit before any query completed.
    """
    dense_hits: list[list[int]] = []
    hybrid_hits: list[list[int]] = []
    expected_doc_ids: list[int] = []

    for index, item in enumerate(queries):
        # Throttle to stay under the Mistral free-tier 1 req/s ceiling.
        if index > 0:
            await asyncio.sleep(THROTTLE_SECONDS)

        embedding = await _embed_question(
            item["query"],
            llm_service=llm_service,
            budget_guard=budget_guard,
            usage_tracker=usage_tracker,
            session_id=f"exact-term-check-{index}",
        )
        if embedding is None:
            break  # Budget cap reached (fail-closed).

        # Dense and hybrid reuse the SAME embedding; only local (no-network) work
        # follows, so no extra throttle is needed between the two modes.
        dense_hits.append(_dense_document_ids(item["query"], embedding, vector_store, settings))
        hybrid_hits.append(
            _hybrid_document_ids(item["query"], embedding, vector_store, bm25_store, settings)
        )
        expected_doc_ids.append(int(item["expected_doc_id"]))

    if not expected_doc_ids:
        return None

    return compare_exact_term_recall(dense_hits, hybrid_hits, expected_doc_ids)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Heavy service imports are deferred past argument parsing
    so ``--help`` never imports FastAPI nor touches any secret."""
    args = _build_arg_parser().parse_args(argv)

    if not Path(args.queries).exists():
        print(
            f"Fichier de requêtes exact-term introuvable: {args.queries}\n"
            "Fournir un JSON de la forme "
            '[{"query": "JIRA-4521", "expected_doc_id": 12}, ...] tiré du corpus '
            "ingéré (identifiants/sigles).",
            file=sys.stderr,
        )
        return 1

    # Deferred imports: pulling these at module top would drag the backend
    # service stack in for a bare --help. Providers build the same singletons
    # the API uses.
    from mimir.config import settings
    from mimir.api.dependencies import (
        get_budget_guard,
        get_bm25_store,
        get_llm_service,
        get_usage_tracker,
        get_vector_store,
    )

    queries = _load_exact_term_queries(Path(args.queries))

    vector_store = get_vector_store()
    vector_store.load()
    bm25_store = get_bm25_store()

    result = asyncio.run(
        _run(
            queries,
            llm_service=get_llm_service(),
            vector_store=vector_store,
            bm25_store=bm25_store,
            budget_guard=get_budget_guard(),
            usage_tracker=get_usage_tracker(),
            settings=settings,
        )
    )

    if result is None:
        print("Aucune requête traitée (corpus vide ou budget atteint).", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"Exact-term check écrit: {out_path} "
        f"(dense_recall={result['dense_recall']:.3f}, "
        f"hybrid_recall={result['hybrid_recall']:.3f}, "
        f"no_regression={result['no_regression']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
