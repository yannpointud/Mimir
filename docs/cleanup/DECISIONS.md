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

### D2.4 Exceptions précises ailleurs

Les modules internes capturent désormais des types précis : erreurs
d'infrastructure des index (`INDEX_BACKEND_ERRORS` dans
`rag_core/interfaces.py`), `SQLAlchemyError`, `OSError`, erreurs de
bibliothèques (`pypdf.errors.PyPdfError`, `docx.opc.exceptions.OpcError`,
`aiosmtplib.SMTPException`, `jwt.PyJWTError`, `pwdlib.exceptions.PwdlibError`,
`jinja2.TemplateError`, `aiohttp.ClientError`) ou les familles métier. Les
chemins qui relançaient en enveloppant une exception métier le font toujours
(mêmes messages), et `raise ... from e` est systématique.

### D2.5 Code mort retiré au passage

Trois fonctions sans aucun appelant, dont la seule raison d'être des
`except Exception` était défensive : `create_validation_report`
(`validation_utils.py`), `get_performance_status` (`log_parser.py`) et les
`try/except` des agrégateurs de `log_parser.py` et `logs_reader.py` dont le
corps ne peut pas lever (calculs sur des valeurs déjà protégées).

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
