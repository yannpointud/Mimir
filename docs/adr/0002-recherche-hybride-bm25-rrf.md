# ADR 0002 — Recherche hybride : FAISS dense + BM25, fusion RRF

## Statut

Acceptée

## Contexte

- La recherche dense (embeddings `mistral-embed`, FAISS) retrouve mal les termes exacts : identifiants, acronymes, noms propres de projets.
- Les scores des deux moteurs ne sont pas comparables. FAISS donne une distance L2 convertie en similarité (`1 - d/2`, un cosinus pour des vecteurs de norme 1, voir ADR 0004), filtrée par `similarity_threshold = 0.5`. BM25 produit un score non borné. Combiner leurs valeurs directement exigerait une normalisation arbitraire.
- Le comportement dense existant devait rester intact et pouvoir être rétabli.

## Décision

- **Second index lexical** `Bm25LexicalStore`, fondé sur `bm25s==0.3.9` (paquet de base, sans PyStemmer) avec les paramètres par défaut de `bm25s.BM25()`. Il est persisté dans `./data/bm25/index` (`bm25_index_path`) via l'API native de bm25s (`allow_pickle=False`). L'écriture passe par un répertoire temporaire, mis en place par `os.replace` (l'ancien index est d'abord écarté, puis restauré en cas d'échec).
- **Tokenizer français léger** `light_french_tokenizer`, appliqué de la même façon à l'indexation et à la requête. Il replie les accents (NFKD), passe en minuscules et découpe sur `[a-z0-9]+`, sans racinisation ni mots vides, pour préserver les identifiants.
- **Index dérivé.** BM25 est entièrement reconstruit à partir des chunks actifs de FAISS (`snapshot_active_chunks()`), qui reste la seule source de vérité. La reconstruction a lieu dans quatre cas :
  - à la fin de la file d'ingestion (une seule fois par lot, via le drapeau `_bm25_dirty`) ;
  - après chaque suppression de document ;
  - lors d'une reconstruction forcée par l'admin ;
  - au démarrage, si l'index est absent et que FAISS contient des chunks.
- **Fusion par Reciprocal Rank Fusion** : `score(d) = Σ 1/(k + rang)`, avec `rrf_k = 60`. Seuls les rangs comptent, pas les scores bruts. Chaque moteur fournit au plus `_HYBRID_POOL_SIZE = 50` candidats ; côté dense, la requête utilise `similarity_floor=0.0` pour obtenir le pool brut. Les chunks pré-inclus par correspondance floue sur le nom de fichier forment une troisième liste classée.
- **Filtrage et confiance propres au mode hybride** (valeurs par défaut de `config.py`). Le filtrage applique `max(rrf_score_threshold = 0.015, meilleur score × (1 − dynamic_filter_percentage = 0.15))`, puis les bornes `min_sources = 1` et `max_sources = 5`. La confiance vaut `min(0.95, 0.8 × min(1, meilleur / (2/(k+1))) + 0.15 × min(1, n/5))`, où `n` est le nombre de résultats.
- **Drapeau réversible** `hybrid_search_enabled`, vrai par défaut. Positionné à `False`, il rétablit le chemin dense, inchangé par l'ajout de l'hybride. Si la requête BM25 lève `RetrievalError`, la liste lexicale est vide : la fusion ne porte alors que sur le pool dense (et la pré-inclusion), avec le seuil et la confiance du mode hybride.
- L'adoption s'appuie sur une mesure RAGAS sur le même échantillon de 40 questions du corpus, sans question adversariale (voir ADR 0003) :
  - `context_recall` passe de 0,6792 à 0,8000 et `context_precision` de 0,5788 à 0,6606 (`scripts/ragas_eval/results/baseline_run_1.json`, `hybrid_run.json`) ;
  - aucune régression sur 5 requêtes à terme exact (`results/exact_term_check.json`) : rappel de 1,0 en dense comme en hybride, ce contrôle établit donc l'absence de régression, pas un gain.

## Conséquences

Positives
- Le mode hybride retrouve les termes exacts sans perdre le rappel sémantique.
- La RRF évite toute calibration entre scores cosinus et BM25.
- Le mode est désactivable par configuration, et une panne de BM25 ne fait pas échouer la requête.

Négatives
- Un second artefact disque doit rester synchronisé avec FAISS. Pendant une ingestion en masse, BM25 est en retard jusqu'à la fin de la file.
- La reconstruction est complète à chaque mutation, ce qui n'est acceptable que pour un corpus modeste.
- En mode hybride, `similarity_score` contient le score RRF : au plus 2/61 ≈ 0,033 avec deux listes, 3/61 ≈ 0,049 avec la liste de pré-inclusion. L'interface l'affiche pourtant en pourcentage de pertinence (`SourcesList.jsx`, `DocumentModal.jsx`).
- Deux seuils distincts coexistent (`similarity_threshold` en dense, `rrf_score_threshold` en hybride), avec des sémantiques différentes.

## Où dans le code

- `backend/mimir/rag_core/fusion.py` : `reciprocal_rank_fusion`
- `backend/mimir/rag_core/tokenizer_fr.py` : `light_french_tokenizer`
- `backend/mimir/rag_core/implementations/bm25_store.py` : `Bm25LexicalStore` (`rebuild`, `query`, `load`, `_swap_dir_into_place`)
- `backend/mimir/rag_core/interfaces.py` : protocole `LexicalIndex`
- `backend/mimir/services/rag_service.py` : `_retrieve`, `_hybrid_retrieve`, `_merge_and_attach_rrf_scores`, `_filter_dynamic_sources`, `_calculate_rrf_confidence`
- `backend/mimir/config.py` : `hybrid_search_enabled`, `rrf_k`, `rrf_score_threshold`, `bm25_index_path`
- `backend/mimir/ingestion/processor.py` : `_maybe_rebuild_bm25_on_drain` ; `backend/mimir/services/index_maintenance.py` : `remove_document_from_indexes`, `rebuild_indexes` ; `backend/mimir/main.py` : `_ensure_bm25_index`
- `backend/mimir/api/dependencies.py` : `get_bm25_store`
