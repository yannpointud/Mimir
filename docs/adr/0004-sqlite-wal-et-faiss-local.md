# ADR 0004 — SQLite en mode WAL et index FAISS en fichiers locaux

## Statut

Acceptée

## Contexte

- Mimir vise un déploiement sur un seul serveur, sur site (`docker-compose.yml`), avec un volume de documents modeste.
- Les données relationnelles comprennent les documents, la configuration, l'audit, l'usage et le registre budgétaire. L'index vectoriel doit servir des lectures concurrentes pendant que le worker d'ingestion écrit.
- L'objectif est d'éviter l'exploitation d'un serveur de base de données ou d'une base vectorielle externe.

## Décision

**SQLite** (`sqlite:///./data/sqlite/mimir.db`)
- Les tables sont créées au démarrage par `Base.metadata.create_all` ; les migrations Alembic sont versionnées à côté (`backend/alembic.ini`, `backend/src/database/migrations/`).
- Un listener `connect` sur le moteur synchrone applique les pragmas suivants (`configure_sqlite_performance`) :
  - `journal_mode=WAL` (piloté par `sqlite_wal_mode = True`) ;
  - `synchronous=NORMAL`, `cache_size=10000`, `temp_store=MEMORY`, `mmap_size=268435456` (256 Mo) ;
  - `busy_timeout=30000` (30 s).
- Le moteur utilise `check_same_thread=False` et `timeout=20`. Les écritures du registre budgétaire et de l'usage sont déportées hors de la boucle d'événements par `asyncio.to_thread` ; les autres accès SQLite des routes restent synchrones.
- La sauvegarde à chaud passe par l'Online Backup API (`sqlite3.Connection.backup()`, compatible WAL), avec des permissions `0o600`. Une rotation conserve `sqlite_backup_max_count = 14` fichiers dans `./data/backups`. Elle est planifiée par cron sur l'hôte (`crontab.mimir.example`). La restauration est vérifiée par `PRAGMA integrity_check` et par une comparaison des nombres de lignes.

**FAISS** (singleton en mémoire, `faiss-cpu==1.12.0`)
- L'index est un `IndexFlatL2` (recherche exhaustive exacte) de dimension `embedding_dimension = 1024`. `IndexFlatL2` renvoie la distance L2 au carré `d`, convertie en similarité par `max(0, 1 - d/2)`. Pour des vecteurs de norme 1, `1 - d/2` est exactement le cosinus. Le code ne normalise pas les vecteurs : la formule repose sur le fait que les embeddings `mistral-embed` sont fournis normalisés, ce que le code ne vérifie pas. Avec des vecteurs non normalisés, le score ne serait plus un cosinus.
- La persistance repose sur deux fichiers : `./data/faiss/index.bin` (`faiss.write_index`) et `./data/faiss/metadata.json`. Ce dernier suit un schéma `MetadataPayload` versionné (`schema_version=1`), validé par pydantic, qui remplace l'ancien format pickle (migré puis renommé en `.pkl.migrated`).
- L'écriture est atomique : fichier temporaire dans le même répertoire, `fsync`, `os.replace`, puis `fsync` du répertoire. L'index est écrit avant les métadonnées : un crash entre les deux ne laisse que des vecteurs orphelins. Le script `scripts/faiss_kill9_persist.py` rejoue ce scénario.
- `chunk_id` correspond à la position du vecteur dans l'index. `delete()` ne fait que poser le drapeau `deleted` en mémoire. `optimize()` reconstruit l'index lorsque plus de 25 % des chunks sont supprimés. Après une suppression de document, un nettoyage des orphelins est aussi déclenché au-delà de 20 % de vecteurs supprimés, sans sauvegarde préalable (`create_backup=False`).
- Deux routes de maintenance :
  - `POST /api/v1/admin/vector-store/rebuild` (`require_admin`) : sauvegarde horodatée de l'index et des métadonnées (rotation `faiss_max_backups = 4`), nettoyage des orphelins, reconstruction, resynchronisation de BM25, vidage des caches et entrée d'audit ;
  - `POST /api/v1/documents/maintenance/validate-consistency?fix_issues=&save_report=` (utilisateur authentifié) : comparaison SQLite/FAISS (`VectorStoreValidator`), corrections optionnelles, rapport JSON.

## Conséquences

Positives
- Aucune dépendance d'infrastructure : SQLite, l'index FAISS, l'index BM25 et les documents vivent dans le volume `mimir-data` monté sur `/app/data`.
- WAL permet des lectures concurrentes pendant une écriture. Le registre budgétaire s'appuie sur la sérialisation des écritures par SQLite (ADR 0001).
- La recherche est exacte, sans paramètre d'index à régler. Les fichiers FAISS restent cohérents après un `kill -9`.

Négatives
- Le déploiement est limité à un seul processus. L'image lance un unique worker uvicorn sans `--reload` (`docker/backend.Dockerfile`), car l'index FAISS, la file d'ingestion et les caches sont locaux au processus. Aucune montée en charge horizontale n'est possible.
- `IndexFlatL2` coûte O(N) par requête et garde tout l'index en RAM (environ N × 1024 × 4 octets). La reconstruction après suppression est complète.
- SQLite et FAISS ne partagent pas de transaction. Leur cohérence repose sur les routes de validation et de reconstruction.
- Une suppression n'est écrite sur disque qu'au prochain `persist()` : prochaine ingestion, reconstruction admin, nettoyage d'orphelins qui en trouve, validation avec corrections, ou `optimize()` automatique au-delà de 25 % de chunks supprimés. Un redémarrage entre-temps recharge les chunks du document supprimé comme actifs : ils redeviennent des résultats denses orphelins (la ligne SQLite a disparu, et l'index BM25, reconstruit et persisté après la suppression, ne les contient plus) jusqu'au prochain nettoyage.
- La sauvegarde planifiée ne couvre que SQLite. Les copies FAISS ne sont faites qu'avant le nettoyage d'orphelins de la reconstruction admin.
- Les pragmas ne sont attachés qu'au moteur synchrone. Le moteur asynchrone (aiosqlite) déclaré dans `connection.py` n'est utilisé nulle part ailleurs.

## Où dans le code

- `backend/src/database/connection.py` : `configure_sqlite_performance`, `DatabaseManager`, `get_session_context`, `init_database`
- `backend/src/config.py` : `database_url`, `sqlite_wal_mode`, `faiss_index_path`, `faiss_metadata_path`, `faiss_max_backups`, `embedding_dimension`, `sqlite_backup_dir`, `sqlite_backup_max_count`
- `backend/src/rag_core/implementations/faiss_store.py` : `FaissVectorStore` (`query`, `delete`, `persist`, `_atomic_write`, `load`, `optimize`, `clean_orphans`, `_create_backup`, `_rotate_backups`, `rebuild_vector_store`), `MetadataPayload`
- `backend/src/rag_core/implementations/validation_utils.py` : `VectorStoreValidator`
- `backend/src/services/index_maintenance.py` : `rebuild_indexes`, `validate_index_consistency`, `remove_document_from_indexes`, `_clean_orphans_if_fragmented`
- `backend/src/api/endpoints/admin.py` : `rebuild_vector_store` ; `backend/src/api/endpoints/documents.py` : `validate_vector_store_consistency`
- `scripts/backup_sqlite.py`, `scripts/restore_sqlite.py`, `scripts/faiss_kill9_persist.py`, `crontab.mimir.example`, `docker-compose.yml`
