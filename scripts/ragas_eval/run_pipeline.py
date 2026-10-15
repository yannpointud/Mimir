#!/usr/bin/env python
"""RAGAS pipeline stage 1/2 (MAIN venv): answers the golden set.

Why this exists: the RAGAS baseline is measured in two strictly separated
stages joined by a JSONL boundary file. This script is the MAIN-venv stage: it
reads the frozen golden set, replays each question through the real
``RagService.answer_stream()`` pipeline drained to a full answer (dense-only by
default, off HTTP), and dumps ``eval_input.jsonl``. The SEPARATE venv (``score_baseline.py``) then
reads ONLY that file and computes the ragas metrics -- it imports nothing from
the Mimir backend.

Design constraints (Mistral free tier = 1 request/second HARD):
  - The answer loop throttles to <= 1 call/sec (``THROTTLE_SECONDS`` >= 1.1) IN
    ADDITION to reserving budget per call, so a real run never trips a 429 and
    never bypasses the daily budget cap (fail-closed).
  - ``MISTRAL_API_KEY`` transits ONLY via environment (read by settings); it is
    never interpolated into a log line, a print, or the output file.

Retrieval mode:
  - ``--retrieval-mode dense`` (default) measures the frozen dense-only baseline.
  - ``--retrieval-mode hybrid`` sets ``HYBRID_SEARCH_ENABLED`` in the environment
    BEFORE ``src.config`` is imported, so the same harness can later score the
    hybrid path without a code change. The baseline itself is dense.

Running the real answering pass consumes Mistral tokens and is a separate,
human-verified step -- this module provides the pure,
unit-tested building blocks plus the CLI entry point.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from collections.abc import Awaitable, Callable, Sequence

# sys.path bootstrap (same discipline as scripts/backup_sqlite.py and
# generate_golden_set.py): make the project root and the backend package
# importable whether this file is run as a script or imported as the package
# module scripts.ragas_eval.run_pipeline (unit tests).
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
_BACKEND_DIR = _PROJECT_ROOT / "backend"
for _path in (_PROJECT_ROOT, _BACKEND_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from scripts.ragas_eval.golden_set_schema import (  # noqa: E402
    GoldenSetEntry,
    load_golden_set,
)

# Mistral free-tier rate limit is ~1 request/second. Throttle the answer loop
# below this ceiling so a real run never hits HTTP 429. This is ON TOP of the
# budget_guard reservation, which bounds spend, not request rate.
THROTTLE_SECONDS = 1.1

_DEFAULT_GOLDEN = _SCRIPT_DIR / "golden_set" / "golden_set_v1.jsonl"
_DEFAULT_OUT = _SCRIPT_DIR / "eval_input.jsonl"

# Type of the injected answer function: (question, session_id) -> result dict,
# or None to signal budget exhaustion (stop the loop). Decoupling the loop from
# RagService/budget_guard keeps it unit-testable with a mocked async callable.
AnswerFn = Callable[[str, str], Awaitable[dict[str, Any] | None]]


async def answer_via_stream(
    rag_service,
    *,
    question: str,
    session_id: str,
    document_repository,
    reservation,
    context_limit: int,
) -> dict[str, Any]:
    """Drain ``RagService.answer_stream()`` into an ``answer()``-shaped result dict.

    The runtime serves answers as SSE events, but the eval harness needs the
    whole answer at once. This collects the stream into the
    ``{answer, sources, confidence_score, session_id}`` shape
    ``_assemble_eval_row`` consumes: ``answer`` is the concatenation of every
    ``chunk`` event's content, and ``sources`` come from the terminal ``done``
    event (which carries the same ``chunk_text``-bearing source dicts the old
    non-stream path returned). An ``error`` event yields an empty answer with no
    sources -- ``_assemble_eval_row`` tolerates a missing ``sources`` list.

    ``answer_stream()`` settles the reservation internally (finalize/release),
    exactly as the removed ``answer()`` did, so the caller's budget accounting
    is unchanged.

    Args:
        rag_service: The injected ``RagService`` singleton.
        question: The golden set question to answer.
        session_id: Per-question session id (distinct per call).
        document_repository: Script-scoped repository for filename lookups.
        reservation: The budget reservation captured before the call.
        context_limit: Maximum number of context documents.

    Returns:
        A ``RagService.answer()``-shaped result dict.
    """
    answer_parts: list[str] = []
    sources: list[dict[str, Any]] = []
    confidence_score = 0.0
    async for event in rag_service.answer_stream(
        question=question,
        context_limit=context_limit,
        include_sources=True,
        session_id=session_id,
        document_repository=document_repository,
        reservation=reservation,
    ):
        event_type = event.get("type")
        if event_type == "chunk":
            answer_parts.append(event.get("content", ""))
        elif event_type == "done":
            sources = event.get("sources", [])
            confidence_score = event.get("confidence_score", 0.0)
        elif event_type == "error":
            break
    return {
        "answer": "".join(answer_parts),
        "sources": sources,
        "confidence_score": confidence_score,
        "session_id": session_id,
    }


def _assemble_eval_row(entry: GoldenSetEntry, result: dict[str, Any]) -> dict[str, Any]:
    """Map a golden set entry + a RagService result to a ragas eval row (pure).

    The output shape is the JSONL boundary contract consumed by
    ``score_baseline.py``: the four ragas fields (``user_input``, ``response``,
    ``retrieved_contexts``, ``reference``) plus ``reference_contexts`` (for
    context_recall) and ``is_adversarial`` (kept so the scorer can split the NaN
    rate on out-of-corpus questions, which legitimately NaN -- ragas issue #733).

    ``result`` is defensive: a missing/empty ``sources`` list yields an empty
    ``retrieved_contexts`` rather than raising, so an error-fallback answer still
    produces a valid row.

    Args:
        entry: One validated ``GoldenSetEntry`` from the frozen golden set.
        result: A ``RagService`` result dict (``answer`` + ``sources``).

    Returns:
        A JSON-serializable eval row.
    """
    sources = result.get("sources") or []
    retrieved_contexts = [s["chunk_text"] for s in sources if "chunk_text" in s]
    return {
        "user_input": entry.user_input,
        "response": result.get("answer", ""),
        "retrieved_contexts": retrieved_contexts,
        "reference": entry.reference,
        "reference_contexts": list(entry.reference_contexts),
        "is_adversarial": entry.is_adversarial,
    }


def _write_eval_rows(rows: Sequence[dict[str, Any]], path: Path) -> None:
    """Write eval rows as newline-delimited JSON (the venv boundary file).

    One compact JSON object per line, UTF-8, ``ensure_ascii=False`` so French
    text stays readable. Creates the parent directory if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


async def _collect_eval_rows(
    entries: Sequence[GoldenSetEntry],
    answer_fn: AnswerFn,
    *,
    throttle_seconds: float,
) -> list[dict[str, Any]]:
    """Replay each entry through ``answer_fn``, throttled, assembling eval rows.

    Throttles to <= 1 call/sec between questions (never before the first) so a
    real run stays under the Mistral free-tier ceiling. An ``answer_fn`` result
    of ``None`` signals budget exhaustion and stops the loop cleanly (rows
    collected so far are kept).

    Args:
        entries: Golden set entries to answer (already sliced by ``--limit``).
        answer_fn: Async callable (question, session_id) -> result dict | None.
        throttle_seconds: Inter-call delay; 0 disables it (tests only).

    Returns:
        The assembled eval rows, in entry order.
    """
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if index > 0 and throttle_seconds > 0:
            await asyncio.sleep(throttle_seconds)
        session_id = f"ragas-eval-{index}"
        result = await answer_fn(entry.user_input, session_id)
        if result is None:
            # Budget exhausted (or explicit stop) -- keep what we have.
            break
        rows.append(_assemble_eval_row(entry, result))
    return rows


def _build_arg_parser() -> argparse.ArgumentParser:
    """CLI parser. Kept separate so ``--help`` needs no heavy imports."""
    parser = argparse.ArgumentParser(
        description=(
            "Rejoue le golden set gelé à travers RagService.answer_stream() (venv "
            "principal) et écrit eval_input.jsonl pour le scoring RAGAS. "
            "Throttle <= 1 appel/s + réserve le budget par appel. "
            "N'affiche jamais MISTRAL_API_KEY."
        )
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=("dense", "hybrid"),
        default="dense",
        help="dense (défaut, baseline gelée) ou hybrid (met HYBRID_SEARCH_ENABLED avant l'import config).",
    )
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=_DEFAULT_GOLDEN,
        help="Chemin du golden set JSONL gelé (source).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help="Chemin de sortie de eval_input.jsonl (frontière entre venvs).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="N'answer que les N premières questions (conservation de tokens / smoke-test).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Heavy backend imports (and the settings singleton, which reads the Mistral
    key from the environment) are deferred past argument parsing so ``--help``
    never imports FastAPI nor touches any secret. When ``--retrieval-mode
    hybrid`` is requested, ``HYBRID_SEARCH_ENABLED`` is exported BEFORE
    ``src.config`` is imported so the flag is picked up by pydantic settings.
    """
    args = _build_arg_parser().parse_args(argv)

    import os

    # Toggle the hybrid flag BEFORE importing src.config: pydantic BaseSettings
    # reads it at import time (case-insensitive). Default dense leaves the env
    # untouched so the frozen baseline is measured on the dense-only path.
    if args.retrieval_mode == "hybrid":
        os.environ["HYBRID_SEARCH_ENABLED"] = "true"

    # Deferred imports: pulling these at module top would drag FastAPI in for a
    # bare --help. Providers build the same singletons the API uses.
    from src.api.dependencies import (  # noqa: E402
        get_budget_guard,
        get_bm25_store,
        get_rag_service,
        get_vector_store,
    )
    from src.config import settings  # noqa: E402
    from src.database.connection import db_manager  # noqa: E402
    from src.database.repository import DocumentRepository  # noqa: E402

    entries = load_golden_set(args.golden_set)
    if args.limit is not None:
        entries = entries[: max(0, args.limit)]
    if not entries:
        print("Golden set vide (ou --limit 0) -- rien à faire.", file=sys.stderr)
        return 1

    # Load persisted indexes once (mirror generate_golden_set.py). In hybrid
    # mode get_bm25_store() loads the lexical index; dense mode never uses it.
    vector_store = get_vector_store()
    vector_store.load()
    if args.retrieval_mode == "hybrid":
        get_bm25_store()

    rag_service = get_rag_service()
    budget_guard = get_budget_guard()

    async def _run() -> list[dict[str, Any]]:
        # One synchronous session for the whole run: document_repository is
        # request-scoped in the API but here a single script-scoped session is
        # fine (read-only lookups of document filenames).
        with db_manager.get_session_context() as session:
            document_repository = DocumentRepository(session)

            async def answer_fn(question: str, session_id: str):
                # Reserve budget BEFORE the call (fail-closed): a None
                # reservation means the daily cap is reached -> stop the loop.
                reservation = budget_guard.reserve("chat")
                if reservation is None:
                    print("Budget quotidien atteint -- arrêt du pipeline.", file=sys.stderr)
                    return None
                # answer_stream() settles the reservation internally
                # (finalize/release); answer_via_stream drains it into the
                # answer()-shaped dict the eval rows consume.
                return await answer_via_stream(
                    rag_service,
                    question=question,
                    session_id=session_id,
                    document_repository=document_repository,
                    reservation=reservation,
                    context_limit=settings.max_sources,
                )

            return await _collect_eval_rows(entries, answer_fn, throttle_seconds=THROTTLE_SECONDS)

    rows = asyncio.run(_run())
    _write_eval_rows(rows, args.out)

    adversarial = sum(1 for r in rows if r.get("is_adversarial"))
    print(
        f"eval_input écrit: {args.out} ({len(rows)} lignes, {adversarial} "
        f"adversariales, mode={args.retrieval_mode})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
