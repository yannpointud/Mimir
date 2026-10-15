# Décisions de la mission de nettoyage

Chaque choix non trivial est consigné ici, avec l'option la plus conservatrice
retenue quand plusieurs étaient possibles.

## Passe 0 : oracle

### D0.1 Tag `pre-cleanup` non poussé

Le tag `pre-cleanup` a été posé localement sur `main` (`b1e18e6`, « merge:
python 3.13 (#2) »), mais le proxy git de la session refuse tout push de tag
(HTTP 403 sur `refs/tags/pre-cleanup`, alors que le push de branche
fonctionne). Conformément à la politique de l'environnement, aucun
contournement n'a été tenté. Le commit de référence est `b1e18e6` ; le tag se
pose à la main :

```
git tag pre-cleanup b1e18e6 && git push origin pre-cleanup
```

### D0.2 PR #2 bien mergée

`main` contient le merge de la PR #2 (Python 3.13) : la mission travaille en
Python 3.13.

### D0.3 Conception de l'oracle

- **Embeddings factices.** Un premier essai en « sac de mots » pur donnait des
  cosinus inférieurs au seuil dense de 0,5 : le mode dense ne renvoyait jamais
  rien et l'oracle ne le couvrait pas. L'embedding factice combine donc une
  direction commune (40 % de la norme) et le sac de mots sans mots vides, ce
  qui donne des classements denses variés (seuil franchi ou non, filtrage
  dynamique, pré-inclusion par nom de fichier, contexte vide).
- **LLM factice.** La réponse streamée contient un hachage du prompt système et
  de la question : toute modification de l'assemblage du contexte (ordre,
  numérotation, gabarit) change l'instantané.
- **Valeurs volatiles.** Neutralisées par clé (horodatages, jetons, durées,
  identifiants générés) et par motif (dates ISO, chemins temporaires, « Completed
  in N ms »). Les listes construites depuis un `set` Python (extensions
  supportées) sont triées, leur ordre dépendant de la graine de hachage.
- **Données dépendantes de la machine.** `system-info`, `disk-usage`, statistiques
  de cache : seule la structure (clés et types) est figée. Endpoints lisant les
  fichiers de logs (`/admin/logs`, `/admin/metrics/chat`, `/admin/analytics/usage`) :
  seules les clés de premier niveau sont figées.
- **Isolation.** Le `db_manager` global est redirigé vers une base temporaire,
  comme le font déjà les tests d'intégration ; les singletons de service sont
  remplacés par `app.dependency_overrides` ; l'application tourne sans son
  lifespan. Les réglages modifiés sont restaurés à la fin de chaque test.
- **Chemins d'erreur.** `test_failure_responses.py` injecte des collaborateurs
  défaillants pour figer les codes et messages renvoyés au client sur les
  chemins 500/503, que la passe 2 va retravailler.
- **Points d'entrée figés.** L'oracle utilise, en plus de l'API HTTP : les
  constructeurs de `RagService`, `IngestionProcessor`, `FaissVectorStore`,
  `Bm25LexicalStore`, les fonctions `get_*` de `src.api.dependencies`,
  `FaissVectorStore.query/snapshot_active_chunks`, `Bm25LexicalStore.query`,
  `RagService.answer_stream` et l'appel `rag_debug.log_vector_search(search_results=...)`.
  Ces points d'entrée sont conservés dans les passes suivantes.
- **Somme SHA256.** `ORACLE.sha256` couvre tous les fichiers de
  `tests/oracle/` (code, corpus, fixtures binaires, instantanés) et de
  `tests/integration/`, hors `__pycache__`.

### D0.4 Anomalies existantes découvertes et figées (non corrigées)

La mission interdit tout changement fonctionnel ; ces comportements sont donc
figés tels quels par l'oracle :

1. `PATCH /api/v1/documents/{id}/preserve` renvoie toujours 500 (« Failed to
   update document preservation status ») : le handler appelle
   `DocumentRepository.update_preserve_status`, qui n'existe pas.
2. `POST /api/v1/admin/documents/upload` ne vérifie pas l'extension du fichier
   (un `.exe` est accepté puis échoue à l'ingestion), contrairement à
   `POST /api/v1/documents/upload`. La fusion des deux uploads (passe 3) doit
   conserver cette différence.
3. La métadonnée `uploaded_by` vaut toujours `"unknown"` : le handler lit
   `current_user["username"]`, clé absente du jeton (qui porte `sub`).
4. Plusieurs logs JSON sont perdus quand un chemin d'ingestion est un `Path`
   (non sérialisable) : `task_queued`, `task_processing`, `task_completed`,
   `pipeline_completed` et les logs d'extraction. Seul le log de
   `IngestionProcessor.queue_document` est corrigé (passe 2), seule correction
   autorisée par la mission.
5. En mémoire, la métadonnée `source` d'un chunk ingéré par upload reste un
   `Path` (elle devient une chaîne après rechargement de l'index).

### D0.5 Script de porte de qualité versionné

La porte de qualité est automatisée dans `docs/cleanup/quality_gate.sh` pour
être rejouable par un relecteur. Les exclusions pip-audit sont lues dans
`scripts/local_ci.sh`, déjà synchronisé avec la CI.

## Passe 1 : lint

### D1.1 Dossiers gelés hors de ruff

`tests/oracle` et `tests/integration` sont dans `extend-exclude`, avec
`force-exclude = true` : ni `ruff check`, ni `--fix`, ni `ruff format` ne les
touchent, même passés explicitement en argument. Conséquence : l'une des
4 F401 initiales (`AsyncMock` inutilisé dans
`tests/integration/test_hybrid_delete_sync.py`) reste en place, ce fichier
étant gelé par `ORACLE.sha256` depuis la passe 0. Les trois autres sont
corrigées.

### D1.2 Règles ignorées

- `B008` (appels dans les valeurs par défaut) : idiome `Depends()`/`Query()`
  de FastAPI, conformément à la consigne.
- `UP042` (`(str, Enum)` vers `StrEnum`) : ce n'est pas une simple mise à jour
  de syntaxe, `str()` et `format()` des membres changent (« DocumentStatus.PENDING »
  devient « pending »), ce qui modifierait des messages de log.

### D1.3 Suppressions `noqa` existantes nettoyées

Le code contenait 122 `# noqa: F401` et quelques `F541`, `F841`, `F811` qui
masquaient des imports morts, des f-strings sans variable et des variables
inutilisées. Les commentaires ont été retirés et les corrections appliquées ;
aucun test ne dépendait de ces imports. Les expressions sans effet laissées
par l'autofix F841 (`datetime.utcnow()` seul, etc.) ont été supprimées.

### D1.4 B904 corrigé dès la passe 1

Seuls C901 et BLE001 peuvent être mis en baseline ; les 56 `raise` sans `from`
dans un `except` reçoivent donc `from <exception>` (le handler est nommé `exc`
quand il ne l'était pas). Effet limité à `__cause__` : aucune réponse HTTP ne
change.

### D1.5 Choix conservateurs pour les autres règles

- `B905` : `zip(..., strict=False)`, comportement identique (`strict=True`
  lèverait une exception sur des longueurs différentes).
- `SIM117` : les `with` imbriqués deviennent un `with (...)` parenthésé.
- `SIM102`, `SIM103`, `SIM105`, `SIM114`, `SIM118`, `B007`, `B017` : réécritures
  équivalentes ; `B017` remplace `pytest.raises(Exception)` par
  `pytest.raises(HTTPException)` dans un test unitaire.

### D1.6 Baseline BLE001 et C901

Après B904, les handlers qui relancent l'exception ne sont plus signalés par
BLE001 : 118 `noqa: BLE001` (et non 170) et 5 `noqa: C901`
(`clean_orphans` est repassé sous le seuil après la fusion SIM102). Les
passes 2 et 3 les retirent.

### D1.7 CI

Nouveau job `ruff` bloquant (`ruff check .` et `ruff format --check .`) ;
`scripts/local_ci.sh` exécute aussi `ruff format --check .`.

## Passe 2 : erreurs

### D2.1 Familles d'exceptions métier

`backend/src/shared/errors.py` définit `MimirError` et quatre familles :
`IngestionError`, `RetrievalError`, `LLMError`, `BudgetExceeded`. Les
exceptions existantes y sont rattachées sans changer de nom (elles sont
importées par les tests gelés) : `LLMException` hérite de `LLMError`,
`VectorStoreException` de `RetrievalError`, `ExtractionError` et
`ProcessingError` d'`IngestionError`. `BudgetExceededError` reste importable
depuis `src.cost.budget_guard` comme alias de `BudgetExceeded`.

### D2.2 Traduction HTTP

`main.py` enregistre deux handlers : `BudgetExceeded` vers le 429
`budget_exceeded` (le même que la route de chat, construit par
`src/api/responses.py`) et `MimirError` vers la même réponse 500 que le
handler générique. Aucune route ne laisse aujourd'hui s'échapper une
exception métier : ces handlers ne changent aucune réponse existante. La
route de chat continue de *renvoyer* son 429 plutôt que de lever
`BudgetExceeded`, sinon slowapi n'ajouterait plus ses en-têtes `X-RateLimit-*`
à cette réponse.

### D2.3 Ce qui reste en `except Exception`

65 `except Exception` restent dans le backend (contre 188 avec `main.py`),
tous annotés `# noqa: BLE001 - <raison>` et accompagnés d'un log :

| Raison | Nombre |
| --- | --- |
| Frontière API (route : erreur inattendue vers 500 générique, échec de file vers 500) | 30 |
| Sonde de santé (tout échec rapporté comme composant en mauvaise santé) | 8 |
| Effet de bord « au mieux » dans une route ou imposé par un test gelé | 6 |
| Worker d'ingestion | 5 |
| Portée de transaction SQLAlchemy (rollback puis relance) | 4 |
| Démarrage et arrêt de l'application (lifespan) | 5 |
| Thread de l'observateur de fichiers | 2 |
| Stream SSE | 2 |
| Décorateur transparent, handler de log d'alerte, authentification « fail closed » | 3 |

Les six « au mieux » sont des cas où l'oracle ou un test gelé fixe le
comportement face à une exception quelconque : récupération des chunks dans
la vue lecteur, extraction du contenu, retrait de l'index lors d'une
suppression, liste des documents avant un rebuild, journal d'audit des
événements d'authentification (oracle `test_failure_responses.py`), et
sauvegarde avant nettoyage des orphelins (`tests/integration/test_orphan_cleanup.py`
injecte une `Exception` brute).

> Note (FIN) : ce décompte est dépassé. La revue a montré que plusieurs
> rétrécissements changeaient un repli ; ces sites sont de nouveau en
> `except Exception` (180 dans le backend, voir DF.1 à DF.6).

### D2.4 Exceptions précises ailleurs

Les modules internes capturent désormais des types précis : erreurs
d'infrastructure des index (`INDEX_BACKEND_ERRORS` dans
`rag_core/interfaces.py`), `SQLAlchemyError`, `OSError`, erreurs de
bibliothèques (`pypdf.errors.PyPdfError`, `docx.opc.exceptions.OpcError`,
`aiosmtplib.SMTPException`, `jwt.PyJWTError`, `pwdlib.exceptions.PwdlibError`,
`jinja2.TemplateError`, `aiohttp.ClientError`) ou les familles métier. Les
chemins qui relançaient en enveloppant une exception métier le font toujours
(mêmes messages), et `raise ... from e` est systématique.

> Note (FIN) : ces listes surestimaient ce qu'un site peut recevoir (pypdf,
> bm25s, `np.load` lèvent aussi `ZeroDivisionError`, `EOFError`,
> `AssertionError`...). Les sites concernés sont revenus à `except Exception`
> et les tuples `INDEX_BACKEND_ERRORS`, `_PARSER_ERRORS`, `_PAYLOAD_ERRORS`,
> `_READ_ERRORS`, `_ENTRY_ERRORS` et `_SOURCE_ERRORS` sont retirés (DF.1).

### D2.5 Code mort retiré au passage

Trois fonctions sans aucun appelant, dont la seule raison d'être des
`except Exception` était défensive : `create_validation_report`
(`validation_utils.py`), `get_performance_status` (`log_parser.py`) et les
`try/except` des agrégateurs de `log_parser.py` et `logs_reader.py` dont le
corps ne peut pas lever (calculs sur des valeurs déjà protégées).

> Note (FIN) : faux pour les agrégateurs, dont les appelés avaient été
> rétrécis (une ligne JSON qui n'est pas un objet donnait un 500) ; leurs
> `try/except` sont rétablis (DF.4). Les deux fonctions mortes restent supprimées.

### D2.6 Tests unitaires adaptés

Plusieurs tests unitaires injectaient une `Exception` brute dans des
collaborateurs pour vérifier un `except Exception`. Ils injectent maintenant
l'exception réelle du contrat (`PdfReadError`, `PackageNotFoundError`,
`OperationalError`, `SMTPConnectError`, `TemplateError`, `InvalidKeyError`,
`RuntimeError`, `OSError`, `VectorStoreOperationError`, `ValueError` « already
exists »). Un test importait `VectorStoreOperationError` via le chemin
`backend.src` (double import du même module) : il passe par `src`. Deux tests
qui n'affirmaient rien (`assert True` dans les deux branches, `pytest.fail` dans
un `except`) affirment désormais le comportement attendu.

> Note (FIN) : ces adaptations masquaient des changements de comportement.
> Les injections d'origine (`Exception`, `RuntimeError`) sont rétablies (DF.7).

### D2.7 Correction autorisée

`IngestionProcessor.queue_document` journalise `str(file_path)` : les routes
d'upload passent un `Path`, que le formateur JSON ne sait pas sérialiser, et
l'enregistrement `document_queued` était perdu. Vérifié avant/après : plus de
« Logging error » sur ce log. Les autres logs perdus pour la même raison
(voir D0.4) ne sont pas corrigés.

### D2.8 Module `file_watcher`

`FileWatcher` n'est branché nulle part dans l'application (seuls ses tests
unitaires l'utilisent), bien que `CLAUDE.md` le décrive. Il est conservé tel
quel (option conservatrice), avec ses exceptions resserrées.

### D2.9 Test intermittent

Un échec isolé (1 test sur 1045) est apparu une fois pendant la passe, non
reproduit sur quatre exécutions complètes suivantes ; la porte a été franchie
sans relance.

## Passe 3 : architecture

### D3.1 Interfaces de rag_core et llm_interface

`AbstractVectorStore` déclare désormais ce que `RagService` et les routes
utilisent réellement : `query(..., similarity_floor=...)`,
`get_corpus_version()` et `snapshot_active_chunks()`. Le store BM25
n'implémente pas `AbstractVectorStore` (il est interrogé en texte brut et
reconstruit d'un bloc) : il reçoit un `Protocol` `LexicalIndex`
(`rebuild`, `query`, `load`). `AbstractLLMService` déclare `generate_stream`
(abstrait), `close()` (sans effet par défaut) et la signature réelle de
`embed(texts, session_id, rag_debug)`. `RagService` et les étapes du pipeline
sont typés sur ces interfaces plutôt que sur les implémentations FAISS, BM25
et Mistral.

### D3.2 Pipeline RAG en étapes nommées

`_process_question_with_rag_stream` (radon E 34, `noqa: C901`) est découpé en
étapes : `_embed_question`, `_pre_include_by_filename`, `_retrieve`,
`_build_context`, `_build_prompt`, `_stream_answer` (fermé par
`contextlib.aclosing` pour que l'usage soit enregistré avant le règlement de
la réservation), `_cache_answer`, et `_QuestionSpend` pour le suivi des
dépenses. La fusion hybride lit les métadonnées actives via
`snapshot_active_chunks()` (copies prises sous le verrou FAISS) au lieu de
parcourir `FaissVectorStore.metadata` : mêmes entrées non supprimées, oracle
hybride inchangé ; le mock d'un test unitaire hybride a été adapté en
conséquence. Le point d'entrée `RagService.answer_stream` et l'appel
`rag_debug.log_vector_search(search_results=...)` sur les candidats avant
filtrage sont conservés.

### D3.3 Services créés et traduction HTTP

La logique des sept handlers de plus de 100 lignes passe dans des services de
`backend/src/services/`, sans dépendance à FastAPI :

| Handler | Lignes avant | Lignes après | Service |
| --- | --- | --- | --- |
| `chat.chat_stream` | 186 | 56 | `chat_stream.py` |
| `documents.upload_document` | 168 | 47 | `document_upload.py` |
| `admin.admin_upload_document` | 161 | 57 | `document_upload.py` |
| `admin.rebuild_vector_store` | 148 | 33 | `index_maintenance.py` |
| `documents.delete_document` | 142 | 48 | `document_deletion.py`, `index_maintenance.py` |
| `documents.validate_vector_store_consistency` | 127 | 44 | `index_maintenance.py` |
| `documents.get_document_with_chunks` | 111 | 21 | `document_reader.py` |

(décorateurs, signature et docstring compris). Un service refuse une requête
en levant `RequestRejectedError` (`services/errors.py`), qui porte le code
HTTP (`http.HTTPStatus`, bibliothèque standard) et le message client ; la
route le traduit en `HTTPException` identique via `rejection_to_http`
(`api/responses.py`). Les `except Exception` de frontière (500 génériques
propres à chaque route, messages inchangés) restent dans les routes ; les
« au mieux » déplacés gardent leur annotation `noqa: BLE001`. Les handlers
entre 60 et 100 lignes (`reprocess_document`, `login`, `get_audit_log`...)
ne sont pas visés par la mission et restent tels quels.

Points d'entrée gelés conservés : `rebuild_vector_store(current_user=,
audit_repo=, vector_store=, bm25_store=, document_repo=)` et
`delete_document(document_id=, force=, current_user=, doc_repo=, audit_repo=,
vector_store=, bm25_store=)` gardent leurs noms, paramètres et effets (FAISS
optimisé puis BM25 reconstruit depuis `snapshot_active_chunks()`, ids des
documents existants pris dans le dépôt injecté).

### D3.4 Fusion des deux uploads

`DocumentUpload` porte le pipeline commun (nom, taille, lecture, doublon,
écriture préfixée par le hachage, enregistrement, mise en file avec rollback
sur file pleine) ; `UploadPolicy` exprime les différences observables, toutes
conservées (figées par l'oracle, D0.4) :

- message 400 du nom invalide : « Invalid filename » contre « Invalid file
  type or filename » ;
- contrôle d'extension seulement sur `/documents/upload` (l'admin accepte un
  `.exe`) ;
- log d'avertissement de doublon et audit `document_upload` seulement sur
  `/documents/upload` (l'audit est écrit avant la mise en file, comme avant) ;
  le log « Document uploaded successfully » reste dans cette route ;
- côté admin : contrôles du nom et de la taille hors du `try` (avant
  l'ouverture de la session), session obtenue par `next(get_db_session())`
  et fermée en `finally`, répertoire d'upload créé avant la lecture du
  fichier (même précédence d'erreur qu'avant), fichier stocké supprimé sur
  erreur inattendue (« Upload failed »), réponse en `dict` ;
- côté documents : 500 « Document upload failed », réponse `DocumentResponse`.

503 file pleine (suppression forcée de l'enregistrement puis du fichier) et
500 « Failed to queue document for processing » sont communs. Seule
différence interne : côté admin, `sanitize_filename` est appelée juste après
`validate_filename` au lieu d'après la création du répertoire (fonction pure,
sans effet observable). Les imports différés de la route admin
(`get_db_session`, `DocumentRepository`) sont gardés : les tests unitaires
les remplacent dans leur module d'origine. Les routes construisent la
politique à partir de leur propre `settings`, que les tests unitaires
remplacent aussi.

### D3.5 Flux SSE du chat

`services/chat_stream.py` contient `ChatStream.events` (l'ancien
`generate_sse`), `ReservationSettlement` (l'ancien drapeau `settled` partagé
entre le générateur et la `BackgroundTask`, avec `release_if_unsettled`
synchrone exécutée dans le pool de threads de Starlette), `convert_numpy_types`,
`generate_session_id` et `SSE_HEADERS`. Ordre des événements, JSON
(`json.dumps` des mêmes dictionnaires, mêmes clés dans le même ordre),
rejeu du cache (libération puis chunk, citation, done, produits un par un),
`finally` de règlement et retour (non levé) de `budget_exceeded_response()`
sont inchangés ; aucun `aclosing` n'est ajouté autour de
`RagService.answer_stream`. Seule différence : l'IP client est lue dans le
corps de la route plutôt qu'à la première itération du générateur ; la
valeur est la même (en-têtes immuables) et cette lecture ne peut pas
échouer. `_generate_session_id` devient `generate_session_id` dans le
service : le test unitaire qui l'importait depuis la route l'importe depuis
le service (pas de réexport). `RagService` reste importé comme module dans
la route, comme avant.

### D3.6 Autres fonctions notées D ou pire, ou en `noqa: C901`

Découpées sans changement de comportement (mêmes exceptions, mêmes messages,
même ordre des effets) :

| Fonction | Avant | Après |
| --- | --- | --- |
| `MistralAPIService.generate_stream` | D 21, C901 | C 12 |
| `VectorStoreValidator._analyze_inconsistencies` | E 34, C901 | A 3 |
| `FaissVectorStore.clean_orphans` | D 28 | B 6 |
| `logs_reader._apply_filters` | D 24 | C 13 |
| `main.lifespan` | C901 | A 3 |
| `log_parser.get_errors_last_hour` | C901 | A 2 |

Détails conservés : dans le flux Mistral, l'usage d'un chunk est lu après le
`yield` de son texte (un consommateur qui s'arrête à ce chunk ne l'enregistre
pas, comme avant) et une ligne `data: null` lève toujours une erreur de flux
(sentinelle `_NO_CHUNK` plutôt que `None`) ; `clean_orphans` appelle toujours
`_create_backup` quand `create_backup=True` et survit à toute exception de
sauvegarde ; un échec de persistance reste enveloppé deux fois comme avant ;
le filtre `since` des logs renvoie toujours la liste non filtrée sur
horodatage invalide ; le comptage d'erreurs garde le total partiel si la
lecture de `error.log` échoue. Les imports différés de `lifespan`
(`db_manager`, `setup_alerting`, `_llm_service`) sont conservés. Aucune autre
fonction notée A, B ou C n'a été modifiée.

### D3.7 Noms de loggers

Les messages déplacés dans les services sont émis par les loggers
`src.services.<module>` au lieu de `src.api.endpoints.<module>` ; leur texte
est inchangé. Aucun handler ni test ne filtre sur ces noms. Les logs des
fonctions découpées dans `main.py`, `mistral_api.py`, `faiss_store.py`,
`validation_utils.py`, `log_parser.py` et `logs_reader.py` gardent leur
logger.

### D3.8 Typage et mypy

Le code du flux SSE n'était pas vérifié par mypy (fonction imbriquée non
annotée). Une fois déplacé, mypy signale que `context_limit` peut valoir
`None` (champ optionnel de `ChatRequest`) : l'annotation de
`RagService.answer_stream` et de `_process_question_with_rag_stream` devient
`int | None` (valeur transmise sans être lue, aucun effet à l'exécution).
`_stream_answer` est annoté `AsyncGenerator` (et non `AsyncIterator`) pour
satisfaire `aclosing`, erreur introduite par le découpage du pipeline. Bilan :
mypy passe de 131 à 112 erreurs, aucune nouvelle.

### D3.9 Tests unitaires adaptés

Hors fichiers gelés : les patchs des tests d'upload visent
`src.services.document_upload` (`validate_filename`, `sanitize_filename`,
`Path`, `hashlib.sha256`) au lieu de la route, et le test de génération
d'identifiant de session importe `generate_session_id` depuis
`src.services.chat_stream`. Les tests unitaires de l'upload admin passent
sans modification.

## Passe 4 : typage

### D4.1 Configuration de mypy et stubs

`[tool.mypy]` dans `pyproject.toml` : mode normal (aucun `disallow_*`),
`python_version = "3.13"`, `warn_unused_ignores` et `warn_redundant_casts`.
`ignore_missing_imports` n'est activé que par module, pour les trois
bibliothèques qui n'ont ni types intégrés ni paquet de stubs : `faiss`,
`bm25s` et `docx` (python-docx 1.1.0 ; aucun `types-docx` ni
`types-python-docx` n'existe sur PyPI). Les trois bibliothèques qui ont des
stubs les reçoivent, épinglés dans `requirements-dev.txt` sur la série qui
correspond à la version installée, et non sur la dernière publiée (qui
décrirait une autre API) : `types-cachetools==5.3.0.7` (cachetools 5.3.2),
`types-Markdown==3.8.0.20250809` (Markdown 3.8.1),
`types-psutil==7.0.0.20251116` (psutil 7.0.0). Bilan : 112 erreurs (porte de
la passe 3) puis 0, y compris dans un venv vierge installé depuis
`requirements.txt` et `requirements-dev.txt` comme en CI.

### D4.2 Modèles SQLAlchemy 2.0

`models.py` passe de `declarative_base()` et `Column(...)` à
`DeclarativeBase`, `Mapped[...]` et `mapped_column(...)`, en gardant pour
chaque colonne son type SQL, sa nullabilité, son défaut, son `onupdate` et ses
drapeaux `index`/`unique` explicites. Vérifications avant/après :

- DDL SQLite compilé (`CreateTable` et `CreateIndex` de chaque table) et
  métadonnées de chaque colonne (défaut, `onupdate`, `autoincrement`, clé
  primaire, contraintes nommées) : strictement identiques ;
- `alembic.autogenerate.compare_metadata` (avec `compare_type` et
  `compare_server_default`) : 0 différence, aussi bien contre une base créée
  par les anciens modèles que contre une base créée par `alembic upgrade head`.

Les fabriques `AuditLog.create_*_action` renvoient `Self`. Effet de bord
utile : les 44 erreurs de `repository.py` liées aux `Column[...]` disparaissent
sans toucher au code des dépôts, hormis les `None` implicites.

### D4.3 `# type: ignore` restants

Quatre, tous avec leur code et un commentaire :

- `documents.py` : `doc_repo.update_preserve_status` (`attr-defined`), bug
  figé par l'oracle (D0.4) : la route doit continuer de répondre 500 ;
- `config.py` : `settings = None` (`assignment`), repli historique propre à
  pytest quand la configuration ne se charge pas ; l'application ne tourne
  jamais avec `None`, le type reste donc `Settings` ;
- `extractors.py` : `pypdf = None` et `markdown = None` (`assignment`),
  dépendances optionnelles testées contre `None` avant usage.

### D4.4 Rétrécissements sans changement de comportement

- `DatabaseManager` : attributs typés `Engine | None`,
  `sessionmaker[Session] | None`, etc. ; les accesseurs paresseux renvoient
  `typing.cast(...)` après `_initialize_database()` (qui lève en cas
  d'échec). Pas d'`assert` : un test unitaire remplace
  `_initialize_database` par un mock et lit `engine` sans erreur.
- `FaissVectorStore.index` est annoté `Any` : faiss n'a pas de types (le
  `faiss.Index | None` d'origine valait déjà `Any | None`) et l'index est posé
  par le constructeur ; un `assert` ou un contrôle explicite aurait changé
  l'exception levée (aujourd'hui une `AttributeError` enveloppée en
  `VectorStoreOperationError`) sur un chemin inatteignable.

### D4.5 Autres corrections d'annotations

`None` implicites rendus explicites (`x: T | None = None`), conteneurs annotés
quand mypy ne peut pas les inférer, `dict[str, any]` vers `dict[str, Any]`.
Corrections sans effet à l'exécution :

- `FileUploadValidation` : `min_items=1` (alias déprécié de Pydantic v2)
  devient `min_length=1` ; même contrainte, même message d'erreur, même
  `minItems` dans le schéma JSON (vérifié) ;
- `send_notification_email` appelle `_send_email` avec `html_content=` ou
  `text_content=` explicitement au lieu d'un `**dict` (mêmes arguments
  nommés, que les tests unitaires vérifient) ;
- `send_escalation_email(user_info=...)` accepte `dict[str, Any]` (la route
  y met des `None`) ;
- le rappel de la file d'ingestion est typé `Callable[..., Awaitable[bool]]`
  (il est attendu par `await`), `question_embedding` est un `np.ndarray` ;
- `IngestionProcessor.queue_document` : la variable du document relu en
  retraitement s'appelle `existing` (elle réutilisait `document`, typé non
  optionnel par la branche de création).

### D4.6 Modèles de réponse Pydantic

Sur les 18 routes déclarées en `response_model=dict` (les 17 de la mesure
initiale et `GET /`), onze renvoient désormais un modèle de
`src/shared/models.py` (les handlers et le service renvoient des instances) ;
les sept autres sont listées en D4.7 :

| Route | Modèle |
| --- | --- |
| `GET /` | `RootResponse` |
| `GET /admin/cache/stats` | `CacheStatsResponse` (`AdminCacheStats`, `CacheGlobalStats`) |
| `GET /admin/configuration`, `GET /admin/config` | `AdminConfigurationResponse` (`ApplicationConfig`) |
| `GET /admin/audit-log` | `AuditLogPage` (`AuditLogEntry`, `AuditLogFilters`) |
| `GET /admin/usage` | `UsageResponse` (`ModelUsageToday`, `DailyModelUsage`) |
| `GET /admin/documents` | `AdminDocumentList` (`AdminDocumentSummary`) |
| `GET /admin/documents/stats` | `AdminDocumentStats` |
| `POST /admin/documents/upload` | `AdminUploadResponse` (`UploadedDocument`) |
| `GET /documents/stats/overview` | `DocumentStatsOverview` (`DocumentStatusCounts`, `VectorStoreOverview`, `StorageInfo`) |
| `POST /documents/maintenance/validate-consistency` | `ConsistencyValidationResponse`, renvoyé par `index_maintenance.validate_index_consistency` |

Règles suivies pour que le JSON ne bouge pas : champs dans l'ordre des
anciennes clés ; `str` pour les dates déjà formatées par `isoformat()`
(`created_at` des documents), `datetime` pour les objets `datetime` que
Pydantic sérialisait déjà (`timestamp`, `AuditLogEntry.timestamp`) ; `int`
pour les compteurs (un champ `float` transformerait 0 en 0.0) et `int | float`
pour `total_size_mb` (toujours 0 aujourd'hui) ; champs `X | None` sans défaut
là où l'ancienne clé valait parfois `None`, jamais pour une clé absente ;
`validation_result` reste un `dict[str, Any]` (rapport du validateur, aussi
écrit en JSON et audité tel quel).

Vérification au-delà de l'oracle (qui neutralise les horodatages et arrondit
les flottants) : un greffon pytest a enregistré le texte brut des
323 réponses `TestClient` de la suite complète avant la passe puis après,
comparées en gardant l'ordre des clés, les types (0 contre 0.0, `null` contre
clé absente) et le format des dates (chiffres masqués, `Z`, décalage et
microsecondes conservés). Seules différences : le schéma OpenAPI (schémas de
réponse, exclus de l'oracle a, comme prévu) et deux tests concurrents dont
l'ordre d'exécution varie déjà d'une exécution à l'autre. Deux tests
unitaires de `get_document_stats` lisent désormais des attributs au lieu de
clés.

### D4.7 Ce qui reste en `dict`

- Routes dont le contenu dépend de la machine ou des logs : `/admin/system-info`,
  `/health/disk-usage`, `/admin/logs`, `/admin/metrics/chat`,
  `/admin/analytics/usage`.
- Sondes `/health/database` et `/health/cache` : leurs clés changent selon le
  résultat (succès : `connection`, `document_count`... ; échec : `error`) et
  les tests gelés remplacent les fonctions `_check_*_health` par des `dict`
  partiels. Un modèle émettrait `null` pour les clés absentes, sauf à
  recourir à `response_model_exclude_unset` : option écartée, la plus
  conservatrice étant de laisser ces sondes telles quelles (comme
  `HealthCheckResponse.checks`, déjà un `dict[str, Any]`).
- Statistiques des composants (`FaissVectorStore.get_stats`, `clean_orphans`,
  `rebuild_vector_store`, `VectorStoreValidator.validate_consistency`,
  `DocumentRepository.get_statistics`, `CacheService.get_stats`) : les tests
  d'intégration gelés lisent ces `dict` par clé, et ils alimentent les
  journaux d'audit et le rapport JSON de cohérence.
- Routes hors des 17 `response_model=Dict` (`/auth/me`, `/chat/sessions/{id}/history`,
  `/health/ready`, `/logs/frontend/health`) : leur annotation `dict` sert de
  modèle de réponse implicite à FastAPI ; elles restent telles quelles. Les
  routes déjà annotées `dict[str, str]` (`/auth/logout`, `/auth/verify-admin`,
  `/auth/change-password`, `/health/live`) sont déjà typées précisément.

### D4.8 Anomalie observée, non corrigée

`GET /api/v1/health/` (et `/health`) ajoute `unhealthy_components` au `dict`
passé à `HealthCheckResponse`, qui ignore les champs inconnus : la clé
n'apparaît jamais dans la réponse. Comportement existant, conservé.

### D4.9 CI

Nouveau job `mypy` bloquant dans `.github/workflows/ci.yml` (installe
`requirements.txt` et `requirements-dev.txt`, car mypy lit les types intégrés
de FastAPI, Pydantic et SQLAlchemy, puis lance `mypy backend/src`) et étape
`mypy backend/src` dans `scripts/local_ci.sh`, entre ruff et pytest.

## Passe 5 : commentaires

### D5.1 Règle appliquée aux docstrings

Périmètre : `backend/src` (hors migrations, voir D5.6), `backend/main.py`,
`backend/scripts`, `scripts/`. Les 794 docstrings du périmètre ont été
inventoriées (AST : signature, décorateurs, texte) et examinées une à une ;
325 sont modifiées (environ 1 600 lignes en moins) :

- **supprimées (120)** quand elles ne disent rien de plus que le nom et la
  signature, sur : fonctions et méthodes privées, `__init__` et méthodes
  spéciales, fournisseurs de dépendances FastAPI (`get_*` de
  `dependencies.py`, dont « Get document repository instance. »), DTO
  Pydantic dont la docstring répète le nom de la classe (« Request model for
  login »), utilitaires triviaux des modèles ORM (`to_dict`, `is_*`,
  `has_error`, fabriques d'`AuditLog`) et `Settings.is_production` ;
- **raccourcies (149)** sur les API publiques (routes FastAPI, classes et
  méthodes publiques des services et des dépôts, interfaces abstraites) : le
  résumé reste, les sections `Args`, `Returns`, `Raises` (et « Query
  Parameters ») disparaissent quand elles ne font que paraphraser noms et
  types ;
- **réécrites (56)** quand une section paraphrasait mais portait une
  information réelle (format, contrainte, effet de bord, pourquoi) : cette
  information est gardée en une phrase (`usage_out`, `similarity_floor`,
  clés de `filters` de l'audit, `order_by`, `index_type`...).

Gardées telles quelles : les docstrings qui expliquent un pourquoi, les
docstrings de module, celles des exceptions (souvent seul corps de la classe)
et, même brèves, celles des méthodes publiques des services et des interfaces
(option conservatrice). Les commentaires `#` ne sont modifiés que s'ils citent
un document de planning ou sont en français : la consigne vise les
docstrings, les commentaires « quoi » restent en place.

### D5.2 Docstrings inexactes corrigées

Sans toucher au code, des docstrings qui décrivaient mal le comportement sont
rectifiées : `_check_llm_health` (annonçait un test de connectivité, alors
qu'il ne vérifie que la présence de la clé), `IngestionProcessor.__init__`
(BM25 reconstruit « après chaque upsert » alors que la reconstruction est
regroupée à la vidange de la file), `DocumentRepository.delete` (renvoie
`False` si absent, lève `ValueError` si protégé),
`DocumentRepository.get_all_paginated` (seul le filtre `status` est appliqué).
Les sections fausses sans information utile sont simplement retirées
(`metadata_path` « pickle » de `FaissVectorStore`, `source` « for logging »
de `chunk_text`, qui part aussi dans les métadonnées).

### D5.3 Effets observables

- La docstring d'une route ou d'un modèle Pydantic devient la `description`
  OpenAPI : ces textes changent, l'oracle (a) les exclut. Vérification
  supplémentaire : le schéma OpenAPI complet, privé de ses clés
  `description`, est strictement identique avant et après la passe.
- Aucun `__doc__` n'est lu à l'exécution (pas de `description=__doc__` dans
  les scripts), aucun test ne lit une docstring.
- Log de démarrage : « Starting Mimir application - Jalon 3: API &
  Services... » devient « Starting Mimir application - API & Services... »
  (aucun test ni handler ne le lit).
- Aucun texte de réponse JSON ou d'événement SSE, aucune chaîne de prompt
  (`MIMIR_SYSTEM_PROMPT`, `NO_CONTEXT_SYSTEM_PROMPT`) n'est modifié.

### D5.4 Références à des documents de planning

Nettoyées en gardant le sens :

- `config.py`, descriptions `Field` (`06-07`, `07-06`, `ROADMAP`, `OPS-05`) :
  « adoptée après mesure RAGAS sur le golden set », « fixée à 60, valeur
  standard de la RRF »... Elles ne sont exposées par aucune route : aucun code
  ne lit `model_fields` ni `model_json_schema`, `Settings` n'est le modèle
  d'aucune route, et le schéma OpenAPI est inchangé hors descriptions ;
- `main.py` (« Milestone 3 », « Jalon 3 » : docstrings, commentaires, log),
  `shared/models.py` (« ready for Milestone 2-3 »), `rag_service.py`
  (« milestone prime directive », « Option A »), `usage_tracker.py`
  (`03-PATTERNS.md`), `models.py` et `connection.py` (renvois au « LLD » et
  aux « specs », absents du dépôt), « locked decision » de `tokenizer_fr.py`,
  `bm25_store.py` et `golden_set_schema.py` ;
- `scripts/ragas_eval` : aide argparse (`RAG-01`, `RAG-02`, `RAG-05`), `print`
  (`plan 06-01`, `plan 06-07 Task 3`), message d'évaluation (`Pitfall #2`),
  commentaire « success criteria », titre généré par `measure_chunking.py`,
  documents `*.md` (`RAG-0x`, `07-0x`, `ROADMAP critère 2`, `phase 6`,
  blocker `STATE`, `RESEARCH Pitfall #2`) ;
- tests : message d'assertion `(WR-01)` de `test_ingestion_processor.py`,
  describe vitest `SEC-04` de `DocumentModal.test.jsx`, docstring de
  `tests/performance/test_faiss_concurrency.py` ;
- `validate_milestone.sh` : les libellés de contrôles (`ROB-01`, `COST-01`,
  `SEC-03`, `OPS-03`, `OPS-01`) et les commentaires qui les décrivent sont
  conservés ; l'en-tête « milestone acceptance proof » devient « acceptance
  proof » et la bannière « Milestone validation summary (TEST-02) » devient
  « Validation summary » (`TEST-02` n'est pas un libellé de contrôle).

Restent volontairement : le nom de fichier `validate_milestone.sh` et ses
mentions, et les entrées `.planning/` de `.gitignore` et `.dockerignore` (elles
empêchent de versionner ou d'embarquer un dossier local ; les retirer pourrait
le faire fuiter). Faux positifs du grep : dates (`freeze_time`,
`today="2024-01-01"`), exemples `COVID-19` et `API-42`. Bilan : 0 référence de
planning hors `validate_milestone.sh`.

### D5.5 Commentaires en français

`CLAUDE.md` exige des commentaires en anglais : les docstrings et commentaires
français du périmètre sont traduits (`backend/scripts/init_db.py`,
`scripts/generate_test_documents.py`, `scripts/test_log_levels.py`, « venv
principal » et « venv SÉPARÉ » des docstrings de `scripts/ragas_eval`). Les
chaînes en français (descriptions `Field`, aide argparse, `print`, documents
`.md`, prompts) ne sont pas des commentaires et restent en français.
`start-servers.sh` et `stop-servers.sh`, hors périmètre, ne sont pas touchés.

### D5.6 Migrations Alembic non modifiées

Les docstrings de `backend/src/database/migrations` (gabarit Alembic :
« Upgrade schema. », en-têtes de révision) restent telles quelles : fichiers
générés, exclus de ruff, et l'en-tête de révision suit la convention Alembic.

## Passe 6 : tests

### D6.1 Méthode de tri

Une mesure de couverture par test (`--cov-context=test`, toute la suite) a
d'abord repéré les tests qui ne couvrent aucune ligne de `backend/src`, ceux
dont les lignes couvertes sont identiques à celles d'un autre test du même
fichier et les lignes que seul un test couvre. Ces indices n'ont servi qu'à
orienter la relecture : les 54 fichiers de test hors `tests/oracle` et
`tests/integration` (`tests/unit`, `tests/performance`) ont été relus. Un test
est supprimé dans deux cas seulement :

1. **il ne vérifie que des mocks, ou rien** : l'assertion porte sur la valeur
   rendue par un mock (ou sur l'attribut que le test vient lui-même de poser)
   à travers une fonction sans logique (délégation d'une ligne, getter), ou le
   mock n'est jamais lu par le code ; les tests vides (`pass`, toujours
   ignorés), ceux qui ne vérifient qu'un import et ceux dont les assertions ne
   s'exécutent jamais ou sont toujours vraies relèvent du même cas ;
2. **il fait doublon** : même chemin de code et assertions identiques ou plus
   faibles qu'un test conservé (souvent un copier-coller avec une valeur sans
   effet sur le chemin suivi).

Option conservatrice : un test qui exerce une branche réelle est gardé, même
faible ou en partie redondant (D6.3). La porte interdit aussi de descendre
sous 993 tests (5 % de 1045) : seuls les cas nets sont supprimés.

### D6.2 Tests supprimés (62)

Ne vérifient que des mocks, ou rien (29) :

- `test_api_endpoints_auth.py` : `TestTokenRefresh::test_refresh_token_unauthorized`
  et `TestLogout::test_logout_unauthorized`, corps `pass` marqués skip (le cas
  sans jeton est figé par l'oracle, « logout no token ») ;
- `test_api_endpoints_health.py` : `TestHealthModels::test_health_check_response_structure`
  (corps `pass`, skip) ; `TestDatabaseHealthEndpoint` et `TestCacheHealthEndpoint`
  (4 tests) : le handler délègue en une ligne au helper patché et l'assertion
  compare le résultat au dictionnaire rendu par le mock ; les helpers restent
  testés par `TestHealthHelperFunctions` ;
- `test_dependencies.py` : `TestRepositoryDependencies` (3) et
  `TestServiceDependencies` (4), getters d'une ligne dont le test patche la
  classe ou le singleton puis vérifie qu'on lui rend son mock ;
  `TestGlobalStateConsistency::test_multiple_services_independent` compare
  entre eux des mocks distincts par construction et répète
  `test_get_*_first_call` ;
- `test_auth_middleware.py::test_middleware_module_imports` et
  `test_api_endpoints_documents.py::test_simple_document_operations` : seuls
  des noms importés « non `None` », ce que l'import en tête de fichier garantit
  déjà ;
- `test_api_middleware_cors.py` : `test_cors_configuration_immutability`
  (relit l'attribut que le test a posé sur le mock) et
  `test_configure_cors_production_without_custom_origins_attr` (un `MagicMock`
  a tous les attributs : le cas annoncé n'est jamais atteint et le résultat ne
  dépend que du `split` du mock) ;
- `test_monitoring_logger.py::test_logger_with_extra_fields_integration` et
  `test_database_models.py::test_configuration_update_timestamp` : relisent la
  valeur que le test vient d'affecter ;
- `test_main_app.py` : `test_production_mode_docs_disabled` (le patch de
  `src.config.settings` n'est jamais lu, l'app étant construite à l'import, et
  l'assertion accepte 404, 307 et 200), `test_request_logging_middleware`
  (`len(caplog.records) >= 0`), `test_general_exception_handler` (logger
  patché inutilisé, même requête que `test_root_endpoint`) ;
- `test_config.py` : `test_env_file_loading` (écrit un `.env` jamais lu, puis
  répète `test_custom_settings`) et `test_case_insensitive_config`
  (`hasattr(settings, "api_version")`) ;
- `test_faiss_additional.py::test_faiss_store_metadata_handling` : assertions
  toujours vraies (`len(results) >= 0`, `hasattr` d'un champ de dataclass) ;
- `test_ingestion_chunking.py` : `test_chunk_character_positions` et
  `test_chunk_minimum_size_enforcement`, dont le texte tient en un chunk : les
  assertions, sous `if len(chunks) > 1` ou dans une boucle sur `chunks[:-1]`,
  ne s'exécutent jamais.

Doublons (33) :

- `test_auth_middleware.py` (6) : `test_call_expired_token` et
  `test_authentication_chain_invalid_token`, copies de `test_call_invalid_token`
  (même `verify_token -> None`) ; `test_get_current_user_expired_token` et
  `test_get_current_user_jwt_handler_exception`, copies de
  `test_get_current_user_invalid_token` (`jwt_payload = None`) ;
  `test_error_propagation`, même chemin que `test_call_jwt_handler_exception`
  (`ValueError` au lieu d'`Exception`, aucun `except`) ;
  `test_bearer_auto_error_false`, identique à `test_call_no_credentials`
  (`HTTPBearer.__call__` étant patché, `auto_error` n'a aucun effet) ;
- `test_rate_limit_middleware.py::test_no_jwt_payload_in_state`, copie de
  `test_no_jwt_payload` ;
- `test_api_endpoints_chat.py` : `test_get_session_history_with_user` et
  `test_clear_session_history_with_user` (les handlers ignorent `current_user`,
  assertions incluses dans les variantes sans utilisateur) ;
- `test_api_endpoints_auth.py::test_rate_limiting_simulation` : dix appels à
  `_get_client_ip`, comme `test_get_client_ip_direct` ;
- `test_email_service.py::TestEmailValidation` (4) : les deux
  `test_validate_email_address_*` vérifient `_is_configured() is True` comme
  `test_is_configured_true` (les méthodes annoncées n'existent pas), les deux
  `test_sanitize_email_content*` répètent `test_generate_escalation_{html,text}_minimal` ;
- FAISS (5) : `test_faiss_store_initialization_basic`, `test_faiss_store_properties`,
  `test_faiss_store_different_dimensions`, `test_faiss_store_initialization_params`
  (`test_faiss_additional.py`) et `test_faiss_store_different_index_types`
  (boucle sur le seul `"FlatL2"`) : versions plus faibles de
  `test_faiss_store_initialization`, la création de l'index restant vérifiée
  par `test_faiss_store_with_mock_index` ;
- `test_main_app.py::test_request_timing_header`
  (`"x-process-time" in headers or status == 200`), version faible de
  `test_timing_header_added` ;
- `test_llm_interface.py::test_model_name_property`, assertion déjà faite par
  `test_mistral_api_initialization` ;
- `test_monitoring_simple.py` (12 des 14 tests, fichier « focus on code
  coverage ») : chaque test répète, en plus faible, un test de
  `test_monitoring_logger.py` (formateurs JSON et console, `setup_logger` :
  nom, niveau, handlers, singleton, écriture à tous les niveaux). Les deux tests
  sans équivalent (`test_json_formatter_no_exception_info`,
  `test_json_formatter_ensure_ascii_false`) sont déplacés tels quels dans
  `TestJSONFormatter` de `test_monitoring_logger.py` et le fichier est supprimé.

Effet mesuré avant ajouts : 1045 → 983 tests, couverture 86,21 % → 86,18 %
(−0,03 pt : seules les lignes 52 et 64 de `api/dependencies.py`, corps de
`get_cache_service` et `get_jwt_handler`, ne sont plus couvertes). Les trois
tests ignorés de la suite étaient les trois tests vides : il n'en reste aucun.

### D6.3 Doublons partiels conservés

Gardés faute de certitude qu'ils n'apportent rien (entrée ou assertion
différente, branche réelle exercée), et parce qu'en les retirant aussi le
total serait tombé sous le plancher de 993 tests :
`test_full_auth_workflow`, `test_health_check_comprehensive_scenario`,
`test_configure_cors_credentials`, `test_configure_cors_max_age`,
`test_cors_different_environments`, `test_list_documents_pagination`,
`test_document_upload_and_stats_workflow` (seul à vérifier
`by_status.pending`), `test_404_handling`,
`test_escalate_to_human_with_authenticated_user`, quatre tests d'envoi d'email,
`test_log_ingestion_event_with_error`, cinq tests FAISS à assertions faibles,
trois du processeur d'ingestion, quatre d'extracteurs, quatre de JWT et mots de passe,
quatre de modèles partagés, quatre de dépôts, `test_field_validation_ranges`,
`test_require_admin_malformed_user` et cinq tests de chunking qui ne passent
que par le chemin à chunk unique.

### D6.4 mutmut : configuration

- mutmut 3.8.0, section `[tool.mutmut]` de `pyproject.toml` :
  `source_paths = ["backend/src"]` (copie complète dans `mutants/`, dont
  `tests/conftest.py` a besoin), `only_mutate` limité aux trois fichiers,
  tests limités à `test_fusion.py`, `test_ingestion_chunking.py` et
  `test_bm25_store.py`, `pytest.ini` copié, `--no-cov`. Lancement :
  `mutmut run`, puis `mutmut results` (435 mutants, moins d'une minute).
- mutmut nomme un mutant d'après le chemin du fichier
  (`backend.src.rag_core.fusion`) et ne l'active que si le `__module__` de la
  fonction porte exactement ce nom. Or les tests importent `src.*` (le
  conftest met `backend/` dans `sys.path`), ce qui charge une seconde copie du
  module, jamais mutée ; des trois fichiers retenus, seul `test_bm25_store.py`
  importe `backend.src.*`. Plutôt que de réécrire les imports de tests
  existants, un petit plugin pytest,
  `tests/mutmut_aliases.py`, chargé par mutmut seulement
  (`-p tests.mutmut_aliases`), fait pointer `src.rag_core.fusion`,
  `src.ingestion.chunking` et `src.rag_core.tokenizer_fr` vers les modules
  `backend.src.*` : les deux chemins d'import partagent le module muté. Le
  fichier ne commence pas par `test_` : `pytest` ne le charge pas.
- `mutants/` est ajouté au `.gitignore` (ruff le respecte).

### D6.5 mutmut : résultats

| Fichier | Mutants | Tués avant | Survivants avant | Tués après | Survivants après |
| --- | --- | --- | --- | --- | --- |
| `rag_core/fusion.py` | 17 | 16 | 1 | 17 | 0 |
| `rag_core/tokenizer_fr.py` | 15 | 15 | 0 | 15 | 0 |
| `ingestion/chunking.py` | 403 | 282 | 121 | 364 | 39 |

« Tués » inclut un timeout (`_assign_section_titles`, `index += 1` →
`index = 1` : boucle infinie, donc détecté). Mesure refaite après les
suppressions de D6.2 et avant les ajouts : résultats identiques.

Tests ajoutés (27) : `test_fusion.py::test_rrf_default_k_is_60` (seul
survivant de `fusion.py` : tous les tests passaient `k=60`, la valeur par
défaut n'était jamais vérifiée) et 26 tests de sortie exacte dans
`test_ingestion_chunking.py` : nettoyage du texte ; chemin par paragraphes
(chunk rempli jusqu'à `chunk_size` inclus, dépassement d'un caractère, chunk
d'exactement `max_chunk_size` non redécoupé, recouvrement) ; chemin par
phrases (`preserve_paragraphs=False` : bornes de `chunk_size` et de
`min_chunk_size`, chunk trop petit qui absorbe la phrase suivante,
`min_chunk_size = 0`, repli sur le texte entier, texte d'exactement
`chunk_size`) ; `_split_sentences` (choix entre découpage regex et découpage
simple, et sa borne) ; `_get_overlap_text` (10 cas : texte vide, taille nulle,
frontière de phrase, fenêtre de recherche de `overlap + 100` caractères et
ses bornes, frontière en fin de texte, recouvrement par caractères) ;
`get_chunk_statistics` (priorité au `word_count` stocké, moyennes) ; titres
de section (préambule sans titre, trois sections successives, balises
internes retirées du titre). Ce sont des tests de caractérisation : ils
figent la sortie actuelle, bizarreries comprises (D6.6), sauf les positions.

Les 39 survivants de `chunking.py` sont non significatifs :

- 22 ne touchent que la journalisation : messages et champs `extra` des
  `logger.debug/info/warning` de `__init__` et de `chunk_text` (19 dans le
  `logger.info` final), et la valeur par défaut de `source`, qui ne sert
  qu'aux logs ;
- 12 sont équivalents : `chunks = None` aussitôt réaffecté ;
  `current_chunk = None` au lieu de `""` (même valeur de vérité) ;
  `continue` → `break` sur un paragraphe ou une phrase vide, cas impossible
  après `_clean_text` et `_split_sentences` (2) ; `or True` dans une branche où
  `current_chunk` est toujours non vide ; 5 mutants sur `sentence_start`,
  variable jamais lue ; `found.sort(key=None)` (positions distinctes, même
  ordre) ; `overlap_size >= len(text)` → `>` (`text[-len(text):] == text`) ;
- 5 tiennent au défaut de positions de D6.6 : l'arithmétique de
  `current_start` (2 mutants par chemin) et le `start_offset` transmis au
  redécoupage d'un paragraphe trop long, masqué parce que `start_char` vaut
  toujours 0. Les tuer obligerait à figer des positions fausses : ils restent
  survivants, à revoir si le défaut est corrigé.

### D6.6 Anomalies révélées, non corrigées

Cette passe ne modifie aucun code de production :

- **positions des chunks** : `_chunk_by_paragraphs` et `_chunk_by_sentences`
  recalculent `current_start` après avoir réaffecté `current_chunk`, si bien
  que `len(current_chunk) - len(overlap_text) - len(paragraph)` vaut 0 :
  `start_char` reste à 0 (ou à `start_offset`) pour tous les chunks et
  `end_char` vaut la longueur du chunk. Ces valeurs ne sont que stockées dans
  `Chunk.metadata` (aucun lecteur). Les tests ne vérifient que des invariants
  vrais aujourd'hui comme après correction (premier chunk à 0, positions
  positives, `end_char - start_char == len(text)`) ;
- **chemin par phrases** (`preserve_paragraphs=False`, ou paragraphe de plus
  de `max_chunk_size`) : `re.split` consomme la ponctuation de fin de phrase et
  les phrases sont recollées par une espace (« First one here Second one
  here ») ; faute de ponctuation, le recouvrement retombe sur une coupe par
  caractères, souvent au milieu d'un mot. Comportement actuel, figé tel quel ;
- **abréviations** : les lookbehinds `(?<!Dr\.)`, `(?<!etc\.)`... de
  `_split_sentences` sont évalués avant le point et ne protègent jamais
  l'abréviation (« Dr. Smith » est coupé). Non figé ;
- **titres à balises internes** : le titre est nettoyé (« Intro part ») mais
  sa signature, `<h2>\s*Intro part`, est absente du HTML
  (`<h2><em>Intro</em> part</h2>`) : il n'est jamais consommé et, les titres
  l'étant dans l'ordre, ceux qui suivent non plus (tous les chunks restent à
  `None`). Non figé ;
- **dernier segment trop court** : dans le chemin par phrases, un reste final
  plus court que `min_chunk_size` est abandonné dès qu'un chunk existe déjà, et
  la ou les dernières phrases sont perdues (rare avec les valeurs par défaut,
  le recouvrement allongeant ce reste). Non figé.

## Passe 7 : dépendances

### D7.1 Lockfiles

`requirements.txt` et `requirements-dev.txt` restent la source. Les locks sont
générés par `uv pip compile` (uv 0.11.32), depuis la racine du dépôt :

- `requirements.lock` (98 paquets), depuis `requirements.txt` ;
- `requirements-dev.lock` (141 paquets), depuis `requirements.txt` et
  `requirements-dev.txt`.

Options : `--generate-hashes --universal --python-version 3.13`. La commande
exacte, à chemins relatifs, est écrite par uv en tête de chaque fichier.
`--universal` produit une seule résolution valable sur toutes les plateformes,
avec marqueurs (`pywin32` sous Windows, `uvloop` hors Windows et PyPy,
`colorama` sous Windows dans `requirements.lock` mais partout dans le lock dev,
radon en dépendant sans condition) : le même lock sert au runner Linux de la CI et aux postes de dev. Les
deux locks ont les mêmes versions pour tous les paquets communs (vérifié). Les
hachages couvrent toutes les distributions publiées de chaque version (wheels
de toutes plateformes et sdist), d'où la taille des fichiers (280 et 330 Ko).
`pip` figure dans `requirements-dev.lock` (dépendance de pip-audit via
pip-api) : uv ne l'exclut pas, et l'installation par hachage l'accepte.

Vérifié dans des venv jetables en Python 3.13.16 :
`pip install --require-hashes -r requirements-dev.lock` et
`-r requirements.lock` réussissent, `pip check` est propre ; dans le venv du
lock runtime seul, les 1010 tests passent (couverture 86,23 %) ; dans celui du
lock dev, ruff, `ruff format --check` et mypy (0 erreur) passent. Le `.venv`
du projet correspondait déjà exactement au lock dev (installation à blanc :
rien à changer).

L'installation documentée (README) et celle du venv vierge de la porte
restent `pip install -r requirements.txt` ; mentionner les locks dans le
README relève de la passe 8.

### D7.2 CI

- **Installation.** Chaque job installe depuis un lock avec
  `pip install --require-hashes`, sans `--no-deps` : en mode hachage, pip
  refuse toute dépendance absente du lock, alors que `--no-deps` la ferait
  ignorer en silence. Jobs ruff, mypy et pip-audit : `requirements-dev.lock` ;
  job pytest : `requirements.lock` seul (la suite n'utilise aucun outil de
  dev ; vérifié, 1010 tests). Avant, les jobs ruff et pip-audit n'installaient
  que `requirements-dev.txt` : faute de lock dédié aux outils, ils installent
  désormais aussi les dépendances runtime (quelques dizaines de secondes de
  plus hors cache). Le cache pip est indexé sur le lock installé.
- **Cohérence lock / requirements.** Les jobs mypy et pytest lancent, après
  l'installation, `pip install -q --no-deps --no-index -r requirements.txt`
  (et `-r requirements-dev.txt` pour mypy). Sans index, pip ne peut rien
  télécharger : si une épingle de `requirements*.txt` n'est pas la version
  installée depuis le lock (bump sans lock régénéré), l'étape échoue. Vérifié
  dans les deux sens (succès sur l'état actuel, échec avec `fastapi` épinglé à
  une autre version). Limite : un paquet retiré de `requirements.txt` mais
  resté dans le lock n'est pas détecté. La CI ne régénère pas le lock pour le
  comparer : la liste des hachages dépend des distributions publiées au moment
  de la génération (une wheel ajoutée après coup à une version existante
  changerait le fichier), ce qui rendrait une comparaison stricte instable.
- **pip-audit.** L'audit existant de `requirements.txt` (résolution par pip,
  même commande que la porte) est conservé. S'y ajoute l'audit de
  `requirements-dev.lock` avec `--require-hashes --disable-pip` : exactement ce
  que la CI installe (runtime, test et outils de dev ; 140 paquets, `pywin32`
  écarté par son marqueur sous Linux), sans résolution. Mêmes exclusions.
  Même ajout dans `scripts/local_ci.sh` ; la porte, qui lit les exclusions
  dans les lignes `--ignore-vuln` de ce script, n'est pas affectée.

### D7.3 Dependabot

`.github/dependabot.yml` (version 2) : pip (`/`), npm (`/frontend`) et
github-actions (`/`), hebdomadaire, 5 pull requests ouvertes au plus par
écosystème. Pour pip, Dependabot ne met à jour que `requirements.txt` et
`requirements-dev.txt` : il ne régénère pas les `.lock` (pour pip, il ne
cherche que des fichiers `*.txt` et `*.in`). Sur chaque pull request
pip, il faut donc régénérer les deux locks avec la commande de leur en-tête
et pousser le résultat sur la branche de la pull request ; tant que ce n'est
pas fait, l'étape de cohérence de la CI échoue, ce qui est voulu (sinon la CI
testerait l'ancienne version du lock). Le fichier le rappelle en commentaire.

Les mises à jour majeures de `mistralai` sont ignorées : la 1.x est un
nouveau SDK, et y passer est la migration exclue par la mission. Il n'existe
pas de version 0.x plus récente que 0.4.2, donc aucune autre mise à jour de ce
paquet n'est masquée. orjson, dépendance transitive, n'est pas suivi par
Dependabot (son exclusion pip-audit reste).

### D7.4 aiosqlite

`aiosqlite` passe de « # Testing » à « # Database » (pilote du moteur
asynchrone de SQLAlchemy, `database/connection.py`), avec un commentaire. Les
autres entrées de « # Testing » (pytest, pytest-asyncio, pytest-cov, httpx,
locust, freezegun) restent dans `requirements.txt` : choix préexistant, la CI
et la porte installant les dépendances de test depuis ce fichier, et
`requirements-dev.txt` étant réservé aux outils de qualité. Aucune n'est
importée par `backend/` ; les sortir changerait le contenu du venv de la porte
et la commande d'installation documentée, sans gain pour cette mission.

### D7.5 pytest 9

Montées aux dernières versions publiées : pytest 7.4.3 → 9.1.1,
pytest-asyncio 0.21.1 → 1.4.0, pytest-cov 4.1.0 → 7.1.0. Essai d'abord dans un
venv jetable, puis dans le `.venv` du projet.

- Aucun changement de tests, de `conftest.py` ni de `pytest.ini` : tous les
  tests asynchrones portent déjà `@pytest.mark.asyncio` (le mode strict reste
  le mode par défaut), aucun n'utilise la fixture `event_loop` supprimée en
  1.0, et pytest-asyncio 1.4 n'avertit pas sur
  `asyncio_default_fixture_loop_scope` non défini.
- Résultat : 1010 tests, 1010 réussis, 0 ignoré, couverture 86,23 %
  (identique) ; tests gelés : 186 réussis ; la sélection de tests de mutmut
  (`-p tests.mutmut_aliases`) passe ; mutmut 3.8.0 demande `pytest>=6.2.5`.
- pytest 9 affiche davantage d'avertissements (21 au lieu de 10) : des
  `ResourceWarning` « unclosed database » de connexions SQLite laissées
  ouvertes par des tests d'intégration gelés, que pytest 7 ne remontait pas.
  Simples avertissements, préexistants ; tests gelés, non modifiés.
- L'exclusion pip-audit PYSEC-2026-1845 (pytest) est retirée de la CI et de
  `scripts/local_ci.sh`. Seule reste PYSEC-2026-107 (orjson 3.10.18, bloqué par
  mistralai 0.4.2, SDK non migré).

### D7.6 Porte de qualité

Tentative 1 : porte franchie, métriques identiques à la passe 6 (1010 tests,
1010 réussis, 0 ignoré, couverture 86,23 %, ruff 0, format OK, radon D+ 0,
mypy 0, pip-audit OK, vitest 141, build OK, `/health/live` 200 depuis un venv
vierge installé depuis `requirements.txt`, tests gelés et sommes de l'oracle
OK). Aucun nouvel avis pip-audit pendant la passe.

## Passe 8 : façade

### D8.1 Périmètre

Seuls des fichiers Markdown changent : `README.md`, `CLAUDE.md`, `docs/adr/`
(nouveau) et `docs/cleanup/`. Aucun code, test ni fichier de configuration.
Le bloc « **critical** » de `CLAUDE.md` est inchangé (vérifié par `diff` des
21 premières lignes avec `HEAD`). Restent donc en l'état, hors périmètre :

- `backend/.env.example` garde un commentaire qui donne la valeur du mot de
  passe admin par défaut, à côté de `ADMIN_PASSWORD_HASH` (fichier
  d'exemple de configuration, pas un document) ;
- `backend/src/security/startup_validation.py` contient cette valeur en
  constante : elle sert à détecter au démarrage un mot de passe resté à
  l'origine (code, comportement) ; un commentaire de
  `tests/unit/test_config_validation.py` la cite aussi ;
- le commentaire de `_start_ingestion` (`backend/main.py`) dit
  `structure_aware_chunking_enabled` à `False` « (current default) », alors
  que le défaut est `True` ;
- le commentaire de `hybrid_search_enabled` (`config.py`) annonce +14,2 % de
  `context_precision` ; les fichiers de résultats donnent 0,5788 → 0,6606,
  soit +14,1 % (chiffre aussi retenu par `adoption_decision.md`). Les ADR
  citent les scores bruts des fichiers.

### D8.2 Lignes de code (pygount 3.2.0)

Mesurées depuis la racine, avec le `.venv` du projet, en lignes de code
(colonne « Code », hors commentaires et lignes vides) ; aucun fichier non
suivi par git dans ces dossiers (hors `__pycache__`, ignoré par pygount) :

```
pygount --format=summary --suffix=py backend/src backend/main.py backend/scripts
pygount --format=summary --merge-embedded-languages --folders-to-skip='...,test' \
  --names-to-skip='...,*.test.js,*.test.jsx' frontend/src
pygount --format=summary --suffix=py tests
pygount --format=summary --merge-embedded-languages frontend/src/test \
  frontend/src/components/Admin/AnalyticsPanel.budget.test.jsx
pygount --format=summary --suffix=py,sh scripts
```

| Périmètre | Fichiers | Code |
| --- | ---: | ---: |
| Backend (`backend/src`, `main.py`, `backend/scripts`), Python | 77 | 9 448 |
| Frontend hors tests (JSX 4 117, JS 829, CSS 206) | 39 | 5 152 |
| Code applicatif | 116 | 14 600 |
| Tests backend (`tests/`), Python | 86 | 13 858 |
| Tests frontend (JSX 1 117, JS 264) | 15 | 1 381 |
| Tests | 101 | 15 239 |
| `scripts/` (Python 1 818, Bash 195) | 16 | 2 013 |

Choix : migrations Alembic comptées dans le backend (code Python livré) ;
`--suffix=py` écarte les instantanés JSON et le corpus de `tests/oracle`, et
le `README` et le gabarit `.mako` des migrations ; `--merge-embedded-languages`
évite que pygount classe des `.js` en « JavaScript+Genshi Text » et le CSS en
« CSS+Lasso » (mêmes totaux). `backend/scripts` (`init_db.py`) est compté
avec le backend ; `scripts/` (évaluation, sauvegarde, CI locale) est donné à
part, ni application ni tests. Les compteurs de tests par dossier viennent de
`pytest --collect-only -q -o addopts=""` : 812 unitaires, 154 d'intégration,
32 de l'oracle, 12 de performance.

### D8.3 Mot de passe admin

Retiré de `README.md` (section « Connexion Admin ») et de `CLAUDE.md`
(section « Environment ») ; la valeur n'apparaît dans aucun texte nouveau.
Remplacé par la façon dont le mot de passe est réellement fixé, d'après le
code :

- `ADMIN_PASSWORD` (en clair) : haché au démarrage par
  `resolve_admin_password`, en mémoire seulement, prioritaire sur
  `ADMIN_PASSWORD_HASH` ; règles de robustesse de
  `validate_password_strength`, bloquantes en production ;
- `ADMIN_PASSWORD_HASH` : hash Argon2 (commande de la section « Génération du
  hash admin », conservée) ;
- changement depuis Admin > Configuration (`POST /auth/change-password`) :
  réécrit `ADMIN_PASSWORD_HASH` dans `backend/.env` ;
- sans aucune des deux variables, le hash intégré à `config.py` s'applique :
  `validate_production_secrets` refuse le démarrage si
  `ENVIRONMENT=production`, avertit sinon.

Le README disait aussi que la production refuse de démarrer « si ces secrets
sont aux valeurs par défaut » en citant `MISTRAL_API_KEY` : seule la clé JWT
et le mot de passe admin sont contrôlés, et seulement avec
`ENVIRONMENT=production` (que `docker-compose.yml` ne fixe pas). Corrigé.

### D8.4 « Easy to swap implementations » : promesse retirée

Constat sur le code :

- une seule implémentation par abstraction : `MistralAPIService`
  (`AbstractLLMService`), `FaissVectorStore` (`AbstractVectorStore`),
  `Bm25LexicalStore` (protocole `LexicalIndex`) ;
- `RagService`, les étapes du pipeline et `IngestionProcessor` sont typés sur
  les abstractions (D3.1) ;
- mais `api/dependencies.py` instancie directement les classes concrètes et
  ses fournisseurs sont annotés avec elles ; `LLM_PROVIDER` et
  `VECTOR_STORE_TYPE` ne sont que lus pour affichage (`admin.py`,
  `health.py`), jamais pour choisir une implémentation ;
- la reconstruction admin (annotée `FaissVectorStore`/`Bm25LexicalStore`), le
  nettoyage d'orphelins, `VectorStoreValidator` et la lecture des chunks d'un
  document appellent des méthodes ou attributs propres à FAISS
  (`rebuild_vector_store`, `clean_orphans`, `get_document_chunks`,
  `metadata`, `document_to_chunks`, `_lock`), absents de
  `AbstractVectorStore`.

Changer de fournisseur demande donc du code, pas de la configuration. La
ligne de `CLAUDE.md` est réécrite en ce sens (interfaces abstraites, une
implémentation chacune, limites ci-dessus). Le README annote `LLM_PROVIDER` et
`VECTOR_STORE_TYPE` comme seulement affichés.

### D8.5 Autres affirmations fausses corrigées dans le README

- `POST /api/v1/chat` n'existe pas : seule `POST /api/v1/chat/stream` répond
  (et l'oracle OpenAPI le confirme) ; ajout de `change-password` et de
  `validate-consistency`, chemins écrits avec leur barre oblique finale
  réelle (`/documents/`, `/health/`) ;
- arborescence : `backend/tests/` n'existe pas (les tests sont à la racine) ;
  ajout de `services/`, `cost/`, `security/`, `shared/errors.py`,
  `api/responses.py`, `rag_core/fusion.py`, `tokenizer_fr.py`,
  `bm25_store.py`, `tests/oracle/`, `docs/adr/` ;
- « Auth : JWT avec bcrypt » : les nouveaux hash sont Argon2, bcrypt n'est
  accepté qu'en vérification ; badge FastAPI 0.116+ → 0.133 ;
- logs dans `backend/logs/` (dossier `./logs` du répertoire de lancement
  d'uvicorn), pas `logs/` ;
- variables : `RATE_LIMIT_PER_MINUTE` n'est lue par aucun limiteur, remplacée
  par les trois variables effectives (login, chat, upload) ; `CACHE_*`
  annotées « déclarées mais non lues » (tailles fixes : 100 entrées et 1 h
  pour le cache général, 50 entrées et 30 min pour les réponses) ;
  `ADMIN_PASSWORD` ajouté ;
- « Configuration email d'escalade » dans l'admin : l'écran Configuration est
  en lecture seule (la configuration SMTP passe par l'environnement) ; il
  permet de tester l'email et de changer le mot de passe ;
- « Rate limiting (chat, admin, upload, auth) » : seuls le login, le chat et
  les deux routes d'upload sont limités ;
- Swagger et ReDoc sont désactivés en production ;
- comptes : « ~1000 pytest + ~138 vitest, ~83 % » devient 1010 tests pytest,
  141 vitest, couverture 86,23 %.

Ajouts : section « Qualité et CI » (ruff, mypy, pytest 9, pip-audit et son
exclusion, `scripts/local_ci.sh`, jobs de la CI, lockfiles et commandes de
régénération reprises de leur en-tête, Dependabot), tableau pygount, liens
vers `docs/adr/`. Ton, plan et sections d'origine conservés.

### D8.6 ADR : revue des brouillons

Cinq ADR et un index écrits dans `docs/adr/` à partir des brouillons ; chaque
nombre, chemin et symbole a été vérifié dans le code et les fichiers de
résultats. Corrections apportées :

- 0001 : le plafond se modifie à chaud par `PUT /api/v1/admin/configuration`,
  pas depuis l'écran Admin > Configuration (en lecture seule) ;
- 0002 : la similarité FAISS n'est un cosinus que pour des vecteurs normés ;
  scores bruts des fichiers (0,6792 → 0,8000 ; 0,5788 → 0,6606) sur 40
  questions du corpus ; le contrôle à terme exact donne un rappel de 1,0 dans
  les deux modes (non-régression, pas un gain) ; score RRF maximal 2/61 ou
  3/61 selon la présence de la pré-inclusion ; si BM25 échoue, la fusion
  porte sur le seul pool dense mais garde seuil et confiance hybrides ;
- 0003 : la moyenne est globale (seul le taux de NaN est ventilé corpus /
  adversarial) ; la CI ne lance aucun script d'évaluation ni appel à Mistral
  (pip-audit, lui, interroge le réseau) ; scores bruts du chunking ajoutés ;
  rerank : fichiers et code absents, aucun chiffre cité ;
- 0004 : tables créées par `create_all` au démarrage, migrations Alembic à
  côté ; seules les écritures budget/usage passent par `asyncio.to_thread` ;
  doute (a) : `IndexFlatL2` renvoie la distance L2 au carré, `1 - d/2` est
  exactement le cosinus pour des vecteurs de norme 1, le code ne normalise
  pas et s'en remet à `mistral-embed` ; le nettoyage d'orphelins déclenché
  après une suppression se fait sans sauvegarde (`create_backup=False`), seule
  la reconstruction admin sauvegarde ; `validate-consistency` demande un
  utilisateur authentifié, pas `require_admin` ; doute (b), voir D8.7 ;
- 0005 : l'évaluation draine `RagService.answer_stream`, pas le flux SSE ;
  `EventSource` écarté faute de POST et d'en-tête `Authorization` ; variables
  `CACHE_*` non lues.

### D8.7 Anomalies préexistantes relevées, non corrigées

Aucun changement de comportement dans cette passe ; ces points sont décrits
dans les ADR ou le README, sans correction :

- **suppression FAISS non persistée** : `FaissVectorStore.delete()` ne pose
  le drapeau `deleted` qu'en mémoire. La suppression n'atteint le disque qu'au
  prochain `persist()` : ingestion, reconstruction admin, nettoyage
  d'orphelins qui en trouve, validation avec corrections, ou `optimize()`
  automatique au-delà de 25 % de vecteurs supprimés. Un redémarrage entre-temps
  recharge les chunks comme actifs (orphelins côté SQLite, absents de BM25
  déjà reconstruit) jusqu'au prochain nettoyage. Antérieur à la mission
  (ADR 0004, README section 5 du dépannage) ;
- **`run_pipeline.py --retrieval-mode dense`** laisse l'environnement
  inchangé : depuis que `hybrid_search_enabled` vaut `True` par défaut, il
  mesure le mode hybride sauf si `HYBRID_SEARCH_ENABLED=false` est défini
  (ADR 0003) ;
- **changement de mot de passe depuis l'interface en conteneur** :
  `_update_env_file` réécrit `<backend>/.env`, absent de l'image (exclu par
  `.dockerignore`, `/app` non inscriptible par l'utilisateur `mimir`) ; d'après
  le code, la route répond alors 500. Le README oriente vers `ADMIN_PASSWORD`
  en conteneur ;
- variables déclarées mais sans effet : `CACHE_ENABLED`, `CACHE_MAX_SIZE`,
  `CACHE_TTL`, `RATE_LIMIT_PER_MINUTE` ; `LLM_PROVIDER` et
  `VECTOR_STORE_TYPE` seulement affichés (D8.4) ;
- en mode hybride, l'interface affiche le score RRF (≤ 0,05) en pourcentage
  de pertinence (ADR 0002) ;
- `scripts/ragas_eval/rerank_adoption_decision.md` cite
  `rerank_baseline_run.json`, `rerank_multibert_run.json`,
  `rerank_latencies.json`, un test `test_rag_service_rerank.py` et un drapeau
  `rerank_enabled` absents du dépôt. Document laissé tel quel (hors
  périmètre), chiffres non repris.

### D8.8 Porte de qualité

Tentative 1 : porte franchie, métriques identiques à la passe 7 (1010 tests,
1010 réussis, 0 ignoré, couverture 86,23 %, ruff 0, format OK, radon D+ 0,
mypy 0, pip-audit OK, vitest 141, build OK, `/health/live` 200 depuis un venv
vierge, tests gelés et sommes de l'oracle OK). Attendu : la passe ne touche
que du Markdown. Aucun nouvel avis pip-audit pendant la passe.

## FIN : corrections après la revue

Revue : `docs/cleanup/REVIEW.md` (3 bloquants, 5 importants, 8 mineurs). Cause
commune : la passe 2 avait rétréci des `except Exception` qui garantissaient un
repli. Base de comparaison : `pre-cleanup` (`b1e18e6`).

### DF.1 Règle appliquée

Pour chaque `except Exception` de `pre-cleanup` dont le handler continuait,
renvoyait une valeur par défaut, convertissait en erreur ou en message précis,
ou journalisait avant de relancer, le code actuel doit donner le même résultat
pour une exception quelconque (`RuntimeError`, `ZeroDivisionError`,
`EOFError`...). Là où ce n'était plus le cas, le `except Exception` est rétabli
avec `# noqa: BLE001 - <raison>` et le corps d'origine : même repli, même log,
même exception levée. Restent de la passe 2 ce qui ne change pas le
comportement : exceptions métier (le validateur lève `RetrievalError`, même
message, au lieu d'une `Exception` nue), `raise ... from e`, logs ajoutés.
Devenus inutiles, les tuples `INDEX_BACKEND_ERRORS` (`rag_core/interfaces.py`),
`_PARSER_ERRORS`, `_PAYLOAD_ERRORS`, `_READ_ERRORS`, `_ENTRY_ERRORS`,
`_SOURCE_ERRORS` et les imports associés sont retirés.

Décompte (analyse AST des handlers `except Exception`) :

| | `backend/src` | avec `main.py` |
| --- | ---: | ---: |
| `pre-cleanup` | 179 | 186 |
| après la passe 2 | 59 | 66 |
| après FIN | 173 | 180 |

### DF.2 Bloquants

- **B1** `IngestionProcessor._maybe_rebuild_bm25_on_drain` : au mieux, FAISS
  tient déjà les chunks ; `_bm25_dirty` reste levé pour la vidange suivante.
- **B2** `get_bm25_store` (`api/dependencies.py`) et `_ensure_bm25_index`
  (`main.py`) : frontières de démarrage, un index BM25 illisible donne un store
  vide. `Bm25LexicalStore.load` enveloppe de nouveau toute erreur (dont
  l'`EOFError` d'un `.npy` tronqué) en `VectorStoreConnectionError`, comme avant.
- **B3** `extractors.py` : boucle par page (page ignorée), déchiffrement,
  handlers externes PDF, DOCX et Markdown (toute erreur devient
  `ExtractionError`), lecture TXT (encodage suivant).

### DF.3 Importants (I1 à I4)

- **I1** `rag_service._hybrid_retrieve` : tout échec de la requête BM25 se
  replie sur le dense seul.
- **I2** `index_maintenance` : `_clean_orphans_if_fragmented` et la resync BM25
  de `remove_document_from_indexes` sont de nouveau deux blocs « au mieux »
  indépendants.
- **I3** `DocumentUpload._reject_queue_full` : nettoyage au mieux, le client
  reçoit toujours le 503.
- **I4** `smtp_client` : `send_escalation_email`, `send_notification_email`
  (`try/except` rétabli), `_send_email`, `_add_attachment`. `/admin/test-email`
  répond de nouveau 200 `success: false` et `/chat/escalate` « Impossible
  d'envoyer votre demande pour le moment... ».

### DF.4 Mineurs restaurés (M2 à M6)

- **M2** `log_parser.py` (28 sites) : handlers par ligne et par fonction, et
  les `try/except` des agrégateurs (`get_chat_metrics`, `get_usage_analytics`,
  `_get_avg_daily_requests`, `_calculate_growth_rate`, `_get_avg_tokens_per_day`,
  `_estimate_monthly_tokens`, `_get_error_rate_period`, `_calculate_health_score`)
  avec leurs valeurs par défaut ; `_parse_timestamp`,
  `_count_recent_error_log_entries`, `_is_recent_error_entry`.
  `logs_reader.py` (6) : `_parse_backend_log_line`, `_parse_frontend_log_line`,
  `_read_log_file`, `get_logs`, `get_available_modules`, `get_logs_summary`
  (`try/except` rétabli). `/admin/analytics/usage` et `/admin/logs` ne
  répondent plus 500 sur une ligne JSON qui n'est pas un objet.
- **M3** `health.disk_usage` : erreur par répertoire.
- **M4** `faiss_store.py` (20 sites) : `_initialize_index`, `_create_new_index`,
  `upsert`, `query`, `delete` (et son `optimize` au mieux), `health_check`,
  `_atomic_write`, `persist`, `load`, `clean_orphans` (persistance, handler
  externe), `_optimize_after_cleanup`, `_create_backup`, `_rotate_backups`,
  `_get_existing_document_ids`, `optimize`, `rebuild_vector_store` (nettoyage au
  mieux, handler externe), `get_document_chunks` ; plus
  `index_maintenance.record_rebuild_failure`. `load` enveloppe de nouveau aussi
  l'`ImportError` d'un pickle hérité : le constructeur repart d'un index vide
  comme avant. Ce comportement d'origine est discutable (la persistance suivante
  écrase l'ancien index) mais il est conservé : aucun changement fonctionnel.
- **M5** `mistral_api.py` : `_make_request`, `generate`, `generate_stream`,
  `_embed_batch` relancent les trois erreurs LLM et enveloppent le reste en
  `LLMAPIError` ; boucle de lots de `embed` ; `health_check`.
- **M6** `jwt_handler.py` : `verify_token` (401 sur toute erreur),
  `verify_password` (`False` : `/auth/change-password` répond de nouveau 400 et
  non 500), `create_access_token` (log puis relance).

### DF.5 Autres sites restaurés par le balayage

`git diff pre-cleanup..HEAD -- backend/src backend/main.py`, chaque
`except Exception` retiré comparé au code actuel :

- `processor.queue_document` (doublon « already exists », relecture du
  document, handler externe : renvoie `False`), `_process_task` (deux
  écritures du statut d'erreur) ;
- `auth.change_password` : 500 « Erreur lors de la mise à jour du fichier de
  configuration » pour toute erreur d'écriture ;
- `config.py` : chargement des settings ;
- `database/connection.py` : `_initialize_database`, `create_tables`,
  `create_tables_async`, `drop_tables`, `init_database` (log puis relance),
  `health_check` (`False`) ;
- `file_watcher/watcher.py` : `_wait_for_file_stability` (`try` externe
  rétabli), `start`, `stop`, `add_directory`, `remove_directory`,
  `scan_existing_files` ;
- `bm25_store.py` : `rebuild`, `query`, `_swap_dir_into_place`, `_persist`,
  `_persist_empty` ;
- `validation_utils.py` : `validate_consistency`, `_get_database_documents`,
  `_get_vector_store_documents`, `_apply_fixes` ;
- services : `rag_service._load_source_documents`,
  `document_reader._read_stored_file`, `document_deletion._remove_stored_file`,
  `index_maintenance._save_validation_report`.

### DF.6 Laissés tels quels (comportement identique)

- `log_parser._get_success_rate_period` et `_get_peak_usage_time` : le corps
  est un `return` de constante, il ne peut pas lever ;
- `get_performance_status` et `create_validation_report` : code mort sans
  appelant, supprimé en D2.5 ;
- les handlers en double des deux routes d'upload : un seul exemplaire dans
  `DocumentUpload` depuis la fusion (D3.4) ;
- équivalences : `asyncio.TimeoutError` devenu `TimeoutError` (alias depuis
  3.11), `except asyncio.CancelledError: pass` devenu `contextlib.suppress`,
  `(OSError, FileNotFoundError)` devenu `OSError`, `BudgetExceededError` devenu
  `BudgetExceeded` (alias), `HTTPException` devenu `RequestRejectedError`
  (traduit à l'identique, D3.3), handlers déplacés dans `_parse_stream_line`,
  `_uvicorn_line_time` et `_filter_since` avec les mêmes types ;
- les `except Exception` gardés par la passe 2 (frontières, sondes, flux SSE,
  transactions) n'avaient pas changé.

### DF.7 Tests

- Injections d'origine rétablies (I5) : `test_auth_jwt_handler.py`
  (`Exception` au lieu d'`InvalidKeyError` et de `ValueError`),
  `test_database_connection.py` (`Exception` au lieu d'`OperationalError`),
  `test_email_service.py` (`_send_email` qui lève `Exception("SMTP Error")`,
  scénario d'origine, et `Exception` au lieu de `SMTPConnectError`),
  `test_file_watcher.py` (5 `Exception` au lieu de `RuntimeError`/`OSError`),
  `test_ingestion_extractors.py` (3 `Exception` au lieu des erreurs pypdf et
  python-docx), `test_ingestion_processor.py` (`RuntimeError("bm25 boom")` et
  `Exception("already exists")`). Aucun autre test de `tests/unit`,
  `tests/performance` ou `tests/conftest.py` n'avait changé d'injection ou de
  chemin d'échec ; les tests supprimés en passe 6 (D6.2) restent supprimés.
- Ajout de `tests/unit/test_failure_fallbacks.py` (26 tests), tirés des scripts
  de reproduction de la revue : B1 (2), B2 (5 : `.npy` tronqué, store renvoyé
  et reconstructible, `_ensure_bm25_index` ne lève pas, `_start_ingestion`
  installe le processeur), B3 (3 : page en `ZeroDivisionError` ignorée,
  `AssertionError` et `OverflowError` converties en `ExtractionError`), M2 (5),
  I1 à I4 (4), M3 à M5 (7). Vérifié sur une copie de `5491ed2` : ces tests et
  les injections rétablies échouent tous sauf un (40 échecs), et passent après
  correction.
- Scripts de reproduction de la revue, lancés sur `backend/` corrigé : B1
  `pipeline success: True`, B2 `get_bm25_store returned a store (degraded
  gracefully)`, B3 `extracted OK (bad page skipped)`, M2 `get_chat_metrics OK`
  et `get_usage_analytics OK` : mêmes sorties que `pre-cleanup`.

### DF.8 M1 : verrou FAISS pris sur la boucle d'événements, non modifié

`_merge_and_attach_rrf_scores` appelle `snapshot_active_chunks()` (verrou
FAISS) depuis la boucle. Mesuré par la revue sur 20 000 chunks : pendant un
`persist()` la fusion bloque la boucle 1,29 s contre environ 1,0 s avec
l'ancien code (le GIL bloquait déjà) ; pendant un rebuild admin, 1,78 s contre
1,96 s. Impact marginal : laissé tel quel (option conservatrice, pas de
nouveau refactor).

### DF.9 M7 : documentation corrigée, code mort conservé

- `CLAUDE.md` et `README.md` : `file_watcher/` est décrit comme non branché
  dans l'application, `WATCH_ENABLED` sans effet (D2.8). Le bloc
  « **critical** » de `CLAUDE.md` n'est pas touché.
- `shared/models.py` : les titres de section signalent les modèles qu'aucune
  route n'utilise ; le titre « Health check and error models » couvre
  `HealthCheckResponse` et `ErrorResponse`, qui sont utilisés.
- `admin.py` : la docstring de `/admin/metrics/chat` n'annonce plus
  « Performance status assessment ».
- `processor.py` : les commentaires citent `BudgetExceeded` au lieu de l'alias.
- Code mort connu, laissé en place (option conservatrice) : modèles Pydantic
  inutilisés (`DocumentUpdate`, `DocumentStatsResponse`, `Configuration*`,
  `AuditLog*`, `DatabaseStatsResponse`, `FileUploadValidation`) ;
  `chat._generate_cache_key`, `ChatResponse`, `SourceReference` (seuls des
  tests unitaires les utilisent) ; `lru_cache` : `get_or_set`,
  `invalidate_pattern`, `get_chat_response`, `set_chat_response` ;
  `monitoring.logger` : fonctions `log_*` ; `password_utils` :
  `generate_secure_password`, `is_password_compromised`,
  `sanitize_password_error_message` ; `database/models.py` :
  `create_*_action`, `get_typed_value` ; `MistralAPIService.health_check` (sans
  appelant) ; le module `file_watcher` et le réglage `watch_enabled`.

### DF.10 M8 : base du diff

Le tag `pre-cleanup` reste local (D0.1) : la description de la PR nomme
explicitement `b1e18e6` comme base.

### DF.11 Porte de qualité

Tentative 1 : porte franchie. 1036 tests (1036 réussis, 0 ignoré ; +26 par
rapport à la passe 8), couverture 88,22 % (contre 86,23 %), ruff 0, format OK,
radon D+ 0, mypy 0, pip-audit OK, vitest 141, build OK, `/health/live` 200
depuis un venv vierge, tests gelés et sommes de l'oracle OK. Les chiffres du
README (tests, couverture, pygount) et de `CLAUDE.md` (tests) sont mis à jour.

### DF.12 Snapshots de l'oracle dépendants du CPU, exclus de la CI GitHub

Premier passage de la CI sur la PR : 7 échecs, tous des écarts de snapshot dans
`tests/oracle/test_retrieval_ranking.py` et `test_chat_stream_events.py`.

Cause : FAISS choisit son noyau SIMD selon le CPU. Les snapshots ont été générés
sur une machine AVX-512, et sur une autre architecture les arrondis de distance
diffèrent et réordonnent des ex aequo. Vérification locale avec
`FAISS_OPT_LEVEL=avx2` : le code de la passe 0 (`8abe5a3`, avant toute
modification du code) échoue sur exactement les mêmes 11 tests que le code
final, et les deux passent avec `avx512`. Ce n'est donc pas une régression,
mais une limite de portabilité de l'oracle.

Les fichiers gelés ne pouvant pas changer, le job pytest de la CI ignore ces
deux modules (commentaire dans `ci.yml`). Ils restent exécutés par
`docs/cleanup/quality_gate.sh` sur la machine de référence. La CI d'avant la
mission n'exécutait aucun test d'oracle, donc elle n'est pas affaiblie.
Commande de la CI vérifiée en local avec `FAISS_OPT_LEVEL=avx2` : 1013 tests
réussis.
