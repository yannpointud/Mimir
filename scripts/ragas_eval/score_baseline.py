#!/usr/bin/env python
"""RAGAS pipeline stage 2/2 (RAG-01, venv SÉPARÉ): scores the baseline.

Why this exists: this is the SEPARATE-venv half of the two-stage RAGAS harness.
It reads ONLY ``eval_input.jsonl`` (produced by ``run_pipeline.py`` in the main
venv) and computes the four legacy ragas metrics with a Mistral judge, then
writes ``results/baseline_run_{N}.json`` carrying, per metric, the mean score
AND the NaN rate (overall + split on adversarial vs corpus questions).

VENV BOUNDARY (SACRED): this module imports NOTHING from the Mimir backend --
no ``from src...``, no ``from backend...``. Its only inputs are the JSONL file
and ``MISTRAL_API_KEY`` from the environment. This is what makes the separate
venv genuinely separate: it never installs the faiss/sqlalchemy/pydantic stack.

Rate-limit safety (Mistral free tier = 1 request/second HARD):
  - RAGAS fires judge/embedding calls CONCURRENTLY by default (max_workers=16),
    which WOULD trip the limit. ``RunConfig(max_workers=1)`` forces SERIAL
    execution, and its exponential-backoff retries absorb transient 429s. This
    makes a run slow-but-safe.
  - ``temperature=0`` on the judge maximizes real determinism WITHOUT a ragas
    cache: a cache would make two "identical" runs trivially equal and falsify
    the inter-run stability proof (Pitfall #4). No ``cache=`` is passed.

Security:
  - ``MISTRAL_API_KEY`` is read from the environment by ChatMistralAI /
    MistralAIEmbeddings; it is never interpolated into a log line or the output.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# The four legacy metrics required by the success criteria. context_recall and
# context_precision are the mandatory pair; faithfulness and answer_relevancy
# are included as they come cheaply from the same evaluate() batch.
_ALL_METRICS = ["context_recall", "context_precision", "faithfulness", "answer_relevancy"]

# Only these keys are forwarded to the ragas dataset; is_adversarial is kept
# aside (ragas would reject it as an unknown sample field) and re-attached to the
# per-row results by position for the adversarial-split NaN report.
_RAGAS_FIELDS = ("user_input", "response", "retrieved_contexts", "reference", "reference_contexts")

_DEFAULT_IN = Path(__file__).resolve().parent / "eval_input.jsonl"
_DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _read_eval_rows(path: Path) -> List[Dict[str, Any]]:
    """Read the newline-delimited JSON boundary file (blank lines tolerated)."""
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number} of {path}: {exc}") from exc
    return rows


def _resolve_metrics(names: List[str]):
    """Map metric names to ragas metric objects (imported lazily).

    Import is deferred so ``--help`` works without ragas installed. Raises a
    clear error naming an unknown metric rather than a bare KeyError.
    """
    from ragas.metrics import (  # noqa: E402
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    registry = {
        "context_recall": context_recall,
        "context_precision": context_precision,
        "faithfulness": faithfulness,
        "answer_relevancy": answer_relevancy,
    }
    resolved = []
    for name in names:
        if name not in registry:
            raise ValueError(
                f"Unknown metric '{name}'. Choose from: {', '.join(registry)}"
            )
        resolved.append(registry[name])
    return resolved


def _mean_ignoring_nan(values: List[float]) -> Optional[float]:
    """Mean of the non-NaN values, or None when every value is NaN."""
    clean = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _nan_rate(values: List[float]) -> float:
    """Fraction of NaN (or missing) entries in a column."""
    if not values:
        return 0.0
    nan_count = sum(1 for v in values if v is None or (isinstance(v, float) and math.isnan(v)))
    return nan_count / len(values)


def _summarize(
    df, metric_names: List[str], is_adversarial: List[bool]
) -> Dict[str, Any]:
    """Compute per-metric mean + NaN rate (overall / corpus / adversarial).

    Splitting the NaN rate on adversarial vs corpus questions is what lets a
    human tell a real judge-parsing bug (NaN concentrated on corpus questions)
    from expected abstention NaN (concentrated on out-of-corpus adversarials,
    ragas issue #733).

    Args:
        df: The ``result.to_pandas()`` dataframe.
        metric_names: Metric column names present in ``df``.
        is_adversarial: Per-row adversarial flags, aligned to df row order.

    Returns:
        A JSON-serializable summary dict.
    """
    corpus_idx = [i for i, adv in enumerate(is_adversarial) if not adv]
    adv_idx = [i for i, adv in enumerate(is_adversarial) if adv]

    per_metric: Dict[str, Any] = {}
    for name in metric_names:
        col = [float(v) for v in df[name].tolist()]
        corpus_col = [col[i] for i in corpus_idx]
        adv_col = [col[i] for i in adv_idx]
        per_metric[name] = {
            "mean": _mean_ignoring_nan(col),
            "nan_rate": _nan_rate(col),
            "nan_rate_corpus": _nan_rate(corpus_col),
            "nan_rate_adversarial": _nan_rate(adv_col),
        }
    return per_metric


def _build_arg_parser() -> argparse.ArgumentParser:
    """CLI parser. Kept separate so ``--help`` needs no ragas import."""
    parser = argparse.ArgumentParser(
        description=(
            "Score la baseline RAGAS depuis eval_input.jsonl (venv SÉPARÉ, zéro "
            "import Mimir). Juge Mistral, RunConfig(max_workers=1) (série, "
            "rate-limit-safe), sans cache. Rapporte moyenne + taux de NaN par "
            "métrique. MISTRAL_API_KEY via environnement, jamais loggée."
        )
    )
    parser.add_argument("--in", dest="in_path", type=Path, default=_DEFAULT_IN,
                        help="Chemin de eval_input.jsonl (entrée).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Chemin du JSON de résultats (défaut: results/baseline_run_{N}.json).")
    parser.add_argument("--run", type=int, default=1,
                        help="Numéro de run (utilisé pour le nom de fichier par défaut).")
    parser.add_argument("--metrics", type=str, default=",".join(_ALL_METRICS),
                        help="Liste de métriques séparées par des virgules.")
    parser.add_argument("--model", type=str, default="mistral-small-latest",
                        help="Modèle juge Mistral (chat).")
    parser.add_argument("--embedding-model", type=str, default="mistral-embed",
                        help="Modèle d'embeddings Mistral pour answer_relevancy.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point (separate venv). Heavy ragas/langchain imports deferred
    past argument parsing so ``--help`` works without the ragas venv."""
    args = _build_arg_parser().parse_args(argv)

    # WSL2 / broken-IPv6 workaround (opt-in via RAGAS_FORCE_IPV4=1): resolve every
    # hostname to IPv4 only. langchain-mistralai's async httpx client otherwise
    # prefers the AAAA (IPv6) records, which fail with EAI_AGAIN on hosts where
    # IPv6 is unreachable (api.mistral.ai publishes both A and AAAA, but WSL2 IPv6
    # is down here). Default behavior is unchanged when the flag is unset.
    if os.environ.get("RAGAS_FORCE_IPV4") == "1":
        import socket as _socket
        _orig_getaddrinfo = _socket.getaddrinfo

        def _getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
            return _orig_getaddrinfo(host, port, _socket.AF_INET, type, proto, flags)

        _socket.getaddrinfo = _getaddrinfo_ipv4_only

    # Self-sufficient key loading: if MISTRAL_API_KEY is not already exported,
    # load it from the project's backend/.env (the same source the backend
    # config uses). The key value is never logged. python-dotenv is a standalone
    # dependency, not a backend import, so the ragas venv stays backend-free.
    if not os.environ.get("MISTRAL_API_KEY"):
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parents[2] / "backend" / ".env")
        except ImportError:
            pass

    if not os.environ.get("MISTRAL_API_KEY"):
        # Fail fast with an actionable message; never echo the key itself.
        print("MISTRAL_API_KEY absente de l'environnement -- exportez-la avant de scorer.",
              file=sys.stderr)
        return 2

    metric_names = [m.strip() for m in args.metrics.split(",") if m.strip()]

    rows = _read_eval_rows(args.in_path)
    if not rows:
        print(f"Aucune ligne dans {args.in_path}.", file=sys.stderr)
        return 1

    # Keep the adversarial flags aside; strip everything but the ragas fields.
    is_adversarial = [bool(r.get("is_adversarial", False)) for r in rows]
    clean_rows = [{k: r.get(k) for k in _RAGAS_FIELDS} for r in rows]

    # Deferred imports (separate venv only) -- NOTHING from the Mimir backend.
    from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.run_config import RunConfig

    metrics = _resolve_metrics(metric_names)
    dataset = EvaluationDataset.from_list(clean_rows)

    # temperature=0: real determinism, NO ragas cache (Pitfall #4 -- a cache
    # would fake inter-run stability). The key is read from the environment.
    judge_llm = LangchainLLMWrapper(ChatMistralAI(model=args.model, temperature=0))
    judge_embeddings = LangchainEmbeddingsWrapper(MistralAIEmbeddings(model=args.embedding_model))

    # max_workers=1 => serial execution (never concurrent), the only safe mode
    # under the Mistral free-tier 1 req/s hard limit. Backoff retries absorb
    # transient 429s so a rate-limited judge degrades gracefully (slow-but-safe).
    run_config = RunConfig(max_workers=1)

    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=judge_llm,
        embeddings=judge_embeddings,
        run_config=run_config,
        raise_exceptions=False,  # NaN per row instead of aborting the whole run
    )

    df = result.to_pandas()
    per_metric = _summarize(df, metric_names, is_adversarial)

    out_path = args.out or (_DEFAULT_RESULTS_DIR / f"baseline_run_{args.run}.json")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "run": args.run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "judge_model": args.model,
        "embedding_model": args.embedding_model,
        "run_config": {"max_workers": 1, "cache": False, "temperature": 0},
        "n_samples": len(rows),
        "n_adversarial": sum(is_adversarial),
        "metrics": metric_names,
        "per_metric": per_metric,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Résultats écrits: {out_path}")
    for name, stats in per_metric.items():
        mean = stats["mean"]
        mean_str = f"{mean:.3f}" if mean is not None else "NaN"
        print(f"  {name}: mean={mean_str} nan_rate={stats['nan_rate']:.1%} "
              f"(corpus={stats['nan_rate_corpus']:.1%}, adv={stats['nan_rate_adversarial']:.1%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
