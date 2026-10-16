# ADR 0003 — Évaluation RAG hors ligne avec RAGAS

## Statut

Acceptée

## Contexte

- Les choix de retrieval, comme la recherche hybride ou le découpage selon la structure du document, modifient la qualité des réponses d'une façon que les tests unitaires ne mesurent pas.
- Une mesure de qualité RAG fait appel à un LLM juge. Elle est payante, lente et non déterministe. Les scripts supposent le débit du palier gratuit de Mistral, environ une requête par seconde.
- La bibliothèque `ragas` entraîne des dépendances lourdes (langchain, datasets, pandas) qui entrent en conflit avec la pile du backend (faiss-cpu, sqlalchemy, pydantic).

## Décision

- **Jeu de référence gelé et versionné** : `scripts/ragas_eval/golden_set/golden_set_v1.jsonl` compte 60 entrées, dont 9 adversariales (hors corpus).
  - Schéma strict `GoldenSetEntry` : `user_input`, `reference`, `reference_contexts`, `is_adversarial`.
  - Bornes contrôlées par `validate_golden_set` : 50 à 200 entrées, au moins une adversariale.
  - Le jeu est généré synthétiquement par `generate_golden_set.py` à partir de chunks actifs de FAISS, via `MistralAPIService` sous réservation budgétaire. `ragas.testset.TestsetGenerator` n'est pas utilisé.
- **Deux étapes, deux environnements virtuels, reliées par un fichier JSONL** :
  1. `run_pipeline.py` s'exécute dans le venv principal. Il rejoue chaque question à travers le vrai `RagService.answer_stream()` (vidé par `answer_via_stream`) et écrit `eval_input.jsonl`. L'option `--retrieval-mode hybrid` exporte `HYBRID_SEARCH_ENABLED=true` avant l'import de la configuration ; `--retrieval-mode dense` (défaut) laisse l'environnement inchangé.
  2. `score_baseline.py` s'exécute dans un venv séparé (`requirements-ragas.txt` : `ragas==0.4.3`, `langchain-mistralai==0.2.4`). Il n'importe rien du backend et écrit par défaut `results/baseline_run_{N}.json`.
- **Métriques** : `context_recall`, `context_precision`, `faithfulness` et `answer_relevancy` (option `--metrics`). Les décisions de retrieval ne retiennent que les deux premières.
- **Juge** : `mistral-small-latest` à température 0, embeddings `mistral-embed`, `RunConfig(max_workers=1)` (exécution en série), sans cache, avec `raise_exceptions=False`. Chaque métrique est rapportée avec sa moyenne globale et son taux de NaN (global, questions du corpus, questions adversariales).
- **Garde-fous d'exécution** : 1,1 s d'attente entre appels (`THROTTLE_SECONDS`) et une réservation `budget_guard` par question. L'arrêt est propre lorsque le plafond est atteint (voir ADR 0001).
- **Contrôles ciblés complémentaires** :
  - `exact_term_check.py` : retrieval seul, dense et hybride, sur 5 requêtes à terme exact ;
  - `calibrate_rrf_threshold.py` : distribution des scores RRF, sans modifier `config.py` ;
  - `measure_chunking.py` : ré-ingestion du corpus dans des répertoires de données isolés, une fois par mode.
- **Hors CI.** Le workflow `.github/workflows/ci.yml` exécute ruff, mypy, pytest et pip-audit, mais aucun script d'évaluation ni aucun appel à Mistral. Seules les fonctions pures sont testées : `tests/unit/test_golden_set_schema.py`, `test_run_pipeline.py`, `test_exact_term_check.py`.

## Conséquences

Positives
- Chaque changement de retrieval est validé par une mesure chiffrée avant d'être activé par défaut :
  - `hybrid_search_enabled` (40 questions du corpus) : voir ADR 0002 ;
  - `structure_aware_chunking_enabled` (60 questions, dont 9 adversariales) : `context_precision` 0,5754 → 0,6174 et `context_recall` 0,7375 → 0,7625 (`results/chunk_baseline_run.json`, `chunk_structure_run.json`).
- La mesure passe par le vrai pipeline, sans HTTP, et respecte le plafond de dépense.
- Les dépendances d'évaluation n'entrent jamais dans l'image du backend.

Négatives
- Aucune détection automatique de régression : un changement qui dégrade la qualité passe la CI tant que les tests unitaires restent verts.
- Le même fournisseur génère le jeu de référence, sert de juge et produit les réponses évaluées, ce qui crée un biais possible.
- Les échantillons sont petits (40 ou 60 questions, un seul run par configuration). Les résultats valent pour le corpus de test, pas pour un corpus de production, et la stabilité d'un run à l'autre n'est pas mesurée.
- Les runs sont longs (exécution en série) et coûteux en tokens.
- Depuis que `hybrid_search_enabled` vaut `True` par défaut, `run_pipeline.py --retrieval-mode dense` ne mesure le chemin dense que si `HYBRID_SEARCH_ENABLED=false` est défini (environnement ou `.env`) : sinon il rejoue le mode hybride.
- `rerank_adoption_decision.md` cite des fichiers de résultats (`rerank_*.json`) absents de `results/`, et aucun code de reranking n'est présent dans `backend/mimir` : ses chiffres ne sont pas vérifiables dans le dépôt.

## Où dans le code

- `scripts/ragas_eval/run_pipeline.py` : `answer_via_stream`, `_assemble_eval_row`, `_collect_eval_rows`, `THROTTLE_SECONDS`
- `scripts/ragas_eval/score_baseline.py` : `_ALL_METRICS`, `_summarize`, `main`
- `scripts/ragas_eval/golden_set_schema.py` : `GoldenSetEntry`, `load_golden_set`, `validate_golden_set`, `ADVERSARIAL_REFERENCE`
- `scripts/ragas_eval/generate_golden_set.py`, `exact_term_check.py`, `calibrate_rrf_threshold.py`, `measure_chunking.py`
- `scripts/ragas_eval/requirements-ragas.txt` ; résultats dans `scripts/ragas_eval/results/`
- `backend/mimir/services/rag_service.py` : `RagService.answer_stream` (point d'entrée commun à l'API et à l'évaluation)
