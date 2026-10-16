# ADR 0005 — Réponses du chat en streaming Server-Sent Events

## Statut

Acceptée

## Contexte

- Une réponse RAG enchaîne l'embedding de la question, la recherche, puis une génération plafonnée à 800 tokens (`_ANSWER_MAX_TOKENS`, température 0,1). Attendre la réponse complète retarderait d'autant le premier affichage.
- Le flux est unidirectionnel (serveur vers client). La requête est un POST avec un corps JSON et, facultativement, un en-tête `Authorization` (`get_optional_user`).
- Le flux doit cohabiter avec le cache de réponses, le plafond budgétaire (ADR 0001) et la mesure d'usage, y compris quand le client se déconnecte en cours de route.

## Décision

- **Route unique** `POST /api/v1/chat/stream`, qui renvoie une `StreamingResponse` de type `text/event-stream` avec les en-têtes `Cache-Control: no-cache`, `X-Accel-Buffering: no` et `Connection: keep-alive`. Il n'existe pas de route de chat non streamée. L'évaluation RAGAS draine le même pipeline (`RagService.answer_stream`, via `answer_via_stream`), sans passer par HTTP.
- **Contrôles faits avant l'ouverture du flux**, seul moment où un vrai statut HTTP reste possible :
  - limitation de débit à `rate_limit_chat_per_minute = 20` par minute et par client (identifiant JWT, sinon adresse IP) ;
  - réservation budgétaire, qui répond 429 `budget_exceeded` en cas de refus.
- **Format des trames** : `data: <json>\n\n`. Le type de l'événement est porté par le champ `type` du JSON ; le champ SSE `event:` n'est pas utilisé. Les événements arrivent dans cet ordre :
  1. `start` : `{session_id}` ;
  2. `chunk` : `{content}`, une trame par fragment généré ;
  3. `citation` : `{citations}`, table `"N" → source` alignée sur la numérotation `[N]` du prompt ;
  4. `done` : `{sources, confidence_score, cached}`.

  En cas d'échec, une trame `error` porte le message générique « Une erreur interne est survenue. » ; le détail n'apparaît que dans les logs.
- **Cache** : la clé est un SHA-256 de `question.strip().lower()` et de `corpus_version`, qui est l'horodatage `last_updated` de FAISS. Toute ingestion ou suppression invalide donc implicitement le cache. Une réponse n'est mise en cache qu'après l'émission de `done`, jamais en cas d'erreur ou de déconnexion. Sur un cache hit, la réservation est libérée et le serveur rejoue, après `start`, `chunk` (réponse entière), `citation`, puis `done` avec `cached: true`.
- **Déconnexion** : la réservation est réglée exactement une fois, grâce à `ReservationSettlement`, au `finally` du pipeline et à une `BackgroundTask` si le flux n'est jamais itéré. Si l'usage réel n'est pas reçu, les tokens sont estimés et la ligne d'usage est marquée `estimated=True`.
- **Client** : `chatAPI.sendMessageStream` utilise `fetch` en POST, avec un corps JSON et un jeton `Bearer` s'il existe, puis lit le flux avec `response.body.getReader()` et `TextDecoder`. Il découpe le texte sur `\n`, analyse les lignes `data: ` et répartit les événements vers `onStart`, `onChunk`, `onCitation`, `onDone` et `onError`. Un flux clos sans `done` ni `error` est rejeté avec « Stream closed before completion ». `EventSource` n'est pas utilisé : il ne permet ni POST ni en-tête `Authorization`.
- **Proxy** : nginx désactive la mise en mémoire tampon (`proxy_buffering off`, `proxy_cache off`) et fixe `proxy_read_timeout 3600s`, sur `location /api/v1/chat/stream` uniquement.

## Conséquences

Positives
- Le texte s'affiche au fil de la génération. Un cache hit est indiscernable d'un flux frais pour le client.
- Les comptes restent justes même si le client se déconnecte : l'usage est enregistré et la réservation réglée.

Négatives
- Après le premier octet, une erreur ne peut plus être signalée que dans le flux, par la trame `error`. Le statut HTTP reste 200.
- L'analyseur client est fait maison et minimal : pas de champ `event:`, pas de reprise (`Last-Event-ID`), ni de trames multi-lignes.
- Le cache de réponses est en mémoire et local au processus (`ChatCacheService()`, 50 entrées, TTL 1800 s ; les variables `CACHE_*` ne sont pas lues). Il est perdu au redémarrage, ce qui renforce la contrainte d'un seul worker.
- La normalisation de la clé de cache se limite à la casse et aux espaces de début et de fin.
- Un proxy intermédiaire non configuré comme nginx peut mettre le flux en mémoire tampon et le livrer d'un bloc.

## Où dans le code

- `backend/src/api/endpoints/chat.py` : `chat_stream`, `ChatRequest`
- `backend/src/services/chat_stream.py` : `ChatStream.events`, `_replay_cached`, `sse_event`, `SSE_HEADERS`, `ReservationSettlement`
- `backend/src/services/rag_service.py` : `RagService.answer_stream`, `_process_question_with_rag_stream`, `_stream_answer`, `_cache_answer`
- `backend/src/cache/lru_cache.py` : `ChatCacheService.get_stream_response/set_stream_response`, `_generate_stream_key`
- `backend/src/rag_core/implementations/faiss_store.py` : `get_corpus_version`
- `frontend/src/services/api.js` : `chatAPI.sendMessageStream` ; `frontend/src/components/Chat/ChatPage.jsx` : `describeChatError`
- `frontend/nginx.conf` : `location /api/v1/chat/stream`
