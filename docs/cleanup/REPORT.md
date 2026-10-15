# Nettoyage qualité de Mimir : rapport

Mission (`docs/cleanup/MISSION.md`) : rendre le dépôt propre et présentable
sans aucun changement de comportement : mêmes routes, mêmes codes HTTP, mêmes
JSON, mêmes messages renvoyés au client. Une seule correction était autorisée :
le log perdu dans `IngestionProcessor.queue_document`.

- **Base** : `main` au commit `b1e18e6` (tag local `pre-cleanup`, non poussé, voir D0.1).
- **Branche** : `cleanup/qualite`.
- **Décisions** : toutes dans `docs/cleanup/DECISIONS.md`, numérotées D0.1 à D8.8 puis DF.1 à DF.11.

## Avant / après

| Mesure | Avant (`b1e18e6`) | Après |
| --- | --- | --- |
| Tests pytest | 1013 (1010 réussis, 3 ignorés) | 1036 (1036 réussis, 0 ignoré) |
| Couverture `backend/src` | 82,91 % | 88,22 % |
| vitest | 141 | 141 |
| ruff, règles d'origine (`F`, `E9`) | 4 (F401) | 0 |
| ruff, `B`, `SIM`, `UP`, `BLE`, `C90` (max 15) | 1059 alertes (dont 96 B008) | 0 (règles actives, B008 ignoré pour `Depends`, bloquant en CI) |
| radon, fonctions notées D ou pire | 5 | 0 |
| mypy `backend/src` (mode normal) | 132 erreurs dans 23 fichiers | 0 (bloquant en CI) |
| pip-audit | OK, 2 exclusions (pytest 7, orjson) | OK, 1 exclusion (orjson, bloqué par mistralai 0.4.2) |
| Handlers de plus de 100 lignes | 7 | 0 (les 7 visés font de 10 à 49 lignes ; le plus long handler en fait 86) |
| Endpoints en `response_model=Dict` | 17 | 7 |
| `except Exception` dans `backend/src` | 181, sans justification | 173, chacun avec un `noqa: BLE001` justifié |
| Lockfiles avec hashes | non | `requirements.lock`, `requirements-dev.lock` (uv) |
| Dependabot | non | pip, npm (`frontend/`), github-actions |

**Porte de qualité de la dernière passe** (`docs/cleanup/quality_gate.sh`) :
- oracle et tests gelés OK ;
- ruff et format OK ;
- vitest et build du front OK ;
- installation dans un venv vierge, puis `GET /api/v1/health/live` qui répond 200.

## Passes

| Passe | Résultat | Contenu |
| --- | --- | --- |
| 0. Oracle | réussie | 32 tests de caractérisation (`tests/oracle/`). Ils figent :<br>- le contrat OpenAPI ;<br>- les JSON des endpoints principaux et des réponses d'erreur ;<br>- les événements SSE pour 10 questions ;<br>- l'ordre de la recherche dense et hybride ;<br>- les chunks d'ingestion PDF, DOCX, TXT et MD.<br>`tests/oracle` et `tests/integration` sont gelés par `ORACLE.sha256` (72 fichiers). |
| 1. Lint | réussie | ruff `B`, `SIM`, `UP`, `BLE`, `C90` avec autofix sûrs, puis `ruff format` ; ruff bloquant en CI. |
| 2. Erreurs | réussie, puis corrigée en fin de mission | Exceptions métier (`MimirError` → `IngestionError`, `RetrievalError`, `LLMError`, `BudgetExceeded`), traduites en HTTP par des handlers, et `raise ... from e`. Les `except` rétrécis sur les chemins « best effort » ont été rétablis après la revue (voir plus bas). |
| 3. Architecture | réussie | Couche `services/` :<br>- pipeline RAG en étapes nommées ;<br>- les 2 uploads fusionnés ;<br>- 7 handlers ramenés à 60 lignes ou moins ;<br>- `RagService` typé sur les interfaces ;<br>- `Protocol` `LexicalIndex` pour BM25. |
| 4. Typage | réussie | mypy 0 et bloquant en CI ; modèles SQLAlchemy 2.0 ; réponses principales en modèles Pydantic, JSON identique. |
| 5. Commentaires | réussie | 325 docstrings redondantes supprimées ou raccourcies ; références de planning retirées ; commentaires restés en français traduits en anglais. |
| 6. Tests | réussie | 62 tests supprimés (mocks seuls ou doublons, chacun justifié) ; mutmut sur `fusion`, `tokenizer_fr` et `chunking`, et tests ajoutés pour tuer les mutants significatifs. |
| 7. Dépendances | réussie | Lockfiles avec hashes utilisés en CI ; Dependabot ; `aiosqlite` passé en runtime ; pytest 9.1.1, pytest-asyncio 1.4.0 et pytest-cov 7.1.0 ; exclusion pip-audit de pytest retirée. |
| 8. Façade | réussie | README à jour, chiffres pygount compris ; mot de passe admin par défaut retiré du README et de CLAUDE.md ; promesse d'implémentations interchangeables remplacée par un constat ; 5 ADR dans `docs/adr/`. |

Aucune passe n'a été annulée. Chacune a passé la porte à la première tentative.

## Revue finale et corrections

Un sous-agent sans contexte a relu le diff complet (`docs/cleanup/REVIEW.md`).
Il n'a trouvé aucune régression de sécurité : gardes admin, 403 de `JWTBearer`
et masquage des secrets sont inchangés.

Il a relevé 3 points bloquants et 5 importants, qui ont la même cause. La passe 2
avait rétréci des `except Exception` qui garantissaient un repli, et l'oracle
n'injecte que des types d'exception inclus dans les nouvelles listes, donc il ne
pouvait pas les voir. Exemples :
- un échec BM25 à la fin de la file faisait échouer une ingestion déjà écrite dans FAISS ;
- un index BM25 tronqué désactivait l'ingestion au démarrage ;
- une page PDF illisible faisait échouer tout le document ;
- les replis e-mail et analytics étaient perdus ;
- quelques tests unitaires avaient été adaptés au lieu de figer l'ancien comportement.

Corrections (DF.1 à DF.11) :
- **Code** : les replis d'origine sont restaurés à l'identique, avec un `noqa: BLE001` justifié.
- **Tests** : les injections d'erreur d'origine sont rétablies, et 26 tests de non-régression ajoutés (`tests/unit/test_failure_fallbacks.py`).
- **Vérification** : les scripts de reproduction de la revue donnent de nouveau le résultat de `pre-cleanup`.
- **Non corrigé** : le point M1 (verrou FAISS pris sur la boucle d'événements, impact mesuré marginal), noté en DF.8.
- **Conservé** : le code mort recensé, listé en DF.9.

## Décisions principales

- **Contrats préservés** : les points d'entrée internes appelés par les tests gelés gardent leur nom et leur signature, par exemple `rebuild_vector_store`, `delete_document` et les `_check_*_health`.
- **403 conservé** sur jeton absent (surcharge de `make_not_authenticated_error`). SDK Mistral non migré.
- **`file_watcher`** : module non branché dans l'application, conservé. La documentation le dit désormais (D2.8, DF.9).
- **Noms de loggers** : ceux du code déplacé en passe 3 ont changé (D3.7).
- **Hors API** : seul le log de démarrage perd « Jalon 3 » (D5.3).
- **mutmut** : un plugin (`tests/mutmut_aliases.py`) aligne les imports `src.*` et `backend.src.*` (D6.4).
- **Dependabot** ne met à jour que `requirements*.txt` : sur une PR pip, il faut régénérer les deux lockfiles avec la commande inscrite dans leur en-tête (D7.3).

## Anomalies préexistantes relevées, non corrigées

La mission interdit tout changement fonctionnel. Ces anomalies sont donc figées
ou documentées, sans correction :

- `PATCH /api/v1/documents/{id}/preserve` renvoie toujours 500, car la méthode de dépôt appelée n'existe pas (D0.4).
- L'upload admin n'est pas filtré par extension (D0.4).
- La métadonnée `uploaded_by` vaut toujours `"unknown"` (D0.4).
- Plusieurs logs JSON d'ingestion sont perdus quand un chemin est un `Path` (D0.4).
- La suppression d'un document n'est écrite sur disque qu'au prochain `persist()` : un redémarrage entre les deux fait revenir les chunks (D8.7, ADR 0004).
- `chunking.py` (D6.6) :
  - `start_char` reste à 0 après le premier chunk ;
  - la ponctuation de fin de phrase est perdue ;
  - la protection des abréviations est inopérante ;
  - un titre balisé bloque l'attribution des titres suivants.
- `run_pipeline --retrieval-mode dense` de l'évaluation RAGAS mesure en fait l'hybride (D8.6).
- Le changement du mot de passe admin depuis l'interface échoue probablement dans l'image Docker, faute de `.env` à réécrire. C'est une déduction du code, non testée (D8.7).
- Les variables `CACHE_*` ne sont lues nulle part (D8.7).

## Test réel

En cours : le résultat sera ajouté avant l'ouverture de la PR.

## Reproduire

```bash
git diff b1e18e6..cleanup/qualite        # diff complet de la mission
bash docs/cleanup/quality_gate.sh /tmp/gate   # porte de qualité (secrets factices forcés)
sha256sum -c docs/cleanup/ORACLE.sha256  # intégrité des tests gelés
```
