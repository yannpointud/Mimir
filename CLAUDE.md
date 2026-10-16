# Mimir - Project Guide

RAG chatbot for enterprise documentation. Python/FastAPI backend, React frontend.


**critical**
Ne jamais pousser sur main. Push autorisé uniquement sur une branche dédiée, livrée par pull request.
INTERDICTION DE MODIFIER AILLEURS QUE DANS LE DOSSIER PROJET
Le dossier scripts/ contient les scripts de tests de developpements temporaire
Tous les commentaires dans le code doivent etres en anglais
Pour lancer serveur et arreter : 
start-servers.sh
stop-servers.sh


## Stack
- **Backend**: Python 3.13, FastAPI, SQLite (WAL), FAISS, Mistral API
- **Frontend**: React 18, Vite 8, Tailwind CSS, Axios
- **Auth**: JWT (PyJWT) + Argon2 (pwdlib, bcrypt legacy)
- **Tests**: pytest (backend), vitest (frontend)

## Project Structure

```
backend/
├── alembic.ini                      # Alembic migrations config
├── mimir/                           # Python package (pip install -e .)
│   ├── main.py                      # FastAPI entry point
│   ├── config.py                    # Pydantic settings (reads .env)
│   ├── api/
│   │   ├── endpoints/               # REST routes: chat, documents, admin, auth, health, logs
│   │   ├── middleware/               # CORS, rate limiting
│   │   ├── responses.py             # Shared HTTP responses (budget 429)
│   │   └── dependencies.py          # Dependency injection (builds the concrete services)
│   ├── auth/                        # JWT handler, password utils, auth middleware
│   ├── cache/                       # LRU cache with TTL
│   ├── cost/                        # Daily AI budget (reservation ledger), price table, usage tracker
│   ├── database/
│   │   ├── connection.py            # SQLite connection management
│   │   ├── models.py                # SQLAlchemy ORM models
│   │   ├── repository.py            # Repository pattern (CRUD)
│   │   └── migrations/              # Alembic migrations
│   ├── email_service/               # SMTP client for escalations
│   ├── ingestion/
│   │   ├── processor.py             # Ingestion pipeline orchestrator
│   │   ├── extractors.py            # Text extraction (PDF, DOCX, TXT, MD)
│   │   ├── chunking.py              # Text splitting with overlap
│   │   └── async_queue_manager.py   # Sequential async queue
│   ├── llm_interface/
│   │   ├── interfaces.py            # LLM/Embedding abstractions
│   │   └── implementations/mistral_api.py  # Mistral API (chat + embeddings)
│   ├── rag_core/
│   │   ├── interfaces.py            # AbstractVectorStore, LexicalIndex Protocol
│   │   ├── fusion.py                # Reciprocal Rank Fusion
│   │   ├── tokenizer_fr.py          # BM25 tokenizer (accent folding, no stemming)
│   │   └── implementations/         # faiss_store.py, bm25_store.py, validation_utils.py
│   ├── security/                    # Admin password resolution, startup secret checks
│   ├── services/                    # Route logic: RAG pipeline, SSE stream, upload, deletion, index maintenance
│   ├── monitoring/                  # Structured JSON logging, SMTP error alerting
│   ├── shared/                      # models.py (Pydantic DTOs), errors.py (domain exceptions), constants.py
│   └── utils/                       # Log file reader (logs_reader.py)
├── data/                            # Runtime data (gitignored)
│   ├── documents/                   # Uploaded files (hashed filenames)
│   ├── faiss/                       # index.bin + metadata.json
│   ├── bm25/                        # BM25 lexical index (derived from FAISS)
│   └── sqlite/                      # mimir.db
└── logs/                            # App logs (gitignored)

frontend/
├── src/
│   ├── App.jsx                      # Router setup
│   ├── components/
│   │   ├── Chat/                    # ChatPage, MessageBubble, SourcesList, EscalationDialog
│   │   ├── Admin/                   # AdminDashboard, DocumentsList, UploadZone, LogViewer
│   │   └── Common/                  # DocumentModal, Layout, ProtectedRoute
│   ├── services/api.js              # Axios client (all API calls)
│   ├── hooks/                       # useAuth (auth context + JWT), useDocumentsList (admin documents list)
│   ├── utils/                       # storage.js, logger.js, auth.js, helpers.js
│   └── test/                        # vitest tests (150 tests)
└── package.json

tests/                               # pytest test suite (921 tests, run from the repo root)
├── conftest.py                      # Shared fixtures (temporary data paths for the whole run)
├── unit/                            # Unit tests (727)
├── integration/                     # API + workflow tests (150)
├── oracle/                          # Characterization snapshots (32)
└── performance/                     # Cleanup, budget and FAISS concurrency tests (12)

scripts/
├── local_ci.sh                      # ruff + mypy + pytest + pip-audit
├── backup_sqlite.py, restore_sqlite.py  # SQLite online backup and verified restore
├── ragas_eval/                      # Offline RAGAS evaluation (separate venv)
└── generate_test_documents.py       # Test data generator (uses Mistral API)

docs/adr/                            # Architecture decision records
```

`tests/oracle/` pins the observable behavior (OpenAPI contract, JSON responses, SSE events, retrieval ranking, chunks) in JSON snapshots. Regenerate them with `ORACLE_UPDATE=1 pytest tests/oracle` only for an intended behavior change, and review the snapshot diff.

## Key Patterns
- **Repository pattern** for all DB access (`database/repository.py`)
- **Abstract interfaces** `AbstractLLMService`, `AbstractVectorStore` and the `LexicalIndex` Protocol, with a single implementation each (Mistral, FAISS, BM25). `RagService` and `IngestionProcessor` are typed on them, but `api/dependencies.py` instantiates the concrete classes directly, and the maintenance paths (rebuild, orphan cleanup, consistency check, document chunks) call FAISS-specific methods: another provider would need code changes, not just configuration
- **Services layer** (`services/`): routes stay thin and delegate to services; domain errors (`shared/errors.py`) and `RequestRejectedError` are translated to HTTP at the API layer
- **Daily AI budget** reserved atomically before every paid Mistral call (`cost/budget_guard.py`, see `docs/adr/0001`)
- **Streaming SSE** for chat responses (`POST /api/v1/chat/stream`)
- **SessionStorage** for chat history (sources stored without chunk_text, modal loads via API)
- **Async queue** for sequential document ingestion (prevents API saturation)

## Commands
```bash
# Start/stop servers
./start-servers.sh          # Backend :8000 + Frontend :3000
./stop-servers.sh

# Tests
pytest                      # All tests with coverage
pytest tests/unit/ -v       # Unit only
cd frontend && npx vitest run   # Frontend tests

# Quality (the CI runs the same checks on every pull request)
bash scripts/local_ci.sh    # ruff check + ruff format --check + mypy backend/mimir + pytest + pip-audit
cd frontend && npm run lint && npx vitest run && npm run build

# API docs
http://localhost:8000/docs   # Swagger UI
```

## Environment
- `backend/.env.example` — copy to `backend/.env` and configure
- Required: `MISTRAL_API_KEY`, `JWT_SECRET_KEY`
- Admin account `admin`: password set with `ADMIN_PASSWORD` (clear text, hashed at startup, takes precedence) or `ADMIN_PASSWORD_HASH` (Argon2 hash); see README "Mot de passe admin". With `ENVIRONMENT=production`, startup refuses an unchanged `JWT_SECRET_KEY` or admin password
- The backend reads the `.env` of its working directory (`backend/` with `start-servers.sh`); an unknown key stops startup (`extra="forbid"`)
- Frontend logging: warnings and errors always reach the console; `VITE_ENABLE_LOGS`, `VITE_DEBUG_MODE` and `VITE_LOG_TO_FILE` add info, debug and backend forwarding (`frontend/.env.example`)
- Lockfiles: `requirements.lock` / `requirements-dev.lock` are generated from `requirements*.txt` (regeneration command in their header)

## Quality Gates
- ruff rules F, E9, B, SIM, UP, BLE, C90, TID (absolute imports only), I, RUF; ruff format
- mypy with `disallow_untyped_defs` and `check_untyped_defs` on `backend/mimir`
- pytest (`pytest.ini`) fails under 85 % coverage of `backend/mimir`, and a DeprecationWarning raised from `mimir` or `tests` is an error
- CI jobs (`.github/workflows/ci.yml`, on pull requests and after each merge into main): ruff, mypy, pytest, pip-audit, frontend (ESLint, vitest, build, `npm audit --omit=dev --audit-level=high`)
