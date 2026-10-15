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
