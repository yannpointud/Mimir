# Avancement de la mission

Consigne : `docs/cleanup/MISSION.md`. Décisions : `docs/cleanup/DECISIONS.md`.

| Passe | État | Tentatives | Dernier commit poussé |
| --- | --- | --- | --- |
| 0. Oracle | réussie | 1 | `8abe5a3` docs(cleanup): track progress after pass 0 |
| 1. Lint | réussie | 1 | `7501847` docs(cleanup): record pass 1 decisions and progress |
| 2. Erreurs | réussie | 1 | `c5362df` docs(cleanup): record pass 2 decisions and progress |
| 3. Architecture | en cours | 1 | `e8190d5` refactor(rag): split the streaming pipeline into named steps |
| 4. Typage | à faire | 0 | |
| 5. Commentaires | à faire | 0 | |
| 6. Tests | à faire | 0 | |
| 7. Dépendances | à faire | 0 | |
| 8. Façade | à faire | 0 | |

## Dernière porte franchie (passe 2)

1045 tests (1042 réussis, 3 ignorés), couverture 85,35 %, ruff 0, format OK,
radon D+ 5, mypy 131, pip-audit OK, vitest 141, build OK, `/health/live` 200.
`except Exception` dans le backend : 65, tous annotés et justifiés.

## Passe 3 en cours

Fait et poussé : interfaces `AbstractVectorStore` (similarity_floor,
get_corpus_version, snapshot_active_chunks), Protocol `LexicalIndex`,
`AbstractLLMService.generate_stream`/`close` ; `RagService` typé sur ces
interfaces ; `_process_question_with_rag_stream` découpé en étapes nommées
(radon A/B, plus de noqa C901 sur cette fonction).

Reste : les 7 handlers de plus de 100 lignes vers des services (fusion des deux
uploads), puis les autres fonctions D+ ou en noqa C901
(`MistralAPIService.generate_stream`, `VectorStoreValidator._analyze_inconsistencies`,
`FaissVectorStore.clean_orphans`, `logs_reader._apply_filters`, `main.lifespan`,
`log_parser.get_errors_last_hour`).

Prochaine étape : terminer la passe 3, puis porte de qualité.
