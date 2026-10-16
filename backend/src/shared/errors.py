"""
Domain exceptions shared by every Mimir layer.

Each family matches one stage of the RAG pipeline. Infrastructure failures
(file system, FAISS, BM25, SQLite, Mistral HTTP calls) are translated into
these families where they occur, so callers only handle domain errors; the
FastAPI application translates any of them that escapes a route into an HTTP
response (see ``main.py``).
"""


class MimirError(Exception):
    """Base class of every domain error raised by Mimir."""


class IngestionError(MimirError):
    """A document could not be extracted, chunked or indexed."""


class RetrievalError(MimirError):
    """A retrieval index (FAISS or BM25) could not be read or updated."""


class LLMError(MimirError):
    """The language model provider failed or rejected a request."""


class BudgetExceeded(MimirError):
    """The daily AI spending cap is exhausted.

    BudgetGuard.reserve() never raises it (it returns None so HTTP routes can
    answer 429 themselves); callers outside a request, such as the ingestion
    worker, raise it to stop without retrying.
    """
