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
