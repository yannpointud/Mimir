"""
Shared harness of the characterization oracle (fixtures are exposed by
``conftest.py``).

The oracle pins the observable behaviour of Mimir before the cleanup mission:
HTTP contract, JSON bodies, SSE event sequences, retrieval rankings and
ingestion chunks. Every test of this package compares the live output with a
frozen snapshot under ``tests/oracle/snapshots``.

Everything is hermetic and deterministic:

- a temporary SQLite database (the global ``db_manager`` is redirected to it,
  exactly like the integration tests do), temporary FAISS/BM25 indexes and a
  temporary upload directory;
- a fake LLM: bag-of-words hashed embeddings and a streamed answer derived
  from a hash of the prompt actually sent, so any change in context assembly
  shows up in the snapshot;
- fake budget guard and usage tracker (no ledger writes);
- the app is driven through ``TestClient`` without running its lifespan, with
  the service singletons replaced through ``app.dependency_overrides``.

Volatile values (timestamps, durations, tokens, generated ids, temporary
paths) are neutralised by :func:`normalize` before comparison.

Snapshots are written only when ``ORACLE_UPDATE=1`` is set; regenerate them
only for an intended behavior change, and review the snapshot diff.
"""

import asyncio
import hashlib
import inspect
import json
import math
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mimir.config import settings
from mimir.cost.budget_guard import BudgetReservation
from mimir.cost.usage_tracker import UsageTracker
from mimir.database.connection import db_manager
from mimir.database.repository import DocumentRepository
from mimir.ingestion.chunking import ChunkingConfig
from mimir.ingestion.processor import IngestionProcessor
from mimir.llm_interface.interfaces import EmbeddingResponse, LLMAPIError
from mimir.rag_core.implementations.bm25_store import Bm25LexicalStore
from mimir.rag_core.implementations.faiss_store import FaissVectorStore

ORACLE_DIR = Path(__file__).resolve().parent
CORPUS_DIR = ORACLE_DIR / "corpus"
FIXTURES_DIR = ORACLE_DIR / "fixtures"
SNAPSHOT_DIR = ORACLE_DIR / "snapshots"

ORACLE_ADMIN_PASSWORD = "Oracle-Admin#2026"
FAKE_CHAT_MODEL = "mistral-small-latest"
FAKE_EMBED_MODEL = "mistral-embed"

# The ten fixed questions shared by the SSE and retrieval oracles.
QUESTIONS: list[str] = [
    "Combien de jours de télétravail sont autorisés par semaine ?",
    "Quelle est la procédure pour déclarer une note de frais ?",
    "Que faire en cas de perte d'un ordinateur portable ?",
    "Comment poser des congés payés ?",
    "Que contient la politique de télétravail ?",
    "Quel est le statut du ticket JIRA-4521 ?",
    "Quelle est la longueur minimale d'un mot de passe ?",
    "Qui contacter le premier jour d'arrivée ?",
    "Quel est le plafond de remboursement d'un repas d'affaires ?",
    "Quelle est la recette de la tarte aux pommes ?",
]

# Corpus documents, in upload order (document ids follow this order).
CORPUS_FILES: list[str] = [
    "politique_teletravail.md",
    "guide_securite_informatique.txt",
    "procedure_notes_de_frais.md",
    "reglement_conges_payes.txt",
    "onboarding_nouveaux_arrivants.md",
    "incident_majeur_JIRA-4521.txt",
]


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_STOPWORDS = frozenset(
    [
        "a",
        "à",
        "au",
        "aux",
        "avec",
        "c",
        "ce",
        "ces",
        "cet",
        "cette",
        "d",
        "dans",
        "de",
        "des",
        "du",
        "elle",
        "elles",
        "en",
        "est",
        "et",
        "être",
        "il",
        "ils",
        "j",
        "l",
        "la",
        "le",
        "les",
        "leur",
        "leurs",
        "m",
        "mais",
        "n",
        "ne",
        "nous",
        "on",
        "ou",
        "où",
        "par",
        "pas",
        "pour",
        "qu",
        "que",
        "quel",
        "quelle",
        "quelles",
        "quels",
        "qui",
        "s",
        "sa",
        "se",
        "ses",
        "son",
        "sont",
        "sur",
        "t",
        "un",
        "une",
        "vous",
        "y",
    ]
)

# Share of the squared norm carried by a direction common to every text:
# cosine = _COMMON_WEIGHT + (1 - _COMMON_WEIGHT) * cosine_of_word_bags, so
# texts sharing a few topical words clear the default 0.5 dense threshold
# while unrelated texts stay below it.
_COMMON_WEIGHT = 0.4


def fake_embedding(text: str, dim: int | None = None) -> list[float]:
    """Deterministic bag-of-words embedding (unit L2 norm).

    Each lower-cased non-stopword token is hashed (SHA-256, never Python's
    salted hash) into one of the dimensions 1..dim-1; dimension 0 carries a
    direction shared by every text. Texts sharing words therefore get close
    vectors, which gives the dense retriever a meaningful, reproducible
    ranking.
    """
    dim = dim or settings.embedding_dimension
    bag = [0.0] * dim
    for token in _TOKEN_RE.findall(text.lower()):
        if token in _STOPWORDS:
            continue
        index = 1 + int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % (dim - 1)
        bag[index] += 1.0
    norm = math.sqrt(sum(v * v for v in bag))
    vector = [0.0] * dim
    vector[0] = math.sqrt(_COMMON_WEIGHT)
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    scale = math.sqrt(1.0 - _COMMON_WEIGHT) / norm
    for index, value in enumerate(bag):
        if value:
            vector[index] = value * scale
    return vector


class FakeLLMService:
    """Deterministic stand-in for MistralAPIService (no network)."""

    def __init__(self, fail_embed: bool = False, fail_after_first_chunk: bool = False):
        self.fail_embed = fail_embed
        self.fail_after_first_chunk = fail_after_first_chunk
        self.embed_calls: list[list[str]] = []
        self.generate_calls: list[dict[str, Any]] = []

    @property
    def model_name(self) -> str:
        return FAKE_CHAT_MODEL

    @property
    def embedding_dimension(self) -> int:
        return settings.embedding_dimension

    async def embed(self, texts, session_id=None, rag_debug=None, **kwargs):
        self.embed_calls.append(list(texts))
        if self.fail_embed:
            raise LLMAPIError("oracle: embedding failure")
        return EmbeddingResponse(
            embeddings=[fake_embedding(t) for t in texts],
            model=FAKE_EMBED_MODEL,
            usage_tokens=sum(len(t) for t in texts) // 4,
            prompt_tokens=sum(len(t) for t in texts) // 4,
            completion_tokens=0,
        )

    async def generate_stream(
        self,
        prompt,
        system_prompt=None,
        max_tokens=None,
        temperature=None,
        session_id=None,
        rag_debug=None,
        usage_out=None,
        **kwargs,
    ):
        self.generate_calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        digest = hashlib.sha256(f"{system_prompt}\n---\n{prompt}".encode()).hexdigest()[:16]
        context_items = len(re.findall(r"^\[\d+\] ", system_prompt or "", re.MULTILINE))
        yield "Réponse fondée sur "
        if self.fail_after_first_chunk:
            raise LLMAPIError("oracle: generation failure")
        yield f"{context_items} extrait(s) "
        yield f"[prompt:{digest}]"
        if usage_out is not None:
            usage_out.update({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})

    async def close(self):
        return None


class FakeBudgetGuard:
    """Budget guard that always grants (or always refuses) a reservation."""

    def __init__(self, exhausted: bool = False):
        self.exhausted = exhausted
        self.calls: list[str] = []

    def reserve(self, kind):
        self.calls.append(f"reserve:{kind}")
        if self.exhausted:
            return None
        return BudgetReservation(today="2026-01-01", estimate_eur=0.01)

    def finalize(self, reservation, actual_cost_eur):
        self.calls.append("finalize")

    def release(self, reservation):
        self.calls.append("release")


class FakeUsageTracker:
    """Usage tracker that persists nothing and prices every call at zero.

    Calls are recorded as named arguments bound to the real
    UsageTracker.record signature, so positional and keyword call styles
    compare equal.
    """

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def record(self, *args, **kwargs):
        bound = inspect.signature(UsageTracker.record).bind(None, *args, **kwargs)
        bound.apply_defaults()
        call = dict(bound.arguments)
        call.pop("self")
        self.calls.append(call)
        return 0.0


class RecordingRagDebug:
    """Records every rag_debug call (method name, args, kwargs)."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return None

        return _record

    def last(self, name):
        for call_name, args, kwargs in reversed(self.calls):
            if call_name == name:
                return args, kwargs
        return None


# --------------------------------------------------------------------------
# Normalisation and snapshots
# --------------------------------------------------------------------------

VOLATILE_KEYS = {
    "timestamp",
    "created_at",
    "updated_at",
    "indexed_at",
    "last_updated",
    "access_token",
    "token_issued_at",
    "token_expires_at",
    "iat",
    "exp",
    "session_id",
    "escalation_id",
    "response_time_ms",
    "duration_ms",
    "duration_seconds",
    "search_time_ms",
    "processing_time",
    "started_at",
    "completed_at",
    "validation_timestamp",
    "report_path",
    "date",
}

_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")
_DURATION_RE = re.compile(r"Completed in \d+ms")


def normalize(value: Any, tmp_root: str | None = None) -> Any:
    """Neutralise volatile values so snapshots stay deterministic."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in VOLATILE_KEYS and item is not None:
                out[key] = f"<{key}>"
            else:
                out[key] = normalize(item, tmp_root)
        return out
    if isinstance(value, list):
        return [normalize(item, tmp_root) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, str):
        text = value
        if tmp_root:
            text = text.replace(tmp_root, "<TMP>")
        text = _ISO_TS_RE.sub("<TS>", text)
        text = _DURATION_RE.sub("Completed in <N>ms", text)
        return text
    return value


def shape(value: Any) -> Any:
    """Structure of a JSON value (keys and types), for machine-dependent data."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    if value is None:
        return "null"
    return type(value).__name__


def assert_snapshot(name: str, actual: Any) -> None:
    """Compare ``actual`` with ``snapshots/<name>.json`` (written when ORACLE_UPDATE=1)."""
    path = SNAPSHOT_DIR / f"{name}.json"
    serialized = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if os.environ.get("ORACLE_UPDATE") == "1":
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
        return
    assert path.exists(), f"missing oracle snapshot {path.name} (run once with ORACLE_UPDATE=1)"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert json.loads(serialized) == expected, f"oracle snapshot mismatch: {path.name}"


def parse_sse(body: str) -> list[dict[str, Any]]:
    """Decode every ``data:`` line of an SSE body."""
    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:") :].strip()))
    return events


# --------------------------------------------------------------------------
# Hermetic environment
# --------------------------------------------------------------------------

_PATCHED_SETTINGS = (
    "database_url",
    "data_dir",
    "upload_dir",
    "faiss_index_path",
    "faiss_metadata_path",
    "bm25_index_path",
    "sqlite_backup_dir",
    "mistral_api_key",
    "mistral_model",
    "mistral_embedding_model",
    "admin_password_hash",
    "environment",
    "hybrid_search_enabled",
    "filename_pre_inclusion",
)


class OracleEnv:
    """A fully isolated Mimir instance driven through the FastAPI app."""

    def __init__(self, tmp: Path):
        from mimir.api import dependencies
        from mimir.auth.jwt_handler import jwt_handler
        from mimir.main import app
        from mimir.services.rag_service import RagService

        self.tmp = tmp
        self.tmp_root = str(tmp)
        self.app = app
        self.llm = FakeLLMService()
        self.budget_guard = FakeBudgetGuard()
        self.usage_tracker = FakeUsageTracker()
        self.rag_debug = RecordingRagDebug()
        self.vector_store = FaissVectorStore(
            dimension=settings.embedding_dimension,
            index_path=settings.faiss_index_path,
            metadata_path=settings.faiss_metadata_path,
            similarity_threshold=settings.similarity_threshold,
            index_type="FlatL2",
        )
        self.bm25_store = Bm25LexicalStore(index_path=settings.bm25_index_path)
        self.chat_cache = dependencies.get_chat_cache_service()
        self.rag_service = RagService(
            llm_service=self.llm,
            vector_store=self.vector_store,
            rag_debug=self.rag_debug,
            budget_guard=self.budget_guard,
            usage_tracker=self.usage_tracker,
            chat_cache=self.chat_cache,
            bm25_store=self.bm25_store,
        )
        self.processor = None
        self.new_processor()

        self._overrides = {
            dependencies.get_vector_store: lambda: self.vector_store,
            dependencies.get_bm25_store: lambda: self.bm25_store,
            dependencies.get_ingestion_processor: lambda: self.processor,
            dependencies.get_rag_service: lambda: self.rag_service,
            dependencies.get_budget_guard: lambda: self.budget_guard,
            dependencies.get_rag_debug_service: lambda: self.rag_debug,
        }
        app.dependency_overrides.update(self._overrides)

        self.client = TestClient(app, raise_server_exceptions=False)
        self.admin_token = jwt_handler.create_access_token({"sub": "admin", "user_type": "admin"})
        self.user_token = jwt_handler.create_access_token({"sub": "reader", "user_type": "user"})
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        self.user_headers = {"Authorization": f"Bearer {self.user_token}"}

    def new_processor(self) -> IngestionProcessor:
        """Fresh ingestion processor (its asyncio queue binds to one event loop)."""
        self._processor_session = db_manager.get_session()
        self.processor = IngestionProcessor(
            llm_service=self.llm,
            vector_store=self.vector_store,
            document_repository=DocumentRepository(self._processor_session),
            chunking_config=ChunkingConfig(
                chunk_size=settings.max_chunk_size,
                overlap=settings.chunk_overlap,
                section_title_tracking=settings.structure_aware_chunking_enabled,
            ),
            max_file_size_mb=settings.max_file_size_mb,
            max_chunks_per_doc=settings.max_chunks_per_doc,
            budget_guard=self.budget_guard,
            usage_tracker=self.usage_tracker,
            bm25_store=self.bm25_store,
        )
        return self.processor

    def document_statuses(self) -> dict[int, str]:
        session = db_manager.get_session()
        try:
            return {doc.id: doc.status for doc in DocumentRepository(session).get_all()}
        finally:
            session.close()

    def drain_ingestion(self, timeout: float = 60.0) -> None:
        """Run the ingestion worker until every queued document is processed."""
        processor = self.processor

        async def _run():
            await processor.start()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                busy = [
                    s for s in self.document_statuses().values() if s in ("pending", "indexing")
                ]
                if not busy and processor.get_queue_size() == 0:
                    break
                await asyncio.sleep(0.05)
            await processor.stop(timeout=10.0)

        asyncio.run(_run())
        self._processor_session.close()
        self.new_processor()

    def upload(
        self,
        path: Path,
        route: str = "/api/v1/documents/upload",
        preserve: bool = False,
        content: bytes | None = None,
    ):
        data = path.read_bytes() if content is None else content
        return self.client.post(
            route,
            headers=self.admin_headers,
            files={"file": (path.name, data, "application/octet-stream")},
            data={"preserve": "true" if preserve else "false"},
        )

    def ingest_corpus(self) -> dict[str, int]:
        """Upload the fixed corpus, ingest it and return filename -> document id."""
        from mimir.api.middleware.rate_limit import limiter

        ids = {}
        limiter_enabled = limiter.enabled
        limiter.enabled = False
        try:
            for name in CORPUS_FILES:
                response = self.upload(CORPUS_DIR / name)
                assert response.status_code == 200, response.text
                ids[name] = response.json()["id"]
        finally:
            limiter.enabled = limiter_enabled
        self.drain_ingestion()
        assert set(self.document_statuses().values()) == {"indexed"}
        return ids

    def stream(self, question: str, **extra) -> list[dict[str, Any]]:
        payload = {"question": question, "include_sources": True}
        payload.update(extra)
        with self.client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
            assert response.status_code == 200, response.read()
            body = "".join(chunk for chunk in response.iter_text())
        return parse_sse(body)

    def close(self) -> None:
        for key in self._overrides:
            self.app.dependency_overrides.pop(key, None)
        self.client.close()
        self._processor_session.close()


def _make_env() -> OracleEnv:
    from mimir.auth.jwt_handler import jwt_handler

    tmp = Path(tempfile.mkdtemp(prefix="mimir_oracle_"))
    saved_settings = {name: getattr(settings, name) for name in _PATCHED_SETTINGS}
    settings.data_dir = str(tmp / "data")
    settings.upload_dir = str(tmp / "data" / "documents")
    settings.faiss_index_path = str(tmp / "data" / "faiss" / "index.bin")
    settings.faiss_metadata_path = str(tmp / "data" / "faiss" / "metadata.json")
    settings.bm25_index_path = str(tmp / "data" / "bm25" / "index")
    settings.sqlite_backup_dir = str(tmp / "data" / "backups")
    settings.mistral_api_key = "test-key"
    settings.mistral_model = FAKE_CHAT_MODEL
    settings.mistral_embedding_model = FAKE_EMBED_MODEL
    settings.admin_password_hash = jwt_handler.hash_password(ORACLE_ADMIN_PASSWORD)
    settings.environment = "test"
    settings.hybrid_search_enabled = True
    settings.filename_pre_inclusion = True
    settings.database_url = f"sqlite:///{tmp / 'data' / 'sqlite' / 'oracle.db'}"
    settings.ensure_directories()
    db_manager.configure(settings.database_url)
    db_manager.create_tables()

    from mimir.cache.lru_cache import cache_service, chat_cache_service

    cache_service.invalidate_all()
    chat_cache_service.invalidate_all()

    env = OracleEnv(tmp)
    env._saved_settings = saved_settings
    return env


def _teardown_env(env: OracleEnv) -> None:
    from mimir.cache.lru_cache import cache_service, chat_cache_service

    env.close()
    cache_service.invalidate_all()
    chat_cache_service.invalidate_all()
    for name, value in env._saved_settings.items():
        setattr(settings, name, value)
    db_manager.configure(settings.database_url)
    shutil.rmtree(env.tmp, ignore_errors=True)


@pytest.fixture
def oracle_env():
    """Empty isolated Mimir instance (function scope)."""
    env = _make_env()
    yield env
    _teardown_env(env)


@pytest.fixture(scope="module")
def oracle_corpus_env():
    """Isolated Mimir instance with the fixed corpus ingested (module scope)."""
    env = _make_env()
    env.corpus_ids = env.ingest_corpus()
    yield env
    _teardown_env(env)
