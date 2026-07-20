# Décision d'adoption — Chunking structure-aware (RAG-05, 07-06)

**Date:** 2026-07-14
**Décision:** **ADOPT** — `structure_aware_chunking_enabled` passe à `True`.

## Contexte de mesure

Même corpus gelé (`data/generated_documents/`) ré-ingéré deux fois (flag OFF = baseline, flag ON = structure-aware) et même golden set gelé (`golden_set_v1.jsonl`), juge Mistral `mistral-small-latest`, `RunConfig(max_workers=1)` (sériel, rate-limit-safe), température 0, sans cache. Métriques de retrieval : `context_recall` et `context_precision`.

## Résultats (preuves chiffrées)

| Métrique | Baseline (OFF) | Structure-aware (ON) | Delta absolu |
|----------|----------------|----------------------|--------------|
| context_recall | 0.7375 | 0.7625 | 0.0250 |
| context_precision | 0.5754 | 0.6174 | 0.0420 |
| taux de NaN (max) | 1.7% | 0.0% | — |

Sources : `chunk_baseline_run.json`, `chunk_structure_run.json`.

## Jugement d'adoption

Règle conservatrice (mirroir de l'adoption hybride) : adopter uniquement si les DEUX métriques de retrieval progressent (delta net > 0) ET si le taux de NaN reste acceptable (<= 20 %).

- Delta net positif sur les deux métriques : **True**
- Taux de NaN acceptable : **True** (baseline 1.7%, structure 0.0%)
- **Verdict : ADOPT.**

## Réversibilité (garde-fou moteur)

Le chemin de chunking reste **byte-identique** quand `structure_aware_chunking_enabled=False` (prouvé : `tests/unit/test_ingestion_chunking.py::TestStructureAwareChunking`). L'adoption est donc totalement réversible par un simple retour du flag à `False`.

