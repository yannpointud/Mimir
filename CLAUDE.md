# Mimir - Project Guide

RAG chatbot for enterprise documentation. Python/FastAPI backend, React frontend.


**critical**
INTERDICTION DE PASSER DES PUSH GITHUB On ne travaille qu'en local
INTERDICTION DE MODIFIER AILLEURS QUE DANS LE DOSSIER PROJET
Le dossier scripts/ contient les scripts de tests de developpements temporaire
Tous les commentaires dans le code doivent etres en anglais
Pour lancer serveur et arreter : 
start-servers.sh
stop_servers.sh


## Stack
- **Backend**: Python 3.11, FastAPI, SQLite (WAL), FAISS, Mistral API
- **Frontend**: React 18, Vite, Tailwind CSS, Axios
- **Auth**: JWT (PyJWT) + Argon2 (pwdlib, bcrypt legacy)
- **Tests**: pytest (backend), vitest (frontend)

## Project Structure

```
backend/
├── main.py                          # FastAPI entry point
├── src/
│   ├── config.py                    # Pydantic settings (reads .env)
│   ├── api/
│   │   ├── endpoints/               # REST routes: chat, documents, admin, auth, health, logs
│   │   ├── middleware/               # CORS, rate limiting
│   │   └── dependencies.py          # Dependency injection
│   ├── auth/                        # JWT handler, password utils, auth middleware
│   ├── cache/                       # LRU cache with TTL
│   ├── database/
│   │   ├── connection.py            # SQLite connection management
│   │   ├── models.py                # SQLAlchemy ORM models
│   │   ├── repository.py            # Repository pattern (CRUD)
│   │   └── migrations/              # Alembic migrations
│   ├── email_service/               # SMTP client for escalations
│   ├── file_watcher/                # Folder monitoring for auto-ingestion
│   ├── ingestion/
│   │   ├── processor.py             # Ingestion pipeline orchestrator
│   │   ├── extractors.py            # Text extraction (PDF, DOCX, TXT, MD)
│   │   ├── chunking.py              # Text splitting with overlap
│   │   └── async_queue_manager.py   # Sequential async queue
│   ├── llm_interface/
│   │   ├── interfaces.py            # LLM/Embedding abstractions
│   │   └── implementations/mistral_api.py  # Mistral API (chat + embeddings)
│   ├── rag_core/
│   │   ├── interfaces.py            # Vector store abstractions
│   │   └── implementations/faiss_store.py  # FAISS index management
│   ├── monitoring/                  # Structured JSON logging
│   ├── shared/models.py             # Pydantic DTOs
│   └── utils/                       # Log parser, logs reader
├── data/                            # Runtime data (gitignored)
│   ├── documents/                   # Uploaded files (hashed filenames)
│   ├── faiss/                       # index.bin + metadata.json
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
│   ├── hooks/useAuth.jsx            # Auth context + JWT management
│   └── utils/                       # storage.js, logger.js, auth.js, helpers.js
└── package.json

tests/                               # pytest test suite
├── conftest.py                      # Shared fixtures
├── unit/                            # Unit tests (~800 tests)
├── integration/                     # API + workflow tests
└── performance/                     # Cleanup performance tests

scripts/
├── generate_test_documents.py       # Test data generator (uses Mistral API)
└── test_log_levels.py               # Log level verification
```

## Key Patterns
- **Repository pattern** for all DB access (`database/repository.py`)
- **Interface abstractions** for LLM and vector store (easy to swap implementations)
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
cd frontend && npx vitest   # Frontend tests

# API docs
http://localhost:8000/docs   # Swagger UI
```

## Environment
- `.env.example` at root — copy to `.env` and configure
- Required: `MISTRAL_API_KEY`, `JWT_SECRET_KEY`
- Default admin: username `admin` / password `Abc1234` (modifiable via l'interface Admin > Configuration)
