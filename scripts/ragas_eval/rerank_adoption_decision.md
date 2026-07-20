# Décision d'adoption — Reranking cross-encoder FlashRank (RAG-03, 07-05)

**Date:** 2026-07-14
**Décision:** **DO-NOT-ADOPT** — `rerank_enabled` reste `False`.

## Contexte de mesure

Même golden set gelé (`golden_set_v1.jsonl`) rejoué deux fois sur les **mêmes index FAISS + BM25 persistés** (le reranking est une opération au moment de la requête : aucune ré-ingestion) : **baseline = hybride (rerank OFF)** vs **hybride + rerank (rerank ON)**. Juge Mistral `mistral-small-latest`, `RunConfig(max_workers=1)` (sériel, rate-limit-safe), température 0, sans cache. Métriques de retrieval : `context_recall` et `context_precision` — le reranking réordonne le contexte récupéré, il n'affecte pas la génération.

## Résultats (preuves chiffrées)

| Métrique | Baseline (hybride) | Hybride + rerank | Delta absolu | Delta relatif |
|----------|--------------------|------------------|--------------|---------------|
| context_recall | 0.7625 | 0.7625 | 0.0000 | +0.0 % |
| context_precision | 0.6058 | 0.5946 | -0.0113 | -1.9 % |
| taux de NaN (max) | 1.7% | 0.0% | — | — |

**p95 latence rerank :** 42703.1323 ms (budget 500 ms, n=19 appels).

Sources : `rerank_baseline_run.json`, `rerank_multibert_run.json`, `rerank_latencies.json`.

## Jugement d'adoption

Règle conservatrice (mirroir de l'adoption hybride, phase 6) : adopter **uniquement** si les DEUX métriques de retrieval progressent (delta net > 0), si le taux de NaN reste acceptable (<= 20 %), ET si le p95 de la latence de reranking sur la **machine cible** reste dans le budget (500 ms).

- Delta net positif sur les deux métriques : **False**
- Taux de NaN acceptable : **True** (baseline 1.7%, rerank 0.0%)
- p95 dans le budget : **False** (p95=42703.1323 ms)
- **Verdict : DO-NOT-ADOPT.**

## Réversibilité (garde-fou moteur)

Le chemin de retrieval reste **byte-identique** quand `rerank_enabled=False` (prouvé : `tests/unit/test_rag_service_rerank.py::TestRerankPipelineIntegration::test_off_path_identical_to_pre_rerank_control` + suites `test_rag_service*.py` inchangées et vertes — aucune expansion de pool, aucun appel au reranker). De plus, tout timeout ou toute exception du reranker replie sur l'ordre pré-rerank (non fatal). L'adoption est donc totalement réversible par un simple retour du flag à `False`.

