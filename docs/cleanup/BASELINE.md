# État initial (passe 0)

Mesures prises sur `main` au commit `b1e18e6` (« merge: python 3.13 (#2) »),
point de départ de la mission, marqué localement par le tag `pre-cleanup`
(voir DECISIONS.md : le push du tag a été refusé par le proxy git de la
session).

Environnement de mesure : Python 3.13.16, Node 22.22.0, npm 10.9.4.
Variables forcées pour toutes les mesures : `MISTRAL_API_KEY=test-key`,
`JWT_SECRET_KEY` aléatoire de 32 caractères, `ENVIRONMENT=test`,
`MISTRAL_MODEL` non défini.

## Avant l'oracle (code de `main` inchangé)

| Mesure | Résultat |
| --- | --- |
| pytest | 1013 tests : 1010 réussis, 0 échec, 3 ignorés |
| Couverture (`backend/src`) | 82,91 % |
| vitest | 14 fichiers, 141 tests réussis |
| Build front (`npm run build`) | OK (avertissement de taille de chunk Vite, préexistant) |
| ruff, configuration actuelle (`F`, `E9`) | 4 erreurs, toutes F401 |
| ruff `--select B,SIM,UP,BLE,C90` | 1059 alertes (détail ci-dessous) |
| radon `cc -n D backend/src` | 5 fonctions notées D ou pire |
| mypy `backend/src` (mode normal, mypy 2.4.0) | 132 erreurs dans 23 fichiers |
| pip-audit (2 exclusions de la CI) | aucune vulnérabilité, 4 entrées ignorées |
| `except Exception` dans `backend/src` | 181 |
| Handlers de plus de 100 lignes | 7 |
| Endpoints en `response_model=Dict` | 17 |

Écart avec les ordres de grandeur annoncés : mypy compte 132 erreurs dans
23 fichiers (126 dans 22 annoncées) ; la différence vient de la version de
mypy (2.4.0 ici). Les autres mesures sont identiques.

### Détail ruff (règles candidates)

```
356 UP006  non-pep585-annotation        33 SIM117 multiple-with-statements
181 BLE001 blind-except                 24 UP015  redundant-open-modes
162 UP045  non-pep604-annotation-opt.   19 C901   complex-structure (seuil 10)
 96 B008   function-call-in-default     5 B007, B017, B905, SIM115
 84 UP035  deprecated-import             4 SIM105, UP043
 56 B904   raise-without-from            3 SIM102, SIM118
                                          2 SIM103, SIM114, UP007, UP017, UP041, UP042
                                          1 SIM300, UP012
```

Avec `max-complexity = 15`, six fonctions dépassent le seuil C901 :
`lifespan` (main.py), `MistralAPIService.generate_stream`,
`FaissVectorStore.clean_orphans`, `VectorStoreValidator._analyze_inconsistencies`,
`_process_question_with_rag_stream`, `get_errors_last_hour` (log_parser).

### radon (D ou pire)

```
services/rag_service.py         _process_question_with_rag_stream        E (34)
llm_interface/.../mistral_api.py MistralAPIService.generate_stream       D (22)
rag_core/.../validation_utils.py VectorStoreValidator._analyze_inconsistencies E (34)
rag_core/.../faiss_store.py     FaissVectorStore.clean_orphans           D (28)
utils/logs_reader.py            _apply_filters                           D (24)
```

### mypy (par code d'erreur)

45 assignment, 32 arg-type, 9 misc, 7 union-attr, 7 operator, 6 valid-type,
6 import-untyped (cachetools, bm25s, docx, markdown, faiss, psutil),
5 return-value, 5 index, 4 var-annotated, 3 attr-defined, 2 call-overload,
1 str-bytes-safe.

### pip-audit sans exclusion

```
pytest 7.4.3   PYSEC-2026-1845  (corrigé en 9.0.3)
orjson 3.10.18 PYSEC-2026-107   (corrigé en 3.11.5 / 3.11.6)
```

### Handlers de plus de 100 lignes

| Handler | Lignes |
| --- | --- |
| `chat.chat_stream` | 189 |
| `documents.upload_document` | 172 |
| `admin.admin_upload_document` | 162 |
| `admin.rebuild_vector_store` | 150 |
| `documents.delete_document` | 136 |
| `documents.validate_vector_store_consistency` | 120 |
| `documents.get_document_with_chunks` | 104 |

## Après l'ajout de l'oracle (fin de passe 0)

| Mesure | Résultat |
| --- | --- |
| pytest | 1045 tests : 1042 réussis, 0 échec, 3 ignorés |
| Couverture | 84,59 % |
| Oracle + intégration | 186 tests réussis |
| ruff (config actuelle) | 4 erreurs (F401), l'oracle n'en ajoute aucune |
| radon D ou pire | 5 |
| mypy | 132 |
| pip-audit | OK |
| vitest / build | 141 tests / OK |
| venv vierge + uvicorn + `GET /api/v1/health/live` | 200 |

## L'oracle (`tests/oracle/`)

Tests de caractérisation gelés par `docs/cleanup/ORACLE.sha256` (avec
`tests/integration/`). Tout est hermétique : base SQLite, index FAISS et BM25
et dossier d'upload temporaires, LLM factice déterministe (embeddings « sac de
mots » hachés en SHA-256, réponse streamée dérivée d'un hachage du prompt
reçu), garde budgétaire et suivi d'usage factices. Les valeurs volatiles
(horodatages, durées, jetons, identifiants générés, chemins temporaires) sont
neutralisées avant comparaison avec les instantanés de `tests/oracle/snapshots/`.

| Fichier | Ce qu'il fige |
| --- | --- |
| `test_openapi_contract.py` | (a) chemins, méthodes, tags, paramètres, corps de requête, codes de statut, sécurité ; schémas de réponse exclus |
| `test_api_responses.py` | (b) JSON et codes HTTP des endpoints health, auth, documents, admin, chat annexes |
| `test_failure_responses.py` | (b) codes et messages client quand un collaborateur échoue (dépôts, index, file d'ingestion) |
| `test_chat_stream_events.py` | (c) séquence SSE complète pour 10 questions fixes, rejeu du cache, événements d'erreur |
| `test_retrieval_ranking.py` | (d) ids et ordre des résultats denses et hybrides (store et pipeline) pour les 10 questions |
| `test_ingestion_chunks.py` | (e) ingestion PDF, DOCX, TXT, MD : nombre, texte et métadonnées des chunks |

## Porte de qualité

`bash docs/cleanup/quality_gate.sh <dossier>` exécute toutes les vérifications
et écrit les métriques dans `<dossier>/metrics.env` :

1. `sha256sum -c docs/cleanup/ORACLE.sha256` ;
2. pytest complet (total, échecs, couverture), puis `tests/oracle` et
   `tests/integration` seuls ;
3. ruff (`check` et `format --check`), radon, mypy, pip-audit (exclusions
   lues dans `scripts/local_ci.sh`) ;
4. `npm ci`, `npx vitest run`, `npm run build` ;
5. venv vierge, `pip install -r requirements.txt`, démarrage d'uvicorn,
   `GET /api/v1/health/live` doit renvoyer 200.

Les critères relatifs (nombre de tests −5 % au plus, couverture −1 point au
plus, aucune nouvelle alerte ruff, mypy ou pip-audit) se comparent aux
métriques de la passe précédente.
