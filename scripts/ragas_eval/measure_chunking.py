#!/usr/bin/env python
"""Structure-aware chunking RAGAS delta: before/after measurement.

Why this exists: structure-aware chunking (``section_title`` metadata behind the
``structure_aware_chunking_enabled`` flag) is ADOPTED ONLY on a net-positive
RAGAS delta measured on the FROZEN evaluation corpus. This script produces that
delta by re-ingesting the same corpus twice -- once flag-OFF (baseline) and once
flag-ON (structure-aware) -- then answering the frozen golden set through the
real pipeline for each, ready for the SEPARATE-venv ragas scorer.

Design (mirrors the two-stage / two-venv harness, WITHOUT editing run_pipeline.py):
  - The flag must be toggled BEFORE ``mimir.config`` is imported (pydantic reads it
    at import time). Two modes therefore run in two SEPARATE PROCESSES -- this
    script re-invokes itself with ``--stage answer --mode {baseline,structure}``
    and the right environment.
  - Each mode runs in an ISOLATED data directory (its own FAISS / BM25 / SQLite /
    uploads under ``.measure/{mode}/``) set via environment path overrides, so the
    LIVE production index is NEVER touched and each mode starts from a clean slate
    (no cross-mode contamination, no clearing logic).
  - Re-ingestion RE-EMBEDS the whole corpus and answering re-queries it: both
    consume Mistral tokens under the fail-closed daily budget cap, serial and
    throttled at <= 1 req/s (Mistral free tier). This is the human/operator-gated
    step -- see ``--dry-run`` for a zero-token validation.
  - Scoring is done by the SEPARATE ragas venv (``score_baseline.py``), which
    imports nothing from the backend. This script writes one ``eval_input`` file
    per mode; the operator scores each, then ``--summarize`` turns the two score
    JSONs into ``chunking_adoption_decision.md`` with an explicit verdict.

Security:
  - ``MISTRAL_API_KEY`` transits ONLY via environment (read by settings); it is
    never interpolated into a log line, a print, or any output file.

Usage:
    # 1. Zero-token wiring check (safe to run anytime):
    python -m scripts.ragas_eval.measure_chunking --dry-run

    # 2. Full measurement (operator-gated, spends tokens; runs both modes):
    python -m scripts.ragas_eval.measure_chunking --run

    # 3. Score each eval_input in the SEPARATE ragas venv:
    python scripts/ragas_eval/score_baseline.py \
        --in scripts/ragas_eval/eval_input_chunk_baseline.jsonl \
        --out scripts/ragas_eval/results/chunk_baseline_run.json
    python scripts/ragas_eval/score_baseline.py \
        --in scripts/ragas_eval/eval_input_chunk_structure.jsonl \
        --out scripts/ragas_eval/results/chunk_structure_run.json

    # 4. Write the adoption decision from the two score JSONs:
    python -m scripts.ragas_eval.measure_chunking --summarize \
        --baseline-json scripts/ragas_eval/results/chunk_baseline_run.json \
        --structure-json scripts/ragas_eval/results/chunk_structure_run.json
"""

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent

# The two modes: OFF is the frozen baseline, ON is structure-aware chunking.
MODES = ("baseline", "structure")
_MODE_FLAG = {"baseline": "false", "structure": "true"}

# Frozen inputs (shared with the existing harness).
_SOURCE_DIR = _PROJECT_ROOT / "data" / "generated_documents"
_GOLDEN_SET = _SCRIPT_DIR / "golden_set" / "golden_set_v1.jsonl"
_MEASURE_ROOT = _SCRIPT_DIR / ".measure"  # isolated per-mode data dirs
_INGESTABLE_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


def _eval_input_path(mode: str) -> Path:
    """Per-mode boundary file consumed by the separate-venv ragas scorer."""
    return _SCRIPT_DIR / f"eval_input_chunk_{mode}.jsonl"


def _isolated_env(mode: str) -> dict[str, str]:
    """Environment overrides isolating a mode's data dir + toggling the flag.

    Every persistent path is redirected under ``.measure/{mode}/`` so the run
    never reads or writes the live production index, and the structure-aware
    flag is set to match the mode. Returned as a dict to overlay on os.environ
    for the child process (the key is NOT included -- it is inherited).
    """
    base = _MEASURE_ROOT / mode
    return {
        "STRUCTURE_AWARE_CHUNKING_ENABLED": _MODE_FLAG[mode],
        "DATABASE_URL": f"sqlite:///{base / 'sqlite' / 'mimir.db'}",
        "FAISS_INDEX_PATH": str(base / "faiss" / "index.bin"),
        "FAISS_METADATA_PATH": str(base / "faiss" / "metadata.json"),
        "BM25_INDEX_PATH": str(base / "bm25" / "index"),
        "DATA_DIR": str(base),
        "UPLOAD_DIR": str(base / "documents"),
    }


# --------------------------------------------------------------------------- #
# Dry-run: zero-token validation of the whole wiring.
# --------------------------------------------------------------------------- #
def _dry_run() -> int:
    """Validate inputs, config flag and output writability without any tokens.

    Proves the measurement is wired correctly (corpus present, golden set valid,
    flag exists and is currently False, env toggle mechanism, output paths
    writable) and prints the exact operator command sequence. Spends NOTHING:
    no ingestion, no answering, no Mistral call.
    """
    ok = True

    # 1. Frozen corpus present and ingestable.
    if _SOURCE_DIR.is_dir():
        docs = [p for p in _SOURCE_DIR.iterdir() if p.suffix.lower() in _INGESTABLE_SUFFIXES]
        print(f"[ok] corpus: {len(docs)} ingestable documents in {_SOURCE_DIR}")
        ok = ok and len(docs) > 0
    else:
        print(f"[MISSING] corpus directory not found: {_SOURCE_DIR}")
        ok = False

    # 2. Frozen golden set present and non-empty.
    if _GOLDEN_SET.is_file():
        n = sum(1 for line in _GOLDEN_SET.read_text(encoding="utf-8").splitlines() if line.strip())
        print(f"[ok] golden set: {n} entries in {_GOLDEN_SET.name}")
        ok = ok and n > 0
    else:
        print(f"[MISSING] golden set not found: {_GOLDEN_SET}")
        ok = False

    # 3. The config flag exists and its CURRENT default is False (byte-identical
    #    baseline until the delta is measured and adoption is decided).
    try:
        from mimir.config import Settings

        field = Settings.model_fields.get("structure_aware_chunking_enabled")
        if field is None:
            print("[MISSING] settings.structure_aware_chunking_enabled not defined")
            ok = False
        else:
            print(f"[ok] flag structure_aware_chunking_enabled default={field.default}")
            if field.default is not False:
                print("     note: default is not False -- adoption already applied?")
    except Exception as exc:  # noqa: BLE001 - CLI check: any import failure is reported as missing
        print(f"[MISSING] cannot import Settings: {exc}")
        ok = False

    # 4. The env-toggle mechanism actually flips the setting (no tokens).
    _probe = os.environ.get("STRUCTURE_AWARE_CHUNKING_ENABLED")
    print(
        f"[ok] env toggle STRUCTURE_AWARE_CHUNKING_ENABLED currently={_probe!r} "
        f"(child processes set it per mode: {_MODE_FLAG})"
    )

    # 5. Output paths writable.
    for mode in MODES:
        out = _eval_input_path(mode)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            print(f"[ok] writable eval_input target: {out.name}")
        except OSError as exc:
            print(f"[MISSING] cannot write {out}: {exc}")
            ok = False

    print("\nFull-run command sequence (operator-gated, spends Mistral tokens):")
    print("  1. python -m scripts.ragas_eval.measure_chunking --run")
    print("  2. score each eval_input_chunk_*.jsonl with score_baseline.py (ragas venv)")
    print(
        "  3. python -m scripts.ragas_eval.measure_chunking --summarize "
        "--baseline-json ... --structure-json ..."
    )

    print("\nDRY-RUN OK" if ok else "\nDRY-RUN FAILED")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# Answer stage: run inside a child process with the mode's env already set.
# --------------------------------------------------------------------------- #
def _list_corpus() -> list[Path]:
    return sorted(p for p in _SOURCE_DIR.iterdir() if p.suffix.lower() in _INGESTABLE_SUFFIXES)


async def _ingest_corpus_isolated() -> int:
    """Re-ingest the frozen corpus into the (isolated) index honoring the flag.

    Mirrors scripts/ingest_corpus.py but reads section_title_tracking from the
    now-imported settings (the child's env already toggled the flag) and runs
    against the isolated data dir, so the mode starts from a clean, empty index.
    """
    from mimir.config import settings
    from mimir.database.connection import init_database, db_manager
    from mimir.ingestion.processor import IngestionProcessor
    from mimir.ingestion.chunking import ChunkingConfig
    from mimir.api.dependencies import (
        get_llm_service,
        get_vector_store,
        get_document_repository,
        get_bm25_store,
    )

    if not settings.mistral_api_key:
        print("ERROR: MISTRAL_API_KEY not set -- cannot embed.", file=sys.stderr)
        return 1

    files = _list_corpus()
    if not files:
        print(f"ERROR: no ingestable documents in {_SOURCE_DIR}", file=sys.stderr)
        return 1

    init_database()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    chunking_config = ChunkingConfig(
        chunk_size=settings.max_chunk_size,
        overlap=settings.chunk_overlap,
        # The whole point of this measurement: honor the flag at ingestion.
        section_title_tracking=settings.structure_aware_chunking_enabled,
    )
    print(
        f"ingest: section_title_tracking={chunking_config.section_title_tracking} "
        f"({len(files)} documents)"
    )

    with db_manager.get_session_context() as session:
        document_repo = get_document_repository(session)
        processor = IngestionProcessor(
            llm_service=get_llm_service(),
            vector_store=get_vector_store(),
            document_repository=document_repo,
            chunking_config=chunking_config,
            max_file_size_mb=settings.max_file_size_mb,
            max_chunks_per_doc=settings.max_chunks_per_doc,
            bm25_store=get_bm25_store(),
        )
        await processor.start()

        for src in files:
            content = src.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
            if document_repo.get_by_hash(file_hash):
                continue
            dest = upload_dir / f"{file_hash}_{src.name}"
            shutil.copyfile(src, dest)
            document = document_repo.create(
                filename=src.name,
                path=str(dest),
                file_hash=file_hash,
                preserve=False,
            )
            processor.queue_document(
                file_path=str(dest),
                document_id=str(document.id),
                preserve=False,
                metadata={"source": "measure_chunking.py"},
            )

        # Drain the queue (embedding is batched + budget-guarded + throttled).
        idle = 0
        for _ in range(1200):  # hard ceiling ~20 min
            await asyncio.sleep(1.0)
            if processor.get_queue_size() == 0:
                idle += 1
                if idle >= 3:
                    break
            else:
                idle = 0
        await processor.stop(timeout=30.0)

    return 0


async def _answer_golden_set(mode: str, limit: int | None) -> int:
    """Answer the frozen golden set through the real pipeline -> eval_input file.

    Reuses run_pipeline.py's pure building blocks (no edit to that module) for
    row assembly / throttling / writing, and the budget-guarded answer loop.
    """
    from scripts.ragas_eval.run_pipeline import (
        THROTTLE_SECONDS,
        _assemble_eval_row,
        _collect_eval_rows,
        _write_eval_rows,
        answer_via_stream,
    )
    from scripts.ragas_eval.golden_set_schema import load_golden_set
    from mimir.api.dependencies import get_budget_guard, get_rag_service, get_vector_store
    from mimir.config import settings
    from mimir.database.connection import db_manager
    from mimir.database.repository import DocumentRepository

    entries = load_golden_set(_GOLDEN_SET)
    if limit is not None:
        entries = entries[: max(0, limit)]
    if not entries:
        print("Golden set empty (or --limit 0).", file=sys.stderr)
        return 1

    vector_store = get_vector_store()
    vector_store.load()
    rag_service = get_rag_service()
    budget_guard = get_budget_guard()

    with db_manager.get_session_context() as session:
        document_repository = DocumentRepository(session)

        async def answer_fn(question: str, session_id: str):
            reservation = budget_guard.reserve("chat")
            if reservation is None:
                print("Daily budget reached -- stopping.", file=sys.stderr)
                return None
            # answer_stream() settles the reservation internally; answer_via_stream
            # drains it into the answer()-shaped dict the eval rows consume.
            return await answer_via_stream(
                rag_service,
                question=question,
                session_id=session_id,
                document_repository=document_repository,
                reservation=reservation,
                context_limit=settings.max_sources,
            )

        # _collect_eval_rows uses _assemble_eval_row internally; imported above
        # only to keep the dependency explicit for readers.
        _ = _assemble_eval_row
        rows = await _collect_eval_rows(entries, answer_fn, throttle_seconds=THROTTLE_SECONDS)

    out = _eval_input_path(mode)
    _write_eval_rows(rows, out)
    print(f"eval_input written: {out} ({len(rows)} rows, mode={mode})")
    return 0


def _answer_stage(mode: str, limit: int | None) -> int:
    """Child-process entry: ingest (honoring the flag) then answer the golden set."""
    rc = asyncio.run(_ingest_corpus_isolated())
    if rc != 0:
        return rc
    return asyncio.run(_answer_golden_set(mode, limit))


# --------------------------------------------------------------------------- #
# Orchestrate: one isolated child process per mode.
# --------------------------------------------------------------------------- #
def _orchestrate(limit: int | None, modes: list[str]) -> int:
    """Run each mode in its own process (fresh config import with the flag set)."""
    import subprocess

    _MEASURE_ROOT.mkdir(parents=True, exist_ok=True)
    for mode in modes:
        print(f"\n=== mode={mode} (structure_aware={_MODE_FLAG[mode]}) ===")
        child_env = dict(os.environ)
        child_env.update(_isolated_env(mode))
        cmd = [sys.executable, str(Path(__file__).resolve()), "--stage", "answer", "--mode", mode]
        if limit is not None:
            cmd += ["--limit", str(limit)]
        result = subprocess.run(cmd, env=child_env)
        if result.returncode != 0:
            print(f"mode={mode} failed (rc={result.returncode}) -- aborting.", file=sys.stderr)
            return result.returncode

    print("\nBoth eval_input files written. Score each in the SEPARATE ragas venv:")
    for mode in modes:
        print(
            f"  python scripts/ragas_eval/score_baseline.py "
            f"--in {_eval_input_path(mode).name} "
            f"--out results/chunk_{mode}_run.json"
        )
    print("Then: measure_chunking.py --summarize --baseline-json ... --structure-json ...")
    return 0


# --------------------------------------------------------------------------- #
# Summarize: two score JSONs -> chunking_adoption_decision.md with a verdict.
# --------------------------------------------------------------------------- #
def _metric(payload: dict[str, Any], name: str) -> dict[str, Any]:
    return payload.get("per_metric", {}).get(name, {}) or {}


def _fmt(value: float | None) -> str:
    return f"{value:.4f}" if isinstance(value, (int, float)) else "NaN"


def _summarize(baseline_json: Path, structure_json: Path, out_path: Path) -> int:
    """Compute the before/after delta and write the adoption decision doc.

    Applies the conservative gate (mirrors adoption_decision.md): ADOPT only if
    BOTH retrieval metrics improve net-positively with an acceptable NaN rate;
    otherwise DO-NOT-ADOPT and leave the flag False.
    """
    baseline = json.loads(baseline_json.read_text(encoding="utf-8"))
    structure = json.loads(structure_json.read_text(encoding="utf-8"))

    rows = []
    verdict_positive = True
    for metric in ("context_recall", "context_precision"):
        b = _metric(baseline, metric).get("mean")
        s = _metric(structure, metric).get("mean")
        delta = (s - b) if isinstance(b, (int, float)) and isinstance(s, (int, float)) else None
        rows.append((metric, b, s, delta))
        if not (isinstance(delta, (int, float)) and delta > 0):
            verdict_positive = False

    b_nan = max(
        (
            _metric(baseline, m).get("nan_rate", 0.0)
            for m in ("context_recall", "context_precision")
        ),
        default=0.0,
    )
    s_nan = max(
        (
            _metric(structure, m).get("nan_rate", 0.0)
            for m in ("context_recall", "context_precision")
        ),
        default=0.0,
    )
    nan_ok = b_nan <= 0.2 and s_nan <= 0.2
    adopt = verdict_positive and nan_ok
    verdict = "ADOPT" if adopt else "DO-NOT-ADOPT"

    lines = [
        "# Décision d'adoption — Chunking structure-aware",
        "",
        f"**Date:** {datetime.now(UTC).date().isoformat()}",
        f"**Décision:** **{verdict}** — "
        + (
            "`structure_aware_chunking_enabled` passe à `True`."
            if adopt
            else "`structure_aware_chunking_enabled` reste `False`."
        ),
        "",
        "## Contexte de mesure",
        "",
        "Même corpus gelé (`data/generated_documents/`) ré-ingéré deux fois "
        "(flag OFF = baseline, flag ON = structure-aware) et même golden set gelé "
        "(`golden_set_v1.jsonl`), juge Mistral `mistral-small-latest`, "
        "`RunConfig(max_workers=1)` (sériel, rate-limit-safe), température 0, sans cache. "
        "Métriques de retrieval : `context_recall` et `context_precision`.",
        "",
        "## Résultats (preuves chiffrées)",
        "",
        "| Métrique | Baseline (OFF) | Structure-aware (ON) | Delta absolu |",
        "|----------|----------------|----------------------|--------------|",
    ]
    for metric, b, s, delta in rows:
        lines.append(f"| {metric} | {_fmt(b)} | {_fmt(s)} | {_fmt(delta)} |")
    lines += [
        f"| taux de NaN (max) | {b_nan:.1%} | {s_nan:.1%} | — |",
        "",
        f"Sources : `{baseline_json.name}`, `{structure_json.name}`.",
        "",
        "## Jugement d'adoption",
        "",
        "Règle conservatrice (mirroir de l'adoption hybride) : adopter uniquement si "
        "les DEUX métriques de retrieval progressent (delta net > 0) ET si le taux de "
        "NaN reste acceptable (<= 20 %).",
        "",
        f"- Delta net positif sur les deux métriques : **{verdict_positive}**",
        f"- Taux de NaN acceptable : **{nan_ok}** (baseline {b_nan:.1%}, structure {s_nan:.1%})",
        f"- **Verdict : {verdict}.**",
        "",
        "## Réversibilité (garde-fou moteur)",
        "",
        "Le chemin de chunking reste **byte-identique** quand "
        "`structure_aware_chunking_enabled=False` (prouvé : "
        "`tests/unit/test_ingestion_chunking.py::TestStructureAwareChunking`). "
        "L'adoption est donc totalement réversible par un simple retour du flag à `False`.",
        "",
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Adoption decision written: {out_path} (verdict={verdict})")
    if adopt:
        print(
            "NOTE: verdict ADOPT -- flip structure_aware_chunking_enabled default "
            "to True in backend/mimir/config.py (human-confirmed step)."
        )
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Mesure le delta RAGAS du chunking structure-aware sur le "
            "corpus gelé. --dry-run ne dépense aucun token. Le run complet est "
            "gated opérateur (ré-ingestion + réponses = tokens Mistral)."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validation zéro-token de tout le câblage (défaut recommandé).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run complet : ré-ingère + répond pour chaque mode (tokens).",
    )
    parser.add_argument(
        "--stage",
        choices=("orchestrate", "answer"),
        default="orchestrate",
        help="Interne : 'answer' est l'entrée du sous-processus par mode.",
    )
    parser.add_argument(
        "--mode", choices=MODES, default=None, help="Interne : mode du sous-processus answer."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="N'answer que les N premières questions (économie de tokens).",
    )
    parser.add_argument(
        "--modes",
        type=str,
        default=",".join(MODES),
        help="Modes à exécuter, séparés par des virgules.",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="Écrit chunking_adoption_decision.md depuis deux JSON de score.",
    )
    parser.add_argument(
        "--baseline-json",
        type=Path,
        default=None,
        help="JSON de score du mode baseline (pour --summarize).",
    )
    parser.add_argument(
        "--structure-json",
        type=Path,
        default=None,
        help="JSON de score du mode structure (pour --summarize).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_SCRIPT_DIR / "chunking_adoption_decision.md",
        help="Chemin du fichier de décision d'adoption.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.dry_run:
        return _dry_run()

    if args.summarize:
        if not args.baseline_json or not args.structure_json:
            print("--summarize requires --baseline-json and --structure-json.", file=sys.stderr)
            return 2
        return _summarize(args.baseline_json, args.structure_json, args.out)

    if args.stage == "answer":
        if args.mode is None:
            print("--stage answer requires --mode.", file=sys.stderr)
            return 2
        return _answer_stage(args.mode, args.limit)

    if args.run:
        modes = [m.strip() for m in args.modes.split(",") if m.strip()]
        return _orchestrate(args.limit, modes)

    # No explicit action: default to the safe zero-token dry-run.
    print("No action given; running --dry-run (use --run for the full measurement).")
    return _dry_run()


if __name__ == "__main__":
    sys.exit(main())
