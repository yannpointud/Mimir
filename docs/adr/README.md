# Architecture Decision Records

Ce répertoire consigne les décisions d'architecture de Mimir telles qu'elles sont implémentées dans le code. Chaque ADR suit le même plan : Statut, Contexte, Décision, Conséquences (positives et négatives) et Où dans le code.

| N° | Titre | Résumé |
|----|-------|--------|
| [0001](0001-budget-ia-par-reservation.md) | Plafond quotidien de dépense IA par réservation | Registre journalier SQLite : réservation conditionnelle atomique avant chaque appel Mistral, règlement après l'appel, 429 `budget_exceeded` si le plafond est atteint. |
| [0002](0002-recherche-hybride-bm25-rrf.md) | Recherche hybride FAISS + BM25, fusion RRF | Index lexical BM25 (tokenizer français sans racinisation) dérivé de FAISS, fusionné avec la recherche dense par Reciprocal Rank Fusion (k = 60), désactivable par drapeau. |
| [0003](0003-evaluation-ragas.md) | Évaluation RAG hors ligne avec RAGAS | Jeu de référence gelé, pipeline réel rejoué en deux étapes et deux venvs, juge Mistral, exécuté à la demande et hors CI. |
| [0004](0004-sqlite-wal-et-faiss-local.md) | SQLite en mode WAL et index FAISS local | Base SQLite WAL et index `IndexFlatL2` persisté de façon atomique sur disque : déploiement mono-serveur à un seul worker. |
| [0005](0005-streaming-sse.md) | Réponses du chat en streaming SSE | `POST /api/v1/chat/stream` émet `start`, `chunk`, `citation` et `done` (ou `error`), avec un cache dépendant de la version du corpus et un client `fetch` + `ReadableStream`. |

## Ajouter un ADR

Numéroter à la suite (`NNNN-titre-court.md`), garder le même plan, citer les fichiers et symboles concernés, puis ajouter une ligne à ce tableau. Une décision remplacée n'est pas supprimée : passer son statut à « Remplacée par NNNN ».
