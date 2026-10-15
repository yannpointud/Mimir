# ADR 0001 — Plafond quotidien de dépense IA par réservation

## Statut

Acceptée

## Contexte

- Chaque question déclenche des appels payants à l'API Mistral : un embedding de la question, puis une génération en streaming. Chaque document ingéré déclenche aussi un appel d'embedding, découpé en lots de `embedding_batch_size` textes.
- Le coût réel n'est connu qu'après l'appel, une fois les tokens renvoyés par le fournisseur. Le refus, lui, doit intervenir avant. Pour le chat, il n'est plus possible de répondre 429 une fois la `StreamingResponse` renvoyée, car le statut 200 est déjà parti.
- Les requêtes de chat et le worker d'ingestion consomment le même budget en parallèle. Lire le solde puis décider en Python laisserait passer des dépassements (TOCTOU).

## Décision

Le budget est suivi dans un registre journalier, `llm_budget_ledger`. Il contient une ligne par date UTC au format `YYYY-MM-DD` et une colonne `spent_eur`. `BudgetGuard` le gère en trois opérations :

1. **`reserve(call_type)`** est appelée avant tout appel payant. Dans une même transaction, elle insère la ligne du jour de façon idempotente (`INSERT ... ON CONFLICT DO NOTHING`), puis exécute un unique `UPDATE` conditionnel : `spent_eur = spent_eur + estimate`, `WHERE date = today AND spent_eur + estimate <= cap`. La réservation est acceptée si `rowcount == 1`. La clause `WHERE` sert de garde anti-TOCTOU, et aucun verrou applicatif n'est utilisé.
2. **`finalize(reservation, actual)`** applique le delta `actual - estimate`, sans condition de plafond.
3. **`release(reservation)`** retire l'estimation quand aucun appel n'a été facturé.

Chaque opération ouvre sa propre session courte (`db_manager.get_session_context()`). La réservation est ainsi commitée avant l'appel réseau.

Les paramètres sont définis dans `backend/src/config.py` :
- `daily_budget_eur = 20.0` ;
- estimations forfaitaires `budget_reservation_chat_eur = 0.01` et `budget_reservation_embedding_eur = 0.001` ;
- `llm_price_table`, la grille de prix en euros par million de tokens.

Le plafond effectif est la clé `daily_budget_eur` de la table `configuration` si elle existe, modifiable à chaud par `PUT /api/v1/admin/configuration` (l'écran Admin > Configuration ne permet pas de la modifier). À défaut, c'est la valeur des settings (`.env`) qui s'applique.

L'application diffère selon le flux :
- **Chat.** La route prend une réservation `"chat"` par question, avant de renvoyer le flux. En cas de refus, `budget_exceeded_response()` renvoie un HTTP 429 avec `{"error_code": "budget_exceeded", "error_message": "Plafond quotidien de dépense IA atteint."}`. Cette réponse est renvoyée (et non levée), sinon le gestionnaire global de `HTTPException` réécrirait le corps. La réservation est réglée une seule fois :
  - `finalize` avec le coût cumulé de l'embedding et de la génération ;
  - `release` en cas de cache hit ou si aucun appel n'a abouti ;
  - `release_if_unsettled`, en tâche de fond, si le flux n'est jamais itéré.
- **Ingestion.** Une réservation `"embedding"` est prise par document. En cas de refus, l'exception `BudgetExceeded` est levée et le document passe en statut `error` (« Daily budget exceeded »), sans nouvelle tentative.
- **Modèle absent de la grille.** `compute_cost_eur` lève `ValueError`. `UsageTracker.record` facture alors l'estimation forfaitaire avec `estimated=True`, pour que le plafond continue de se remplir.

## Conséquences

Positives
- Le plafond est vérifié avant l'appel payant, y compris sous concurrence, sans verrou en mémoire.
- Le mécanisme échoue en mode fermé. Un modèle non tarifé n'annule pas la réservation. Un flux interrompu est facturé sur des tokens estimés à partir de la longueur du texte (`len // 4`, `estimated=True`).
- Le tableau de bord (`GET /api/v1/admin/usage`) affiche le même plafond effectif que celui appliqué par la garde.
- La remise à zéro est implicite au changement de jour UTC (nouvelle ligne), sans tâche planifiée.

Négatives
- Le plafond est souple : `finalize` n'est pas bornée, et l'estimation forfaitaire ne reflète pas le coût réel. Le total peut donc dépasser le plafond du montant des requêtes en cours.
- Chaque question entraîne plusieurs écritures SQLite (réservation, lignes `llm_usage`, règlement), que SQLite traite une par une.
- Une réservation non réglée, par exemple après un arrêt brutal du processus, reste imputée jusqu'au lendemain. Aucune réconciliation n'est prévue dans le code.
- `ChatPage.jsx` ne lit que le statut HTTP : un 429 de limitation de débit et un 429 `budget_exceeded` affichent le même message, qui cite les deux causes possibles.

## Où dans le code

- `backend/src/cost/budget_guard.py` : `BudgetGuard` (`reserve`, `finalize`, `release`, `_effective_cap`), `BudgetReservation`, singleton `budget_guard`
- `backend/src/database/repository.py` : `UsageRepository.reserve/finalize/release`, `get_today_ledger`
- `backend/src/database/models.py` : `LlmBudgetLedger`, `LlmUsage` ; migration `backend/src/database/migrations/versions/10d18a595afa_add_llm_usage_and_llm_budget_ledger.py`
- `backend/src/cost/pricing.py` : `compute_cost_eur` ; `backend/src/cost/usage_tracker.py` : `UsageTracker.record`
- `backend/src/api/responses.py` : `budget_exceeded_response` ; `backend/main.py` : `budget_exceeded_handler`
- `backend/src/api/endpoints/chat.py` : `chat_stream` ; `backend/src/services/chat_stream.py` : `ReservationSettlement` ; `backend/src/services/rag_service.py` : `_QuestionSpend`
- `backend/src/ingestion/processor.py` : `_process_document_pipeline`, `_process_task`
- `backend/src/api/endpoints/admin.py` : `get_usage`, `update_configuration` (clé `daily_budget_eur`)
