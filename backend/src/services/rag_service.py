"""
RAG pipeline service.

Hosts the full Retrieval-Augmented Generation pipeline (embed -> vector
search -> fuzzy filename pre-include -> dynamic source filter -> confidence
scoring -> LLM generation) as a framework-agnostic RagService class.

Extracted verbatim from backend/src/api/endpoints/chat.py so the
pipeline can be invoked directly -- notably by the RAGAS evaluation
harness -- without going through HTTP. This module imports NOTHING from
FastAPI.
"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime
import asyncio
import logging

import numpy as np
from rapidfuzz import fuzz
from sqlalchemy.exc import SQLAlchemyError

from src.cache.lru_cache import ChatCacheService
from src.database.repository import DocumentRepository
from src.llm_interface.interfaces import AbstractLLMService, EmbeddingResponse
from src.rag_core.interfaces import AbstractVectorStore, LexicalIndex, SearchResult
from src.rag_core.fusion import reciprocal_rank_fusion
from src.monitoring.rag_debug_logger import RagDebugService
from src.cost.budget_guard import BudgetGuard, BudgetReservation
from src.cost.usage_tracker import UsageTracker
from src.config import settings
from src.shared.errors import RetrievalError

logger = logging.getLogger(__name__)

# Candidate pool size requested from each retriever in hybrid mode. Deliberately
# larger than max_sources so RRF has enough ranked candidates to fuse before the
# dedicated hybrid threshold trims the result.
_HYBRID_POOL_SIZE = 50

# System prompt template for RAG context-based responses (moved from chat.py)
MIMIR_SYSTEM_PROMPT = """Vous êtes Mimir, un assistant documentaire intelligent.
Votre rôle est de répondre aux questions en vous basant UNIQUEMENT sur le contexte documentaire fourni.

Règles importantes:
1. Répondez UNIQUEMENT avec les informations présentes dans le contexte
2. Si la réponse n'est pas dans le contexte, dites-le clairement
3. Soyez précis et factuel
4. Utilisez un ton professionnel mais accessible
5. Citez vos sources en utilisant la notation [N], où N correspond exactement au
   numéro affiché devant chaque extrait de contexte ci-dessous. N'inventez jamais
   un numéro de source qui n'existe pas dans le contexte fourni.

Contexte documentaire:
{context}

Répondez à la question suivante en vous basant sur ce contexte:"""

# System prompt used when retrieval returned no relevant context
NO_CONTEXT_SYSTEM_PROMPT = """Vous êtes Mimir, un assistant documentaire intelligent.
L'utilisateur vous pose une question mais aucun contexte pertinent n'a été trouvé dans la documentation."""

# Generation parameters of the RAG answer
_ANSWER_MAX_TOKENS = 800
_ANSWER_TEMPERATURE = 0.1

# Client-facing message of the SSE error event (details stay in the logs)
_STREAM_ERROR_MESSAGE = "Une erreur interne est survenue."


def _clean_filename(filename: str) -> str:
    """
    Clean the filename to extract a human-readable name.
    Removes the hash, extension and underscores.

    Example: "2e821c8cd63bcacaca47f4f52576ff08fadbad66dde9e359a3fbae80da79a818_CV_Yann_POINTUD.pdf"
            -> "CV Yann POINTUD"
    """
    import os

    # Remove the path if present
    filename = os.path.basename(filename)

    # Remove the extension
    filename = os.path.splitext(filename)[0]

    # Remove the hash (64 hex characters at the beginning)
    if "_" in filename and len(filename.split("_")[0]) == 64:
        filename = "_".join(filename.split("_")[1:])

    # Replace underscores with spaces
    filename = filename.replace("_", " ")

    return filename.strip()


def _find_documents_by_fuzzy_match(
    question: str, document_repository, threshold: int = 70
) -> list[tuple]:
    """Find documents whose filename matches the question via fuzzy matching.

    ``threshold`` is the minimum fuzzy score (0-100).

    Returns:
        List of tuples (document_id, filename, fuzzy_score)
    """
    all_documents = document_repository.get_all()
    matches = []

    for doc in all_documents:
        # Clean the filename
        clean_name = _clean_filename(doc.filename)

        # Calculate the fuzzy matching score
        fuzzy_score = fuzz.partial_ratio(question.lower(), clean_name.lower())

        if fuzzy_score >= threshold:
            matches.append((doc.id, doc.filename, fuzzy_score))
            logger.info(
                f"Fuzzy match found: '{clean_name}' (score: {fuzzy_score}) for question: '{question}'"
            )

    # Sort by descending score
    matches.sort(key=lambda x: x[2], reverse=True)

    return matches


async def _pre_include_document_chunks(
    document_ids: list[int],
    question_embedding: np.ndarray,
    vector_store,
    document_repository,
    boost_factor: float,
    filename_similarities: dict[int, float],
) -> list[Any]:
    """Retrieve all chunks from specified documents and apply the boost.

    ``filename_similarities`` maps each document_id to its fuzzy score.
    Returns the chunks with boosted scores.
    """
    pre_included_chunks = []

    for doc_id in document_ids:
        # Retrieve the document
        document = document_repository.get_by_id(doc_id)
        if not document:
            continue

        # Retrieve all chunks for this document from FAISS
        # Perform a search with a very large top_k and filter by document_id
        all_results = await asyncio.to_thread(vector_store.query, question_embedding, top_k=1000)

        # Filter to keep only chunks from this document
        doc_chunks = [r for r in all_results if int(r.document_id) == doc_id]

        # Apply boost to each chunk
        filename_similarity = filename_similarities.get(doc_id, 0) / 100.0  # Normalize 0-1

        for chunk in doc_chunks:
            # Calculate boost based on filename similarity
            original_score = chunk.similarity_score
            boost_amount = boost_factor * filename_similarity
            boosted_score = chunk.similarity_score + boost_amount
            boosted_score = min(0.99, boosted_score)

            # Update the score
            chunk.similarity_score = boosted_score
            pre_included_chunks.append(chunk)

            # Report the true pre-boost score: chunk.similarity_score has already
            # been reassigned to the (possibly clamped) boosted value, so it can
            # no longer be reversed by subtracting boost_amount.
            logger.debug(
                f"Pre-included chunk: doc_id={doc_id}, chunk_index={chunk.chunk_index}, "
                f"score_original={original_score:.3f}, "
                f"boost={boost_amount:.3f}, score_final={boosted_score:.3f}"
            )

    return pre_included_chunks


def _calculate_rrf_confidence(search_results: list[Any], rrf_k: int = 60) -> float:
    """Confidence for hybrid (RRF) mode -- rank/consensus based.

    RRF scores are NOT cosine similarities, so the weighted-magnitude formula
    used in dense mode does not apply. A chunk retrieved by BOTH the dense and
    lexical retrievers accumulates two 1/(k+rank) contributions, so its fused
    magnitude already encodes cross-retriever consensus. Confidence is the best
    fused score normalized by the theoretical two-retriever top-rank maximum
    (2/(k+1) -- both retrievers ranking it #1), lightly boosted by how many
    corroborating results agree, capped at 0.95 like the dense algorithm.

    Args:
        search_results: Fused search results (similarity_score = RRF score).
        rrf_k: RRF damping constant used during fusion.

    Returns:
        Confidence score between 0.0 and 0.95.
    """
    if not search_results:
        return 0.1

    scores = [r.similarity_score for r in search_results]
    best = max(scores)
    max_possible = 2.0 / (rrf_k + 1)  # both retrievers rank the chunk #1
    consensus = min(1.0, best / max_possible) if max_possible > 0 else 0.0
    # Support factor: more corroborating results -> slightly higher confidence.
    support = min(1.0, len(scores) / 5.0)
    confidence = min(0.95, consensus * 0.8 + support * 0.15)

    logger.debug(
        f"RRF confidence: best={best:.4f}, max_possible={max_possible:.4f}, "
        f"consensus={consensus:.3f}, support={support:.3f}, final={confidence:.3f}"
    )
    return confidence


def _merge_and_attach_rrf_scores(
    dense_pool: list[Any],
    extra_results: list[Any],
    fused_scores: dict[int, float],
    vector_store: AbstractVectorStore,
) -> list[Any]:
    """Build a unified SearchResult list carrying fused RRF scores.

    Dense hits are already SearchResult objects; chunk_ids known only to BM25
    (or to a fuzzy pre-inclusion list) are reconstructed from the FAISS metadata
    -- the single source of truth. Every result's similarity_score is REPLACED by
    its fused RRF score so the downstream hybrid-mode filter/confidence operate on
    rank scores rather than incompatible cosine magnitudes.

    Args:
        dense_pool: Raw dense SearchResult candidates (similarity_floor=0.0).
        extra_results: Additional SearchResult objects usable for reconstruction
            (e.g. filename pre-included chunks); may be empty.
        fused_scores: chunk_id -> fused RRF score from reciprocal_rank_fusion.
        vector_store: Source of FAISS metadata for lexical-only chunk_ids.

    Returns:
        SearchResult list sorted by descending fused score.
    """
    by_id: dict[int, Any] = {}
    for r in dense_pool:
        by_id.setdefault(r.chunk_id, r)
    for r in extra_results or []:
        by_id.setdefault(r.chunk_id, r)

    # chunk_id -> metadata dict of the non-deleted FAISS entries.
    meta_by_id: dict[int, dict[str, Any]] = {
        meta["chunk_id"]: meta for meta in vector_store.snapshot_active_chunks()
    }

    merged: list[Any] = []
    for chunk_id, rrf_score in fused_scores.items():
        existing = by_id.get(chunk_id)
        if existing is not None:
            existing.similarity_score = rrf_score
            merged.append(existing)
            continue
        meta = meta_by_id.get(chunk_id)
        if meta is None:
            # chunk_id known to BM25 but absent from FAISS metadata (index
            # drift) -- cannot reconstruct a source, skip it.
            continue
        merged.append(
            SearchResult(
                chunk_id=meta["chunk_id"],
                document_id=meta["document_id"],
                text=meta["text"],
                source=meta["source"],
                similarity_score=rrf_score,
                chunk_index=meta["chunk_index"],
                total_chunks=meta["total_chunks"],
                metadata=meta.get("metadata", {}),
            )
        )

    merged.sort(key=lambda x: x.similarity_score, reverse=True)
    return merged


def _calculate_weighted_confidence(
    search_results: list[Any],
    algorithm: str = "weighted",
    mode: str = "dense",
    rrf_k: int = 60,
) -> float:
    """
    Calculate confidence score using different algorithms.

    Args:
        search_results: List of search results
        algorithm: "simple" or "weighted"
        mode: "dense" (cosine magnitude, unchanged) or "hybrid" (RRF
            rank/consensus based -- delegates to _calculate_rrf_confidence)
        rrf_k: RRF damping constant, only used when mode == "hybrid"

    Returns:
        Confidence score between 0.0 and 0.95
    """
    if mode == "hybrid":
        return _calculate_rrf_confidence(search_results, rrf_k)

    if not search_results:
        return 0.1

    scores = [r.similarity_score for r in search_results]

    if algorithm == "simple":
        # Original algorithm (for backward compatibility)
        avg_similarity = sum(scores) / len(scores)
        return min(0.9, avg_similarity * (len(search_results) / 5))

    elif algorithm == "weighted":
        # Improved algorithm with degressive weighting

        # Position-weighting assumes a descending-score order. Sort defensively so
        # the metric stays order-agnostic: on the retrieval path the list is
        # already sorted, so this is a no-op (byte-identical); the sort only guards
        # the scoring against any future caller that would pass an unsorted list. The
        # coherence and quality factors below use max()/std() and are already
        # order-independent.
        scores = sorted(scores, reverse=True)

        # 1. Position-weighted score (first results count more)
        weights = [1.0, 0.8, 0.6, 0.4, 0.2]  # Degressive weighting
        weighted_sum = sum(
            score * weights[min(i, len(weights) - 1)] for i, score in enumerate(scores)
        )
        weight_total = sum(weights[: min(len(scores), len(weights))])
        base_score = weighted_sum / weight_total

        # 2. Coherence factor (penalizes highly dispersed scores)
        if len(scores) > 1:
            std_dev = np.std(scores)
            max_score = max(scores)
            # High coherence if standard deviation is low relative to max
            coherence_factor = max(0.5, 1 - (std_dev / max(max_score, 0.1)))
        else:
            coherence_factor = 1.0

        # 3. Quality factor (bonus if the best score is really good)
        best_score = max(scores)
        quality_bonus = 1.0
        if best_score > 0.9:
            quality_bonus = 1.2
        elif best_score > 0.8:
            quality_bonus = 1.1

        # 4. Combined final score
        confidence = min(
            0.95,
            base_score * 0.7  # 70% weighted score
            + coherence_factor * 0.2  # 20% coherence
            + (best_score * 0.1)  # 10% best result quality
            * quality_bonus,
        )

        logger.debug(
            f"Confidence computed: base={base_score:.3f}, coherence={coherence_factor:.3f}, "
            f"quality={quality_bonus:.3f}, final={confidence:.3f}"
        )

        return confidence

    else:
        # Fallback to the simple algorithm
        logger.warning(f"Unknown algorithm '{algorithm}', falling back to 'simple'")
        return _calculate_weighted_confidence(search_results, "simple")


def _filter_dynamic_sources(
    search_results: list[Any], config: Any, question: str = "", mode: str = "dense"
) -> list[Any]:
    """
    Dynamically filter sources based on relevance with gap detection.

    Args:
        search_results: List of search results (sorted by descending score)
        config: Configuration with similarity_threshold, min_sources, max_sources
        question: Question for named entity detection
        mode: "dense" (cosine similarity_threshold floor, unchanged) or "hybrid"
            (RRF rank scores -- use config.rrf_score_threshold, NEVER the cosine
            0.5 floor: RRF scores are far below it and would all be filtered out)

    Returns:
        Filtered list of relevant sources
    """
    if not search_results:
        return []

    scores = [r.similarity_score for r in search_results]
    best_score = scores[0]

    logger.debug(f"Dynamic filtering - Scores: {[f'{s:.3f}' for s in scores[:8]]}")

    # Dynamic filtering based on gap from the best score
    # Threshold = max(FLOOR, best_score x (1 - DYNAMIC_FILTER_PERCENTAGE))
    # where FLOOR is the cosine similarity_threshold in dense mode and the
    # dedicated rrf_score_threshold in hybrid mode. Using the cosine floor on RRF
    # scores (~0.033 peak at k=60) would always wipe the whole result set.
    dynamic_threshold = best_score * (1 - config.dynamic_filter_percentage)
    if mode == "hybrid":
        final_threshold = max(config.rrf_score_threshold, dynamic_threshold)
        method = f"hybrid@{final_threshold:.4f}"
    else:
        final_threshold = max(config.similarity_threshold, dynamic_threshold)
        method = f"dynamic@{final_threshold:.3f}"
    filtered_results = [r for r in search_results if r.similarity_score >= final_threshold]

    logger.debug(
        f"Dynamic filtering: best={best_score:.3f}, gap={config.dynamic_filter_percentage:.2f}, "
        f"threshold={final_threshold:.3f}, {len(search_results)} → {len(filtered_results)} chunks"
    )

    # 4. Enforce min/max constraints
    original_count = len(filtered_results)

    if len(filtered_results) < config.min_sources:
        filtered_results = search_results[: config.min_sources]
        method += f"→min({config.min_sources})"
    elif len(filtered_results) > config.max_sources:
        filtered_results = filtered_results[: config.max_sources]
        method += f"→max({config.max_sources})"

    # 5. Detailed filtering log
    logger.info(
        f"Dynamic sources: {len(search_results)} → {len(filtered_results)} sources "
        f"(method: {method})"
    )

    if len(filtered_results) != original_count:
        logger.debug(f"Constraint adjustment: {original_count} → {len(filtered_results)}")

    return filtered_results


async def _hybrid_retrieve(
    question: str,
    question_embedding: np.ndarray,
    vector_store: AbstractVectorStore,
    bm25_store: LexicalIndex,
    pre_included_chunks: list[Any],
    rag_debug: RagDebugService,
    session_id: str,
    embedding_tokens: Any,
) -> list[Any]:
    """Run the hybrid retrieval branch: dense raw pool + BM25, fused via RRF.

    The dense pool is fetched with similarity_floor=0.0 (raw ranking, so the
    cosine threshold does not truncate it before fusion);
    the BM25 pool comes from the lexical store. Filename pre-included chunks, when
    present, are folded in as a THIRD ranked retriever so their signal stays on
    the RRF scale (mixing their raw cosine boost scores into RRF scores would
    reintroduce the threshold-wipeout pitfall). All blocking store calls go
    through asyncio.to_thread, like the dense path.

    Returns:
        Unified SearchResult list with fused RRF scores (unsorted filtering is
        applied by the caller via _filter_dynamic_sources(mode="hybrid")).
    """
    logger.info("Hybrid retrieval enabled: fusing dense + BM25 pools via RRF")
    start_search = datetime.utcnow()

    dense_pool = await asyncio.to_thread(
        vector_store.query,
        vector=question_embedding,
        top_k=_HYBRID_POOL_SIZE,
        filter_dict=None,
        similarity_floor=0.0,
    )
    # Graceful degradation (milestone prime directive: never break the working
    # engine). The BM25 index is only built at ingestion/deletion; on a cold
    # start or an upgrade of an existing FAISS install it may not exist yet, and
    # bm25_store.query() would raise. In that case fall back to dense-only for
    # this query rather than let the exception break an otherwise-working engine.
    try:
        lexical_pool = await asyncio.to_thread(bm25_store.query, question, _HYBRID_POOL_SIZE)
    except RetrievalError as e:
        logger.warning(
            f"BM25 lexical retrieval unavailable ({e}); degrading to dense-only for this query"
        )
        lexical_pool = []

    rank_lists = [
        [r.chunk_id for r in dense_pool],
        [chunk_id for chunk_id, _ in lexical_pool],
    ]
    if pre_included_chunks:
        rank_lists.append([c.chunk_id for c in pre_included_chunks])

    fused_scores = reciprocal_rank_fusion(rank_lists, k=settings.rrf_k)
    search_results = _merge_and_attach_rrf_scores(
        dense_pool, pre_included_chunks, fused_scores, vector_store
    )

    search_time = (datetime.utcnow() - start_search).total_seconds() * 1000
    logger.info(
        f"Hybrid fusion: dense={len(dense_pool)}, lexical={len(lexical_pool)}, "
        f"fused={len(search_results)} candidates"
    )

    rag_debug.log_vector_search(
        session_id=session_id,
        search_results=search_results,
        embedding_tokens=embedding_tokens,
        search_time_ms=search_time,
    )

    return search_results


@dataclass
class _QuestionSpend:
    """Euro cost of the LLM calls made while answering one question."""

    usage_tracker: UsageTracker | None
    session_id: str
    total_eur: float = 0.0
    llm_call_made: bool = False

    async def record(
        self,
        call_type: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated: bool,
    ) -> None:
        """Price and persist one call (no-op without a usage tracker)."""
        if self.usage_tracker is None:
            return
        # asyncio.to_thread: record() is a blocking SQLite write.
        self.total_eur += await asyncio.to_thread(
            self.usage_tracker.record,
            call_type,
            model,
            prompt_tokens,
            completion_tokens,
            estimated=estimated,
            session_id=self.session_id,
        )

    async def settle(
        self, budget_guard: BudgetGuard | None, reservation: BudgetReservation | None
    ) -> None:
        """Finalize the reservation with the real cost, or release it if no call was made."""
        if budget_guard is None or reservation is None:
            return
        # asyncio.to_thread keeps the blocking SQLite ledger write off the
        # event loop.
        if self.llm_call_made:
            await asyncio.to_thread(budget_guard.finalize, reservation, self.total_eur)
        else:
            await asyncio.to_thread(budget_guard.release, reservation)


@dataclass
class _AnswerContext:
    """Numbered context passages and the matching source references."""

    passages: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)

    @property
    def citations(self) -> dict[str, dict[str, Any]]:
        """[N] -> source map, derived from the numbering of the prompt passages."""
        return {str(i + 1): source for i, source in enumerate(self.sources)}


async def _embed_question(
    question: str,
    llm_service: AbstractLLMService,
    rag_debug: RagDebugService,
    spend: _QuestionSpend,
) -> tuple[np.ndarray, EmbeddingResponse]:
    """Step 1: embed the question and record the embedding cost."""
    logger.info("Generating embeddings for streaming question")
    response = await llm_service.embed([question], session_id=spend.session_id, rag_debug=rag_debug)
    question_embedding = np.array(response.embeddings[0], dtype=np.float32)

    spend.llm_call_made = True
    await spend.record(
        "embedding",
        response.model,
        response.prompt_tokens,
        response.completion_tokens,
        estimated=False,
    )
    return question_embedding, response


async def _pre_include_by_filename(
    question: str,
    question_embedding: np.ndarray,
    vector_store: AbstractVectorStore,
    document_repository: DocumentRepository,
) -> list[Any]:
    """Step 1.5: boost every chunk of the documents whose filename matches the question."""
    if not settings.filename_pre_inclusion:
        return []

    matched_docs = _find_documents_by_fuzzy_match(
        question, document_repository, threshold=settings.filename_fuzzy_threshold
    )
    if not matched_docs:
        return []

    return await _pre_include_document_chunks(
        document_ids=[doc_id for doc_id, _, _ in matched_docs],
        question_embedding=question_embedding,
        vector_store=vector_store,
        document_repository=document_repository,
        boost_factor=settings.filename_boost,
        filename_similarities={doc_id: score for doc_id, _, score in matched_docs},
    )


async def _dense_retrieve(
    question_embedding: np.ndarray,
    vector_store: AbstractVectorStore,
    pre_included_chunks: list[Any],
    rag_debug: RagDebugService,
    session_id: str,
    embedding_tokens: int,
) -> list[Any]:
    """Step 2, dense mode: cosine search, then merge the pre-included chunks."""
    start_search = datetime.utcnow()
    search_results = await asyncio.to_thread(
        vector_store.query,
        vector=question_embedding,
        top_k=settings.max_sources * 2,
        filter_dict=None,
    )
    search_time = (datetime.utcnow() - start_search).total_seconds() * 1000

    rag_debug.log_vector_search(
        session_id=session_id,
        search_results=search_results,
        embedding_tokens=embedding_tokens,
        search_time_ms=search_time,
    )

    if pre_included_chunks:
        pre_included_ids = {chunk.chunk_id for chunk in pre_included_chunks}
        unique_vector_results = [r for r in search_results if r.chunk_id not in pre_included_ids]
        search_results = pre_included_chunks + unique_vector_results
        search_results.sort(key=lambda x: x.similarity_score, reverse=True)

    return search_results


async def _retrieve(
    question: str,
    question_embedding: np.ndarray,
    embedding_tokens: int,
    vector_store: AbstractVectorStore,
    bm25_store: LexicalIndex | None,
    pre_included_chunks: list[Any],
    rag_debug: RagDebugService,
    session_id: str,
) -> tuple[list[Any], str]:
    """Step 2: hybrid or dense retrieval, then dynamic source filtering.

    Returns:
        The filtered results and the retrieval mode ("hybrid" or "dense").
    """
    if settings.hybrid_search_enabled and bm25_store is not None:
        retrieval_mode = "hybrid"
        search_results = await _hybrid_retrieve(
            question=question,
            question_embedding=question_embedding,
            vector_store=vector_store,
            bm25_store=bm25_store,
            pre_included_chunks=pre_included_chunks,
            rag_debug=rag_debug,
            session_id=session_id,
            embedding_tokens=embedding_tokens,
        )
    else:
        retrieval_mode = "dense"
        search_results = await _dense_retrieve(
            question_embedding,
            vector_store,
            pre_included_chunks,
            rag_debug,
            session_id,
            embedding_tokens,
        )

    if search_results:
        search_results = _filter_dynamic_sources(
            search_results, settings, question, mode=retrieval_mode
        )
    return search_results, retrieval_mode


def _load_source_documents(
    search_results: list[Any], document_repository: DocumentRepository
) -> dict[int, Any]:
    """Load every distinct source document in one query.

    Avoids one get_by_id() per chunk (chunks frequently share a document). Any
    database error degrades to the chunk source names.
    """
    try:
        return document_repository.get_by_ids(list({int(r.document_id) for r in search_results}))
    except (ValueError, SQLAlchemyError):
        return {}


def _build_context(
    search_results: list[Any], include_sources: bool, document_repository: DocumentRepository
) -> _AnswerContext:
    """Step 3: numbered passages and source references, from one single ordering.

    Building both in the same enumerate() pass keeps the [N] citation map from
    drifting away from the numbering of the prompt.
    """
    context = _AnswerContext()
    if not search_results:
        return context

    documents_by_id = (
        _load_source_documents(search_results, document_repository) if include_sources else {}
    )
    for i, result in enumerate(search_results, start=1):
        context.passages.append(f"[{i}] {result.text}")

        if include_sources:
            document = documents_by_id.get(int(result.document_id))
            filename = document.filename if document else str(result.source)
            context.sources.append(
                {
                    "document_id": int(result.document_id),
                    "filename": filename,
                    "chunk_text": result.text,
                    "similarity_score": float(round(result.similarity_score, 3)),
                    "chunk_index": int(result.chunk_index),
                    "total_chunks": int(result.total_chunks),
                }
            )
    return context


def _build_prompt(passages: list[str]) -> tuple[str, str, str]:
    """Step 4: system prompt template, context text and the final system prompt."""
    if passages:
        context_text = "\n\n".join(passages)
        return MIMIR_SYSTEM_PROMPT, context_text, MIMIR_SYSTEM_PROMPT.format(context=context_text)

    logger.warning("No relevant context found")
    return NO_CONTEXT_SYSTEM_PROMPT, "", NO_CONTEXT_SYSTEM_PROMPT


async def _stream_answer(
    question: str,
    full_prompt: str,
    llm_service: AbstractLLMService,
    rag_debug: RagDebugService,
    spend: _QuestionSpend,
    answer_parts: list[str],
) -> AsyncGenerator[dict[str, Any]]:
    """Step 5: stream the answer as chunk events and record exactly one chat usage row.

    The real usage is recorded when the provider reports it at the end of the
    stream. Otherwise -- no usage chunk, an error, or a client disconnect
    (GeneratorExit) -- the tokens are estimated from the text lengths in the
    finally block. The prompt side is estimated too: the provider bills the
    whole prompt even for an interrupted stream, and the document context is
    usually the dominant share of the billed tokens. Awaiting (no yield) in an
    async generator's finally is legal during aclose().
    """
    logger.info("Starting streaming LLM generation...")
    usage_out: dict[str, Any] = {}
    chat_usage_recorded = False
    try:
        async for chunk in llm_service.generate_stream(
            prompt=question,
            system_prompt=full_prompt,
            max_tokens=_ANSWER_MAX_TOKENS,
            temperature=_ANSWER_TEMPERATURE,
            session_id=spend.session_id,
            rag_debug=rag_debug,
            usage_out=usage_out,
        ):
            answer_parts.append(chunk)
            yield {"type": "chunk", "content": chunk}

        if spend.usage_tracker is not None and usage_out:
            await spend.record(
                "chat",
                llm_service.model_name,
                usage_out.get("prompt_tokens", 0),
                usage_out.get("completion_tokens", 0),
                estimated=False,
            )
            chat_usage_recorded = True
    finally:
        if spend.usage_tracker is not None and not chat_usage_recorded:
            full_answer = "".join(answer_parts)
            await spend.record(
                "chat",
                llm_service.model_name,
                max(1, (len(full_prompt) + len(question)) // 4),
                max(1, len(full_answer) // 4),
                estimated=True,
            )


def _cache_answer(
    chat_cache: ChatCacheService | None,
    corpus_version: str | None,
    question: str,
    answer: str,
    context: _AnswerContext,
    confidence_score: float,
) -> None:
    """Store a fully streamed answer in the corpus-aware SSE cache."""
    if chat_cache is None or corpus_version is None:
        return
    chat_cache.set_stream_response(
        question,
        corpus_version,
        {
            "answer": answer,
            "sources": context.sources,
            "citations": context.citations,
            "confidence_score": float(round(confidence_score, 2)),
        },
    )


async def _process_question_with_rag_stream(
    question: str,
    context_limit: int | None,
    include_sources: bool,
    session_id: str,
    llm_service: AbstractLLMService,
    vector_store: AbstractVectorStore,
    document_repository: DocumentRepository,
    rag_debug: RagDebugService,
    budget_guard: BudgetGuard | None = None,
    usage_tracker: UsageTracker | None = None,
    reservation: BudgetReservation | None = None,
    chat_cache: ChatCacheService | None = None,
    corpus_version: str | None = None,
    bm25_store: LexicalIndex | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Answer a question with the streaming RAG pipeline, yielding SSE event dicts.

    Events: one "chunk" per generated text chunk, then "citation" and "done";
    or "error" if any step fails.

    The reservation is settled in the outermost finally: a mid-stream client
    disconnect throws GeneratorExit -- a BaseException, not caught by the
    except clause -- straight through this generator, and only that finally
    runs in every case (completion, error or disconnect).
    """
    spend = _QuestionSpend(usage_tracker=usage_tracker, session_id=session_id)
    try:
        question_embedding, embedding_response = await _embed_question(
            question, llm_service, rag_debug, spend
        )
        pre_included_chunks = await _pre_include_by_filename(
            question, question_embedding, vector_store, document_repository
        )
        search_results, retrieval_mode = await _retrieve(
            question,
            question_embedding,
            embedding_response.usage_tokens,
            vector_store,
            bm25_store,
            pre_included_chunks,
            rag_debug,
            session_id,
        )
        context = _build_context(search_results, include_sources, document_repository)
        system_prompt, context_text, full_prompt = _build_prompt(context.passages)
        rag_debug.log_context_building(
            session_id=session_id,
            system_prompt=system_prompt,
            context_text=context_text,
            context_chunks=len(context.passages),
            filtered_sources=context.sources,
        )

        # aclosing(): on a client disconnect the answer stream is closed (and
        # its usage recorded) before this generator settles the reservation.
        answer_parts: list[str] = []
        async with aclosing(
            _stream_answer(question, full_prompt, llm_service, rag_debug, spend, answer_parts)
        ) as answer_stream:
            async for event in answer_stream:
                yield event

        confidence_score = _calculate_weighted_confidence(
            search_results, settings.confidence_algorithm, mode=retrieval_mode, rrf_k=settings.rrf_k
        )

        # The citation map travels in its own event so the "done" payload
        # keeps the shape the frontend already consumes.
        yield {"type": "citation", "citations": context.citations}
        yield {
            "type": "done",
            "sources": context.sources,
            "confidence_score": float(round(confidence_score, 2)),
            "cached": False,
        }

        logger.info(f"Streaming RAG completed - confidence: {confidence_score:.2f}")

        # Written only here, after the done event: never in the except branch
        # (errors are not cached) nor in a finally (which also runs on a
        # disconnect). The write performs no await, so a GeneratorExit cannot
        # interrupt it once the done event has been consumed.
        _cache_answer(
            chat_cache, corpus_version, question, "".join(answer_parts), context, confidence_score
        )

    except Exception as e:  # noqa: BLE001 - SSE boundary: any failure becomes an error event
        logger.error(f"Streaming RAG pipeline failed: {str(e)}", exc_info=True)
        rag_debug.log_error(
            session_id=session_id,
            error_type=type(e).__name__,
            error_message=str(e),
            stage="streaming_rag_pipeline",
        )
        yield {"type": "error", "message": _STREAM_ERROR_MESSAGE}

    finally:
        await spend.settle(budget_guard, reservation)


class RagService:
    """
    Framework-agnostic RAG pipeline service.

    Constructed once through dependency injection (see
    ``src/api/dependencies.py::get_rag_service``) and usable outside an HTTP
    request, notably by the RAGAS evaluation harness, which drains
    answer_stream() into a result dict.

    document_repository is a per-call argument of answer_stream(), not an
    attribute: it wraps a request-scoped SQLAlchemy session that must not leak
    across requests.
    """

    def __init__(
        self,
        llm_service: AbstractLLMService,
        vector_store: AbstractVectorStore,
        rag_debug: RagDebugService,
        budget_guard: BudgetGuard | None = None,
        usage_tracker: UsageTracker | None = None,
        chat_cache: ChatCacheService | None = None,
        bm25_store: LexicalIndex | None = None,
    ):
        self.llm_service = llm_service
        self.vector_store = vector_store
        self.rag_debug = rag_debug
        self.budget_guard = budget_guard
        self.usage_tracker = usage_tracker
        self.chat_cache = chat_cache
        # Lexical index of hybrid retrieval; ignored when
        # settings.hybrid_search_enabled is False.
        self.bm25_store = bm25_store

    async def answer_stream(
        self,
        question: str,
        context_limit: int | None,
        include_sources: bool,
        session_id: str,
        document_repository: DocumentRepository,
        reservation: BudgetReservation | None = None,
        corpus_version: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Answer one question, yielding the SSE event dicts of the pipeline.

        The reservation is always settled, including on a mid-stream
        disconnect. When corpus_version is given and the service has a chat
        cache, a fully successful answer is cached after the done event.
        """
        async for event in _process_question_with_rag_stream(
            question=question,
            context_limit=context_limit,
            include_sources=include_sources,
            session_id=session_id,
            llm_service=self.llm_service,
            vector_store=self.vector_store,
            document_repository=document_repository,
            rag_debug=self.rag_debug,
            budget_guard=self.budget_guard,
            usage_tracker=self.usage_tracker,
            reservation=reservation,
            chat_cache=self.chat_cache,
            corpus_version=corpus_version,
            bm25_store=self.bm25_store,
        ):
            yield event
